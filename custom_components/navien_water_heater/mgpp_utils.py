"""Utility helpers for MGPP value conversions."""

def to_celsius_display(raw_half: int | float) -> float:
    """Convert half-degree Celsius encoded integer to Celsius float."""
    try:
        return float(raw_half) / 2.0
    except Exception:
        return 0.0

def to_celsius_debug(raw_tenths: int | float) -> float:
    """Convert tenth-degree Celsius encoded integer to Celsius float."""
    try:
        return float(raw_tenths) / 10.0
    except Exception:
        return 0.0


