def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    current_state = options.get("current_state", {})
    
    # Build a map of task dependencies
    dependencies_map = {}
    for task in data:
        task_name = task["task"]
        dependencies = task["dependencies"]
        dependencies_map[task_name] = dependencies
    
    # Build a map of task status
    task_status = {task_name: current_state.get(task_name, "not_started") for task_name in dependencies_map}
    
    # Find tasks that can be executed next
    runnable_tasks = []
    for task_name, dependencies in dependencies_map.items():
        all_dependencies_met = True
        for dependency in dependencies:
            if task_status.get(dependency, "not_started") != "completed":
                all_dependencies_met = False
                break
        if all_dependencies_met and task_status[task_name] == "not_started":
            runnable_tasks.append(task_name)
    
    return {"results": runnable_tasks}