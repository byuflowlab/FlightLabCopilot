# FlightLabCopilot

A local web app that tells a copilot which way the pilot should fly to reach a sequence of GPS waypoints. The aircraft's GPS position comes over the radio pair used in ME 415 (the same setup as [byuflowlab/415gps](https://github.com/byuflowlab/415gps)); a small Python server on your computer reads it and the guidance shows in your browser. It works without internet.

## Student and TA download

No Git, Python or terminal commands needed. Download the launcher for [macOS](https://github.com/byuflowlab/FlightLabCopilot/raw/main/student_setup/downloads/FlightLabCopilot-macOS.zip), [Windows](https://github.com/byuflowlab/FlightLabCopilot/raw/main/student_setup/downloads/FlightLabCopilot-Windows.zip), or [Linux](https://github.com/byuflowlab/FlightLabCopilot/raw/main/student_setup/downloads/FlightLabCopilot-Linux.zip), unzip it, read **START HERE**, and double-click the launcher. The first launch needs internet and downloads a private copy of Python and the app, so do it before going to the field; later launches start in seconds, work offline, and update automatically when a new build is promoted. The course, map and recordings are kept across updates. Instructors: see [student_setup/README.md](student_setup/README.md).

## Quick start

For development, or to run from a clone of this repository, you need [uv](https://docs.astral.sh/uv/), which downloads the right Python and libraries by itself. Install it once:

- macOS and Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

Open a new terminal afterwards so it can find `uv`. Then, from this folder:

```bash
uv run flightlabcopilot
```

A browser tab opens at `http://127.0.0.1:5160/`. Keep the terminal open while you use the app. To stop, click **Exit** at the top right of the app, or press `Ctrl-C` in the terminal. Use `--port 8000` for a different port, `--no-open` to skip opening the browser, and `--data-dir FOLDER` to keep the course, map and logs somewhere else.

**Run it once with internet before going to the field.** The first run downloads Python and the libraries; after that it starts offline.

## Try it without hardware

Click **GPS source** and then **Start simulator**. A simulated aircraft sits on the ground for 3 s (long enough to set the start point), takes off and flies the course, with wind and GPS-like noise. This is the easiest way to learn the screen or to check a new course before flying it.

You can also replay a recorded flight: **GPS source → Replay a recorded flight** accepts a CSV written by `gpslog.py` or one of this app's own logs, at 1× to 10× speed.

## At the field

1. **Connect the radio.** Plug the ground radio into USB. Power the aircraft's GPS and radio (keep them at least 4 inches apart, as in the 415gps instructions). Click **GPS source**, pick the port (likely ones such as `/dev/cu.usbserial-…` are listed first) and click **Connect**. The app reconnects by itself if the cable is bumped, and connects to the same port automatically the next time it starts.
2. **Wait for a fix.** The GPS chip at the top turns green once there is a fix, showing the number of satellites, HDOP (lower is better; above 2 turns it yellow) and the update rate (about 5 Hz). A first fix needs open sky and can take a minute.
3. **Set the start point.** All altitudes are heights above the start point. The app takes it automatically from the first 2 s of fixes. If the aircraft was not on the ground and still at that moment, put it on the ground at the launch spot and click **Set start here**. A start point is reused for 6 hours, so restarting the app mid-session does not lose it.
4. **Enable the chime.** Browsers only play sound after a click on the page, so click once anywhere (the chip at the top shows 🔔 when sound is ready).
5. **Record.** Click the green **● Record** button before take-off. It turns into a red **■ Stop** button, and a red *REC* timer shows at the top while recording.
6. **Fly.** The copilot reads the left half of the screen and calls it to the pilot.
7. **Stop** the recording after landing.

## Reading the screen

- **Waypoint title** shows which waypoint is next, e.g. *WP 2 of 5 · Tower*.
- **Arrow and turn text** show how far to turn: *LEFT 35°*, *RIGHT 20°*, or *AHEAD* (within 10°). Straight up on the dial is the direction the aircraft is moving over the ground. Directions are relative to the GPS ground track, not where the nose points; in a crosswind the track is what has to point at the waypoint. Below 2 m/s the track is meaningless, so the dial shows **N** at the top and the arrow points to the waypoint from north instead.
- **Distance** is the horizontal distance to the waypoint, with the straight-line (3-D) distance and the time to go at the current speed underneath.
- **Altitude** says *↑ CLIMB*, *↓ DESCEND* or *HOLD* (green, within half the bubble height of the target), with the current height and the target height.
- **Closest so far** is the closest the aircraft has come to the current waypoint, split into horizontal and vertical parts (positive vertical means above).
- **Banner** across the top shows the most important problem: *OUT OF BOUNDS — RETURN NOW* (flashing red), *NO GPS DATA* (the guidance also greys out, because it is out of date), *Close to boundary — ready the pilot*, no fix, or setting the start point.

## Waypoints and completion

Each waypoint has a bubble around it, by default a sphere of 2.5 m radius. A waypoint is **reached** when the aircraft enters its bubble: the screen flashes, the chime plays and the next waypoint becomes active. Waypoints are flown in order; only the active one can be reached.

Because the GPS reports a position only 5 times a second, an aircraft at 15 m/s moves about 3 m between fixes. The app assumes a straight line between fixes when checking the bubble and the closest approach, so a pass between two fixes still counts. After a waypoint is reached its closest approach keeps updating until the aircraft leaves the bubble.

GPS altitude is noisier than horizontal position (often several metres), so a pass can miss the bubble on altitude alone. The **Closest** column shows the horizontal and vertical parts of each miss so a TA can judge it. In **Course** you can make the bubble taller than it is wide (*Bubble half-height*).

The TA has the final say. In the waypoint table:

- **✓ Complete** marks a waypoint as reached by hand (shown as *✓ by hand*).
- **Skip** passes over a waypoint.
- **Undo** puts a waypoint back to pending; it becomes active again if it is the first pending one.
- **Restart run** sets every waypoint back to pending and clears the closest approaches, for the next team. The log keeps everything.

## Recording and history

Nothing is written to disk until you click **● Record**. From then until **■ Stop**, every GPS fix and every event (waypoint reached, manual overrides, start point, boundary) goes into a new CSV named by its start time, e.g. `flight-20261124-170131.csv`. Each recording is a separate file, so record one per team or per flight. The app stops and saves a recording in progress when you click **Exit**.

The **History** section under the waypoint table lists how many recordings there are:

- **Download history** downloads them: a single CSV if there is one recording, or a zip of all of them.
- **Clear history** deletes the recordings from this computer and clears the track on the map and the event list. It asks first; download the history before clearing if you need it. A recording in progress is kept.

## Editing the course

Click **Course**. For each waypoint enter a name, latitude and longitude in decimal degrees (south and west are negative, e.g. `40.26764, -111.63587`) and the altitude in metres above the start point. Use the arrows to reorder and ✕ to delete. **Paste many** takes one waypoint per line as `lat, lon, alt` or `name, lat, lon, alt` and replaces the table. **Add at current position** adds a waypoint where the GPS is now, at its current height, which is handy for walking the GPS to a spot.

The same dialog sets the bubble size and the flying-field boundary: an ellipse given by its centre, two semi-axes and a rotation, exactly as `bdy_center`, `bdy_R` and `bdy_theta` in `gpslog.py` (the defaults are the ones from that file). The app warns past 0.7 of the ellipse (gpslog's value; adjustable under *Warn at*) and alerts outside it.

Click **Save** to apply. The course is saved on this computer and reloaded next time. Editing the course keeps the progress of waypoints that were not moved. **Export file** downloads the course as a `.course.json` file to keep or share, and **Import file** loads one.

## Map

The map on the right is optional. Click **Map** to choose:

- **Hidden**: the waypoint table takes the whole right side.
- **Blank grid**: a grid in metres. Needs nothing.
- **Picture**: your own north-up image of the field (a Google Earth screenshot, a drone photo…). Enter the latitude of its top and bottom edges and the longitude of its left and right edges.
- **Satellite**: imagery downloaded while you have internet and kept for the field. Save the course first; the download covers the boundary and every waypoint. Imagery © Esri and its partners.

The map shows the boundary (solid red) and warning line (dashed), waypoint bubbles (numbered; green when reached, orange when active), the start point **S**, the aircraft and its recent track, and a dashed line to the active waypoint.

## Where things are saved

Everything is kept in one data folder, printed in the terminal when the app starts: `~/.local/share/flightlabcopilot` on macOS and Linux, `%LOCALAPPDATA%\FlightLabCopilot` on Windows.

- `course.json`: waypoints, bubble size and boundary.
- `run.json`: progress through the course.
- `home.json`: the start point.
- `settings.json`: last radio port, map and display choices.
- `map/`: your picture or downloaded imagery.
- `logs/`: the recordings, one CSV per Record/Stop. The first columns match `gpslog.py` (`time, fix, NumSat, latitude, longitude, altitude, speed, ground_course, covariance`), followed by the height above the start point, local east/north position, active waypoint, distance to it, boundary value, and events such as waypoints reached and manual overrides. Logs can be replayed from **GPS source**.

## Troubleshooting

- **No serial ports listed**: check the radio's USB cable and its faint green light, then click **Refresh**.
- **Connected but "Waiting for GPS data"**: the aircraft side is not powered, or the radios are not paired or not at 57600 baud. The `gps_and_radio_config` scripts in [415gps](https://github.com/byuflowlab/415gps) set this up.
- **Data arrives but "No GPS fix"**: go outside with open sky, keep the GPS away from the radio, and wait up to a minute.
- **Altitudes look tens of metres off**: the start point was set while the aircraft was elsewhere. Put it at the launch spot and click **Set start here**.
- **"Lost connection to the app"**: the terminal window was closed or the app stopped. Start it again; the course and progress are kept.

## Development

```bash
uv run pytest
```

- `flightlabcopilot/nav.py`: navigation math (local coordinates, steering, bubble and closest approach, boundary).
- `flightlabcopilot/engine.py`: app state; turns each fix into progress and guidance.
- `flightlabcopilot/sources.py`: radio, replay and simulator.
- `flightlabcopilot/app.py`: HTTP routes; live updates go to the browser as Server-Sent Events.
- `flightlabcopilot/static/`: the page (no external libraries, so it works offline).
- `flightlabcopilot/vendor/libnmea_navsat_driver/`: the NMEA parser from 415gps (BSD licence), unchanged apart from relative imports and one regex string prefix.
