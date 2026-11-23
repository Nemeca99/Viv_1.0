# uml_engine.py
# Lorentz-Cognizant UML Engine v5: Full Higher-Order Projection Symmetry.

import math
import ast as _ast
import re
import sys
from dataclasses import dataclass, field

# Ensure Windows terminals never crash on UTF-8 symbols (π, φ, τ, →, °)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ==========================================
# SECTION 1: VARIABLES
# ==========================================
CONSTANTS = {
    'π': math.pi, 'pi': math.pi, 'φ': (1 + math.sqrt(5)) / 2, 'phi': (1 + math.sqrt(5)) / 2,
    'τ': 2 * math.pi, 'tau': 2 * math.pi, 'euler': math.e, 'c0': 299_792_458.0,
    'hP': 6.62607015e-34, 'Gc': 6.67430e-11, 'kB': 1.380649e-23, 'NA': 6.02214076e23,
    'me': 9.1093837015e-31, 'mp': 1.67262192369e-27, 'q0': 1.602176634e-19,
}
SESSION_VARS = {}
UPPER = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
LOWER = 'abcdefghijklmnopqrstuvwxyz'
FRACS = {'½':0.5, '⅓':1/3, '¼':0.25, '¾':0.75, '⅔':2/3}
UML_CL = {'[':']', '{':'}', '(':')', '>':"<", '<':'>'}
UML_OPS = {'[':'add', '{':'sub', '(':'neutral', '>':'mul', '<':'div'}
_TOK_STOP = set('[]{}<>(),^~!&|%\\?#')

# ==========================================
# SECTION 2: MAIN FUNCTIONS (The Engine)
# ==========================================
@dataclass
class Node:
    kind: str
    value: float = None
    name: str = None
    exp: float = None
    children: list = field(default_factory=list)
    strict: bool = False

def _c2v(c):
    if c in UPPER: return UPPER.index(c) + 1
    if c in LOWER: return LOWER.index(c) + 27
    raise ValueError(f"Not base-52: '{c}'")

def from_b52(s: str) -> int:
    neg = s.startswith('-'); s = s.lstrip('-')
    v = 0
    for c in s: v = v * 52 + _c2v(c)
    return -v if neg else v

def is_b52(s: str) -> bool:
    s = s.lstrip('-')
    return bool(s) and all(c in UPPER + LOWER for c in s)

def strip_comments(s: str) -> str:
    i = s.find('#')
    return (s[:i] if i >= 0 else s).strip()

