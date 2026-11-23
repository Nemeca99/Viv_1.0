def solve(value):
    data = value.get('data', [])
    options = value.get('options', {})
    current_state = options.get('current_state', {})
    
    completed_tasks = set(task for task, status in current_state.items() if status == 'completed')
    failed_tasks = set(task for task, status in current_state.items() if status == 'failed')
    in_progress_tasks = set(task for task, status in current_state.items() if status == 'in_progress')
    
    task_to_dependencies = {}
    for task in data:
        task_name = task['task']
        dependencies = task['dependencies']
        task_to_dependencies[task_name] = dependencies
    
    results = []
    for task in data:
        task_name = task['task']
        if task_name in completed_tasks or task_name in in_progress_tasks:
            continue
        all_deps_completed = True
        for dep in task_to_dependencies[task_name]:
            if dep not in completed_tasks or dep in failed_tasks:
                all_deps_completed = False
                break
        if all_deps_completed:
            results.append(task_name)
    
    return {"results": results}