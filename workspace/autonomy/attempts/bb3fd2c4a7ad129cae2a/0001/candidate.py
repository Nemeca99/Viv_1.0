def solve(value):
    from collections import defaultdict

    def filter_completed_tasks(data):
        return [task for task in data if task.get("status") == "completed"]

    def sort_tasks_by_task(tasks):
        return sorted(tasks, key=lambda x: x.get("task"))

    def get_sorted_completed_tasks(data):
        completed_tasks = filter_completed_tasks(data)
        return sort_tasks_by_task(completed_tasks)

    return {"results": get_sorted_completed_tasks(value["input"]["data"])}
