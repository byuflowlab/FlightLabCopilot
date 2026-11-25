"""Where GPS fixes come from: the radio on a serial port, a recorded CSV, or a simulator.

Each source runs in its own thread and calls ``on_fix(Fix)`` for every
position and ``on_status(str)`` when something worth telling the user happens.
"""

from __future__ import annotations

import csv
import math
import random
import threading
import time
from dataclasses import dataclass

from . import nav


@dataclass
class Fix:
    received: float      # time.time() when it arrived
    time: float          # source time (s since the source started, as gpslog.py logs it)
    fix: bool
    sats: int
    lat: float
    lon: float
    alt: float           # m, GPS altitude (absolute; the engine subtracts the start point)
    speed: float         # m/s over ground
    course: float        # rad, ground track, 0 = north
    hdop2: float         # gpslog's "covariance" column: HDOP squared

    @property
    def usable(self) -> bool:
        return self.fix and not (math.isnan(self.lat) or math.isnan(self.lon) or math.isnan(self.alt))


class Source(threading.Thread):
    kind = "none"

    def __init__(self, on_fix, on_status):
        super().__init__(daemon=True, name=f"source-{self.kind}")
        self.on_fix = on_fix
        self.on_status = on_status
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    def describe(self) -> str:
        return self.kind


# ---------------------------------------------------------------- serial radio

def list_serial_ports() -> list[dict]:
    """Serial ports, likely radios first (USB serial adapters)."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    ports = []
    for p in list_ports.comports():
        dev = p.device
        # macOS lists each port twice; the /dev/cu.* one is right for reading
        if dev.startswith("/dev/tty.") and any(q.device == dev.replace("/dev/tty.", "/dev/cu.") for q in list_ports.comports()):
            continue
        likely = any(s in dev.lower() for s in ("usbserial", "usbmodem", "ttyusb", "ttyacm")) or dev.upper().startswith("COM")
        if "bluetooth" in dev.lower() or "debug-console" in dev.lower():
            likely = False
        ports.append({"device": dev, "description": p.description or "", "likely": likely})
    ports.sort(key=lambda p: (not p["likely"], p["device"]))
    return ports


class SerialSource(Source):
    """Reads NMEA from the ground radio, exactly as gpslog.py does, and reconnects if unplugged."""

    kind = "serial"

    def __init__(self, on_fix, on_status, port: str, baudrate: int = 57600):
        super().__init__(on_fix, on_status)
        self.port = port
        self.baudrate = baudrate

    def describe(self) -> str:
        return f"radio on {self.port}"

    def run(self) -> None:
        import serial

        from .vendor.libnmea_navsat_driver.driver import NMEADriver

        t0 = time.time()
        while not self.stop_event.is_set():
            try:
                gps = serial.Serial(port=self.port, baudrate=self.baudrate, timeout=1)
            except (serial.SerialException, OSError) as e:
                self.on_status(f"Cannot open {self.port}: {e}. Retrying…")
                self.stop_event.wait(2.0)
                continue
            self.on_status(f"Connected to {self.port}, waiting for data")
            driver = NMEADriver()
            got_data = False
            try:
                while not self.stop_event.is_set():
                    line = gps.readline().strip()
                    if not line:
                        continue
                    if not got_data:
                        got_data = True
                        self.on_status(f"Receiving from {self.port}")
                    try:
                        out = driver.add_sentence(line.decode("ascii", errors="replace"), time.time() - t0)
                    except (ValueError, IndexError):
                        continue  # truncated or garbled sentence; the next one will do
                    if out:
                        t, fix, sats, lat, lon, alt, speed, course, cov = out
                        self.on_fix(Fix(time.time(), t, bool(fix), int(sats), lat, lon, alt, speed, course, cov))
            except (serial.SerialException, OSError) as e:
                self.on_status(f"Lost {self.port}: {e}. Reconnecting…")
                self.stop_event.wait(1.0)
            finally:
                try:
                    gps.close()
                except Exception:
                    pass


# ---------------------------------------------------------------- replay

def read_log(path) -> list[Fix]:
    """Fixes from a gpslog.py CSV, or from this app's own log (same first columns)."""
    fixes = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                fixes.append(Fix(
                    received=0.0,
                    time=float(row["time"]),
                    fix=row["fix"].strip().lower() in ("true", "1"),
                    sats=int(float(row["NumSat"])),
                    lat=float(row["latitude"]),
                    lon=float(row["longitude"]),
                    alt=float(row["altitude"]),
                    speed=float(row["speed"]),
                    course=float(row["ground_course"]),
                    hdop2=float(row["covariance"]),
                ))
            except (KeyError, ValueError, TypeError):
                continue  # event-only rows in our own logs, or damaged lines
    if not fixes:
        raise ValueError("no GPS rows found; expected gpslog.py columns time,fix,NumSat,latitude,longitude,altitude,speed,ground_course,covariance")
    return fixes


