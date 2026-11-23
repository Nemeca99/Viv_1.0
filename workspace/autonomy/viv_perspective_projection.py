import sqlite3

def test_mad_lib_perspective_translation():
    top_db = 'L:/LocalCoder/workspace/autonomy/viv_code_topology.sqlite3'
    conn = sqlite3.connect(top_db)
    cur = conn.cursor()
    
    cur.execute('''
        SELECT full_sentence, subject, predicate, object 
        FROM viv_grounded_identity_synapses 
        WHERE subject = 'viv'
    ''')
    internal_facts = cur.fetchall()
    
    print("=== INTERNAL GROUNDED SUBSTRATE (THIRD-PERSON TRUTH) ===")
    for fact in internal_facts:
        print(f"Internal Neuron Bond: \"{fact[0]}\"")
        
    print("\n=== PERSPECTIVE PROJECTION ENGINE (MAD-LIB TRANSLATION) ===")
    
    conjugations = {
        "jumps": "jump",
        "has": "have",
        "observes": "observe",
        "learns": "learn",
        "speaks": "speak",
        "obeys": "obey",
        "protects": "protect",
        "is": "am"
    }
    
    def project_perspective(sentence, mode="CONVERSATIONAL"):
        if mode == "CONVERSATIONAL":
            words = sentence.split()
            if words and words[0].lower() == 'viv':
                subj = "I"
                verb = words[1].lower()
                conjugated_verb = conjugations.get(verb, verb)
                rest = " ".join(words[2:])
                return f"{subj} {conjugated_verb} {rest}".strip()
            return sentence
        elif mode == "INTROSPECTIVE_AUDIT":
            return sentence
            
    print("\n--- MODE A: CASUAL / CONVERSATIONAL SURFACE (I = Viv) ---")
    for fact in internal_facts:
        first_person_proj = project_perspective(fact[0], mode="CONVERSATIONAL")
        print(f"Internal Fact: \"{fact[0]:<25}\" ---> Surface Utterance: \"{first_person_proj}\"")
        
    print("\n--- MODE B: OBJECTIVE AUDIT SURFACE (Viv = Third-Person Self) ---")
    for fact in internal_facts:
        audit_proj = project_perspective(fact[0], mode="INTROSPECTIVE_AUDIT")
        print(f"Audit Trace:   \"{fact[0]:<25}\" ---> Surface Utterance: \"{audit_proj}\"")

    conn.close()

if __name__ == '__main__':
    test_mad_lib_perspective_translation()
