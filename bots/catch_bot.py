import discord
import random
import asyncio
import json
import os
from discord.ext import tasks, commands
from dotenv import load_dotenv

from core.tx_utils import (
    safe_append_tx,
    get_nonce,
    get_effective_balance
)

# Nonce lock for send_tip
nonce_lock = asyncio.Lock()

load_dotenv()
FISHING_BOT_ID = os.getenv("FISHING_BOT_ID")


FISH_CHANNELS = {}
raw_channel_data = os.getenv("FISH_CHANNELS", "")

for entry in raw_channel_data.split(","):
    if ":" in entry:
        cid, chance = entry.split(":")
        try:
            cid_int = int(cid.strip())
            chance_int = int(chance.strip())
            FISH_CHANNELS[cid_int] = chance_int
        except ValueError:
            print(f"[WARN] Invalid FISH_CHANNELS entry: {entry}")

FISH_CHANNEL_IDS = list(FISH_CHANNELS.keys())
treasury = FISHING_BOT_ID

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEADERBOARD_FILE = os.path.join(os.path.dirname(BASE_DIR), "data", "fish_leaderboard.json")
FISH_IMAGES_DIR = os.path.join(BASE_DIR, "fish_images")

fish_pool = [
    ("Common Carp", (5, 15), 505),
    ("Mirror Carp", (12, 25), 180),
    ("Grass Carp", (15, 35), 80),
    ("Ghost Carp", (6, 15), 60),
    ("Leather Carp", (12, 25), 50),
    ("Siamese Giant Carp", (50, 120), 5),
    ("Koi Carp", (4, 10), 10),
    ("Crucian Carp", (2, 6), 40),
    ("Prussian Carp", (2, 6), 40),
    ("Goldfish", (1, 2), 20),
    ("F1 Carp", (3, 9), 10)
]
types, ranges, weights = zip(*fish_pool)
range_dict = dict(zip(types, ranges))

if os.path.exists(LEADERBOARD_FILE):
    with open(LEADERBOARD_FILE) as f:
        leaderboard = json.load(f)
else:
    leaderboard = {}

# Cooldown tracking for catching fish
last_catch_time = {}
# Cooldown settings
BASE_CATCH_COOLDOWN = 60 * 60        # 60 minutes default
BAIT_CATCH_COOLDOWN = 10 * 60        # 10 minutes for bait user

bait_boost = {}  # channel_id -> (boost_factor, expiry_time, caster_id)


# Return the current boost factor if active, otherwise 1
def get_boost_factor(channel_id):
    boost_factor, expiry, *_ = bait_boost.get(channel_id, (1, 0))
    if asyncio.get_event_loop().time() > expiry:
        return 1
    return boost_factor


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


# !help command
@bot.command(name="help")
async def help_command(ctx):
    msg = (
        "🎣 **Fishing Bot Commands**\n\n"
        "- `!leaderboard` – Show the top 10 fishers in this channel\n"
        "- `!bait corn` – Use corn (200 BOILIES) to quadruple the spawn rate for 1 hour\n"
        "- `!bait boilie` – Use boilie (1000 BOILIES) to boost the spawn rate eightfold for 2 hours\n"
        "- `!baitstatus` – Show current bait effect in this channel\n\n"
        "Just wait for fish to appear and be the first to click **🎣 Catch!**\n"
        "The heavier the fish, the more BOILIES you earn.\n\n"
        "⏳ Cooldown: 60 minutes after catching a fish – or only 10 minutes if you're the one who cast the bait!"
    )
    await ctx.send(msg)

last_fish_message = {}
last_fish_view = {}


