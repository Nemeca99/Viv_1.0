import glob
import os

files = glob.glob('L:\\LocalCoder\\workspace\\hviv_*.py') + [
    'L:\\LocalCoder\\workspace\\main_aios.py',
    'L:\\LocalCoder\\workspace\\viv_standalone.py',
    'L:\\LocalCoder\\workspace\\triadic_mutex.py',
    'L:\\LocalCoder\\workspace\\drive_router.py',
    'L:\\LocalCoder\\workspace\\drive_memory_manager.py',
    'L:\\LocalCoder\\workspace\\option1_dryrun.py',
    'L:\\LocalCoder\\workspace\\option3_finetune_prep.py'
]

print("==================================================")
print("     EXACT CODE LINE COUNTS WRITTEN TODAY         ")
print("==================================================")

total = 0
for f in sorted(list(set(files))):
    if os.path.exists(f):
        with open(f, "r", encoding="utf-8") as file_obj:
            lines = len(file_obj.readlines())
            total += lines
            print(f"{os.path.basename(f):<35} {lines:>5} lines")

print("--------------------------------------------------")
print(f"TOTAL PYTHON CODE WRITTEN TODAY:    {total:>5} lines")
print("==================================================")
