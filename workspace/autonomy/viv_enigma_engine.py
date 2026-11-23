"""
Viv Inverted Enigma Engine & Dual-Substrate Sovereign Server
============================================================
Architect: Travis (Nox Forge / AIOS V2)
Purpose:
  1. Inverted Enigma Multi-Rotor Architecture:
     - Base-52 integer polynomial keying sets rotor positions.
     - Rotor 0: English Grammar/Syntax (viv_core_english_epoch0140.vtm)
     - Rotor 1: Hot-Swappable Domain Expert (Physics, Biology, CompSci, Math, Philosophy, Python)
     - Reflector: UML Boundary Gate (<!0, !0> = 1.0 vs {!0, !0} = 0.0)
  2. Dual-Substrate Grounded Execution:
     - GPU Tensor Cores: Associative routing, resonance, permutation (<10 ms).
     - SQLite Databases: 100% uncompressed factual ground truth.
     - Hallucination Prevention: Out-of-domain queries trip {!0, !0} = 0.0 -> NULL_UNLEARNED_ENTITY.
  3. Sovereign OpenAI-Compatible Server for AIOS V2 (Port 1235).
"""

from __future__ import annotations

import json
import math
import operator
import os
import re
import sqlite3
import ssl
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch
import torch.nn.functional as F

AUTONOMY_DIR = Path(__file__).resolve().parent
if str(AUTONOMY_DIR) not in sys.path:
    sys.path.insert(0, str(AUTONOMY_DIR))

# UML Calc Engine integration
UML_DIR = Path(r"L:\LocalCoder\UML_Calc")
if UML_DIR.is_dir() and str(UML_DIR) not in sys.path:
    sys.path.insert(0, str(UML_DIR))

try:
    import uml_engine
    UML_CEILING = float(uml_engine.evaluate("<!0, !0>")[0])  # 1.0
    UML_FLOOR = float(uml_engine.evaluate("{!0, !0}")[0])    # 0.0
except Exception:
    UML_CEILING = 1.0
    UML_FLOOR = 0.0

from vtm_spec import VTMContainer
from viv_conversational_softener import ConversationalSoftener

CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
CHAR_MAP = {c: i + 1 for i, c in enumerate(CHARS)}  # 1..52

DOMAIN_GAUGES: Dict[str, int] = {
    "english": 0,
    "physics": 1,
    "biology": 2,
    "comp_sci": 3,
    "mathematics": 4,
    "philosophy": 5,
    "python": 6,
    "engineering": 7,
    "history": 8,
    "geography": 9,
    "general": 5,
    "live": 9,
}

DOMAIN_CARTRIDGES: Dict[str, Path] = {
    "english": Path(r"E:\Viv_Sandbox\cartridges\viv_core_english_epoch0140.vtm"),
    "physics": Path(r"E:\Viv_Sandbox\cartridges\wiki\wiki_physics_epoch0140.vtm"),
    "biology": Path(r"E:\Viv_Sandbox\cartridges\wiki\wiki_biology_epoch0140.vtm"),
    "comp_sci": Path(r"E:\Viv_Sandbox\cartridges\wiki\wiki_comp_sci_epoch0140.vtm"),
    "mathematics": Path(r"E:\Viv_Sandbox\cartridges\wiki\wiki_mathematics_epoch0140.vtm"),
    "philosophy": Path(r"E:\Viv_Sandbox\cartridges\wiki\wiki_philosophy_epoch0140.vtm"),
    "python": Path(r"E:\Viv_Sandbox\cartridges\viv_expert_python_epoch0139.vtm"),
    "engineering": Path(r"E:\Viv_Sandbox\cartridges\wiki\wiki_engineering_epoch0140.vtm"),
    "history": Path(r"E:\Viv_Sandbox\cartridges\wiki\wiki_history_epoch0140.vtm"),
    "geography": Path(r"E:\Viv_Sandbox\cartridges\wiki\wiki_geography_epoch0140.vtm"),
    "general": Path(r"E:\Viv_Sandbox\cartridges\wiki\wiki_history_epoch0140.vtm"),
    "live": Path(r"E:\Viv_Sandbox\cartridges\wiki\wiki_history_epoch0140.vtm"),
}

DOMAIN_DATABASES: Dict[str, Path] = {
    "physics": Path(r"F:\AI_Datasets\domain_dbs\wiki_physics.sqlite3"),
    "biology": Path(r"F:\AI_Datasets\domain_dbs\wiki_biology.sqlite3"),
    "comp_sci": Path(r"F:\AI_Datasets\domain_dbs\wiki_comp_sci.sqlite3"),
    "mathematics": Path(r"F:\AI_Datasets\domain_dbs\wiki_mathematics.sqlite3"),
    "philosophy": Path(r"F:\AI_Datasets\domain_dbs\wiki_philosophy.sqlite3"),
    "python": Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3"),
    "engineering": Path(r"F:\AI_Datasets\domain_dbs\wiki_engineering.sqlite3"),
    "history": Path(r"F:\AI_Datasets\domain_dbs\wiki_history.sqlite3"),
    "geography": Path(r"F:\AI_Datasets\domain_dbs\wiki_geography.sqlite3"),
    "general": Path(r"F:\AI_Datasets\domain_dbs\wiki_general.sqlite3"),
    "live": Path(r"F:\AI_Datasets\domain_dbs\wiki_live.sqlite3"),
}


def get_domain_cartridge_path(domain: str) -> Optional[Path]:
    """Resolves the highest available epoch cartridge for a domain."""
    if domain == "english":
        return Path(r"E:\Viv_Sandbox\cartridges\viv_core_english_epoch0140.vtm")
    if domain == "python":
        return Path(r"E:\Viv_Sandbox\cartridges\viv_expert_python_epoch0139.vtm")
    if domain in ("live", "general"):
        return Path(r"E:\Viv_Sandbox\cartridges\wiki\wiki_history_epoch0140.vtm")
    wiki_dir = Path(r"E:\Viv_Sandbox\cartridges\wiki")
    matches = sorted(wiki_dir.glob(f"wiki_{domain}_epoch*.vtm"))
    if matches:
        return matches[-1]
    return DOMAIN_CARTRIDGES.get(domain)


def b52_key(text: str, shift: int = 0) -> int:
    """Computes deterministic Base-52 polynomial integer key for word or text."""
    val = 0
    for c in text:
        if c in CHAR_MAP:
            c_val = ((CHAR_MAP[c] - 1 + shift) % 52) + 1
            val = (val * 52 + c_val) & 0xFFFFFFFFFFFFFFFF
    return val


