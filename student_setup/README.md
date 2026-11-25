# FlightLabCopilot student launchers

These launchers are the no-Git, no-Python-install route for students and TAs. Give each person the ZIP file for their operating system. The first launch downloads a private copy of Python and FlightLabCopilot; later launches start that copy directly. The launchers are ported from FlightLabFoam's and work the same way.

## Student directions

1. Download the launcher for your computer and unzip it.
2. Open it by double-clicking it (on Linux, run it from a terminal; see below).
3. Keep the small launcher window open while using FlightLabCopilot in your browser.
4. Click **Exit** in the app, or close the launcher window, when you are finished.

The first launch needs an internet connection and takes a few minutes. **Do it before going to the flying field**, which has no internet. Later launches take a few seconds and work offline: the launcher tries to check a small release file, and if it cannot, it starts the installed copy. This setup does not change the computer's normal Python installation and does not require Git or administrator access.

### macOS

Open **Start FlightLabCopilot.command**. If macOS blocks it because it was downloaded, Control-click the file, choose **Open**, and then choose **Open** again. This is normally needed only once.

### Windows

Open **Start FlightLabCopilot.cmd**. If Windows SmartScreen appears, choose **More info**, verify that the file came from the course, and choose **Run anyway**.

### Linux

Open a terminal in the unzipped folder and run `bash "Start FlightLabCopilot.sh"`. Most desktop file managers can also run it directly (right-click, **Run as a Program**), or make it executable once with `chmod +x "Start FlightLabCopilot.sh"`. The script needs `curl` or `wget`, which nearly every distribution includes.

## Updating FlightLabCopilot

Keep using the same launcher. Each time it starts, it checks the small `student_setup/release.txt` file in this repository. If the instructor has promoted a new build, the launcher installs it into a fresh environment. If that install fails part-way (for example, the connection drops), the previously installed build starts instead. If the update check itself fails (no internet at the field), the already-installed build starts without any network access.

## The course, map and recordings survive updates

The launchers pass `--data-dir` pointing at the FlightLabCopilot data folder (see [What the launchers do](#what-the-launchers-do)). The app keeps everything the user makes there: `course.json`, progress, the start point, `settings.json` (radio port, map choice, theme), the map picture or downloaded imagery in `map/`, and the flight recordings in `logs/`. The installed environment lives in the same folder under `env/` and is replaced on every update; nothing else is touched by an update or a reinstall of the environment.

## Library versions are frozen

The `pinned` extra in `pyproject.toml` lists every third-party package at one exact version, resolved once for Windows, macOS, and Linux on Python 3.12. Because the launchers install `flightlabcopilot[pinned]` from the promoted commit, everyone receives the same libraries no matter when they first install or update. Only FlightLabCopilot itself changes from one promoted build to the next.

The pins are generated, not hand-edited, from the core `dependencies` in `pyproject.toml`. Before a course starts, refresh them with `uv` on the PATH:

```bash
python student_setup/update_pins.py
uv lock
uv sync
uv run pytest
uv run flightlabcopilot
```

Then commit and promote as usual. Do not edit the block between `BEGIN PINS` and `END PINS` by hand; rerun the script instead. To add or drop a dependency without moving any other pin, add it to `dependencies` (with `uv add`) and run `python student_setup/update_pins.py --keep`.

## Resetting an installation

Someone whose installed environment is broken can force a clean reinstall of the current build. Re-downloading the launcher ZIP alone does **not** do this: the environment lives outside the ZIP and the launcher will keep starting it. Deleting `installed.txt` makes the next launch rebuild the environment and keeps the course and recordings. Deleting the whole folder also re-downloads `uv` and Python **and deletes the course, map and recordings**, so download the history from the app first.

**Windows.** Press the Windows key and R together, paste `%LOCALAPPDATA%\FlightLabCopilot`, and press Enter. Delete `installed.txt`, or go up one level and delete the whole `FlightLabCopilot` folder. Then open **Start FlightLabCopilot.cmd** again.

**macOS.** Click the desktop so Finder is active, press Shift, Command, and G together, paste `~/.local/share/flightlabcopilot`, and press Return. Drag `installed.txt` to the Trash, or press Command and the up arrow and drag the whole `flightlabcopilot` folder to the Trash. Then open **Start FlightLabCopilot.command** again. From Terminal the equivalent is `rm ~/.local/share/flightlabcopilot/installed.txt`.

**Linux.** Same folder as macOS: `rm ~/.local/share/flightlabcopilot/installed.txt` (or `rm -rf ~/.local/share/flightlabcopilot`), then run the launcher again. If `XDG_DATA_HOME` is set, the folder is under that directory instead.

## What the launchers do

They install `uv` into a FlightLabCopilot-only folder in the user's account (`~/.local/share/flightlabcopilot` on macOS and Linux, `%LOCALAPPDATA%\FlightLabCopilot` on Windows). The first time a build is seen, `uv` downloads Python 3.12, creates a virtual environment in that folder, and installs `flightlabcopilot[pinned]` from the promoted Git commit's source archive on GitHub. The commit hash is recorded in `installed.txt` next to the environment. On every later launch the launcher compares that file with `release.txt` and, when they match, starts the environment's own Python directly with `python -m flightlabcopilot --data-dir <data folder>`.

Each launcher also carries a fallback commit (`FLIGHTLABCOPILOT_DEFAULT_COMMIT`), used only when the very first launch cannot reach `release.txt`. Update it when you rebuild the ZIP files.

Both `release.txt` and the source archives are fetched anonymously, so **the GitHub repository must be public** for the launchers to work.

For a release, first push and test the new code. Then put that tested 40-character commit hash in `student_setup/release.txt` and push that one-file change. Users receive the new build the next time they launch FlightLabCopilot with internet. Commits that have not been placed in `release.txt` are never sent to students.

The **Student launcher smoke tests** GitHub Actions workflow runs the real launcher twice (install, then reuse) on macOS, Windows, and Ubuntu, with `FLIGHTLABCOPILOT_TEST_ONLY=1` so the second run imports the app instead of starting the server. It runs only when a build is released, that is, when a push to `main` changes `release.txt`, so it tests the launchers against the build students are about to get. To test launcher changes before releasing, start it by hand from the repository's **Actions** tab (**Run workflow**).

After editing any launcher or `START HERE.txt`, rebuild the ZIP files:

```bash
./student_setup/build_downloads.sh
```

The files to post are then in `student_setup/downloads/`. The short [release checklist](RELEASE_CHECKLIST.md) covers the first launch, ordinary promotion, and rollback.
