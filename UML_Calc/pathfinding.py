import random
import math

def simulate_pathfinding(steps=5):
    print("=========================================================")
    print("  AIOS PATHFINDING: RID STABILITY SCALAR (Sn) SIMULATOR")
    print("  Equation: Sn^2 = ((RLE * LTP) * RSR)^3")
    print("=========================================================")

    for step in range(1, steps + 1):
        # 1. Randomly generate physical entropy (RLE) and distance (LTP) bounds
        rle = random.uniform(0.1, 0.9) # Kept slightly above 0 for cleaner logs
        ltp = random.uniform(0.1, 0.9)
        
        # 2. State Reconstruction (RSR) natively produced by multiplying RLE and LTP
        rsr = rle * ltp
        
        # 3. Calculate 3D volumetric computational load
        inner_core = (rle * ltp) * rsr
        volume = inner_core ** 3
        
        # 4. Bind to 2D squared stability scalar (Sn^2 = Volume -> Sn = sqrt(Volume))
        sn = math.sqrt(volume)
        
        print(f"Step {step:02d} | RLE (Entropy) : {rle:.4f} | LTP (Distance) : {ltp:.4f}")
        print(f"        | RSR (Velocity): {rsr:.4f}")
        print(f"        | Vol Load      : {volume:.8f} | STABILITY SCALAR (Sn): {sn:.8f}")
        print("-" * 57)

if __name__ == "__main__":
    simulate_pathfinding()