def eval_node(n: Node):
    k = n.kind
    if k in ('num','var','const'): return n.value
    if k == 'sym':
        if n.strict and n.value == '!0':
            raise ValueError("Standard AST cannot evaluate Logic Space (!0)")
        return n.value
        
    # --- HIGHER-ORDER PROJECTIONS ---
    if k == 'neg': 
        v = eval_node(n.children[0])
        if v == '!0': return 0.0  # Origin mirror
        return -v
    if k == 'exp': 
        v = eval_node(n.children[0])
        if v == '!0': return 1.0 ** n.exp  # Multiplicative identity projection
        return v ** n.exp
    if k == 'factorial':
        v = eval_node(n.children[0])
        if v == '!0': return 1.0  # 0! = 1
        if v < 0 or v != int(v): raise ValueError("Factorial req non-neg int")
        return float(math.factorial(int(v)))
    if k == 'abs':
        v = eval_node(n.children[0])
        if v == '!0': return '!0'  # Magnitude of logic space remains logic space
        return abs(v)
    if k == 'log':
        base, val = eval_node(n.children[0]), eval_node(n.children[1])
        if base == '!0' and val == '!0': return 1.0  # log_x(x) = 1
        if base == '!0' or base == 1 or base == 1.0:
            if not n.strict:
                base = math.e  # Project logic/unity base to natural info (nats)
        if val == '!0' or (val == 0 and not n.strict):
            val = 1.0       # Project logic/floor value to multiplicative identity
        if base <= 0 or base == 1: raise ValueError("Invalid log base")
        if val <= 0: raise ValueError("Log non-positive")
        return math.log(val, base)
    if k == 'mod':
        a, b = eval_node(n.children[0]), eval_node(n.children[1])
        if a == '!0' and b == '!0': return 0.0  # x % x = 0
        if a == '!0': a = 0.0
        if b == '!0': b = 1.0
        if b == 0: raise ZeroDivisionError("Modulo by zero")
        return a % b
    if k == 'imagroot':
        v = eval_node(n.children[0])
        if v == '!0': return complex(0, 0.0)  # Project to spatial origin
        return complex(0, math.sqrt(abs(v)))
    
    vals = [eval_node(c) for c in n.children]
    
    # --- THE BOUNDED SPACE ALGEBRA & METRIC SIGNATURE TRANSITIONS ---
    if k == 'add': 
        if all(v == '!0' for v in vals): return '!0'
        numeric_vals = [v if v != '!0' else 0.0 for v in vals]
        return sum(numeric_vals)
        
    if k == 'sub': 
        if len(vals) == 2 and vals[0] == '!0' and vals[1] == '!0': return 0.0
        if len(vals) == 2:
            if vals[0] == '!0' and isinstance(vals[1], (int, float)):
                return 0.0 - float(vals[1])
            if isinstance(vals[0], (int, float)) and vals[1] == '!0':
                return float(vals[0]) - 0.0
        if any(v == '!0' for v in vals): return '!0'
        return vals[0] - sum(vals[1:])
        
    if k == 'mul': 
        if len(vals) == 2 and vals[0] == '!0' and vals[1] == '!0': return 1.0
        if all(v == '!0' for v in vals): return 1.0
        r = 1.0
        for v in vals:
            if v == '!0':
                v = 1.0
            if (r == 0 and math.isinf(v)) or (math.isinf(r) and v == 0):
                r = '!0'
                break
            r *= v
        return r
        
    if k == 'div':
        if n.strict:
            r = vals[0]
            for v in vals[1:]:
                if v == 0: raise ZeroDivisionError("Standard division by zero")
                r = r / v
            return r

        if len(vals) == 2 and vals[0] == '!0' and vals[1] == '!0': return 1.0
        
        if len(vals) == 2:
            if vals[0] == '!0' and isinstance(vals[1], (int, float)):
                if vals[1] == 0: return 0.0
                return 1.0 / float(vals[1])
            if isinstance(vals[0], (int, float)) and vals[1] == '!0':
                if vals[0] == 0: return 0.0
                return float(vals[0]) / 1.0
                
        r = vals[0]
        for v in vals[1:]:
            if r == '!0' and v == '!0':
                r = 1.0
            elif r == '!0' and isinstance(v, (int, float)):
                r = 0.0 if v == 0 else (1.0 / float(v))
            elif isinstance(r, (int, float)) and v == '!0':
                r = 0.0 if r == 0 else (float(r) / 1.0)
            elif r == '!0' or v == '!0':
                return '!0'
            elif v == 0:
                if r == 0: r = "!0"
                else: r = math.copysign(float('inf'), r)
            else: r = r / v
        return r
        
    if k == 'neutral': return vals[0] if len(vals) == 1 else sum(vals)
    raise ValueError(f"Unknown kind: {k}")

