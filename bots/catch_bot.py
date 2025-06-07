# catch_bot.py (refactored into CatchBot class)

import discord
from dotenv import load_dotenv
import random
import asyncio
import json
import os
import sys
from discord.ext import tasks, commands
from paths import LEADERBOARD_FILE, FISH_IMAGES_DIR
from core.tx_utils import (
    safe_append_tx,
    get_nonce,
    get_effective_balance
)

from paths import DEBUG_FILE

sys.stdout = open(DEBUG_FILE, "a")
sys.stderr = sys.stdout


class CatchBot:
    def __init__(self):
        load_dotenv()
        self.nonce_lock = None
        self.CATCHBOT_ID = os.getenv("CATCHBOT_ID")
        self.CATCHBOT_CHANNELS = {}
        raw_channel_data = os.getenv("CATCHBOT_CHANNELS", "")
        for entry in raw_channel_data.split(","):
            if ":" in entry:
                cid, chance = entry.split(":")
                try:
                    cid_int = int(cid.strip())
                    chance_int = int(chance.strip())
                    self.CATCHBOT_CHANNELS[cid_int] = chance_int
                    print(f"Found CATCHBOT_CHANNELS entry: {entry}")
                except ValueError:
                    print(f"[WARN] Invalid CATCHBOT_CHANNELS entry: {entry}")
        self.CATCHBOT_CHANNELS_IDS = list(self.CATCHBOT_CHANNELS.keys())
        self.treasury = self.CATCHBOT_ID

        self.fish_pool = [
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
        self.types, self.ranges, self.weights = zip(*self.fish_pool)
        self.range_dict = dict(zip(self.types, self.ranges))

        if os.path.exists(LEADERBOARD_FILE):
            with open(LEADERBOARD_FILE) as f:
                self.leaderboard = json.load(f)
        else:
            self.leaderboard = {}

        self.last_catch_time = {}  # Cooldown tracking
        self.BASE_CATCH_COOLDOWN = 30 * 60
        self.BAIT_CATCH_COOLDOWN = 5 * 60
        self.bait_boost = {}
        self.last_fish_message = {}
        self.last_fish_view = {}

        self.intents = discord.Intents.default()
        self.intents.message_content = True
        self.bot = commands.Bot(command_prefix="!", intents=self.intents, help_command=None)

        # Register commands and events
        self.register_commands()
        self.bot.event(self.on_ready)

        # spawn_fish task
        self.spawn_fish = tasks.loop(seconds=30)(self._spawn_fish_task)

    def register_commands(self):
        @self.bot.command(name="help", aliases=["h"], case_insensitive=True)
        async def _help(ctx):
            await self.help_command(ctx)

        @self.bot.command(name="leaderboard", aliases=["lb", "top"], case_insensitive=True)
        async def _leaderboard(ctx):
            await self.leaderboard_command(ctx)

        @self.bot.command(name="checkrights", aliases=["rights", "perms"], case_insensitive=True)
        async def _checkrights(ctx):
            await self.checkrights(ctx)

        @self.bot.command(name="bait", aliases=["castbait"], case_insensitive=True)
        async def _bait(ctx, *, bait_type: str):
            await self.bait_command(ctx, bait_type)

        @self.bot.command(name="baitstatus", aliases=["baitinfo"], case_insensitive=True)
        async def _baitstatus(ctx):
            await self.baitstatus(ctx)

        @self.bot.command(name="spawnfish", aliases=["fishnow"], case_insensitive=True)
        @commands.has_permissions(administrator=True)
        async def _spawnfish(ctx):
            await self.spawnfish(ctx)

    # Utility: Get boost factor for a channel
    def get_boost_factor(self, channel_id):
        boost_factor, expiry, *_ = self.bait_boost.get(channel_id, (1, 0))
        if asyncio.get_event_loop().time() > expiry:
            return 1
        return boost_factor

    # HELP command
    async def help_command(self, ctx):
        msg = (
            "🎣 **Catch Bot Commands**\n\n"
            "- `!leaderboard` – Show the top 10 fishers in this channel\n"
            "- `!bait <type>` – Use bait to boost fish spawns (paid in BOILIES)\n"
            "- `!baitstatus` – Show current bait effect in this channel\n\n"
            "**Available Baits:**\n"
            "- `Boilies`: 30 min, 40×, 1000 BOILIES\n"
            "- `Popups`: 60 min, 20×, 1000 BOILIES\n"
            "- `Tiger nuts`: 60 min, 16×, 800 BOILIES\n"
            "- `Halibut`: 60 min, 10×, 500 BOILIES\n"
            "- `Mixers`: 60 min, 8×, 400 BOILIES\n"
            "- `Maggots`: 60 min, 5×, 250 BOILIES\n"
            "- `Worms`: 30 min, 10×, 250 BOILIES\n"
            "- `Bread`: 30 min, 8×, 200 BOILIES\n"
            "- `Corn`: 15 min, 16×, 200 BOILIES\n\n"
            "⏳ Cooldown: 30 minutes after catching a fish – or only 5 minutes if you're the one who cast the bait!"
        )
        await ctx.send(msg)

    class CatchView(discord.ui.View):
        def __init__(self, botref, reward, fish_type, weight, channel_id):
            super().__init__()
            self.botref = botref
            self.reward = reward
            self.claimed = False
            self.fish_type = fish_type
            self.weight = weight
            self.channel_id = channel_id
            self.timeout = 900  # 15 min
            self.caught_by = None
            self.caught_by_name = None

        async def on_timeout(self):
            for item in self.children:
                item.disabled = True
            try:
                await self.botref.last_fish_message[self.channel_id].edit(view=self)
            except Exception as e:
                print(f"[WARN] Failed to disable catch button after timeout: {e}")

        @discord.ui.button(label="🎣 Catch!", style=discord.ButtonStyle.primary)
        async def catch_button(self, interaction: discord.Interaction, _: discord.ui.Button):
            now = asyncio.get_event_loop().time()
            user_id = str(interaction.user.id)
            if self.channel_id not in self.botref.last_catch_time:
                self.botref.last_catch_time[self.channel_id] = {}
            if user_id in self.botref.last_catch_time[self.channel_id]:
                elapsed = now - self.botref.last_catch_time[self.channel_id][user_id]
                boost = self.botref.bait_boost.get(self.channel_id)
                is_bait_caster = (
                    boost and
                    len(boost) > 2 and
                    boost[2] == str(interaction.user.id) and
                    asyncio.get_event_loop().time() < boost[1]
                )
                cooldown = self.botref.BAIT_CATCH_COOLDOWN if is_bait_caster else self.botref.BASE_CATCH_COOLDOWN
                if elapsed < cooldown:
                    remaining = cooldown - elapsed
                    if remaining < 60:
                        time_msg = f"{int(remaining)} seconds"
                    else:
                        time_msg = f"{int(remaining // 60)} minutes"
                    message = f"⏳ You've already caught a fish recently. Try again in {time_msg}."
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
            effective = get_effective_balance(self.botref.CATCHBOT_ID)
            if effective < self.reward:
                await interaction.response.send_message("❌ Insufficient BOILIES.", ephemeral=True)
                return

            nonce = get_nonce(self.botref.CATCHBOT_ID)
            tx = {
                "type": "reward",
                "user_id": self.botref.CATCHBOT_ID,
                "username": "Catch Bot",
                "to": self.caught_by,
                "to_username": str(interaction.user),
                "amount": self.reward,
                "nonce": nonce
            }
            if not safe_append_tx(tx):
                await interaction.response.send_message("⚠️ Reward transaction already in mempool.", ephemeral=True)
                return

            channel_id_str = str(self.channel_id)
            name = str(interaction.user.display_name)
            if channel_id_str not in self.botref.leaderboard:
                self.botref.leaderboard[channel_id_str] = {}
            self.botref.leaderboard[channel_id_str][name] = self.botref.leaderboard[channel_id_str].get(name, 0) + self.reward
            with open(LEADERBOARD_FILE, "w") as f:
                json.dump(self.botref.leaderboard, f, indent=2)
            self.botref.last_catch_time[self.channel_id][user_id] = now
            if interaction.response.is_done():
                await interaction.followup.send(f"🐟 You caught a **{self.fish_type}** weighing **{self.weight} lbs** and earned **{self.reward} BOILIES**!", ephemeral=True)
            else:
                await interaction.response.send_message(f"🐟 You caught a **{self.fish_type}** weighing **{self.weight} lbs** and earned **{self.reward} BOILIES**!", ephemeral=True)
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(
                content=f"✅ **{self.fish_type}** ({self.weight} lbs) was caught by **{self.caught_by_name}**.",
                view=self
            )
            self.stop()

    # Fish spawner task
    async def _spawn_fish_task(self):
        for channel_id in self.CATCHBOT_CHANNELS_IDS:
            base_chance = self.CATCHBOT_CHANNELS.get(channel_id, 1)
            boost_factor = self.get_boost_factor(channel_id)
            adjusted_chance = max(1, int(base_chance / boost_factor))
            if random.randint(1, adjusted_chance) != 1:
                continue
            if channel_id in self.last_fish_message:
                try:
                    original_view = self.last_fish_view.get(channel_id)
                    if original_view:
                        for item in original_view.children:
                            item.disabled = True
                        if original_view.claimed:
                            summary = f"✅ {original_view.fish_type} ({original_view.weight} lbs) was caught by **{original_view.caught_by_name}**."
                        else:
                            summary = "❌ The fish escaped..."
                        await self.last_fish_message[channel_id].edit(content=summary, view=original_view)
                except Exception as e:
                    print(f"[WARN] Failed to update previous fish message in channel {channel_id}: {e}")
            selected_type = random.choices(self.types, weights=self.weights, k=1)[0]
            weight = random.randint(*self.range_dict[selected_type])
            if selected_type in ["Koi Carp", "Siamese Giant Carp"]:
                reward = weight * 100
            elif selected_type == "Leather Carp":
                reward = weight * 50
            else:
                reward = weight * 10
            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue
            view = self.CatchView(self, reward, selected_type, weight, channel_id)
            file = discord.File(os.path.join(FISH_IMAGES_DIR, f"{selected_type.replace(' ', '_').lower()}.png"), filename="fish.png")
            if selected_type in ["Koi Carp", "Siamese Giant Carp", "Leather Carp"]:
                message_text = f"🌟 A **rare {selected_type}** appeared! First to catch it earns massive amounts of BOILIES!\n_(Disappears in 15 minutes if not caught.)_"
            else:
                message_text = f"🎣 A wild **{selected_type}** appeared! Be the first to catch it!\n_(Disappears in 15 minutes if not caught.)_"
            try:
                self.last_fish_message[channel_id] = await channel.send(message_text, file=file, view=view)
                self.last_fish_view[channel_id] = view

                async def delete_later(message):
                    await asyncio.sleep(86400)
                    try:
                        await message.delete()
                    except Exception as e:
                        print(f"[WARN] Could not delete message: {e}")
                asyncio.create_task(delete_later(self.last_fish_message[channel_id]))
            except discord.Forbidden:
                print(f"[ERROR] Missing permissions in channel {channel_id}. Skipping...")
            except Exception as e:
                print(f"[ERROR] Failed to send message in channel {channel_id}: {e}")

    # Leaderboard command
    async def leaderboard_command(self, ctx):
        channel_id_str = str(ctx.channel.id)
        if channel_id_str not in self.leaderboard or not self.leaderboard[channel_id_str]:
            await ctx.send("🏆 No fish caught yet!")
            return
        top = sorted(self.leaderboard[channel_id_str].items(), key=lambda x: x[1], reverse=True)[:10]
        msg = "**🎣 Top Fishers:**\n" + "\n".join([f"{i+1}. {name} – {score} BOILIES" for i, (name, score) in enumerate(top)])
        await ctx.send(msg)

    # Checkrights command
    async def checkrights(self, ctx):
        perms = ctx.channel.permissions_for(ctx.guild.me)
        await ctx.send(
            f"🔍 Permissions in this channel:\n"
            f"- Send Messages: {'✅' if perms.send_messages else '❌'}\n"
            f"- Attach Files: {'✅' if perms.attach_files else '❌'}\n"
            f"- Embed Links: {'✅' if perms.embed_links else '❌'}\n"
            f"- Read Message History: {'✅' if perms.read_message_history else '❌'}"
        )

    # Bait command
    async def bait_command(self, ctx, bait_type: str):
        user = str(ctx.author.id)
        channel_id = ctx.channel.id
        current_time = asyncio.get_event_loop().time()
        bait_options = {
            "boilies":      (30, 40, 1000),
            "popups":       (60, 20, 1000),
            "tiger nuts":   (60, 16, 800),
            "halibut":      (60, 10, 500),
            "mixers":       (60, 8, 400),
            "maggots":      (60, 5, 250),
            "worms":        (30, 10, 250),
            "bread":        (30, 8, 200),
            "corn":         (15, 16, 200)
        }
        bait_type = bait_type.lower().strip()
        if bait_type not in bait_options:
            await ctx.send("🐟 Unknown bait type. Available: " + ", ".join(bait_options.keys()))
            return
        duration_min, boost_factor, price = bait_options[bait_type]
        if channel_id in self.bait_boost:
            _, expiry, _ = self.bait_boost[channel_id]
            if current_time < expiry:
                remaining = int((expiry - current_time) // 60)
                await ctx.send(f"🪱 Bait is already active in this channel for another {remaining} minute(s).")
                return
        if not self.treasury:
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
            "to": self.treasury,
            "to_username": "Catch Bot",
            "amount": price,
            "nonce": nonce_user
        }
        if not safe_append_tx(tx):
            await ctx.send("⚠️ Bait transaction already in mempool for your account.")
            return
        self.bait_boost[channel_id] = (
            boost_factor,
            current_time + 60 * duration_min,
            user
        )
        await ctx.send(f"🎣 You used **{bait_type.title()}** – spawns boosted {boost_factor}× for {duration_min} minutes!")

    # Baitstatus command
    async def baitstatus(self, ctx):
        channel_id = ctx.channel.id
        boost = self.bait_boost.get(channel_id)
        if not boost or asyncio.get_event_loop().time() > boost[1]:
            await ctx.send("🎣 No active bait in this channel.")
            return
        minutes = int((boost[1] - asyncio.get_event_loop().time()) // 60)
        await ctx.send(f"🎣 Bait is active! Spawn chance is boosted by {boost[0]}× for another {minutes} minute(s).")

    # Spawnfish command (admin only)
    async def spawnfish(self, ctx):
        selected_type = random.choices(self.types, weights=self.weights, k=1)[0]
        weight = random.randint(*self.range_dict[selected_type])
        reward = weight * (100 if selected_type in ["Koi Carp", "Siamese Giant Carp"]
                           else 50 if selected_type == "Leather Carp"
                           else 10)
        view = self.CatchView(self, reward, selected_type, weight, ctx.channel.id)
        file = discord.File(os.path.join(FISH_IMAGES_DIR, f"{selected_type.replace(' ', '_').lower()}.png"), filename="fish.png")
        message_text = f"🌟 A **{selected_type}** appeared! Click to catch it!\n_(Disappears in 15 minutes if not caught.)_"
        self.last_fish_message[ctx.channel.id] = await ctx.send(message_text, file=file, view=view)
        self.last_fish_view[ctx.channel.id] = view

    # On ready event
    async def on_ready(self):
        self.nonce_lock = asyncio.Lock()
        print(f"🐟 Catch Bot connected as {self.bot.user}")
        if not self.spawn_fish.is_running():
            self.spawn_fish.start()

    # Run the bot (replaces run_bot)
    def run(self, stop_event=None):
        async def start_bot():
            try:
                await self.bot.start(os.getenv("DISCORD_TOKEN_CATCH"))
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"[ERROR] Bot runner error: {e}")
            finally:
                if self.spawn_fish.is_running():
                    self.spawn_fish.cancel()
                await self.bot.close()
                print("🔻 Catch Bot has shut down.")

        async def run_until_stop():
            bot_task = asyncio.create_task(start_bot())
            if stop_event:
                while not stop_event.is_set():
                    await asyncio.sleep(1)
                print("[INFO] Shutdown signal received. Closing Catch Bot...")
                bot_task.cancel()
                try:
                    await bot_task
                except asyncio.CancelledError:
                    pass
            else:
                await bot_task

        asyncio.run(run_until_stop())


# Factory for use elsewhere
def create_catch_bot():
    return CatchBot()
