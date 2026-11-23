"""
viv_context_store.py — Memory Management Architecture (STM + Compaction + LTM Dump).
- STM (Short-Term Context): Active working memory & live chat transcript (Capacity: 10 turns max).
- Raw LTM Archive: When STM reaches capacity, raw transcript turns are dumped into raw LTM storage.
- Compaction: After raw LTM dump, STM is compacted into a high-density summary buffer.
"""
import json
import math
import pathlib
import re
import sys
from datetime import datetime, timezone

MEMORY_DIR = pathlib.Path("L:/LocalCoder/workspace/aios_rebuild/memory")
AIOS_REBUILD = pathlib.Path(__file__).resolve().parent / "aios_rebuild"
if str(AIOS_REBUILD) not in sys.path:
    sys.path.insert(0, str(AIOS_REBUILD))
from privacy_core.privacy_core import PrivacyCore

STM_FILE = MEMORY_DIR / "short_term_context.json"
LTM_RAW_FILE = MEMORY_DIR / "long_term_raw_dump.json"
LTM_ARCHIVE_FILE = MEMORY_DIR / "long_term_memory.json"
CHAT_HISTORY_FILE = MEMORY_DIR / "chat_transcript.json"

STM_CAPACITY = 10  # Max dialogue turns before compaction trigger
RAM_COMPACTION_PERCENT = 90.0
RAM_WRITE_HOLD_PERCENT = 95.0
RAM_COMPACTION_RESET_PERCENT = 85.0
MIN_MEMORY_DISK_FREE_BYTES = 2 * 1024 * 1024 * 1024


class MemoryPressureHold(RuntimeError):
    pass


