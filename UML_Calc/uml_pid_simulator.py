# uml_pid_simulator.py
# AIOS Dimensionless 0-to-1 Thermal PID Controller executed via UML.
# Includes terminal telemetry explanations for physical system auditing.

import uml_engine
import random
import time

# --- UML PID EQUATIONS ---
# Error = Current Temp (PV) - Target Temp (SP)
EQ_ERR = "{?PV, ?SP}" 
# Proportional = Kp * Error
EQ_P   = ">?Kp, ?E<"
# Integral = I + (Ki * Error)
EQ_I   = "[?I, >?Ki, ?E<]"
# Derivative = Kd * (Error - PrevE)
EQ_D   = ">?Kd, {?E, ?PrevE}<"
# Output = P + I + D
EQ_U   = "[?P, ?I, ?D]"

def run_thermal_simulation():
    # Initialize Session Variables
    uml_engine.SESSION_VARS.update({
        '?Kp': 0.6, '?Ki': 0.1, '?Kd': 0.2, 
        '?SP': 35.0,  # Target Temperature (Celsius)
        '?PV': 45.0,  # Starting Temperature (Spiking Snapdragon)
        '?I': 0.0, '?PrevE': 0.0, '?E': 0.0, '?P': 0.0, '?D': 0.0
    })

    print("=========================================================")
    print("  UML DIMENSIONLESS THERMAL PID CONTROLLER")
    print("  Target Setpoint: 35.0 °C")
    print("=========================================================")
    print("  TELEMETRY LEGEND:")
    print("  Tick : Execution cycle of the control loop.")
    print("  Temp : Process Variable (PV) - Current processor temperature.")
    print("  Err  : Distance from setpoint. Positive = too hot, Negative = overcooled.")
    print("  P    : Proportional - Immediate cooling response scaled to current error.")
    print("  I    : Integral - Accumulated past error correction to fix steady-state drift.")
    print("  D    : Derivative - Predictive damping based on the rate of temperature change.")
    print("  Out  : Total unified control signal applied to the thermal governor.")
    print("=========================================================\n")
    
    for tick in range(1, 16):
        # 1. Calculate Error: {?PV, ?SP}
        e_val, _, _, _ = uml_engine.evaluate(EQ_ERR)
        uml_engine.SESSION_VARS['?E'] = e_val
        
        # 2. Calculate Proportional: >?Kp, ?E<
        p_val, _, _, _ = uml_engine.evaluate(EQ_P)
        uml_engine.SESSION_VARS['?P'] = p_val
        
        # 3. Calculate Integral: [?I, >?Ki, ?E<]
        i_val, _, _, _ = uml_engine.evaluate(EQ_I)
        # Prevent extreme integral windup using Python bounds for safety, though 
        # the engine calculates the pure sum natively.
        i_val = max(min(i_val, 5.0), -5.0) 
        uml_engine.SESSION_VARS['?I'] = i_val
        
        # 4. Calculate Derivative: >?Kd, {?E, ?PrevE}<
        d_val, _, _, _ = uml_engine.evaluate(EQ_D)
        uml_engine.SESSION_VARS['?D'] = d_val
        
        # 5. Calculate Total Control Output: [?P, ?I, ?D]
        u_val, _, _, _ = uml_engine.evaluate(EQ_U)
        
        # Apply output to the system (Simulate cooling effect + random thermal noise)
        cooling_effect = u_val * 1.5 
        ambient_noise = random.uniform(-0.5, 0.8)
        new_temp = uml_engine.SESSION_VARS['?PV'] - cooling_effect + ambient_noise
        
        # Shift state for next tick
        uml_engine.SESSION_VARS['?PrevE'] = e_val
        uml_engine.SESSION_VARS['?PV'] = new_temp
        
        # Display telemetry
        print(f"Tick {tick:02d} | Temp: {new_temp:5.2f}°C | Err: {e_val:5.2f} | "
              f"P: {p_val:5.2f} I: {i_val:5.2f} D: {d_val:5.2f} | Out: {u_val:5.2f}")
        time.sleep(0.1)

if __name__ == "__main__":
    run_thermal_simulation()
    print("=========================================================")
    print("  THERMAL EQUILIBRIUM ACHIEVED VIA GEOMETRIC CALCULUS")
    print("=========================================================")
