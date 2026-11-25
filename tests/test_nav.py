import math

import pytest

from flightlabcopilot import nav


def test_local_roundtrip():
    lat0, lon0 = 40.2672305, -111.635524
    e, n = nav.to_local(lat0, lon0, 40.2675, -111.6350)
    lat, lon = nav.from_local(lat0, lon0, e, n)
    assert lat == pytest.approx(40.2675, abs=1e-12)
    assert lon == pytest.approx(-111.6350, abs=1e-12)


def test_matches_gpslog_distance():
    # gpslog.py: distN = R*(lat2-lat1)*pi/180, distE = R*cos(lat1)*(lon2-lon1)*pi/180
    p1, p2 = (40.267641059243935, -111.63587333726502), (40.26678857, -111.63552403)
    e, n = nav.to_local(*p1, *p2)
    R = 6371000.0
    assert n == pytest.approx(R * (p2[0] - p1[0]) * math.pi / 180)
    assert e == pytest.approx(R * math.cos(p1[0] * math.pi / 180) * (p2[1] - p1[1]) * math.pi / 180)


@pytest.mark.parametrize("a,expected", [(0, 0), (180, 180), (-180, 180), (190, -170), (-190, 170), (360, 0), (540, 180)])
def test_wrap180(a, expected):
    assert nav.wrap180(a) == pytest.approx(expected)


def test_bearing():
    assert nav.bearing_deg(0, 1) == pytest.approx(0)
    assert nav.bearing_deg(1, 0) == pytest.approx(90)
    assert nav.bearing_deg(0, -1) == pytest.approx(180)
    assert nav.bearing_deg(-1, 0) == pytest.approx(270)


def test_segment_catches_pass_between_fixes():
    # fixes 3 m either side of the waypoint, both outside a 2.5 m bubble, but the line passes 0.5 m away
    a = nav.segment_approach((-3, 0.5, 0), (3, 0.5, 0), (0, 0, 0), 2.5, 2.5)
    assert a.distance == pytest.approx(0.5)
    assert a.bubble < 1
    # checking only the second fix would have missed it
    b = nav.segment_approach(None, (3, 0.5, 0), (0, 0, 0), 2.5, 2.5)
    assert b.bubble > 1


def test_segment_vertical_component():
    a = nav.segment_approach((-5, 0, 3), (5, 0, 3), (0, 0, 0), 2.5, 2.5)
    assert a.horizontal == pytest.approx(0)
    assert a.vertical == pytest.approx(3)
    assert a.bubble > 1          # 3 m above a 2.5 m sphere
    b = nav.segment_approach((-5, 0, 3), (5, 0, 3), (0, 0, 0), 2.5, 4.0)
    assert b.bubble < 1          # inside a taller bubble


def test_steering_left_right_ahead():
    # flying north (course 0), waypoint to the north-west
    s = nav.steering((0, 0, 10), (-50, 50, 15), 0.0, 15.0, radius_v=2.5)
    assert s.turn == "LEFT" and s.relative == pytest.approx(-45)
    assert s.vertical == "CLIMB" and s.climb == pytest.approx(5)
    s = nav.steering((0, 0, 10), (50, 50, 10), 0.0, 15.0, radius_v=2.5)
    assert s.turn == "RIGHT" and s.vertical == "HOLD"
    s = nav.steering((0, 0, 10), (2, 100, 4), 0.0, 15.0, radius_v=2.5)
    assert s.turn == "AHEAD" and s.vertical == "DESCEND"
    assert s.time_to_go == pytest.approx(100.02 / (15 * math.cos(math.atan2(2, 100))), rel=1e-3)


def test_steering_slow_has_no_turn():
    s = nav.steering((0, 0, 0), (10, 0, 0), 0.0, 0.5, radius_v=2.5)
    assert s.relative is None and s.turn == "" and s.bearing == pytest.approx(90)


def test_steering_across_north():
    # track 350, waypoint at bearing 10: 20 deg right, not 340 left
    s = nav.steering((0, 0, 0), (math.sin(math.radians(10)) * 100, math.cos(math.radians(10)) * 100, 0), 350.0, 15.0, radius_v=2.5)
    assert s.relative == pytest.approx(20)


def test_ellipse_matches_gpslog():
    c = (40.2672305, -111.635524)
    R = (98.353826748828595, 127.49653449395105)
    assert nav.ellipse_value(*c, *R, -15.0, *c) == pytest.approx(0)
    # a point well outside
    lat, lon = nav.from_local(*c, 0, 300)
    assert nav.boundary_status(nav.ellipse_value(*c, *R, -15.0, lat, lon)) == "out"
    # along the first rotated axis at 0.9 R: value 0.81, past the 0.7 warning
    th = math.radians(-15.0)
    e, n = 0.9 * R[0] * math.cos(th), 0.9 * R[0] * math.sin(th)
    lat, lon = nav.from_local(*c, e, n)
    v = nav.ellipse_value(*c, *R, -15.0, lat, lon)
    assert v == pytest.approx(0.81, rel=1e-6)
    assert nav.boundary_status(v) == "warn"
