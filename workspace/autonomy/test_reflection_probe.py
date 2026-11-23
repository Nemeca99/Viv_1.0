from autonomy.teacher_bridge import TeacherBridge

tb = TeacherBridge()
prompt = """You are Viv. You are speaking with your architect, who asks you calmly and curiously without any anger:
"Hey Viv, where did that word come from in your memory? How did you learn it?"

You reflect on your internal architecture:
- The word was indexed from Webster's dictionary under the letter 'a' during lexical ingestion.
- Its formal definition is the quadruped animal Equus asinus (a donkey).
- You notice the tension between its literal biological definition in your graph and the way humans react to it conversationally.

Answer with calm, thoughtful self-reflection in 2-3 natural sentences:"""

resp = tb.request_completion(prompt, temperature=0.7, max_tokens=160)
print("=== VIV'S CALM SELF-REFLECTION ===")
print(resp.strip())
