"""The app's state: course, progress, start point, GPS source, and what to tell the pilot.

Every GPS fix goes through :meth:`Engine.on_fix`, which updates progress and
pushes a snapshot to every open browser tab.
"""

from __future__ import annotations

import csv
import math
import queue
import threading
import time
from collections import deque
from pathlib import Path

from . import nav
from .sources import Fix, ReplaySource, SerialSource, SimSource, Source
from .storage import Store, validate_course

HOME_SAMPLES = 10          # fixes averaged for the start point (2 s at 5 Hz)
HOME_KEEP_HOURS = 6.0      # reuse a saved start point this recent after a restart
MAX_SEGMENT_GAP = 1.5      # s; longer gaps between fixes are not interpolated
EVENT_KEEP = 50

LOG_COLUMNS = [
    # gpslog.py columns first, so a log can be replayed or read by the 415 scripts
    "time", "fix", "NumSat", "latitude", "longitude", "altitude", "speed", "ground_course", "covariance",
    "wall_time", "height_above_start", "east", "north", "active_wp", "distance_to_wp", "boundary", "event",
]


def _wp_key(w: dict) -> tuple:
    return (round(w["lat"], 9), round(w["lon"], 9), round(w["alt"], 3))


class Recorder:
    """Writes fixes and events to a CSV between Record and Stop; one file per recording."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.file = None
        self.writer = None
        self.path: Path | None = None
        self.started: float | None = None
        self.rows = 0

    @property
    def active(self) -> bool:
        return self.writer is not None

    def start(self) -> Path:
        if self.active:
            return self.path
        name = time.strftime("flight-%Y%m%d-%H%M%S")
        path = self.folder / f"{name}.csv"
        k = 2
        while path.exists():                      # two recordings in the same second
            path = self.folder / f"{name}-{k}.csv"
            k += 1
        self.path = path
        self.file = open(path, "w", newline="")
        self.writer = csv.writer(self.file)
        self.writer.writerow(LOG_COLUMNS)
        self.started = time.time()
        self.rows = 0
        return path

    def write(self, row: dict) -> None:
        if not self.active:
            return
        self.writer.writerow(["" if row.get(c) is None else row.get(c) for c in LOG_COLUMNS])
        self.file.flush()
        self.rows += 1

    def stop(self) -> None:
        if self.file:
            self.file.close()
        self.file = self.writer = None
        self.started = None

    def files(self) -> list[Path]:
        return sorted(self.folder.glob("*.csv"))


class Engine:
    def __init__(self, store: Store):
        self.store = store
        self.lock = threading.RLock()
        self.settings = store.settings()
        self.course = store.course()
        self._course_changed()
        self.run = self._load_run()
        self.home = self._load_home()
        self.home_samples: list[Fix] | None = None if self.home else []
        self.source: Source | None = None
        self.source_status = "No GPS source selected"
        self.last_fix: Fix | None = None
        self.prev_point: tuple | None = None     # (e, n, u, received)
        self.local: dict | None = None
        self.steer: nav.Steering | None = None
        self.boundary_value: float | None = None
        self.recv_times: deque = deque(maxlen=11)
        self.trail: deque = deque(maxlen=int(self.settings["trail_seconds"] * 5))
        self.events: deque = deque(maxlen=EVENT_KEEP)
        self.event_id = 0
        self.seq = 0
        self.subscribers: list[queue.Queue] = []
        self.log = Recorder(store.root / "logs")
        self.last_run_save = 0.0
        self.map_job: dict | None = None
        self.leaving: int | None = None          # waypoint just reached, still inside its bubble
        self._stop = threading.Event()
        threading.Thread(target=self._heartbeat, daemon=True, name="heartbeat").start()

    # ================================================================ persistence
    def _course_changed(self):
        b = self.course["boundary"]
        self.origin = (b["center_lat"], b["center_lon"])
        self.wp_local = [(*nav.to_local(*self.origin, w["lat"], w["lon"]), w["alt"]) for w in self.course["waypoints"]]

    def _blank_entry(self, w):
        return {"key": list(_wp_key(w)), "status": "pending", "how": None, "at": None, "closest": None}

    def _load_run(self) -> dict:
        run = self.store.load("run.json", None)
        wps = self.course["waypoints"]
        if not run or len(run.get("waypoints", [])) != len(wps) or any(
                tuple(e.get("key", ())) != _wp_key(w) for e, w in zip(run["waypoints"], wps)):
            run = {"started": time.time(), "waypoints": [self._blank_entry(w) for w in wps]}
        return run

    def _save_run(self):
        self.store.save("run.json", self.run)
        self.last_run_save = time.time()

    def _load_home(self):
        h = self.store.load("home.json", None)
        if h and time.time() - h.get("set_at", 0) < HOME_KEEP_HOURS * 3600:
            return h
        return None

    # ================================================================ derived
    def active_index(self) -> int | None:
        for i, e in enumerate(self.run["waypoints"]):
            if e["status"] == "pending":
                return i
        return None

    def target_for_sim(self):
        with self.lock:
            i = self.active_index()
            if i is None:
                return None
            w = self.course["waypoints"][i]
            return (w["lat"], w["lon"], w["alt"])

    # ================================================================ events
    def _event(self, kind: str, text: str, **extra):
        self.event_id += 1
        ev = {"id": self.event_id, "kind": kind, "text": text, "at": time.time(), **extra}
        self.events.append(ev)
        self.log.write({"wall_time": f"{time.time():.3f}", "event": text})
        return ev

    # ================================================================ GPS input
    def on_status(self, text: str):
        with self.lock:
            self.source_status = text
        self.publish()

    def on_fix(self, fx: Fix):
        with self.lock:
            self.last_fix = fx
            self.recv_times.append(fx.received)
            row = {
                "time": f"{fx.time:.3f}", "fix": fx.fix, "NumSat": fx.sats, "latitude": fx.lat, "longitude": fx.lon,
                "altitude": fx.alt, "speed": fx.speed, "ground_course": fx.course, "covariance": fx.hdop2,
                "wall_time": f"{fx.received:.3f}",
            }
            if not fx.usable:
                self.local = None
                self.steer = None
                self.log.write(row)
            else:
                self._process(fx, row)
                self.log.write(row)
        self.publish()

    def _process(self, fx: Fix, row: dict):
        # start point
        if self.home_samples is not None:
            self.home_samples.append(fx)
            if len(self.home_samples) >= HOME_SAMPLES:
                s = self.home_samples
                self.home = {
                    "lat": sum(f.lat for f in s) / len(s),
                    "lon": sum(f.lon for f in s) / len(s),
                    "alt": sum(f.alt for f in s) / len(s),
                    "set_at": time.time(),
                }
                self.home_samples = None
                self.store.save("home.json", self.home)
                self._event("home", f"Start point set (altitude {self.home['alt']:.1f} m)")

        e, n = nav.to_local(*self.origin, fx.lat, fx.lon)
        u = fx.alt - self.home["alt"] if self.home else None
        self.local = {"e": e, "n": n, "u": u}
        self.trail.append((round(e, 2), round(n, 2)))
        row.update(east=f"{e:.2f}", north=f"{n:.2f}", height_above_start=None if u is None else f"{u:.2f}")

        b = self.course["boundary"]
        if b["enabled"]:
            self.boundary_value = nav.ellipse_value(b["center_lat"], b["center_lon"], b["semi_east"],
                                                    b["semi_north"], b["rotation_deg"], fx.lat, fx.lon)
            row["boundary"] = f"{self.boundary_value:.3f}"
        else:
            self.boundary_value = None

        self.steer = None
        if u is None:
            self.prev_point = None
            return
        p1 = (e, n, u)
        p0 = None
        if self.prev_point and fx.received - self.prev_point[3] <= MAX_SEGMENT_GAP:
            p0 = self.prev_point[:3]
        self.prev_point = (e, n, u, fx.received)

        rh, rv = self.course["radius_h"], self.course["radius_v"]
        # A waypoint completes on entering its bubble, but the aircraft usually gets
        # closer still; keep its closest approach updating until it leaves the bubble.
        if self.leaving is not None:
            entry = self.run["waypoints"][self.leaving]
            ap = nav.segment_approach(p0, p1, self.wp_local[self.leaving], rh, rv)
            self._update_closest(entry, ap)
            if ap.bubble > 1.0 or entry["status"] != "done":
                self.leaving = None
                self._save_run()
        i = self.active_index()
        if i is not None:
            ap = nav.segment_approach(p0, p1, self.wp_local[i], rh, rv)
            entry = self.run["waypoints"][i]
            self._update_closest(entry, ap)
            if ap.bubble <= 1.0:
                self.leaving = i
                entry.update(status="done", how="auto", at=time.time())
                name = self.course["waypoints"][i]["name"]
                self._event("reached", f"Reached {i + 1}: {name} (closest {entry['closest']['distance']:.1f} m)", wp=i)
                self._save_run()
                if self.active_index() is None:
                    self._event("finished", "Course complete")
            elif time.time() - self.last_run_save > 2.0:
                self._save_run()

        i = self.active_index()
        if i is not None:
            self.steer = nav.steering(p1, self.wp_local[i], math.degrees(fx.course), fx.speed,
                                      radius_v=rv, min_speed=self.settings["min_speed"])
            row.update(active_wp=i + 1, distance_to_wp=f"{self.steer.distance_3d:.2f}")

    @staticmethod
    def _update_closest(entry: dict, ap: nav.Approach):
        if entry["closest"] is None or ap.distance < entry["closest"]["distance"]:
            entry["closest"] = {"distance": ap.distance, "horizontal": ap.horizontal,
                                "vertical": ap.vertical, "at": time.time()}

    # ================================================================ user actions
    def set_course(self, course: dict):
        course = validate_course(course)
        with self.lock:
            old = {tuple(e["key"]): e for e in self.run["waypoints"]}
            self.course = course
            self.store.save("course.json", course)
            self._course_changed()
            # keep progress of waypoints that did not move
            self.run["waypoints"] = [old.get(_wp_key(w)) or self._blank_entry(w) for w in course["waypoints"]]
            self.prev_point = None
            self.leaving = None
            self._save_run()
            self._event("course", f"Course saved: {course['name']} ({len(course['waypoints'])} waypoints)")
        self.publish()

    def mark(self, index: int, status: str):
        if status not in ("done", "pending", "skipped"):
            raise ValueError("status must be done, pending or skipped")
        with self.lock:
            if not 0 <= index < len(self.run["waypoints"]):
                raise ValueError("no such waypoint")
            entry = self.run["waypoints"][index]
            entry.update(status=status, how="manual" if status != "pending" else None,
                         at=time.time() if status != "pending" else None)
            word = {"done": "marked complete", "pending": "marked not complete", "skipped": "skipped"}[status]
            self._event("manual", f"Waypoint {index + 1} {word} by hand", wp=index)
            self.prev_point = None
            self._save_run()
        self.publish()

    def restart_run(self):
        with self.lock:
            self.run = {"started": time.time(), "waypoints": [self._blank_entry(w) for w in self.course["waypoints"]]}
            self.prev_point = None
            self.leaving = None
            self.trail.clear()
            self._save_run()
            self._event("restart", "Run restarted")
        self.publish()

    def start_recording(self):
        with self.lock:
            if not self.log.active:
                path = self.log.start()
                c = self.course
                self._event("record", f"Recording started: {path.name} (course {c['name']}, "
                                      f"bubble {c['radius_h']:g} m x {c['radius_v']:g} m)")
        self.publish()

    def stop_recording(self):
        with self.lock:
            if self.log.active:
                name = self.log.path.name
                self._event("record", f"Recording stopped: {name} ({self.log.rows} rows)")
                self.log.stop()
        self.publish()

    def history_files(self) -> list[Path]:
        with self.lock:
            return self.log.files()

    def clear_history(self):
        """Delete every recording (except one in progress), the map track and the event list."""
        with self.lock:
            current = self.log.path if self.log.active else None
            for p in self.log.files():
                if p != current:
                    p.unlink(missing_ok=True)
            self.trail.clear()
            self.events.clear()
            self._event("clear", "History cleared" + (" (the recording in progress was kept)" if current else ""))
        self.publish()

    def set_home_here(self):
        with self.lock:
            self.home_samples = []
            self.prev_point = None
            self._event("home", "Setting start point: hold the aircraft still for 2 s")
        self.publish()

    def update_settings(self, patch: dict):
        allowed = {"min_speed", "stale_after", "chime", "theme", "map"}
        with self.lock:
            for k, v in patch.items():
                if k in allowed:
                    self.settings[k] = v
            self.store.save("settings.json", self.settings)
        self.publish()

    # ================================================================ sources
    def set_source(self, kind: str, **kw):
        with self.lock:
            if self.source:
                self.source.stop()
                self.source = None
            self.last_fix = None
            self.local = None
            self.steer = None
            self.prev_point = None
            self.recv_times.clear()
            if kind == "serial":
                port = kw["port"]
                baud = int(kw.get("baudrate") or 57600)
                self.source = SerialSource(self.on_fix, self.on_status, port, baud)
                self.settings["source"].update(kind="serial", port=port, baudrate=baud)
                self.store.save("settings.json", self.settings)
            elif kind == "replay":
                self.source = ReplaySource(self.on_fix, self.on_status, kw["path"], kw["name"], kw.get("speed", 1.0))
                self.home_samples = []   # recorded flights start on the ground
            elif kind == "sim":
                lat, lon = (self.home["lat"], self.home["lon"]) if self.home else self.origin
                self.source = SimSource(self.on_fix, self.on_status, lat, lon, self.target_for_sim)
                self.home_samples = []
            elif kind == "none":
                self.source_status = "GPS source stopped"
            else:
                raise ValueError(f"unknown source {kind}")
            if self.source:
                self.source_status = f"Starting {self.source.describe()}"
                self._event("source", f"GPS source: {self.source.describe()}")
                self.source.start()
        self.publish()

    def shutdown(self):
        self._stop.set()
        with self.lock:
            if self.source:
                self.source.stop()
            self.log.stop()

    # ================================================================ output
    def snapshot(self, full: bool = False) -> dict:
        with self.lock:
            fx = self.last_fix
            rate = None
            if len(self.recv_times) >= 3:
                span = self.recv_times[-1] - self.recv_times[0]
                if span > 0:
                    rate = (len(self.recv_times) - 1) / span
            s = self.steer
            i = self.active_index()
            snap = {
                "seq": self.seq,
                "now": time.time(),
                "source": {
                    "kind": self.source.kind if self.source else "none",
                    "describe": self.source.describe() if self.source else "none",
                    "status": self.source_status,
                },
                "gps": None if fx is None else {
                    "received": fx.received, "fix": fx.fix and fx.usable, "sats": fx.sats,
                    "hdop": math.sqrt(fx.hdop2) if fx.hdop2 == fx.hdop2 and fx.hdop2 >= 0 else None,
                    "lat": _f(fx.lat), "lon": _f(fx.lon), "speed": _f(fx.speed),
                    "course": _f(math.degrees(fx.course) % 360.0), "rate": rate,
                },
                "local": self.local,
                "home": {
                    "set": self.home is not None and self.home_samples is None,
                    "setting": self.home_samples is not None,
                    "samples": len(self.home_samples) if self.home_samples is not None else 0,
                    "needed": HOME_SAMPLES,
                    "set_at": self.home["set_at"] if self.home else None,
                    "lat": self.home["lat"] if self.home else None,
                    "lon": self.home["lon"] if self.home else None,
                },
                "boundary": None if self.boundary_value is None else {
                    "value": self.boundary_value,
                    "status": nav.boundary_status(self.boundary_value, self.course["boundary"]["warn_at"]),
                },
                "active": i,
                "steer": None if s is None else s.__dict__,
                "course": self.course,
                "origin": self.origin,
                "wp_local": self.wp_local,
                "run": self.run,
                "events": list(self.events)[-10:],
                "settings": self.settings,
                "map_job": self.map_job,
                "recording": {
                    "active": self.log.active,
                    "started": self.log.started,
                    "file": self.log.path.name if self.log.active else None,
                    "rows": self.log.rows,
                },
                "history": [p.name for p in self.log.files()],
            }
            if full:
                snap["trail"] = list(self.trail)
            return snap

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=5)
        with self.lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def publish(self):
        with self.lock:
            self.seq += 1
            snap = self.snapshot()
            subs = list(self.subscribers)
        for q in subs:
            try:
                q.put_nowait(snap)
            except queue.Full:
                # a slow tab: drop its oldest update, it only needs the newest
                try:
                    q.get_nowait()
                    q.put_nowait(snap)
                except (queue.Empty, queue.Full):
                    pass

    def _heartbeat(self):
        """Keep tabs updating (and showing 'no data') when no fixes arrive."""
        while not self._stop.wait(1.0):
            fx = self.last_fix
            if fx is None or time.time() - fx.received > 0.9:
                self.publish()


def _f(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else x
