"""Physical Dialogue Adapter for Viv: Natural Language to Topological Wave Reasoning.

Bridges human conversational queries directly into Viv's first-principles physical lattice:
1. Parses natural language questions to identify physical/causal anchor poles.
2. Pulses the anchors through ConceptualResonanceEngine (zero matrix multiplies).
3. Synthesizes deterministic causal explanations and engineering deductions
   grounded in Viv's verified ontology conduits.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
import sys

WORKSPACE = Path(r"L:\LocalCoder\workspace")
sys.path.insert(0, str(WORKSPACE))
sys.path.insert(0, r"L:\Standalone\NN")

from autonomy.terminal_neuron_learning import latest_run
from nn_local.steel_brain_store import SQLiteNeuronGraphStore
from autonomy.conceptual_resonance_engine import ConceptualResonanceEngine

AUTONOMY_DATA = WORKSPACE / "autonomy/data"
DB_PATH = AUTONOMY_DATA / "lexicon_ontology.db"

# Physical domain keyword dictionary mapping conversational variants to graph tokens
PHYSICAL_SYNONYMS = {
    "computer": "power",
    "pc": "power",
    "hardware": "power",
    "device": "load",
    "freeze": "cold",
    "freezes": "cold",
    "freezing": "cold",
    "frozen": "ice",
    "unplugged": "shut",
    "shutdown": "shut",
    "shutoff": "off",
    "breaks": "break",
    "broken": "break",
    "leaking": "leak",
    "flooding": "flood",
    "bursting": "burst",
    "rubbing": "friction",
    "heating": "heat",
    "boiling": "boiling",
    "pressure": "pressure",
    "steam": "steam",
    "hot": "hot",
    "cold": "cold",
    "water": "water",
    "pipe": "pipe",
    "wire": "wire",
    "metal": "metal",
    "power": "power",
    "shut": "shut",
    "off": "off",
    "breaker": "breaker",
    "fuse": "fuse",
    "voltage": "voltage",
    "current": "current",
    "resistance": "resistance",
    "overload": "overload",
    "short": "short",
    "spark": "spark",
    "tool": "tool",
    "force": "force",
    "forces": "force",
    "lever": "lever",
    "torque": "torque",
    "bolt": "bolt",
    "valve": "valve",
    "piston": "piston",
    "engine": "engine",
    "blockage": "blockage",
    "clog": "blockage",
    "clogged": "blockage",
    "stress": "stress",
    "rupture": "rupture",
    "fulcrum": "fulcrum",
    "pivot": "fulcrum",
    "pivoting": "fulcrum",
    "effort": "effort",
    "load": "load",
    "wheel": "wheel",
    "wheels": "wheel",
    "axle": "axle",
    "pulley": "pulley",
    "pulleys": "pulley",
    "rope": "rope",
    "ropes": "rope",
    "cable": "cable",
    "hoist": "hoist",
    "hoisting": "hoist",
    "ramp": "ramp",
    "ramps": "ramp",
    "slope": "slope",
    "incline": "slope",
    "inclined": "slope",
    "wedge": "wedge",
    "wedges": "wedge",
    "blade": "blade",
    "axe": "axe",
    "split": "split",
    "splitting": "split",
    "cleave": "split",
    "cleaving": "split",
    "screw": "screw",
    "screws": "screw",
    "thread": "thread",
    "threads": "thread",
    "pitch": "pitch",
    "clamp": "clamp",
    "clamping": "clamp",
    "fasten": "fasten",
    "fastener": "fastener",
    "joint": "joint",
    "lift": "lift",
    "lifting": "lift",
    "gravity": "gravity",
    "gravitational": "gravity",
    "fall": "fall",
    "falling": "fall",
    "drop": "drop",
    "dropped": "drop",
    "mass": "mass",
    "weight": "weight",
    "speed": "speed",
    "velocity": "velocity",
    "accelerate": "acceleration",
    "acceleration": "acceleration",
    "accelerating": "acceleration",
    "inertia": "inertia",
    "momentum": "momentum",
    "thrust": "thrust",
    "recoil": "recoil",
    "impact": "impact",
    "collision": "collision",
    "bounce": "bounce",
    "bouncing": "bounce",
    "kinetic": "kinetic",
    "potential": "potential",
    "energy": "energy",
    "ground": "ground",
    "earth": "earth",
    "point": "point",
    "points": "point",
    "line": "line",
    "lines": "line",
    "angle": "angle",
    "angles": "angle",
    "triangle": "triangle",
    "triangles": "triangle",
    "square": "square",
    "squares": "square",
    "circle": "circle",
    "circles": "circle",
    "radius": "radius",
    "diameter": "diameter",
    "cube": "cube",
    "cubes": "cube",
    "sphere": "sphere",
    "spheres": "sphere",
    "area": "area",
    "surface": "surface",
    "perimeter": "perimeter",
    "boundary": "boundary",
    "shape": "shape",
    "geometry": "shape",
    "rigid": "rigid",
    "rigidity": "rigid",
    "truss": "triangle",
    # Light & Optics
    "light": "light",
    "lights": "light",
    "ray": "ray",
    "rays": "ray",
    "beam": "ray",
    "beams": "ray",
    "sun": "sun",
    "sunlight": "light",
    "obstacle": "obstacle",
    "opaque": "obstacle",
    "shadow": "shadow",
    "shadows": "shadow",
    "mirror": "mirror",
    "mirrors": "mirror",
    "reflect": "reflect",
    "reflects": "reflect",
    "reflection": "reflect",
    "specular": "mirror",
    "refract": "glass",
    "refracts": "glass",
    "refraction": "glass",
    "bend": "glass",
    "bends": "glass",
    "bent": "glass",
    "lens": "lens",
    "lenses": "lens",
    "glass": "glass",
    "image": "image",
    "images": "image",
    "focus": "lens",
    "focuses": "lens",
    # Sound & Acoustics
    "sound": "sound",
    "sounds": "sound",
    "vibration": "vibration",
    "vibrations": "vibration",
    "vibrate": "vibration",
    "vibrates": "vibration",
    "vibrating": "vibration",
    "wave": "wave",
    "waves": "wave",
    "medium": "air",
    "acoustic": "sound",
    "acoustics": "sound",
    "vacuum": "vacuum",
    "space": "vacuum",
    "pitch": "pitch",
    "tone": "pitch",
    "frequency": "pitch",
    "echo": "echo",
    "echoes": "echo",
    "ear": "ear",
    "ears": "ear",
    "hear": "ear",
    "hearing": "ear",
    "listen": "ear",
    # Conservation of Energy & Thermodynamics
    "energy": "energy",
    "energies": "energy",
    "conserve": "energy",
    "conserved": "energy",
    "conservation": "energy",
    "work": "work",
    "destroy": "energy",
    "destroyed": "energy",
    "destruction": "energy",
    "fuel": "fuel",
    "chemical": "chemical",
    "thermal": "thermal",
    "steam": "steam",
    "turbine": "generator",
    "generator": "generator",
    "generators": "generator",
    "electric": "electric",
    "electricity": "electric",
    "dissipate": "friction",
    "dissipates": "friction",
    "dissipation": "friction",
    "entropy": "entropy",
    # Biological Systems & Homeostasis
    "human": "human",
    "humans": "human",
    "people": "human",
    "person": "human",
    "body": "body",
    "bodies": "body",
    "life": "life",
    "living": "life",
    "alive": "alive",
    "food": "food",
    "eat": "food",
    "eating": "food",
    "meal": "food",
    "calorie": "food",
    "calories": "food",
    "glucose": "glucose",
    "sugar": "glucose",
    "metabolism": "chemical",
    "respiration": "oxygen",
    "breathe": "breath",
    "breathing": "breath",
    "breath": "breath",
    "lung": "lung",
    "lungs": "lung",
    "oxygen": "oxygen",
    "cell": "cell",
    "cells": "cell",
    "blood": "blood",
    "heart": "heart",
    "pulse": "pulse",
    "pulses": "pulse",
    "muscle": "muscle",
    "muscles": "muscle",
    "waste": "waste",
    "hunger": "hunger",
    "hungry": "hunger",
    "starvation": "hunger",
    "thirst": "thirst",
    "thirsty": "thirst",
    "dehydration": "thirst",
    "drink": "water",
    "drinking": "water",
    "shiver": "shiver",
    "shivering": "shiver",
    "shivers": "shiver",
    "sweat": "sweat",
    "sweating": "sweat",
    "perspiration": "sweat",
    "skin": "skin",
    "chill": "chill",
    "warm": "warm",
    "cool": "cool",
    "hypothermia": "cold",
    "fever": "fever",
    "fevers": "fever",
    "nerve": "nerve",
    "nerves": "nerve",
    "nervous": "nerve",
    "neuron": "nerve",
    "neurons": "nerve",
    "stimulus": "stimulus",
    "stimuli": "stimulus",
    "reflex": "reflex",
    "reflexes": "reflex",
    "movement": "movement",
    "move": "move",
    "immune": "immune",
    "immunity": "immune",
    "pathogen": "virus",
    "pathogens": "virus",
    "virus": "virus",
    "viruses": "virus",
    "viral": "virus",
    "bacteria": "bacteria",
    "bacterium": "bacteria",
    "bacterial": "bacteria",
    "infection": "infection",
    "infected": "infection",
    "infectious": "infection",
    "antibody": "antibody",
    "antibodies": "antibody",
    "heal": "heal",
    "healing": "heal",
    "heals": "heal",
    "wound": "wound",
    "wounds": "wound",
    "pain": "pain",
    "grief": "pain",
    "hurt": "pain",
    "hurts": "pain",
    "exhaustion": "exhaustion",
    "fatigue": "exhaustion",
    "tired": "exhaustion",
    "risk": "risk",
    "risks": "risk",
    "danger": "harm",
    "protect": "protect",
    "protects": "protect",
    "protection": "protect",
    "shield": "protect",
    "guardian": "protect",
    "harm": "harm",
    "damage": "damage",
    # HVAC, Mechanical Refrigeration & Multi-Domain Systems
    "hvac": "cool",
    "ac": "cool",
    "compressor": "engine",
    "fan": "fan",
    "server": "power",
    "servers": "power",
    "ambient": "thermal",
    "sensory": "stimulus",
    "flare": "pain",
    "flares": "pain",
    "shift": "work",
    "eds": "body",
    "heat": "heat",
}


class PhysicalDialogueAdapter:
    def __init__(self, run_dir: Path | None = None, ontology_db: Path = DB_PATH):
        self.run_dir = run_dir or Path(latest_run())
        self.g_path = self.run_dir / "neuron_graph.sqlite3"
        self.ontology_db = ontology_db

        if not self.g_path.exists():
            raise FileNotFoundError(f"Neuron graph store not found at {self.g_path}")
        self.graph = SQLiteNeuronGraphStore(self.g_path, readonly=True)
        self.engine = ConceptualResonanceEngine(self.graph)
        self.manifest = self.graph.manifest()
        self.word_idx = self.manifest.get("word_index", {})

    def close(self):
        self.graph.close()

    def extract_physical_anchors(self, prompt: str) -> list[str]:
        """Extract physical and ontology tokens present in prompt, manifest, or lexicon ontology."""
        words = re.findall(r"[a-z]+", prompt.lower())
        detected = []
        # Query ontology DB to check if a word is an invariant concrete/physical entity
        ontology_entities = set()
        if self.ontology_db.exists():
            try:
                with sqlite3.connect(f"file:{self.ontology_db.resolve()}?mode=ro", uri=True) as con:
                    placeholders = ",".join("?" for _ in words)
                    if placeholders:
                        rows = con.execute(
                            f"SELECT lemma FROM lexical_entities WHERE lemma IN ({placeholders}) AND is_concrete = 1",
                            tuple(words),
                        ).fetchall()
                        ontology_entities = {r[0].lower() for r in rows}
            except Exception:
                pass

        for w in words:
            canon = PHYSICAL_SYNONYMS.get(w, w)
            if canon in detected:
                continue
            # Allow token if it is mapped in PHYSICAL_SYNONYMS, exists in neural graph word_idx,
            # or is a verified concrete entity in the ontology
            if (
                canon in PHYSICAL_SYNONYMS.values()
                or (canon in self.word_idx and len(canon) >= 3)
                or canon in ontology_entities
            ):
                detected.append(canon)
        return detected

    def reason_physical_query(self, prompt: str) -> dict | None:
        """Evaluate a physical question through wave interference and return a grounded deduction."""
        anchors = self.extract_physical_anchors(prompt)
        if len(anchors) < 2:
            return None

        # Resolve top resonant attractors via wave interference
        attractors = self.engine.resolve_multi_anchor_query(anchors, top_k=6)
        if not attractors and self.ontology_db.exists():
            # Fall back to grounded semantic relations in ontology when the neural graph
            # has not yet inscribed direct 2-hop links between these anchors
            try:
                with sqlite3.connect(f"file:{self.ontology_db.resolve()}?mode=ro", uri=True) as con:
                    if len(anchors) == 2:
                        w1, w2 = anchors[0], anchors[1]
                        rows = con.execute(
                            """
                            SELECT m.lemma, count(*) as weight
                            FROM semantic_relations r1
                            JOIN semantic_relations r2 ON (
                                (r1.target_entity_id = r2.source_entity_id AND r2.target_entity_id = (SELECT entity_id FROM lexical_entities WHERE lemma=?))
                                OR (r1.target_entity_id = r2.target_entity_id AND r2.source_entity_id = (SELECT entity_id FROM lexical_entities WHERE lemma=?))
                                OR (r1.source_entity_id = r2.source_entity_id AND r2.target_entity_id = (SELECT entity_id FROM lexical_entities WHERE lemma=?))
                                OR (r1.source_entity_id = r2.target_entity_id AND r2.source_entity_id = (SELECT entity_id FROM lexical_entities WHERE lemma=?))
                            )
                            JOIN lexical_entities m ON (m.entity_id = r1.target_entity_id OR m.entity_id = r1.source_entity_id)
                            WHERE (r1.source_entity_id = (SELECT entity_id FROM lexical_entities WHERE lemma=?)
                                   OR r1.target_entity_id = (SELECT entity_id FROM lexical_entities WHERE lemma=?))
                              AND m.lemma NOT IN (?, ?)
                            GROUP BY m.lemma
                            ORDER BY weight DESC, m.lemma
                            LIMIT 6
                            """,
                            (w2, w2, w2, w2, w1, w1, w1, w2),
                        ).fetchall()
                        if rows:
                            attractors = [(str(r[0]), float(r[1]) * 100_000.0) for r in rows]
            except sqlite3.Error:
                pass
        if not attractors:
            return None

        top_tokens = [w for w, score in attractors]

        # Look up matching causal implication chains from lexicon_ontology.db
        matched_chain = None
        if self.ontology_db.exists():
            prompt_words = set(re.findall(r"[a-z]+", prompt.lower()))
            conn = sqlite3.connect(self.ontology_db)
            cur = conn.cursor()
            cur.execute("SELECT title, domain, description, step_sequence FROM causal_implication_chains")
            best_chain = None
            best_score = -1
            for title, domain, desc, steps_json in cur.fetchall():
                steps = json.loads(steps_json)
                chain_nodes = {s[0] for s in steps} | {s[2] for s in steps}
                anchor_overlap = len(set(anchors) & chain_nodes)
                token_overlap = len(set(top_tokens[:4]) & chain_nodes)
                chain_text_words = set(re.findall(r"[a-z]+", f"{title} {domain} {desc}".lower()))
                text_overlap = len(prompt_words & chain_text_words)
                score = anchor_overlap * 4 + token_overlap * 2 + text_overlap
                if score > best_score and score >= 2:
                    best_score = score
                    best_chain = {
                        "title": title,
                        "domain": domain,
                        "description": desc,
                        "steps": steps,
                    }
            matched_chain = best_chain
            conn.close()

        return {
            "prompt": prompt,
            "anchors": anchors,
            "attractors": attractors,
            "matched_chain": matched_chain,
            "top_tokens": top_tokens,
        }

    def format_physical_response(self, result: dict) -> str:
        """Serialize only graph and SQL evidence already returned by the query."""
        if not result or not result.get("attractors"):
            return "NULL_UNLEARNED_ENTITY"
        evidence = {
            "anchors": result["anchors"],
            "attractors": result["attractors"],
            "matched_chain": result.get("matched_chain"),
        }
        return json.dumps(evidence, ensure_ascii=False)


def main():
    adapter = PhysicalDialogueAdapter()

    test_prompts = [
        "Viv, my computer just shut off suddenly. What are the likely physical causes based on your lattice?",
        "Viv, if the pipe in the basement freezes tonight, what will happen?",
        "Why did the dry metal parts in the engine stop moving?",
        "There is a flood on the basement floor near the pipe, what happened?",
    ]

    print("=" * 72)
    print("DEMONSTRATING VIV'S NATURAL LANGUAGE PHYSICAL REASONING INTERFACE")
    print("=" * 72)

    for p in test_prompts:
        print(f"\nArchitect > {p}")
        res = adapter.reason_physical_query(p)
        if res:
            answer = adapter.format_physical_response(res)
            print(f"Viv > {answer}")
            print(f"      [-] Topological Attractors: {', '.join(f'{w}({int(s):,})' for w, s in res['attractors'][:4])}")
        else:
            print("Viv > I could not detect 2 physical poles in that query.")

    adapter.close()


if __name__ == "__main__":
    main()
