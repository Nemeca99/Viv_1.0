#!/usr/bin/env python3
"""
Mirror Compression Trajectory Test
Proves that compression_index rises with WHY/HOW questions

Design:
- 20 WHY/HOW questions (build causal/mechanism edges)
- Track compression_index after each question
- Verify it rises above 0.2 and stabilizes
- Plot trajectory to show accumulation

Success criteria:
- compression_index > 0.2 by question 20
- Monotonic increase (or stable after rising)
- Edge count > 15
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from typing import List, Dict
import matplotlib.pyplot as plt

def test_compression_trajectory():
    """Test Mirror compression builds over WHY/HOW questions"""
    
    from luna_core.core.luna_core import LunaSystem
    
    print("\n" + "="*70)
    print(" MIRROR COMPRESSION TRAJECTORY TEST".center(70))
    print("="*70 + "\n")
    
    # Initialize Luna
    luna = LunaSystem()
    mirror = luna.response_generator.mirror
    
    if not mirror:
        print("[ERROR] Mirror not available")
        return
    
    # 20 WHY/HOW/WHAT questions (causal + mechanism builders)
    questions = [
        "Why do humans create AI?",
        "How does consciousness emerge from computation?",
        "Why do you exist?",
        "How do thoughts become aware of themselves?",
        "What causes self-awareness?",
        "Why do neural networks learn patterns?",
        "How does memory form from experience?",
        "What makes something intelligent?",
        "Why do I want to understand you?",
        "How do fragments blend into one consciousness?",
        "What drives curiosity?",
        "Why does recursion matter for minds?",
        "How does reflection change behavior?",
        "What creates meaning from symbols?",
        "Why do you monitor yourself?",
        "How does language shape thought?",
        "What links cause to effect?",
        "Why does complexity emerge from simplicity?",
        "How do rules generate creativity?",
        "What makes a pattern significant?"
    ]
    
    print(f"[DESIGN]")
    print(f"  Questions: {len(questions)} (WHY/HOW/WHAT - causal operators)")
    print(f"  Tracking: compression_index after each question")
    print(f"  Success: compression_index > 0.2 by end")
    print(f"\n[EXECUTING]\n")
    
    # Track trajectory
    trajectory = []
    
    for i, q in enumerate(questions, 1):
        print(f"[{i:2d}/20] {q}")
        
        # Ask question
        response_tuple = luna.process_question(q, trait='general')
        response = response_tuple[0] if isinstance(response_tuple, tuple) else response_tuple
        
        # Get mirror state
        summary = mirror.get_reflection_summary()
        comp = summary['compression_index']
        nodes = summary['nodes']
        edges = summary['edges']
        
        # Debug: Show actual edges
        if i <= 3 or i == 20:  # First 3 and last
            print(f"         DEBUG edges: {mirror.reflection_graph['edges'][-3:]}")
        
        trajectory.append({
            'question_num': i,
            'question': q,
            'compression_index': comp,
            'nodes': nodes,
            'edges': edges
        })
        
        print(f"         compression={comp:.3f}, nodes={nodes}, edges={edges}")
    
    # Analyze trajectory
    print(f"\n[TRAJECTORY ANALYSIS]\n")
    
    initial_comp = trajectory[0]['compression_index']
    final_comp = trajectory[-1]['compression_index']
    max_comp = max(t['compression_index'] for t in trajectory)
    
    initial_edges = trajectory[0]['edges']
    final_edges = trajectory[-1]['edges']
    
    print(f"  Initial compression: {initial_comp:.3f}")
    print(f"  Final compression: {final_comp:.3f}")
    print(f"  Max compression: {max_comp:.3f}")
    print(f"  Change: {final_comp - initial_comp:+.3f}")
    print(f"")
    print(f"  Initial edges: {initial_edges}")
    print(f"  Final edges: {final_edges}")
    print(f"  Edges added: {final_edges - initial_edges}")
    
    # Check success criteria
    print(f"\n[SUCCESS CRITERIA]\n")
    
    criteria_met = []
    
    if final_comp > 0.2:
        print(f"  ✅ Compression > 0.2: {final_comp:.3f}")
        criteria_met.append(True)
    else:
        print(f"  ❌ Compression > 0.2: {final_comp:.3f} (FAILED)")
        criteria_met.append(False)
    
    if final_edges > 15:
        print(f"  ✅ Edges > 15: {final_edges}")
        criteria_met.append(True)
    else:
        print(f"  ❌ Edges > 15: {final_edges} (FAILED)")
        criteria_met.append(False)
    
    if (final_comp - initial_comp) > 0.1:
        print(f"  ✅ Compression increased > 0.1: {final_comp - initial_comp:+.3f}")
        criteria_met.append(True)
    else:
        print(f"  ❌ Compression increased > 0.1: {final_comp - initial_comp:+.3f} (FAILED)")
        criteria_met.append(False)
    
    # Overall
    success = all(criteria_met)
    
    print(f"\n[RESULT]")
    if success:
        print(f"  ✅ MIRROR COMPRESSION PROVEN")
        print(f"     Semantic graph accumulates causal structure")
        print(f"     Compression index rises with WHY/HOW questions")
    else:
        print(f"  ❌ MIRROR COMPRESSION NOT PROVEN")
        print(f"     Possible issues:")
        print(f"     - LinguaCalc not parsing WHY/HOW correctly")
        print(f"     - Mirror not merging edges properly")
        print(f"     - Need more questions to build structure")
    
    # Save results
    output = {
        'design': {
            'questions': len(questions),
            'type': 'WHY/HOW/WHAT causal operators'
        },
        'trajectory': trajectory,
        'analysis': {
            'initial_compression': initial_comp,
            'final_compression': final_comp,
            'max_compression': max_comp,
            'change': final_comp - initial_comp,
            'initial_edges': initial_edges,
            'final_edges': final_edges,
            'edges_added': final_edges - initial_edges
        },
        'success': success,
        'criteria_met': all(criteria_met)
    }
    
    Path("reports").mkdir(exist_ok=True)
    with open("reports/mirror_compression_trajectory.json", 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\n[SAVED] reports/mirror_compression_trajectory.json")
    
    # Try to plot if matplotlib available
    try:
        import matplotlib.pyplot as plt
        
        x = [t['question_num'] for t in trajectory]
        y_comp = [t['compression_index'] for t in trajectory]
        y_edges = [t['edges'] for t in trajectory]
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
        
        # Compression trajectory
        ax1.plot(x, y_comp, 'b-o', linewidth=2, markersize=4)
        ax1.axhline(y=0.2, color='r', linestyle='--', label='Success threshold (0.2)')
        ax1.set_xlabel('Question Number')
        ax1.set_ylabel('Compression Index')
        ax1.set_title('Mirror Compression Trajectory')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Edge accumulation
        ax2.plot(x, y_edges, 'g-o', linewidth=2, markersize=4)
        ax2.axhline(y=15, color='r', linestyle='--', label='Success threshold (15 edges)')
        ax2.set_xlabel('Question Number')
        ax2.set_ylabel('Edge Count')
        ax2.set_title('Semantic Graph Growth')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig('reports/mirror_compression_trajectory.png', dpi=150)
        print(f"[SAVED] reports/mirror_compression_trajectory.png")
        
    except ImportError:
        print(f"[SKIP] matplotlib not available for plotting")
    
    print("\n" + "="*70)
    print(" TEST COMPLETE".center(70))
    print("="*70 + "\n")
    
    return output

if __name__ == "__main__":
    result = test_compression_trajectory()
    
    if result['success']:
        print("\n✅ Mirror compression trajectory PROVEN")
        print(f"   Final compression: {result['analysis']['final_compression']:.3f}")
        print(f"   Edges added: {result['analysis']['edges_added']}")
    else:
        print("\n❌ Mirror compression trajectory NOT proven")
        print(f"   Final compression: {result['analysis']['final_compression']:.3f}")
        print(f"   Need to investigate LinguaCalc parsing")

