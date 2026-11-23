"""Read-only browser dashboard for the live LocalCoder INN distillation loop."""
from __future__ import annotations

import json
import math
import socket
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "autonomy"
DB_PATH = STATE_DIR / "state.sqlite3"
INN_STATE = STATE_DIR / "inn_hive_state.json"
EXPERIENCES = STATE_DIR / "learning" / "inn_hive_experiences.jsonl"
LEARNING_STATUS = STATE_DIR / "learning" / "multi_daemon_status.json"
STAGING_RUNS = Path(r"D:\AIOS_RawDump\L_neural_runs")
LOCAL_ARCHIVE = Path(r"F:\LocalCoder_Archive\INN_live_runs")
CLOUD_ARCHIVE = Path(r"G:\My Drive\AIOS_RawDump\L_neural_runs")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def load_receipts() -> list[dict]:
    try:
        with EXPERIENCES.open('rb') as stream:
            stream.seek(0, 2)
            start = max(0, stream.tell() - 8_000_000)
            stream.seek(start)
            lines = stream.read().splitlines()
        if start:
            lines = lines[1:]
        receipts = []
        for line in lines[-2000:]:
            try:
                receipts.append(json.loads(line))
            except (ValueError, UnicodeError):
                # A concurrent append can expose an incomplete final line.
                continue
        return receipts
    except OSError:
        return []


def setting(con: sqlite3.Connection, key: str, default=None):
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        return default


def runtime_state() -> tuple[dict, list[tuple], dict]:
    values, events, cycle = {}, [], {}
    try:
        with sqlite3.connect(DB_PATH, timeout=1) as con:
            for key in ("enabled", "worker", "supervisor", "worker_mode", "farm_gpu_phase"):
                values[key] = setting(con, key)
            events = con.execute(
                "SELECT at,kind,data FROM events ORDER BY id DESC LIMIT 16").fetchall()
            row = con.execute(
                "SELECT at,data FROM events WHERE kind='inn_hive_cycle_started' "
                "ORDER BY id DESC LIMIT 1").fetchone()
            if row:
                cycle = {"at": row[0], **json.loads(row[1])}
    except (sqlite3.Error, ValueError):
        pass
    return values, events, cycle


def ollama_online() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=0.25):
            return True
    except OSError:
        return False


def queen_processor() -> str:
    try:
        result = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=2,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return rows[1] if len(rows) > 1 else "Model not currently loaded"
    except (OSError, subprocess.SubprocessError):
        return "Ollama placement unavailable"


def age(timestamp: float | None) -> str:
    if not timestamp:
        return "never"
    seconds = max(0, time.time() - timestamp)
    if seconds < 60:
        return f"{seconds:.0f}s ago"
    return f"{seconds / 60:.1f}m ago"


def bool_mark(value) -> str:
    return "✅" if value is True else "❌" if value is False else "—"


def storage_free_gb(path: Path) -> float | None:
    try:
        return round(shutil.disk_usage(path).free / (1024 ** 3), 2)
    except OSError:
        return None


def archive_count(root: Path) -> int:
    try:
        return sum(1 for _ in root.glob("language-routes-*") if _.is_dir())
    except OSError:
        return 0


def lattice_metrics(snapshot_name: str | None) -> dict:
    if not snapshot_name:
        return {}
    graph = STATE_DIR / "learning" / "neural_runs" / snapshot_name / "neuron_graph.sqlite3"
    try:
        with sqlite3.connect(f"file:{graph.resolve()}?mode=ro", uri=True, timeout=0.5) as con:
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if {"neuron_identity", "links"}.issubset(tables):
                nodes = con.execute("SELECT COUNT(*) FROM neuron_identity").fetchone()[0]
                edges = con.execute("SELECT COUNT(*) FROM links").fetchone()[0]
            elif {"neurons", "links"}.issubset(tables):
                nodes = con.execute("SELECT COUNT(*) FROM neurons").fetchone()[0]
                edges = con.execute("SELECT COUNT(*) FROM links").fetchone()[0]
            else:
                return {"state": "UNSUPPORTED_SCHEMA"}
        return {
            "state": "LIVE",
            "nodes": int(nodes),
            "edges": int(edges),
            "E/N": round(edges / max(1, nodes), 6),
            "phase": "mesh_threshold_crossed" if edges >= nodes else "sparse_transition",
        }
    except (OSError, sqlite3.Error):
        return {"state": "READ_HOLD"}


