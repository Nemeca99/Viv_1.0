from collections import defaultdict


def sort_tasks(tasks):
    # Sort eligible tasks by descending priority, then ascending id
    return sorted(tasks, key=lambda x: (-x.get('priority', 0), x['id']))