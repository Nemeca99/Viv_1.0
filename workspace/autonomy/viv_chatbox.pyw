"""
viv_chatbox.pyw - Standalone Desktop GUI Chat Box for Travis Miner (The Architect)
Provides an interactive window to transmit thoughts/prompts directly into Viv's inbox
and observe her live responses and internal monologues in real-time.
"""

import json
import os
import sys
import time
import tkinter as tk
from tkinter import ttk, scrolledtext
from datetime import datetime
from pathlib import Path

INBOX_DIR = Path(r"E:\Viv_Sandbox\playground\inbox")
MONOLOGUE_FILE = Path(r"E:\Viv_Sandbox\playground\monologue\viv_monologue.md")

class VivChatboxApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Viv Sandbox — Architect Direct Transmitter")
        self.root.geometry("900x700")
        self.root.minsize(700, 500)
        self.root.configure(bg="#121212")

        self.last_mtime = 0
        self.last_size = 0

        self._build_ui()
        self._poll_monologue()

    def _build_ui(self):
        # Header Frame
        header = tk.Frame(self.root, bg="#1a1a1a", height=50)
        header.pack(fill=tk.X, side=tk.TOP)

        title = tk.Label(
            header,
            text="AIOS V2 // VIV COGNITIVE MONITOR & TRANSMITTER",
            font=("Consolas", 13, "bold"),
            fg="#00e5ff",
            bg="#1a1a1a",
            padx=15,
            pady=10
        )
        title.pack(side=tk.LEFT)

        status_badge = tk.Label(
            header,
            text="[AIRGAP ISOLATION: ACTIVE | TARGET: DRIVE E:]",
            font=("Consolas", 9),
            fg="#76ff03",
            bg="#1a1a1a",
            padx=15
        )
        status_badge.pack(side=tk.RIGHT)

        # Monologue View Frame
        view_frame = tk.Frame(self.root, bg="#121212")
        view_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(8, 4))

        view_label = tk.Label(
            view_frame,
            text="LIVE LAB NOTEBOOK & MONOLOGUE STREAM (E:\\Viv_Sandbox\\playground\\monologue\\viv_monologue.md):",
            font=("Consolas", 9, "bold"),
            fg="#888888",
            bg="#121212"
        )
        view_label.pack(anchor=tk.W, pady=(0, 4))

        self.text_view = scrolledtext.ScrolledText(
            view_frame,
            wrap=tk.WORD,
            bg="#181818",
            fg="#e0e0e0",
            insertbackground="#ffffff",
            font=("Consolas", 10),
            padx=10,
            pady=10,
            relief=tk.FLAT,
            borderwidth=1
        )
        self.text_view.pack(fill=tk.BOTH, expand=True)

        # Input Frame
        input_frame = tk.Frame(self.root, bg="#1a1a1a", padx=12, pady=10)
        input_frame.pack(fill=tk.X, side=tk.BOTTOM)

        prompt_label = tk.Label(
            input_frame,
            text="Transmit to Viv (Press Ctrl+Enter or click Transmit):",
            font=("Consolas", 9, "bold"),
            fg="#ffab00",
            bg="#1a1a1a"
        )
        prompt_label.pack(anchor=tk.W, pady=(0, 4))

        entry_row = tk.Frame(input_frame, bg="#1a1a1a")
        entry_row.pack(fill=tk.X)

        self.msg_entry = tk.Text(
            entry_row,
            height=3,
            bg="#242424",
            fg="#ffffff",
            insertbackground="#00e5ff",
            font=("Consolas", 11),
            padx=8,
            pady=6,
            relief=tk.FLAT,
            borderwidth=1
        )
        self.msg_entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        self.msg_entry.bind("<Control-Return>", lambda event: self.send_message())
        self.msg_entry.focus_set()

        send_btn = tk.Button(
            entry_row,
            text="TRANSMIT\nTO VIV",
            font=("Consolas", 10, "bold"),
            bg="#00838f",
            fg="#ffffff",
            activebackground="#00acc1",
            activeforeground="#ffffff",
            width=12,
            relief=tk.FLAT,
            command=self.send_message
        )
        send_btn.pack(side=tk.RIGHT, fill=tk.BOTH)

        self.status_bar = tk.Label(
            input_frame,
            text="Ready. Transmissions appear directly in Viv's journal.",
            font=("Consolas", 8),
            fg="#777777",
            bg="#1a1a1a"
        )
        self.status_bar.pack(anchor=tk.W, pady=(5, 0))

    def send_message(self):
        text = self.msg_entry.get("1.0", tk.END).strip()
        if not text:
            return

        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        msg_id = f"msg_{int(time.time())}_{os.getpid()}"
        target = INBOX_DIR / f"{msg_id}.json"
        payload = {
            "id": msg_id,
            "author": "Travis Miner (The Architect)",
            "timestamp": datetime.now().isoformat(),
            "message": text
        }
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        self.msg_entry.delete("1.0", tk.END)
        self.status_bar.config(
            text=f"Transmitted at {datetime.now().strftime('%I:%M:%S %p')} — Waiting for Viv's daemon to digest...",
            fg="#00e5ff"
        )

    def _poll_monologue(self):
        try:
            if MONOLOGUE_FILE.exists():
                mtime = MONOLOGUE_FILE.stat().st_mtime
                size = MONOLOGUE_FILE.stat().st_size
                if mtime != self.last_mtime or size != self.last_size:
                    self.last_mtime = mtime
                    self.last_size = size
                    content = MONOLOGUE_FILE.read_text(encoding="utf-8", errors="replace")
                    
                    # Keep scroll position at end if user was near end
                    self.text_view.delete("1.0", tk.END)
                    self.text_view.insert(tk.END, content)
                    self.text_view.see(tk.END)
        except Exception:
            pass

        self.root.after(1500, self._poll_monologue)

def launch_gui():
    root = tk.Tk()
    app = VivChatboxApp(root)
    root.mainloop()

if __name__ == "__main__":
    launch_gui()