def live_lattice_2d(snapshot_name: str | None, limit: int = 220):
    """Render a deterministic 2D projection of real SQLite nodes and links."""
    if not snapshot_name:
        return None
    graph = STATE_DIR / "learning" / "neural_runs" / snapshot_name / "neuron_graph.sqlite3"
    try:
        with sqlite3.connect(f"file:{graph.resolve()}?mode=ro", uri=True, timeout=0.5) as con:
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if {"neuron_identity", "links"}.issubset(tables):
                rows = con.execute(
                    """SELECT s.neuron_id, s.semantic_key, t.neuron_id, t.semantic_key, l.weight
                       FROM links l JOIN neuron_identity s ON s.neuron_id=l.source_id
                       JOIN neuron_identity t ON t.neuron_id=l.peer_id
                       ORDER BY l.weight DESC LIMIT ?""", (limit,)
                ).fetchall()
            elif {"neurons", "links"}.issubset(tables):
                rows = con.execute(
                    """SELECT s.neuron_id, s.neuron_id, t.neuron_id, t.neuron_id, l.weight
                       FROM links l JOIN neurons s ON s.neuron_id=l.source_id
                       JOIN neurons t ON t.neuron_id=l.peer_id
                       ORDER BY l.weight DESC LIMIT ?""", (limit,)
                ).fetchall()
            else:
                return None
        if not rows:
            return None
        names = {}
        edges = []
        for source_id, source, target_id, target, weight in rows:
            names[str(source_id)] = str(source)
            names[str(target_id)] = str(target)
            edges.append((str(source_id), str(target_id), float(weight or 0)))
        ordered = sorted(names)
        positions = {}
        for index, node_id in enumerate(ordered):
            angle = (index / max(1, len(ordered))) * 6.283185307179586
            radius = 1.0 + (index % 7) * 0.12
            positions[node_id] = (radius * math.cos(angle), radius * math.sin(angle))
        edge_x, edge_y = [], []
        for source_id, target_id, _ in edges:
            sx, sy = positions[source_id]; tx, ty = positions[target_id]
            edge_x.extend([sx, tx, None]); edge_y.extend([sy, ty, None])
        node_x = [positions[node_id][0] for node_id in ordered]
        node_y = [positions[node_id][1] for node_id in ordered]
        figure = go.Figure()
        figure.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines", line={"width": 0.5, "color": "#42657d"}, hoverinfo="none"))
        figure.add_trace(go.Scatter(
            x=node_x, y=node_y, mode="markers+text", text=[names[node_id] for node_id in ordered],
            textposition="top center", marker={"size": 7, "color": "#66d9ef"},
            hovertemplate="%{text}<extra>verified SQLite neuron</extra>",
        ))
        figure.update_layout(height=520, margin={"l": 0, "r": 0, "t": 10, "b": 0},
                             showlegend=False, paper_bgcolor="#071018", plot_bgcolor="#071018",
                             xaxis={"visible": False}, yaxis={"visible": False})
        return figure
    except (OSError, sqlite3.Error):
        return None


