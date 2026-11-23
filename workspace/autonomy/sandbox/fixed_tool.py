import psutil

def get_system_info():
    info = {
        'CPU cores': psutil.cpu_count(),
        'RAM (GB)': round(psutil.virtual_memory().total / (1024**3), 2),
        'Python Version': platform.python_version()
    }
    return info

system_info = get_system_info()
print("System Information:")
print(f"CPU cores: {system_info['CPU cores']}")
print(f"RAM (GB): {system_info['RAM (GB)']}")
print(f"Python Version: {system_info['Python Version']])