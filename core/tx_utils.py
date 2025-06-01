# tx_utils.py
import discord
import json
import os
import hashlib
from filelock import FileLock

from paths import WALLET_FILE, PENDING_FILE, LOCKFILE, TX_LOG_FILE, REJECTED_LOG_FILE, TICKETS_FILE

FISHING_BOT_ID = os.getenv("FISHING_BOT_ID")
MAX_LOG_SCAN = 2000  # Limit number of TXs to scan for duplicates


def get_or_create_wallet(user: discord.User):
    uid = str(user.id)
    with FileLock(LOCKFILE):
        wallets = load_json(WALLET_FILE)
        changed = False
        if uid not in wallets:
            wallets[uid] = {
                "name": str(user),
                "carp_balance": 0,
                "nonce": 0
            }
            changed = True
        else:
            if wallets[uid].get("name") != str(user):
                wallets[uid]["name"] = str(user)
                changed = True
            if "nonce" not in wallets[uid]:
                wallets[uid]["nonce"] = 0
                changed = True
        if changed:
            save_json(WALLET_FILE, wallets)
    return wallets[uid]


def get_or_create_wallet_by_id(user_id: str, username: str = None):
    with FileLock(LOCKFILE):
        wallets = load_json(WALLET_FILE)
        changed = False
        if user_id not in wallets:
            wallets[user_id] = {
                "name": username or user_id,
                "carp_balance": 0,
                "nonce": 0
            }
            changed = True
        else:
            if username and wallets[user_id].get("name") != username:
                wallets[user_id]["name"] = username
                changed = True
            if "nonce" not in wallets[user_id]:
                wallets[user_id]["nonce"] = 0
                changed = True
        if changed:
            save_json(WALLET_FILE, wallets)
    return wallets[user_id]


def load_json(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {"txs": []} if "pending" in path else {}


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def generate_tx_id(tx):
    tx_copy = dict(tx)
    tx_str = json.dumps(tx_copy, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(tx_str.encode("utf-8")).hexdigest()


def tx_exists(data, user_id, nonce):
    return any(tx["user_id"] == user_id and tx.get("nonce") == nonce for tx in data.get("txs", []))


def tx_id_exists(tx_id):
    for file in [PENDING_FILE, TX_LOG_FILE]:
        data = load_json(file)
        key = "txs" if "pending" in file else "log"
        for entry in data.get(key, []):
            if entry.get("tx_id") == tx_id:
                return True
    return False


def get_nonce(user_id: str) -> int:
    with FileLock(LOCKFILE):
        wallets = load_json(WALLET_FILE)
        if user_id in wallets:
            return wallets[user_id].get("nonce", 0) + 1
    return 1


def get_effective_balance(user_id):
    with FileLock(LOCKFILE):
        wallet = load_json(WALLET_FILE)
        pending = load_json(PENDING_FILE)

        # Subtract all own outgoing pending TXs
        pending_out = sum(
            tx.get("amount", 0)
            for tx in pending.get("txs", [])
            if tx.get("user_id") == user_id
        )

        balance = wallet.get(user_id, {}).get("carp_balance", 0)
        return balance - pending_out


def safe_append_tx(tx):
    with FileLock(LOCKFILE):
        data = load_json(PENDING_FILE)
        tx_log = load_json(TX_LOG_FILE)

        if tx_exists(data, tx["user_id"], tx["nonce"]):
            return False

        if "tx_id" not in tx:
            tx["tx_id"] = generate_tx_id(tx)

        # Check if tx_id already exists in pending
        if any(t.get("tx_id") == tx["tx_id"] for t in data.get("txs", [])):
            return False

        # Check last MAX_LOG_SCAN txs in tx_log
        if any(t.get("tx_id") == tx["tx_id"] for t in tx_log.get("log", [])[-MAX_LOG_SCAN:]):
            return False

        data["txs"].append(tx)
        save_json(PENDING_FILE, data)
        return True


def append_to_tx_log(entry):
    if "tx_id" not in entry:
        entry["tx_id"] = generate_tx_id(entry)
    tx_log = load_json(TX_LOG_FILE)
    tx_log.setdefault("log", []).append(entry)
    save_json(TX_LOG_FILE, tx_log)


def append_to_rejected_log(entry, reason):
    rej_log = load_json(REJECTED_LOG_FILE)
    rej_log.setdefault("rejected", []).append({"reason": reason, "tx": entry})
    save_json(REJECTED_LOG_FILE, rej_log)


def load_tickets():
    if os.path.exists(TICKETS_FILE):
        with open(TICKETS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_tickets(data):
    with open(TICKETS_FILE, "w") as f:
        json.dump(data, f, indent=2)