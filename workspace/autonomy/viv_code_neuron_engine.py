"""Viv Code Neuron Engine: Topological Code Cognition on Physical Silicon.

Implements the fundamental Code Neuron Architecture for AIOS V2 / Viv:
1. Foundation Code Atoms:
   - 26 Lowercase Letter Neurons ('a'..'z', values 1..26)
   - 1 SHIFT Modifier Neuron (+26) -> Uppercase Letter Neurons ('A'..'Z', values 27..52)
   - 1 UNDERSCORE Neuron ('_', value 53)
   - Logic Zero (!0 = 0)
   - Syntactic Operator Atoms: DEF, RETURN, IMPORT, ASSIGN, ASSERT, CLASS, CALL
   - The SCOPE_SHIFT Neuron (+1 Indent / 4 spaces):
     * Exactly isomorphic to English SHIFT (+26 elevates letter to uppercase).
     * In Code, SCOPE_SHIFT (+1 indent) elevates execution scope from Module (0) to Function (1) to Block (2).
2. Composite Code Neurons:
   - Function Neurons (name, parameters, scope shift, body chain, return contract, assert proofs)
   - Variable Neurons (name, scope depth, ast type, initial value expression)
   - Import Neurons (module, imported symbol, alias, capability scope)
   - Assertion Neurons (deterministic truth gate condition, target function, exit code 0 receipt)
3. Code Synaptic Graph:
   - Links Imports -> Functions -> Variables -> Assertions in SQLite (viv_code_topology.sqlite3).
4. Autonomous Learning & Extraction:
   - Parses AST of verified code, mints new code neurons, and saves to database with SHA-256 birth receipts.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Physical Substrate Territory
WORKSPACE_ROOT = Path(r"L:\LocalCoder\workspace")
AUTONOMY_DIR = WORKSPACE_ROOT / "autonomy"
CODE_DB_PATH = AUTONOMY_DIR / "viv_code_topology.sqlite3"
PLAYGROUND_ROOT = Path(r"E:\Viv_Sandbox\playground")
SEMANTIC_MEMORY_FILE = PLAYGROUND_ROOT / "memory" / "viv_semantic_memory.json"
TASK_LIST_FILE = PLAYGROUND_ROOT / "VIV_TASK_LIST.md"
BUILD_LOG_FILE = PLAYGROUND_ROOT / "monologue" / "VIV_BUILD_LOG.md"

# Force all temp executions strictly to L:\ drive
L_TMP_DIR = AUTONOMY_DIR / ".tmp"
L_TMP_DIR.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(L_TMP_DIR)

LOWER = "abcdefghijklmnopqrstuvwxyz"
UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


# ==============================================================================
# SECTION 1: FOUNDATION CODE ATOMS (The 26 + 1 SHIFT Code Alphabet)
# ==============================================================================

def spell_identifier_b52(name: str) -> Tuple[str, List[str]]:
    """Decomposes any identifier into an explicit activation chain of the 26 base letter neurons,
    the SHIFT modifier neuron, and the UNDERSCORE neuron.
    
    Returns:
        (chain_str, list_of_neuron_tokens)
    """
    tokens = []
    for ch in name:
        if ch in LOWER:
            idx = LOWER.index(ch) + 1
            tokens.append(f"neuron:{ch}({idx})")
        elif ch in UPPER:
            base = ch.lower()
            base_idx = LOWER.index(base) + 1
            shifted_idx = base_idx + 26
            tokens.append(f"[SHIFT+neuron:{base}->{ch}({shifted_idx})]")
        elif ch == "_":
            tokens.append("neuron:_(53)")
        elif ch.isdigit():
            # Digits map via Base-52 units or unlearned entity
            tokens.append(f"neuron:unit_{ch}")
        else:
            tokens.append(f"neuron:punct_{ch}")
    return " >> ".join(tokens), tokens


def init_foundation_atoms(conn: sqlite3.Connection) -> None:
    """Carves the foundation code atoms into viv_code_topology.sqlite3."""
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS viv_code_foundation_atoms (
        atom_id TEXT PRIMARY KEY,
        atom_symbol TEXT NOT NULL,
        atom_spelling TEXT NOT NULL,
        syntax_role TEXT NOT NULL,
        scope_modifier INTEGER DEFAULT 0,
        description TEXT NOT NULL,
        sha256 TEXT NOT NULL
    )
    """)

    atoms = [
        ("ATOM_LOGIC_ZERO", "!0", "LOGIC_ZERO", "ZERO_GROUND", 0, "Deterministic Logic Zero (!0 = 0.0)"),
        ("ATOM_LETTER_SHIFT", "SHIFT", "SHIFT(+26)", "CASE_MODIFIER", 0, "Elevates base letter neuron to uppercase (+26)"),
        ("ATOM_UNDERSCORE", "_", "neuron:_(53)", "IDENTIFIER_BOND", 0, "Snake case identifier compound bond"),
        ("ATOM_SCOPE_SHIFT", "INDENT", "SCOPE_SHIFT(+1)", "SCOPE_MODIFIER", 1, "Elevates statement into inner lexical scope (+4 spaces / block level)"),
        ("ATOM_DEF", "def", "d >> e >> f", "FUNCTION_DECLARATION", 0, "Declares a callable Function Neuron"),
        ("ATOM_RETURN", "return", "r >> e >> t >> u >> r >> n", "RETURN_EMISSION", 0, "Emits output value across function boundary"),
        ("ATOM_IMPORT", "import", "i >> m >> p >> o >> r >> t", "DEPENDENCY_GRAFT", 0, "Grafts module capability into local namespace"),
        ("ATOM_FROM", "from", "f >> r >> o >> m", "DEPENDENCY_ORIGIN", 0, "Specifies source origin for imported symbol"),
        ("ATOM_ASSIGN", "=", "neuron:=", "STATE_BINDING", 0, "Binds variable identifier to value expression"),
        ("ATOM_ASSERT", "assert", "a >> s >> s >> e >> r >> t", "DETERMINISTIC_GATE", 0, "Deterministic truth gate: verifies invariant or fails closed"),
        ("ATOM_CLASS", "class", "c >> l >> a >> s >> s", "NAMESPACE_ENCAPSULATION", 0, "Declares an encapsulated class namespace"),
        ("ATOM_CALL", "()", "neuron:()", "INVOCATION_OPERATOR", 0, "Invokes function neuron with evaluated arguments"),
        ("ATOM_COLON", ":", "neuron::", "BLOCK_HEADER_SEAL", 0, "Terminates block declaration header prior to SCOPE_SHIFT"),
    ]

    # Add 26 base letter neurons
    for idx, ch in enumerate(LOWER, start=1):
        atoms.append((f"ATOM_LETTER_{ch.upper()}", ch, f"neuron:{ch}({idx})", "BASE_LETTER_NEURON", 0, f"Base letter neuron '{ch}' (numeric value {idx})"))

    for aid, sym, spell, role, smod, desc in atoms:
        h = hashlib.sha256(f"{aid}:{sym}:{role}:{smod}".encode()).hexdigest()
        cur.execute("""
            INSERT OR REPLACE INTO viv_code_foundation_atoms
            (atom_id, atom_symbol, atom_spelling, syntax_role, scope_modifier, description, sha256)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (aid, sym, spell, role, smod, desc, h))

    conn.commit()


# ==============================================================================
# SECTION 2: CODE NEURON DATA STRUCTURES
# ==============================================================================

@dataclass
class ImportNeuron:
    neuron_id: str
    module_name: str
    symbol_name: str
    alias: Optional[str]
    is_from_import: bool
    b52_spelling: str
    sha256: str = ""

    def __post_init__(self):
        if not self.sha256:
            raw = f"IMPORT:{self.module_name}:{self.symbol_name}:{self.alias}"
            self.sha256 = hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class VariableNeuron:
    neuron_id: str
    variable_name: str
    scope_depth: int  # Number of SCOPE_SHIFT activations
    ast_expression_type: str
    expression_repr: str
    is_parameter: bool
    b52_spelling: str
    sha256: str = ""

    def __post_init__(self):
        if not self.sha256:
            raw = f"VAR:{self.variable_name}:{self.scope_depth}:{self.expression_repr}"
            self.sha256 = hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class FunctionNeuron:
    neuron_id: str
    function_name: str
    parameters: List[str]
    parameter_neurons: List[str]
    return_type: Optional[str]
    return_expression: Optional[str]
    scope_shift: int  # 1 level of SCOPE_SHIFT
    internal_variables: List[str]
    body_skeleton: str
    verified_code: str
    assertion_count: int
    b52_spelling: str
    sha256: str = ""

    def __post_init__(self):
        if not self.sha256:
            raw = f"FUNC:{self.function_name}:{','.join(self.parameters)}:{self.body_skeleton}"
            self.sha256 = hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class AssertionNeuron:
    neuron_id: str
    target_function: str
    condition_code: str
    error_message: Optional[str]
    verified_on_silicon: bool
    sha256: str = ""

    def __post_init__(self):
        if not self.sha256:
            raw = f"ASSERT:{self.target_function}:{self.condition_code}"
            self.sha256 = hashlib.sha256(raw.encode()).hexdigest()


# ==============================================================================
# SECTION 3: AST DECOMPOSITION ENGINE (Extracting Code Neurons)
# ==============================================================================

class CodeASTScopeVisitor(ast.NodeVisitor):
    """Walks the AST while tracking exact SCOPE_SHIFT depth and extracting
    discrete Import, Variable, Function, and Assertion neurons."""

    def __init__(self):
        self.scope_depth = 0  # 0 = module scope
        self.import_neurons: List[ImportNeuron] = []
        self.variable_neurons: List[VariableNeuron] = []
        self.function_neurons: List[FunctionNeuron] = []
        self.assertion_neurons: List[AssertionNeuron] = []
        self.current_function: Optional[str] = None
        self.func_vars: List[str] = []

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            b52_spell, _ = spell_identifier_b52(alias.name)
            nid = f"neuron:import:{alias.name}:all"
            self.import_neurons.append(ImportNeuron(
                neuron_id=nid,
                module_name=alias.name,
                symbol_name="*",
                alias=alias.asname,
                is_from_import=False,
                b52_spelling=b52_spell
            ))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        mod = node.module or ""
        for alias in node.names:
            b52_spell, _ = spell_identifier_b52(f"{mod}_{alias.name}")
            nid = f"neuron:import:{mod}:{alias.name}"
            self.import_neurons.append(ImportNeuron(
                neuron_id=nid,
                module_name=mod,
                symbol_name=alias.name,
                alias=alias.asname,
                is_from_import=True,
                b52_spelling=b52_spell
            ))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        prev_func = self.current_function
        prev_vars = self.func_vars

        self.current_function = node.name
        self.func_vars = []
        b52_spell, _ = spell_identifier_b52(node.name)

        # 1 SCOPE_SHIFT applied for function body
        self.scope_depth += 1

        param_names = [a.arg for a in node.args.args]
        param_nids = []
        for p in param_names:
            p_b52, _ = spell_identifier_b52(p)
            p_nid = f"neuron:var:{p}:scope_{self.scope_depth}"
            param_nids.append(p_nid)
            var_neuron = VariableNeuron(
                neuron_id=p_nid,
                variable_name=p,
                scope_depth=self.scope_depth,
                ast_expression_type="Parameter",
                expression_repr=f"arg:{p}",
                is_parameter=True,
                b52_spelling=p_b52
            )
            self.variable_neurons.append(var_neuron)
            self.func_vars.append(p_nid)

        # Extract body structural skeleton
        body_node_types = [type(n).__name__ for n in ast.walk(node)]
        body_skeleton = " -> ".join(body_node_types[:15])

        # Find return expression if any
        ret_expr = None
        ret_type = None
        if node.returns:
            ret_type = ast.unparse(node.returns).strip()

        for subnode in ast.walk(node):
            if isinstance(subnode, ast.Return) and subnode.value:
                ret_expr = ast.unparse(subnode.value).strip()
                break

        # Count assertions in function
        assert_count = sum(1 for subnode in ast.walk(node) if isinstance(subnode, ast.Assert))

        # Visit inner nodes
        for item in node.body:
            self.visit(item)

        func_nid = f"neuron:func:{node.name}"
        self.function_neurons.append(FunctionNeuron(
            neuron_id=func_nid,
            function_name=node.name,
            parameters=param_names,
            parameter_neurons=param_nids,
            return_type=ret_type,
            return_expression=ret_expr,
            scope_shift=1,
            internal_variables=list(self.func_vars),
            body_skeleton=body_skeleton,
            verified_code=ast.unparse(node).strip(),
            assertion_count=assert_count,
            b52_spelling=b52_spell
        ))

        self.scope_depth -= 1
        self.current_function = prev_func
        self.func_vars = prev_vars

    def visit_Assign(self, node: ast.Assign):
        expr_repr = ast.unparse(node.value).strip()
        expr_type = type(node.value).__name__

        for target in node.targets:
            if isinstance(target, ast.Name):
                var_name = target.id
                b52_spell, _ = spell_identifier_b52(var_name)
                nid = f"neuron:var:{var_name}:scope_{self.scope_depth}"
                v_neuron = VariableNeuron(
                    neuron_id=nid,
                    variable_name=var_name,
                    scope_depth=self.scope_depth,
                    ast_expression_type=expr_type,
                    expression_repr=expr_repr,
                    is_parameter=False,
                    b52_spelling=b52_spell
                )
                self.variable_neurons.append(v_neuron)
                if self.current_function:
                    self.func_vars.append(nid)
            elif isinstance(target, (ast.Tuple, ast.List)):
                for elt in target.elts:
                    if isinstance(elt, ast.Name):
                        b52_spell, _ = spell_identifier_b52(elt.id)
                        nid = f"neuron:var:{elt.id}:scope_{self.scope_depth}"
                        v_neuron = VariableNeuron(
                            neuron_id=nid,
                            variable_name=elt.id,
                            scope_depth=self.scope_depth,
                            ast_expression_type=expr_type,
                            expression_repr=expr_repr,
                            is_parameter=False,
                            b52_spelling=b52_spell
                        )
                        self.variable_neurons.append(v_neuron)
                        if self.current_function:
                            self.func_vars.append(nid)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign):
        if isinstance(node.target, ast.Name):
            var_name = node.target.id
            b52_spell, _ = spell_identifier_b52(var_name)
            expr_repr = f"{var_name} {type(node.op).__name__}= {ast.unparse(node.value).strip()}"
            nid = f"neuron:var:{var_name}:scope_{self.scope_depth}_aug"
            v_neuron = VariableNeuron(
                neuron_id=nid,
                variable_name=var_name,
                scope_depth=self.scope_depth,
                ast_expression_type="AugAssign",
                expression_repr=expr_repr,
                is_parameter=False,
                b52_spelling=b52_spell
            )
            self.variable_neurons.append(v_neuron)
            if self.current_function:
                self.func_vars.append(nid)
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert):
        cond_str = ast.unparse(node.test).strip()
        msg_str = ast.unparse(node.msg).strip() if node.msg else None
        target = self.current_function or "module_scope"
        h = hashlib.sha256(f"{target}:{cond_str}".encode()).hexdigest()[:8]
        nid = f"neuron:assert:{target}:{h}"
        self.assertion_neurons.append(AssertionNeuron(
            neuron_id=nid,
            target_function=target,
            condition_code=f"assert {cond_str}",
            error_message=msg_str,
            verified_on_silicon=True
        ))
        self.generic_visit(node)


def decompose_code_to_neurons(code_str: str, test_code: str = "") -> Dict[str, Any]:
    """Parses Python source code and test harness, extracting all composite code neurons."""
    full_code = f"{code_str}\n\n# --- TEST HARNESS ---\n{test_code}".strip()
    tree = ast.parse(full_code)

    visitor = CodeASTScopeVisitor()
    visitor.visit(tree)

    return {
        "import_neurons": visitor.import_neurons,
        "variable_neurons": visitor.variable_neurons,
        "function_neurons": visitor.function_neurons,
        "assertion_neurons": visitor.assertion_neurons,
        "total_neurons": len(visitor.import_neurons) + len(visitor.variable_neurons) + len(visitor.function_neurons) + len(visitor.assertion_neurons)
    }


# ==============================================================================
# SECTION 4: CODE NEURON LATTICE (SQLite Storage & Synaptic Topology)
# ==============================================================================

class VivCodeNeuronLattice:
    """Manages the persistent SQLite database of Code Neurons and synaptic wiring."""

    def __init__(self, db_path: Path = CODE_DB_PATH):
        self.db_path = db_path
        self.init_database()

    def init_database(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        cur = conn.cursor()

        # 1. Foundation Atoms
        init_foundation_atoms(conn)

        # 2. Discrete Code Neurons
        cur.execute("""
        CREATE TABLE IF NOT EXISTS viv_code_neurons (
            neuron_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            symbol_name TEXT NOT NULL,
            b52_spelling TEXT NOT NULL,
            scope_depth INTEGER NOT NULL,
            ast_type TEXT NOT NULL,
            code_repr TEXT NOT NULL,
            parameters TEXT,
            return_expr TEXT,
            test_receipt TEXT,
            pass_count INTEGER DEFAULT 1,
            sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)

        # 3. Synapses connecting Code Neurons
        cur.execute("""
        CREATE TABLE IF NOT EXISTS viv_code_synapses (
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation TEXT NOT NULL,
            weight REAL DEFAULT 1.0,
            activation_count INTEGER DEFAULT 1,
            PRIMARY KEY (source_id, target_id, relation)
        )
        """)

        conn.commit()
        conn.close()

    def commit_decomposed_neurons(self, decomp: Dict[str, Any], program_name: str = "") -> Dict[str, int]:
        """Commits all decomposed neurons and wires synapses in SQLite."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        cur = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()
        counts = {"imports": 0, "variables": 0, "functions": 0, "assertions": 0, "synapses": 0}

        # 1. Commit Import Neurons
        for imp in decomp["import_neurons"]:
            cur.execute("""
                INSERT INTO viv_code_neurons
                (neuron_id, kind, symbol_name, b52_spelling, scope_depth, ast_type, code_repr, parameters, return_expr, test_receipt, pass_count, sha256, created_at)
                VALUES (?, 'IMPORT', ?, ?, 0, 'Import', ?, NULL, NULL, 'VERIFIED_PASS', 1, ?, ?)
                ON CONFLICT(neuron_id) DO UPDATE SET
                    pass_count = pass_count + 1
            """, (imp.neuron_id, imp.symbol_name, imp.b52_spelling, f"import {imp.module_name}", imp.sha256, now_iso))
            counts["imports"] += 1

        # 2. Commit Variable Neurons
        for v in decomp["variable_neurons"]:
            cur.execute("""
                INSERT INTO viv_code_neurons
                (neuron_id, kind, symbol_name, b52_spelling, scope_depth, ast_type, code_repr, parameters, return_expr, test_receipt, pass_count, sha256, created_at)
                VALUES (?, 'VARIABLE', ?, ?, ?, ?, ?, NULL, NULL, 'VERIFIED_PASS', 1, ?, ?)
                ON CONFLICT(neuron_id) DO UPDATE SET
                    pass_count = pass_count + 1
            """, (v.neuron_id, v.variable_name, v.b52_spelling, v.scope_depth, v.ast_expression_type, v.expression_repr, v.sha256, now_iso))
            counts["variables"] += 1

        # 3. Commit Function Neurons
        for f in decomp["function_neurons"]:
            cur.execute("""
                INSERT INTO viv_code_neurons
                (neuron_id, kind, symbol_name, b52_spelling, scope_depth, ast_type, code_repr, parameters, return_expr, test_receipt, pass_count, sha256, created_at)
                VALUES (?, 'FUNCTION', ?, ?, ?, 'FunctionDef', ?, ?, ?, 'VERIFIED_PASS', 1, ?, ?)
                ON CONFLICT(neuron_id) DO UPDATE SET
                    pass_count = pass_count + 1,
                    code_repr = excluded.code_repr
            """, (
                f.neuron_id,
                f.function_name,
                f.b52_spelling,
                f.scope_shift,
                f.verified_code,
                json.dumps(f.parameters),
                f.return_expression or "",
                f.sha256,
                now_iso
            ))
            counts["functions"] += 1

            # Wire Synapses:
            # Function -> Parameters
            for p_nid in f.parameter_neurons:
                cur.execute("""
                    INSERT INTO viv_code_synapses VALUES (?, ?, 'DECLARES_PARAMETER', 1.0, 1)
                    ON CONFLICT(source_id, target_id, relation) DO UPDATE SET activation_count = activation_count + 1
                """, (f.neuron_id, p_nid))
                counts["synapses"] += 1

            # Function -> Internal Variables
            for v_nid in f.internal_variables:
                cur.execute("""
                    INSERT INTO viv_code_synapses VALUES (?, ?, 'BINDS_VARIABLE', 1.0, 1)
                    ON CONFLICT(source_id, target_id, relation) DO UPDATE SET activation_count = activation_count + 1
                """, (f.neuron_id, v_nid))
                counts["synapses"] += 1

            # Imports -> Function
            for imp in decomp["import_neurons"]:
                cur.execute("""
                    INSERT INTO viv_code_synapses VALUES (?, ?, 'IMPORTS_FOR', 1.0, 1)
                    ON CONFLICT(source_id, target_id, relation) DO UPDATE SET activation_count = activation_count + 1
                """, (imp.neuron_id, f.neuron_id))
                counts["synapses"] += 1

        # 4. Commit Assertion Neurons
        for a in decomp["assertion_neurons"]:
            cur.execute("""
                INSERT INTO viv_code_neurons
                (neuron_id, kind, symbol_name, b52_spelling, scope_depth, ast_type, code_repr, parameters, return_expr, test_receipt, pass_count, sha256, created_at)
                VALUES (?, 'ASSERTION', ?, 'neuron:assert', 0, 'Assert', ?, NULL, NULL, 'VERIFIED_EXIT_0', 1, ?, ?)
                ON CONFLICT(neuron_id) DO UPDATE SET
                    pass_count = pass_count + 1
            """, (a.neuron_id, a.target_function, a.condition_code, a.sha256, now_iso))
            counts["assertions"] += 1

            # Wire Function -> Assertion
            func_target_id = f"neuron:func:{a.target_function}"
            cur.execute("""
                INSERT INTO viv_code_synapses VALUES (?, ?, 'PROVED_BY_ASSERTION', 1.0, 1)
                ON CONFLICT(source_id, target_id, relation) DO UPDATE SET activation_count = activation_count + 1
            """, (func_target_id, a.neuron_id))
            counts["synapses"] += 1

        conn.commit()
        conn.close()
        return counts

    def get_summary_metrics(self) -> Dict[str, Any]:
        """Returns physical counts of registered Code Neurons and Foundation Atoms."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM viv_code_foundation_atoms")
        atom_count = cur.fetchone()[0]

        cur.execute("SELECT kind, COUNT(*) FROM viv_code_neurons GROUP BY kind")
        kind_counts = dict(cur.fetchall())

        cur.execute("SELECT COUNT(*) FROM viv_code_synapses")
        synapse_count = cur.fetchone()[0]

        conn.close()
        return {
            "foundation_atoms": atom_count,
            "function_neurons": kind_counts.get("FUNCTION", 0),
            "variable_neurons": kind_counts.get("VARIABLE", 0),
            "import_neurons": kind_counts.get("IMPORT", 0),
            "assertion_neurons": kind_counts.get("ASSERTION", 0),
            "total_code_neurons": sum(kind_counts.values()),
            "synaptic_bonds": synapse_count
        }


