from helpers import sort_tasks

import json
import sys
import os
from collections import defaultdict


def solve(value):
    data = value.get('data', [])
    options = value.get('options', {})

    # Filter out tasks that are not queued or retry
    eligible_tasks = [task for task in data if task['status'] in ['queued', 'retry']]

    # Build dependency graph
    dependency_graph = defaultdict(set)
    task_id_to_task = {}
    for task in data:
        task_id_to, task = task['id'], task
        task_id_to_task[task_id] = task
        if 'dependencies' in task:
            for dep_id in task['dependencies']:
                dependency_graph[dep_id].add(task_id)

    # Check for dependencies and collect eligible tasks
    eligible_tasks = []
    for task in eligible_tasks:
        task_id = task['id']
        all_deps_met = True
        for dep_id in task['dependencies']:
            if dep_id not in task_id_to_task or task_id_to_task[dep_id]['status'] not in ['tested']:
                all_deps_met = False
                break
        if all_deps_met:
            eligible_tasks.append(task)

    # Sort eligible tasks by descending priority, then ascending id
    eligible_tasks = sort_tasks(eligible_tasks)

    # Extract ids of eligible tasks
    order = [task['id'] for task in eligible_tasks]

    return {'order': order}

if __name__ == '__main__':
    value = json.load(sys.stdin)
    result = solve(value)
    print(json.dumps(result))