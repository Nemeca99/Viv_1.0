def solve(value):
    data = value.get('data', [])
    options = value.get('options', {})
    current_state = options.get('current_state', {})
    completed_tasks = [task for task, status in current_state.items() if status == 'completed']
    failed_tasks = [task for task, status in current_state.items() if status == 'failed']
    in_progress_tasks = [task for task, status in current_state.items() if status == 'in_progress']
    
    task_to_dependencies = {task: dependencies for task in data for dependencies in [task['dependencies']] if task['task'] == task}
    task_to_status = {task['task']: status for task in data for status in [task['status']] if task['task'] == task}
    
    def is_task_runnable(task):
        dependencies = task_to_dependencies.get(task, [])
        for dep in dependencies:
            if dep not in completed_tasks and dep not in in_progress_tasks:
                return False
        return True
    
    def is_task_failed(task):
        dependencies = task_to_dependencies.get(task, [])
        for dep in dependencies:
            if dep in failed_tasks:
                return True
        return False
    
    results = []
    for task in data:
        task_name = task['task']
        if task_name in completed_tasks or task_name in in_progress_tasks:
            continue
        if is_task_runnable(task_name):
            results.append(task_name)
    
    return {"results": results}
