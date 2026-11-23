import argparse
import hashlib
import json
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

from .engine import DEFAULT_CONFIG, LinearEngine, Simulation
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


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local INN: Python engine and Rust farm')
    parser.add_argument('--engine', choices=['transformer', 'linear'], default='transformer')
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    parser.add_argument('--steps', type=int, default=10000, help='0 runs until Ctrl+C')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--fresh', action='store_true', help='New farm instead of importing the saved sheet run')
    parser.add_argument('--resume', type=Path, help='Checkpoint generation directory')
    parser.add_argument('--checkpoint-every', type=int, default=1000)
    parser.add_argument('--train-every', type=int)
    parser.add_argument('--report-every', type=int, default=1000)
    parser.add_argument('--threads', type=int, default=1)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.steps < 0 or min(args.checkpoint_every, args.train_every or 32, args.report_every, args.threads) < 1:
        parser.error('Counts must be positive; steps may be zero for continuous operation')
    if args.resume:
        state = load_checkpoint(args.resume)
        expected = 'linear-v8' if args.engine == 'linear' else 'transformer'
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
        engine = LinearEngine(config, state)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = args.output or ROOT / 'runs' / run_id
    output.mkdir(parents=True, exist_ok=False)
    with Farm(state) as farm:
        sim = Simulation(farm, engine, state, args.seed)
        if state is None:
            sim.r['epsilon'] = config['epsilonStart']
        initial_tick = sim.r['tick']
        write_json(output / 'run.json', dict(engine=engine.kind, device=args.device, seed=args.seed,
                   initial_tick=initial_tick, source=(state or {}).get('source'), python=os.sys.executable,
                   config=config, train_every=args.train_every))
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
            with (output / 'telemetry.jsonl').open('w', encoding='utf-8') as log:
                while not stop_requested and (args.steps == 0 or completed < args.steps):
                    sim.step()
                    completed += 1
                    if completed % args.report_every == 0:
                        row = dict(steps=completed, tick=sim.r['tick'], seconds=time.perf_counter()-begin,
                                   bank=sim.r['bank'], lifetime=sim.r['lifetime'], active=sim.r['active'],
                                   harvests=sim.r['harvests'], decays=sim.r['decays'], loss=engine.loss,
                                   optimizer_steps=getattr(engine, 'optimizer_steps', 0))
                        log.write(json.dumps(row) + '\n')
                        log.flush()
                        print(f"{completed:,} steps | {completed/row['seconds']:.1f}/s | bank {row['bank']:g} | harvests {row['harvests']} | loss {engine.loss:.4g}", flush=True)
                    if completed % args.checkpoint_every == 0:
                        checkpoint(sim, output / f'checkpoint-{completed:09d}')
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
                checkpoint(sim, output / 'checkpoint-final')
            write_json(output / 'receipt.json', dict(status=stopped, steps=completed, seconds=seconds,
                       steps_per_second=completed/max(seconds, 1e-9), initial_tick=initial_tick,
                       final_tick=sim.r['tick'], engine=engine.kind, optimizer_steps=getattr(engine,'optimizer_steps',0),
                       final_runtime=sim.r, final_loss=engine.loss))
        print(f'{stopped}: {completed:,} steps in {seconds:.3f}s ({completed/max(seconds,1e-9):.1f}/s)', flush=True)
    return output