class EnigmaRotorStack:
    """Manages the cascaded Inverted Enigma rotors in GPU VRAM."""

    def __init__(self, device: str = "cuda:0" if torch.cuda.is_available() else "cpu"):
        self.device = torch.device(device)
        self.active_domain: str = "english"
        self.rotor0_tensors: Dict[str, torch.Tensor] = {}
        self.rotor0_meta: Dict[str, Any] = {}
        self.rotor1_tensors: Dict[str, torch.Tensor] = {}
        self.rotor1_meta: Dict[str, Any] = {}

        # Load Rotor 0 (English Grammar - permanently in VRAM)
        self._load_rotor0()
        # Default Rotor 1 (Physics)
        self.mount_domain_rotor("physics")

    def _load_rotor0(self):
        core_path = get_domain_cartridge_path("english")
        if core_path and core_path.exists():
            t0 = time.perf_counter()
            self.rotor0_tensors, self.rotor0_meta = VTMContainer.load_tensors(core_path, device=str(self.device))
            ms = (time.perf_counter() - t0) * 1000
            print(f"[+] Loaded Rotor 0 (English Grammar) in {ms:.2f} ms | Epoch {self.rotor0_meta.get('epoch')}")
        else:
            print(f"[-] Warning: English cartridge not found at {core_path}")

    def mount_domain_rotor(self, domain: str) -> float:
        """Hot-swaps Rotor 1 to the requested domain expert in milliseconds."""
        if domain == self.active_domain and self.rotor1_tensors:
            return 0.0

        target_path = get_domain_cartridge_path(domain)
        if not target_path or not target_path.exists():
            return -1.0

        t0 = time.perf_counter()
        self.rotor1_tensors, self.rotor1_meta = VTMContainer.load_tensors(target_path, device=str(self.device))
        self.active_domain = domain
        ms = (time.perf_counter() - t0) * 1000
        print(f"[+] Mounted Rotor 1 ({domain.upper()} Epoch {self.rotor1_meta.get('epoch')}) in {ms:.2f} ms")
        return ms

    def classify_domain(self, prompt: str) -> str:
        """Determines the most resonant domain for a given prompt."""
        p_lower = prompt.lower()
        scores = {d: 0.0 for d in DOMAIN_CARTRIDGES if d != "english"}

        # 1. Explicit domain markers (highest priority)
        domain_markers = {
            "comp_sci": ["in computer science", "in comp sci", "in computing", "in software"],
            "biology": ["in biology", "in biological", "in genetics"],
            "physics": ["in physics", "in physical science", "in quantum"],
            "mathematics": ["in mathematics", "in math", "in algebra", "in calculus"],
            "philosophy": ["in philosophy", "in ethics", "in metaphysics"],
            "engineering": ["in engineering", "in mechanical engineering"],
            "history": ["in history", "in historical", "during the reign", "during the war"],
            "geography": ["in geography", "geographic"],
            "python": ["in python", "python function", "python method"],
        }
        marker_hit = False
        for domain, markers in domain_markers.items():
            for m in markers:
                if m in p_lower:
                    scores[domain] += 50.0
                    marker_hit = True

        # 1.5 Direct entity title match across domain DBs (if no explicit domain marker forced)
        if not marker_hit:
            clean_probe = re.sub(r"^(who\s+(?:was|is)|what\s+(?:was|is|are)|when\s+(?:was|did|is)|where\s+(?:was|is|did)|why\s+(?:was|did|is)|how\s+(?:did|was|is)|tell\s+me\s+about|define|explain)\s+(?:the\s+)?", "", prompt, flags=re.I).strip(" ?.")
            clean_probe = re.sub(r"\s+(?:born|die|died|assassinated|serve|reign|happen|founded|invented)$", "", clean_probe, flags=re.I).strip(" ?.")
            proper_phrases = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", prompt)
            candidates_to_check = [c for c in [clean_probe] + proper_phrases if c and len(c) >= 2]

            found_match = False
            for cand in candidates_to_check:
                probe_variants = [cand, cand.title(), cand.capitalize()]
                if cand.isupper() or len(cand) <= 5:
                    probe_variants.append(cand.upper())
                for d, p in DOMAIN_DATABASES.items():
                    if p.exists():
                        try:
                            conn = sqlite3.connect(str(p))
                            cur = conn.cursor()
                            for v in set(probe_variants):
                                cur.execute("SELECT 1 FROM articles WHERE title = ? LIMIT 1", (v,))
                                if cur.fetchone():
                                    scores[d] += 40.0
                                    found_match = True
                                    conn.close()
                                    break
                            else:
                                conn.close()
                                continue
                            break
                        except Exception:
                            pass
                if found_match:
                    break

        # 2. Compound high-order context (weight = 15.0)
        compound_keywords = {
            "comp_sci": [
                "computer science", "data structure", "data structures", "operating system",
                "machine learning", "neural network", "binary tree", "source code",
                "linked list", "hash table", "search algorithm"
            ],
            "physics": [
                "quantum mechanics", "general relativity", "special relativity",
                "speed of light", "particle physics", "thermodynamics", "subatomic particle"
            ],
            "biology": [
                "molecular biology", "cell biology", "evolutionary biology",
                "genetic code", "amino acid", "natural selection", "cellular respiration"
            ],
            "mathematics": [
                "linear algebra", "abstract algebra", "differential equation",
                "differential equations", "number theory", "prime number"
            ],
            "philosophy": [
                "moral philosophy", "philosophy of mind", "epistemological", "categorical imperative"
            ],
            "engineering": [
                "electrical engineering", "mechanical engineering", "civil engineering",
                "aerospace engineering", "structural engineering"
            ],
            "history": [
                "world war", "civil war", "ancient rome", "ancient greece",
                "roman empire", "middle ages", "united states president", "us president"
            ],
            "geography": [
                "south america", "north america", "united kingdom", "pacific ocean",
                "mountain range", "capital city"
            ],
        }
        for domain, compounds in compound_keywords.items():
            for c in compounds:
                if c in p_lower:
                    scores[domain] += 15.0

        # 3. Unigram keywords (weight = 1.0)
        keywords = {
            "physics": ["physics", "energy", "force", "mass", "gravity", "quantum", "relativity", "speed of light", "time", "atom", "astronomy", "astronomer", "wave", "particle"],
            "biology": ["biology", "cell", "dna", "rna", "protein", "species", "organism", "gene", "amphibian", "animal", "plant", "evolution", "virus", "bacteria"],
            "comp_sci": ["computer", "algorithm", "database", "binary", "ascii", "network", "software", "hardware", "cpu", "gpu", "compiler", "operating system"],
            "mathematics": ["math", "equation", "matrix", "algebra", "calculus", "geometry", "number", "prime", "topology", "manifold", "integral"],
            "philosophy": ["philosophy", "ethics", "epistemology", "metaphysics", "logic", "truth", "consciousness", "existentialism", "mind", "morality"],
            "python": ["def ", "class ", "import ", "lambda", "yield", "python", "pytest", "sqlite3", "torch", "decorator", "self."],
            "engineering": ["engineering", "engine", "mechanical", "electrical", "turbine", "bridge", "circuit", "robot", "aerospace", "materials", "infrastructure"],
            "history": ["history", "war", "battle", "century", "empire", "king", "queen", "ancient", "dynasty", "revolution", "president", "treaty", "historian"],
            "geography": ["geography", "country", "city", "river", "mountain", "ocean", "continent", "capital", "island", "lake", "border", "population", "region"],
        }

        for domain, kw_list in keywords.items():
            for kw in kw_list:
                if kw in p_lower:
                    scores[domain] += 1.0

        best_domain = max(scores, key=scores.get)
        if scores[best_domain] > 0.0:
            return best_domain
        return "physics"  # Default fallback expert


def clean_lead_text(raw: str, title: str) -> str:
    """Extracts clean, authoritative lead prose from raw Wikipedia markup."""
    # Strip orphaned infobox residue if present
    if "}}" in raw[:1500] and not raw.strip().startswith("{{"):
        idx = raw.find("}}")
        candidate = raw[idx + 2:].strip()
        if len(candidate) > 80:
            raw = candidate

    pattern = rf"{re.escape(title)}[,\s]*(?:\(.*?\))?[,\s]*(?:was|is|are)\s+.*"
    m = re.search(pattern, raw, flags=re.DOTALL | re.IGNORECASE)
    if m:
        lead = m.group(0)
    else:
        lead = re.sub(r"\{\|.*?\|\}", "", raw, flags=re.DOTALL)
        lead = re.sub(r"\{\{.*?\}\}", "", lead, flags=re.DOTALL)
        lead = re.sub(r"\|[a-zA-Z0-9_\s]+=\s*[^|\n\}]*", "", lead)

    lead = re.sub(r"<ref.*?>.*?</ref>", "", lead, flags=re.DOTALL)
    lead = re.sub(r"<.*?>", "", lead)
    lead = re.sub(r"&nbsp;", " ", lead)
    lead = re.sub(r"<!--.*?-->", "", lead, flags=re.DOTALL)
    lead = re.sub(r"\{\{.*?\}\}", "", lead, flags=re.DOTALL)
    lead = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", lead)
    lead = re.sub(r"'''+|''+", "", lead)
    sec_m = re.search(r"==+\s*[^=]+\s*==+", lead)
    if sec_m and sec_m.start() > 100:
        lead = lead[:sec_m.start()]
    lead = re.sub(r"\s+", " ", lead).strip()
    return lead


PLUGBOARD_DB = Path(r"F:\AI_Datasets\domain_dbs\wiki_plugboard.sqlite3")


class EnigmaPlugboard:
    """Pre-rotor coordinate swapping (Steckerbrett) for entity aliases and synonyms."""

    @staticmethod
    def swap(phrase: str) -> Optional[str]:
        if not PLUGBOARD_DB.exists():
            return None
        try:
            conn = sqlite3.connect(str(PLUGBOARD_DB))
            cur = conn.cursor()
            cur.execute("SELECT target FROM plugboard WHERE alias = ? COLLATE NOCASE LIMIT 1", (phrase.strip(),))
            row = cur.fetchone()
            conn.close()
            if row:
                return row[0]
        except Exception:
            pass
        return None


LIVE_DB_PATH = Path(r"F:\AI_Datasets\domain_dbs\wiki_live.sqlite3")


