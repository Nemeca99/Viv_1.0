from helpers import sort_tasks

def solve(value):
    data = value.get('data', [])
    options = value.get('options', {})

    eligible_tasks = []
    for task in data:
        if task['status'] not in ['queued', 'retry']:
            continue
        
        dependencies = task.get('dependencies', [])
        all_deps_met = True
        for dep_id in dependencies:
            dep = next((t for t in data if t['id'] == dep_id), None)
            if not dep or dep['status'] not in ['queued', 'retry']:
                all_deps_met = False
                break
        
        if all_deps_met:
            eligible_tasks.append(task)

    sorted_tasks = sort_tasks(eligible_tasks)
    return {'order': [task['id'] for task in sorted_tasks]}