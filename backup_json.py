import os
import time
import zipfile
import datetime

BACKUP_DIR = "backup"
MAX_AGE_HOURS = 72
BACKUP_INTERVAL_SECONDS = 3600  # 1 hour

def create_backup():
    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    zip_name = f"backup_{timestamp}.zip"
    os.makedirs(BACKUP_DIR, exist_ok=True)
    zip_path = os.path.join(BACKUP_DIR, zip_name)

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in os.listdir():
            if file.endswith(".json") and os.path.isfile(file):
                zipf.write(file)
    print(f"[{timestamp}] Created backup: {zip_path}")

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

def run_backup_loop():
    while True:
        try:
            create_backup()
            cleanup_old_backups()
        except Exception as e:
            print(f"❌ Backup error: {e}")
        time.sleep(BACKUP_INTERVAL_SECONDS)

if __name__ == "__main__":
    run_backup_loop()