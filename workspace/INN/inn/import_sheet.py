"""Read the local XLSX export using only the standard library."""
import hashlib
import json
import math
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .engine import DEFAULT_CONFIG

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}


def import_workbook(path, archive=None):
    path = Path(path)
    with zipfile.ZipFile(path) as z:
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            strings = [''.join(s.itertext()) for s in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        rels = {r.attrib['Id']: r.attrib['Target'] for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        sheets = ET.fromstring(z.read('xl/workbook.xml')).find('m:sheets', NS)
        cells = {}
        formulas = {}
        for sheet in sheets:
            target = rels[sheet.attrib['{' + NS['r'] + '}id']]
            filename = target.lstrip('/') if target.startswith('/') else 'xl/' + target
            tab = {}
            for cell in ET.fromstring(z.read(filename)).iterfind('.//m:c', NS):
                if cell.find('m:f', NS) is not None:
                    formulas[(sheet.attrib['name'],cell.attrib['r'])] = True
                value = cell.find('m:v', NS)
                if cell.attrib.get('t') == 'inlineStr':
                    value = ''.join(cell.find('m:is', NS).itertext())
                elif value is not None:
                    value = strings[int(value.text)] if cell.attrib.get('t') == 's' else value.text
                else:
                    continue
                tab[cell.attrib['r']] = value
            cells[sheet.attrib['name']] = tab
    tab = cells['_Farming_v8_State']
    if tab.get('A1') != '8-outcomes':
        raise ValueError('Expected V8 outcome checkpoint')
    count, checksum = tab['B1'].split('|')
    text = ''.join(tab[f'B{i+2}'] for i in range(int(count)))
    # Apps Script hashes UTF-16 code units, rather than UTF-8 bytes.
    h = 2166136261
    units = text.encode('utf-16-le')
    for i in range(0, len(units), 2):
        h = ((h ^ int.from_bytes(units[i:i+2], 'little')) * 16777619) & 0xffffffff
    if str(h) != checksum:
        raise ValueError('Source sheet checkpoint checksum mismatch')
    state = json.loads(text)
    # load8 refreshes settings from the Farming controls after loading its checkpoint.
    config = dict(DEFAULT_CONFIG)
    controls = dict(tickMs=5,tills=6,tillDecay=7,seedDecay=8,waterDecay=9,
                    harvestDuration=10,alpha=13,gamma=14,epsilonStart=15,
                    epsilonDecay=16,epsilonMin=17,threshold=18,surface=19,dk=22)
    for name,row in controls.items():
        value = cells['Farming'].get(f'B{row}', '')
        try: value = float(value) if value not in ('',None) else config[name]
        except (TypeError,ValueError): value = config[name]
        config[name] = value if math.isfinite(value) else config[name]
    volume = cells['Farming'].get('B20',3)
    try: volume = float(volume) if volume not in ('',None) else 3
    except (TypeError,ValueError): volume = 3
    config['volumeFixed'] = None if ('Farming','B20') in formulas else (volume if math.isfinite(volume) else 3)
    if not (config['tickMs']>=1000 and config['tills']==3 and config['dk']==5):
        raise ValueError('Required: tickMs >= 1000, tills = 3, dk = 5')
    if not all(config[k]>=1 and int(config[k])==config[k] for k in ('tillDecay','seedDecay','waterDecay','harvestDuration')):
        raise ValueError('Timers must be positive integer ticks')
    if not (0<config['alpha']<=1 and 0<=config['gamma']<1 and 0<=config['threshold']<=1
            and 0<=config['epsilonMin']<=config['epsilonStart']<=1 and 0<config['epsilonDecay']<=1
            and config['surface']>0 and (config['volumeFixed'] is None or config['volumeFixed']>0)):
        raise ValueError('Invalid training configuration')
    for name in ('tickMs','tills','tillDecay','seedDecay','waterDecay','harvestDuration','dk'):
        if int(config[name])==config[name]: config[name]=int(config[name])
    state['config'] = config
    logs = cells['Training_Logs']
    def column(index):
        return chr(64+index) if index <= 26 else 'A' + chr(64+index-26)
    row_numbers = sorted({int(''.join(filter(str.isdigit, key))) for key in logs})
    history = []
    for row in [r for r in row_numbers if r >= 101][-2048:]:
        values = [logs.get(f'{column(i)}{row}', '') for i in range(1,32)]
        if values[22] == 'TRANSITION' and values[23] == '8-outcomes':
            for index in [1,3,4,*range(6,22),25,26,27,28,29]:
                if isinstance(values[index],str) and values[index]:
                    values[index] = float(values[index])
        history.append(values)
    state['history'] = history
    state['source'] = dict(path=str(path.resolve()), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                           checkpoint_checksum=checksum, tabs=list(cells))
    if archive is not None:
        archive = Path(archive)
        archive.mkdir(parents=True, exist_ok=False)
        (archive / 'source_state.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
        logs = cells['Training_Logs']
        row_numbers = sorted({int(''.join(filter(str.isdigit, key))) for key in logs})
        def column(index):
            return chr(64+index) if index <= 26 else 'A' + chr(64+index-26)
        records = 0
        with (archive / 'training_history.jsonl').open('w', encoding='utf-8') as output:
            for row in row_numbers:
                if row >= 100:
                    values = [logs.get(f'{column(i)}{row}', '') for i in range(1, 32)]
                    output.write(json.dumps(dict(sheet_row=row, values=values)) + '\n')
                    records += 1
        files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in archive.iterdir()}
        (archive / 'manifest.json').write_text(json.dumps(dict(source=state['source'],
                 files=files, history_rows=records), indent=2), encoding='utf-8')
    return state
