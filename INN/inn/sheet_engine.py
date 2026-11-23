"""Execute the supplied workbook's formula graph in Python, without Excel/Sheets.

No Python eval, cached-result substitution, or inferred connections between tabs.
The cached workbook values are used only by the independent comparison command.
"""
import math
import operator
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import openpyxl
from openpyxl.formula import Tokenizer
from openpyxl.utils.cell import range_boundaries, get_column_letter


def flatten(value):
    if isinstance(value, list):
        return [x for row in value for x in flatten(row)]
    return [value]


def mapped(fn, value):
    return [mapped(fn, x) for x in value] if isinstance(value, list) else fn(value)


def number(value):
    return 0 if value is None or value == '' else float(value)


def binary(fn, a, b):
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            raise ValueError('Array shape mismatch')
        return [binary(fn, x, y) for x, y in zip(a, b)]
    if isinstance(a, list):
        return [binary(fn, x, b) for x in a]
    if isinstance(b, list):
        return [binary(fn, a, y) for y in b]
    return fn(a, b)


class Formula:
    precedence = {'=': 1, '<>': 1, '<': 1, '>': 1, '<=': 1, '>=': 1,
                  '&': 2, '+': 3, '-': 3, '*': 4, '/': 4, '^': 5}

    def __init__(self, text):
        self.tokens = [t for t in Tokenizer(text if text.startswith('=') else '=' + text).items if t.type != 'WHITE-SPACE']
        self.i = 0
        self.tree = self.expression()
        if self.i != len(self.tokens):
            raise ValueError(f'Unparsed formula: {text}')

    def expression(self, minimum=0):
        token = self.tokens[self.i]
        self.i += 1
        if token.type == 'OPERATOR-PREFIX':
            node = ('unary', token.value, self.expression(5))
        elif token.subtype == 'OPEN':
            if token.type == 'FUNC':
                args = []
                while self.tokens[self.i].subtype != 'CLOSE':
                    args.append(self.expression())
                    if self.tokens[self.i].type == 'SEP':
                        self.i += 1
                    else:
                        break
                node = ('call', token.value[:-1].upper(), args)
            else:
                node = self.expression()
            if self.tokens[self.i].subtype != 'CLOSE':
                raise ValueError('Missing closing parenthesis')
            self.i += 1
        elif token.subtype == 'NUMBER':
            node = ('value', float(token.value))
        elif token.subtype == 'TEXT':
            node = ('value', token.value[1:-1].replace('""', '"'))
        elif token.subtype == 'LOGICAL':
            node = ('value', token.value.upper() == 'TRUE')
        elif token.subtype == 'RANGE':
            node = ('ref', token.value)
        else:
            raise ValueError(f'Unsupported token: {token}')
        while self.i < len(self.tokens):
            token = self.tokens[self.i]
            if token.type == 'OPERATOR-POSTFIX':
                self.i += 1
                node = ('binary', '/', node, ('value', 100.))
                continue
            if token.type != 'OPERATOR-INFIX' or self.precedence.get(token.value, -1) < minimum:
                break
            self.i += 1
            node = ('binary', token.value, node, self.expression(self.precedence[token.value] + 1))
        return node


