def solve(value):
    comparison = {}
    difference = {}
    baseline_task = value['options']['baseline_task']
    data = value['data']
    
    for task in data:
        task_name = task['task']
        evaluation = task['evaluation']
        if task_name == baseline_task:
            baseline = evaluation
        else:
            comparison[task_name] = evaluation
    
    for task in data:
        task_name = task['task']
        evaluation = task['evaluation']
        if task_name != baseline_task:
            if evaluation['success']:
                difference[task_name] = evaluation
            else:
                if 'error' in evaluation:
                    difference[task_name] = evaluation
    
    return {"results": difference}