def live_learning_panel() -> None:
    status = read_json(LEARNING_STATUS, {})
    st.subheader("Viv learning and storage pipeline")
    if not status:
        st.warning("No multi-daemon heartbeat available.")
        return
    cols = st.columns(6)
    cols[0].metric("Learner", "RUNNING" if status.get("running") else "STOPPED")
    cols[1].metric("Attempts", f"{status.get('total_attempted', 0):,}")
    cols[2].metric("Graduated", f"{status.get('total_graduated', 0):,}")
    cols[3].metric("Sentences", f"{status.get('total_sentences_synthesized', 0):,}")
    cols[4].metric("L free GB", storage_free_gb(Path("L:\\")) or "—")
    cols[5].metric("E/N", f"{status.get('epoch_progress_edges_per_node', '—')}")
    st.caption(f"Heartbeat: {status.get('timestamp', 'unknown')} · latest: {status.get('latest_snapshot', 'none')}")
    lattice = lattice_metrics(status.get("latest_snapshot"))
    if lattice.get("state") == "LIVE":
        lcols = st.columns(4)
        lcols[0].metric("Lattice nodes", f"{lattice['nodes']:,}")
        lcols[1].metric("Lattice edges", f"{lattice['edges']:,}")
        lcols[2].metric("E/N", f"{lattice['E/N']:.6f}")
        lcols[3].metric("Topology phase", lattice["phase"])
    else:
        st.info(f"Lattice read state: {lattice.get('state', 'UNAVAILABLE')}")
    figure = live_lattice_2d(status.get("latest_snapshot"))
    if figure is not None:
        st.caption("Live 2D projection of verified SQLite nodes and edges; refreshed with the 2-second lattice fragment.")
        st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})
    pipeline = {
        "D staging runs": archive_count(STAGING_RUNS),
        "F local archive runs": archive_count(LOCAL_ARCHIVE),
        "G cloud archive runs": archive_count(CLOUD_ARCHIVE),
        "D free GB": storage_free_gb(Path("D:\\")),
        "F free GB": storage_free_gb(Path("F:\\")),
    }
    st.json(pipeline, expanded=False)
    if not status.get("running"):
        st.warning("Learner heartbeat is stopped or stale; process presence alone is not proof of learning.")


def action(item: dict | None) -> str:
    if not item:
        return "unavailable"
    return f"{item.get('tool', '?')} · plot {item.get('plot_a', '?')} · {item.get('stage', '?')}"


def correctness(receipt: dict, modern: str, legacy: str):
    return receipt.get(modern, receipt.get(legacy))


def neural_panel():
    corpus = read_json(STATE_DIR / 'learning' / 'farm_corpus_latest.json', {})
    adapter = read_json(STATE_DIR / 'learning' / 'farm_adapter_status.json', {})
    if corpus:
        st.subheader('Game-generated shared training corpus')
        st.caption(f"Corpus {corpus.get('corpus_id', '')[:16]} · "
                   f"{corpus.get('language_facts', 0)} Rust text facts · "
                   f"{corpus.get('action_contexts', 0)} action contexts · "
                   f"{corpus.get('model_rows', 0)} LoRA training rows")
        st.write('INN training is connected to this immutable corpus. A matching view is prepared for Hive LoRA training. Reserved plots 21 and 41 are excluded from training.')
    if adapter:
        st.write('**Model Queen LoRA:** ' + adapter.get('stage', 'preflight'))
        if adapter.get('output'):
            progress = read_json(Path(adapter['output']) / 'adapter' / 'training_progress.json', {})
            if progress:
                st.write(f"GPU training: {progress.get('stage')} · optimizer update "
                         f"{progress.get('update', 0)}/{progress.get('total_updates', 0)}")
                if progress.get('total_updates'):
                    st.progress(min(1., progress.get('update', 0) / progress['total_updates']))
                if progress.get('logs'):
                    st.json(progress['logs'], expanded=False)
            evaluation_progress = read_json(Path(adapter['output']) / 'adapter' / 'language_evaluation_progress.json', {})
            if adapter.get('stage') == 'evaluating_language' and evaluation_progress:
                st.write(f"Reserved language evaluation: {evaluation_progress.get('arm')} · "
                         f"{evaluation_progress.get('completed')}/{evaluation_progress.get('total')} · "
                         f"exact {evaluation_progress.get('exact')}")
            evaluation = adapter.get('language_evaluation')
            if evaluation:
                st.write('**Reserved language results:**')
                columns = st.columns(3)
                for column, key, label in zip(columns, ('base', 'farm-queen', 'farm-queen-final'),
                                              ('Base / plot 21', 'LoRA / plot 21', 'LoRA / plot 41')):
                    result = evaluation['summary'].get(key, {})
                    column.metric(label, f"{result.get('exact', 0)}/{result.get('total', 0)}")
                if evaluation.get('passed_language_gate'):
                    st.success('Reserved language gate passed. Adapter remains a candidate pending farm behavior and live activation gates.')
                else:
                    st.error('Reserved language gate failed. Adapter has not been activated.')
                st.caption('This is a language gate. Rust farm behavior and live adapter activation remain separate gates.')
        if adapter.get('blockers'):
            st.warning(' · '.join(adapter['blockers']))
        if not adapter.get('live_queen_weights_updated'):
            st.caption('The live Queen has not received a farm LoRA weight update.')
    status = read_json(STATE_DIR / 'learning' / 'neural_status.json', {})
    if not status:
        return
    st.subheader('Own neural INN: action + language training')
    st.caption('Shared INN attention blocks · byte language output · CPU training')
    admitted = read_json(STATE_DIR / 'learning' / 'neural_admitted.json', {})
    if admitted:
        proof = read_json(Path(admitted['run']) / 'evaluation.json', {})
        st.success(f"Admitted neural parent: {admitted.get('engine_sha256', '')[:16]} · "
                   f"reserved descriptions {proof.get('language', {}).get('exact', 0)}/{proof.get('language', {}).get('total', 0)}")
        with st.expander('Admitted neural parent: farm and language evidence'):
            st.json(proof)
    st.write('**Latest candidate attempt**')
    st.write(f"**Stage:** {status.get('stage')} · **Updated:** {status.get('at_utc', 'unknown')}")
    if status.get('error'):
        st.error(status['error'])
    if status.get('total_updates'):
        st.progress(min(1., status.get('update', 0) / status['total_updates']))
        st.write(f"Optimizer update {status.get('update', 0):,}/{status['total_updates']:,}")
    if status.get('losses'):
        st.json(status['losses'], expanded=False)
    result = status.get('receipt') or status.get('validation')
    if result:
        language = result.get('language', {})
        st.metric('Generated descriptions exactly correct', f"{language.get('exact', 0)}/{language.get('total', 0)}")
        if 'passed' in result:
            if result['passed']:
                admission = read_json(STATE_DIR / 'learning' / 'neural_admitted.json', {})
                st.success('Offline farm + language gates passed. ' +
                           ('Neural drone proposals admitted; Queen chooses and Rust verifies.'
                            if admission.get('run') == status.get('run') else 'Candidate awaits repeated verification.'))
            else:
                st.warning('Candidate failed the combined gate. Preserved for analysis; live policy remains unchanged.')
        examples = language.get('examples', [])
        if examples:
            st.dataframe(pd.DataFrame(examples), use_container_width=True, hide_index=True)
        with st.expander('Neural evaluation and farm comparisons'):
            st.json(result)


