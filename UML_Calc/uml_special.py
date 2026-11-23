# uml_special.py
# The Gearbox: Preprocessor for the UML Calculator.
# Translates mixed notation, handles aliases, and compresses raw text into base-52 UML arrays.

import re

# ==========================================
# SECTION 1: VARIABLES & ALIASES
# ==========================================
ALIASES = {
    "0~": "!0",
    "lz": "!0",
    "LZ": "!0",
    "letter_zero": "!0",
}

OPERATOR_MAP = {
    "/": "<{},{}>",   # Division
    "*": ">{},{}<",   # Multiplication
    "+": "[{},{}]",   # Addition
    "-": "{{{},{}}}", # Subtraction
}

TOKEN_PATTERN = r'(!0|-?\d+(?:\.\d+)?)'

UPPER = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
LOWER = 'abcdefghijklmnopqrstuvwxyz'

# ==========================================
# SECTION 2: BASE-52 LOGOGRAPHIC PIPELINE
# ==========================================
def _c2v(c):
    if c in UPPER: return UPPER.index(c) + 1
    if c in LOWER: return LOWER.index(c) + 27
    raise ValueError(f"Not base-52: '{c}'")

def _v2c(v):
    if 1 <= v <= 26: return UPPER[v - 1]
    if 27 <= v <= 52: return LOWER[v - 27]
    raise ValueError(f"Out of base-52 bounds: {v}")

def text_to_b52_int(s: str) -> int:
    """Converts a continuous string of letters into a single base-52 integer."""
    if not s.isalpha():
        raise ValueError(f"String '{s}' contains non-base-52 characters.")
    v = 0
    for c in s:
        v = v * 52 + _c2v(c)
    return v

def b52_int_to_text(v: int) -> str:
    """Reverses a base-52 integer back into a logographic string."""
    if v == 0: return ""
    v = int(abs(v))
    s = ""
    while v > 0:
        rem = (v - 1) % 52 + 1
        s = _v2c(rem) + s
        v = (v - rem) // 52
    return s

def compress_text(text: str) -> str:
    """
    Translates a raw sentence into a UML structural math array.
    Example: 'Romeo and Juliet' -> '[Romeo,and,Juliet]'
    """
    words = ''.join(c if c.isalpha() else ' ' for c in text).split()
    if not words: return text
    if len(words) == 1: return words[0]
    return "[" + ",".join(words) + "]"

# ==========================================
# SECTION 3: CORE ROUTING & TRANSLATION
# ==========================================
def normalize(s: str) -> str:
    for alias, canonical in ALIASES.items():
        s = s.replace(alias, canonical)
    return s

def translate_mixed(s: str):
    for op, template in OPERATOR_MAP.items():
        pattern = rf'^\s*{TOKEN_PATTERN}\s*{re.escape(op)}\s*{TOKEN_PATTERN}\s*$'
        m = re.match(pattern, s)
        if m:
            a, b = m.group(1), m.group(2)
            if a == "!0" or b == "!0":
                return template.format(a, b)
    # Compound standard expressions containing !0 -> convert via AST to UML
    if "!0" in s and any(op in s for op in ('+', '-', '*', '/', '^')) and not any(c in s for c in '[{<>'):
        try:
            import uml_engine
            node = uml_engine.std_parse(s)
            return uml_engine.to_uml(node)
        except Exception:
            pass
    return None

def process(input_str: str):
    """
    Main entry point. 
    Routes aliases, mixed math, and raw text compression.
    Returns: (translated_input: str, was_translated: bool)
    """
    s = normalize(input_str.strip())
    if not s:
        return (input_str, False)
    
    # 1. Check for standard-to-UML math translation
    translated = translate_mixed(s)
    if translated:
        return (translated, True)
        
    # 2. Check for logographic text compression (contains letters, no math/UML ops)
    if re.search(r'[A-Za-z]', s) and not any(op in s for op in '[{<>&|\\^~+*/-]') and s != '!0':
        compressed = compress_text(s)
        if compressed != s:
            return (compressed, True)
    
    # 3. Fallback check for alias expansion
    if s != input_str.strip():
        return (s, True)
    
    return (s, False)

# ==========================================
# SECTION 4: SUB-MAIN (Standalone Tests)
# ==========================================
if __name__ == "__main__":
    import uml_engine 
    
    print("=========================================================")
    print("  THE VOID PROOF: STANDARD MATH vs UML LOGIC SPACE")
    print("=========================================================")
    
    equations = [
        ("The Base Paradox", "0 / 0", "<!0, !0>"),
        ("Addition of the Void", "(0 / 0) + 5", "[<!0, !0>, 5]"),
        ("The Identity Cancellation", "(0 / 0) / (0 / 0)", "<<!0, !0>, <!0, !0>>"),
        ("Scaling the Void", "5 * (0 / 0)", ">5, <!0, !0><"),
        ("Subtracting Reality", "10 - (0 / 0)", "{10, <!0, !0>}"),
    ]

    for name, std_eq, uml_eq in equations:
        print(f"\n--- {name} ---")
        print(f"  Standard: {std_eq}")
        try:
            node = uml_engine.std_parse(std_eq)
            result = uml_engine.eval_node(node)
            print(f"    Result: {uml_engine.fmt(result)}")
        except Exception as e:
            print(f"    REJECTED: {type(e).__name__}")
            
        print(f"  UML:      {uml_eq}")
        try:
            result, node, nota, trace = uml_engine.evaluate(uml_eq)
            print(f"    Result: {uml_engine.fmt(result)}")
        except Exception as e:
            print(f"    REJECTED: {type(e).__name__}")

    print("\n=========================================================")
    print("  LOGOGRAPHIC BASE-52 PIPELINE PROOF")
    print("=========================================================")
    
    # Test sentence compression routing
    test_sentence = "Romeo and Juliet"
    processed, was_translated = process(test_sentence)
    
    print(f"  Raw Input:       '{test_sentence}'")
    print(f"  UML Output:      {processed}")
    print(f"  Routed:          {was_translated}")
    
    if processed != test_sentence:
        try:
            val, _, _, _ = uml_engine.evaluate(processed)
            print(f"  Engine Eval:     {uml_engine.fmt(val)}")
        except Exception as e:
            print(f"  Engine Error:    {e}")
            
    print("=========================================================")
