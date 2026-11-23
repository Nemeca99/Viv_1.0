import json
import copy
import heapq

from helpers import is_valid_task, get_eligible_tasks


def solve(value):
    data = value.get('data', [])
    options = value.get('options', {})

    # Create a deep copy of the data to avoid mutating the input
    tasks = copy.deepcopy(data)

    # Build a map of task id to task for quick lookup
    task_map = {task['id']: task for task in tasks}

    # Build a map of task id to its dependencies
    dependency_map = {}
    for task in tasks:
        dependency_map[task['id']] = task.get('dependencies', [])

    # Build a map of task id to its status
    status_map = {task['id']: task['status'] for task in tasks}

    # Build a map of task id to its priority (default 0 if not present)
    priority_map = {task['id']: task.get('priority', 0) for task in tasks}

    # Build a list of eligible task ids
    eligible_ids = get_eligible_tasks(task_map, dependency_map, status_map, priority_map)

    # Sort eligible tasks by descending priority, then ascending id
    eligible_ids.sort(key=lambda x: (-priority_map[x], x))

    # Return the result in the required format
    return {'order': eligible_ids}