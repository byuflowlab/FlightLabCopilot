"""Navigation math. Pure functions, no state.

Positions are converted to a local east/north/up frame in metres around a
reference latitude/longitude, using the same flat-earth approximation as
``gpslog.py`` in byuflowlab/415gps. Over a flying field (a few hundred metres)
its error is far below the GPS noise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS = 6371000.0  # m, as in gpslog.py


def to_local(ref_lat: float, ref_lon: float, lat: float, lon: float) -> tuple[float, float]:
    """(east, north) in metres of (lat, lon) from (ref_lat, ref_lon)."""
    north = EARTH_RADIUS * math.radians(lat - ref_lat)
    east = EARTH_RADIUS * math.cos(math.radians(ref_lat)) * math.radians(lon - ref_lon)
    return east, north


def from_local(ref_lat: float, ref_lon: float, east: float, north: float) -> tuple[float, float]:
    """Inverse of :func:`to_local`."""
    lat = ref_lat + math.degrees(north / EARTH_RADIUS)
    lon = ref_lon + math.degrees(east / (EARTH_RADIUS * math.cos(math.radians(ref_lat))))
    return lat, lon


def wrap180(deg: float) -> float:
    """Angle wrapped to (-180, 180]."""
    a = math.fmod(deg + 180.0, 360.0)
    if a <= 0.0:
        a += 360.0
    return a - 180.0


def bearing_deg(d_east: float, d_north: float) -> float:
    """Compass bearing (0 = north, 90 = east) of a displacement, in [0, 360)."""
    return math.degrees(math.atan2(d_east, d_north)) % 360.0


# ---------------------------------------------------------------- waypoint bubble

def bubble_distance(de: float, dn: float, du: float, radius_h: float, radius_v: float) -> float:
    """Distance measured in bubble radii: <= 1 means inside.

    The bubble is an ellipsoid with horizontal radius ``radius_h`` and vertical
    half-height ``radius_v``; equal radii give a sphere.
    """
    return math.sqrt((de * de + dn * dn) / radius_h**2 + (du * du) / radius_v**2)


def _closest_t(p0, p1, w, scale) -> float:
    """Parameter t in [0, 1] of the point on segment p0->p1 closest to w,
    with each coordinate divided by ``scale`` first."""
    d = [(b - a) / s for a, b, s in zip(p0, p1, scale)]
    r = [(c - a) / s for a, c, s in zip(p0, w, scale)]
    dd = sum(x * x for x in d)
    if dd == 0.0:
        return 0.0
    return min(1.0, max(0.0, sum(x * y for x, y in zip(d, r)) / dd))


@dataclass
class Approach:
    distance: float      # 3-D distance at the closest point (m)
    horizontal: float    # horizontal part of that distance (m)
    vertical: float      # aircraft height minus waypoint height there (m), + = above
    bubble: float        # smallest bubble distance along the segment (<= 1 is a hit)


def segment_approach(p0, p1, w, radius_h: float, radius_v: float) -> Approach:
    """Closest approach to waypoint ``w`` while flying straight from ``p0`` to ``p1``.

    Points are (east, north, up) in metres. At 5 Hz and flying speed the
    aircraft moves several metres between fixes, so checking only the fixes
    would overstate a miss; the straight line between them is a better guess.
    ``p0`` may be None (first fix), in which case only ``p1`` is used.
    """
    if p0 is None:
        p0 = p1
    t = _closest_t(p0, p1, w, (1.0, 1.0, 1.0))
    c = [a + t * (b - a) for a, b in zip(p0, p1)]
    de, dn, du = c[0] - w[0], c[1] - w[1], c[2] - w[2]
    # The hit test uses the bubble's own shape, which can pick a different
    # point on the segment than the plain 3-D closest point when radii differ.
    tb = _closest_t(p0, p1, w, (radius_h, radius_h, radius_v))
    cb = [a + tb * (b - a) for a, b in zip(p0, p1)]
    bub = bubble_distance(cb[0] - w[0], cb[1] - w[1], cb[2] - w[2], radius_h, radius_v)
    return Approach(
        distance=math.sqrt(de * de + dn * dn + du * du),
        horizontal=math.hypot(de, dn),
        vertical=du,
        bubble=bub,
    )


# ---------------------------------------------------------------- steering

@dataclass
class Steering:
    distance_h: float           # horizontal distance to the waypoint (m)
    distance_3d: float          # straight-line distance (m)
    bearing: float              # compass bearing to the waypoint (deg)
    relative: float | None      # turn needed relative to the ground track (deg, + = right); None when too slow
    turn: str                   # "LEFT", "RIGHT", "AHEAD" or "" (no track)
    climb: float                # waypoint height minus aircraft height (m), + = climb
    vertical: str               # "CLIMB", "DESCEND" or "HOLD"
    time_to_go: float | None    # s at the current ground speed along the track, None if not closing


def steering(pos, wp, ground_course_deg: float, speed: float, *, radius_v: float,
             min_speed: float = 2.0, ahead_deg: float = 10.0) -> Steering:
    """Where to fly from ``pos`` to ``wp`` (both (east, north, up) in metres).

    Directions are relative to the GPS ground track, not the nose heading: in
    a crosswind the track is what has to point at the waypoint. Below
    ``min_speed`` the track is noise, so no turn is given.
    """
    de, dn, du = wp[0] - pos[0], wp[1] - pos[1], wp[2] - pos[2]
    dist_h = math.hypot(de, dn)
    brg = bearing_deg(de, dn)
    rel = None
    turn = ""
    ttg = None
    if speed >= min_speed and not math.isnan(ground_course_deg):
        rel = wrap180(brg - ground_course_deg)
        turn = "AHEAD" if abs(rel) <= ahead_deg else ("RIGHT" if rel > 0 else "LEFT")
        closing = speed * math.cos(math.radians(rel))
        if closing > 0.5:
            ttg = dist_h / closing
    if abs(du) <= 0.5 * radius_v:
        vert = "HOLD"
    else:
        vert = "CLIMB" if du > 0 else "DESCEND"
    return Steering(
        distance_h=dist_h,
        distance_3d=math.sqrt(dist_h * dist_h + du * du),
        bearing=brg,
        relative=rel,
        turn=turn,
        climb=du,
        vertical=vert,
        time_to_go=ttg,
    )


# ---------------------------------------------------------------- boundary

def ellipse_value(center_lat: float, center_lon: float, semi_east: float, semi_north: float,
                  rotation_deg: float, lat: float, lon: float) -> float:
    """> 1 outside the boundary ellipse. Same formula as ``gpslog.py``.

    ``semi_east`` and ``semi_north`` are the semi-axes before rotation (gpslog's
    ``bdy_R``), ``rotation_deg`` is gpslog's ``bdy_theta`` in degrees.
    """
    dx, dy = to_local(center_lat, center_lon, lat, lon)
    th = math.radians(rotation_deg)
    ct, st = math.cos(th), math.sin(th)
    return ((dx * ct + dy * st) / semi_east) ** 2 + ((dx * st - dy * ct) / semi_north) ** 2


def boundary_status(value: float, warn_at: float = 0.7) -> str:
    """'out' beyond the ellipse, 'warn' past ``warn_at`` (gpslog's 0.7), else 'ok'."""
    if value > 1.0:
        return "out"
    if value > warn_at:
        return "warn"
    return "ok"