st.set_page_config(page_title="INN Distillation", page_icon="🧠", layout="wide")
st.markdown("""
<style>
  .stApp { background: #071018; color: #e7f3ff; }
  [data-testid="stMetric"] { background: #0d1d2b; border: 1px solid #1d3a51;
      border-radius: 10px; padding: 12px; }
  .stTabs [data-baseweb="tab"] { font-size: 1rem; }
</style>
""", unsafe_allow_html=True)

st.title("INN Distillation Console")
st.caption("Read-only live view · GPU switches between Queen inference and adapter training · INN drone and Rust oracle on CPU")


@st.fragment(run_every="2s")
def live_view():
    values, events, cycle = runtime_state()
    live_learning_panel()
    state = read_json(INN_STATE, {})
    farm = state.get("r", {})
    distillation = state.get("distillation") or {}
    admission = state.get("behavioral_admission") or {}
    recovery = read_json(STATE_DIR / "learning" / "recovery_evaluation.json", {})
    if recovery.get("passed"):
        st.caption("Legacy farm fallback: recovery passed its three frozen comparisons. Neural action/language evidence is in Learning history.")
        with st.expander("Legacy recovery gains"):
            st.dataframe(pd.DataFrame([{"steps": row["steps"], "candidate score": row["candidate"]["score"],
                                       "parent score": row["parent"]["score"], "candidate decays": row["candidate"]["decays"],
                                       "parent decays": row["parent"]["decays"]} for row in recovery["comparisons"]]), hide_index=True)
            st.caption(recovery["scope"])
    if admission:
        st.caption(f"Legacy learner gate: accepted={admission.get('accepted')}, measured improvement={admission.get('improved')}. Last checked {admission.get('at_utc')}.")
        with st.expander("Legacy parent versus candidate evidence"):
            st.json(admission)
    receipts = load_receipts()
    latest = receipts[-1] if receipts else {}
    worker = values.get("worker") or {}
    phase = values.get('farm_gpu_phase') or {}
    gpu_phase_active = phase.get('stage') in ('pausing_inference', 'training', 'restoring_queen', 'releasing_gpu')
    farm_paused = not values.get('enabled', False)
    worker_live = worker.get("state") == "running" and time.time() - worker.get("at", 0) < 30
    model_live = ollama_online()
    role_receipts = [item for item in receipts if "model_queen_correct" in item]
    receipt_time = datetime.fromisoformat(latest["at_utc"]).timestamp() if latest else 0
    recent_errors = [json.loads(raw).get("error", "Unknown error")
                     for timestamp, kind, raw in events
                     if kind == "worker_error" and timestamp > receipt_time]
    receipt_age = time.time() - receipt_time
    if recent_errors:
        st.error("Farm learning is failing: " + recent_errors[0])
    if receipt_age > 60 and not gpu_phase_active and not farm_paused:
        st.warning(f"No successful farm cycle for {receipt_age / 60:.1f} minutes. A worker heartbeat does not prove learning progress.")
    lesson_receipts = [item for item in receipts if item.get("distillation_lesson")]
    meaningful_lessons = sum(len(item.get("evaluations") or []) > 1 for item in lesson_receipts)
    neural_live = latest.get('inn_proposal_source') == 'own_neural_inn'
    speech_status = ('Current drone text is generated by the trained own INN; scope is short farm legality descriptions.'
                     if neural_live else 'Current proposal uses the legacy policy and a formatted message.')
    st.caption(f"Lessons with multiple action candidates: {meaningful_lessons}/{len(lesson_receipts)}. Single-action correctness does not measure decision skill. {speech_status}")
    queen_wins = sum(item.get("model_queen_correct") is True for item in role_receipts)
    inn_wins = sum(item.get("inn_drone_correct") is True for item in role_receipts)
    agreement = sum(item.get("agreement") is True for item in role_receipts)

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Live runtime")
        if gpu_phase_active:
            st.info('Scheduled GPU phase: ' + phase['stage'] + '. Farm execution is paused. Bounded GPU commands finish with the farm paused unless resume is requested.')
        elif farm_paused:
            st.info('Farm paused. Dashboard refresh continues, but it does not run training or advance the farm.')
        status = "⏸ Scheduled GPU training pause" if gpu_phase_active else "⏸ Paused · finishing current cycle" if farm_paused and worker_live else "⏸ Paused" if farm_paused else "🔴 Cycle failures" if recent_errors else "🟢 Process alive" if worker_live else "🔴 Stopped or stale"
        st.write(f"**Farm worker:** {status}  ·  last heartbeat {age(worker.get('at'))}")
        st.write(f"**Mode:** `{values.get('worker_mode') or 'hive'}`  ·  **Ollama:** {'🟢 online' if model_live else '🔴 offline'}")
        st.code(queen_processor(), language=None)
    with right:
        st.subheader("Placement")
        st.write("**Model Queen**  \n" + ('Ollama inference paused; GPU assigned to the farm adapter phase' if gpu_phase_active else 'Farm inference paused; resident GPU models shown at left' if farm_paused else 'GPU via Ollama, pinned for 30 minutes'))
        st.write("**INN drone**  \n" + ('CPU own neural action + language model' if neural_live else 'CPU legacy farm policy'))
        st.write("**Rust oracle/farm**  \nCPU deterministic evaluator")

    metrics = st.columns(3) + st.columns(3)
    metrics[0].metric("Farm tick", f"{farm.get('tick', 0):,}")
    metrics[1].metric("Farm steps", f"{farm.get('steps', 0):,}")
    metrics[2].metric("Distillation lessons", distillation.get("lessons", 0))
    metrics[3].metric("Teacher accepted", distillation.get("teacher_verified", 0))
    metrics[4].metric("Teacher rejected", distillation.get("teacher_rejected", 0))
    metrics[5].metric("Role-correct cycles", len(role_receipts))

    tabs = st.tabs(["Conversation", "Decision evidence", "Learning history", "Runtime log", "Raw receipt"])

    with tabs[0]:
        st.subheader("Last completed Queen ↔ INN exchange")
        st.caption(f"Recorded {latest.get('at_utc', 'never')} · {age(receipt_time)} · tick {latest.get('tick', '—')}")
        if latest.get("dialogue"):
            for turn in latest["dialogue"]:
                role = "assistant" if turn.get("speaker") == "Model Queen" else "user"
                with st.chat_message(role, avatar="👑" if role == "assistant" else "🧠"):
                    st.markdown(f"**{turn.get('speaker', 'Unknown')}**")
                    st.write(turn.get("content", ""))
                    if turn.get("action"):
                        st.caption(action(turn["action"]))
            queen = latest.get("model_queen") or {}
            if queen.get("rationale"):
                st.info("**Recorded Queen rationale:** " + queen["rationale"])
        else:
            st.info("Waiting for a role-correct Queen/INN cycle.")

        lesson = latest.get("distillation_lesson") or {}
        shadow = latest.get('neural_shadow') or {}
        if shadow:
            st.subheader('Own neural INN: actual generated text')
            if shadow.get('error'):
                st.error(shadow['error'])
            else:
                st.write(shadow.get('generated_text', ''))
                st.caption(f"Rust target: {shadow.get('rust_grounded_target')} · Exact: {shadow.get('text_exact')} · Mode: {shadow.get('mode')} · Execution authority: none")
                st.code(shadow.get('language_prompt', ''), language=None)
        if lesson:
            verdict = "accepted and imitated" if lesson.get("accepted") else "rejected after Rust evaluation"
            st.info(f"Saved Rust verdict: Queen lesson **{verdict}** · signal `{lesson.get('signal')}` · "
                       f"Candidate updates applied `{lesson.get('engine_updates_applied')}`")
            st.caption(lesson.get("update_target", "Historical receipt: updates predate candidate isolation."))

    with tabs[1]:
        st.subheader("Candidate actions evaluated by Rust")
        evaluations = latest.get("evaluations") or []
        rows = [{
            "candidate": item.get("candidate_id", "")[:12],
            "action": action(item.get("action")),
            "INN score": item.get("score"), "gate": item.get("gate"),
            "legal": item.get("legal"), "reward": item.get("reward"),
            "Rust utility": item.get("utility"),
        } for item in evaluations]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        if cycle and (not latest or cycle.get("at", 0) > datetime.fromisoformat(latest["at_utc"]).timestamp()):
            st.warning(f"Cycle in progress at tick {cycle.get('tick')}: "
                       f"{cycle.get('candidate_count')} candidates offered to the Queen.")
            st.json(cycle.get("candidates", []), expanded=False)

    with tabs[2]:
        unified_status = read_json(STATE_DIR / 'learning/unified_viv_status.json', {})
        if unified_status:
            st.subheader('Unified AIOS Viv Toddler Brain (Steel Brain Neurons + UML `!0` + INN Language)')
            u_summary = unified_status.get('brain_summary') or {}
            u_receipt = unified_status.get('receipt') or {}
            u_rid = u_receipt.get('rid_stability') or {}
            st.write(
                f"Stage: **{unified_status.get('stage')}** · "
                f"Updates: {unified_status.get('update', 0)}/{unified_status.get('total_updates', 0)} · "
                f"Total Steel Brain Neurons: **{u_summary.get('total_neurons', 0):,}** "
                f"(`STABLE` words: **{u_summary.get('total_stable_words', 0):,}**)"
            )
            if u_rid:
                r_cols = st.columns(4)
                r_cols[0].metric('RID $S_n$', f"{u_rid.get('s_n', 0.0):.4f}")
                r_cols[1].metric('RSR (Identity)', f"{u_rid.get('rsr', 0.0):.4f}")
                r_cols[2].metric('LTP (Structure)', f"{u_rid.get('ltp', 0.0):.4f}")
                r_cols[3].metric('RLE (Efficiency)', f"{u_rid.get('rle', 0.0):.4f}")
            u_stages = u_receipt.get('stages') or {}
            if u_stages:
                s_cols = st.columns(3)
                for col, s_key, s_label in zip(
                    s_cols,
                    ('spelling', 'speaking', 'meaning'),
                    ('Stage 1: Spelling & Unscramble', 'Stage 2: Toddler Speaking', 'Stage 3: Word Meaning'),
                ):
                    s_data = u_stages.get(s_key, {})
                    col.metric(s_label, f"{s_data.get('exact', 0)}/{s_data.get('total', 0)} ({s_data.get('accuracy', 0.0)*100:.1f}%)")
                if u_receipt.get('passed'):
                    u_flash = u_receipt.get('emergent_flashcard_deck') or {}
                    u_found = u_flash.get('hardcoded_foundation') or {}
                    st.success(
                        f"Unified Toddler Gate Passed · Origin DB Immutable Verified: {u_receipt.get('origin_immutable_verified')} · "
                        f"Hardcoded Primitives: {u_found.get('total_hardcoded_primitives', 27)} (26 letters + 1 SHIFT) · "
                        f"Flashcards Mastered: {u_flash.get('mastered_cards', 0)}/{u_flash.get('deck_size', 0)} "
                        f"(Reshuffles: {u_flash.get('total_reshuffles', 0)}) · "
                        f"Meanings Bound in Clone: {u_receipt.get('bound_meanings_in_clone', 0)}"
                    )
                with st.expander('Unified Viv Toddler Demonstrations & Flashcard STDP Trace'):
                    st.json({
                        'emergent_flashcard_deck': u_receipt.get('emergent_flashcard_deck', {}),
                        'demonstrations': u_receipt.get('demonstrations', []),
                    }, expanded=False)
        wiki_status = read_json(STATE_DIR / 'learning/inn_wikipedia_status.json', {})
        if wiki_status:
            st.subheader('Resumable Wikipedia learning campaign')
            st.write(f"Stage: **{wiki_status.get('stage')}** · Command updates: {wiki_status.get('updates', 0)}/{wiki_status.get('total_updates', 0)} · CPU INN")
            st.write(f"Completed eligible articles: **{wiki_status.get('articles_completed', 0):,}** · Presented training chunks: **{wiki_status.get('chunks_presented', 0):,}**")
            st.caption(f"Current segment: {wiki_status.get('segment_articles', 0)} articles; {wiki_status.get('offset', 0)}/{wiki_status.get('segment_chunks', 0)} training chunks. Optimizer steps: {wiki_status.get('optimizer_start', 0)} → {wiki_status.get('optimizer_steps', wiki_status.get('optimizer_start', 0))}. Vocabulary: {wiki_status.get('tokenizer_size', 0)}.")
            st.caption('Committed dataset cursor: ' + (wiki_status.get('cursor') or 'Start; first segment still pending'))
            if wiki_status.get('error'):
                st.error(wiki_status['error'])
            wiki_receipt = wiki_status.get('receipt') or {}
            if wiki_receipt:
                st.write(f"Prior descriptions retained: {wiki_receipt['retained']}/{wiki_receipt['retention_total']} · Checkpoint reload identical: {wiki_receipt['reload_identical']} · Continuation commit: {wiki_receipt['passed']}")
                for split, result in wiki_receipt.get('after', {}).items():
                    st.write(f"{split} development NLL: {wiki_receipt['before'][split]['nll']:.3f} → {result['nll']:.3f}")
                with st.expander('Campaign neural continuations and receipt'):
                    for item in wiki_receipt.get('generations', []):
                        st.code(item['prompt'] + item['generated'], language=None)
                        st.caption('Reference: ' + item['reference'])
                    st.json(wiki_receipt, expanded=False)
            st.warning('Presented articles are training exposure, not proof they were learned. Factual generation remains unproven; farm admission is unchanged.')
        sentence_status = read_json(STATE_DIR / 'learning/inn_sentence_status.json', {})
        if sentence_status:
            st.subheader('Wikipedia sentence-learning pilot')
            st.write(f"Stage: **{sentence_status.get('stage')}** · Updates: {sentence_status.get('updates', 0)}/{sentence_status.get('total_updates', 0)} · Curriculum: {sentence_status.get('curriculum')}")
            st.caption(f"{sentence_status.get('articles')} accepted article leads · {sentence_status.get('train_sentences')} training sentences · {sentence_status.get('tokenizer_size')} character/special rows · CPU · candidate only")
            sentence_receipt = sentence_status.get('receipt') or {}
            if sentence_status.get('error'):
                st.error(sentence_status['error'])
            if sentence_receipt:
                for split in ('validation', 'test'):
                    st.write(f"{split} next-character NLL: {sentence_receipt['before'][split]['nll']:.3f} → {sentence_receipt['after'][split]['nll']:.3f} (lower is better)")
                st.write(f"Retained prior descriptions: {sentence_receipt['retained']}/{sentence_receipt['retention_total']}")
                st.write('Prediction/retention gate: ' + ('passed' if sentence_receipt['passed'] else 'failed'))
                st.warning('Readable factual sentence generation has not passed a quality gate. Prediction loss and prior-skill retention are measured separately.')
                st.caption(sentence_receipt['scope'])
                with st.expander('Actual Wikipedia continuation samples'):
                    for example in sentence_receipt.get('generations', []):
                        st.code(example['prompt'] + example['generated'], language=None)
                        st.caption('Source reference: ' + example['reference'])
        tokenizer_status = read_json(STATE_DIR / 'learning/inn_tokenizer_status.json', {})
        if tokenizer_status:
            st.subheader('Custom UML tokenizer inside INN')
            st.write(f"Stage: **{tokenizer_status.get('stage')}** · Updates: {tokenizer_status.get('updates', 0)}/{tokenizer_status.get('total_updates', 0)}")
            st.caption(f"Active character vocabulary: {tokenizer_status.get('tokenizer_size')} including special tokens · Context: {tokenizer_status.get('context_length')} characters/tokens · Candidate only")
            token_receipt = tokenizer_status.get('receipt') or {}
            if token_receipt:
                for arm, result in token_receipt.get('after', {}).items():
                    before = token_receipt['baseline'][arm]
                    st.write(f"{arm}: before {before['exact']}/{before['total']} → after {result['exact']}/{result['total']}")
                if token_receipt.get('passed'):
                    st.success('Tokenizer integration and reserved sentence-generation gate passed. Candidate has not replaced the live INN.')
                else:
                    st.error('Candidate failed the reserved sentence-generation gate. Previous live checkpoint preserved.')
                st.caption(token_receipt.get('scope', ''))
                with st.expander('Custom tokenizer verification receipt'):
                    st.json(token_receipt, expanded=False)
        st.caption('Neural training: a bounded 500-update CPU attempt every 250 completed farm lessons. Each attempt resumes the admitted parent, reads verified live facts, and must pass language and farm gates before replacement.')
        neural_panel()
        st.subheader("Verified teacher-student results")
        if role_receipts:
            history = pd.DataFrame([{
                "tick": item.get("tick"),
                "model queen": int(item.get("model_queen_correct") is True),
                "INN drone": int(item.get("inn_drone_correct") is True),
                "agreement": int(item.get("agreement") is True),
                "candidates": len(item.get("evaluations") or []),
                "teacher signal": (item.get("distillation_lesson") or {}).get("signal"),
            } for item in role_receipts])
            st.line_chart(history.set_index("tick")[["model queen", "INN drone", "agreement"]], height=260)
            st.dataframe(history.iloc[::-1], use_container_width=True, hide_index=True)
        else:
            st.info("No role-correct cycles recorded yet.")
        st.caption(f"Current totals: Queen correct {queen_wins}/{len(role_receipts)} · "
                   f"INN correct {inn_wins}/{len(role_receipts)} · agreement {agreement}/{len(role_receipts)}")

    with tabs[3]:
        st.subheader("Latest Hive events")
        log_rows = []
        for timestamp, kind, raw in events:
            try:
                data = json.loads(raw)
                detail = data.get("result") or data.get("error") or data.get("reason") or ""
            except (TypeError, ValueError):
                detail = raw
            log_rows.append({"time": datetime.fromtimestamp(timestamp).strftime("%H:%M:%S"),
                             "event": kind, "detail": str(detail)[:400]})
        st.dataframe(pd.DataFrame(log_rows), use_container_width=True, hide_index=True)

    with tabs[4]:
        st.caption("The receipt is immutable evidence for the most recently completed learning cycle.")
        st.json(latest, expanded=False)


live_view()
