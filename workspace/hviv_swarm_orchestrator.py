import os
import sys
import json
import subprocess

sys.stdout.reconfigure(encoding="utf-8")

class MultiGPUSwarmOrchestrator:
    def __init__(self):
        self.gpus = self.detect_cuda_gpus()

    def detect_cuda_gpus(self) -> list:
        """
        Queries nvidia-smi on Windows Host to enumerate GPUs and VRAM.
        """
        try:
            cmd = ["nvidia-smi", "--query-gpu=index,name,memory.total,memory.free", "--format=csv,noheader,nounits"]
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            if res.returncode != 0:
                return []
            
            gpu_list = []
            for line in res.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) == 4:
                    gpu_list.append({
                        "index": int(parts[0]),
                        "name": parts[1],
                        "total_vram_mb": int(parts[2]),
                        "free_vram_mb": int(parts[3])
                    })
            return gpu_list
        except Exception:
            return []

    def allocate_swarm_topology(self) -> dict:
        num_gpus = len(self.gpus)
        print(f"[{num_gpus} CUDA GPU(s) Detected]")
        
        topology = {}
        if num_gpus == 0:
            print("  └─ Running in CPU / Single Substrate Fallback Mode.")
            topology = {
                "GPU_0 (CPU/Fallback)": "Luna Core LLM (qwen3:8b) + Voice + Subagents (Sequential 1Hz)",
                "mode": "SINGLE_NODE_SEQUENTIAL"
            }
        elif num_gpus == 1:
            print(f"  └─ Single GPU Found: {self.gpus[0]['name']} ({self.gpus[0]['total_vram_mb']} MB VRAM)")
            topology = {
                "GPU_0": f"Luna Core LLM + Voice + Subagents ({self.gpus[0]['name']})",
                "mode": "SINGLE_GPU_PINNED_OR_UNLOAD"
            }
        elif num_gpus == 2:
            print("  └─ Dual-GPU Swarm Architecture Unlocked!")
            topology = {
                "GPU_0": f"Luna Core LLM (qwen3:8b / 32b) -> {self.gpus[0]['name']}",
                "GPU_1": f"Voice STT/TTS Engine + Vision Agents -> {self.gpus[1]['name']}",
                "mode": "DUAL_GPU_PARALLEL_SWARM"
            }
        else: # 3+ GPUs (Mining Rig Setup)
            print(f"  └─ Full Multi-GPU Mining Rig Swarm Unlocked! ({num_gpus} GPUs)")
            topology = {
                "GPU_0": f"Luna Core LLM (Sovereign Reasoner) -> {self.gpus[0]['name']}",
                "GPU_1": f"Voice STT/TTS Engine + Realtime Audio -> {self.gpus[1]['name']}",
                "GPU_2": f"Sub-Agent Code Refactoring & Carma Vector Memory -> {self.gpus[2]['name']}",
                "mode": "MULTI_GPU_MINING_RIG_SWARM"
            }
        return topology

    def generate_launch_script(self, target_script: str = "L:\\LocalCoder\\workspace\\swarm_launch.bat"):
        topology = self.allocate_swarm_topology()
        lines = ["@echo off", ":: HViv Multi-GPU Swarm Launch Script", ""]
        
        if len(self.gpus) >= 2:
            lines.append("echo Launching Dual/Multi GPU Swarm Nodes...")
            lines.append("set CUDA_VISIBLE_DEVICES=0")
            lines.append("start \"GPU 0 - Luna LLM\" ollama serve")
            lines.append("set CUDA_VISIBLE_DEVICES=1")
            lines.append("start \"GPU 1 - Voice Engine\" python L:\\LocalCoder\\workspace\\voice_engine.py")
        else:
            lines.append("echo Launching Single Substrate Node...")
            lines.append("ollama serve")

        with open(target_script, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
            
        print(f"\nSwarm launch script generated: {target_script}")
        return topology

if __name__ == "__main__":
    print("==================================================")
    print("    HViv Multi-GPU Swarm Orchestrator Engine     ")
    print("==================================================")
    
    orchestrator = MultiGPUSwarmOrchestrator()
    top = orchestrator.generate_launch_script()
    print("\nAllocated Swarm Topology:")
    print(json.dumps(top, indent=2))
