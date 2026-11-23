def solve(data, options):
    baseline_task = options['baseline_task']
    comparison_type = options['comparison_type']
    
    comparison = {}
    difference = {}
    
    for item in data:
        task = item['task']
        if comparison_type == 'time':
            metric = item.get('time', None)
            baseline_metric = next((i.get('time') for i in data if i['task'] == baseline_task), None)
        elif comparison_type == 'success':
            metric = item.get('success', None)
            baseline_metric = next((i.get('success') for i in data if i['task'] == baseline_task), None)
        elif comparison_type == 'error':
            metric = item.get('error', None)
            baseline_metric = next((i.get('error') for i in data if i['task'] == baseline_task), None)
        else:
            metric = None
            baseline_metric = None
        
        if metric is not None and baseline_metric is not None:
            comparison[task] = {
                'metric': metric,
                'baseline': baseline_metric,
                'relative': metric - baseline_metric
            }
            difference[task] = metric - baseline_metric
        else:
            comparison[task] = {'metric': metric, 'baseline': baseline_metric, 'relative': None}
            difference[task] = None
    
    return {"comparison": comparison, "difference": difference}
