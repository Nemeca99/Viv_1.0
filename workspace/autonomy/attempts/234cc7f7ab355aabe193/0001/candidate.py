def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    completed_tasks = set(options.get("current_state", {}).keys())
    
    task_to_dependencies = {task: set(dependencies) for task in data for dependencies in [task.get("dependencies", [])]}
    task_to_name = {task.get("task"): task for task in data}
    
    available_tasks = []
    for task in data:
        task_name = task.get("task")
        dependencies = task.get("dependencies", [])
        if all(dep in completed_tasks for dep in dependencies):
            available_tasks.append(task_name)
    
    return {"results": available_tasks}