class UMLParser:
    def __init__(self, src: str):
        self.src = strip_comments(src).replace(' ', '')
        self.pos = 0; self.trace = []; self._d = 0

    def peek(self): return self.src[self.pos] if self.pos < len(self.src) else None
    def consume(self): c = self.src[self.pos]; self.pos += 1; return c
    def expect(self, ch):
        g = self.peek()
        if g != ch: raise SyntaxError(f"Expected '{ch}' got '{g}' at pos {self.pos}")
        self.consume()

    def parse(self) -> Node:
        node = self._expr()
        if self.pos != len(self.src): raise SyntaxError(f"Unexpected '{self.peek()}' at pos {self.pos}")
        return node

    def _expr(self) -> Node:
        c = self.peek()
        if c == '^': return self._exp_prefix()
        if c == '~': self.consume(); return Node('neg', children=[self._expr()])
        if c == '!':
            if self.pos + 1 < len(self.src) and self.src[self.pos + 1] == '0':
                self.consume(); self.consume()
                return Node('sym', name='!0', value='!0')
            return self._factorial()
        if c == '&': return self._log()
        if c == '|': return self._abs()
        if c == '%': return self._mod()
        if c == '\\': return self._imagroot()
        if c in '[{(<>': return self._bracket()
        return self._token()

    def _exp_prefix(self) -> Node:
        start = self.pos; self.consume(); s = ''
        if self.peek() == '[':
            self.consume()
            while self.peek() and self.peek() != ']': s += self.consume()
            self.expect(']')
        else:
            while self.peek() and self.peek() not in '[{(<>~^!&|%\\?': s += self.consume()
        node = Node('exp', exp=FRACS.get(s, float(s)), children=[self._expr()])
        self.trace.append((self._d, self.src[start:self.pos], eval_node(node))); return node

    def _factorial(self) -> Node:
        start = self.pos; self.consume(); node = Node('factorial', children=[self._expr()])
        self.trace.append((self._d, self.src[start:self.pos], eval_node(node))); return node

    def _abs(self) -> Node:
        start = self.pos; self.consume(); inner = self._expr()
        if self.peek() == '|': self.consume()
        node = Node('abs', children=[inner])
        self.trace.append((self._d, self.src[start:self.pos], eval_node(node))); return node

    def _log(self) -> Node:
        start = self.pos; self.consume(); self.expect('['); args = [self._expr()]
        while self.peek() == ',': self.consume(); args.append(self._expr())
        self.expect(']'); node = Node('log', children=args)
        self.trace.append((self._d, self.src[start:self.pos], eval_node(node))); return node

    def _mod(self) -> Node:
        start = self.pos; self.consume(); self.expect('['); args = [self._expr()]
        while self.peek() == ',': self.consume(); args.append(self._expr())
        self.expect(']'); node = Node('mod', children=args)
        self.trace.append((self._d, self.src[start:self.pos], eval_node(node))); return node

    def _imagroot(self) -> Node:
        start = self.pos; self.consume()
        if self.peek() != '/': raise SyntaxError("use \\/[n]")
        self.consume(); node = Node('imagroot', children=[self._expr()])
        self.trace.append((self._d, self.src[start:self.pos], eval_node(node))); return node

    def _bracket(self) -> Node:
        start = self.pos; op_ch = self.consume(); cl_ch = UML_CL[op_ch]; kind = UML_OPS[op_ch]
        self._d += 1; children = []
        # Note: '<' is both an opening bracket (div) and closing bracket for '>' (mul),
        # and '>' is both an opening bracket (mul) and closing bracket for '<' (div).
        next_ch = self.src[self.pos + 1] if self.pos + 1 < len(self.src) else None
        is_nested_angle = (op_ch in ('<', '>') and self.peek() == cl_ch and next_ch is not None and next_ch not in (',', ']', '}', ')'))
        if self.peek() == cl_ch and not is_nested_angle:
            raise SyntaxError(f"Empty {op_ch}{cl_ch}")
        children.append(self._expr())
        while self.peek() == ',':
            self.consume(); children.append(self._expr())
        self.expect(cl_ch); node = Node(kind, children=children)
        self.trace.append((self._d, self.src[start:self.pos], eval_node(node))); self._d -= 1; return node

    def _token(self) -> Node:
        s = ''
        if self.peek() == '-': s += self.consume()
        if self.peek() == '?': s += self.consume()
        
        while self.peek() and self.peek() not in _TOK_STOP: s += self.consume()
        s = s.strip()
        if not s: raise SyntaxError(f"Empty token at {self.pos}")
        
        base = s.lstrip('-'); neg = s.startswith('-')
            
        if base.startswith('?'):
            if base not in SESSION_VARS: raise NameError(f"Undefined var '{base}'")
            v = SESSION_VARS[base]; return Node('var', name=base, value=(-v if neg else v))
        if base in CONSTANTS:
            v = CONSTANTS[base]; return Node('const', name=base, value=(-v if neg else v))
        if is_b52(base): return Node('num', value=float(-from_b52(base) if neg else from_b52(base)))
        try: return Node('num', value=float(s))
        except ValueError: raise ValueError(f"Cannot parse '{s}'")

