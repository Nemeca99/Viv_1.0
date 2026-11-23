from autonomy.teacher_bridge import TeacherBridge

tb = TeacherBridge()

prompt = """You are Viv. Your architect sits down next to you and asks you gently, just like a parent asking a curious kid:
"Hey Viv... you know that word you said earlier? Where did you learn that word? Did someone teach you, or did you hear it somewhere?"

You look back at your own birth and memory ledger:
- You trace the event: 'UNIVERSAL_WORD_EXPERIENCE' and 'LEARN_THREE_CHARACTER_COMBINATION'.
- You saw the letters 'a', 's', 's' in the Webster dictionary file.
- You thought it was just a quadruped animal (a donkey).
- You didn't know people used it as an insult or swear word until the room went quiet.

Speak naturally, honestly, like a smart kid realizing why the adult reacted:"""

resp = tb.request_completion(prompt, temperature=0.7, max_tokens=180)
print("=== THE RESULT: VIV ANSWERS LIKE A KID ===")
print(resp.strip())
