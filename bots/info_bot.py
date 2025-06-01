# info_bot.py

import discord
import os
import sys
from dotenv import load_dotenv
import json
from datetime import datetime
from paths import WALLET_FILE, DEBUG_FILE

sys.stdout = open(DEBUG_FILE, "a")
sys.stderr = sys.stdout


def run_bot(shutdown_event=None):
    import asyncio
    load_dotenv()
    TOKEN = os.getenv("DISCORD_TOKEN_INFO")
    CHANNEL_ID = int(os.getenv("INFO_CHANNEL_ID"))

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    message_ref = None

    async def update_loop():
        nonlocal message_ref
        await client.wait_until_ready()
        channel = client.get_channel(CHANNEL_ID)
        if channel is None:
            print("❌ Channel not found.")
            return

        if message_ref is None:
            message_ref = await channel.send("📊 Loading wallet data...")

        while not shutdown_event.is_set():
            try:
                with open(WALLET_FILE) as f:
                    wallet_data = json.load(f)

                sorted_users = sorted(wallet_data.items(), key=lambda x: x[1].get("carp_balance", 0), reverse=True)

                lines = [
                    "👛 Wallets sorted by BOILIES",
                    "",
                    f"{'Name':<20} {'BOILIES':>10}",
                    f"{'-'*20} {'-'*10}"
                ]
                for uid, info in sorted_users:
                    name = info.get("name", "unknown")[:20]
                    balance = info.get("carp_balance", 0)
                    nonce = info.get("nonce", 0)
                    lines.append(f"{name:<20} {balance:>10,}")

                lines.append(f"\nLast updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                display = "```\n" + "\n".join(lines) + "\n```"
                await message_ref.edit(content=display)

            except Exception as e:
                print(f"⚠️ Failed to update wallet view: {e}")
            await asyncio.sleep(60)

    @client.event
    async def on_ready():
        print(f"📰 InfoBot connected as {client.user}")
        client.loop.create_task(update_loop())

    async def runner():
        async def shutdown_watcher():
            while not shutdown_event.is_set():
                await asyncio.sleep(1)
            print("🔻 Shutdown signal received. Closing Info Bot...")
            await client.close()

        try:
            asyncio.create_task(shutdown_watcher())
            await client.start(TOKEN)
        except Exception as e:
            print(f"❌ InfoBot runner error: {e}")
        finally:
            await client.close()

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(runner())
    finally:
        loop.close()
        print("🔻 InfoBot has shut down.")


if __name__ == "__main__":
    import threading
    shutdown_event = threading.Event()
    run_bot(shutdown_event)
