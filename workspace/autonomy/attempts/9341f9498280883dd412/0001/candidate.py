def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    current_state = options.get("current_state", {})
    
    completed_tasks = [task for task, status in current_state.items() if status == "completed"]
    failed_tasks = [task for task, status in current_state.items() if status == "failed"]
    in_progress_tasks = [task for task, status in current_state.items() if status == "in_progress"]
    
    task_to_dependencies = {task: dependencies for task in data for dependencies in [task["dependencies"]]}
    task_to_status = {task: current_state.get(task, "not_started") for task in task_to_dependencies}
    
    runnable_tasks = []
    
    for task in task_to_dependencies:
        dependencies = task_to_dependencies[task]
        if all(dep in completed_tasks for dep in dependencies):
            if task_to_status[task] == "not_started" and task not in failed_tasks and task not in in_progress_tasks:
                runnable_tasks.append(task)
    
    return {"results": runnable_tasks}