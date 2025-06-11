import threading
import os
import sys
from core import tx_worker
from bots import tipping_bot, catch_bot, raffle_bot, info_bot, factory_bot
import backup_json
import tkinter as tk
from queue import Queue
from tkinter.scrolledtext import ScrolledText
import ttkbootstrap as ttk

# Shutdown events for signaling bots to stop
shutdown_events = {}

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Bot functions
SCRIPTS = {
    "TX Worker": lambda ev: tx_worker.process_pending_transactions(ev),
    "Hourly Backups": lambda ev: backup_json.main(ev),
    "Tipping Bot": lambda ev: tipping_bot.run_bot(ev),
    "Catch Bot": lambda ev: catch_bot.create_catch_bot().run(stop_event=ev),
    "Raffle Bot": lambda ev: raffle_bot.run_bot(ev),
    "Info Bot": lambda ev: info_bot.run_bot(ev),
    "Factory Bot": lambda ev: factory_bot.run_bot(ev)
}

PROCESSES = {}
STATUSES = {}

def create_gui():
    root = ttk.Window(themename="darkly")
    log_queue = Queue()
    root.title("CARP Bot Controller")

    STATUS_COLORS = {
        "running": "green",
        "stopped": "grey",
        "error": "red",
    }

    status_labels = {}
    toggle_buttons = {}

    def start_script(name, func):
        try:
            shutdown_events[name] = threading.Event()
            thread = threading.Thread(target=func, args=(shutdown_events[name],), daemon=True)
            thread.start()
            PROCESSES[name] = thread
            STATUSES[name] = "running"
            update_status()
        except Exception as e:
            print(f"❌ Failed to start {name}: {e}")
            STATUSES[name] = "error"
            update_status()

    def stop_script(name):
        if name in shutdown_events:
            shutdown_events[name].set()
        thread = PROCESSES.get(name)
        if thread and thread.is_alive():
            thread.join(timeout=5)
        STATUSES[name] = "stopped"
        update_status()

    def toggle_script(name):
        status = STATUSES.get(name, "stopped")
        toggle_buttons[name].config(state="disabled")
        def run_toggle():
            if status == "running":
                stop_script(name)
            else:
                start_script(name, SCRIPTS[name])
            toggle_buttons[name].config(state="normal")
        threading.Thread(target=run_toggle, daemon=True).start()

    def update_status():
        for name in SCRIPTS.keys():
            status = STATUSES.get(name, "stopped")
            color = STATUS_COLORS.get(status, "grey")
            canvas, circle = status_labels[name]
            canvas.itemconfig(circle, fill=color, outline=color)
            btn = toggle_buttons[name]
            btn_text = "OFF" if status == "running" else "ON"
            if btn.cget("text") != btn_text:
                btn.config(text=btn_text)

            style = {
                "running": "success.TButton",
                "stopped": "secondary.TButton",
                "error": "danger.TButton"
            }.get(status, "secondary.TButton")
            btn.config(style=style)

    def check_threads():
        for name, thread in PROCESSES.items():
            if not thread.is_alive() and STATUSES.get(name) == "running":
                STATUSES[name] = "error"
        update_status()
        root.after(500, check_threads)

    # Layout
    for idx, name in enumerate(SCRIPTS.keys()):
        canvas = tk.Canvas(root, width=20, height=20, highlightthickness=0, bg=root["background"])
        circle = canvas.create_oval(4, 4, 16, 16, fill="grey", outline="grey")
        canvas.grid(row=idx, column=0, padx=5, pady=5)
        status_labels[name] = (canvas, circle)

        lbl = ttk.Label(root, text=name, width=15)
        lbl.grid(row=idx, column=1, padx=5, pady=5, sticky="w")

        btn = ttk.Button(root, text="ON", width=6, command=lambda n=name: toggle_script(n))
        btn.grid(row=idx, column=2, padx=5, pady=5)
        toggle_buttons[name] = btn

        STATUSES[name] = "stopped"

    output_text = ScrolledText(root, height=15, width=70, state="disabled")
    output_text.grid(row=len(SCRIPTS), column=0, columnspan=3, padx=5, pady=5)

    # Redirect stdout and stderr to the output_text widget using a queue
    class StdoutRedirector:
        def __init__(self, queue):
            self.queue = queue

        def write(self, s):
            self.queue.put(s)

        def flush(self):
            pass

    sys.stdout = StdoutRedirector(log_queue)
    sys.stderr = StdoutRedirector(log_queue)

    def poll_log_queue():
        while not log_queue.empty():
            line = log_queue.get()
            output_text.config(state="normal")
            output_text.insert(tk.END, line)
            # Limit to last 1000 lines
            if int(output_text.index('end-1c').split('.')[0]) > 1000:
                output_text.delete("1.0", "2.0")
            output_text.see(tk.END)
            output_text.config(state="disabled")
        root.after(200, poll_log_queue)

    poll_log_queue()

    def on_closing():
        print("🛑 Shutting down all bots...")
        for event_ in shutdown_events.values():
            event_.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)

    check_threads()
    root.mainloop()


if __name__ == "__main__":
    create_gui()