class VivLiveCrystallizer:
    """Sovereign real-time factual intake from official Wikimedia REST API.
    
    Crystallizes newly discovered encyclopedic entities directly into local SQLite,
    commits aliases to Enigma Steckerbrett, and updates the local coordinate manifold.
    Zero hallucination: if Wikimedia returns 404/Not Found, fails closed immediately.
    """
    WIKI_API_TEMPLATE = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    USER_AGENT = "VivSovereign/2.0 (InvertedEnigma; AIOS_V2; contact@aios.internal)"

    @classmethod
    def _init_live_db(cls):
        if not LIVE_DB_PATH.parent.exists():
            LIVE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(LIVE_DB_PATH))
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                article_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT UNIQUE,
                summary TEXT,
                domain TEXT,
                timestamp TEXT,
                source_url TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_live_title ON articles (title COLLATE NOCASE)")
        conn.commit()
        conn.close()

    @classmethod
    def resolve_and_crystallize(cls, query_phrase: str) -> Optional[Dict[str, Any]]:
        cls._init_live_db()
        clean = query_phrase.strip().replace(" ", "_")
        if not clean or len(clean) < 2:
            return None

        encoded_title = urllib.parse.quote(clean)
        url = cls.WIKI_API_TEMPLATE.format(title=encoded_title)

        req = urllib.request.Request(
            url,
            headers={"User-Agent": cls.USER_AGENT}
        )
        ctx = ssl._create_unverified_context()

        try:
            t0 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=3.5, context=ctx) as resp:
                fetch_ms = (time.perf_counter() - t0) * 1000
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data.get("type") in ("standard", "page") and data.get("extract"):
                        title = data.get("title", "")
                        extract = data.get("extract", "")
                        timestamp = data.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ"))
                        source_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")

                        # Commit to wiki_live.sqlite3 (Fast Channel Corpus Expansion)
                        t_db = time.perf_counter()
                        conn = sqlite3.connect(str(LIVE_DB_PATH))
                        cur = conn.cursor()
                        cur.execute("""
                            INSERT OR REPLACE INTO articles (title, summary, domain, timestamp, source_url)
                            VALUES (?, ?, ?, ?, ?)
                        """, (title, extract, "live_crystallized", timestamp, source_url))
                        conn.commit()
                        conn.close()
                        commit_ms = (time.perf_counter() - t_db) * 1000

                        # Commit alias to plugboard
                        clean_query = query_phrase.strip()
                        if clean_query.lower() != title.lower() and PLUGBOARD_DB.exists():
                            try:
                                pb_conn = sqlite3.connect(str(PLUGBOARD_DB))
                                pb_cur = pb_conn.cursor()
                                pb_cur.execute("""
                                    INSERT OR IGNORE INTO plugboard (alias, target)
                                    VALUES (?, ?)
                                """, (clean_query, title))
                                pb_conn.commit()
                                pb_conn.close()
                            except Exception:
                                pass

                        return {
                            "title": title,
                            "summary": extract,
                            "source": "wiki_live.sqlite3 (Live REST Crystallized)",
                            "fetch_ms": round(fetch_ms, 2),
                            "commit_ms": round(commit_ms, 2),
                            "revision_time": timestamp,
                            "url": source_url
                        }
        except urllib.error.HTTPError:
            return None
        except Exception:
            return None
        return None


