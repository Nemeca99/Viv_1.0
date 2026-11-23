import argparse
import json
from pathlib import Path
from inn.sheet_engine import SheetEngine

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Execute the original INN workbook architecture in Python')
    parser.add_argument('--inputs', type=Path, help='JSON mapping such as {"Pesonal!B1": 0}')
    parser.add_argument('--output', type=Path, default=Path('architecture-results.json'))
    args = parser.parse_args()
    inputs = json.loads(args.inputs.read_text()) if args.inputs else {}
    engine = SheetEngine(overrides=inputs)
    results = engine.calculate()
    args.output.write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
    print(f'Calculated {len(results)} architecture tabs: {args.output}')
