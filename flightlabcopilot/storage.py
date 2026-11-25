"""Where things are kept between sessions, and their defaults.

Everything lives in one data folder (``--data-dir``, default below):

- ``course.json``   waypoints, bubble size and flying-field boundary
- ``run.json``      progress through the course (completions, closest approaches)
- ``home.json``     the start point that altitudes are measured from
- ``settings.json`` GPS source, map background and display options
- ``map/``          background picture or downloaded imagery
- ``logs/``         one CSV per session, every fix plus events
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path

APP = "flightlabcopilot"


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "FlightLabCopilot"
    # same place as the student launchers, so both find the same course and recordings
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP


# Boundary and example waypoints are the ones in gpslog.py (byuflowlab/415gps).
DEFAULT_COURSE = {
    "name": "Example course",
    "radius_h": 2.5,   # m, horizontal bubble radius
    "radius_v": 2.5,   # m, vertical bubble half-height (equal to radius_h: a sphere)
    "waypoints": [
        {"name": "Start", "lat": 40.267641059243935, "lon": -111.63587333726502, "alt": 15.0},
        {"name": "Finish", "lat": 40.26678857, "lon": -111.63552403, "alt": 15.0},
    ],
    "boundary": {
        "enabled": True,
        "center_lat": 40.2672305,
        "center_lon": -111.635524,
        "semi_east": 98.353826748828595,
        "semi_north": 127.49653449395105,
        "rotation_deg": -15.0,
        "warn_at": 0.7,
    },
}

DEFAULT_SETTINGS = {
    "source": {"kind": "none", "port": "", "baudrate": 57600, "replay_speed": 1.0},
    "map": {"kind": "blank"},          # blank | image | tiles | off
    "min_speed": 2.0,                  # m/s; below this the ground track is not trusted
    "stale_after": 1.5,                # s without a fix before the display greys out
    "trail_seconds": 120,
    "chime": True,
    "theme": "day",
}


class Store:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root else default_data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "logs").mkdir(exist_ok=True)
        (self.root / "map").mkdir(exist_ok=True)

    # -- generic json -------------------------------------------------------
    def load(self, name: str, default=None):
        path = self.root / name
        try:
            with open(path) as f:
                return json.load(f)
        except FileNotFoundError:
            return copy.deepcopy(default)
        except (OSError, json.JSONDecodeError) as e:
            # keep the broken file for inspection rather than overwriting it silently
            bad = path.with_suffix(path.suffix + ".broken")
            try:
                path.replace(bad)
            except OSError:
                pass
            print(f"warning: could not read {path} ({e}); moved it to {bad.name} and used defaults")
            return copy.deepcopy(default)

    def save(self, name: str, data) -> None:
        """Write atomically so a crash mid-write never leaves a half file."""
        path = self.root / name
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=f".{name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # -- typed accessors ----------------------------------------------------
    def course(self) -> dict:
        return merge_defaults(self.load("course.json", DEFAULT_COURSE), DEFAULT_COURSE)

    def settings(self) -> dict:
        return merge_defaults(self.load("settings.json", DEFAULT_SETTINGS), DEFAULT_SETTINGS)


def merge_defaults(data, default):
    """Fill keys missing from ``data`` with ``default`` (recursively for dicts)."""
    if not isinstance(data, dict) or not isinstance(default, dict):
        return data
    out = copy.deepcopy(default)
    for k, v in data.items():
        out[k] = merge_defaults(v, default[k]) if k in default else v
    return out


def validate_course(c: dict) -> dict:
    """Check and normalise a course sent from the browser or an imported file.

    Raises ValueError with a message the user can act on.
    """
    if not isinstance(c, dict):
        raise ValueError("course must be an object")
    c = merge_defaults(c, DEFAULT_COURSE)
    out = {"name": str(c.get("name") or "Course")}
    for key in ("radius_h", "radius_v"):
        v = _num(c[key], key)
        if v <= 0:
            raise ValueError(f"{key} must be positive")
        out[key] = v
    wps = []
    for i, w in enumerate(c.get("waypoints") or []):
        label = f"waypoint {i + 1}"
        lat = _num(w.get("lat"), f"{label} latitude")
        lon = _num(w.get("lon"), f"{label} longitude")
        if not -90 <= lat <= 90:
            raise ValueError(f"{label}: latitude {lat} is outside -90..90")
        if not -180 <= lon <= 180:
            raise ValueError(f"{label}: longitude {lon} is outside -180..180")
        wps.append({
            "name": str(w.get("name") or f"WP {i + 1}"),
            "lat": lat,
            "lon": lon,
            "alt": _num(w.get("alt", 0.0), f"{label} altitude"),
        })
    out["waypoints"] = wps
    b = c["boundary"]
    out["boundary"] = {
        "enabled": bool(b.get("enabled")),
        "center_lat": _num(b["center_lat"], "boundary centre latitude"),
        "center_lon": _num(b["center_lon"], "boundary centre longitude"),
        "semi_east": _num(b["semi_east"], "boundary east semi-axis"),
        "semi_north": _num(b["semi_north"], "boundary north semi-axis"),
        "rotation_deg": _num(b["rotation_deg"], "boundary rotation"),
        "warn_at": _num(b.get("warn_at", 0.7), "boundary warning level"),
    }
    if out["boundary"]["semi_east"] <= 0 or out["boundary"]["semi_north"] <= 0:
        raise ValueError("boundary semi-axes must be positive")
    return out


def _num(v, what: str) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what}: '{v}' is not a number") from None
    if x != x or x in (float("inf"), float("-inf")):
        raise ValueError(f"{what}: '{v}' is not a number")
    return x
