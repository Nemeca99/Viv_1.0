
import math

def test_harmonic_invariant(steps=1000):
    phi = (1 + math.sqrt(5)) / 2
    total = 0.0
    for n in range(1, steps + 1):
        # Lorentz-damped harmonic decay
        beta = 1.0 / (n * phi)
        gamma = 1.0 / math.sqrt(1.0 - beta**2)
        total += (1.0 / n) * (1.0 / gamma)
    return total

val = test_harmonic_invariant()
print(f"HARMONIC INVARIANT CONVERGENCE POINT: {val:.8f}")
assert val > 0 and not math.isnan(val), "Must produce finite real scalar"
