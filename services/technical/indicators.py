"""Deterministic Python extension point; not required by Node demo."""
def sma(values, window):
    if window < 1 or len(values) < window:
        raise ValueError("insufficient data or invalid window")
    return sum(values[-window:]) / window

