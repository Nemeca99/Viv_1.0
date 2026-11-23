"""Stopped-state source controls: immutable checkpoint branches, original reset/replay."""
import argparse
from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from inn.cli import load_checkpoint, checkpoint, write_json
from inn.engine import SourceEngine, StabilizedSourceEngine, Simulation
from inn.farm import Farm, ROOT
from inn.import_sheet import import_workbook


def read_history(path):
    with path.open(encoding='utf-8') as stream:
        tail = deque(stream, maxlen=2048)
    rows = []
    numeric = [1,3,4,*range(6,22),25,26,27,28,29]
    for line in tail:
        row = json.loads(line)['values']
        if row[22]=='TRANSITION' and row[23]=='8-outcomes':
            for index in numeric:
                row[index] = float(row[index]) if isinstance(row[index],str) and row[index] else row[index]
        rows.append(row)
    return rows


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['reset','bank'])
    parser.add_argument('--value',type=float)
    parser.add_argument('--seed',type=int,default=1)
    parser.add_argument('--checkpoint',type=Path)
    args=parser.parse_args()
    pointer=ROOT/'latest-source.json'
    parent=args.checkpoint or (Path(json.loads(pointer.read_text())['checkpoint']) if pointer.exists() else None)
    state=load_checkpoint(parent) if parent else import_workbook(ROOT/'Integrated Neural Network Architecture.xlsx')
    engine_type = {'source-v8': SourceEngine, 'learned-v9': StabilizedSourceEngine}.get(state.get('engine_kind','source-v8'))
    if engine_type is None: parser.error('Use a source or learned checkpoint')
    if args.command=='bank' and args.value is None: parser.error('--value is required for bank')
    # Prevent a running source process from overwriting the control branch's continuation pointer.
    for lock in (ROOT/'runs').glob('*/source-active.json'):
        import ctypes
        pid=json.loads(lock.read_text())['pid']
        kernel=ctypes.windll.kernel32
        kernel.OpenProcess.restype=ctypes.c_void_p
        handle=kernel.OpenProcess(0x1000,False,pid)
        if handle:
            kernel.CloseHandle.argtypes=[ctypes.c_void_p]
            kernel.CloseHandle(handle)
            parser.error('Stop the source run with Ctrl+C before using bank/reset')
    output=ROOT/'runs'/('control-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    output.mkdir(parents=True)
    history_path=parent.parent/'training_log.jsonl' if parent else ROOT/'source_archive/training_history.jsonl'
    history=state.get('history')
    if history is None:
        history=read_history(history_path)
    with Farm(state) as farm:
        sim=Simulation(farm,engine_type(state['config'],state),state)
        first_row=sim.log_next
        if args.command=='reset':
            rows=sim.reset(history,args.seed)
        else:
            sim.set_bank(args.value)
            rows=[]
        with (output/'training_log.jsonl').open('w',encoding='utf-8') as stream:
            if args.command=='reset':
                # Keep the replay corpus with the branch so a second reset can replay it too.
                for index,row in enumerate(history,max(101,first_row-len(history))):
                    stream.write(json.dumps(dict(sheet_row=index,values=row))+'\n')
            elif history_path.exists():
                for index,row in enumerate(history,max(101,first_row-len(history))):
                    stream.write(json.dumps(dict(sheet_row=index,values=row))+'\n')
            for index,row in enumerate(rows,first_row):
                stream.write(json.dumps(dict(sheet_row=index,values=row))+'\n')
        destination=output/'checkpoint-final'
        checkpoint(sim,destination)
        temporary=pointer.with_suffix('.tmp')
        write_json(temporary,dict(checkpoint=str(destination),run=str(output),tick=sim.r['tick']))
        os.replace(temporary,pointer)
        write_json(output/'control.json',dict(command=args.command,value=args.value,parent=str(parent),
                   replayed=sim.replayed,run_id=sim.id))
        print(destination)


if __name__=='__main__': main()