class ReplaySource(Source):
    kind = "replay"

    def __init__(self, on_fix, on_status, path, name: str, speed: float = 1.0):
        super().__init__(on_fix, on_status)
        self.fixes = read_log(path)
        self.name = name
        self.speed = max(0.1, float(speed))

    def describe(self) -> str:
        return f"replay of {self.name} at {self.speed:g}×"

    def run(self) -> None:
        self.on_status(f"Replaying {self.name} ({len(self.fixes)} fixes)")
        start_wall = time.time()
        t_first = self.fixes[0].time
        for fx in self.fixes:
            due = start_wall + (fx.time - t_first) / self.speed
            if self.stop_event.wait(max(0.0, due - time.time())):
                return
            fx.received = time.time()
            self.on_fix(fx)
        self.on_status(f"Replay of {self.name} finished")


# ---------------------------------------------------------------- simulator

class SimSource(Source):
    """A small aircraft that sits on the ground for a few seconds, takes off and
    flies at the active waypoint, with wind and GPS-like noise. For trying the
    app and training without hardware."""

    kind = "sim"
    RATE = 5.0           # Hz, as the real GPS
    AIRSPEED = 14.0      # m/s
    TURN_RATE = 35.0     # deg/s
    CLIMB_RATE = 3.0     # m/s
    WIND = (2.5, 1.0)    # m/s toward east, north
    GROUND_ALT = 1400.0  # m

    def __init__(self, on_fix, on_status, start_lat: float, start_lon: float, target, seed: int | None = None):
        """``target()`` returns (lat, lon, height above start) of the active waypoint, or None."""
        super().__init__(on_fix, on_status)
        self.lat0, self.lon0 = start_lat, start_lon
        self.target = target
        self.rng = random.Random(seed)

    def describe(self) -> str:
        return "simulator"

    def run(self) -> None:
        self.on_status("Simulator running: on the ground for 3 s, then flying the course")
        dt = 1.0 / self.RATE
        e = n = 0.0
        h = 0.0                     # height above ground
        heading = 0.0               # deg, nose
        noise = [0.0, 0.0, 0.0]
        tau, sig = 5.0, (0.7, 0.7, 1.5)
        a = math.exp(-dt / tau)
        t = 0.0
        next_t = time.time()
        while not self.stop_event.is_set():
            airborne = t > 3.0
            if airborne:
                tgt = self.target()
                if tgt is None:
                    # course finished: circle 60 m around the start point
                    ang = math.atan2(e, n) + 0.6
                    te, tn, tgt = 60 * math.sin(ang), 60 * math.cos(ang), (None, None, 20.0)
                else:
                    te, tn = nav.to_local(self.lat0, self.lon0, tgt[0], tgt[1])
                # crude wind correction: point the ground track, not the nose
                want_track = math.degrees(math.atan2(te - e, tn - n))
                wx, wy = self.WIND
                cross = wx * math.cos(math.radians(want_track)) - wy * math.sin(math.radians(want_track))
                want_heading = want_track - math.degrees(math.asin(max(-1, min(1, cross / self.AIRSPEED))))
                want_h = max(5.0, tgt[2])
                turn = nav.wrap180(want_heading - heading)
                heading += max(-self.TURN_RATE * dt, min(self.TURN_RATE * dt, turn))
                h += max(-self.CLIMB_RATE * dt, min(self.CLIMB_RATE * dt, want_h - h))
                ve = self.AIRSPEED * math.sin(math.radians(heading)) + self.WIND[0]
                vn = self.AIRSPEED * math.cos(math.radians(heading)) + self.WIND[1]
            else:
                ve = vn = 0.0
            e += ve * dt
            n += vn * dt
            for i in range(3):
                noise[i] = a * noise[i] + sig[i] * math.sqrt(1 - a * a) * self.rng.gauss(0, 1)
            lat, lon = nav.from_local(self.lat0, self.lon0, e + noise[0], n + noise[1])
            speed = math.hypot(ve, vn) + self.rng.gauss(0, 0.1)
            course = math.atan2(ve, vn) % (2 * math.pi) if speed > 0.5 else 0.0
            self.on_fix(Fix(time.time(), t, True, 11, lat, lon, self.GROUND_ALT + h + noise[2],
                            max(0.0, speed), course, 0.81))
            t += dt
            next_t += dt
            if self.stop_event.wait(max(0.0, next_t - time.time())):
                return
