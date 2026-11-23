"""Viv's Native UML Programming Language: Interpreter + Python/Rust/Machine-Code/English Compiler.

UML (Universal Mathematical Language) is Viv's native deterministic thought & programming substrate:
- Numbers are Base-52 letter neurons (`a=1..z=26`, `SHIFT+a=A=27..Z=52`, `!0=0`). Zero digit neurons.
- Variables start with `?` (e.g. `?x`, `?n`).
- Nested non-linear algebraic brackets:
    `[x, y]`   -> Addition (`x + y`)
    `{x, y}`   -> Subtraction (`x - y`)
    `>x, y<`   -> Multiplication (`x * y`)
    `<x, y>`   -> Protected Division (`x // y` or UML manifold `<!0,!0> = 1`)
    `%[x, y]`  -> Modulo (`x % y`)
    `^k[x]`    -> Power (`x ** k`, where `k` is a Base-52 letter neuron)
- Function definitions:
    `@name(?x, ?y) := <UML expression>`

This module provides:
1. `parse_uml_program(src)`  -> Deterministic AST of a UML function or expression.
2. `eval_uml_fn(ast, args)`  -> Native UML interpreter (returns integer + Base-52 letter string).
3. `compile_to_python(ast)`  -> Emits valid Python source code.
4. `compile_to_rust(ast)`    -> Emits valid Rust source code (compiled by `rustc` to machine code).
5. `compile_to_english(ast)` -> Translates nested UML thoughts into spoken English sentences.
6. `verify_tri_modal_in_container(uml_src, test_inputs)`:
   Runs the UML interpreter, the compiled Python, and the compiled Rust machine-code binary
   inside `viv-vm` and proves all three produce the exact same outputs (`UML == Python == Rust ELF`).
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from viv_alu_transducer import b52_neuron_chain, b52_to_int, int_to_b52, int_to_words

DB = Path(__file__).resolve().parent / "viv_code_topology.sqlite3"
CONTAINER = "viv-vm"


@dataclass
class UMLNode:
    kind: str  # 'b52', 'var', 'add', 'sub', 'mul', 'div', 'mod', 'pow'
    b52_token: str = ""
    int_val: int = 0
    var_name: str = ""
    children: list["UMLNode"] = field(default_factory=list)


@dataclass
class UMLFunction:
    name: str
    params: list[str]
    body: UMLNode
    raw_src: str


class UMLProgramParser:
    """Recursive-descent parser for nested Base-52 UML expressions."""

    def __init__(self, text: str):
        self.src = re.sub(r"\s+", "", text)
        self.pos = 0

    def peek(self) -> str:
        return self.src[self.pos] if self.pos < len(self.src) else ""

    def consume(self, expected: str | None = None) -> str:
        ch = self.peek()
        if expected is not None and ch != expected:
            raise SyntaxError(f"Expected {expected!r} at pos {self.pos} in {self.src!r}, got {ch!r}")
        self.pos += 1
        return ch

    def parse_expr(self) -> UMLNode:
        ch = self.peek()
        if not ch:
            raise SyntaxError("Unexpected end of UML expression")
        if ch == "[":
            return self._parse_bracket("[", "]", "add")
        if ch == "{":
            return self._parse_bracket("{", "}", "sub")
        if ch == ">":
            return self._parse_bracket(">", "<", "mul")
        if ch == "<":
            return self._parse_bracket("<", ">", "div")
        if ch == "%" and self.src[self.pos: self.pos + 2] == "%[":
            self.pos += 1
            return self._parse_bracket("[", "]", "mod")
        if ch == "^":
            self.consume("^")
            exp_tok = self._read_token()
            exp_node = self._token_to_node(exp_tok)
            base_node = self._parse_bracket("[", "]", "pow_base")
            return UMLNode(kind="pow", children=[base_node.children[0], exp_node])
        tok = self._read_token()
        return self._token_to_node(tok)

    def _parse_bracket(self, open_ch: str, close_ch: str, kind: str) -> UMLNode:
        self.consume(open_ch)
        children = [self.parse_expr()]
        while self.peek() == ",":
            self.consume(",")
            children.append(self.parse_expr())
        self.consume(close_ch)
        if kind == "pow_base":
            return UMLNode(kind="pow_base", children=children)
        if len(children) < 2:
            raise SyntaxError(f"UML operator {kind} requires at least 2 arguments")
        return UMLNode(kind=kind, children=children)

    def _read_token(self) -> str:
        start = self.pos
        if self.peek() in ("-", "?", "!"):
            self.pos += 1
        while self.peek() and self.peek() not in "[]{}<>(),^%":
            self.pos += 1
        tok = self.src[start: self.pos]
        if not tok:
            raise SyntaxError(f"Empty token at pos {self.pos} in {self.src!r}")
        return tok

    def _token_to_node(self, tok: str) -> UMLNode:
        if tok.startswith("?"):
            vname = tok[1:]
            if not vname.isidentifier():
                raise SyntaxError(f"Invalid UML variable name: {tok!r}")
            return UMLNode(kind="var", var_name=vname)
        val = b52_to_int(tok)
        return UMLNode(kind="b52", b52_token=tok, int_val=val)


def parse_uml_function(src: str) -> UMLFunction:
    """Parse `@fn(?x, ?y) := <expr>` or a bare expression (defaults to `@uml_fn(?x)`)."""
    clean = src.strip()
    m = re.match(r"^@([A-Za-z_][A-Za-z0-9_]*)\(([^)]*)\)\s*:=\s*(.+)$", clean)
    if m:
        name = m.group(1)
        raw_params = [p.strip() for p in m.group(2).split(",") if p.strip()]
        params = []
        for p in raw_params:
            if not p.startswith("?"):
                raise SyntaxError(f"UML parameter {p!r} must start with '?'")
            params.append(p[1:])
        expr_str = m.group(3).strip()
    else:
        name = "uml_fn"
        params = ["x"]
        expr_str = clean
    parser = UMLProgramParser(expr_str)
    body = parser.parse_expr()
    if parser.pos != len(parser.src):
        raise SyntaxError(f"Trailing characters in UML expression: {parser.src[parser.pos:]!r}")
    return UMLFunction(name=name, params=params, body=body, raw_src=clean)


# =====================================================================
# 1. NATIVE UML INTERPRETER
# =====================================================================
def eval_uml_node(node: UMLNode, env: dict[str, int]) -> int:
    if node.kind == "b52":
        return node.int_val
    if node.kind == "var":
        if node.var_name not in env:
            raise NameError(f"Unbound UML variable '?{node.var_name}'")
        return env[node.var_name]
    vals = [eval_uml_node(c, env) for c in node.children]
    if node.kind == "add":
        return sum(vals)
    if node.kind == "sub":
        return vals[0] - sum(vals[1:])
    if node.kind == "mul":
        prod = 1
        for v in vals:
            prod *= v
        return prod
    if node.kind == "div":
        r = vals[0]
        for v in vals[1:]:
            if r == 0 and v == 0:
                r = 1  # UML <!0, !0> = a (1)
            elif v == 0:
                r = 0
            else:
                r = r // v
        return r
    if node.kind == "mod":
        return 0 if vals[1] == 0 else vals[0] % vals[1]
    if node.kind == "pow":
        return int(vals[0] ** max(0, vals[1]))
    raise ValueError(f"Unknown UML node kind: {node.kind}")


def eval_uml_fn(fn: UMLFunction, args: list[int]) -> dict[str, Any]:
    env = dict(zip(fn.params, args))
    res_int = eval_uml_node(fn.body, env)
    return {
        "int": res_int,
        "b52": int_to_b52(res_int),
        "word": int_to_words(res_int),
        "neuron_chain": b52_neuron_chain(res_int),
    }


# =====================================================================
# 2. COMPILER TARGETS: PYTHON, RUST (MACHINE CODE), AND SPOKEN ENGLISH
# =====================================================================
def _node_to_py(node: UMLNode) -> str:
    if node.kind == "b52":
        return f"b52({node.b52_token!r})"
    if node.kind == "var":
        return node.var_name
    parts = [_node_to_py(c) for c in node.children]
    if node.kind == "add":
        return "(" + " + ".join(parts) + ")"
    if node.kind == "sub":
        return "(" + parts[0] + " - " + " - ".join(parts[1:]) + ")"
    if node.kind == "mul":
        return "(" + " * ".join(parts) + ")"
    if node.kind == "div":
        return f"(1 if ({parts[0]} == 0 and {parts[1]} == 0) else (0 if {parts[1]} == 0 else {parts[0]} // {parts[1]}))"
    if node.kind == "mod":
        return f"(0 if {parts[1]} == 0 else {parts[0]} % {parts[1]})"
    if node.kind == "pow":
        return f"({parts[0]} ** {parts[1]})"
    raise ValueError(node.kind)


def compile_to_python(fn: UMLFunction) -> str:
    sig = ", ".join(f"{p}: int" for p in fn.params)
    return f"def {fn.name}({sig}) -> int:\n    return {_node_to_py(fn.body)}\n"


def _node_to_rust(node: UMLNode) -> str:
    if node.kind == "b52":
        return f"{node.int_val}i64"
    if node.kind == "var":
        return node.var_name
    parts = [_node_to_rust(c) for c in node.children]
    if node.kind == "add":
        return "(" + " + ".join(parts) + ")"
    if node.kind == "sub":
        return "(" + parts[0] + " - " + " - ".join(parts[1:]) + ")"
    if node.kind == "mul":
        return "(" + " * ".join(parts) + ")"
    if node.kind == "div":
        return f"(if {parts[0]} == 0 && {parts[1]} == 0 {{ 1 }} else if {parts[1]} == 0 {{ 0 }} else {{ {parts[0]} / {parts[1]} }})"
    if node.kind == "mod":
        return f"(if {parts[1]} == 0 {{ 0 }} else {{ {parts[0]} % {parts[1]} }})"
    if node.kind == "pow":
        return f"{parts[0]}.pow({parts[1]} as u32)"
    raise ValueError(node.kind)


def compile_to_rust(fn: UMLFunction) -> str:
    sig = ", ".join(f"{p}: i64" for p in fn.params)
    return f"pub fn {fn.name}({sig}) -> i64 {{\n    {_node_to_rust(fn.body)}\n}}\n"


def _node_to_english(node: UMLNode) -> str:
    if node.kind == "b52":
        return f"{int_to_words(node.int_val)} (b52:{node.b52_token})"
    if node.kind == "var":
        return f"variable {node.var_name}"
    parts = [_node_to_english(c) for c in node.children]
    if node.kind == "add":
        return "the sum of " + " and ".join(parts)
    if node.kind == "sub":
        return f"the difference of {parts[0]} minus " + " minus ".join(parts[1:])
    if node.kind == "mul":
        return "the product of " + " times ".join(parts)
    if node.kind == "div":
        return f"the quotient of {parts[0]} divided by {parts[1]}"
    if node.kind == "mod":
        return f"the remainder of {parts[0]} modulo {parts[1]}"
    if node.kind == "pow":
        return f"{parts[0]} raised to the power of {parts[1]}"
    return ""


def compile_to_english(fn: UMLFunction) -> str:
    p_str = ", ".join(fn.params)
    return f"In UML, function {fn.name}({p_str}) computes {_node_to_english(fn.body)}."


# =====================================================================
# 3. FOUR-WAY COMPILER & EFFICIENCY BENCHMARK:
#    UML vs PYTHON vs RUST vs RAW x86-64 MACHINE CODE
# =====================================================================
def _node_to_x86_asm(node: UMLNode, param0: str) -> list[str]:
    """Compile a 1-arg UML AST (`?x` in `rdi`, SysV AMD64 ABI) into raw x86-64 assembly instructions."""
    if node.kind == "b52":
        return [f"mov rax, {node.int_val}"]
    if node.kind == "var":
        return ["mov rax, rdi"]
    if node.kind == "pow" and node.children[1].kind == "b52":
        exp = node.children[1].int_val
        ins = _node_to_x86_asm(node.children[0], param0)
        if exp == 0:
            return ["mov rax, 1"]
        if exp == 2:
            return ins + ["imul rax, rax"]
        if exp == 3:
            return ins + ["mov rcx, rax", "imul rax, rcx", "imul rax, rcx"]
    # General binary/n-ary stack evaluation
    ins = _node_to_x86_asm(node.children[0], param0)
    for child in node.children[1:]:
        ins += ["push rax"] + _node_to_x86_asm(child, param0) + ["mov rcx, rax", "pop rax"]
        if node.kind == "add":
            ins.append("add rax, rcx")
        elif node.kind == "sub":
            ins.append("sub rax, rcx")
        elif node.kind == "mul":
            ins.append("imul rax, rcx")
        elif node.kind == "div":
            ins += ["cqo", "idiv rcx"]
        elif node.kind == "mod":
            ins += ["cqo", "idiv rcx", "mov rax, rdx"]
    return ins


def compile_to_x86_64_asm(fn: UMLFunction) -> str:
    """Emit standalone x86-64 assembly (`global_asm!` compatible, SysV AMD64 ABI: arg in rdi, return in rax)."""
    p0 = fn.params[0] if fn.params else "x"
    body_ins = _node_to_x86_asm(fn.body, p0)
    lines = [f".global uml_x86_{fn.name}", f"uml_x86_{fn.name}:"] + [f"    {i}" for i in body_ins] + ["    ret"]
    return "\n".join(lines) + "\n"


def verify_tri_modal_in_container(uml_src: str, test_inputs: list[list[int]], iterations: int = 200_000) -> dict[str, Any]:
    """Compile UML to Python, Rust, and raw x86-64 Machine Code; verify outputs AND benchmark efficiency in viv-vm."""
    import time
    from viv_alu_transducer import ALU_PRELUDE

    fn = parse_uml_function(uml_src)
    # 1. Native UML Interpreter + timing
    t0 = time.perf_counter_ns()
    for _ in range(max(1, iterations // 100)):
        for inp in test_inputs:
            eval_uml_node(fn.body, dict(zip(fn.params, inp)))
    uml_ns_per_call = round((time.perf_counter_ns() - t0) / (max(1, iterations // 100) * len(test_inputs)), 2)

    uml_outputs = [eval_uml_fn(fn, inp)["int"] for inp in test_inputs]
    b52_outputs = [eval_uml_fn(fn, inp)["b52"] for inp in test_inputs]
    py_code = compile_to_python(fn)
    rs_code = compile_to_rust(fn)
    x86_asm = compile_to_x86_64_asm(fn)
    english = compile_to_english(fn)

    # 2. Run & benchmark compiled Python inside viv-vm
    py_calls = ", ".join(f"{fn.name}({', '.join(map(str, inp))})" for inp in test_inputs)
    py_runner = (
        f"{ALU_PRELUDE}\n{py_code}\nimport json, time\n"
        f"outs = [{py_calls}]\n"
        f"N = {max(1, iterations // 20)}\n"
        f"t0 = time.perf_counter_ns()\n"
        f"for _ in range(N):\n"
        f"    _ = [{py_calls}]\n"
        f"ns = round((time.perf_counter_ns() - t0) / (N * {len(test_inputs)}), 2)\n"
        f"print(json.dumps({{'outs': outs, 'ns_per_call': ns}}))\n"
    )
    r_py = subprocess.run(
        ["docker", "exec", "-i", "-w", "/work", CONTAINER, "python", "-"],
        input=py_runner.encode(),
        capture_output=True,
        timeout=30,
    )
    py_data = json.loads(r_py.stdout.decode().strip()) if r_py.returncode == 0 else {"outs": [], "ns_per_call": -1}
    py_outputs = py_data["outs"]
    py_ns_per_call = py_data["ns_per_call"]

    # 3. Compile & benchmark BOTH Rust and Raw x86-64 Machine Code inside viv-vm
    in_vec = ", ".join(f"{inp[0]}i64" for inp in test_inputs)
    asm_escaped = "\\n".join(x86_asm.strip().splitlines())
    rs_bench = f"""