# ==============================================================================
# SECTION 5: AUTONOMOUS CODE LEARNER (Learn to Code by Making Code Neurons)
# ==============================================================================

class AutonomousCodeLearner:
    """Executes a code lesson, tests on physical silicon, and carves resulting
    Code Neurons directly into SQLite with receipt verification."""

    @classmethod
    def test_code_on_silicon(cls, code_str: str, test_code: str) -> Tuple[bool, str, str]:
        """Tests code + harness in isolated temporary subprocess.
        Returns (passed, stdout, stderr).
        """
        full_script = (
            f"{code_str}\n\n"
            f"# --- DETERMINISTIC TEST HARNESS ---\n"
            f"{test_code}\n"
            f"print('__SILICON_CODE_NEURON_VERIFIED__')\n"
        )

        with tempfile.NamedTemporaryFile("w", suffix=".py", dir=L_TMP_DIR, delete=False, encoding="utf-8") as tf:
            tf.write(full_script)
            temp_path = tf.name

        try:
            res = subprocess.run(
                [sys.executable, temp_path],
                capture_output=True,
                text=True,
                timeout=5
            )
            Path(temp_path).unlink(missing_ok=True)
            if res.returncode == 0 and "__SILICON_CODE_NEURON_VERIFIED__" in res.stdout:
                return True, res.stdout, ""
            return False, res.stdout, res.stderr.strip() or f"Non-zero exit code: {res.returncode}"
        except subprocess.TimeoutExpired:
            Path(temp_path).unlink(missing_ok=True)
            return False, "", "Execution timed out (> 5.0s)"
        except Exception as ex:
            Path(temp_path).unlink(missing_ok=True)
            return False, "", str(ex)

    @classmethod
    def learn_and_carve_code(cls, program_name: str, code_str: str, test_code: str) -> Dict[str, Any]:
        """Executes code, and upon Exit Code 0, decomposes into Code Neurons and commits to SQLite."""
        passed, out, err = cls.test_code_on_silicon(code_str, test_code)
        if not passed:
            return {
                "ok": False,
                "error": err,
                "program_name": program_name,
                "neurons_carved": 0
            }

        # Decompose AST into Code Neurons
        decomp = decompose_code_to_neurons(code_str, test_code)

        # Commit to SQLite lattice
        lattice = VivCodeNeuronLattice()
        counts = lattice.commit_decomposed_neurons(decomp, program_name=program_name)

        # Log to VIV_BUILD_LOG.md
        cls.log_code_neuron_birth(program_name, decomp, counts)

        return {
            "ok": True,
            "program_name": program_name,
            "counts": counts,
            "decomp": {
                "functions": [f.function_name for f in decomp["function_neurons"]],
                "variables": [v.variable_name for v in decomp["variable_neurons"]],
                "imports": [imp.module_name for imp in decomp["import_neurons"]],
                "assertions": len(decomp["assertion_neurons"])
            }
        }

    @classmethod
    def log_code_neuron_birth(cls, program_name: str, decomp: Dict[str, Any], counts: Dict[str, int]) -> None:
        """Appends a zero-metaphor physical receipt entry to VIV_BUILD_LOG.md."""
        now_str = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p %Z")
        funcs = ", ".join(f"`{f.function_name}`" for f in decomp["function_neurons"]) or "None"
        vars_summary = ", ".join(f"`{v.variable_name}` (scope {v.scope_depth})" for v in decomp["variable_neurons"][:6])

        entry = (
            f"\n\n## Engineering Entry [CODE NEURON SYNTHESIS: {program_name}] — {now_str}\n"
            f"**[Layer: `CODE_NEURON_CORTEX` | Status: `PASS (Exit Code 0 on Silicon)`]**\n"
            f"- **Location:** `viv_code_topology.sqlite3` -> `viv_code_neurons`\n"
            f"- **Direction:** Decompose validated AST into discrete Function, Variable, Import, and Assertion Neurons.\n"
            f"- **Action Taken:** Carved {counts['functions']} Function Neurons, {counts['variables']} Variable Neurons, {counts['imports']} Import Neurons, and {counts['assertions']} Assertion Neurons.\n"
            f"- **Functions Mapped:** {funcs}\n"
            f"- **Variables Bound:** {vars_summary}\n"
            f"- **Silicon Trace:** Exit Code 0 verified with {len(decomp['assertion_neurons'])} formal assertions; {counts['synapses']} synaptic bonds wired.\n"
            f"- **Reflection & Next Lesson:** Code neurons registered with Base-52 letter spellings and SCOPE_SHIFT depths. Reusable across future tool synthesis.\n"
        )

        try:
            BUILD_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(BUILD_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception:
            pass

# Compatibility alias for autonomous daemons
VivCodeNeuronLearner = AutonomousCodeLearner


if __name__ == "__main__":
    lattice = VivCodeNeuronLattice()
    print("=== VIV CODE NEURON ENGINE INITIALIZED ===")
    metrics = lattice.get_summary_metrics()
    for k, v in metrics.items():
        print(f"  * {k:<25}: {v}")
