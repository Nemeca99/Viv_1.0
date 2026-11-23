def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    current_state = options.get("current_state", {})
    
    completed_tasks = set(current_state.get("completed", []))
    failed_tasks = set(current_state.get("failed", []))
    in_progress_tasks = set(current_state.get("in_progress", []))
    
    task_to_dependency = {task: set(dependencies) for task in data for dependencies in [task.get("dependencies", [])]}
    task_to_name = {task.get("task"): task for task in data}
    
    available_tasks = []
    
    for task, dependencies in task_to_dependency.items():
        if task in failed_tasks or task in in_progress_tasks:
            continue
        if all(dep in completed_tasks for dep in dependencies):
            available_tasks.append(task)
    
    return {"results": available_tasks}