use std::arch::global_asm;
use std::hint::black_box;
use std::time::Instant;

global_asm!("{asm_escaped}");
extern "sysv64" {{
    fn uml_x86_{fn.name}(x: i64) -> i64;
}}

#[inline(never)]
{rs_code}

fn main() {{
    let inputs = [{in_vec}];
    let rs_outs: Vec<i64> = inputs.iter().map(|&x| {fn.name}(x)).collect();
    let mc_outs: Vec<i64> = inputs.iter().map(|&x| unsafe {{ uml_x86_{fn.name}(x) }}).collect();
    let n: u64 = {iterations};

    let t_rs = Instant::now();
    let mut acc_rs = 0i64;
    for _ in 0..n {{
        for &x in &inputs {{
            acc_rs = acc_rs.wrapping_add({fn.name}(black_box(x)));
        }}
    }}
    let rs_ns = t_rs.elapsed().as_nanos() as f64 / ((n as f64) * (inputs.len() as f64));

    let t_mc = Instant::now();
    let mut acc_mc = 0i64;
    for _ in 0..n {{
        for &x in &inputs {{
            acc_mc = acc_mc.wrapping_add(unsafe {{ uml_x86_{fn.name}(black_box(x)) }});
        }}
    }}
    let mc_ns = t_mc.elapsed().as_nanos() as f64 / ((n as f64) * (inputs.len() as f64));
    black_box((acc_rs, acc_mc));

    println!("RS_OUTS:{{:?}}", rs_outs);
    println!("MC_OUTS:{{:?}}", mc_outs);
    println!("RS_NS:{{:.3}}", rs_ns);
    println!("MC_NS:{{:.3}}", mc_ns);
}}
"""
    sh_cmd = (
        "cat > /tmp/uml_prog.rs && "
        "rustc -C opt-level=3 /tmp/uml_prog.rs -o /tmp/uml_bin && "
        "rustc --emit=obj -C opt-level=3 /tmp/uml_prog.rs -o /tmp/uml_prog.o && "
        "/tmp/uml_bin && "
        "stat -c '%s' /tmp/uml_prog.o"
    )
    r_rs = subprocess.run(
        ["docker", "exec", "-i", "-w", "/work", CONTAINER, "sh", "-c", sh_cmd],
        input=rs_bench.encode(),
        capture_output=True,
        timeout=60,
    )
    rs_outputs, mc_outputs = [], []
    rs_ns_per_call, mc_ns_per_call, obj_bytes = -1.0, -1.0, 0
    if r_rs.returncode == 0:
        for ln in r_rs.stdout.decode().strip().splitlines():
            if ln.startswith("RS_OUTS:"):
                rs_outputs = json.loads(ln.split(":", 1)[1])
            elif ln.startswith("MC_OUTS:"):
                mc_outputs = json.loads(ln.split(":", 1)[1])
            elif ln.startswith("RS_NS:"):
                rs_ns_per_call = float(ln.split(":", 1)[1])
            elif ln.startswith("MC_NS:"):
                mc_ns_per_call = float(ln.split(":", 1)[1])
            elif ln.strip().isdigit():
                obj_bytes = int(ln.strip())

    agree = (uml_outputs == py_outputs == rs_outputs == mc_outputs) and len(uml_outputs) == len(test_inputs)

    # Record in viv_code_topology.sqlite3
    with sqlite3.connect(DB, timeout=30) as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS viv_uml_programs ("
            "program_id TEXT PRIMARY KEY, uml_src TEXT NOT NULL, python_code TEXT NOT NULL, "
            "rust_code TEXT NOT NULL, english_speech TEXT NOT NULL, b52_outputs TEXT NOT NULL, "
            "elf_machine_bytes INTEGER NOT NULL, verified INTEGER NOT NULL, created_utc TEXT NOT NULL, sha256 TEXT NOT NULL)"
        )
        now = datetime.now(timezone.utc).isoformat()
        pid = f"UML_{fn.name}_{hashlib.sha256(uml_src.encode()).hexdigest()[:10]}"
        seal = hashlib.sha256(f"{uml_src}:{py_code}:{rs_code}:{x86_asm}:{b52_outputs}".encode()).hexdigest()
        c.execute(
            "INSERT OR REPLACE INTO viv_uml_programs VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, uml_src, py_code, rs_code + "\n// x86_64:\n" + x86_asm, english, json.dumps(b52_outputs), obj_bytes, int(agree), now, seal),
        )
        c.commit()

    return {
        "program_id": pid,
        "uml_src": uml_src,
        "english": english,
        "python": py_code.strip(),
        "rust": rs_code.strip(),
        "x86_64_machine_asm": x86_asm.strip(),
        "uml_outputs": uml_outputs,
        "b52_outputs": b52_outputs,
        "py_outputs": py_outputs,
        "rs_outputs": rs_outputs,
        "x86_machine_outputs": mc_outputs,
        "efficiency_ns_per_call": {
            "uml_interpreter_ns": uml_ns_per_call,
            "python_vm_ns": py_ns_per_call,
            "rust_compiled_ns": rs_ns_per_call,
            "raw_x86_64_machine_code_ns": mc_ns_per_call,
            "speedup_x86_vs_python": round(py_ns_per_call / max(0.001, mc_ns_per_call), 1) if mc_ns_per_call > 0 else 0,
            "speedup_x86_vs_uml_interp": round(uml_ns_per_call / max(0.001, mc_ns_per_call), 1) if mc_ns_per_call > 0 else 0,
        },
        "source_compactness_chars": {
            "uml_chars": len(uml_src),
            "python_chars": len(py_code.strip()),
            "rust_chars": len(rs_code.strip()),
            "x86_asm_chars": len(x86_asm.strip()),
        },
        "elf_machine_bytes": obj_bytes,
        "tri_modal_verified": agree,
    }


def self_author_uml_program(step_k: int) -> dict[str, Any]:
    """Viv writes her own nested Base-52 UML function and compiles it to Python, Rust, x86-64 Machine Code, and English."""
    import urllib.request
    import viv_code_learning_loop as L

    examples = [
        "@step(?x) := [?x, a]",
        "@linear(?x) := [>b, ?x<, c]",
        "@quad(?x) := [>b, ^b[?x]<, >c, ?x<, a]",
        "@diff_sq(?x) := {^b[?x], a}",
    ]
    prior_err = ""
    last_line = ""
    res = None
    for _try in range(3):
        prompt = (
            "Write ONE nested UML function using Base-52 letter neurons (a=1, b=2, c=3, ..., z=26, A=27, !0=0, NO DIGITS).\n"
            "Grammar rules:\n"
            "  Left side MUST be `@name(?x) :=` (only `?x` is the variable).\n"
            "  Right side uses:\n"
            "    [?x, a]   for addition\n"
            "    {?x, a}   for subtraction\n"
            "    >b, ?x<   for multiplication\n"
            "    ^b[?x]    for squaring `?x`\n"
            "Valid examples:\n  " + "\n  ".join(examples) + "\n"
        )
        if prior_err:
            prompt += f"\nYour previous attempt `{last_line}` failed with: {prior_err}\nFix the UML syntax and output ONLY one valid `@name(?x) := ...` line."
        else:
            prompt += "\nReply with ONLY one new line in the form: @compute(?x) := <nested UML expression>"
        payload = {
            "model": L.MODEL,
            "temperature": 0.3,
            "max_tokens": 120,
            "messages": [
                {"role": "system", "content": "You write pure UML (Universal Mathematical Language) in Base-52. Output only one `@name(?x) := ...` line."},
                {"role": "user", "content": prompt},
            ],
        }
        req = urllib.request.Request(L.API_URL, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = json.loads(r.read())["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            return {"task": "self_uml_compile", "ok": False, "code": "", "error": str(exc), "path": "", "diff": "", "sha": "0" * 64}

        last_line = next((ln.strip().strip("`") for ln in raw.splitlines() if "@" in ln and ":=" in ln), raw.splitlines()[0].strip().strip("`") if raw else "")
        try:
            res = verify_tri_modal_in_container(last_line, [[0], [1], [2], [5]])
            break
        except Exception as exc:
            prior_err = str(exc)

    if res is None:
        return {"task": "self_uml_compile", "ok": False, "code": last_line, "error": f"UML compile error: {prior_err}", "path": "", "diff": "", "sha": hashlib.sha256(last_line.encode()).hexdigest()}

    cpath = f"/work/self_uml_compile/a{step_k}.py"
    eff = res["efficiency_ns_per_call"]
    bundle = (
        f"# UML Source : {res['uml_src']}\n"
        f"# English    : {res['english']}\n"
        f"# Base-52 Out: {res['b52_outputs']} -> {res['uml_outputs']}\n"
        f"# Efficiency : UML={eff['uml_interpreter_ns']}ns, Py={eff['python_vm_ns']}ns, Rust={eff['rust_compiled_ns']}ns, x86_64={eff['raw_x86_64_machine_code_ns']}ns ({eff['speedup_x86_vs_python']}x vs Py)\n"
        f"# x86-64 Obj : {res['elf_machine_bytes']} bytes (verified={res['tri_modal_verified']})\n"
        f"{res['python']}\n"
    )
    subprocess.run(
        ["docker", "exec", "-i", "-w", "/work", CONTAINER, "sh", "-c", f"mkdir -p /work/self_uml_compile && cat > {cpath}"],
        input=bundle.encode(),
        capture_output=True,
    )
    return {
        "task": "self_uml_compile",
        "ok": bool(res["tri_modal_verified"]),
        "code": res["python"],
        "error": "" if res["tri_modal_verified"] else "tri-modal mismatch",
        "path": cpath,
        "diff": "",
        "sha": hashlib.sha256(bundle.encode()).hexdigest(),
    }


if __name__ == "__main__":
    # Example: @quad(?x) := [>b, ^b[?x]<, >c, ?x<, a]
    # In Base-52 (a=1, b=2, c=3): 2*(x^2) + 3*x + 1
    sample_uml = "@quad(?x) := [>b, ^b[?x]<, >c, ?x<, a]"
    res = verify_tri_modal_in_container(sample_uml, [[0], [1], [2], [5]])
    print(json.dumps(res, indent=2))
