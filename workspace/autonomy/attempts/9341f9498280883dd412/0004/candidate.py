def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    current_state = options.get("current_state", {})
    
    task_to_dependencies = {}
    for task in data:
        task_to_dependencies[task["task"]] = task["dependencies"]
    
    task_to_status = {}
    for task in task_to_dependencies:
        task_to_status[task] = current_state.get(task, "not_started")
    
    runnable_tasks = []
    for task, dependencies in task_to_dependencies.items():
        if all(dep in current_state and current_state[dep] == "completed" for dep in dependencies):
            if task_to_status[task] == "not_started" and task not in current_state or current_state[task] != "failed" and current_state[task] != "in_progress":
                runnable_tasks.append(task)
    
    return {"results": runnable_tasks}