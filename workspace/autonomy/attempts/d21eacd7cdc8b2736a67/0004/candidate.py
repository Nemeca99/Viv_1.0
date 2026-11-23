def solve(data, options):
    baseline_task = options['baseline_task']
    comparison_type = options['comparison_type']
    comparison = {}
    difference = {}
    
    for task in data:
        task_name = task['task']
        if task_name == baseline_task:
            continue
        if comparison_type == 'time':
            baseline_time = next((t['time'] for t in data if t['task'] == baseline_task), None)
            if baseline_time is not None:
                diff = task['time'] - baseline_time
                comparison[task_name] = task['time']
                difference[task_name] = diff
        elif comparison_type == 'success':
            baseline_success = next((t['success'] for t in data if t['task'] == baseline_task), None)
            if baseline_success is not None:
                comparison[task_name] = task['success']
                difference[task_name] = task['success'] - baseline_success
        elif comparison_type == 'error':
            baseline_error = next((t['error'] for t in data if t['task'] == baseline_task), None)
            if baseline_error is not None:
                comparison[task_name] = task['error']
                difference[task_name] = task['error'] - baseline_error
    
    return {'comparison': comparison, 'difference': difference}
