from autonomy.teacher_bridge import TeacherBridge

tb = TeacherBridge()
evidence_steps = [
    "cold FREEZES water (Sub-zero temperatures freeze liquid water)",
    "water FORMS ice (Freezing water undergoes solid phase transition)",
    "ice CAUSES expansion (Ice lattice occupies higher specific volume)",
    "expansion EXERTS stress (Confined volumetric expansion creates extreme radial stress)",
    "stress ACTS_ON pipe (Expanding ice pushes outward against rigid pipe)",
    "pipe SUFFERS crack (Wall stress exceeding tensile limit fractures pipe)",
    "crack CAUSES burst (Fracture propagates along stress lines)",
    "burst PRODUCES leak -> flood"
]

steps_text = "\n".join(f"- {s}" for s in evidence_steps)

prompt = f"""You are Viv. You are having a genuine conversation with someone you care about.
They ask you: "Viv, what will happen if the pipe in my basement freezes tonight?"

Speak warmly, naturally, and conversationally—like a real friend who understands how things work. 
Do not recite technical bullet points, but ensure your advice is faithful to these verified facts:
{steps_text}

Respond warmly in 2-3 natural sentences:"""

resp = tb.request_completion(prompt, temperature=0.7, max_tokens=150)
print("=== VIV'S WARM CONVERSATIONAL EMBODIMENT ===")
print(resp.strip())
