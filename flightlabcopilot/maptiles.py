"""Satellite imagery for the map, downloaded once (with internet) and kept for the field.

Tiles are standard web-map tiles (EPSG:3857, 256 px). Each is stored with the
latitude/longitude of its edges so the browser can place it on the local map.
"""

from __future__ import annotations

import math
import threading
import urllib.request

from . import nav

SOURCES = {
    "esri": {
        "label": "Esri World Imagery",
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attribution": "Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    },
}
MAX_TILES = 400


def lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[float, float]:
    n = 2**z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def tile_to_lonlat(x: float, y: float, z: int) -> tuple[float, float]:
    n = 2**z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


def course_bbox(course: dict, margin: float = 60.0) -> tuple[float, float, float, float]:
    """(south, west, north, east) covering the boundary and every waypoint, plus a margin in metres."""
    b = course["boundary"]
    lat0, lon0 = b["center_lat"], b["center_lon"]
    pts = []
    r = max(b["semi_east"], b["semi_north"])
    pts += [(-r, -r), (r, r)]
    for w in course["waypoints"]:
        pts.append(nav.to_local(lat0, lon0, w["lat"], w["lon"]))
    es = [p[0] for p in pts]
    ns = [p[1] for p in pts]
    s, w_ = nav.from_local(lat0, lon0, min(es) - margin, min(ns) - margin)
    n, e = nav.from_local(lat0, lon0, max(es) + margin, max(ns) + margin)
    return s, w_, n, e


def plan(bbox, zoom: int) -> list[tuple[int, int]]:
    s, w, n, e = bbox
    x0, y0 = lonlat_to_tile(w, n, zoom)
    x1, y1 = lonlat_to_tile(e, s, zoom)
    return [(x, y) for x in range(int(x0), int(x1) + 1) for y in range(int(y0), int(y1) + 1)]


def download(engine, zoom: int, source: str = "esri") -> None:
    """Start downloading in the background; progress goes to ``engine.map_job``."""
    src = SOURCES[source]
    with engine.lock:
        bbox = course_bbox(engine.course)
    tiles = plan(bbox, zoom)
    if len(tiles) > MAX_TILES:
        raise ValueError(f"{len(tiles)} tiles at zoom {zoom} is too many (limit {MAX_TILES}); pick a lower zoom")
    if engine.map_job and engine.map_job.get("running"):
        raise ValueError("a download is already running")
    folder = engine.store.root / "map" / "tiles"
    folder.mkdir(parents=True, exist_ok=True)
    engine.map_job = {"running": True, "done": 0, "total": len(tiles), "error": None}

    def work():
        out = []
        try:
            for x, y in tiles:
                name = f"{source}_{zoom}_{x}_{y}.jpg"
                path = folder / name
                if not path.exists():
                    req = urllib.request.Request(src["url"].format(z=zoom, x=x, y=y),
                                                 headers={"User-Agent": "FlightLabCopilot/0.1"})
                    with urllib.request.urlopen(req, timeout=20) as r:
                        data = r.read()
                    path.write_bytes(data)
                west, north = tile_to_lonlat(x, y, zoom)
                east, south = tile_to_lonlat(x + 1, y + 1, zoom)
                out.append({"file": name, "north": north, "south": south, "west": west, "east": east})
                engine.map_job["done"] += 1
                engine.publish()
            engine.map_job["running"] = False
            engine.update_settings({"map": {**engine.settings["map"], "kind": "tiles", "tiles": out,
                                            "zoom": zoom, "attribution": src["attribution"]}})
        except Exception as e:  # network down, server refused, disk full...
            engine.map_job.update(running=False, error=f"Download failed: {e}")
            engine.publish()

    threading.Thread(target=work, daemon=True, name="map-download").start()
