import math
import time

import pytest

from flightlabcopilot import nav
from flightlabcopilot.engine import HOME_SAMPLES, Engine
from flightlabcopilot.sources import Fix, read_log
from flightlabcopilot.storage import DEFAULT_COURSE, Store, validate_course
from flightlabcopilot.vendor.libnmea_navsat_driver.driver import NMEADriver

LAT0, LON0 = 40.2672305, -111.635524
GROUND = 1400.0


def make_engine(tmp_path, waypoints):
    eng = Engine(Store(tmp_path))
    course = dict(DEFAULT_COURSE, waypoints=waypoints)
    eng.set_course(course)
    eng.home_samples = []
    return eng


def feed(eng, e, n, h, t, speed=15.0, course=0.0):
    lat, lon = nav.from_local(LAT0, LON0, e, n)
    eng.on_fix(Fix(t, t, True, 10, lat, lon, GROUND + h, speed, course, 0.81))


def wp(e, n, alt, name="w"):
    lat, lon = nav.from_local(LAT0, LON0, e, n)
    return {"name": name, "lat": lat, "lon": lon, "alt": alt}


def test_home_then_auto_complete_between_fixes(tmp_path):
    eng = make_engine(tmp_path, [wp(0, 100, 20, "A"), wp(100, 100, 20, "B")])
    t = time.time()
    for k in range(HOME_SAMPLES):
        feed(eng, 0, 0, 0, t + 0.2 * k, speed=0)
    assert eng.home is not None and eng.home["alt"] == pytest.approx(GROUND)
    # fly north at 20 m height, fixes 3 m apart straddling waypoint A with a 1 m offset
    t += 5
    for k, n in enumerate([94, 97, 100 - 1.4, 101.6, 104.6]):
        feed(eng, 1.0, n, 20.0, t + 0.2 * k)
    run = eng.run["waypoints"]
    assert run[0]["status"] == "done" and run[0]["how"] == "auto"
    assert run[0]["closest"]["distance"] == pytest.approx(1.0, abs=1e-6)
    assert eng.active_index() == 1
    assert any(e["kind"] == "reached" for e in eng.events)
    assert eng.steer.turn == "RIGHT"


def test_altitude_miss_is_not_complete(tmp_path):
    eng = make_engine(tmp_path, [wp(0, 100, 20)])
    t = time.time()
    for k in range(HOME_SAMPLES):
        feed(eng, 0, 0, 0, t + 0.2 * k, speed=0)
    t += 5
    for k, n in enumerate(range(90, 112, 3)):
        feed(eng, 0, n, 26.0, t + 0.2 * k)   # passes directly over, 6 m too high
    e = eng.run["waypoints"][0]
    assert e["status"] == "pending"
    assert e["closest"]["vertical"] == pytest.approx(6.0)
    assert e["closest"]["horizontal"] == pytest.approx(0.0, abs=1e-6)


def test_manual_override_and_persistence(tmp_path):
    eng = make_engine(tmp_path, [wp(0, 100, 20), wp(50, 50, 10)])
    eng.mark(0, "done")
    assert eng.active_index() == 1
    eng.mark(0, "pending")
    assert eng.active_index() == 0
    eng.mark(0, "skipped")
    eng.shutdown()
    eng2 = Engine(Store(tmp_path))
    assert eng2.run["waypoints"][0]["status"] == "skipped"
    assert len(eng2.course["waypoints"]) == 2
    eng2.shutdown()


def test_editing_course_keeps_progress_of_unchanged_waypoints(tmp_path):
    a, b = wp(0, 100, 20, "A"), wp(50, 50, 10, "B")
    eng = make_engine(tmp_path, [a, b])
    eng.mark(0, "done")
    eng.set_course(dict(DEFAULT_COURSE, waypoints=[a, dict(b, alt=12.0)]))
    assert eng.run["waypoints"][0]["status"] == "done"
    assert eng.run["waypoints"][1]["status"] == "pending"
    eng.shutdown()


