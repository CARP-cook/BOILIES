# tx_worker.py
import time
from filelock import FileLock
from core.tx_utils import (
    load_json,
    save_json,
    append_to_tx_log,
    append_to_rejected_log,
    load_tickets,
    save_tickets
)

from core.tx_utils import WALLET_FILE, PENDING_FILE, LOCKFILE


def process_pending_transactions():
    print("🔄 TX worker started...")
    while True:
        # print("🔄 Checking for pending transactions...")
        with FileLock(LOCKFILE):
            pending = load_json(PENDING_FILE)
            wallet = load_json(WALLET_FILE)
            txs = pending.get("txs", [])
            # print(f"📦 Found {len(txs)} pending transaction(s).")
            processed = []
            rejected = []

            for tx in txs:
                try:
                    print(f"\n⚙️ Processing TX: {tx}")
                    uid = tx["user_id"]
                    if uid not in wallet:
                        print(f"➕ Creating wallet for user {uid}")
                        wallet[uid] = {"name": tx["username"], "carp_balance": 0, "nonce": 0}
                    elif wallet[uid]["name"] != tx["username"]:
                        print(f"📝 Updating username for {uid} to {tx['username']}")
                        wallet[uid]["name"] = tx["username"]

                    nonce = tx.get("nonce")
                    expected_nonce = wallet[uid]["nonce"] + 1
                    print(f"🔢 Nonce in TX: {nonce}, Expected: {expected_nonce}")

                    if nonce is None:
                        print("❌ Rejected: Missing nonce.")
                        append_to_rejected_log(tx, "Missing nonce")
                        rejected.append(tx)
                        continue

                    if nonce != expected_nonce:
                        print("❌ Rejected: Invalid nonce.")
                        append_to_rejected_log(tx, f"Invalid nonce (expected {expected_nonce}, got {nonce})")
                        rejected.append(tx)
                        continue

                    tx_type = tx["type"]

                    if tx_type in ["tip", "bait", "reward"]:
                        print(f"💸 Handling {tx_type} transaction")
                        to = tx["to"]
                        if wallet[uid]["carp_balance"] < tx["amount"]:
                            print("❌ Rejected: Insufficient balance.")
                            append_to_rejected_log(tx, "Insufficient balance")
                            rejected.append(tx)
                            continue

                        if to not in wallet:
                            print(f"➕ Creating recipient wallet for {to}")
                            wallet[to] = {"name": tx["to_username"], "carp_balance": 0, "nonce": 0}
                        elif wallet[to]["name"] != tx["to_username"]:
                            print(f"📝 Updating recipient username for {to}")
                            wallet[to]["name"] = tx["to_username"]

                        wallet[uid]["carp_balance"] -= tx["amount"]
                        wallet[to]["carp_balance"] += tx["amount"]
                        wallet[uid]["nonce"] = nonce
                        append_to_tx_log(tx)
                        # if tx_type != "bait":
                        #     append_to_tx_log({**tx, "type": "receive"})
                        processed.append(tx)
                        print(f"✅ Processed {tx_type} transaction.")

                    elif tx_type == "mint":
                        print("🪙 Handling mint transaction")
                        wallet[uid]["carp_balance"] += tx["amount"]
                        wallet[uid]["nonce"] = nonce
                        append_to_tx_log(tx)
                        processed.append(tx)
                        print("✅ Mint transaction processed.")

                    elif tx_type == "buyticket":
                        print("🎟 Handling buyticket transaction")
                        raffle_name = tx.get("raffle")
                        ticket_count = tx.get("ticket_count", 0)
                        amount = tx.get("amount", 0)

                        if not raffle_name or ticket_count <= 0 or amount <= 0:
                            print("❌ Rejected: Invalid raffle ticket data.")
                            append_to_rejected_log(tx, "Invalid buyticket fields")
                            rejected.append(tx)
                            continue

                        if wallet[uid]["carp_balance"] < amount:
                            print("❌ Rejected: Insufficient balance.")
                            append_to_rejected_log(tx, "Insufficient balance for buyticket")
                            rejected.append(tx)
                            continue

                        tickets = load_tickets()
                        if raffle_name not in tickets:
                            tickets[raffle_name] = {}

                        current_tickets = tickets[raffle_name].get(uid, 0)
                        tickets[raffle_name][uid] = current_tickets + ticket_count
                        save_tickets(tickets)

                        wallet[uid]["carp_balance"] -= amount
                        wallet[to]["carp_balance"] += amount
                        wallet[uid]["nonce"] = nonce
                        append_to_tx_log(tx)
                        processed.append(tx)
                        print(f"✅ Buyticket transaction processed: {ticket_count} tickets for {raffle_name}.")

                    else:
                        print("❌ Rejected: Unknown transaction type.")
                        append_to_rejected_log(tx, "Unknown transaction type")
                        rejected.append(tx)

                except Exception as e:
                    print(f"🔥 Exception while processing TX: {e}")
                    append_to_rejected_log(tx, f"Exception: {e}")
                    rejected.append(tx)

            # Remove processed or rejected TXs
            txs = [tx for tx in txs if tx not in processed and tx not in rejected]
            pending["txs"] = txs
            save_json(PENDING_FILE, pending)
            save_json(WALLET_FILE, wallet)
            # print(f"✅ Updated wallet and pending tx files. Sleeping...\n")

        time.sleep(10)


if __name__ == "__main__":
    process_pending_transactions()