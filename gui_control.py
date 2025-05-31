import tkinter as tk
import ttkbootstrap as ttk
import subprocess
import os
import threading
import time
import sys
import signal
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Paths to the scripts to be controlled
SCRIPTS = {
    "TX Worker": os.path.join(PROJECT_ROOT, "core", "tx_worker.py"),
    "Backup Loop": os.path.join(PROJECT_ROOT, "backup_json.py"),
    "Tipping Bot": os.path.join(PROJECT_ROOT, "bots", "tipping_bot.py"),
    "Catch Bot": os.path.join(PROJECT_ROOT, "bots", "catch_bot.py"),
    "Raffle Bot": os.path.join(PROJECT_ROOT, "bots", "raffle_bot.py")
}

# Process status: {name: subprocess.Popen}
PROCESSES = {}
STATUSES = {}

LOGFILE = "debug.log"
LOG_START_LINE = 0

def log(msg):
    with open(LOGFILE, "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")

def start_script(name, path, update_status_callback):
    try:
        log(f"Starting {name}")
        env = os.environ.copy()
        env["PYTHONPATH"] = PROJECT_ROOT
        proc = subprocess.Popen(
            ["python3", path],
            stdout=open(LOGFILE, "a"),
            stderr=subprocess.STDOUT,
            cwd=PROJECT_ROOT,
            env=env,
            preexec_fn=os.setsid if os.name != "nt" else None,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        )
        PROCESSES[name] = proc
        STATUSES[name] = "running"
    except Exception as e:
        log(f"Failed to start {name}: {e}")
        STATUSES[name] = "error"
    update_status_callback()

def stop_script(name, update_status_callback):
    proc = PROCESSES.get(name)
    if proc and proc.poll() is None:
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            else:
                subprocess.call(["taskkill", "/F", "/T", "/PID", str(proc.pid)])
        except Exception as e:
            log(f"Error terminating {name}: {e}")
        log(f"Terminated {name}")
        STATUSES[name] = "stopped"
    else:
        log(f"{name} is not running")
        STATUSES[name] = "stopped"
    update_status_callback()

def check_status_loop(update_status_callback):
    while True:
        for name, proc in PROCESSES.items():
            if proc.poll() is not None and STATUSES[name] != "stopped":
                STATUSES[name] = "error"
        update_status_callback()
        time.sleep(5)

def update_log_display(log_widget):
    while True:
        try:
            with open(LOGFILE, "r") as f:
                lines = f.readlines()
            new_lines = lines[LOG_START_LINE:]
            log_widget.configure(state="normal")
            log_widget.delete("1.0", tk.END)
            log_widget.insert(tk.END, "".join(new_lines[-20:]))
            log_widget.configure(state="disabled")
            log_widget.see(tk.END)
        except Exception:
            pass
        time.sleep(5)

def create_gui():
    root = ttk.Window(themename="darkly")
    root.title("CARP Bot Controller")
    root.geometry("500x500")

    status_labels = {}
    toggle_buttons = {}

    def update_status():
        for name in SCRIPTS.keys():
            status = STATUSES.get(name, "stopped")
            color = {"running": "green", "stopped": "gray", "error": "red"}.get(status, "gray")
            status_labels[name].configure(background=color)
            if status == "running":
                toggle_buttons[name].configure(text="OFF", bootstyle="danger")
            else:
                toggle_buttons[name].configure(text="ON", bootstyle="success")

    def toggle_button_action(name, button, status_label):
        status = STATUSES.get(name, "stopped")
        button.configure(state="disabled")
        def run():
            if status == "running":
                stop_script(name, update_status)
            else:
                start_script(name, SCRIPTS[name], update_status)
            button.configure(state="normal")
        threading.Thread(target=run, daemon=True).start()

    for idx, (name, path) in enumerate(SCRIPTS.items()):
        label = ttk.Label(root, text=name)
        label.grid(row=idx, column=0, sticky="w", padx=20, pady=5)

        btn = ttk.Button(root, text="ON", width=10, bootstyle="success")
        btn.grid(row=idx, column=1, padx=10, pady=5)
        status = tk.Label(root, text="     ", background="gray", borderwidth=1, relief="solid")
        status.grid(row=idx, column=2, padx=10, pady=5)

        status_labels[name] = status
        toggle_buttons[name] = btn
        STATUSES[name] = "stopped"

        btn.configure(command=lambda n=name, b=btn, s=status: toggle_button_action(n, b, s))

    # Add a Text widget for log display
    log_text = tk.Text(root, height=15, background="black", foreground="lime", insertbackground="lime",
                       font=("Consolas", 10), state="disabled")
    log_text.grid(row=len(SCRIPTS), column=0, columnspan=3, sticky="nsew", padx=10, pady=10)

    # Configure grid weights for resizing
    root.grid_rowconfigure(len(SCRIPTS), weight=1)
    root.grid_columnconfigure(0, weight=1)
    root.grid_columnconfigure(1, weight=0)
    root.grid_columnconfigure(2, weight=0)

    global LOG_START_LINE
    try:
        with open(LOGFILE, "r") as f:
            LOG_START_LINE = len(f.readlines())
    except Exception:
        LOG_START_LINE = 0

    threading.Thread(target=check_status_loop, args=(update_status,), daemon=True).start()
    threading.Thread(target=update_log_display, args=(log_text,), daemon=True).start()

    def on_close():
        for name, proc in PROCESSES.items():
            if proc and proc.poll() is None:
                try:
                    if os.name != "nt":
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    else:
                        subprocess.call(["taskkill", "/F", "/T", "/PID", str(proc.pid)])
                    log(f"Cleaned up {name} on GUI close")
                except Exception as e:
                    log(f"Failed to terminate {name} on close: {e}")
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()

if __name__ == "__main__":
    create_gui()