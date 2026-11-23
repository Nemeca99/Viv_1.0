"""
Batch Domain Cartridge Compiler (Epoch 141)
"""
import sys
import time
from pathlib import Path

AUTONOMY_DIR = Path(__file__).resolve().parent
if str(AUTONOMY_DIR) not in sys.path:
    sys.path.insert(0, str(AUTONOMY_DIR))

from viv_wiki_cartridge_compiler import WikiCartridgeCompiler

DOMAINS = [
    "mathematics",
    "engineering",
    "philosophy",
    "comp_sci",
    "biology",
    "geography",
    "history",
]

def main():
    epoch = 141
    print(f"[*] Starting Batch Cartridge Compilation for Epoch {epoch}...")
    t_start = time.perf_counter()

    for domain in DOMAINS:
        t0 = time.perf_counter()
        compiler = WikiCartridgeCompiler(domain=domain)
        try:
            out_path = compiler.compile(epoch=epoch)
            dur = time.perf_counter() - t0
            print(f"[+] Domain {domain.upper()} finished in {dur:.2f}s -> {out_path.name}\n")
        except Exception as e:
            print(f"[-] Error compiling {domain}: {e}\n")

    total_dur = time.perf_counter() - t_start
    print(f"[+] All domains compiled in {total_dur:.2f}s!")

if __name__ == "__main__":
    main()
