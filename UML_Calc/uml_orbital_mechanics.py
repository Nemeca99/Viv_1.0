# uml_orbital_mechanics.py
# AIOS 2D Orbital Kinematics & Gravity Singularity Simulator.
# Executing astrophysics entirely through bracket geometry.

import uml_engine
import time

# --- UML KINEMATIC EQUATIONS ---
# dx, dy = CenterMass(X1,Y1) - Planet(X2,Y2)
EQ_DX = "{?X1, ?X2}"
EQ_DY = "{?Y1, ?Y2}"

# Distance squared: dx^2 + dy^2
EQ_R2 = "[^2[?DX], ^2[?DY]]"

# Absolute Distance: sqrt(r^2)
EQ_R  = "^0.5[?R2]"

# Gravity (Curvature) Acceleration Magnitude: (G * M1) / r^2
# Note: Shielded the inner multiplication with neutral brackets ( ) 
# to prevent the <> parser collision.
EQ_A  = "<(>?G, ?M1<), ?R2>"

# Vector Components: a * (dx / r) and a * (dy / r)
EQ_AX = ">?A, <?DX, ?R><"
EQ_AY = ">?A, <?DY, ?R><"

# Euler Integration (Additive State Evolution)
EQ_VX = "[?VX, ?AX]"
EQ_VY = "[?VY, ?AY]"
EQ_X2 = "[?X2, ?VX]"
EQ_Y2 = "[?Y2, ?VY]"

def simulate_orbit(name, init_x, init_y, init_vx, init_vy, ticks=10, speed=0.1):
    # Anchor the environment parameters
    uml_engine.SESSION_VARS.update({
        '?G': 1.0, '?M1': 100.0, # Center Mass (Sun) & Gravitational Constant
        '?X1': 0.0, '?Y1': 0.0,  # Center Position (Anchor at 0,0)
        '?X2': init_x, '?Y2': init_y, # Orbiting Body Position
        '?VX': init_vx, '?VY': init_vy, # Orbiting Body Velocity
    })
    
    print(f"\n=========================================================")
    print(f"  UML MISSION: {name}")
    print(f"=========================================================")
    
    for tick in range(1, ticks + 1):
        try:
            # 1. Calculate Topology Boundaries (Distance)
            dx, _, _, _ = uml_engine.evaluate(EQ_DX)
            dy, _, _, _ = uml_engine.evaluate(EQ_DY)
            uml_engine.SESSION_VARS['?DX'] = dx
            uml_engine.SESSION_VARS['?DY'] = dy
            
            r2, _, _, _ = uml_engine.evaluate(EQ_R2)
            uml_engine.SESSION_VARS['?R2'] = r2
            
            r, _, _, _ = uml_engine.evaluate(EQ_R)
            uml_engine.SESSION_VARS['?R'] = r
            
            # 2. Calculate Curvature (Gravity)
            a_mag, _, _, _ = uml_engine.evaluate(EQ_A)
            uml_engine.SESSION_VARS['?A'] = a_mag
            
            ax, _, _, _ = uml_engine.evaluate(EQ_AX)
            ay, _, _, _ = uml_engine.evaluate(EQ_AY)
            uml_engine.SESSION_VARS['?AX'] = ax
            uml_engine.SESSION_VARS['?AY'] = ay
            
            # 3. Additive Kinematics (Motion Evolution)
            vx, _, _, _ = uml_engine.evaluate(EQ_VX)
            vy, _, _, _ = uml_engine.evaluate(EQ_VY)
            uml_engine.SESSION_VARS['?VX'] = vx
            uml_engine.SESSION_VARS['?VY'] = vy
            
            x2, _, _, _ = uml_engine.evaluate(EQ_X2)
            y2, _, _, _ = uml_engine.evaluate(EQ_Y2)
            uml_engine.SESSION_VARS['?X2'] = x2
            uml_engine.SESSION_VARS['?Y2'] = y2
            
            # Formatted Telemetry
            print(f"Tick {tick:02d} | Pos: ({uml_engine.fmt(x2):>6}, {uml_engine.fmt(y2):>6}) | "
                  f"Dist: {uml_engine.fmt(r):>6} | Accel: {uml_engine.fmt(a_mag):>6} | "
                  f"Vel: ({uml_engine.fmt(vx):>6}, {uml_engine.fmt(vy):>6})")
                  
            time.sleep(speed)
        except Exception as e:
            print(f"Tick {tick:02d} | SYSTEM CRASH: {e}")
            break

if __name__ == "__main__":
    print("=========================================================")
    print("  UML ASTROPHYSICS & KINEMATICS ENGINE")
    print("  Executing orbital mechanics via spatial geometry.")
    print("=========================================================")
    
    simulate_orbit("Stable Orbital Curvature", init_x=15.0, init_y=0.0, init_vx=0.0, init_vy=2.5, ticks=10, speed=0.1)
    simulate_orbit("Singularity Collision (r=0)", init_x=0.0, init_y=0.0, init_vx=0.0, init_vy=0.0, ticks=3, speed=0.1)