class CatchView(discord.ui.View):
    def __init__(self, reward, fish_type, weight, channel_id):
        super().__init__()
        self.reward = reward
        self.claimed = False
        self.fish_type = fish_type
        self.weight = weight
        self.channel_id = channel_id
        self.timeout = 900  # 15 minutes timeout to keep Discord button interaction alive
        self.caught_by = None  # initialized here to avoid IDE warnings
        self.caught_by_name = None # initialized here to avoid IDE warnings

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await last_fish_message[self.channel_id].edit(view=self)
        except Exception as e:
            print(f"[WARN] Failed to disable catch button after timeout: {e}")

    @discord.ui.button(label="🎣 Catch!", style=discord.ButtonStyle.primary)
    async def catch_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        now = asyncio.get_event_loop().time()
        user_id = str(interaction.user.id)
        if self.channel_id not in last_catch_time:
            last_catch_time[self.channel_id] = {}
        if user_id in last_catch_time[self.channel_id]:
            elapsed = now - last_catch_time[self.channel_id][user_id]
            boost = bait_boost.get(self.channel_id)
            is_bait_caster = (
                boost and
                len(boost) > 2 and
                boost[2] == str(interaction.user.id) and
                asyncio.get_event_loop().time() < boost[1]
            )
            cooldown = BAIT_CATCH_COOLDOWN if is_bait_caster else BASE_CATCH_COOLDOWN
            if elapsed < cooldown:
                remaining = int((cooldown - elapsed) // 60)
                message = f"⏳ You've already caught a fish recently. Try again in {remaining} minutes."
                if interaction.response.is_done():
                    await interaction.followup.send(message, ephemeral=True)
                else:
                    await interaction.response.send_message(message, ephemeral=True)
                return
        if self.claimed:
            message = f"🐟 This fish was already caught by **{self.caught_by_name}**, weighing **{self.weight} lbs**. Enter !leaderboard to see the top 10 anglers."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return

        self.claimed = True
        self.caught_by = str(interaction.user.id)
        self.caught_by_name = str(interaction.user.display_name)
        effective = get_effective_balance(FISHING_BOT_ID)
        if effective < self.reward:
            await interaction.response.send_message("❌ Insufficient BOILIES.", ephemeral=True)
            return

        # Transaction-based BOILIE award (via safe_append_tx)
        nonce = get_nonce(FISHING_BOT_ID)
        tx = {
            "type": "reward",
            "user_id": FISHING_BOT_ID,
            "username": "Fishing Bot",
            "to": self.caught_by,
            "to_username": str(interaction.user),
            "amount": self.reward,
            "nonce": nonce
        }
        if not safe_append_tx(tx):
            await interaction.response.send_message("⚠️ Reward transaction already in mempool.", ephemeral=True)
            return

        # Update leaderboard and cooldown
        channel_id_str = str(self.channel_id)
        name = str(interaction.user.display_name)
        if channel_id_str not in leaderboard:
            leaderboard[channel_id_str] = {}
        leaderboard[channel_id_str][name] = leaderboard[channel_id_str].get(name, 0) + self.reward
        with open(LEADERBOARD_FILE, "w") as f:
            json.dump(leaderboard, f, indent=2)

        # Set cooldown for this user
        last_catch_time[self.channel_id][user_id] = now

        # Show ephemeral message to the catching user
        if interaction.response.is_done():
            await interaction.followup.send(f"🐟 You caught a **{self.fish_type}** weighing **{self.weight} lbs** and earned **{self.reward} BOILIES**!", ephemeral=True)
        else:
            await interaction.response.send_message(f"🐟 You caught a **{self.fish_type}** weighing **{self.weight} lbs** and earned **{self.reward} BOILIES**!", ephemeral=True)

        # Update public message
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(
            content=f"✅ **{self.fish_type}** ({self.weight} lbs) was caught by **{self.caught_by_name}**.",
            view=self
        )

        self.stop()


@tasks.loop(seconds=30)
async def spawn_fish():
    global last_fish_message
    global last_fish_view
    for channel_id in FISH_CHANNEL_IDS:
        base_chance = FISH_CHANNELS.get(channel_id, 1)
        boost_factor = get_boost_factor(channel_id)
        adjusted_chance = max(1, int(base_chance / boost_factor))
        if random.randint(1, adjusted_chance) != 1:
            continue
        if channel_id in last_fish_message:
            try:
                original_view = last_fish_view.get(channel_id)
                if original_view:
                    for item in original_view.children:
                        item.disabled = True

                    if original_view.claimed:
                        summary = f"✅ {original_view.fish_type} ({original_view.weight} lbs) was caught by **{original_view.caught_by_name}**."
                    else:
                        summary = "❌ The fish escaped..."

                    await last_fish_message[channel_id].edit(content=summary, view=original_view)
            except Exception as e:
                print(f"[WARN] Failed to update previous fish message in channel {channel_id}: {e}")

        selected_type = random.choices(types, weights=weights, k=1)[0]
        weight = random.randint(*range_dict[selected_type])
        # Reward calculation: rare fish get higher reward
        if selected_type in ["Koi Carp", "Siamese Giant Carp"]:
            reward = weight * 100
        elif selected_type == "Leather Carp":
            reward = weight * 50
        else:
            reward = weight * 10

        channel = bot.get_channel(channel_id)
        if not channel:
            continue

        view = CatchView(reward, selected_type, weight, channel_id)
        file = discord.File(os.path.join(FISH_IMAGES_DIR, f"{selected_type.replace(' ', '_').lower()}.png"), filename="fish.png")

        if selected_type in ["Koi Carp", "Siamese Giant Carp", "Leather Carp"]:
            message_text = f"🌟 A **rare {selected_type}** appeared! First to catch it earns massive amounts of BOILIES!\n_(Disappears in 15 minutes if not caught.)_"
        else:
            message_text = f"🎣 A wild **{selected_type}** appeared! Be the first to catch it!\n_(Disappears in 15 minutes if not caught.)_"

        try:
            # Try sending the fish message to the channel
            last_fish_message[channel_id] = await channel.send(message_text, file=file, view=view)
            last_fish_view[channel_id] = view
            # Schedule auto-delete after 24 hours

            async def delete_later(message):
                await asyncio.sleep(86400)  # 24 hours in seconds
                try:
                    await message.delete()
                except Exception as e:
                    print(f"[WARN] Could not delete message: {e}")

            asyncio.create_task(delete_later(last_fish_message[channel_id]))
        except discord.Forbidden:
            # Log permission errors but allow the loop to continue
            print(f"[ERROR] Missing permissions in channel {channel_id}. Skipping...")
        except Exception as e:
            # Catch any other errors to prevent full task crash
            print(f"[ERROR] Failed to send message in channel {channel_id}: {e}")


@bot.command(name="leaderboard")
async def leaderboard_command(ctx):
    channel_id_str = str(ctx.channel.id)
    if channel_id_str not in leaderboard or not leaderboard[channel_id_str]:
        await ctx.send("🏆 No fish caught yet!")
        return
    top = sorted(leaderboard[channel_id_str].items(), key=lambda x: x[1], reverse=True)[:10]
    msg = "**🎣 Top Fishers:**\n" + "\n".join([f"{i+1}. {name} – {score} BOILIES" for i, (name, score) in enumerate(top)])
    await ctx.send(msg)


# Command to check bot's permissions in the current channel
@bot.command(name="checkrights")
async def checkrights(ctx):
    # Report the bot's permissions in the current channel
    perms = ctx.channel.permissions_for(ctx.guild.me)
    await ctx.send(
        f"🔍 Permissions in this channel:\n"
        f"- Send Messages: {'✅' if perms.send_messages else '❌'}\n"
        f"- Attach Files: {'✅' if perms.attach_files else '❌'}\n"
        f"- Embed Links: {'✅' if perms.embed_links else '❌'}\n"
        f"- Read Message History: {'✅' if perms.read_message_history else '❌'}"
    )


@bot.command(name="bait")
async def bait_command(ctx, bait_type: str):
    user = str(ctx.author.id)
    channel_id = ctx.channel.id

    # Prevent multiple overlapping bait boosts in the same channel
    current_time = asyncio.get_event_loop().time()
    if channel_id in bait_boost:
        _, expiry, _ = bait_boost[channel_id]
        if current_time < expiry:
            remaining = int((expiry - current_time) // 60)
            await ctx.send(f"🪱 Bait is already active in this channel for another {remaining} minute(s).")
            return

    bait_prices = {
        "corn": 250,
        "boilie": 1000
    }
    bait_effect = {
        "corn": 4,
        "boilie": 8
    }

    if bait_type not in bait_prices:
        await ctx.send("🐟 Unknown bait type. Use `corn` or `boilie`.")
        return

    price = bait_prices[bait_type]
    boost_factor = bait_effect[bait_type]
    if not treasury:
        await ctx.send("⚠️ Treasury not yet initialized.")
        return

    effective = get_effective_balance(user)

    if effective < price:
        await ctx.send("❌ You do not have enough BOILIES.")
        return

    nonce_user = get_nonce(user)
    tx = {
        "type": "bait",
        "user_id": user,
        "username": str(ctx.author),
        "to": treasury,
        "to_username": "Fishing Bot",
        "amount": price,
        "nonce": nonce_user
    }

    if not safe_append_tx(tx):
        await ctx.send("⚠️ Bait transaction already in mempool for your account.")
        return

    bait_boost[channel_id] = (
        boost_factor,
        asyncio.get_event_loop().time() + 60 * 60 * (2 if bait_type == "boilie" else 1),
        user
    )
    bait_emojis = {
        "corn": "🌽",
        "boilie": "🍡"
    }
    bait_label = "sweetcorn" if bait_type == "corn" else bait_type
    await ctx.send(f"{bait_emojis.get(bait_type, '🎣')} You cast out some {bait_label}! Fish in this channel will be more active for {2 if bait_type == 'boilie' else 1} hour(s).")


# Add baitstatus command
@bot.command(name="baitstatus")
async def baitstatus(ctx):
    channel_id = ctx.channel.id
    boost = bait_boost.get(channel_id)
    if not boost or asyncio.get_event_loop().time() > boost[1]:
        await ctx.send("🎣 No active bait in this channel.")
        return
    minutes = int((boost[1] - asyncio.get_event_loop().time()) // 60)
    await ctx.send(f"🎣 Bait is active! Spawn chance is boosted by {boost[0]}× for another {minutes} minute(s).")


@bot.command(name="spawnfish")
@commands.has_permissions(administrator=True)
async def spawnfish(ctx):
    selected_type = random.choices(types, weights=weights, k=1)[0]
    weight = random.randint(*range_dict[selected_type])
    reward = weight * (100 if selected_type in ["Koi Carp", "Siamese Giant Carp"]
                       else 50 if selected_type == "Leather Carp"
                       else 10)

    view = CatchView(reward, selected_type, weight, ctx.channel.id)
    file = discord.File(os.path.join(FISH_IMAGES_DIR, f"{selected_type.replace(' ', '_').lower()}.png"), filename="fish.png")
    message_text = f"🌟 A **{selected_type}** appeared! Click to catch it!\n_(Disappears in 15 minutes if not caught.)_"
    last_fish_message[ctx.channel.id] = await ctx.send(message_text, file=file, view=view)
    last_fish_view[ctx.channel.id] = view


@bot.event
async def on_ready():
    print(f"🐟 FishBot ready as {bot.user}")
    spawn_fish.start()

bot.run(os.getenv("DISCORD_TOKEN_FISHING"))
