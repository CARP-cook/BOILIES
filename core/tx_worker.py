# tx_worker.py
import sys
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
from paths import FACTORY_FILE
from paths import DEBUG_FILE
sys.stdout = open(DEBUG_FILE, "a")
sys.stderr = sys.stdout

def check_upgrade_completion():
    try:
        factory_data = load_json(FACTORY_FILE)
        current_time = int(time.time())
        updated = False

        for user_id, factory in factory_data.items():
            upgrade_time = factory.get("upgrade_ready_time")
            if upgrade_time is not None and current_time >= upgrade_time:
                factory["factory_level"] += 1
                factory["upgrade_ready_time"] = None
                print(f"🏭 Factory upgrade completed for user {user_id} to level {factory['factory_level']}")
                updated = True

            for idx, worker in enumerate(factory.get("workers", [])):
                w_u = worker.get("upgrade_ready_time")
                if w_u is not None and current_time >= w_u:
                    worker["stars"] += 1
                    worker["upgrade_ready_time"] = None
                    print(f"👷‍♂️ Worker {idx} upgraded for user {user_id} to {worker['stars']} stars")
                    updated = True

            for idx, machine in enumerate(factory.get("machines", [])):
                m_u = machine.get("upgrade_ready_time")
                if m_u is not None and current_time >= m_u:
                    machine["stars"] += 1
                    machine["upgrade_ready_time"] = None
                    print(f"🛠️ Machine {idx} upgraded for user {user_id} to {machine['stars']} stars")
                    updated = True

        if updated:
            save_json(FACTORY_FILE, factory_data)

    except Exception as e:
        print(f"⚠️ Error checking upgrade completion: {e}")


def process_pending_transactions(shutdown_event):
    print("🔄 TX worker started...")
    while not shutdown_event.is_set():
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
            check_upgrade_completion()
            # print(f"✅ Updated wallet and pending tx files. Sleeping...\n")

        time.sleep(5)
    print("🛑 TX worker stopped.")


import threading


def main():
    shutdown_event = threading.Event()
    process_pending_transactions(shutdown_event)


if __name__ == "__main__":
    main()