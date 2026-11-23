def solve(value):
    from collections import defaultdict
    import heapq

    def get_success_likelihood(task):
        if task['status'] == 'completed':
            return 1.0
        elif task['status'] == 'failed':
            return 0.0
        else:
            return 0.5

    def get_dependency_order(task):
        return len(task['dependencies'])

    def get_task_priority(task):
        return get_success_likelihood(task), -get_dependency_order(task)

    def get_task_status(task):
        if task['status'] == 'completed':
            return 'completed'
        elif task['status'] == 'failed':
            return 'failed'
        else:
            return 'pending'

    def get_task_dependencies(task):
        return task['dependencies']

    def get_task_name(task):
        return task['task']

    def get_task_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task
        return None

    def get_missing_dependencies(task, completed_tasks):
        missing = []
        for dep in task['dependencies']:
            if dep not in completed_tasks:
                missing.append(dep)
        return missing

    def get_task_order(tasks, completed_tasks):
        ordered_tasks = []
        for task in tasks:
            if task['task'] in completed_tasks:
                ordered_tasks.append(task)
        return ordered_tasks

    def get_next_tasks(tasks, completed_tasks, options):
        next_tasks = []
        for task in tasks:
            if task['task'] not in completed_tasks:
                missing = get_missing_dependencies(task, completed_tasks)
                if not missing:
                    next_tasks.append(task)
        return next_tasks

    def get_task_status_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task['status']
        return 'pending'

    def get_task_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task
        return None

    def get_task_order(tasks, completed_tasks):
        ordered_tasks = []
        for task in tasks:
            if task['task'] in completed_tasks:
                ordered_tasks.append(task)
        return ordered_tasks

    def get_task_status_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task['status']
        return 'pending'

    def get_task_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task
        return None

    def get_task_order(tasks, completed_tasks):
        ordered_tasks = []
        for task in tasks:
            if task['task'] in completed_tasks:
                ordered_tasks.append(task)
        return ordered_tasks

    def get_task_status_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task['status']
        return 'pending'

    def get_task_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task
        return None

    def get_task_order(tasks, completed_tasks):
        ordered_tasks = []
        for task in tasks:
            if task['task'] in completed_tasks:
                ordered_tasks.append(task)
        return ordered_tasks

    def get_task_status_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task['status']
        return 'pending'

    def get_task_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task
        return None

    def get_task_order(tasks, completed_tasks):
        ordered_tasks = []
        for task in tasks:
            if task['task'] in completed_tasks:
                ordered_tasks.append(task)
        return ordered_tasks

    def get_task_status_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task['status']
        return 'pending'

    def get_task_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task
        return None

    def get_task_order(tasks, completed_tasks):
        ordered_tasks = []
        for task in tasks:
            if task['task'] in completed_tasks:
                ordered_tasks.append(task)
        return ordered_tasks

    def get_task_status_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task['status']
        return 'pending'

    def get_task_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task
        return None

    def get_task_order(tasks, completed_tasks):
        ordered_tasks = []
        for task in tasks:
            if task['task'] in completed_tasks:
                ordered_tasks.append(task)
        return ordered_tasks

    def get_task_status_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task['status']
        return 'pending'

    def get_task_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task
        return None

    def get_task_order(tasks, completed_tasks):
        ordered_tasks = []
        for task in tasks:
            if task['task'] in completed_tasks:
                ordered_tasks.append(task)
        return ordered_tasks

    def get_task_status_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task['status']
        return 'pending'

    def get_task_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task
        return None

    def get_task_order(tasks, completed_tasks):
        ordered_tasks = []
        for task in tasks:
            if task['task'] in completed_tasks:
                ordered_tasks.append(task)
        return ordered_tasks

    def get_task_status_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task['status']
        return 'pending'

    def get_task_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task
        return None

    def get_task_order(tasks, completed_tasks):
        ordered_tasks = []
        for task in tasks:
            if task['task'] in completed_tasks:
                ordered_tasks.append(task)
        return ordered_tasks

    def get_task_status_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task['status']
        return 'pending'

    def get_task_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task
        return None

    def get_task_order(tasks, completed_tasks):
        ordered_tasks = []
        for task in tasks:
            if task['task'] in completed_tasks:
                ordered_tasks.append(task)
        return ordered_tasks

    def get_task_status_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task['status']
        return 'pending'

    def get_task_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task
        return None

    def get_task_order(tasks, completed_tasks):
        ordered_tasks = []
        for task in tasks:
            if task['task'] in completed_tasks:
                ordered_tasks.append(task)
        return ordered_tasks

    def get_task_status_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task['status']
        return 'pending'

    def get_task_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task
        return None

    def get_task_order(tasks, completed_tasks):
        ordered_tasks = []
        for task in tasks:
            if task['task'] in completed_tasks:
                ordered_tasks.append(task)
        return ordered_tasks

    def get_task_status_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task['status']
        return 'pending'

    def get_task_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task
        return None

    def get_task_order(tasks, completed_tasks):
        ordered_tasks = []
        for task in tasks:
            if task['task'] in completed_tasks:
                ordered_tasks.append(task)
        return ordered_tasks

    def get_task_status_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task['status']
        return 'pending'

    def get_task_from_name(tasks, name):
        for task in tasks:
            if task['task'] == name:
                return task
        return None

    def get_task_order(tasks, completed_tasks):
        ordered_tasks = []
        for task in tasks:
            if task['task'] in completed
    return {"results": []}