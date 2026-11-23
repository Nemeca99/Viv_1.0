def calculate_total(numbers):
    return sum(numbers)

def calculate_average(numbers):
    return sum(numbers) / len(numbers)

def calculate_median(numbers):
    sorted_numbers = sorted(numbers)
    middle_index = len(numbers) // 2
    if len(numbers) % 2 == 0:
        return (sorted_numbers[middle_index - 1] + sorted_numbers[middle_index]) / 2
    else:
        return sorted_numbers[middle_index]

def format_summary_table(numbers):
    total = calculate_total(numbers)
    avg = calculate_average(numbers)
    median = calculate_median(numbers)
    table = f"Total: {total}, Average: {avg}, Median: {median}"
    return table

numbers = [1, 2, 3, 4]
print(format_summary_table(numbers))