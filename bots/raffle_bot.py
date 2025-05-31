import discord
from discord import app_commands
import json
import os
from dotenv import load_dotenv
from datetime import datetime
import random

from core.tx_utils import (
    safe_append_tx,
    get_nonce,
    get_effective_balance
)

load_dotenv()
ALLOWED_CHANNEL_IDS = set(map(int, os.getenv("RAFFLE_CHANNEL_IDS", "").split(",")))

# Set up base and data directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "..", "data")

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

LOCKFILE = os.path.join(DATA_DIR, "pending_tx.lock")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN_RAFFLE")
ADMIN_IDS = set(map(int, os.getenv("ADMIN_IDS", "").split(",")))
FISHING_BOT_ID = os.getenv("FISHING_BOT_ID")
RAFFLES_FILE = os.path.join(DATA_DIR, "raffles.json")
TICKETS_FILE = os.path.join(DATA_DIR, "raffle_tickets.json")
WINNERS_FILE = os.path.join(DATA_DIR, "raffle_winners.json")

class RaffleBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        await self.tree.sync()
        print(f"🎰 RaffleBot connected as {self.user}")


treasury = FISHING_BOT_ID
bot = RaffleBot()


# Move the /raffle_stats command here so that bot is already defined
@bot.tree.command(name="raffle_stats", description="Show the total number of tickets sold for a raffle")
@app_commands.describe(name="Raffle name to show stats for")
async def raffle_stats(interaction: discord.Interaction, name: str):
    if interaction.channel_id not in ALLOWED_CHANNEL_IDS:
        await interaction.response.send_message("❌ This command is not allowed in this channel.", ephemeral=True)
        return
    if name not in raffles:
        await interaction.response.send_message("❌ Raffle not found.", ephemeral=True)
        return
    if name not in tickets or not tickets[name]:
        await interaction.response.send_message("📭 No tickets have been bought for this raffle yet.", ephemeral=False)
        return
    total_tickets = sum(tickets[name].values())
    await interaction.response.send_message(f"🎟️ A total of **{total_tickets}** ticket(s) have been bought for raffle **{name}**.", ephemeral=False)


@bot.tree.command(name="help", description="Show all available commands")
async def help_command(interaction: discord.Interaction):
    if interaction.channel_id not in ALLOWED_CHANNEL_IDS:
        await interaction.response.send_message("❌ This command is not allowed in this channel.", ephemeral=True)
        return
    user_id = interaction.user.id
    help_msg = "**Available Commands:**\n"
    help_msg += "• `/list` - List all active raffles\n"
    help_msg += "• `/mytickets` - Show your current raffle tickets\n"
    help_msg += "• `/buyticket <raffle_name> <count>` - Buy tickets for a specific raffle\n"
    help_msg += "• `/winners` - Show the last 5 raffle winners\n"
    help_msg += "• `/raffle_stats` - Show how many tickets have been bought for a raffle\n"
    if user_id in ADMIN_IDS:
        help_msg += "\n**Admin Commands:**\n"
        help_msg += "• `/create_raffle` - Create a new raffle\n"
        help_msg += "• `/start_raffle` - Mark a raffle as active (becomes visible for users)\n"
        help_msg += "• `/stop_raffle` - Mark a raffle as inactive (becomes invisible for users)\n"
        help_msg += "• `/edit` - Edit an existing raffle\n"
        help_msg += "• `/delete` - Delete a raffle\n"
        help_msg += "• `/draw_winner` - Draw a winner for a raffle\n"
        help_msg += "• `/list_all` - List all raffles (active and inactive)\n"
    await interaction.response.send_message(help_msg, ephemeral=True)
