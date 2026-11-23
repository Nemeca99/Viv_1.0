import json
from autonomy.physical_dialogue_adapter import PhysicalDialogueAdapter

adapter = PhysicalDialogueAdapter()

probes = [
    # 1. Negative/Contradiction Probes (Physically impossible / nonsensical combinations)
    ('vacuum sound', 'Acoustic wave in vacuum (impossible propagation)'),
    ('gravity float', 'Floating with gravity (antigravity contradiction)'),
    ('heat cold', 'Thermodynamic equilibrium / opposing thermal poles'),
    ('perpetual energy', 'Thermodynamic violation (first/second law)'),
    
    # 2. Category Mistake / Abstract Entity Probes
    ('justice mass', 'Abstract moral concept coupled to physical tensor'),
    ('triangle weight', 'Geometric concept coupled to gravitational force'),
    ('idea temperature', 'Cognitive concept coupled to thermal state'),
    
    # 3. High Polysemy / Ambiguity Traps
    ('bank current', 'Financial institution vs river bank / electrical vs water current'),
    ('spring mass', 'Season vs mechanical coil vs water source / mass as weight vs church service'),
    ('charge field', 'Electrical charge vs judicial accusation / agricultural field vs electromagnetic field'),
    
    # 4. Extreme Coordinate / Distant Domain Probes
    ('star enzyme', 'Astrophysics coupled to cellular biochemistry'),
    ('black_hole feather', 'General relativity singularity coupled to aerodynamic plumage'),
    ('quantum lever', 'Subatomic scale coupled to macroscopic classical mechanics')
]

print("=== ADVERSARIAL RED TEAM ATTACK ON VIV TOPOLOGY ===\n")

for p, desc in probes:
    try:
        res = adapter.reason_physical_query(p)
        if res is None:
            print(f'PROBE: "{p}" ({desc})')
            print(f'  -> Anchors: {adapter.extract_physical_anchors(p)}')
            print(f'  -> Verdict: PROPER_FAIL_CLOSED (NULL_UNLEARNED_ENTITY)\n')
            continue

        anchors = res.get('anchors', [])
        attractors = [a[0] for a in res.get('attractors', [])]
        matched = res.get('matched_chain')
        domain = matched.get('domain') if matched else 'NO_CHAIN_MATCHED'
        title = matched.get('title') if matched else 'NONE'
        
        status = 'PROVED' if matched else 'OPEN_CIRCUIT_FAIL_CLOSED'
        if not attractors and not matched:
            status = 'PROPER_FAIL_CLOSED'
        elif matched and len(anchors) < 2:
            status = 'OVERFITTED_SINGLE_ANCHOR'
            
        print(f'PROBE: "{p}" ({desc})')
        print(f'  -> Anchors: {anchors}')
        print(f'  -> Attractors: {attractors[:4]}')
        print(f'  -> Resolved Domain: {domain} | {title}')
        print(f'  -> Verdict: {status}\n')
    except Exception as e:
        print(f'PROBE: "{p}" CRASHED: {e}\n')
