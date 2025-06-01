import os
import time
import zipfile
import datetime
import sys
from paths import BACKUP_DIR, DEBUG_FILE, DATA_DIR

# Optional: Nur loggen, wenn nicht in GUI-Umgebung
if __name__ != "__main__":
    sys.stdout = open(DEBUG_FILE, "a")
    sys.stderr = sys.stdout

MAX_AGE_HOURS = 72
BACKUP_INTERVAL_SECONDS = 3600  # 1 hour


def create_backup():
    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    zip_name = f"backup_{timestamp}.zip"
    os.makedirs(BACKUP_DIR, exist_ok=True)
    zip_path = os.path.join(BACKUP_DIR, zip_name)

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(DATA_DIR):
            for file in files:
                if file.endswith(".json"):
                    full_path = os.path.join(root, file)
                    arcname = os.path.relpath(str(full_path), start=str(DATA_DIR))
                    zipf.write(str(full_path), str(arcname))
    print(f"[{timestamp}] ✅ Created backup: {zip_path}")


def cleanup_old_backups():
    now = time.time()
    deleted = 0
    for file in os.listdir(BACKUP_DIR):
        path = os.path.join(BACKUP_DIR, file)
        if os.path.isfile(path) and file.endswith(".zip"):
            mtime = os.path.getmtime(path)
            age_hours = (now - mtime) / 3600
            if age_hours > MAX_AGE_HOURS:
                os.remove(path)
                deleted += 1
    if deleted:
        print(f"🧹 Deleted {deleted} old backup(s).")


def run_backup_loop(stop_event):
    print("🌀 Backup loop started.")
    while not stop_event.is_set():
        try:
            create_backup()
            cleanup_old_backups()
        except Exception as e:
            print(f"❌ Backup error: {e}")
        # Stop wait: returns early if stop_event is set
        if stop_event.wait(BACKUP_INTERVAL_SECONDS):
            break
    print("🛑 Backup loop stopped.")


def run_backup(stop_event):
    run_backup_loop(stop_event)


# Alias for external usage, e.g., from BOILIE_control
main = run_backup


if __name__ == "__main__":
    import threading
    run_backup(threading.Event())