def test_validate_course_messages():
    with pytest.raises(ValueError, match="waypoint 1 latitude"):
        validate_course(dict(DEFAULT_COURSE, waypoints=[{"lat": "abc", "lon": 0, "alt": 0}]))
    with pytest.raises(ValueError, match="outside -90"):
        validate_course(dict(DEFAULT_COURSE, waypoints=[{"lat": 140, "lon": 0, "alt": 0}]))
    c = validate_course(dict(DEFAULT_COURSE, waypoints=[{"lat": "40.1", "lon": "-111.2", "alt": "5"}]))
    assert c["waypoints"][0] == {"name": "WP 1", "lat": 40.1, "lon": -111.2, "alt": 5.0}


def test_sample_log_reads():
    fixes = read_log("tests/data/sample_gpslog.csv")
    assert len(fixes) > 1000
    assert fixes[0].lat == pytest.approx(40.2679268333)


def test_vendored_driver_parses_gga_and_rmc():
    d = NMEADriver()

    def nmea(body):
        cs = 0
        for ch in body:
            cs ^= ord(ch)
        return f"${body}*{cs:02X}"

    assert d.add_sentence(nmea("GPRMC,123519,A,4016.0756,N,11138.0696,W,022.4,084.4,230394,003.1,W"), 1.0) is False
    out = d.add_sentence(nmea("GPGGA,123520,4016.0756,N,11138.0696,W,1,08,0.9,1490.4,M,-17.0,M,,"), 1.2)
    t, fix, sats, lat, lon, alt, speed, course, cov = out
    assert fix and sats == 8
    assert lat == pytest.approx(40 + 16.0756 / 60)
    assert lon == pytest.approx(-(111 + 38.0696 / 60))
    assert speed == pytest.approx(22.4 * 0.514444444444)
    assert course == pytest.approx(math.radians(84.4))
    assert cov == pytest.approx(0.81)


def test_record_stop_download_clear(tmp_path):
    import csv
    import io
    import zipfile

    from flightlabcopilot.app import create_app

    app = create_app(tmp_path)
    eng = app.config["ENGINE"]
    c = app.test_client()
    t = time.time()
    feed(eng, 0, 0, 0, t, speed=0)                     # not recording: nothing written
    assert eng.snapshot()["history"] == []
    assert c.get("/api/history/download").status_code == 404

    assert c.post("/api/record", json={"action": "start"}).status_code == 200
    assert eng.snapshot()["recording"]["active"]
    for k in range(3):
        feed(eng, 0, 0, 0, t + 0.2 * (k + 1), speed=0)
    c.post("/api/record", json={"action": "stop"})
    snap = eng.snapshot()
    assert not snap["recording"]["active"] and len(snap["history"]) == 1

    r = c.get("/api/history/download")
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.data.decode())))
    assert sum(1 for row in rows if row["latitude"]) == 3
    assert rows[0]["event"].startswith("Recording started")
    assert rows[-1]["event"].startswith("Recording stopped")
    # a recording replays like a gpslog.py file
    assert len(read_log(eng.store.root / "logs" / snap["history"][0])) == 3

    c.post("/api/record", json={"action": "start"})
    feed(eng, 0, 0, 0, t + 2, speed=0)
    c.post("/api/record", json={"action": "stop"})
    r = c.get("/api/history/download")
    assert r.mimetype == "application/zip"
    assert len(zipfile.ZipFile(io.BytesIO(r.data)).namelist()) == 2

    c.post("/api/record", json={"action": "start"})    # in progress: survives a clear
    c.post("/api/history/clear")
    snap = eng.snapshot()
    assert len(snap["history"]) == 1 and snap["recording"]["active"]
    assert list(eng.trail) == []
    assert c.post("/api/record", json={"action": "bogus"}).status_code == 400
    eng.shutdown()