@bot.tree.command(name="winners", description="Show the last 5 raffle winners")
async def winners_command(interaction: discord.Interaction):
    if interaction.channel_id not in ALLOWED_CHANNEL_IDS:
        await interaction.response.send_message("❌ This command is not allowed in this channel.", ephemeral=False)
        return
    if not winners:
        await interaction.response.send_message("📭 No winners recorded yet.")
        return
    msg = "🏆 **Last 5 Raffle Winners:**\n"
    for entry in winners[-5:][::-1]:
        raffle = entry.get("raffle", "Unknown")
        winner = entry.get("winner", "Unknown")
        timestamp = entry.get("timestamp", 0)
        msg += f"• **{raffle}**: {winner} (<t:{timestamp}:F>)\n"
    await interaction.response.send_message(msg)

# Ensure all required files exist
for path, default in [
    (RAFFLES_FILE, {}),
    (TICKETS_FILE, {}),
    (WINNERS_FILE, [])
]:
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f)

if os.path.exists(RAFFLES_FILE):
    with open(RAFFLES_FILE) as f:
        raffles = json.load(f)
else:
    raffles = {}

if os.path.exists(TICKETS_FILE):
    with open(TICKETS_FILE) as f:
        tickets = json.load(f)
else:
    tickets = {}

if os.path.exists(WINNERS_FILE):
    with open(WINNERS_FILE) as f:
        winners = json.load(f)
else:
    winners = []

def save():
    with open(RAFFLES_FILE, "w") as f:
        json.dump(raffles, f, indent=2)
    with open(TICKETS_FILE, "w") as f:
        json.dump(tickets, f, indent=2)
    with open(WINNERS_FILE, "w") as f:
        json.dump(winners, f, indent=2)

def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))




@bot.tree.command(name="list", description="List all active raffles")
async def list_raffles(interaction: discord.Interaction):
    if interaction.channel_id not in ALLOWED_CHANNEL_IDS:
        await interaction.response.send_message("❌ This command is not allowed in this channel.", ephemeral=True)
        return
    active_raffles = {name: r for name, r in raffles.items() if r.get("active")}
    if not active_raffles:
        await interaction.response.send_message("📭 No active raffles at the moment.")
        return
    msg = "🎟️ **Active Raffles:**\n"
    for name, r in active_raffles.items():
        msg += f"\n• **{name}**: {r['prize']} (Draw: <t:{int(r['draw_time'])}:F>, Max/User: {r['max_tickets_per_user']})"
    await interaction.response.send_message(msg)

@bot.tree.command(name="mytickets", description="Show your current raffle tickets")
async def mytickets(interaction: discord.Interaction):
    if interaction.channel_id not in ALLOWED_CHANNEL_IDS:
        await interaction.response.send_message("❌ This command is not allowed in this channel.", ephemeral=True)
        return
    user_id = str(interaction.user.id)
    msg = f"🎫 Tickets for {interaction.user.display_name}:\n"
    for rname, tdict in tickets.items():
        if user_id in tdict:
            msg += f"• {rname}: {tdict[user_id]} ticket(s)\n"
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="buyticket", description="Buy raffle tickets")
@app_commands.describe(raffle_name="Name of the raffle", count="Number of tickets to buy (1000 BOILIES each)")
async def buyticket(interaction: discord.Interaction, raffle_name: str, count: int):
    if interaction.channel_id not in ALLOWED_CHANNEL_IDS:
        await interaction.response.send_message("❌ This command is not allowed in this channel.", ephemeral=True)
        return
    if count <= 0:
        await interaction.response.send_message("❌ Ticket count must be positive.", ephemeral=True)
        return

    if raffle_name not in raffles or not raffles[raffle_name].get("active", False):
        await interaction.response.send_message("❌ The specified raffle does not exist or is not active.", ephemeral=True)
        return

    user_id = str(interaction.user.id)
    r = raffles[raffle_name]
    user_tickets = tickets.setdefault(raffle_name, {}).get(user_id, 0)
    if user_tickets + count > r['max_tickets_per_user']:
        await interaction.response.send_message("❌ You would exceed your ticket limit.", ephemeral=True)
        return

    total = 100 * count
    effective = get_effective_balance(user_id)

    if effective < total:
        await interaction.response.send_message("❌ Not enough BOILIES.", ephemeral=True)
        return

    nonce = get_nonce(user_id)
    tx = {
        "type": "tip",
        "user_id": user_id,
        "username": str(interaction.user),
        "to": treasury,
        "to_username": "Fishing Bot",
        "amount": total,
        "nonce": nonce
    }
    success = safe_append_tx(tx)
    if not success:
        await interaction.response.send_message("⚠️ Transaction already in mempool. Please wait.", ephemeral=True)
        return
    try:
        # Only book tickets locally; wallet deduction is handled by tx processor
        tickets[raffle_name][user_id] = user_tickets + count
        save()
        await interaction.response.send_message(f"✅ You bought {count} ticket(s) for raffle **{raffle_name}**.", ephemeral=True)
    finally:
        # No explicit removal from pending_tx, as this is now handled by the new system; tx stays in mempool until processed.
        pass

