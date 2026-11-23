import argparse
import copy
import hashlib
import json
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

from .engine import DEFAULT_CONFIG, LinearEngine, SourceEngine, StabilizedSourceEngine, Simulation, LOG_HEADER
from .farm import Farm, ROOT
from .import_sheet import import_workbook


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')


def checkpoint(sim, folder):
    folder.mkdir()
    write_json(folder / 'state.json', sim.snapshot())
    if sim.engine.kind == 'transformer':
        sim.engine.save(folder / 'engine.pt')
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}
    write_json(folder / 'manifest.json', dict(files=files, tick=sim.r['tick'], engine=sim.engine.kind))


def load_checkpoint(folder):
    manifest = json.loads((folder / 'manifest.json').read_text())
    for name, digest in manifest['files'].items():
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Checkpoint integrity failed: {name}')
    return json.loads((folder / 'state.json').read_text())


def probe_learned(engine, config, seed=991, steps=1000):
    """Evaluate a linear policy on a fresh farm without changing its weights."""
    if engine.kind != 'learned-v9':
        return None
    from .farm import Farm
    candidate = copy.deepcopy(engine)
    candidate.learn = lambda *args, **kwargs: None
    candidate.outcome = lambda *args, **kwargs: None
    with Farm() as farm:
        sim = Simulation(farm, candidate, None, seed)
        sim.r['epsilon'] = 0.
        start = copy.deepcopy(sim.r)
        for _ in range(steps):
            sim.step()
        return dict(score=(sim.r['harvests']-start['harvests'])-(sim.r['decays']-start['decays']),
                    harvests=sim.r['harvests']-start['harvests'],
                    decays=sim.r['decays']-start['decays'])


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local INN: Python engine and Rust farm')
    parser.add_argument('--engine', choices=['source', 'learned', 'transformer', 'linear'], default='learned')
    parser.add_argument('--experimental-transformer', action='store_true', help='Explicitly select the earlier redesigned neural experiment')
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    parser.add_argument('--steps', type=int, default=10000, help='0 runs until Ctrl+C')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--fresh', action='store_true', help='New farm instead of importing the saved sheet run')
    parser.add_argument('--from-sheet', action='store_true', help='Start from the original sheet checkpoint instead of the latest local source run')
    parser.add_argument('--resume', type=Path, help='Checkpoint generation directory')
    parser.add_argument('--checkpoint-every', type=int, default=1000)
    parser.add_argument('--train-every', type=int)
    parser.add_argument('--report-every', type=int, default=1000)
    parser.add_argument('--threads', type=int, default=1)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--run-root', type=Path, default=ROOT / 'runs')
    parser.add_argument('--no-latest', action='store_true', help='Do not update the normal continuation pointer (verification runs)')
    parser.add_argument('--compact-log', action='store_true', help='Write one ACTION row per step; retain telemetry and checkpoints')
    args = parser.parse_args(argv)
    if args.engine == 'transformer' and not args.experimental_transformer:
        parser.error('The added Transformer changes the source learner. Use --experimental-transformer only for that experiment. The default executes your source engine.')
    latest_pointer = ROOT / 'latest-source.json'
    latest_learned_checkpoint = ROOT / 'latest-learned-checkpoint.json'
    learned_policy_pointer = ROOT / 'latest-learned-policy.json'
    continuation_pointer = latest_pointer if args.engine == 'source' else latest_learned_checkpoint
    if args.engine in ('source','learned') and not any((args.resume,args.fresh,args.from_sheet)) and continuation_pointer.exists():
        candidate = Path(json.loads(continuation_pointer.read_text())['checkpoint'])
        expected = {'source':'source-v8','learned':'learned-v9'}[args.engine]
        if candidate.exists() and json.loads((candidate / 'state.json').read_text()).get('engine_kind') == expected:
            args.resume = candidate
    if args.steps < 0 or min(args.checkpoint_every, args.train_every or 32, args.report_every, args.threads) < 1:
        parser.error('Counts must be positive; steps may be zero for continuous operation')
    if args.resume:
        state = load_checkpoint(args.resume)
        expected = {'source':'source-v8','learned':'learned-v9','linear':'linear-v8','transformer':'transformer'}[args.engine]
        if state['engine_kind'] != expected:
            parser.error('Resume with the same engine kind as the checkpoint')
    elif args.fresh:
        state = None
    else:
        state = import_workbook(ROOT / 'Integrated Neural Network Architecture.xlsx')
    config = dict(DEFAULT_CONFIG, **(state or {}).get('config', {}))
    args.train_every = args.train_every or (state or {}).get('train_every', 32)
    if args.engine == 'transformer':
        import torch
        from .transformer import TransformerEngine
        torch.set_num_threads(args.threads)
        if args.device == 'cuda' and not torch.cuda.is_available():
            parser.error('CUDA is unavailable in this Python environment')
        engine = TransformerEngine(config, state, args.device, args.train_every, args.seed)
        if args.resume:
            engine.load(args.resume / 'engine.pt')
    else:
        engine = ({'source': SourceEngine, 'learned': StabilizedSourceEngine,
                   'linear': LinearEngine}[args.engine])(config, state)
        if args.engine == 'learned' and not args.resume and not args.fresh and learned_policy_pointer.exists():
            promoted = json.loads(learned_policy_pointer.read_text())
            engine.w = promoted['engine']['w']
            engine.validity = promoted['engine']['validity']
            engine.loss = promoted['engine'].get('loss', 0.)
            engine.updates = promoted['engine'].get('updates', 0)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = args.output or args.run_root / run_id
    output.mkdir(parents=True, exist_ok=False)
    active_lock = output / 'source-active.json'
    if args.engine == 'source':
        write_json(active_lock,dict(pid=os.getpid()))
    with Farm(state) as farm:
        sim = Simulation(farm, engine, state, args.seed)
        if state is None:
            sim.r['epsilon'] = config['epsilonStart']
        initial_tick = sim.r['tick']
        write_json(output / 'run.json', dict(engine=engine.kind, device=args.device, seed=args.seed,
                   initial_tick=initial_tick, source=(state or {}).get('source'), python=os.sys.executable,
                   config=config, train_every=args.train_every, resume=str(args.resume) if args.resume else None,
                   action_logging='every action, transition, and world event', source_run_id=sim.id))
        write_json(output / 'training_log_schema.json', dict(columns=LOG_HEADER,source='FarmScript.txt row8'))
        previous_report = dict(sim.r)
        best_score = float('-inf')
        best_probe = None
        best_engine_state = None
        def save_checkpoint(folder):
            checkpoint(sim, folder)
            if args.engine == 'source' and not args.no_latest:
                temporary = latest_pointer.with_suffix('.tmp')
                write_json(temporary, dict(checkpoint=str(folder.resolve()),run=str(output.resolve()),tick=sim.r['tick']))
                os.replace(temporary, latest_pointer)
            if args.engine == 'learned' and not args.no_latest:
                temporary = latest_learned_checkpoint.with_suffix('.tmp')
                write_json(temporary, dict(checkpoint=str(folder.resolve()),run=str(output.resolve()),tick=sim.r['tick']))
                os.replace(temporary, latest_learned_checkpoint)
        print(f'{engine.kind} | {args.device} | tick {initial_tick} | {output}', flush=True)
        begin = time.perf_counter()
        completed = 0
        stopped = 'complete'
        stop_requested = False
        def request_stop(signum, frame):
            nonlocal stop_requested
            stop_requested = True
        previous_handler = signal.signal(signal.SIGINT, request_stop)
        try:
            with (output / 'telemetry.jsonl').open('w', encoding='utf-8') as log, (output / 'training_log.jsonl').open('w',encoding='utf-8',buffering=1024*1024) as actions:
                while not stop_requested and (args.steps == 0 or completed < args.steps):
                    event = sim.step()
                    completed += 1
                    logged_rows = [row for row in event['rows'] if not args.compact_log or row[22] == 'ACTION']
                    for index,row in enumerate(logged_rows):
                        actions.write(json.dumps(dict(sheet_row=sim.batch_start+index,local_step=completed,values=row),separators=(',',':'),allow_nan=False)+'\n')
                    if completed % 100 == 0:
                        actions.flush()
                    if completed % args.report_every == 0:
                        row = dict(steps=completed, tick=sim.r['tick'], seconds=time.perf_counter()-begin,
                                   bank=sim.r['bank'], lifetime=sim.r['lifetime'], active=sim.r['active'],
                                   harvests=sim.r['harvests'], decays=sim.r['decays'], loss=engine.loss,
                                   optimizer_steps=getattr(engine, 'optimizer_steps', 0),
                                   episode_reward=sim.r['episode'],reward_delta=sim.r['episode']-previous_report['episode'],
                                   harvest_delta=sim.r['harvests']-previous_report['harvests'],
                                   decay_delta=sim.r['decays']-previous_report['decays'],
                                   invalid_delta=sim.r['invalid']-previous_report['invalid'],updates=engine.updates,
                                   max_plots=sim.r['max'])
                        previous_report = dict(sim.r)
                        log.write(json.dumps(row) + '\n')
                        log.flush()
                        score = sim.r['harvests'] - sim.r['decays']
                        probe = probe_learned(engine, config) if engine.kind == 'learned-v9' else None
                        if probe is not None and (best_probe is None or probe['score'] >= best_probe['score']):
                            best_probe = probe
                            best_engine_state = copy.deepcopy(engine.state())
                            policy = dict(engine=best_engine_state, probe=best_probe,
                                          source_run_id=sim.id, training_steps=completed)
                            temporary_policy = learned_policy_pointer.with_suffix('.tmp')
                            write_json(temporary_policy, policy)
                            os.replace(temporary_policy, learned_policy_pointer)
                        elif probe is not None and best_engine_state is not None:
                            engine.w = copy.deepcopy(best_engine_state['w'])
                            engine.validity = copy.deepcopy(best_engine_state['validity'])
                            engine.loss = best_engine_state['loss']
                            engine.updates = best_engine_state['updates']
                        if score > best_score:
                            best_score = score
                            write_json(output / 'best_policy.json', dict(score=score, steps=completed,
                                runtime=sim.r, probe=best_probe, engine=(best_engine_state or engine.state()), source_run_id=sim.id))
                        print(f"{completed:,} steps | {completed/row['seconds']:.1f}/s | bank {row['bank']:g} | harvests {row['harvests']} | loss {engine.loss:.4g}", flush=True)
                    if completed % args.checkpoint_every == 0:
                        actions.flush()
                        os.fsync(actions.fileno())
                        save_checkpoint(output / f'checkpoint-{completed:09d}')
                if stop_requested:
                    stopped = 'interrupted'
        except KeyboardInterrupt:
            stopped = 'interrupted'
        except Exception:
            stopped = 'error'
            raise
        finally:
            signal.signal(signal.SIGINT, previous_handler)
            seconds = time.perf_counter() - begin
            # Mid-tick errors have no committed checkpoint; preserve the diagnostic separately.
            if stopped != 'error':
                save_checkpoint(output / 'checkpoint-final')
            write_json(output / 'receipt.json', dict(status=stopped, steps=completed, seconds=seconds,
                       steps_per_second=completed/max(seconds, 1e-9), initial_tick=initial_tick,
                       final_tick=sim.r['tick'], engine=engine.kind, optimizer_steps=getattr(engine,'optimizer_steps',0),
                       final_runtime=sim.r, final_loss=engine.loss))
            if active_lock.exists():
                active_lock.unlink()
        print(f'{stopped}: {completed:,} steps in {seconds:.3f}s ({completed/max(seconds,1e-9):.1f}/s)', flush=True)
    return output