class DualContextMemory:
    def __init__(self, privacy_core=None, memory_pressure_reader=None, disk_free_reader=None):
        self.privacy_core = privacy_core or PrivacyCore()
        self.memory_pressure_reader = memory_pressure_reader or self._read_memory_percent
        self.disk_free_reader = disk_free_reader or self._read_disk_free_bytes
        self._ram_pressure_compacted = False
        self.stm = self._load_json(STM_FILE, default={
            "active_task": "Idle / System Operations",
            "current_step": "Awaiting Operator Directive",
            "compacted_summary": "System online. Core foundation 13/13 bound.",
            "working_buffer": [],
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        self.ltm_raw = self._load_json(LTM_RAW_FILE, default=[])
        self.ltm_archive = self._load_json(LTM_ARCHIVE_FILE, default=[])
        self.chat_history = self._load_json(CHAT_HISTORY_FILE, default=[])

    @staticmethod
    def _read_memory_percent():
        try:
            import psutil

            percent = float(psutil.virtual_memory().percent)
        except (ImportError, OSError, AttributeError, TypeError, ValueError):
            return None
        return percent if math.isfinite(percent) and 0.0 <= percent <= 100.0 else None

    @staticmethod
    def _read_disk_free_bytes():
        try:
            import psutil

            drive = pathlib.Path(MEMORY_DIR).resolve().anchor
            return int(psutil.disk_usage(drive).free)
        except (ImportError, OSError, AttributeError, TypeError, ValueError):
            return None

    def _memory_pressure_percent(self):
        try:
            percent = self.memory_pressure_reader()
        except Exception:
            return None
        if isinstance(percent, bool):
            return None
        try:
            percent = float(percent)
        except (TypeError, ValueError):
            return None
        return percent if math.isfinite(percent) and 0.0 <= percent <= 100.0 else None

    def _disk_free_bytes(self):
        try:
            free_bytes = self.disk_free_reader()
        except Exception:
            return None
        if isinstance(free_bytes, bool):
            return None
        try:
            free_bytes = int(free_bytes)
        except (TypeError, ValueError, OverflowError):
            return None
        return free_bytes if free_bytes >= 0 else None

    def _load_json(self, path: pathlib.Path, default):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return default
        return default

    def _save_stm(self):
        self._write_json(STM_FILE, self.stm)

    def _save_ltm_raw(self):
        self._write_json(LTM_RAW_FILE, self.ltm_raw)

    def _save_ltm_archive(self):
        self._write_json(LTM_ARCHIVE_FILE, self.ltm_archive)

    def _save_chat_history(self):
        self._write_json(CHAT_HISTORY_FILE, self.chat_history)

    def _write_json(self, path: pathlib.Path, value):
        self.privacy_core.write_text(path, json.dumps(value, indent=2), encoding="utf-8")

    def _ensure_body_memory_budget(self):
        disk_free_bytes = self._disk_free_bytes()
        if disk_free_bytes is None:
            raise MemoryPressureHold("AIOS body disk telemetry unavailable; memory write held")
        if disk_free_bytes < MIN_MEMORY_DISK_FREE_BYTES:
            raise MemoryPressureHold("AIOS body held memory write below 2 GiB free disk")
        pressure = self._memory_pressure_percent()
        if pressure is None:
            raise MemoryPressureHold("AIOS body RAM telemetry unavailable; memory write held")
        if pressure >= RAM_WRITE_HOLD_PERCENT:
            if len(self.chat_history) > 2:
                self._trigger_raw_dump_and_compact(
                    trigger="ram_pressure_hold", ram_percent=pressure)
            self._ram_pressure_compacted = True
            raise MemoryPressureHold(
                f"AIOS body held memory write at {pressure:.1f}% RAM"
            )
        if pressure <= RAM_COMPACTION_RESET_PERCENT:
            self._ram_pressure_compacted = False
        if pressure >= RAM_COMPACTION_PERCENT and not self._ram_pressure_compacted:
            if self.chat_history:
                self._trigger_raw_dump_and_compact(
                    trigger="ram_pressure_compaction", ram_percent=pressure)
            self._ram_pressure_compacted = True
        return pressure

    def get_short_term_context(self) -> dict:
        return self.stm

    def append_dialogue_turn(self, role: str, content: str):
        """Appends a turn to STM. If STM capacity is reached, dumps raw to LTM and compacts STM."""
        pressure = self._ensure_body_memory_budget()
        entry = {"role": role, "content": content, "timestamp": datetime.now(timezone.utc).isoformat()}
        self.chat_history.append(entry)
        self._save_chat_history()

        # Check if STM capacity reached
        if len(self.chat_history) >= STM_CAPACITY:
            self._trigger_raw_dump_and_compact(
                trigger="turn_capacity", ram_percent=pressure)

    def _trigger_raw_dump_and_compact(self, *, trigger="turn_capacity", ram_percent=None):
        """Dumps raw turns to LTM disk file, compacts short-term buffer, and resets STM."""
        print(f"\n[Memory Store]: STM Capacity ({len(self.chat_history)} turns) reached.")
        print("[Memory Store]: 1. Dumping raw context to Long-Term Memory (long_term_raw_dump.json)...")
        
        # 1. Dump raw turns to LTM
        dump_record = {
            "dump_timestamp": datetime.now(timezone.utc).isoformat(),
            "trigger": trigger,
            "ram_percent": ram_percent,
            "raw_turns": list(self.chat_history)
        }
        self.ltm_raw.append(dump_record)
        self._save_ltm_raw()

        print("[Learning Hold]: Raw memory is retained; adapter distillation requires a separate authorized run.")

        # 2. Compact short-term buffer
        print("[Memory Store]: 2. Summarizing and compacting Short-Term Context...")
        summarized_facts = []
        for turn in self.chat_history:
            if turn["role"] == "user":
                summarized_facts.append(f"Operator asked/said: {turn['content'][:80]}")
            elif turn["role"] == "assistant":
                summarized_facts.append(f"Viv responded: {turn['content'][:80]}")
        
        compact_str = " | ".join(summarized_facts[-6:])
        self.stm["compacted_summary"] = f"Compacted prior dialogue ({datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC): {compact_str}"
        self.stm["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._save_stm()

        # 3. Flush active STM chat buffer down to last 2 turns
        self.chat_history = self.chat_history[-2:]
        self._save_chat_history()
        print("[Memory Store]: Compaction complete. STM context reset and primed.")

    def get_recent_chat_history(self, limit: int = 10) -> list[dict]:
        return [{"role": item["role"], "content": item["content"]} for item in self.chat_history[-limit:]]

    def update_short_term(self, active_task: str, current_step: str, detail: str = ""):
        self._ensure_body_memory_budget()
        self.stm["active_task"] = active_task
        self.stm["current_step"] = current_step
        self.stm["timestamp"] = datetime.now(timezone.utc).isoformat()
        if detail:
            self.stm["working_buffer"].append({"time": datetime.now(timezone.utc).isoformat(), "log": detail})
            self.stm["working_buffer"] = self.stm["working_buffer"][-10:]
        self._save_stm()

    def query_long_term_memory(self, query: str, limit: int = 5) -> list[dict]:
        """Retrieve historical turns by ranked lexical overlap, newest first on ties."""
        stop = {"about", "after", "again", "also", "been", "being", "could", "does",
                "from", "have", "here", "into", "just", "make", "more", "most", "only",
                "some", "than", "that", "them", "then", "there", "these", "they", "this",
                "what", "when", "where", "which", "while", "with", "would", "your", "you",
                "will", "were", "want", "need", "does", "have", "doesn", "should"}
        terms = {w for w in re.findall(r"[a-z0-9_]{3,}", query.lower()) if w not in stop}
        aliases = {"persistant": "persistent", "conscienness": "consciousness",
                   "consciencness": "consciousness", "awareness": "aware"}
        terms = {aliases.get(word, word) for word in terms}
        if not terms:
            return []
        ranked = []
        seen = set()
        position = 0
        for dump in self.ltm_raw:
            for turn in dump.get("raw_turns", []):
                content = turn.get("content", "")
                identity = (turn.get("role"), content)
                if identity in seen:
                    continue
                seen.add(identity)
                words = set(re.findall(r"[a-z0-9_]{3,}", content.lower()))
                overlap = len(terms & words)
                if overlap:
                    ranked.append((overlap / len(terms), overlap, position, turn))
                position += 1
        ranked.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
        return [dict(turn) for _, _, _, turn in ranked[:max(0, limit)]]

memory_store = DualContextMemory()