@bot.tree.command(name="create_raffle", description="Create a new raffle (Admin only)")
@app_commands.describe(name="Raffle name", prize="Prize description", draw_unix="Draw time (UTC timestamp)", max_per_user="Max tickets/user")
async def create_raffle(interaction: discord.Interaction, name: str, prize: str, draw_unix: int, max_per_user: int):
    if interaction.channel_id not in ALLOWED_CHANNEL_IDS:
        await interaction.response.send_message("❌ This command is not allowed in this channel.", ephemeral=True)
        return
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ You are not authorized.", ephemeral=True)
        return

    raffles[name] = {
        "prize": prize,
        "draw_time": draw_unix,
        "max_tickets_per_user": max_per_user,
        "active": False
    }
    save()
    await interaction.response.send_message(f"🎉 Raffle **{name}** created.", ephemeral=False)

@bot.tree.command(name="start_raffle", description="Mark a raffle as active (Admin only)")
@app_commands.describe(name="Raffle name to start")
async def start_raffle(interaction: discord.Interaction, name: str):
    if interaction.channel_id not in ALLOWED_CHANNEL_IDS:
        await interaction.response.send_message("❌ This command is not allowed in this channel.", ephemeral=True)
        return
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ You are not authorized.", ephemeral=True)
        return
    if name not in raffles:
        await interaction.response.send_message("❌ Raffle not found.", ephemeral=True)
        return
    raffles[name]["active"] = True
    save()
    await interaction.response.send_message(f"✅ Raffle **{name}** is now active.", ephemeral=True)

@bot.tree.command(name="draw_winner", description="Draw a winner for a raffle (Admin only)")
@app_commands.describe(name="Raffle name to draw winner from")
async def draw_winner(interaction: discord.Interaction, name: str):
    if interaction.channel_id not in ALLOWED_CHANNEL_IDS:
        await interaction.response.send_message("❌ This command is not allowed in this channel.", ephemeral=True)
        return
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ You are not authorized.", ephemeral=True)
        return
    if name not in raffles:
        await interaction.response.send_message("❌ Raffle not found.", ephemeral=True)
        return
    if name not in tickets or not tickets[name]:
        await interaction.response.send_message("❌ No tickets sold for this raffle.", ephemeral=True)
        return

    ticket_holders = list(tickets[name].keys())
    ticket_counts = [tickets[name][user] for user in ticket_holders]
    winner_id = random.choices(ticket_holders, weights=ticket_counts, k=1)[0]
    winner_user = await bot.fetch_user(int(winner_id))
    winner_name = winner_user.name if winner_user else winner_id

    raffles[name]["active"] = False

    # Save winner info
    winners.append({
        "raffle": name,
        "winner": winner_name,
        "timestamp": int(datetime.utcnow().timestamp())
    })

    save()
    await interaction.response.send_message(f"🎉 The winner of **{name}** is {winner_name}! Congratulations!")


