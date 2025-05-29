# rewardbot.py

import discord
import os
from discord import app_commands
from dotenv import load_dotenv

from tx_utils import (
    safe_append_tx,
    get_nonce,
    get_or_create_wallet,
    get_effective_balance
)

load_dotenv()
ADMIN_IDS = os.getenv("ADMIN_IDS", "").split(",")


class BoilieBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        await self.tree.sync()
        print(f"🤖BOILIE Tipping Bot connected as {self.user}")


client = BoilieBot()


@client.tree.command(name="help", description="List all commands and their usage")
async def help_command(interaction: discord.Interaction):
    help_text = (
        "**🧾 BOILIE Tipping Bot Commands:**\n\n"
        "• `/tip @user amount` – Send BOILIE to another user.\n"
        "• `/multitip users amounts` – Send BOILIE to multiple users at once.\n"
        "• `/balance` – Show your current BOILIE balance.\n"
        "• `/help` – Display this help message.\n"
    )
    await interaction.response.send_message(help_text, ephemeral=True)


@client.tree.command(name="tip", description="Send BOILIES to another user")
@app_commands.describe(user="Recipient Discord user", amount="Amount of BOILIES to send")
async def tip(interaction: discord.Interaction, user: discord.User, amount: int):
    #sender_wallet = get_or_create_wallet(interaction.user)
    #if sender_wallet["carp_balance"] < amount:
    effective = get_effective_balance(str(interaction.user.id))
    if effective < amount:
        await interaction.response.send_message("❌ Insufficient BOILIES.", ephemeral=True)
        return

    nonce = get_nonce(str(interaction.user.id))
    tx = {
        "type": "tip",
        "user_id": str(interaction.user.id),
        "username": str(interaction.user),
        "to": str(user.id),
        "to_username": str(user),
        "amount": amount,
        "nonce": nonce
    }

    if not safe_append_tx(tx):
        await interaction.response.send_message("⚠️ Transaction already in mempool. Please wait.", ephemeral=True)
        return

    # Private confirmation to sender
    await interaction.response.send_message(
        f"✅ Tip of {amount} BOILIES queued for {user.display_name}.", ephemeral=True)

    # Public message in same channel
    try:
        await interaction.channel.send(
            f"🎏 {interaction.user.display_name} just tipped {amount} BOILIES to {user.mention}!")
    except Exception as e:
        print(f"⚠️ Failed to send public tip message: {e}")


@client.tree.command(name="multitip", description="Send BOILIES to multiple users")
@app_commands.describe(users="Space-separated list of @users", amounts="Corresponding BOILIES amounts")
async def multitip(interaction: discord.Interaction, users: str, amounts: str):
    #sender_wallet = get_or_create_wallet(interaction.user)
    effective = get_effective_balance(str(interaction.user.id))
    user_list = users.split()
    amount_list = list(map(int, amounts.split()))

    if any(a <= 0 for a in amount_list):
        await interaction.response.send_message("❌ All amounts must be positive.", ephemeral=True)
        return
    if len(user_list) != len(amount_list):
        await interaction.response.send_message("❌ Mismatched number of users and amounts.", ephemeral=True)
        return

    total = sum(amount_list)
    #if sender_wallet["carp_balance"] < total:
    if effective < total:
        await interaction.response.send_message(f"❌ You need {total} BOILIES.", ephemeral=True)
        return

    current_nonce = get_nonce(str(interaction.user.id))
    skipped = 0
    summary_lines = []

    for i, mention in enumerate(user_list):
        user_id_str = mention.strip('<@!>')
        try:
            user_obj = await client.fetch_user(int(user_id_str))
            username = str(user_obj)
            display_name = user_obj.display_name
        except Exception:
            username = mention
            display_name = username

        tx = {
            "type": "tip",
            "user_id": str(interaction.user.id),
            "username": str(interaction.user),
            "to": user_id_str,
            "to_username": username,
            "amount": amount_list[i],
            "nonce": current_nonce
        }
        success = safe_append_tx(tx)
        if success:
            summary_lines.append(f"• {interaction.user.display_name} → {display_name}: {amount_list[i]} BOILIES")
        else:
            skipped += 1
        current_nonce += 1

    if summary_lines:
        summary = "🍡 **Multitip Summary:**\n" + "\n".join(summary_lines)
    else:
        summary = "⚠️ All transactions were skipped due to duplicate nonces."

    if skipped:
        summary += f"\n⚠️ {skipped} transaction(s) were skipped due to duplicate nonces."

    await interaction.response.send_message(summary, ephemeral=True)


@client.tree.command(name="balance", description="Check your BOILIES balance")
async def balance(interaction: discord.Interaction):
    wallet = get_or_create_wallet(interaction.user)
    await interaction.response.send_message(f"💰 Balance: {wallet['carp_balance']} BOILIES", ephemeral=True)


@client.tree.command(name="mint", description="Mint BOILIES to a user (admin only)")
async def mint(interaction: discord.Interaction, user: discord.User, amount: int):
    if str(interaction.user.id) not in ADMIN_IDS:
        await interaction.response.send_message("❌ Not authorized.", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
        return

    nonce = get_nonce(str(user.id))
    tx = {
        "type": "mint",
        "user_id": str(user.id),
        "username": str(user),
        "amount": amount,
        "nonce": nonce
    }

    if not safe_append_tx(tx):
        await interaction.response.send_message("⚠️ Mint transaction already in mempool.", ephemeral=True)
        return

    await interaction.response.send_message(f"✅ Mint of {amount} BOILIES queued for {user.display_name}.", ephemeral=True)

client.run(os.getenv("DISCORD_TOKEN_TIPPING"))