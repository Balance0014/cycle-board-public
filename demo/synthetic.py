"""SYNTHETIC fixture. Not market data. Not a vendor series.

`pipeline/run_all.py` does not read this module. Tests use it only to
exercise cycle arithmetic without touching `data/raw/`, `results/`, or `看板/`.
"""
import datetime as dt


def monthly(start: int = 1971, end: int = 2025):
    """Deterministic monthly curve: smooth growth plus a four-year wobble."""
    rows = []
    i = 0
    for year in range(start, end + 1):
        for month in range(1, 13):
            wobble = 1 + 0.02 * ((year % 4) - 1.5)
            price = 100 * (1.004 ** i) * wobble
            rows.append((dt.date(year, month, 1), price))
            i += 1
    return rows
