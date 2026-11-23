from pathlib import Path
from inn.import_sheet import import_workbook

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    state = import_workbook(root / 'Integrated Neural Network Architecture.xlsx', root / 'source_archive')
    print(f"Imported {state['id']} at tick {state['r']['tick']} into source_archive")
