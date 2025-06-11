import os
import sys
from dotenv import load_dotenv

# Dynamic base directory detection (for PyInstaller-compiled .exe or normal Python)
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load environment variables from .env in the main directory
load_dotenv(os.path.join(BASE_DIR, ".env"))

# File and directory paths
DATA_DIR = os.path.join(BASE_DIR, "data")
BACKUP_DIR = os.path.join(BASE_DIR, "backup")
CORE_DIR = os.path.join(BASE_DIR, "core")
BOTS_DIR = os.path.join(BASE_DIR, "bots")
FISH_IMAGES_DIR = os.path.join(BASE_DIR, "fish_images")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# Individual files
DEBUG_FILE = os.path.join(BASE_DIR, "debug.log")
WALLET_FILE = os.path.join(DATA_DIR, "wallet_store.json")
LOCKFILE = WALLET_FILE + ".lock"
TICKETS_FILE = os.path.join(DATA_DIR, "raffle_tickets.json")
PENDING_FILE = os.path.join(DATA_DIR, "pending_tx.json")
TX_LOG_FILE = os.path.join(DATA_DIR, "tx_log.json")
REJECTED_LOG_FILE = os.path.join(DATA_DIR, "rejected_tx_log.json")
LEADERBOARD_FILE = os.path.join(DATA_DIR, "fish_leaderboard.json")
RAFFLES_FILE = os.path.join(DATA_DIR, "raffles.json")
WINNERS_FILE = os.path.join(DATA_DIR, "raffle_winners.json")
FACTORY_FILE = os.path.join(DATA_DIR, "factory_data.json")
