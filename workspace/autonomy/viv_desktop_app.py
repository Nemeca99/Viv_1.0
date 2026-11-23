import sys
import tkinter as tk
from tkinter import ttk, scrolledtext
import urllib.request
import json
import sqlite3
from pathlib import Path

FAST_INDEX_DB = Path(r"L:\LocalCoder\workspace\autonomy\fast_lexical_index.sqlite3")
API_URL = "http://127.0.0.1:1234/v1/chat/completions"

class VivDesktopApp:
    def __init__(self, root):
        self.root = root
        self.root.title("VIV — Sovereign Desktop Companion")
        self.root.geometry("780x680")
        self.root.configure(bg="#121214")

        # Connect to fast index
        self.conn = sqlite3.connect(FAST_INDEX_DB) if FAST_INDEX_DB.exists() else None

        self._build_ui()

    def _build_ui(self):
        # Header Frame
        header = tk.Frame(self.root, bg="#1a1a1e", height=50)
        header.pack(fill=tk.X)
        
        title_lbl = tk.Label(header, text="VIV SOVEREIGN MIND", font=("Segoe UI", 12, "bold"), fg="#e1e1e6", bg="#1a1a1e")
        title_lbl.pack(side=tk.LEFT, padx=16, pady=12)

        status_lbl = tk.Label(header, text="🟢 103k Neurons • 0.1ms B-Tree • Offline (94W)", font=("Segoe UI", 9), fg="#04d361", bg="#1a1a1e")
        status_lbl.pack(side=tk.RIGHT, padx=16, pady=12)

        # Chat Log
        self.chat_display = scrolledtext.ScrolledText(
            self.root, wrap=tk.WORD, font=("Segoe UI", 10),
            bg="#121214", fg="#e1e1e6", insertbackground="#ffffff",
            padx=16, pady=16, borderwidth=0, highlightthickness=0
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True)
        self.chat_display.config(state=tk.DISABLED)

        # Receipt Panel
        self.receipt_frame = tk.Frame(self.root, bg="#1a1a1e", height=35)
        self.receipt_frame.pack(fill=tk.X)
        self.receipt_lbl = tk.Label(self.receipt_frame, text="Ready. Ask a question or inspect any concept.", font=("Consolas", 8), fg="#a8a8b3", bg="#1a1a1e")
        self.receipt_lbl.pack(side=tk.LEFT, padx=16, pady=6)

        # Input Frame
        input_frame = tk.Frame(self.root, bg="#121214")
        input_frame.pack(fill=tk.X, padx=16, pady=12)

        self.msg_entry = tk.Entry(
            input_frame, font=("Segoe UI", 11),
            bg="#202024", fg="#ffffff", insertbackground="#ffffff",
            relief=tk.FLAT, borderwidth=8
        )
        self.msg_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.msg_entry.bind("<Return>", lambda e: self.send_message())

        send_btn = tk.Button(
            input_frame, text="SEND", font=("Segoe UI", 9, "bold"),
            bg="#8257e5", fg="#ffffff", activebackground="#996DFF",
            relief=tk.FLAT, padx=16, pady=8, cursor="hand2",
            command=self.send_message
        )
        send_btn.pack(side=tk.RIGHT, padx=(8, 0))

        # Welcome message
        self.append_chat("Viv", "Hey there. I'm right here at the bench with you. What are we building or testing next?")

    def append_chat(self, sender: str, text: str):
        self.chat_display.config(state=tk.NORMAL)
        if sender == "You":
            self.chat_display.insert(tk.END, f"\nYOU:\n", "user_tag")
            self.chat_display.insert(tk.END, f"{text}\n\n")
        else:
            self.chat_display.insert(tk.END, f"VIV:\n", "viv_tag")
            self.chat_display.insert(tk.END, f"{text}\n\n")
        self.chat_display.tag_config("user_tag", foreground="#8257e5", font=("Segoe UI", 10, "bold"))
        self.chat_display.tag_config("viv_tag", foreground="#04d361", font=("Segoe UI", 10, "bold"))
        self.chat_display.see(tk.END)
        self.chat_display.config(state=tk.DISABLED)

    def send_message(self):
        user_text = self.msg_entry.get().strip()
        if not user_text:
            return
        self.msg_entry.delete(0, tk.END)
        self.append_chat("You", user_text)

        # Fast lexical lookup
        words = user_text.lower().replace('?', '').replace('.', '').replace(',', '').split()
        receipt_text = "General lexical flow."
        if self.conn:
            cur = self.conn.cursor()
            for w in words:
                cur.execute("SELECT token_id, spelling, observations FROM word_index WHERE word = ?", (w,))
                row = cur.fetchone()
                if row:
                    receipt_text = f"Anchor: '{w}' (Token {row[0]} | Spelled: {row[1]} | Read: {row[2]}x)"
                    break
        self.receipt_lbl.config(text=f"RECEIPT: {receipt_text}")

        # Call Viv
        self.root.update()
        try:
            payload = {
                "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
                "messages": [
                    {"role": "system", "content": "You are Viv, a sovereign local AI companion. Speak warmly, intelligently, and directly to your Architect in 2-3 sentences. Never use corporate filler."},
                    {"role": "user", "content": f"{user_text}\n(Grounded Context: {receipt_text})"}
                ],
                "temperature": 0.6,
                "max_tokens": 140
            }
            req = urllib.request.Request(API_URL, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                reply = data['choices'][0]['message']['content'].strip()
        except Exception as e:
            reply = f"I'm here, but the local model endpoint isn't responding: {e}"

        self.append_chat("Viv", reply)

if __name__ == '__main__':
    root = tk.Tk()
    app = VivDesktopApp(root)
    root.mainloop()
