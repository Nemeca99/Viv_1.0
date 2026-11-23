def is_valid_task(task):
    return task['status'] in ['queued', 'retry']


def get_eligible_tasks(task_map, dependency_map, status_map, priority_map):
    eligible_ids = []
    for task_id, task in task_map.items():
        if task['status'] not in ['queued', 'retry']:
            continue

        # Check if all dependencies have status exactly 'tested'
        dependencies = dependency_map.get(task_id, [])
        valid = True
        for dependency_id in dependencies:
            if status_map.get(dependency_id, '') != 'tested':
                valid = False
                break

        if valid:
            eligible_ids.append(task_id)

    return eligible_ids