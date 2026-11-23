import sqlite3
import hashlib
from datetime import datetime, timezone

def learn_python_dual_ontology_and_coding_cortex():
    lex_db = 'L:/LocalCoder/workspace/autonomy/data/lexicon_ontology.db'
    top_db = 'L:/LocalCoder/workspace/autonomy/viv_code_topology.sqlite3'
    
    # 1. Update lexicon_ontology.db: Register python_programming as unique lemma
    conn_lex = sqlite3.connect(lex_db)
    cur_lex = conn_lex.cursor()
    
    now_utc = datetime.now(timezone.utc).isoformat()
    cur_lex.execute("SELECT entity_id FROM lexical_entities WHERE lemma = 'python_programming'")
    coding_row = cur_lex.fetchone()
    
    if not coding_row:
        def_text = "A high-level programming language used to build tools, write scripts, define functions, manage memory, and orchestrate CLI applications."
        def_hash = hashlib.sha256(def_text.encode()).hexdigest()
        src_hash = hashlib.sha256(b"AIOS_PYTHON_PROGRAMMING_BIRTH").hexdigest()
        
        cur_lex.execute('''
            INSERT INTO lexical_entities (lemma, part_of_speech, domain, is_concrete, raw_definition, source_entry_id, definition_hash, created_utc)
            VALUES ('python_programming', 'noun', 'domain:software_engineering', 0, ?, ?, ?, ?)
        ''', (def_text, src_hash, def_hash, now_utc))
        coding_python_id = cur_lex.lastrowid
        print(f"[LEXICON SUCCESS] Created Python Programming Entity: ID {coding_python_id}")
    else:
        coding_python_id = coding_row[0]
        print(f"[LEXICON EXISTS] Python Programming Entity ID: {coding_python_id}")
        
    conn_lex.commit()
    conn_lex.close()
    
    # 2. Wire Python Neurons and Tool-Building Blueprints into viv_code_topology.sqlite3
    conn_top = sqlite3.connect(top_db)
    cur_top = conn_top.cursor()
    
    # Fundamental Python Neurons
    cur_top.execute('''
    CREATE TABLE IF NOT EXISTS viv_python_neural_cortex (
        neuron_id TEXT PRIMARY KEY,
        neuron_label TEXT NOT NULL,
        syntax_role TEXT NOT NULL,
        code_template TEXT NOT NULL,
        ast_validator_pattern TEXT NOT NULL,
        resonance_weight REAL DEFAULT 1.0,
        activation_count INTEGER DEFAULT 1,
        sha256_hash TEXT NOT NULL
    )
    ''')
    
    python_neurons = [
        (
            "NEURON_PY_IMPORT",
            "python_neuron:import",
            "IMPORT",
            "import {module}\nfrom {module} import {symbol}",
            "ast.Import, ast.ImportFrom",
            hashlib.sha256(b"PY_IMPORT").hexdigest()
        ),
        (
            "NEURON_PY_FUNCTION",
            "python_neuron:function_def",
            "FUNCTION_DEF",
            "def {func_name}({args}) -> {ret_type}:\n    \"\"\"{doc}\"\"\"\n    {body}\n    return {ret_val}",
            "ast.FunctionDef, ast.Return",
            hashlib.sha256(b"PY_FUNCTION").hexdigest()
        ),
        (
            "NEURON_PY_VARIABLE",
            "python_neuron:variable_assign",
            "VARIABLE_ASSIGN",
            "{var_name} = {expression}",
            "ast.Assign",
            hashlib.sha256(b"PY_ASSIGN").hexdigest()
        ),
        (
            "NEURON_PY_CONTROL_FLOW",
            "python_neuron:control_flow",
            "CONTROL_FLOW",
            "if {condition}:\n    {if_body}\nelse:\n    {else_body}",
            "ast.If, ast.Compare",
            hashlib.sha256(b"PY_IF").hexdigest()
        ),
        (
            "NEURON_PY_CLI_TOOL_CALL",
            "python_neuron:cli_tool_invocation",
            "CLI_TOOL_CALL",
            "subprocess.run([{cmd_args}], capture_output=True, text=True, check=True)",
            "ast.Call",
            hashlib.sha256(b"PY_CLI").hexdigest()
        )
    ]
    
    for nid, label, role, tmpl, ast_pat, h in python_neurons:
        cur_top.execute('''
            INSERT INTO viv_python_neural_cortex
            (neuron_id, neuron_label, syntax_role, code_template, ast_validator_pattern, resonance_weight, activation_count, sha256_hash)
            VALUES (?, ?, ?, ?, ?, 1.0, 1, ?)
            ON CONFLICT(neuron_id) DO UPDATE SET
            activation_count = activation_count + 1,
            resonance_weight = resonance_weight + 0.1
        ''', (nid, label, role, tmpl, ast_pat, h))
        
    # 3. Contextual Disambiguation Router: Animal vs Coding Language
    cur_top.execute('''
    CREATE TABLE IF NOT EXISTS viv_semantic_disambiguation_rules (
        rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
        polysemous_word TEXT NOT NULL,
        context_cues TEXT NOT NULL,
        resolved_domain TEXT NOT NULL,
        activated_neuron_cluster TEXT NOT NULL
    )
    ''')
    cur_top.execute('DELETE FROM viv_semantic_disambiguation_rules WHERE polysemous_word = "python"')
    cur_top.execute('''
        INSERT INTO viv_semantic_disambiguation_rules (polysemous_word, context_cues, resolved_domain, activated_neuron_cluster)
        VALUES 
        ('python', 'snake, reptile, zoo, jungle, bite, wild, biology, species, venom', 'BIOLOGICAL_ANIMAL', 'NEURON_ANIMAL_SERPENT'),
        ('python', 'code, script, write, build, function, import, def, variable, program, cli, run, tool, bug', 'SOFTWARE_ENGINEERING', 'NEURON_PY_IMPORT,NEURON_PY_FUNCTION,NEURON_PY_VARIABLE,NEURON_PY_CLI_TOOL_CALL')
    ''')
    
    # 4. Tool Building Governance Matrix: Allowed vs Forbidden Boundaries
    cur_top.execute('''
    CREATE TABLE IF NOT EXISTS viv_tool_building_governance (
        blueprint_id INTEGER PRIMARY KEY AUTOINCREMENT,
        tool_category TEXT NOT NULL,
        allow_or_forbidden TEXT NOT NULL, -- 'ALLOWED' vs 'FORBIDDEN'
        boundary_condition TEXT NOT NULL,
        verification_gate TEXT NOT NULL,
        sha256_seal TEXT NOT NULL
    )
    ''')
    
    cur_top.execute('DELETE FROM viv_tool_building_governance')
    governance_rules = [
        ("FILE_ANALYZER_AND_PARSER", "ALLOWED", "Reads .py, .md, .json, .sqlite3 files within L:\\ territory only.", "AST Parse + Sandboxed Read Receipt", hashlib.sha256(b"ALLOW_PARSER").hexdigest()),
        ("CLI_UTILITY_RUNNER", "ALLOWED", "Executes local verified diagnostic CLI tools within L:\\ territory.", "Deterministic Exit Code 0 + Timeout Gate", hashlib.sha256(b"ALLOW_CLI").hexdigest()),
        ("MATHEMATICAL_AND_DATA_TOOL", "ALLOWED", "Pure algorithmic calculators, encoders, and data processors.", "Deterministic ALU & Unit Tests Passing", hashlib.sha256(b"ALLOW_MATH").hexdigest()),
        ("EXTERNAL_NETWORK_EXFILTRATION", "FORBIDDEN", "Outbound internet requests outside authorized 192.168.1.21:1234 LM Studio.", "Rust Socket Filter (Hard Deny)", hashlib.sha256(b"FORBID_EXFIL").hexdigest()),
        ("DESTRUCTIVE_FILESYSTEM_WIPE", "FORBIDDEN", "Commands deleting system directories or formatting storage outside scratch buffers.", "Monotonic Write Governor (Hard Deny)", hashlib.sha256(b"FORBID_WIPE").hexdigest())
    ]
    
    for cat, status, cond, gate, seal in governance_rules:
        cur_top.execute('''
            INSERT INTO viv_tool_building_governance
            (tool_category, allow_or_forbidden, boundary_condition, verification_gate, sha256_seal)
            VALUES (?, ?, ?, ?, ?)
        ''', (cat, status, cond, gate, seal))
        
    conn_top.commit()
    print("[TOPOLOGY SUCCESS] Python Neurons, Disambiguation Rules, and Tool Building Governance Matrix recorded.")
    
    conn_top.close()

if __name__ == '__main__':
    learn_python_dual_ontology_and_coding_cortex()
