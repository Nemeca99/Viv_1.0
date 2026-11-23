def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    current_state = options.get("current_state", {})
    
    completed_tasks = set()
    for task, status in current_state.items():
        if status == "completed":
            completed_tasks.add(task)
    
    available_tasks = []
    for task in data:
        task_name = task.get("task")
        dependencies = task.get("dependencies", [])
        if all(dep in completed_tasks for dep in dependencies):
            available_tasks.append(task_name)
    
    return {"results": available_tasks}