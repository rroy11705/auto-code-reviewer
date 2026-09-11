def divide(a: float, b: float) -> float:
    """Divide a by b."""
    return a / b


def compute_metrics(values: list) -> dict:
    """Compute sum and average for a list of numbers."""
    total = sum(values)
    count = len(values)
    # Warning: Calling divide with count=0 will raise ZeroDivisionError if values is empty
    avg = divide(total, count)
    return {"total": total, "average": avg}
