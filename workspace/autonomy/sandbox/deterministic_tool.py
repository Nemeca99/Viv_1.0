import psutil

# Get CPU core count
cpu_count = psutil.cpu_count()

# Print CPU core count
print('CPU cores: ', cpu_count)

# Get RAM in GB
ram_gb = psutil.virtual_memory().total / 1024 / 1024 / 1024
print('RAM: ', round(ram_gb, 2))

# Print Python version
print('Python version:', __import__('sys').version[0])