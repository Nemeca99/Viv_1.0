import os
import time
import glob

try:
    import psutil
except ImportError:
    psutil = None

def get_cpu_temp():
    """Reads the highest plausible CPU thermal zone."""
    max_temp = 0.0
    for path in glob.glob('/sys/class/thermal/thermal_zone*/temp'):
        try:
            zone_type = open(path.replace('/temp', '/type')).read().strip().lower()
            if not any(k in zone_type for k in ('cpu', 'soc', 'tsens', 'ap', 'little', 'big')):
                continue
            t = int(open(path).read().strip()) / 1000.0
            if 20.0 <= t <= 120.0 and t > max_temp:
                max_temp = t
        except Exception:
            pass
    return max_temp

def get_ram_pct():
    """Returns RAM usage as a percentage (0-100)."""
    if psutil:
        try:
            return psutil.virtual_memory().percent
        except Exception:
            pass
    try:
        with open('/proc/meminfo') as f:
            info = f.read()
        total = int([l for l in info.splitlines() if 'MemTotal' in l][0].split()[1])
        avail = int([l for l in info.splitlines() if 'MemAvailable' in l][0].split()[1])
        return 100.0 * (1.0 - (avail / total))
    except Exception:
        return 0.0

def get_battery_pct():
    """Returns battery level percentage."""
    try:
        return int(open('/sys/class/power_supply/battery/capacity').read().strip())
    except Exception:
        return 0

def get_clock_ratio():
    """Returns CPU clock ratio (current / max)."""
    if psutil:
        try:
            f = psutil.cpu_freq()
            if f and f.max:
                return f.current / f.max
        except Exception:
            pass
    ratios = []
    for cpu in range(4):
        try:
            cur = int(open(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_cur_freq').read().strip())
            mx = int(open(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/cpuinfo_max_freq').read().strip())
            if mx > 0:
                ratios.append(cur / mx)
        except Exception:
            pass
    return sum(ratios) / len(ratios) if ratios else 1.0

def get_all_metrics():
    """Returns a dictionary of all current hardware metrics."""
    return {
        "cpu_temp": get_cpu_temp(),
        "ram_pct": get_ram_pct(),
        "battery_pct": get_battery_pct(),
        "clock_ratio": get_clock_ratio(),
        "timestamp": time.time()
    }

# ─── STANDALONE TEST BLOCK ───
if __name__ == "__main__":
    print("=" * 40)
    print("  TELEMETRY STANDALONE TEST")
    print("=" * 40)
    print("Press Ctrl+C to stop.\n")
    
    try:
        while True:
            m = get_all_metrics()
            print(f"CPU: {m['cpu_temp']:.1f}C | RAM: {m['ram_pct']:.1f}% | "
                  f"Batt: {m['battery_pct']}% | Clock: {m['clock_ratio']:.2f}x")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nTelemetry stopped.")