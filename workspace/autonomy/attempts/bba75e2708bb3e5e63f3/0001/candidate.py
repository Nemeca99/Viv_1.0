def solve(input):
    data = input.get('data', [])
    current_state = input.get('current_state', {})
    tasks = []
    for task in data:
        task_name = task.get('task')
        dependencies = task.get('dependencies', [])
        all_deps_completed = True
        for dep in dependencies:
            if current_state.get(dep, 'not_started') != 'completed':
                all_deps_completed = False
                break
        if all_deps_completed and current_state.get(task_name, 'not_started') == 'not_started':
            tasks.append(task_name)
    return {"results": tasks}
