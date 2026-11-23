"""Require removal of only the post-commit destructive retention try block."""
import ast
from pathlib import Path

root = Path('L:/LocalCoder')
before = ast.parse((root / '.opencode/evals/measured_learning_20261117/terminal_before.py').read_text(encoding='utf-8'))
current = (root / 'workspace/autonomy/terminal_neuron_learning.py').read_text(encoding='utf-8')
after = ast.parse(current)

class RemoveRetention(ast.NodeTransformer):
    removed = 0
    def visit_Try(self, node):
        direct = [n for statement in node.body for n in ast.walk(statement)]
        destructive = {n.func.attr for n in direct if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                       and isinstance(n.func.value, ast.Name) and n.func.value.id == 'shutil'}
        if {'move', 'rmtree'} <= destructive and len(node.body) <= 4:
            self.removed += 1
            return None
        return self.generic_visit(node)

cleaner = RemoveRetention()
expected = cleaner.visit(before)
assert cleaner.removed == 1
assert ast.dump(expected, include_attributes=False) == ast.dump(after, include_attributes=False), 'Only retention block may change'
assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and
               isinstance(n.func.value, ast.Name) and n.func.value.id == 'shutil' and n.func.attr in ('move','rmtree')
               for n in ast.walk(after))
compile(current, '<native learner>', 'exec')
print('PASS: history retained; native learner parses; all other logic unchanged')
