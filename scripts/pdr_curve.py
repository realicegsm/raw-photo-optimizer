"""
Sensor Photographic Dynamic Range (PDR) reference curve — Sony ILCE-6100.

Source: measured PDR chart from PhotonsToPhotos (photonstophotos.net/Charts/PDR.htm),
contributed by the user for this camera specifically. Values are EV of usable
dynamic range at each ISO, not the marketing "typical DR" figure.

This replaces fixed absolute DR thresholds (e.g. "dr_ev > 12.0") in the pipeline,
which were calibrated for full-frame sensors with 14+ EV headroom and never
actually triggered on this camera (base ISO ceiling is ~10.5 EV, not 12+).

Instead, decisions should be relative to how close the measured scene DR is to
the sensor's actual physical ceiling *at the shot's ISO*, since that ceiling
drops by roughly 5-6 EV between base ISO and ISO 25600.
"""
import math

# (ISO, Photographic Dynamic Range in EV) — measured, PhotonsToPhotos
_PDR_TABLE_RAW = [
    (100, 10.54), (126, 10.25), (159, 10.06), (200, 9.82),
    (251, 9.54),  (318, 9.14),  (400, 9.21),  (503, 8.86),
    (636, 8.51),  (800, 8.16),  (1006, 7.85), (1273, 7.49),
    (1600, 7.18), (2011, 6.87), (2546, 6.49), (3200, 6.21),
    (4022, 5.87), (5091, 5.52), (6400, 5.25), (8045, 4.86),
    (10183, 4.53), (12800, 4.19), (16090, 3.90), (20366, 3.51),
    (25600, 3.24), (32180, 3.44), (40731, 3.12), (51200, 2.78),
]


def _build_monotonic_table():
    """
    Enforce non-increasing PDR with rising ISO.

    The raw measurement has a bump at ISO 32180 (3.44 vs 3.24 at 25600) — a
    known artifact of extended/"Hi" ISO modes where digital gain is applied
    after the ADC. Left as-is, that bump could make the interpolation return
    a *higher* ceiling for a higher ISO, which would silently disable
    denoising exactly where it's needed most.
    """
    fixed = []
    running_min = float("inf")
    for iso, pdr in _PDR_TABLE_RAW:
        running_min = min(running_min, pdr)
        fixed.append((iso, running_min))
    return fixed


PDR_TABLE = _build_monotonic_table()
BASE_ISO = PDR_TABLE[0][0]


def sensor_pdr_ceiling(iso) -> float:
    """Interpolated photographic DR ceiling (EV) for a given ISO (log2-scale interpolation)."""
    try:
        iso = float(iso)
    except (TypeError, ValueError):
        iso = BASE_ISO
    if iso <= 0:
        iso = BASE_ISO

    table = PDR_TABLE
    if iso <= table[0][0]:
        return table[0][1]
    if iso >= table[-1][0]:
        return table[-1][1]
    for (iso_lo, dr_lo), (iso_hi, dr_hi) in zip(table, table[1:]):
        if iso_lo <= iso <= iso_hi:
            t = (math.log2(iso) - math.log2(iso_lo)) / (math.log2(iso_hi) - math.log2(iso_lo))
            return dr_lo + t * (dr_hi - dr_lo)
    return table[-1][1]


def pdr_delta_ev(iso, base_iso: float = BASE_ISO) -> float:
    """How many EV of PDR have been lost relative to base ISO (always >= 0)."""
    return max(0.0, sensor_pdr_ceiling(base_iso) - sensor_pdr_ceiling(iso))


def dr_headroom_ratio(dr_ev, iso) -> float:
    """
    Measured scene DR as a fraction of the sensor's ceiling at this ISO.
    Values approaching/exceeding 1.0 mean the scene's contrast is at or beyond
    what the sensor can capture cleanly at this ISO — the signal to lean on
    DRC/highlight recovery harder, regardless of what the absolute EV number is.
    """
    try:
        dr_ev = float(dr_ev)
    except (TypeError, ValueError):
        return 0.0
    ceiling = sensor_pdr_ceiling(iso)
    if ceiling <= 0:
        return 0.0
    return dr_ev / ceiling


def interp_control_points(points, x):
    """
    Generic linear interpolation over a list of (x, y1, y2, ...) control points,
    clamped at the ends. Used to turn a continuous driver (e.g. delta_ev) into
    smoothly-varying output parameters instead of stepped thresholds.
    """
    if x <= points[0][0]:
        return points[0][1:]
    if x >= points[-1][0]:
        return points[-1][1:]
    for p0, p1 in zip(points, points[1:]):
        x0, x1 = p0[0], p1[0]
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0)
            return tuple(y0 + t * (y1 - y0) for y0, y1 in zip(p0[1:], p1[1:]))
    return points[-1][1:]
