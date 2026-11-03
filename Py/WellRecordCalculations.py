"""Calculate well spacing from the assigned TCA; keep missing values explicit."""
import math


def calculate_spacing(wps):
    if wps is None or (isinstance(wps, str) and not wps.strip()):
        return {"Spacing_Ft": None, "DA_Ft": None, "status": "MissingWps"}
    if isinstance(wps, bool):
        return {"Spacing_Ft": None, "DA_Ft": None, "status": "InvalidWps"}
    try:
        value = float(wps)
    except (TypeError, ValueError, OverflowError):
        return {"Spacing_Ft": None, "DA_Ft": None, "status": "InvalidWps"}
    if not math.isfinite(value) or value <= 0:
        return {"Spacing_Ft": None, "DA_Ft": None, "status": "NonpositiveOrNonfiniteWps"}
    spacing = 5280.0 / value
    if not math.isfinite(spacing):
        return {"Spacing_Ft": None, "DA_Ft": None, "status": "CalculationOverflow"}
    return {"Spacing_Ft": spacing, "DA_Ft": spacing / 2.0, "status": "Calculated"}