class SheetEngine:
    def __init__(self, workbook=None, overrides=None):
        workbook = workbook or Path(__file__).resolve().parents[1] / 'Integrated Neural Network Architecture.xlsx'
        formulas = openpyxl.load_workbook(workbook, read_only=True, data_only=False)
        cached = openpyxl.load_workbook(workbook, read_only=True, data_only=True)
        self.cells, self.cached = {}, {}
        self.tabs = formulas.sheetnames[:7]
        for name in self.tabs:
            for row in formulas[name]:
                for cell in row:
                    if cell.value is not None:
                        self.cells[(name, cell.coordinate)] = getattr(cell.value, 'text', cell.value)
            for row in cached[name]:
                for cell in row:
                    if cell.value is not None:
                        self.cached[(name, cell.coordinate)] = cell.value
        formulas.close()
        cached.close()
        self.overrides = {}
        for name, value in (overrides or {}).items():
            sheet, address = name.rsplit('!', 1)
            self.overrides[(sheet, address.replace('$', '').upper())] = value
        self.results, self.parsed, self.visiting = {}, {}, set()

    def cell(self, sheet, address):
        key = (sheet, address.replace('$', '').upper())
        if key in self.overrides:
            return self.overrides[key]
        if key in self.results:
            return self.results[key]
        if key in self.visiting:
            raise ValueError(f'Circular formula: {key}')
        raw = self.cells.get(key, '')
        self.visiting.add(key)
        try:
            result = self.expression(raw, sheet) if isinstance(raw, str) and raw.startswith('=') else raw
            self.results[key] = result
            return result
        finally:
            self.visiting.remove(key)

    def expression(self, text, sheet, variables=None):
        if text not in self.parsed:
            self.parsed[text] = Formula(text).tree
        return self.evaluate(self.parsed[text], sheet, variables or {})

    def evaluate(self, node, sheet, variables):
        kind = node[0]
        ev = lambda n: self.evaluate(n, sheet, variables)
        if kind == 'value':
            return node[1]
        if kind == 'ref':
            ref = node[1].replace('$', '')
            if ref.lower() in variables:
                return variables[ref.lower()]
            if '!' in ref:
                sheet, ref = ref.rsplit('!', 1)
                sheet = sheet.strip("'").replace("''", "'")
            if ':' not in ref:
                if not re.fullmatch('[A-Za-z]+[0-9]+', ref):
                    raise ValueError(f'Unknown name: {ref}')
                return self.cell(sheet, ref)
            left, top, right, bottom = range_boundaries(ref)
            return [[self.cell(sheet, f'{get_column_letter(c)}{r}') for c in range(left, right+1)] for r in range(top, bottom+1)]
        if kind == 'unary':
            return mapped(lambda x: number(x) * (-1 if node[1] == '-' else 1), ev(node[2]))
        if kind == 'binary':
            ops = {'+': lambda a,b:number(a)+number(b), '-':lambda a,b:number(a)-number(b),
                   '*':lambda a,b:number(a)*number(b), '/':lambda a,b:number(a)/number(b),
                   '^':lambda a,b:number(a)**number(b), '&':lambda a,b:str(a)+str(b),
                   '=':operator.eq, '<>':operator.ne, '<':operator.lt, '>':operator.gt,
                   '<=':operator.le, '>=':operator.ge}
            return binary(ops[node[1]], ev(node[2]), ev(node[3]))
        name, args = node[1:]
        if name == 'IF':
            return ev(args[1]) if ev(args[0]) else ev(args[2]) if len(args)>2 else False
        if name == 'IFERROR':
            try:
                return ev(args[0])
            except (ValueError, TypeError, ZeroDivisionError, IndexError, OverflowError):
                return ev(args[1])
        if name == 'ISNUMBER':
            try:
                value = ev(args[0])
                return isinstance(value, (int,float)) and not isinstance(value,bool)
            except (ValueError, TypeError):
                return False
        if name == 'LET':
            scope = dict(variables)
            for i in range(0,len(args)-1,2):
                scope[args[i][1].lower()] = self.evaluate(args[i+1], sheet, scope)
            return self.evaluate(args[-1], sheet, scope)
        values = [ev(a) for a in args]
        nums = [float(v) for v in flatten(values) if isinstance(v,(int,float)) and not isinstance(v,bool)]
        if name == '__XLUDF.DUMMYFUNCTION':
            text = values[0]
            if text.upper().startswith('SPARKLINE('):
                return ''  # Chart rendering has no numeric output.
            return self.expression(text, sheet, variables)
        if name == 'SUM': return sum(nums)
        if name == 'MINUS': return number(values[0])-number(values[1])
        if name == 'PRODUCT': return math.prod(nums)
        if name == 'SUMSQ': return sum(x*x for x in nums)
        if name == 'AVERAGE': return sum(nums)/len(nums)
        if name == 'VARP': return sum((x-sum(nums)/len(nums))**2 for x in nums)/len(nums)
        if name == 'COUNT': return len(nums)
        if name == 'COUNTA': return sum(v not in ('',None) for v in flatten(values))
        if name == 'MAX': return max(nums)
        if name == 'MIN': return min(nums)
        if name == 'AND': return all(flatten(values))
        if name == 'PI': return math.pi
        if name in ('EXP','SQRT','LN','COS'):
            fn = {'EXP':math.exp,'SQRT':math.sqrt,'LN':math.log,'COS':math.cos}[name]
            return mapped(lambda x:fn(number(x)),values[0])
        if name == 'ROUND':
            value, digits = values
            return float(Decimal(format(value,'.15g')).quantize(Decimal(1).scaleb(-int(digits)),rounding=ROUND_HALF_UP))
        if name == 'SUMPRODUCT':
            arrays = [flatten(v) for v in values]
            if len({len(v) for v in arrays}) != 1: raise ValueError('SUMPRODUCT size mismatch')
            return sum(math.prod(number(x) for x in row) for row in zip(*arrays))
        if name == 'RANK':
            value, array = values[:2]
            return 1+sum(x<value if len(values)>2 and values[2] else x>value for x in flatten(array))
        if name == 'TEXT':
            value, fmt = values
            digits = len(fmt.split('.',1)[1].rstrip('%')) if '.' in fmt else 0
            decimal=Decimal(format(value*100 if '%' in fmt else value,'.15g')).quantize(Decimal(1).scaleb(-digits),rounding=ROUND_HALF_UP)
            return f'{decimal:.{digits}f}' + ('%' if '%' in fmt else '')
        if name == 'COUNTIF':
            array, criterion = values
            match = re.fullmatch(r'(>=|<=|<>|>|<|=)?(-?[0-9.]+)',str(criterion))
            if match:
                op, value = match.groups()
                fn = {'>':operator.gt,'<':operator.lt,'>=':operator.ge,'<=':operator.le,'<>':operator.ne,'=':operator.eq}[op or '=']
                return sum(fn(number(x),float(value)) for x in flatten(array))
            return sum(str(x).lower()==str(criterion).lower() for x in flatten(array))
        if name == 'VLOOKUP':
            key, table, column = values[:3]
            for row in table:
                if str(row[0]).lower() == str(key).lower(): return row[int(column)-1]
            raise ValueError(f'Lookup missing: {key}')
        if name == 'MATCH':
            key, array = values[:2]
            for i, item in enumerate(flatten(array),1):
                if item == key: return i
            raise ValueError(f'Match missing: {key}')
        if name == 'INDEX':
            array, row = values[:2]
            return array[int(row)-1][int(values[2])-1 if len(values)>2 else 0]
        if name == 'LEN': return mapped(lambda x:len(str(x)),values[0])
        if name == 'SEARCH': return str(values[1]).lower().index(str(values[0]).lower())+1
        if name == 'SPLIT': return [str(values[0]).split(str(values[1]))]
        if name == 'SUBSTITUTE': return str(values[0]).replace(str(values[1]),str(values[2]))
        if name == 'REGEXREPLACE': return mapped(lambda x:re.sub(values[1],values[2],str(x)),values[0])
        if name == 'ARRAYFORMULA': return values[0]
        if name == 'UNIQUE':
            return [list(row) for row in dict.fromkeys(tuple(row) for row in values[0])]
        raise ValueError(f'Unsupported function: {name}')

    def calculate(self):
        return {sheet:{address:self.cell(sheet,address) for s,address in self.cells if s==sheet} for sheet in self.tabs}
