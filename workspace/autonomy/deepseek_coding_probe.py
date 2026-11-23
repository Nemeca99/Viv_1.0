"""Bounded local model coding probe; raw outputs are never repaired."""
import json
import subprocess
import urllib.request
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from viv_code_learning_loop import extract_code

TASKS = [
    ("Implement unique_in_order(items): return unique hashable items in first-occurrence order. Return only Python code.",
     "assert unique_in_order([1,2,1,3,2]) == [1,2,3]\nassert unique_in_order([]) == []"),
    ("Implement is_palindrome(s): compare a string case-insensitively. Return only Python code.",
     "assert is_palindrome('AbA') is True\nassert is_palindrome('ab') is False"),
    ("Implement first_negative(values): return the first negative number or None if there is none. Return only Python code.",
     "assert first_negative([3,0,-2,-5]) == -2\nassert first_negative([]) is None\nassert first_negative([0,4]) is None"),
    ("Implement rotate_right(items, k): return a new list rotated right by k positions; support empty lists and k larger than length. Return only Python code.",
     "assert rotate_right([1,2,3],1) == [3,1,2]\nassert rotate_right([1,2,3],4) == [3,1,2]\nassert rotate_right([],2) == []\nassert rotate_right([1,2],0) == [1,2]"),
]

def main():
    results = []
    for prompt, assertions in TASKS:
        request = urllib.request.Request('http://127.0.0.1:1234/v1/chat/completions',
            data=json.dumps({'messages':[{'role':'system','content':'Return only executable Python code.'},{'role':'user','content':prompt}], 'max_tokens':180,'temperature':0, 'stop':['\nUSER:', '\nSYSTEM:']}).encode(),
            headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = json.load(response)['choices'][0]['message']['content']
        source = raw + '\n' + assertions + '\n'
        proc = subprocess.run(['docker','run','--rm','-i','--network','none','--memory','256m','--cpus','1','--pids-limit','32','--read-only','--entrypoint','python','viv-vm:1','-I','-'], input=source, text=True, capture_output=True, timeout=30)
        extracted = extract_code(raw, 'python')
        adapted = subprocess.run(['docker','run','--rm','-i','--network','none','--memory','256m','--cpus','1','--pids-limit','32','--read-only','--entrypoint','python','viv-vm:1','-I','-'], input=extracted+'\n'+assertions+'\n', text=True, capture_output=True, timeout=30)
        results.append({'prompt':prompt,'raw':raw,'exit_code':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr,
                        'extracted':extracted, 'adapted_exit_code':adapted.returncode, 'adapted_stderr':adapted.stderr})
        print(json.dumps(results[-1]), flush=True)
    print(json.dumps({'raw_passed':sum(r['exit_code']==0 for r in results),
                      'extracted_passed':sum(r['adapted_exit_code']==0 for r in results),
                      'total':len(results)}), flush=True)

if __name__ == '__main__':
    main()
