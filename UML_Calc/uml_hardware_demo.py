import time
import random
import uml_engine
import uml_telemetry
import uml_chaos

def generate_random_uml(metrics):
    """Takes live hardware metrics and builds a random UML expression."""
    # Create a pool of numbers from the live telemetry
    # We clamp them to realistic ranges so the math doesn't explode
    pool = [
        max(1.0, round(metrics['cpu_temp'], 2)),
        max(1.0, round(metrics['ram_pct'], 2)),
        max(1.0, round(metrics['clock_ratio'] * 100, 2)), 
        max(1.0, float(random.randint(10, 500)))
    ]
    
    # Randomly choose an operator
    op = random.choice(['add', 'mul', 'sub', 'div', 'exp', 'log'])
    
    a = random.choice(pool)
    b = random.choice(pool)
    
    if op == 'add':
        return f"[{a},{b}]"
    elif op == 'sub':
        return f"{{{a},{b}}}"
    elif op == 'mul':
        return f">{a},{b}<"
    elif op == 'div':
        return f"<{a},{b}>"
    elif op == 'exp':
        return f"^2[{a}]"
    elif op == 'log':
        # Log base 'a' of 'b'. Ensure base > 1.
        if a <= 1: a = 2
        return f"&[{a},{b}]"

# ==========================================
# STANDALONE TEST BLOCK
# ==========================================
if __name__ == "__main__":
    print("=" * 60)
    print("  HARDWARE RANDOM DEMO STANDALONE TEST")
    print("=" * 60)
    print("Starting Dynamometer in background...")
    
    sab = uml_chaos.Saboteur(threads=4, intensity=0.8)
    sab.start()
    
    print("Generating UML equations from live hardware telemetry...\n")
    
    try:
        for i in range(1, 6):  # Run 5 slides
            time.sleep(3)  # Wait a few seconds for heat to build
            
            # 1. Pull the telemetry
            metrics = uml_telemetry.get_all_metrics()
            
            # 2. Generate the UML
            uml_str = generate_random_uml(metrics)
            
            # 3. Evaluate it using the engine
            try:
                result, node, notation, trace = uml_engine.evaluate(uml_str)
                
                print(f"--- Slide {i} ---")
                print(f"  Hardware State: Temp={metrics['cpu_temp']:.1f}C | RAM={metrics['ram_pct']:.1f}% | Clock={metrics['clock_ratio']:.2f}x")
                print(f"  UML Equation:   {uml_str}")
                print(f"  Result:         {uml_engine.fmt(result)}")
                print("  Trace:")
                for depth, sub, val in trace:
                    print(f"    d{depth} {sub:<25} = {uml_engine.fmt(val)}")
                print()
                
            except Exception as e:
                print(f"  MATH ERROR on {uml_str}: {e}")
                
    except KeyboardInterrupt:
        print("\nStopping demo...")
    finally:
        sab.stop()
        print("Demo complete. Dynamometer stopped.")