class DeterministicALUNode:
    """Deterministic ALU execution for numerical operations (No Digit Neurons Covenant)."""

    OPS = {
        "plus": operator.add,
        "+": operator.add,
        "minus": operator.sub,
        "-": operator.sub,
        "times": operator.mul,
        "*": operator.mul,
        "multiplied by": operator.mul,
        "divided by": operator.truediv,
        "/": operator.truediv,
    }

    DIGIT_WORDS = {
        0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
        6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
        11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
        16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty",
        30: "thirty", 40: "forty", 50: "fifty", 60: "sixty", 70: "seventy",
        80: "eighty", 90: "ninety"
    }

    @classmethod
    def to_words(cls, n: int) -> str:
        if n in cls.DIGIT_WORDS:
            return cls.DIGIT_WORDS[n]
        if 21 <= n <= 99:
            tens = (n // 10) * 10
            units = n % 10
            return f"{cls.DIGIT_WORDS[tens]}-{cls.DIGIT_WORDS[units]}"
        if 100 <= n <= 999:
            hundreds = n // 100
            rem = n % 100
            if rem == 0:
                return f"{cls.DIGIT_WORDS.get(hundreds, str(hundreds))} hundred"
            return f"{cls.DIGIT_WORDS.get(hundreds, str(hundreds))} hundred {cls.to_words(rem)}"
        if 1000 <= n <= 999999:
            thousands = n // 1000
            rem = n % 1000
            if rem == 0:
                return f"{cls.to_words(thousands)} thousand"
            return f"{cls.to_words(thousands)} thousand {cls.to_words(rem)}"
        return str(n)

    @classmethod
    def evaluate(cls, query: str) -> Optional[Dict[str, Any]]:
        q = query.lower().strip()
        m = re.search(r"(\d+(?:\.\d+)?)\s*(plus|minus|times|multiplied by|divided by|\+|\-|\*|\/)\s*(\d+(?:\.\d+)?)", q)
        if m:
            n1 = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
            op_str = m.group(2).strip()
            n2 = float(m.group(3)) if "." in m.group(3) else int(m.group(3))
            op_func = cls.OPS.get(op_str)
            if op_func:
                if op_str in ("divided by", "/") and n2 == 0:
                    return None
                result = op_func(n1, n2)
                res_int = int(result) if isinstance(result, (int, float)) and result == int(result) else result
                word_rep = cls.to_words(res_int) if isinstance(res_int, int) else str(res_int)
                return {
                    "expression": f"{n1} {op_str} {n2}",
                    "result": res_int,
                    "word_tokens": f"{word_rep} units",
                    "formula": f"{n1} {op_str} {n2} = {res_int} ({word_rep} units)"
                }
        return None


class SessionDiscourseManager:
    """Tracks active entities and resolves anaphoric references across dialogue turns."""
    PRONOUNS = {"he", "him", "his", "she", "her", "hers", "it", "its", "they", "them", "their"}

    @classmethod
    def resolve_query(
        cls,
        messages: List[Dict[str, str]],
        prior_entity: Optional[str] = None
    ) -> Tuple[str, Optional[str]]:
        if not messages:
            return "", None
        current_query = messages[-1].get("content", "").strip()
        words = re.findall(r"\b[A-Za-z]+\b", current_query.lower())
        contains_pronoun = any(w in cls.PRONOUNS for w in words)

        entity = prior_entity
        if not entity and len(messages) >= 2:
            for msg in reversed(messages[:-1]):
                content = msg.get("content", "")
                proper = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", content)
                if proper:
                    entity = proper[0]
                    break

        if contains_pronoun and entity:
            resolved = current_query
            for p in ["he was", "he is", "he did", "he "]:
                resolved = re.sub(rf"\b{p}", f"{entity} ", resolved, flags=re.IGNORECASE)
            for p in ["his ", "her ", "its ", "their "]:
                resolved = re.sub(rf"\b{p}", f"{entity}'s ", resolved, flags=re.IGNORECASE)
            for p in ["he", "she", "it", "they"]:
                resolved = re.sub(rf"\b{p}\b", entity, resolved, flags=re.IGNORECASE)
            return resolved, entity

        return current_query, entity


class DualSubstrateDispatcher:
    """Coordinates the Inverted Enigma GPU routing with SQLite factual ground truth."""

    def __init__(self, rotor_stack: EnigmaRotorStack):
        self.stack = rotor_stack
        self.softener = ConversationalSoftener()
        self.last_entity: Optional[str] = None

    def _compute_rotor_transition_prob(self, title1: str, title2: str) -> float:
        """Computes associative transition probability between two entities using active rotor."""
        try:
            tok_emb = self.stack.rotor1_tensors.get("tok_emb.weight")
            if tok_emb is None:
                return 0.50
            b1 = title1.encode("utf-8", errors="ignore")
            b2 = title2.encode("utf-8", errors="ignore")
            if not b1 or not b2:
                return 0.50
            dev = self.stack.device
            idx1 = torch.tensor(list(b1), device=dev, dtype=torch.long)
            idx2 = torch.tensor(list(b2), device=dev, dtype=torch.long)
            idx1 = torch.clamp(idx1, 0, tok_emb.shape[0] - 1)
            idx2 = torch.clamp(idx2, 0, tok_emb.shape[0] - 1)
            v1 = tok_emb[idx1].float().mean(dim=0)
            v2 = tok_emb[idx2].float().mean(dim=0)
            cos_sim = torch.cosine_similarity(v1, v2, dim=0).item()
            return max(0.0, min(1.0, (cos_sim + 1.0) / 2.0))
        except Exception:
            return 0.50

    def route_query(self, query: str, temperature: float = 0.2, persona: str = "jarvis") -> Dict[str, Any]:
        """Processes query through Inverted Enigma rotor stack and UML boundary gate."""
        t0 = time.perf_counter()

        # Step 0: Check Deterministic ALU (Numerical / Arithmetic Reasoning Covenant)
        alu_result = DeterministicALUNode.evaluate(query)
        if alu_result:
            latency_ms = (time.perf_counter() - t0) * 1000
            resp_text = (
                f"Deterministic ALU Invariant satisfied:\n\n"
                f"{alu_result['expression']} = {alu_result['result']} ({alu_result['word_tokens']})\n\n"
                f"Calculated on physical silicon without token spinning. Boundary reflected <!0, !0> = 1.0."
            )
            return {
                "domain": "mathematics",
                "gauge_shift": 4,
                "base52_key": b52_key(query, shift=4),
                "gate_status": f"<!0, !0> = {UML_CEILING:.1f} (DETERMINISTIC ALU)",
                "is_grounded": True,
                "matched_entity": alu_result["expression"],
                "response": resp_text,
                "hop_chain": [{"hop": 1, "type": "DETERMINISTIC_ALU", "entity": alu_result["expression"], "p": 1.000, "result": alu_result["result"]}],
                "plugboard_swap": None,
                "latency_ms": round(latency_ms, 2),
                "swap_ms": 0.0,
            }

        # Step 0.5: Check Self-Referential / Conversational Queries
        q_clean = query.lower().strip(" ?.")
        is_self_referential = any(
            q_clean.startswith(prefix) for prefix in [
                "who are you", "what are you", "what can you do", "what is your name",
                "who made you", "who created you", "how are you", "what do you do",
                "help", "capabilities"
            ]
        ) or any(
            q_clean.startswith(g) for g in [
                "hello", "hi", "hey", "greetings", "good morning", "good afternoon", "good evening"
            ]
        )

        if is_self_referential:
            latency_ms = (time.perf_counter() - t0) * 1000
            resp_text = self._synthesize_response(query, persona=persona)
            return {
                "domain": "english",
                "gauge_shift": 0,
                "base52_key": b52_key(query, shift=0),
                "gate_status": f"<!0, !0> = {UML_CEILING:.1f} (SYNTACTIC CONVERSATION)",
                "is_grounded": True,
                "matched_entity": "Viv",
                "response": resp_text,
                "hop_chain": [{"hop": 1, "type": "DETERMINISTIC", "entity": "Viv Core Node", "p": 1.000}],
                "plugboard_swap": None,
                "latency_ms": round(latency_ms, 2),
                "swap_ms": 0.0,
            }

        # Step 1: Enigma Steckerbrett (Plugboard Coordinate Swapping)
        plugboard_trace = None
        working_query = query
        phrases_to_test = [
            re.sub(r"^(who\s+was|who\s+is|what\s+is|what\s+was|tell\s+me\s+about|define|explain)\s+(the\s+)?", "", query, flags=re.I).strip(" ?."),
            query.strip(" ?.")
        ]
        for phrase in phrases_to_test:
            if phrase and (len(phrase) >= 2 or phrase.isalpha()):
                swapped = EnigmaPlugboard.swap(phrase)
                if swapped:
                    plugboard_trace = f"{phrase} -> {swapped}"
                    working_query = query.replace(phrase, swapped)
                    break

        domain = self.stack.classify_domain(working_query)
        swap_ms = self.stack.mount_domain_rotor(domain)

        gauge_shift = DOMAIN_GAUGES.get(domain, 0)
        query_key = b52_key(working_query, shift=gauge_shift)

        # 1. Check SQLite Factual Knowledge Base
        db_path = DOMAIN_DATABASES.get(domain)
        matched_entity = None
        exploration_meta: Dict[str, Any] = {}

        # Extract explicit entity probe candidates from query
        raw_tokens = re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", working_query)
        ignore_initial = {
            "Who", "What", "Tell", "Explain", "Where", "Was", "Were", "Are", "Is",
            "Which", "How", "Can", "Could", "Would", "Define", "Describe"
        }
        proper_probes = []
        for idx, token in enumerate(raw_tokens):
            if idx == 0 and token in ignore_initial:
                continue
            if token.isdigit():
                continue
            if (token[0].isupper() or any(c.isdigit() for c in token)) and token.lower() not in {"the", "a", "an", "of", "in", "to", "for"}:
                proper_probes.append(token.lower())

        # Extract clean core subject phrase (handling optional domain constraint prefix)
        clean_subj = re.sub(
            r"^(?:in\s+[a-z_\s]+,\s*)?(?:who\s+(?:was|is|were|are)|what\s+(?:was|is|are)|when\s+(?:was|did|is)|where\s+(?:was|is|did)|why\s+(?:was|did|is)|how\s+(?:did|was|is)|tell\s+me\s+about|define|explain|describe)\s+(?:the\s+|a\s+|an\s+)?",
            "",
            working_query,
            flags=re.I
        ).strip(" ?.")
        clean_subj = re.sub(r"\s+(?:born|die|died|assassinated|serve|reign|happen|founded|invented)$", "", clean_subj, flags=re.I).strip(" ?.")
        core_subject = clean_subj.lower()
        if "formula of" in working_query.lower():
            f_match = re.search(r"formula\s+of\s+([A-Za-z0-9\-]+)", working_query, flags=re.IGNORECASE)
            if f_match:
                core_subject = f_match.group(1).strip().lower()
        core_subject_words = [w for w in re.findall(r"[a-z0-9]+", core_subject) if w not in {"the", "a", "an", "chemical", "in", "of", "to", "for"}]

        # Pre-compute query tokens, content words, and exact probe candidates
        words = re.findall(r"[a-zA-Z0-9]+", working_query)
        stop_words = {
            "what", "is", "an", "the", "how", "explain", "tell", "about",
            "define", "does", "in", "who", "which", "most", "famous", "greatest",
            "was", "were", "are", "of", "to", "for", "me", "only"
        }
        content_words = [
            w.lower() for w in words
            if (len(w) >= 3 or re.match(r"^(?:[ivx]+|\d+)$", w, re.I)) and w.lower() not in stop_words
        ]
        exact_probes = []
        if plugboard_trace and " -> " in plugboard_trace:
            exact_probes.append(plugboard_trace.split(" -> ")[1].strip())
        if clean_subj:
            exact_probes.extend([clean_subj, clean_subj.title(), clean_subj.capitalize()])
        proper_phrases = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", working_query)
        for pp in proper_phrases:
            exact_probes.extend([pp, pp.title()])
        ordinals = [w for w in content_words if re.match(r"^\d+(?:st|nd|rd|th)$", w)]
        superlatives = ["famous", "greatest", "first", "largest", "fastest", "leading", "prominent"]

        if db_path and db_path.exists() and content_words:
            try:
                conn = sqlite3.connect(str(db_path))
                cur = conn.cursor()

                if domain == "python":
                    for cw in content_words:
                        cur.execute("SELECT name, ast_hash, docstring FROM code_neurons WHERE name LIKE ? LIMIT 1", (f"%{cw}%",))
                        row = cur.fetchone()
                        if row:
                            matched_entity = {
                                "title": row[0],
                                "summary": row[2] or f"Python code entity: {row[0]} (AST: {row[1]})",
                                "source": "viv_code_topology.sqlite3",
                            }
                            break
                else:
                    candidate_map: Dict[int, Tuple[str, str]] = {}

                    # 0. Exact indexed title match for swapped alias, clean probe, or title variants (< 0.01 ms)
                    for ep in set(exact_probes):
                        if ep:
                            cur.execute("SELECT article_id, title, summary FROM articles WHERE title = ? LIMIT 1", (ep,))
                            r = cur.fetchone()
                            if r and not any(r[1].startswith(pfx) for pfx in ("Wikipedia:", "Category:", "Portal:", "Template:", "Help:", "Draft:")):
                                candidate_map[r[0]] = (r[1], r[2])

                    for cw in content_words:
                        cur.execute("SELECT article_id, title, summary FROM articles WHERE title LIKE ? AND title NOT LIKE 'Wikipedia:%' AND title NOT LIKE 'Category:%' AND title NOT LIKE 'Portal:%' LIMIT 15", (f"%{cw}%",))
                        for r in cur.fetchall():
                            candidate_map[r[0]] = (r[1], r[2])

                    # Direct phrase lookup
                    if len(content_words) > 1:
                        phrase = " ".join(content_words)
                        cur.execute("SELECT article_id, title, summary FROM articles WHERE title LIKE ? AND title NOT LIKE 'Wikipedia:%' AND title NOT LIKE 'Category:%' AND title NOT LIKE 'Portal:%' LIMIT 10", (f"%{phrase}%",))
                        for r in cur.fetchall():
                            candidate_map[r[0]] = (r[1], r[2])

                    # Check for ordinals like 18th, 32nd, 1st
                    ordinals = [w for w in content_words if re.match(r"^\d+(?:st|nd|rd|th)$", w)]
                    for o in ordinals:
                        cur.execute("SELECT article_id, title, summary FROM articles WHERE summary LIKE ? AND title NOT LIKE 'Wikipedia:%' AND title NOT LIKE 'Category:%' AND title NOT LIKE 'Portal:%' LIMIT 15", (f"%{o} president%",))
                        for r in cur.fetchall():
                            candidate_map[r[0]] = (r[1], r[2])

                    # Descriptive / Superlative semantic search in summary
                    superlatives = ["famous", "greatest", "first", "largest", "fastest", "leading", "prominent"]
                    if any(s in working_query.lower() for s in superlatives):
                        primary_kw = content_words[0] if content_words else "president"
                        cur.execute(
                            "SELECT article_id, title, summary FROM articles WHERE (summary LIKE ? OR title LIKE ?) "
                            "AND (summary LIKE '%greatest%' OR summary LIKE '%famous%' OR summary LIKE '%prominent%') "
                            "AND title NOT LIKE 'Wikipedia:%' AND title NOT LIKE 'Category:%' AND title NOT LIKE 'Portal:%' LIMIT 15",
                            (f"%{primary_kw}%", f"%{primary_kw}%"),
                        )
                        for r in cur.fetchall():
                            candidate_map[r[0]] = (r[1], r[2])

                    # Semantic Scoring across candidate entities
                    scored_candidates = []
                    q_lower = working_query.lower()
                    clean_q = re.sub(r"[^\w\s]", "", working_query).strip().lower()

                    for art_id, (t_val, s_val) in candidate_map.items():
                        score = 0.0
                        t_lower = t_val.lower()
                        s_lower = s_val.lower()

                        # Wikipedia administrative / meta page rejection
                        if any(t_val.startswith(pfx) for pfx in ("Wikipedia:", "Category:", "Portal:", "Template:", "Help:", "Draft:", "File:", "User:", "Talk:")):
                            score -= 200.0

                        # Disambiguation penalty: an index or redirect page is not a grounded knowledge leaf
                        if "(disambiguation)" in t_lower or "may refer to:" in s_lower or "most commonly refers to:" in s_lower or "refers to:" in s_lower[:120]:
                            score -= 80.0

                        # Exact or near-exact title match: massive resonance
                        if t_lower == clean_q or clean_q == t_lower:
                            score += 60.0
                        elif t_lower in q_lower or any(t_lower == cw for cw in content_words):
                            score += 40.0
                        elif any(re.search(rf"\b{re.escape(cw)}\b", t_lower) for cw in content_words):
                            score += 15.0

                        # Question Type Invariant: "Who" requires animate / human entity
                        is_who_query = bool(re.search(r"\bwho\s+(?:was|is|were|are|created|invented|discovered|wrote|designed)\b", q_lower))
                        if is_who_query:
                            if t_lower.startswith("list of "):
                                score -= 50.0
                            if "first lady" in t_lower:
                                score -= 40.0
                            if "election" in t_lower and "election" not in q_lower:
                                score -= 40.0
                            if t_val.startswith("USS ") or t_val.startswith("SS "):
                                score -= 50.0

                            # Digits at start of title indicate asteroid/catalog object
                            if t_val and t_val[0].isdigit():
                                score -= 90.0

                            non_person_markers = [
                                "airport", "station", "building", "bridge", "park", "highway", "stadium",
                                "museum", "university", "school", "hospital", "observatory", "monument",
                                "ship", "car", "automobile", "song", "album", "band", "film", "movie",
                                "(unit)", "theorem", "equation", "constant", "asteroid", "crater", "fault", "hoax"
                            ]
                            if any(npm in t_lower for npm in non_person_markers):
                                score -= 80.0
                            if any(phrase in s_lower[:150] for phrase in [
                                "is an international airport", "is a railway station", "is a building",
                                "is the unit of", "is a rock band", "is a heavy metal band", "is a song by",
                                "is a film", "is a book", "is a novel", "is an asteroid", "is a carbonaceous asteroid",
                                "is a minor planet"
                            ]):
                                score -= 80.0

                        # Penalize bare category concept titles when querying a specific instance (e.g. "Battle" when asking for "Battle of X")
                        if t_lower in {"battle", "war", "treaty", "empire", "dynasty", "kingdom", "siege", "president"}:
                            if f"{t_lower} of" in q_lower or f"{t_lower} in" in q_lower:
                                score -= 80.0

                        # Penalize domain marker concepts if query is constraining domain (e.g. "In physics, what is X?" should not match "Physics")
                        domain_marker_concepts = {"physics", "biology", "history", "philosophy", "engineering", "geography", "mathematics", "computer science", "comp sci"}
                        if t_lower in domain_marker_concepts and any(f"in {c}" in q_lower or f"of {c}" in q_lower for c in domain_marker_concepts):
                            score -= 120.0

                        for cw in content_words:
                            if cw in t_lower:
                                score += 5.0
                            if cw in s_lower:
                                score += 1.0

                        # Primary definition bonus: "{Title} was/is the {ordinal} president"
                        for o in ordinals:
                            if re.search(rf"\b(?:was|is|served as)\s+(?:the\s+)?{o}\s+president\b", s_lower):
                                score += 80.0
                            elif f"{o} president" in s_lower:
                                score += 25.0

                        for sup in superlatives:
                            if sup in q_lower and sup in s_lower:
                                score += 4.0

                        if "greatest president" in s_lower or "famous president" in s_lower:
                            score += 10.0
                        if "president of the united states" in s_lower:
                            score += 6.0

                        # Probe grounding verification
                        if proper_probes:
                            matches = sum(1 for p in proper_probes if p in t_lower or p in s_lower)
                            if matches == 0:
                                score -= 40.0
                            else:
                                score += matches * 8.0

                        scored_candidates.append((score, art_id, t_val, s_val))

                        MIN_RESONANCE_THRESHOLD = 25.0

                        if scored_candidates:
                            scored_candidates.sort(key=lambda x: x[0], reverse=True)
                            best = scored_candidates[0]
                            best_score = best[0]

                            # Check core subject requirement: all critical subject words must be present
                            subject_satisfied = True
                            if core_subject_words:
                                # Non-generic words in subject
                                non_generic = [
                                    w for w in core_subject_words
                                    if w not in {"the", "a", "an", "emperor", "dynasty", "battle", "president", "war", "treaty", "empire"}
                                ]
                                if non_generic:
                                    subject_satisfied = all(
                                        (ng in best[2].lower() or ng in best[3].lower())
                                        for ng in non_generic
                                    )

                            # Check distinctive proper probes: if query specified proper names, at least one MUST be in candidate
                            generic_class_nouns = {
                                "battle", "war", "treaty", "empire", "dynasty", "president",
                                "king", "queen", "emperor", "country", "city", "river", "mountain",
                                "formula", "theory", "law", "the", "first", "second",
                                "north", "south", "east", "west", "upper", "lower", "new", "old"
                            }
                            distinctive_probes = [p for p in proper_probes if p not in generic_class_nouns and not p.isdigit()]
                            if distinctive_probes:
                                match_count = sum(
                                    1 for dp in distinctive_probes
                                    if (dp in best[2].lower() or dp in best[3].lower())
                                )
                                required_matches = min(2, len(distinctive_probes)) if len(distinctive_probes) >= 2 else 1
                                if match_count < required_matches:
                                    subject_satisfied = False

                            if best_score >= MIN_RESONANCE_THRESHOLD and subject_satisfied:
                                clean_text = clean_lead_text(best[3], best[2])
                                matched_entity = {
                                    "title": best[2],
                                    "summary": clean_text[:800],
                                    "source": db_path.name,
                                }

                                # ==============================================================================
                                # Dual-Layer Reasoning: Hop 1 (Deterministic) vs Hop >1 (Probabilistic)
                                # ==============================================================================
                                # Hop 1 is strictly Deterministic (P = 1.0, Ground Truth Invariant)
                                hop_chain = [{
                                    "hop": 1,
                                    "type": "DETERMINISTIC",
                                    "entity": best[2],
                                    "p": 1.000,
                                    "source": db_path.name
                                }]

                                # > 1 Hops: Probabilistic Exploration (T > 0.0)
                                prob_hops = []
                                if temperature > 0.05:
                                    max_hops = max(1, int(temperature * 3))
                                    internal_concepts = re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*", best[3])
                                    stop_concepts = {best[2], "United States", "March", "April", "December", "February", "U.S.", "Illinois", "Kentucky", "Indiana"}
                                    visited_entities = {best[2]}
                                    current_entity = best[2]

                                    for h in range(2, max_hops + 2):
                                        candidates = []
                                        for c in set(internal_concepts):
                                            if c not in stop_concepts and c not in visited_entities and len(c) > 3:
                                                cur.execute("SELECT article_id, title, summary FROM articles WHERE title = ? LIMIT 1", (c,))
                                                row = cur.fetchone()
                                                if row and row[1] not in visited_entities:
                                                    p_trans = self._compute_rotor_transition_prob(current_entity, row[1])
                                                    candidates.append((p_trans, row[1], row[2]))

                                        if candidates:
                                            candidates.sort(key=lambda x: x[0], reverse=True)
                                            top_prob, top_title, top_summary = candidates[0]
                                            min_p = max(0.50, 0.90 - (temperature * 0.40))
                                            if top_prob >= min_p:
                                                prob_hops.append({
                                                    "hop": h,
                                                    "type": "PROBABILISTIC",
                                                    "entity": top_title,
                                                    "p": round(top_prob, 4),
                                                })
                                                visited_entities.add(top_title)
                                                current_entity = top_title
                                                internal_concepts = re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*", top_summary)
                                            else:
                                                break
                                        else:
                                            break

                                peer_candidates = [s[2] for s in scored_candidates[1:] if s[0] >= 5.0][:max(1, int(temperature * 4))] if temperature > 0.05 else []

                                exploration_meta = {
                                    "hop_chain": hop_chain + prob_hops,
                                    "probabilistic_hops": prob_hops,
                                    "resonant_peers": peer_candidates,
                                    "temperature": temperature,
                                }

                conn.close()
            except Exception as e:
                print(f"[-] SQLite lookup error: {e}")

        rotor_rerouted = False
        reroute_trace = None

        # 1.8 Cross-Rotor Resonance Fallback: If ungrounded in primary domain, search alternate domain manifolds
        if not matched_entity and domain != "python":
            MIN_RESONANCE_THRESHOLD = 25.0

            # Phase 1: Priority exact title probe across all alternate domain databases
            exact_match_found = False
            for alt_domain, alt_db in DOMAIN_DATABASES.items():
                if alt_domain == domain or alt_domain == "python" or not alt_db.exists():
                    continue
                try:
                    alt_conn = sqlite3.connect(str(alt_db))
                    alt_cur = alt_conn.cursor()
                    for ep in set(exact_probes):
                        if ep:
                            alt_cur.execute("SELECT article_id, title, summary FROM articles WHERE title = ? LIMIT 1", (ep,))
                            r = alt_cur.fetchone()
                            if r:
                                if any(r[1].startswith(pfx) for pfx in ("Wikipedia:", "Category:", "Portal:", "Template:", "Help:", "Draft:", "File:", "User:", "Talk:")):
                                    continue
                                t_alt = r[1].lower()
                                s_alt = r[2].lower()
                                # Disambiguation filter: reject index / redirect pages in cross-rotor probe
                                if "(disambiguation)" in t_alt or "may refer to:" in s_alt or "most commonly refers to:" in s_alt or "refers to:" in s_alt[:120]:
                                    continue
                                # Animate constraint for "who" queries
                                is_who_q = bool(re.search(r"\bwho\s+(?:was|is|were|are|created|invented|discovered|wrote|designed)\b", working_query.lower()))
                                if is_who_q:
                                    if r[1] and r[1][0].isdigit():
                                        continue
                                    non_person = ["airport", "station", "building", "bridge", "park", "highway", "stadium", "museum", "university", "(unit)", "asteroid", "song", "album", "band", "film"]
                                    if any(np in t_alt for np in non_person) or any(ph in s_alt[:150] for ph in ["is an international airport", "is the unit of", "is a rock band", "is an asteroid"]):
                                        continue
                                clean_text = clean_lead_text(r[2], r[1])
                                rotor_rerouted = True
                                initial_dom = domain
                                initial_g = gauge_shift
                                resolved_g = DOMAIN_GAUGES.get(alt_domain, 0)
                                reroute_trace = {
                                    "initial_domain": initial_dom,
                                    "initial_gauge": initial_g,
                                    "resolved_domain": alt_domain,
                                    "resolved_gauge": resolved_g,
                                    "diagnostic": f"Entity '{r[1]}' ungrounded in requested domain '{initial_dom}' (Gauge {initial_g}); cross-rotor resonance resolved via '{alt_domain}' manifold (Gauge {resolved_g}, {alt_db.name})."
                                }
                                swap_ms += self.stack.mount_domain_rotor(alt_domain)
                                domain = alt_domain
                                gauge_shift = resolved_g
                                query_key = b52_key(working_query, shift=gauge_shift)
                                db_path = alt_db
                                matched_entity = {
                                    "title": r[1],
                                    "summary": clean_text[:800],
                                    "source": alt_db.name,
                                }
                                exploration_meta = {
                                    "hop_chain": [{
                                        "hop": 1,
                                        "type": "CROSS_ROTOR_DETERMINISTIC",
                                        "entity": r[1],
                                        "p": 1.000,
                                        "source": alt_db.name,
                                        "reroute_from": initial_dom
                                    }],
                                    "probabilistic_hops": [],
                                    "resonant_peers": [],
                                    "temperature": temperature,
                                    "rotor_rerouted": True,
                                    "reroute_trace": reroute_trace
                                }
                                exact_match_found = True
                                alt_conn.close()
                                break
                    alt_conn.close()
                    if exact_match_found:
                        break
                except Exception as ex:
                    print(f"[-] Cross-rotor exact probe error in {alt_domain}: {ex}")

            # Phase 2: If no exact title match across all databases, check semantic content words
            if not matched_entity and content_words:
                for alt_domain, alt_db in DOMAIN_DATABASES.items():
                    if alt_domain == domain or alt_domain == "python" or not alt_db.exists():
                        continue
                    try:
                        alt_conn = sqlite3.connect(str(alt_db))
                        alt_cur = alt_conn.cursor()
                        alt_cand_map: Dict[int, Tuple[str, str]] = {}

                        for cw in content_words:
                            alt_cur.execute("SELECT article_id, title, summary FROM articles WHERE title LIKE ? AND title NOT LIKE 'Wikipedia:%' AND title NOT LIKE 'Category:%' AND title NOT LIKE 'Portal:%' LIMIT 10", (f"%{cw}%",))
                            for r in alt_cur.fetchall():
                                alt_cand_map[r[0]] = (r[1], r[2])

                        if alt_cand_map:
                            alt_scored = []
                            q_lower = working_query.lower()
                            clean_q = re.sub(r"[^\w\s]", "", working_query).strip().lower()
                            for art_id, (t_val, s_val) in alt_cand_map.items():
                                sc = 0.0
                                t_low = t_val.lower()
                                s_low = s_val.lower()

                                # Wikipedia administrative / meta page rejection
                                if any(t_val.startswith(pfx) for pfx in ("Wikipedia:", "Category:", "Portal:", "Template:", "Help:", "Draft:", "File:", "User:", "Talk:")):
                                    sc -= 200.0

                                # Disambiguation penalty
                                if "(disambiguation)" in t_low or "may refer to:" in s_low or "most commonly refers to:" in s_low or "refers to:" in s_low[:120]:
                                    sc -= 80.0

                                if t_low == clean_q or clean_q == t_low:
                                    sc += 60.0
                                elif t_low in q_lower or any(t_low == cw for cw in content_words):
                                    sc += 40.0
                                elif any(re.search(rf"\b{re.escape(cw)}\b", t_low) for cw in content_words):
                                    sc += 15.0

                                # Question Type Invariant: "Who" requires animate / human entity
                                is_who_query = bool(re.search(r"\bwho\s+(?:was|is|were|are|created|invented|discovered|wrote|designed)\b", q_lower))
                                if is_who_query:
                                    if t_low.startswith("list of "):
                                        sc -= 50.0
                                    if "first lady" in t_low:
                                        sc -= 40.0
                                    if "election" in t_low and "election" not in q_lower:
                                        sc -= 40.0
                                    if t_val.startswith("USS ") or t_val.startswith("SS "):
                                        sc -= 50.0

                                    if t_val and t_val[0].isdigit():
                                        sc -= 90.0

                                    non_person_markers = [
                                        "airport", "station", "building", "bridge", "park", "highway", "stadium",
                                        "museum", "university", "school", "hospital", "observatory", "monument",
                                        "ship", "car", "automobile", "song", "album", "band", "film", "movie",
                                        "(unit)", "theorem", "equation", "constant", "asteroid", "crater", "fault", "hoax"
                                    ]
                                    if any(npm in t_low for npm in non_person_markers):
                                        sc -= 80.0
                                    if any(phrase in s_low[:150] for phrase in [
                                        "is an international airport", "is a railway station", "is a building",
                                        "is the unit of", "is a rock band", "is a heavy metal band", "is a song by",
                                        "is a film", "is a book", "is a novel", "is an asteroid", "is a carbonaceous asteroid",
                                        "is a minor planet"
                                    ]):
                                        sc -= 80.0

                                # Domain marker suppression
                                domain_marker_concepts = {"physics", "biology", "history", "philosophy", "engineering", "geography", "mathematics", "computer science", "comp sci"}
                                if t_low in domain_marker_concepts and any(f"in {c}" in q_lower or f"of {c}" in q_lower for c in domain_marker_concepts):
                                    sc -= 120.0

                                for cw in content_words:
                                    if cw in t_low: sc += 5.0
                                    if cw in s_low: sc += 1.0

                                if proper_probes:
                                    matches = sum(1 for p in proper_probes if p in t_low or p in s_low)
                                    if matches == 0:
                                        sc -= 40.0
                                    else:
                                        sc += matches * 8.0

                                alt_scored.append((sc, art_id, t_val, s_val))

                            alt_scored.sort(key=lambda x: x[0], reverse=True)
                            if alt_scored and alt_scored[0][0] >= MIN_RESONANCE_THRESHOLD:
                                best_alt = alt_scored[0]
                                alt_subject_satisfied = True
                                if core_subject_words:
                                    non_gen = [w for w in core_subject_words if w not in {"the", "a", "an", "emperor", "dynasty", "battle", "president", "war", "treaty"}]
                                    if non_gen:
                                        alt_subject_satisfied = all((ng in best_alt[2].lower() or ng in best_alt[3].lower()) for ng in non_gen)

                                generic_class_nouns = {"battle", "war", "treaty", "empire", "dynasty", "president", "king", "queen", "emperor", "country", "city", "river", "mountain", "formula", "theory", "law", "the"}
                                distinctive_probes = [p for p in proper_probes if p not in generic_class_nouns and not p.isdigit()]
                                if distinctive_probes:
                                    match_count = sum(1 for dp in distinctive_probes if (dp in best_alt[2].lower() or dp in best_alt[3].lower()))
                                    req_matches = min(2, len(distinctive_probes)) if len(distinctive_probes) >= 2 else 1
                                    if match_count < req_matches:
                                        alt_subject_satisfied = False

                                if alt_subject_satisfied:
                                    clean_text = clean_lead_text(best_alt[3], best_alt[2])
                                    rotor_rerouted = True
                                    initial_dom = domain
                                    initial_g = gauge_shift
                                    resolved_g = DOMAIN_GAUGES.get(alt_domain, 0)
                                    reroute_trace = {
                                        "initial_domain": initial_dom,
                                        "initial_gauge": initial_g,
                                        "resolved_domain": alt_domain,
                                        "resolved_gauge": resolved_g,
                                        "diagnostic": f"Entity '{best_alt[2]}' ungrounded in requested domain '{initial_dom}' (Gauge {initial_g}); cross-rotor resonance resolved via '{alt_domain}' manifold (Gauge {resolved_g}, {alt_db.name})."
                                    }
                                    swap_ms += self.stack.mount_domain_rotor(alt_domain)
                                    domain = alt_domain
                                    gauge_shift = resolved_g
                                    query_key = b52_key(working_query, shift=gauge_shift)
                                    db_path = alt_db
                                    matched_entity = {
                                        "title": best_alt[2],
                                        "summary": clean_text[:800],
                                        "source": alt_db.name,
                                    }
                                    exploration_meta = {
                                        "hop_chain": [{
                                            "hop": 1,
                                            "type": "CROSS_ROTOR_DETERMINISTIC",
                                            "entity": best_alt[2],
                                            "p": 1.000,
                                            "source": alt_db.name,
                                            "reroute_from": initial_dom
                                        }],
                                        "probabilistic_hops": [],
                                        "resonant_peers": [],
                                        "temperature": temperature,
                                        "rotor_rerouted": True,
                                        "reroute_trace": reroute_trace
                                    }
                                    alt_conn.close()
                                    break
                        alt_conn.close()
                    except Exception as ex:
                        print(f"[-] Cross-rotor search error in {alt_domain}: {ex}")

        # 2. Evaluate UML Reflector Gate
        if matched_entity:
            self.last_entity = matched_entity["title"]
            gate_status = f"<!0, !0> = {UML_CEILING:.1f} (RESONANT REFLECTION)"
            response_text = self.softener.soften(
                query=query,
                domain=domain,
                title=matched_entity["title"],
                clean_lead=matched_entity["summary"],
                exploration_meta=exploration_meta,
                temperature=temperature,
                persona=persona,
            )
            is_grounded = True
        else:
            # Check if this query is a self-referential / conversational query
            q_clean = working_query.lower().strip(" ?.")
            is_self_referential = any(
                q_clean.startswith(prefix) for prefix in [
                    "who are you", "what are you", "what can you do", "what is your name",
                    "who made you", "who created you", "how are you", "what do you do",
                    "help", "capabilities"
                ]
            ) or any(
                q_clean.startswith(g) for g in [
                    "hello", "hi", "hey", "greetings", "good morning", "good afternoon", "good evening"
                ]
            )

            # Check if this query was an explicit factual probe
            is_factual_probe = (
                not is_self_referential
                and (
                    any(working_query.lower().strip().startswith(prefix) for prefix in [
                        "who", "what is", "what was", "tell me about", "where", "explain how", "explain the", "define", "describe", "was ", "is "
                    ])
                    or bool(proper_probes)
                )
                and any(len(w) >= 3 for w in re.findall(r"[a-zA-Z0-9]+", working_query))
            )

            if is_factual_probe:
                # First check if the Sovereign Live Crystallizer can resolve it from Wikipedia REST API!
                crystallized = None
                generic_class_nouns = {"emperor", "king", "queen", "president", "general", "mars", "earth", "sir", "lord", "lady"}
                distinctive_probes = [p for p in proper_probes if p not in generic_class_nouns and not p.isdigit()]

                probe_candidates = []
                if core_subject and not core_subject.isdigit():
                    probe_candidates.append(core_subject)
                clean_probe = re.sub(
                    r"^(who\s+(?:was|is)|what\s+(?:was|is|are)|when\s+(?:was|did|is)|where\s+(?:was|is|did)|tell\s+me\s+about|define|explain)\s+(?:the\s+)?",
                    "",
                    working_query,
                    flags=re.I
                ).strip(" ?.")
                clean_probe = re.sub(r"\s+(?:in|on|at|during|from)?\s*\b\d{1,4}\b(?:\s*(?:bc|ad|bce|ce))?$", "", clean_probe, flags=re.I).strip(" ?.")
                if clean_probe and clean_probe not in probe_candidates and not clean_probe.isdigit():
                    probe_candidates.append(clean_probe)
                for pp in proper_probes:
                    if pp.isdigit() or (distinctive_probes and pp in generic_class_nouns):
                        continue
                    if pp not in probe_candidates:
                        probe_candidates.append(pp)

                for pc in probe_candidates:
                    if pc and len(pc) >= 2 and not pc.isdigit():
                        res = VivLiveCrystallizer.resolve_and_crystallize(pc)
                        if res:
                            if distinctive_probes:
                                t_low = res["title"].lower()
                                s_low = res["summary"].lower()
                                match_count = sum(1 for dp in distinctive_probes if (dp in t_low or dp in s_low))
                                req_matches = min(2, len(distinctive_probes)) if len(distinctive_probes) >= 2 else 1
                                if match_count >= req_matches:
                                    crystallized = res
                                    break
                            else:
                                crystallized = res
                                break

                if crystallized:
                    matched_entity = {
                        "title": crystallized["title"],
                        "summary": crystallized["summary"],
                        "source": crystallized["source"],
                    }
                    self.last_entity = matched_entity["title"]
                    gate_status = f"<!0, !0> = {UML_CEILING:.1f} (RESONANT REFLECTION)"
                    exploration_meta = {
                        "hop_chain": [{
                            "hop": 1,
                            "type": "LIVE_CRYSTALLIZED",
                            "entity": crystallized["title"],
                            "p": 1.000,
                            "source": crystallized["source"],
                            "revision_time": crystallized.get("revision_time"),
                        }],
                        "peer_candidates": [],
                    }
                    response_text = self.softener.soften(
                        query=query,
                        domain=domain,
                        title=matched_entity["title"],
                        clean_lead=matched_entity["summary"],
                        exploration_meta=exploration_meta,
                        temperature=temperature,
                        persona=persona,
                    )
                    is_grounded = True
                else:
                    # Deterministic brake trips on ungrounded or unlearned entities
                    gate_status = f"{{!0, !0}} = {UML_FLOOR:.1f} (DETERMINISTIC BRAKE)"
                    response_text = "NULL_UNLEARNED_ENTITY"
                    is_grounded = False
            else:
                # Conversational synthesis through Grammar Rotor
                gate_status = f"<!0, !0> = {UML_CEILING:.1f} (SYNTACTIC CONVERSATION)"
                response_text = self._synthesize_response(query, persona=persona)
                is_grounded = True

        latency_ms = (time.perf_counter() - t0) * 1000

        return {
            "domain": domain,
            "gauge_shift": gauge_shift,
            "base52_key": query_key,
            "gate_status": gate_status,
            "is_grounded": is_grounded,
            "matched_entity": matched_entity["title"] if matched_entity else None,
            "response": response_text,
            "hop_chain": exploration_meta.get("hop_chain", []),
            "plugboard_swap": plugboard_trace,
            "rotor_rerouted": rotor_rerouted,
            "reroute_trace": reroute_trace,
            "latency_ms": round(latency_ms, 2),
            "swap_ms": round(swap_ms, 2),
        }

    def _synthesize_response(self, prompt: str, persona: str = "jarvis") -> str:
        """Conversational synthesis using active rotor stack and persona transducer."""
        return self.softener.synthesize_conversational(
            query=prompt,
            active_domain=self.stack.active_domain,
            persona=persona
        )


# ==============================================================================
# Sovereign OpenAI-Compatible Server for AIOS V2
# ==============================================================================

class EnigmaHTTPHandler(BaseHTTPRequestHandler):
    dispatcher: DualSubstrateDispatcher = None

    def log_message(self, format, *args):
        pass

    def _send_json(self, status: int, data: Dict[str, Any]):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            ui_path = Path(__file__).resolve().parent / "viv_web_ui.html"
            if ui_path.exists():
                content = ui_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content)
            else:
                self._send_json(404, {"error": "Web UI file not found"})
        elif self.path == "/v1/models":
            self._send_json(200, {
                "object": "list",
                "data": [{
                    "id": "vtm-enigma-transducer",
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "viv_aios_v2",
                    "active_rotor": self.dispatcher.stack.active_domain,
                    "vram_mb": round(torch.cuda.memory_allocated() / (1024*1024), 2),
                }]
            })
        elif self.path == "/health":
            self._send_json(200, {
                "status": "ok",
                "engine": "InvertedEnigmaTransducer",
                "active_domain": self.dispatcher.stack.active_domain,
                "vram_mb": round(torch.cuda.memory_allocated() / (1024*1024), 2),
                "device": str(self.dispatcher.stack.device),
            })
        else:
            self._send_json(404, {"error": "Endpoint not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            payload = {}

        if self.path in ("/v1/chat/completions", "/v1/completions"):
            is_chat = (self.path == "/v1/chat/completions")
            stream_mode = bool(payload.get("stream", False))
            temperature = float(payload.get("temperature", 0.2))
            persona = str(payload.get("persona", "jarvis"))

            if is_chat:
                messages = payload.get("messages", [])
                raw_query = messages[-1].get("content", "") if messages else ""
                resolved_query, _ = SessionDiscourseManager.resolve_query(messages, prior_entity=self.dispatcher.last_entity)
            else:
                raw_query = payload.get("prompt", "")
                resolved_query = raw_query

            result = self.dispatcher.route_query(resolved_query, temperature=temperature, persona=persona)
            if result.get("matched_entity"):
                self.dispatcher.last_entity = result["matched_entity"]

            completion_id = f"chatcmpl-enigma-{int(time.time()*1000)}"

            if stream_mode:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()

                full_text = result["response"]
                tokens = re.findall(r"\S+|\s+", full_text)

                for idx, tok in enumerate(tokens):
                    chunk_obj = {
                        "id": completion_id,
                        "object": "chat.completion.chunk" if is_chat else "text_completion",
                        "created": int(time.time()),
                        "model": "vtm-enigma-transducer",
                        "choices": [{
                            "index": 0,
                            "delta": {"content": tok} if is_chat else {},
                            "text": tok if not is_chat else None,
                            "finish_reason": None,
                        }]
                    }
                    if idx == 0:
                        chunk_obj["enigma_trace"] = {
                            "domain": result["domain"],
                            "gauge_shift": result["gauge_shift"],
                            "base52_key": result["base52_key"],
                            "gate_status": result["gate_status"],
                            "matched_entity": result["matched_entity"],
                            "hop_chain": result.get("hop_chain", []),
                            "plugboard_swap": result.get("plugboard_swap"),
                            "persona": persona,
                            "temperature": temperature,
                            "latency_ms": result["latency_ms"],
                            "swap_ms": result["swap_ms"],
                        }
                    chunk_bytes = f"data: {json.dumps(chunk_obj, ensure_ascii=False)}\n\n".encode("utf-8")
                    self.wfile.write(chunk_bytes)
                    self.wfile.flush()
                    time.sleep(0.005)

                # Stop chunk
                stop_obj = {
                    "id": completion_id,
                    "object": "chat.completion.chunk" if is_chat else "text_completion",
                    "created": int(time.time()),
                    "model": "vtm-enigma-transducer",
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }],
                    "enigma_trace": {
                        "domain": result["domain"],
                        "gauge_shift": result["gauge_shift"],
                        "base52_key": result["base52_key"],
                        "gate_status": result["gate_status"],
                        "matched_entity": result["matched_entity"],
                        "hop_chain": result.get("hop_chain", []),
                        "plugboard_swap": result.get("plugboard_swap"),
                        "rotor_rerouted": result.get("rotor_rerouted", False),
                        "reroute_trace": result.get("reroute_trace"),
                        "persona": persona,
                        "temperature": temperature,
                        "latency_ms": result["latency_ms"],
                        "swap_ms": result["swap_ms"],
                    }
                }
                self.wfile.write(f"data: {json.dumps(stop_obj, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            else:
                resp = {
                    "id": completion_id,
                    "object": "chat.completion" if is_chat else "text_completion",
                    "created": int(time.time()),
                    "model": "vtm-enigma-transducer",
                    "choices": [{
                        "index": 0,
                        "text": result["response"],
                        "message": {"role": "assistant", "content": result["response"]},
                        "finish_reason": "stop",
                    }],
                    "enigma_trace": {
                        "domain": result["domain"],
                        "gauge_shift": result["gauge_shift"],
                        "base52_key": result["base52_key"],
                        "gate_status": result["gate_status"],
                        "matched_entity": result["matched_entity"],
                        "hop_chain": result.get("hop_chain", []),
                        "plugboard_swap": result.get("plugboard_swap"),
                        "rotor_rerouted": result.get("rotor_rerouted", False),
                        "reroute_trace": result.get("reroute_trace"),
                        "persona": persona,
                        "temperature": temperature,
                        "latency_ms": result["latency_ms"],
                        "swap_ms": result["swap_ms"],
                    }
                }
                self._send_json(200, resp)

        elif self.path == "/v1/quiesce":
            torch.cuda.empty_cache()
            self._send_json(200, {"status": "quiesced"})

        elif self.path == "/v1/resume":
            self._send_json(200, {"status": "resumed"})

        elif self.path == "/v1/mount":
            domain = payload.get("domain", "physics")
            ms = self.dispatcher.stack.mount_domain_rotor(domain)
            self._send_json(200, {"status": "mounted", "domain": domain, "swap_ms": ms})

        else:
            self._send_json(404, {"error": "Endpoint not found"})


def run_enigma_server(port: int = 1235):
    stack = EnigmaRotorStack()
    dispatcher = DualSubstrateDispatcher(stack)
    EnigmaHTTPHandler.dispatcher = dispatcher

    server = ThreadingHTTPServer(("127.0.0.1", port), EnigmaHTTPHandler)
    print(f"[*] Inverted Enigma Sovereign Server listening on http://127.0.0.1:{port}")
    print(f"    Allocated VRAM: {torch.cuda.memory_allocated() / (1024*1024):.2f} MB")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=1235)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    if args.test:
        stack = EnigmaRotorStack()
        disp = DualSubstrateDispatcher(stack)
        test_queries = [
            "What is an Astronomer?",
            "Explain DNA in biology",
            "What is ASCII in computers?",
            "Who is Zaphod Beeblebrox Nonexistent?",
        ]
        for q in test_queries:
            r = disp.route_query(q)
            print(f"\nQuery: {q}")
            print(f"  Domain: {r['domain']} | Shift: {r['gauge_shift']} | Key: {r['base52_key']}")
            print(f"  Gate: {r['gate_status']} | Latency: {r['latency_ms']} ms")
            print(f"  Response: {r['response'][:140]}...")
    else:
        run_enigma_server(port=args.port)
