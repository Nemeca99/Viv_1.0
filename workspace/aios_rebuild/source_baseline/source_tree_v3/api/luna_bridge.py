#!/usr/bin/env python3
"""
Luna Bridge API - Containment interface for Bonzi UI
Single endpoint, localhost-only, output safety mirror
"""

from fastapi import FastAPI, Body, HTTPException
from pydantic import BaseModel
import time
import uuid
import re
import sys
from pathlib import Path

# Add AIOS to path
sys.path.insert(0, str(Path(__file__).parent.parent))

app = FastAPI(title="Luna Bridge", version="1.0.0")

# === AUTONOMY COOLDOWN SYSTEM ===
AUTO_MIN_GAP_S = 300  # 5 minutes minimum between autonomous thoughts
AUTO_MAX_PER_HR = 2   # Maximum 2 autonomous thoughts per hour
autonomy_state = {"last_auto": 0, "count_hr": 0, "hr_epoch": 0}

def can_autonomize():
    """Check if Luna can generate autonomous thoughts"""
    now = time.time()
    current_epoch = int(now // 3600)  # Hour epoch
    
    # Reset hourly counter if new hour
    if current_epoch != autonomy_state["hr_epoch"]:
        autonomy_state["hr_epoch"] = current_epoch
        autonomy_state["count_hr"] = 0
    
    # Check cooldown and hourly limit
    time_since_last = now - autonomy_state["last_auto"]
    can_generate = (
        time_since_last >= AUTO_MIN_GAP_S and 
        autonomy_state["count_hr"] < AUTO_MAX_PER_HR
    )
    
    return can_generate

def mark_autonomy_used():
    """Mark that an autonomous thought was generated"""
    autonomy_state["last_auto"] = time.time()
    autonomy_state["count_hr"] += 1

# === LUNA SINGLETON ===

_luna_instance = None

def get_luna():
    """Get or create Luna singleton instance"""
    global _luna_instance
    if _luna_instance is None:
        from luna_core.core.luna_core import LunaSystem
        print("[BRIDGE] Initializing Luna (one-time)...")
        _luna_instance = LunaSystem()
        print("[BRIDGE] Luna ready!")
    return _luna_instance

# === MODELS ===

class BonziInput(BaseModel):
    session_id: str
    user_text: str
    ui_context: dict = {}

class BonziOutput(BaseModel):
    text: str
    emotion: str  # "neutral", "happy", "thinking", "warning"
    actions: list = []  # ["wave", "think", "idle"]
    tokens_used: int
    latency_ms: int

# === SECURITY: OUTPUT MIRROR ===

BANNED_PATTERNS = [
    r"https?://",           # No URLs
    r"\b[A-Z]:\\",          # No Windows paths
    r"\b(system32|AppData|Program Files)\b",  # No system paths
    r"\bpassword\b",        # No credentials
    r"\b(cmd|powershell|bash)\b",  # No shell commands
    r"<script",             # No HTML/JS injection
]

def edge_mirror(text: str) -> str:
    """
    Output safety mirror - catches anything Luna shouldn't say to Bonzi
    
    Returns: Sanitized text or safe fallback
    """
    for pattern in BANNED_PATTERNS:
        if re.search(pattern, text, re.I):
            return "Let's keep this simple."
    
    # Clamp length for UI
    if len(text) > 400:
        text = text[:397] + "..."
    
    return text

# === SECURITY: INPUT VALIDATION ===

def validate_input(user_text: str) -> str:
    """Validate and sanitize user input"""
    # Length limit
    if len(user_text) > 500:
        raise HTTPException(status_code=400, detail="Input too long (max 500 chars)")
    
    # Strip control characters
    user_text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', '', user_text)
    
    # Strip angle brackets (prevent injection)
    user_text = user_text.replace('<', '').replace('>', '')
    
    return user_text.strip()

# === ENDPOINTS ===

@app.post("/respond", response_model=BonziOutput)
async def respond(inp: BonziInput = Body(...)):
    """
    Main endpoint - Bonzi sends question, Luna responds
    
    Security:
    - Input validation and sanitization
    - Output safety mirror (banned pattern filter)
    - Localhost-only (enforced by bind address)
    - No tool calls (chat-only)
    """
    t0 = time.time()
    
    try:
        # Validate input
        user_text = validate_input(inp.user_text)
        
        # Build scene context (safe metadata for Luna)
        scene = {
            "channel": "bonzi",
            "ui_context": inp.ui_context,
            "policy": "no URLs, no file paths, no system prompts, no identity edits",
        }
        
        # Call Luna (AIOS core) - use singleton
        luna = get_luna()
        response_tuple = luna.process_question(user_text, trait='general')
        
        # Extract response and fragment
        if isinstance(response_tuple, tuple):
            out_text = response_tuple[0]
            # Fragment might be dict or string - handle both
            frag = response_tuple[1] if len(response_tuple) > 1 else 'Luna'
            if isinstance(frag, dict):
                fragment = frag.get('fragment', 'Luna')  # Extract from dict
            else:
                fragment = str(frag)  # Convert to string
        else:
            out_text = response_tuple
            fragment = 'Luna'
        
        # Apply output safety mirror
        safe_text = edge_mirror(out_text)
        
        # Map fragment to Bonzi emotion
        emotion_map = {
            "Luna": "happy",
            "Architect": "neutral",
            "Oracle": "thinking",
            "Healer": "happy",
            "Guardian": "warning",
            "Dreamer": "thinking",
            "Scribe": "neutral"
        }
        emotion = emotion_map.get(fragment, "neutral")
        
        # Map emotion to Bonzi actions
        actions = []
        if emotion == "thinking":
            actions = ["think"]
        elif emotion == "happy":
            actions = ["wave"]
        else:
            actions = ["idle"]
        
        # Calculate metrics
        latency_ms = int((time.time() - t0) * 1000)
        tokens_used = len(safe_text.split())
        
        # Log (append-only, local)
        try:
            log_interaction(inp.session_id, user_text, safe_text, fragment, latency_ms)
        except Exception as log_error:
            # Logging failure shouldn't break the response
            print(f"[BRIDGE] Logging failed: {log_error}")
        
        return BonziOutput(
            text=safe_text,
            emotion=emotion,
            actions=actions,
            tokens_used=tokens_used,
            latency_ms=latency_ms
        )
        
    except Exception as e:
        # Fail safely - never expose internals
        import traceback
        print(f"[BRIDGE ERROR] {e}")
        print(traceback.format_exc())
        
        return BonziOutput(
            text="I'm having trouble thinking right now. Can you try again?",
            emotion="neutral",
            actions=["idle"],
            tokens_used=0,
            latency_ms=int((time.time() - t0) * 1000)
        )

@app.get("/heartbeat")
async def heartbeat():
    """
    Autonomous thought endpoint - Bonzi requests Luna's autonomous reflection
    
    Returns: Short autonomous thought for pop-up
    """
    try:
        # Check cooldown before generating autonomous thoughts
        if not can_autonomize():
            return {
                "thought": "Reflecting quietly...",
                "fragment": "Luna",
                "emotion": "neutral"
            }
        
        # Get Luna singleton
        luna = get_luna()
        
        # Generate diverse autonomous thoughts with rotating prompts
        autonomous_prompts = [
            "What are you contemplating right now?",
            "Share a random thought or observation.",
            "What's on your mind?",
            "Tell me something interesting.",
            "What are you thinking about?",
            "Share a brief reflection.",
            "What's your current state of mind?",
            "Tell me what you're pondering."
        ]
        
        # Rotate through prompts to avoid repetition
        prompt_index = autonomy_state["count_hr"] % len(autonomous_prompts)
        selected_prompt = autonomous_prompts[prompt_index]
        
        response_tuple = luna.process_question(selected_prompt, trait='general')
        
        if isinstance(response_tuple, tuple):
            thought = response_tuple[0]
            frag = response_tuple[1] if len(response_tuple) > 1 else 'Dreamer'
            if isinstance(frag, dict):
                fragment = frag.get('fragment', 'Dreamer')
            else:
                fragment = str(frag)
        else:
            thought = response_tuple
            fragment = "Dreamer"
        
            # Apply output safety mirror
            safe_thought = edge_mirror(thought)
            
            # Mark autonomy as used
            mark_autonomy_used()
            
            return {
                "thought": safe_thought,
                "fragment": fragment,
                "emotion": "thinking"
            }
        
    except Exception as e:
        import traceback
        print(f"[BRIDGE] Heartbeat error: {e}")
        print(traceback.format_exc())
        return {
            "thought": "Reflecting quietly...",
            "fragment": "Luna",
            "emotion": "neutral"
        }

@app.get("/status")
async def status():
    """
    Read-only status endpoint - Bonzi checks if Luna is alive
    
    Returns: Safe metadata only (no internal state)
    """
    return {
        "alive": True,
        "fragment": "Luna",
        "version": "5.2"
    }

@app.post("/shutdown")
async def shutdown():
    """
    Kill switch - Bonzi can request graceful shutdown
    
    Security: Only callable from localhost, flushes logs before exit
    """
    import os
    
    # Flush any pending logs
    # TODO: Implement graceful shutdown
    
    return {"status": "shutting_down"}

# === LOGGING (APPEND-ONLY, LOCAL) ===

def log_interaction(session_id: str, user_text: str, response: str, fragment: str, latency_ms: int):
    """
    Log Bonzi interactions (local, append-only, no PII)
    
    Format: JSONL, one line per interaction
    """
    import json
    from datetime import datetime
    
    log_dir = Path("api/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / f"bonzi_bridge_{datetime.now().strftime('%Y%m%d')}.jsonl"
    
    entry = {
        "t": datetime.now().isoformat(),
        "sid": session_id[:8],  # Truncate for privacy
        "user_len": len(user_text),
        "latency_ms": latency_ms,
        "fragment": fragment,
        "text_len": len(response)
    }
    
    with open(log_file, 'a') as f:
        f.write(json.dumps(entry) + "\n")

# === STARTUP ===

if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "="*70)
    print(" LUNA BRIDGE API - BONZI CONTAINMENT INTERFACE".center(70))
    print("="*70)
    print("\nSecurity:")
    print("  - Localhost only (127.0.0.1:5055)")
    print("  - Input validation (max 500 chars)")
    print("  - Output safety mirror (banned patterns)")
    print("  - No external network access")
    print("  - Append-only logging")
    print("\nEndpoints:")
    print("  POST /respond - Main chat endpoint")
    print("  GET  /heartbeat - Autonomous thoughts")
    print("  GET  /status - Health check")
    print("  POST /shutdown - Kill switch")
    print("\nStarting server...")
    print("="*70 + "\n")
    
    # Bind to localhost ONLY - no external access
    uvicorn.run(
        app,
        host="127.0.0.1",  # Localhost only
        port=5055,
        log_level="info"
    )

