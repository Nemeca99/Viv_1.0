import subprocess
import sys

exe_path = r'"C:\Users\nemec\AppData\Local\Programs\Clawd on Desk\Clawd on Desk.exe"'
cmd = [
    'schtasks', '/create',
    '/tn', 'ClawdOnDesk',
    '/tr', exe_path,
    '/sc', 'ONCE',
    '/st', '00:00',
    '/it',
    '/f'
]
res = subprocess.run(cmd, capture_output=True, text=True)
print('STDOUT:', res.stdout)
print('STDERR:', res.stderr)
print('Exit code:', res.returncode)

if res.returncode == 0:
    run_res = subprocess.run(['schtasks', '/run', '/tn', 'ClawdOnDesk'], capture_output=True, text=True)
    print('RUN STDOUT:', run_res.stdout)
    print('RUN STDERR:', run_res.stderr)
    print('RUN Exit code:', run_res.returncode)