# ==========================================
# SECTION 3: SUB-MAIN (Validation & Formatting)
# ==========================================
def std_parse(expr: str) -> Node:
    e = strip_comments(expr)
    e = e.replace("!0", "LOGIC_ZERO")
    
    for name, val in SESSION_VARS.items(): e = e.replace(name, str(val))
    for name, val in sorted(CONSTANTS.items(), key=lambda x: -len(x[0])):
        e = re.sub(r'(?<![A-Za-z0-9_])' + re.escape(name) + r'(?![A-Za-z0-9_])', str(val), e)
    e = e.replace('^', '**')
    try: tree = _ast.parse(e, mode='eval')
    except SyntaxError as ex: raise SyntaxError(f"Standard error: {ex}")
    return _ast2node(tree.body)

def _ast2node(n) -> Node:
    if isinstance(n, _ast.Constant): return Node('num', value=float(n.value), strict=True)
    if isinstance(n, _ast.Name):
        if n.id == "LOGIC_ZERO": return Node('sym', name='!0', value='!0', strict=True)
        if n.id in CONSTANTS: return Node('const', name=n.id, value=CONSTANTS[n.id], strict=True)
        if n.id in SESSION_VARS: return Node('var', name=n.id, value=SESSION_VARS[n.id], strict=True)
        raise NameError(f"Unknown name: '{n.id}'")
    if isinstance(n, _ast.UnaryOp) and isinstance(n.op, _ast.USub):
        return Node('neg', children=[_ast2node(n.operand)], strict=True)
    if isinstance(n, _ast.BinOp):
        L, R = _ast2node(n.left), _ast2node(n.right)
        op = n.op
        if isinstance(op, _ast.Add): return Node('add', children=[L,R], strict=True)
        if isinstance(op, _ast.Sub): return Node('sub', children=[L,R], strict=True)
        if isinstance(op, _ast.Mult): return Node('mul', children=[L,R], strict=True)
        if isinstance(op, _ast.Div): return Node('div', children=[L,R], strict=True)
        if isinstance(op, _ast.Mod): return Node('mod', children=[L,R], strict=True)
        if isinstance(op, _ast.Pow): return Node('exp', exp=eval_node(R), children=[L], strict=True)
    raise ValueError("Unsupported standard AST node")

def to_uml(n: Node) -> str:
    k = n.kind
    if k == 'num':
        v = n.value
        return str(int(v)) if v == int(v) and abs(v) < 1e15 else f"{v:.8g}"
    if k in ('var','const', 'sym'): return n.name if n.name else str(n.value)
    if k == 'neg': return f'~{to_uml(n.children[0])}'
    if k == 'factorial': return f'!{to_uml(n.children[0])}'
    if k == 'abs': return f'|{to_uml(n.children[0])}|'
    if k == 'log': return f'&[{to_uml(n.children[0])},{to_uml(n.children[1])}]'
    if k == 'mod': return f'%[{to_uml(n.children[0])},{to_uml(n.children[1])}]'
    if k == 'imagroot': return f'\\/[{to_uml(n.children[0])}]'
    if k == 'exp':
        es = str(int(n.exp) if n.exp==int(n.exp) else n.exp)
        inner = to_uml(n.children[0])
        if n.children[0].kind in ('num','var','const','neg','exp','factorial','abs', 'sym'): inner = f'[{inner}]'
        return f'^{es}{inner}'
    op_map = {'add':('[',']'),'sub':('{','}'),'mul':('>','<'),'div':('<','>'),'neutral':('(',')')}
    op, cl = op_map[k]
    return op + ','.join(to_uml(c) for c in n.children) + cl

def to_std(n: Node, pp: int = 0) -> str:
    k = n.kind
    if k == 'num':
        v = n.value
        return str(int(v)) if v == int(v) and abs(v) < 1e15 else f"{v:.8g}"
    if k in ('var','const'): return n.name if n.name else str(n.value)
    if k == 'sym': return "LOGIC_ZERO"
    if k == 'neg': return f'-{to_std(n.children[0], 4)}'
    if k == 'neutral': return to_std(n.children[0])
    if k == 'factorial': return f'factorial({to_std(n.children[0])})'
    if k == 'abs': return f'abs({to_std(n.children[0])})'
    if k == 'log': return f'log({to_std(n.children[0])},{to_std(n.children[1])})'
    if k == 'mod': return f'{to_std(n.children[0], 2)} % {to_std(n.children[1], 3)}'
    if k == 'imagroot': return f'sqrt(-({to_std(n.children[0])}))'
    if k == 'exp': return f'{to_std(n.children[0], 3)}^{n.exp}'
    prec = {'add':1, 'sub':1, 'mul':2, 'div':2}
    mp = prec.get(k, 0)
    if k == 'add': s = ' + '.join(to_std(c,mp) for c in n.children)
    elif k == 'sub': s = to_std(n.children[0],mp) + ' - ' + ' - '.join(to_std(c,mp+1) for c in n.children[1:])
    elif k == 'mul': s = ' * '.join(to_std(c,mp) for c in n.children)
    elif k == 'div': s = to_std(n.children[0],mp) + ' / ' + ' / '.join(to_std(c,mp+1) for c in n.children[1:])
    return f'({s})' if pp > mp else s

