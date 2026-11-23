def solve(value):
    data = value.get('data', [])
    options = value.get('options', {})
    current_state = options.get('current_state', {})
    query = options.get('query', '')
    sort = options.get('sort', '')
    limit = options.get('limit', 0)

    task_to_dependency = {task['task']: set(task['dependencies']) for task in data}
    dependency_to_tasks = {dep: [] for task in data for dep in task_to_dependency[task['task']]}

    for task in data:
        for dep in task_to_dependency[task['task']]:
            dependency_to_tasks[dep].append(task['task'])

    completed_tasks = set(current_state.get('completed', []))
    failed_tasks = set(current_state.get('failed', []))
    in_progress_tasks = set(current_state.get('in_progress', []))

    ready_tasks = []

    for task in data:
        task_name = task['task']
        dependencies = task_to_dependency[task_name]

        if all(dep in completed_tasks for dep in dependencies):
            if task_name not in failed_tasks and task_name not in in_progress_tasks:
                ready_tasks.append(task_name)

    if query == 'tasks with status failed':
        ready_tasks = [task['task'] for task in data if task['task'] in failed_tasks]
    elif query == 'tasks with status completed':
        ready_tasks = [task['task'] for task in data if task['task'] in completed_tasks]
    elif query == 'tasks with status pending':
        ready_tasks = [task['task'] for task in data if task['task'] not in completed_tasks and task['task'] not in failed_tasks and task['task'] not in in_progress_tasks]
    elif query == 'tasks with status in progress':
        ready_tasks = [task['task'] for task in data if task['task'] in in_progress_tasks]
    elif query == 'ready_tasks':
        ready_tasks = [task['task'] for task in data if all(dep in completed_tasks for dep in task_to_dependency[task['task']]) and task['task'] not in failed_tasks and task['task'] not in in_progress_tasks]

    if sort == 'alphabetical':
        ready_tasks.sort()
    elif sort == 'reverse_alphabetical':
        ready_tasks.sort(reverse=True)
    elif sort == 'dependency_order':
        ready_tasks.sort(key=lambda x: len(task_to_dependency[x]))
    elif sort == 'none':
        pass

    if limit > 0:
        ready_tasks = ready_tasks[:limit]

    return {"results": ready_tasks}