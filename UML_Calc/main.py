import sys
import time
import random
import uml_engine
import uml_telemetry
import uml_chaos
import uml_special

# ==========================================
# SUB-MAIN: THE HARDWARE DEMO
# ==========================================
def run_hardware_demo(slides=5, delay=3):
    print("\n" + "=" * 42)
    print(f"  HARDWARE RANDOM DEMO ({slides} slides)")
    print("=" * 42)
    sab = uml_chaos.Saboteur(threads=4, intensity=0.8); sab.start()
    try:
        for slide in range(1, slides + 1):
            time.sleep(delay)
            m = uml_telemetry.get_all_metrics()
            pool = [max(1.0, round(m['cpu_temp'], 2)), max(1.0, round(m['ram_pct'], 2)), 
                    max(1.0, round(m['clock_ratio'] * 100, 2)), max(1.0, float(random.randint(10, 500)))]
            op = random.choice(['add', 'mul', 'sub', 'div', 'exp', 'log'])
            a = random.choice(pool); b = random.choice(pool)
            
            if op == 'add': expr = f"[{a},{b}]"
            elif op == 'sub': expr = f"{{{a},{b}}}"
            elif op == 'mul': expr = f">{a},{b}<"
            elif op == 'div': expr = f"<{a},{b}>"
            elif op == 'exp': expr = f"^2[{a}]"
            else: expr = f"&[{max(2.0, a)},{b}]"

            print(f"\n  -- {slide} of {slides} --")
            print(f"  Hardware: {m['cpu_temp']:.1f}C | RAM {m['ram_pct']:.1f}%")
            print(f"  UML:      {expr}")
            try:
                result, node, nota, trace = uml_engine.evaluate(expr)
                print(f"  Result:   {uml_engine.fmt(result)}")
                for d, sub, val in trace: print(f"    d{d} {sub:<20} = {uml_engine.fmt(val)}")
            except Exception as e: print(f"  MATH ERROR: {e}")
    except KeyboardInterrupt: print("\n  [stopped]")
    finally:
        sab.stop(); print("\n  Demo complete.\n")

# ==========================================
# SUB-MAIN: THE DUAL CALCULATOR
# ==========================================
def run_calculator():
    print("\n  -- DUAL CALCULATOR --")
    print("  UML vs Standard AST. Type 0 to return.")
    while True:
        try: line = input("Input> ").strip()
        except (EOFError, KeyboardInterrupt): print(); return
        if not line: continue
        if line in ('0', 'menu', 'm'): return
        
        try:
            # 1. Run through the Gearbox preprocessor (handles 0~, LZ, mixed !0 ops)
            proc_line, was_translated = uml_special.process(line)
            
            # 2. Parse into a syntax tree without crashing on standard 0/0 yet
            node = uml_engine.parse_only(proc_line)
            
            # 3. Run the dual comparison
            d = uml_engine.dual_eval_from_node(node)
            
            print(f"\n  Input: {line}")
            if was_translated:
                print(f"  Gear:  {proc_line}")
            
            if 'uml_val' in d:
                print(f"  UML:   {uml_engine.fmt(d['uml_val'])}")
            else:
                print(f"  UML:   REJECTED ({d.get('uml_err', '')})")
                
            if 'std_val' in d:
                print(f"  AST:   {uml_engine.fmt(d['std_val'])}")
            else:
                print(f"  AST:   REJECTED ({d.get('std_err', '')})")
                
            if d['agree']:
                print(f"  Check: PASS - Both engines agree")
            else:
                print(f"  Check: DIVERGENCE - The engines disagree")
                
        except Exception as ex:
            print(f"  Input Error: {ex}")

# ==========================================
# MAIN LOOP
# ==========================================
def main():
    while True:
        print("\n  ========================")
        print("  UML CALCULATOR (Modular)")
        print("  Travis Miner")
        print("  ========================")
        print("  1  Hardware random demo")
        print("  2  Dual Calculator")
        print("  3  Check Telemetry")
        print("  0  Quit")
        print("  ========================")
        try: choice = input("  > ").strip()
        except (EOFError, KeyboardInterrupt): print("\nbye"); return
            
        if choice == '1': run_hardware_demo()
        elif choice == '2': run_calculator()
        elif choice == '3':
            m = uml_telemetry.get_all_metrics()
            print(f"\n  CPU: {m['cpu_temp']:.1f}C | RAM: {m['ram_pct']:.1f}% | Clock: {m['clock_ratio']:.2f}x\n")
        elif choice in ('0', 'quit', 'exit', 'q'): print("  bye"); return

if __name__ == '__main__':
    main()
