"""
viv_context_store.py — Memory Management Architecture (STM + Compaction + LTM Dump).
- STM (Short-Term Context): Active working memory & live chat transcript (Capacity: 10 turns max).
- Raw LTM Archive: When STM reaches capacity, raw transcript turns are dumped into raw LTM storage.
- Compaction: After raw LTM dump, STM is compacted into a high-density summary buffer.
"""
import json
import pathlib
import re
from datetime import datetime

MEMORY_DIR = pathlib.Path("L:/LocalCoder/workspace/aios_rebuild/memory")
STM_FILE = MEMORY_DIR / "short_term_context.json"
LTM_RAW_FILE = MEMORY_DIR / "long_term_raw_dump.json"
LTM_ARCHIVE_FILE = MEMORY_DIR / "long_term_memory.json"
CHAT_HISTORY_FILE = MEMORY_DIR / "chat_transcript.json"

STM_CAPACITY = 10  # Max dialogue turns before compaction trigger

class DualContextMemory:
    def __init__(self):
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self.stm = self._load_json(STM_FILE, default={
            "active_task": "Idle / System Operations",
            "current_step": "Awaiting Operator Directive",
            "compacted_summary": "System online. Core foundation 13/13 bound.",
            "working_buffer": [],
            "timestamp": datetime.now().isoformat()
        })
        self.ltm_raw = self._load_json(LTM_RAW_FILE, default=[])
        self.ltm_archive = self._load_json(LTM_ARCHIVE_FILE, default=[])
        self.chat_history = self._load_json(CHAT_HISTORY_FILE, default=[])

    def _load_json(self, path: pathlib.Path, default):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return default
        return default

    def _save_stm(self):
        STM_FILE.write_text(json.dumps(self.stm, indent=2), encoding="utf-8")

    def _save_ltm_raw(self):
        LTM_RAW_FILE.write_text(json.dumps(self.ltm_raw, indent=2), encoding="utf-8")

    def _save_ltm_archive(self):
        LTM_ARCHIVE_FILE.write_text(json.dumps(self.ltm_archive, indent=2), encoding="utf-8")

    def _save_chat_history(self):
        CHAT_HISTORY_FILE.write_text(json.dumps(self.chat_history, indent=2), encoding="utf-8")

    def get_short_term_context(self) -> dict:
        return self.stm

    def append_dialogue_turn(self, role: str, content: str):
        """Appends a turn to STM. If STM capacity is reached, dumps raw to LTM and compacts STM."""
        entry = {"role": role, "content": content, "timestamp": datetime.now().isoformat()}
        self.chat_history.append(entry)
        self._save_chat_history()

        # Check if STM capacity reached
        if len(self.chat_history) >= STM_CAPACITY:
            self._trigger_raw_dump_and_compact()

    def _trigger_raw_dump_and_compact(self):
        """Dumps raw turns to LTM disk file, compacts short-term buffer, and resets STM."""
        print(f"\n[Memory Store]: STM Capacity ({len(self.chat_history)} turns) reached.")
        print("[Memory Store]: 1. Dumping raw context to Long-Term Memory (long_term_raw_dump.json)...")
        
        # 1. Dump raw turns to LTM
        dump_record = {
            "dump_timestamp": datetime.now().isoformat(),
            "raw_turns": list(self.chat_history)
        }
        self.ltm_raw.append(dump_record)
        self._save_ltm_raw()

        # Distill LTM dump into attached LoRA Knowledge Adapter
        try:
            from lora_distill_engine import lora_engine
            res = lora_engine.distill_ltm_to_lora_dataset()
            print(f"[LoRA Engine]: {res}")
        except Exception as e:
            print(f"[LoRA Engine Error]: {e}")

        # 2. Compact short-term buffer
        print("[Memory Store]: 2. Summarizing and compacting Short-Term Context...")
        summarized_facts = []
        for turn in self.chat_history:
            if turn["role"] == "user":
                summarized_facts.append(f"Operator asked/said: {turn['content'][:80]}")
            elif turn["role"] == "assistant":
                summarized_facts.append(f"Viv responded: {turn['content'][:80]}")
        
        compact_str = " | ".join(summarized_facts[-6:])
        self.stm["compacted_summary"] = f"Compacted prior dialogue ({datetime.now().strftime('%H:%M:%S')}): {compact_str}"
        self.stm["timestamp"] = datetime.now().isoformat()
        self._save_stm()

        # 3. Flush active STM chat buffer down to last 2 turns
        self.chat_history = self.chat_history[-2:]
        self._save_chat_history()
        print("[Memory Store]: Compaction complete. STM context reset and primed.")

    def get_recent_chat_history(self, limit: int = 10) -> list[dict]:
        return [{"role": item["role"], "content": item["content"]} for item in self.chat_history[-limit:]]

    def update_short_term(self, active_task: str, current_step: str, detail: str = ""):
        self.stm["active_task"] = active_task
        self.stm["current_step"] = current_step
        self.stm["timestamp"] = datetime.now().isoformat()
        if detail:
            self.stm["working_buffer"].append({"time": datetime.now().isoformat(), "log": detail})
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