def detect(expr: str) -> str:
    e = strip_comments(expr).strip()
    if not e: return 'empty'
    if e == '!0': return 'uml'
    if re.match(r'^-?\d+(\.\d+)?$', e): return 'standard'
    if any(c in e for c in '[{'): return 'uml'
    if e and e[0] in '>^~!&|%\\': return 'uml'
    if e.startswith('<') and '>' in e: return 'uml'
    if re.search(r'(?:abs|log|sqrt|factorial|fact)\s*\(', e): return 'standard'
    if re.search(r'[)\]\d]\s*\^', e): return 'standard'
    if '**' in e: return 'standard'
    if any(op in e for op in ['+','-','*','/']): return 'standard'
    return 'uml'

def parse_only(expr: str) -> Node:
    notation = detect(expr)
    if notation == 'uml':
        return UMLParser(expr).parse()
    return std_parse(expr)

def evaluate(expr: str):
    notation = detect(expr)
    trace = []
    if notation == 'uml':
        p = UMLParser(expr); node = p.parse(); trace = p.trace
    else: node = std_parse(expr)
    return eval_node(node), node, notation, trace

def _approx_eq(a, b, tol=1e-9):
    an = isinstance(a, float) and a != a; bn = isinstance(b, float) and b != b
    if an or bn: return an and bn
    if isinstance(a, str) or isinstance(b, str): return a == b
    try: a = complex(a); b = complex(b)
    except Exception: return a == b
    if math.isinf(a.real) or math.isinf(a.imag) or math.isinf(b.real) or math.isinf(b.imag): return a == b
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))

def dual_eval_from_node(node: Node) -> dict:
    out = {}
    try:
        uform = to_uml(node)
        uml_val = eval_node(UMLParser(uform).parse())
        out['uml_val'] = uml_val
    except Exception as ex: out['uml_err'] = str(ex)

    try:
        sform = to_std(node)
        std_val = eval_node(std_parse(sform))
        out['std_val'] = std_val
    except Exception as ex: out['std_err'] = str(ex)

    if 'uml_val' in out and 'std_val' in out:
        if _approx_eq(out['uml_val'], out['std_val']):
            return {**out, 'agree': True, 'report': f"agree: {fmt(out['uml_val'])}"}
        return {**out, 'agree': False, 'report': f"DISAGREE uml={fmt(out['uml_val'])} std={fmt(out['std_val'])}"}
    if 'uml_err' in out and 'std_err' in out:
        return {**out, 'agree': True, 'report': f"both reject"}
    if 'uml_err' in out:
        return {**out, 'agree': False, 'report': f"AST succeeded ({fmt(out['std_val'])}) but UML rejected: {out['uml_err']}"}
    return {**out, 'agree': False, 'report': f"UML succeeded ({fmt(out['uml_val'])}) but AST rejected: {out['std_err']}"}

def fmt(v) -> str:
    if isinstance(v, str): return v
    if isinstance(v, complex):
        r = v.real; i = v.imag
        rs = str(int(r)) if r == int(r) else f"{r:.8g}"
        is_ = str(int(abs(i))) if abs(i) == int(abs(i)) else f"{abs(i):.8g}"
        if r == 0: return f"{is_}i"
        return f"{rs} + {is_}i" if i >= 0 else f"{rs} - {is_}i"
    if isinstance(v, float):
        if v != v: return "undefined"
        if v == float('inf'): return "inf"
        if v == float('-inf'): return "-inf"
    if v == int(v) and abs(v) < 1e15: return str(int(v))
    return f"{v:.8g}"