# Admin command: /stop_raffle - mark a raffle as inactive
@bot.tree.command(name="stop_raffle", description="Mark a raffle as inactive (Admin only)")
@app_commands.describe(name="Raffle name")
async def stop_raffle(interaction: discord.Interaction, name: str):
    if interaction.channel_id not in ALLOWED_CHANNEL_IDS:
        await interaction.response.send_message("❌ This command is not allowed in this channel.", ephemeral=True)
        return
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ You are not authorized.", ephemeral=True)
        return
    if name not in raffles:
        await interaction.response.send_message("❌ Raffle not found.", ephemeral=True)
        return
    raffles[name]["active"] = False
    save()
    await interaction.response.send_message(f"⏹️ Raffle **{name}** is now inactive.", ephemeral=True)

@bot.tree.command(name="edit", description="Edit an existing raffle (Admin only)")
@app_commands.describe(
    name="Raffle name to edit",
    prize="New prize description (optional)",
    draw_unix="New draw time (UTC timestamp, optional)",
    max_per_user="New max tickets per user (optional)"
)
async def edit(interaction: discord.Interaction, name: str, prize: str = None, draw_unix: int = None, max_per_user: int = None):
    if interaction.channel_id not in ALLOWED_CHANNEL_IDS:
        await interaction.response.send_message("❌ This command is not allowed in this channel.", ephemeral=True)
        return
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ You are not authorized.", ephemeral=True)
        return
    if name not in raffles:
        await interaction.response.send_message("❌ Raffle not found.", ephemeral=True)
        return

    if prize is not None:
        raffles[name]["prize"] = prize
    if draw_unix is not None:
        raffles[name]["draw_time"] = draw_unix
    if max_per_user is not None:
        raffles[name]["max_tickets_per_user"] = max_per_user

    save()
    await interaction.response.send_message(f"✏️ Raffle **{name}** has been updated.", ephemeral=True)

@bot.tree.command(name="delete", description="Delete a raffle (Admin only)")
@app_commands.describe(name="Raffle name to delete")
async def delete(interaction: discord.Interaction, name: str):
    if interaction.channel_id not in ALLOWED_CHANNEL_IDS:
        await interaction.response.send_message("❌ This command is not allowed in this channel.", ephemeral=True)
        return
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ You are not authorized.", ephemeral=True)
        return
    if name not in raffles:
        await interaction.response.send_message("❌ Raffle not found.", ephemeral=True)
        return

    raffles.pop(name)
    tickets.pop(name, None)
    save()
    await interaction.response.send_message(f"🗑️ Raffle **{name}** has been deleted.", ephemeral=True)

# Admin command: /list_all - list all raffles with status
@bot.tree.command(name="list_all", description="List all raffles (Admin only)")
async def list_all(interaction: discord.Interaction):
    if interaction.channel_id not in ALLOWED_CHANNEL_IDS:
        await interaction.response.send_message("❌ This command is not allowed in this channel.", ephemeral=True)
        return
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ You are not authorized.", ephemeral=True)
        return
    if not raffles:
        await interaction.response.send_message("📭 No raffles found.", ephemeral=True)
        return
    msg = "🎟️ **All Raffles:**\n"
    for name, r in raffles.items():
        status = "active" if r.get("active") else "inactive"
        msg += f"\n• **{name}**: {r['prize']} (Draw: <t:{int(r['draw_time'])}:F>, Max/User: {r['max_tickets_per_user']}, Status: {status})"
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="reset_winners", description="Reset the list of raffle winners (Admin only)")
async def reset_winners(interaction: discord.Interaction):
    if interaction.channel_id not in ALLOWED_CHANNEL_IDS:
        await interaction.response.send_message("❌ This command is not allowed in this channel.", ephemeral=True)
        return
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ You are not authorized.", ephemeral=True)
        return
    global winners
    winners = []
    save()
    await interaction.response.send_message("🗑️ All raffle winners have been reset.", ephemeral=True)

bot.run(DISCORD_TOKEN)
