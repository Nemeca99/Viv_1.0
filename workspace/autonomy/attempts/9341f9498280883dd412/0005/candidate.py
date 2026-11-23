def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    current_state = options.get("current_state", {})
    
    task_to_dependencies = {}
    for task_info in data:
        task = task_info["task"]
        dependencies = task_info["dependencies"]
        task_to_dependencies[task] = dependencies
    
    task_to_status = {}
    for task in task_to_dependencies:
        task_to_status[task] = current_state.get(task, "not_started")
    
    runnable_tasks = []
    for task, dependencies in task_to_dependencies.items():
        if task_to_status[task] == "not_started":
            all_deps_completed = True
            for dep in dependencies:
                if dep not in current_state or current_state[dep] != "completed":
                    all_deps_completed = False
                    break
            if all_deps_completed:
                runnable_tasks.append(task)
    
    return {"results": runnable_tasks}