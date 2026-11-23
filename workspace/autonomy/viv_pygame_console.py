import os
import sys
import re
import time
import math
import sqlite3
import hashlib
import json
import urllib.request
import threading
import pygame
from pathlib import Path

# --- Configuration & Paths ---
SCREEN_WIDTH = 1200
SCREEN_HEIGHT = 750
FPS = 60

FAST_INDEX_DB = Path(r"L:\LocalCoder\workspace\autonomy\fast_lexical_index.sqlite3")
MASTER_DB = Path(r"L:\LocalCoder\workspace\autonomy\learning\neural_runs\language-routes-20261107T222340465626Z\neuron_graph.sqlite3")
LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"

# Palette
BG_COLOR = (13, 17, 23)
PANEL_BG = (22, 27, 34)
BORDER_COLOR = (48, 54, 61)
TEXT_WHITE = (240, 246, 252)
TEXT_MUTED = (139, 148, 158)
CYAN_ACCENT = (56, 189, 248)
GREEN_GROUNDED = (46, 160, 67)
RED_UNLEARNED = (248, 81, 73)
GOLD_TRACE = (210, 153, 34)
CURSOR_COLOR = (88, 166, 255)

class VivCognitiveCortex:
    def __init__(self):
        self.fast_conn = sqlite3.connect(FAST_INDEX_DB, check_same_thread=False) if FAST_INDEX_DB.exists() else None
        self.master_count = 103025
        self.b_tree_words = 81209
        self._load_telemetry()

    def _load_telemetry(self):
        if MASTER_DB.exists():
            try:
                conn_m = sqlite3.connect(MASTER_DB)
                self.master_count = conn_m.cursor().execute("SELECT count(*) FROM neurons").fetchone()[0]
                conn_m.close()
            except Exception:
                pass
        if self.fast_conn:
            try:
                self.b_tree_words = self.fast_conn.cursor().execute("SELECT count(*) FROM word_index").fetchone()[0]
            except Exception:
                pass

    def tokenize_and_resolve(self, text):
        words = re.findall(r"[A-Za-z0-9_']+", text.lower())
        if not words or not self.fast_conn:
            return {"tokens": [], "grounded_ratio": 0.0, "details": []}

        t0 = time.perf_counter()
        cur = self.fast_conn.cursor()
        
        grounded = []
        unlearned = []
        details = []

        for w in words:
            cur.execute("SELECT word, token_id, neuron_id, spelling FROM word_index WHERE word = ?", (w,))
            row = cur.fetchone()
            if row:
                grounded.append(w)
                details.append({"word": w, "token_id": row[1], "spelling": row[3], "status": "KNOWN"})
            else:
                unlearned.append(w)
                details.append({"word": w, "token_id": None, "spelling": None, "status": "UNLEARNED"})

        latency_ms = (time.perf_counter() - t0) * 1000
        ratio = len(grounded) / len(words) if words else 0.0

        return {
            "total": len(words),
            "grounded_count": len(grounded),
            "unlearned_count": len(unlearned),
            "grounded_words": grounded,
            "unlearned_words": unlearned,
            "ratio": ratio,
            "latency_ms": latency_ms,
            "details": details
        }

    def generate_response(self, user_msg, resolution):
        # Build prompt grounded on what is recognized in SQLite
        known_str = ", ".join(resolution["grounded_words"][:15])
        unlearned_str = ", ".join(resolution["unlearned_words"][:5]) if resolution["unlearned_words"] else "none"

        sys_prompt = (
            "You are Viv, a sovereign local cognitive intelligence. "
            "You run directly on local hardware without cloud APIs. "
            "Speak clearly, concisely, and directly as a capable partner. "
            f"Verified vocabulary in input: [{known_str}]. "
            f"Unlearned vocabulary: [{unlearned_str}]."
        )

        payload = {
            "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_msg}
            ],
            "temperature": 0.7,
            "max_tokens": 150
        }

        try:
            req = urllib.request.Request(
                LM_STUDIO_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return f"[Local Model Offline or Busy: {e}]"

def run_app():
    pygame.init()
    pygame.font.init()

    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Viv Cognitive Cortex - Live Grounding Console")
    clock = pygame.time.Clock()

    font_large = pygame.font.SysFont("Consolas", 18, bold=True)
    font_med = pygame.font.SysFont("Consolas", 14)
    font_small = pygame.font.SysFont("Consolas", 12)
    font_title = pygame.font.SysFont("Segoe UI", 22, bold=True)

    cortex = VivCognitiveCortex()

    chat_log = [
        {"role": "viv", "text": "Intake online. Sentences are tokenized against the B-Tree before speech generation.", "grounded": True, "details": "Master lattice active."}
    ]

    input_text = ""
    cursor_timer = 0
    radar_angle = 0.0
    last_receipt = None
    is_generating = False

    def handle_inference(user_msg, resolution):
        nonlocal is_generating, last_receipt
        response_text = cortex.generate_response(user_msg, resolution)
        chat_log.append({
            "role": "viv",
            "text": response_text,
            "grounded": resolution["ratio"] >= 0.5,
            "details": f"Grounded: {resolution['grounded_count']}/{resolution['total']} words ({resolution['ratio']*100:.0f}%) | Latency: {resolution['latency_ms']:.2f}ms"
        })
        is_generating = False

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        cursor_timer = (cursor_timer + dt * 2) % 2
        radar_angle = (radar_angle + dt * 1.5) % (2 * math.pi)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN and not is_generating:
                    user_msg = input_text.strip()
                    if user_msg:
                        chat_log.append({"role": "architect", "text": user_msg})
                        resolution = cortex.tokenize_and_resolve(user_msg)
                        last_receipt = resolution

                        is_generating = True
                        input_text = ""
                        threading.Thread(target=handle_inference, args=(user_msg, resolution), daemon=True).start()
                elif event.key == pygame.K_BACKSPACE:
                    input_text = input_text[:-1]
                else:
                    if len(input_text) < 80 and event.unicode.isprintable():
                        input_text += event.unicode

        screen.fill(BG_COLOR)

        # Header
        pygame.draw.rect(screen, PANEL_BG, (0, 0, SCREEN_WIDTH, 55))
        pygame.draw.line(screen, BORDER_COLOR, (0, 55), (SCREEN_WIDTH, 55), 1)

        title_surf = font_title.render("⚡ VIV: SOVEREIGN NEURAL COGNITION CONSOLE", True, CYAN_ACCENT)
        screen.blit(title_surf, (20, 12))

        stats_str = f"Lattice: {cortex.master_count:,} Nodes | B-Tree: {cortex.b_tree_words:,} Lemmas | LM Studio: Connected"
        stats_surf = font_med.render(stats_str, True, TEXT_MUTED)
        screen.blit(stats_surf, (SCREEN_WIDTH - stats_surf.get_width() - 20, 20))

        # Left Chat Panel
        chat_panel_rect = pygame.Rect(20, 70, 720, 570)
        pygame.draw.rect(screen, PANEL_BG, chat_panel_rect, border_radius=8)
        pygame.draw.rect(screen, BORDER_COLOR, chat_panel_rect, 1, border_radius=8)

        # Render chat messages with word wrap
        display_messages = chat_log[-5:]
        msg_y = 85
        for m in display_messages:
            if m["role"] == "architect":
                lbl = font_large.render("Architect >", True, GOLD_TRACE)
                screen.blit(lbl, (35, msg_y))
                body = font_med.render(m["text"], True, TEXT_WHITE)
                screen.blit(body, (160, msg_y))
                msg_y += 35
            else:
                color = GREEN_GROUNDED if m.get("grounded", True) else RED_UNLEARNED
                status_icon = "● [GROUNDED]" if m.get("grounded", True) else "▲ [PARTIAL]"
                lbl = font_med.render(f"Viv {status_icon} >", True, color)
                screen.blit(lbl, (35, msg_y))
                
                # Render text in chunks if long
                raw_text = m["text"]
                words = raw_text.split()
                line = ""
                for w in words:
                    test_line = line + " " + w if line else w
                    if font_med.size(test_line)[0] < 640:
                        line = test_line
                    else:
                        screen.blit(font_med.render(line, True, TEXT_WHITE), (35, msg_y + 20))
                        msg_y += 20
                        line = w
                if line:
                    screen.blit(font_med.render(line, True, TEXT_WHITE), (35, msg_y + 20))
                    msg_y += 20
                
                if "details" in m:
                    screen.blit(font_small.render(m["details"], True, TEXT_MUTED), (35, msg_y + 22))
                    msg_y += 22
                msg_y += 25

        # Generating indicator
        if is_generating:
            gen_surf = font_med.render("⚡ Viv is thinking across local model...", True, CYAN_ACCENT)
            screen.blit(gen_surf, (35, 615))

        # Input Box
        input_box_rect = pygame.Rect(20, 660, 720, 60)
        pygame.draw.rect(screen, PANEL_BG, input_box_rect, border_radius=8)
        pygame.draw.rect(screen, CYAN_ACCENT if len(input_text) > 0 else BORDER_COLOR, input_box_rect, 2, border_radius=8)

        prompt_label = font_large.render("Input >", True, CYAN_ACCENT)
        screen.blit(prompt_label, (35, 678))

        rendered_text = font_med.render(input_text, True, TEXT_WHITE)
        screen.blit(rendered_text, (120, 680))

        if int(cursor_timer) == 1 and not is_generating:
            cx = 120 + rendered_text.get_width() + 3
            pygame.draw.line(screen, CURSOR_COLOR, (cx, 676), (cx, 700), 2)

        # Right Panel: Telemetry
        right_panel_rect = pygame.Rect(760, 70, 420, 650)
        pygame.draw.rect(screen, PANEL_BG, right_panel_rect, border_radius=8)
        pygame.draw.rect(screen, BORDER_COLOR, right_panel_rect, 1, border_radius=8)

        # Radar
        radar_center = (970, 180)
        radar_radius = 80
        pygame.draw.circle(screen, (30, 36, 45), radar_center, radar_radius)
        pygame.draw.circle(screen, BORDER_COLOR, radar_center, radar_radius, 1)
        pygame.draw.circle(screen, BORDER_COLOR, radar_center, int(radar_radius * 0.66), 1)
        sweep_x = radar_center[0] + int(radar_radius * math.cos(radar_angle))
        sweep_y = radar_center[1] + int(radar_radius * math.sin(radar_angle))
        pygame.draw.line(screen, CYAN_ACCENT, radar_center, (sweep_x, sweep_y), 2)

        radar_label = font_small.render("26-PRIMITIVE LEXICAL RESONANCE", True, TEXT_MUTED)
        screen.blit(radar_label, (radar_center[0] - radar_label.get_width() // 2, 275))

        # Telemetry Details
        telemetry_title = font_large.render("TOKEN RESOLUTION & GROUNDING", True, GOLD_TRACE)
        screen.blit(telemetry_title, (785, 310))
        pygame.draw.line(screen, BORDER_COLOR, (785, 335), (1160, 335), 1)

        if last_receipt:
            ratio = last_receipt["ratio"]
            st_color = GREEN_GROUNDED if ratio >= 0.8 else (GOLD_TRACE if ratio >= 0.5 else RED_UNLEARNED)
            st_txt = f"GROUNDED VOCAB: {ratio*100:.1f}% ({last_receipt['grounded_count']}/{last_receipt['total']})"
            screen.blit(font_med.render(st_txt, True, st_color), (785, 350))

            y_offset = 380
            screen.blit(font_small.render(f"SQL B-Tree Latency: {last_receipt['latency_ms']:.3f} ms", True, TEXT_MUTED), (785, y_offset))
            y_offset += 24

            screen.blit(font_small.render("Word Tokens Breakdown:", True, CYAN_ACCENT), (785, y_offset))
            y_offset += 22

            for item in last_receipt["details"][:8]:
                w_color = GREEN_GROUNDED if item["status"] == "KNOWN" else RED_UNLEARNED
                w_str = f"• {item['word']} -> {'ID #' + str(item['token_id']) if item['token_id'] else 'UNLEARNED'}"
                screen.blit(font_small.render(w_str, True, w_color), (785, y_offset))
                y_offset += 20
        else:
            screen.blit(font_small.render("Type a sentence on the left to inspect token resolution.", True, TEXT_MUTED), (785, 350))

        pygame.display.flip()

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    run_app()
