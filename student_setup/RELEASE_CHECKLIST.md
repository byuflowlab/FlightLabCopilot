# FlightLabCopilot student release checklist

## One-time launch

1. Make the GitHub repository public. The launchers download `release.txt` and the source archive without logging in.
2. Commit and push the app, `student_setup/`, the tests, and the GitHub Actions workflow to `main`.
3. Put the pushed commit's hash in `student_setup/release.txt` and in `FLIGHTLABCOPILOT_DEFAULT_COMMIT` in all three launchers (they start as forty zeros, which no launcher can install), rebuild the ZIP files with `./student_setup/build_downloads.sh`, and push again.
4. Open the repository's **Actions** tab and confirm that **Student launcher smoke tests** passes on macOS, Windows, and Linux.
5. Post these three files on the course site:
   - `student_setup/downloads/FlightLabCopilot-macOS.zip`
   - `student_setup/downloads/FlightLabCopilot-Windows.zip`
   - `student_setup/downloads/FlightLabCopilot-Linux.zip`

## Ordinary code update

1. Finish and test the changes (`uv run pytest`, then open the app once and fly the simulator).
2. Commit and push them to `main`.
3. Run `git rev-parse HEAD` and copy the full 40-character commit hash.
4. Replace the hash in `student_setup/release.txt` and push that one-file change.
5. Tell users to click **Exit** and reopen FlightLabCopilot **while they have internet**. Their existing launcher checks the release file and installs the promoted build into a fresh environment (under a minute; downloaded libraries are reused). Their course, map and recordings are kept.

Do not promote a build on a flying day: a launcher at the field cannot reach GitHub and keeps the old build, which is fine, but a half-finished update elsewhere is not worth the risk.

Do not rebuild or repost the ZIP files for an ordinary code update. Rebuild them only when a launcher or its `START HERE.txt` file changes.

## Library refresh

Do this before a course starts, not during it.

1. With `uv` on the PATH, run `python student_setup/update_pins.py`, then `uv lock`.
2. Run the tests and open the app once with the new pins.
3. Commit, push, and promote the commit exactly like an ordinary code update. No new ZIP files are needed.

## Rollback

Put the last known-good commit hash back in `student_setup/release.txt` and push the change. Users return to that build the next time they launch FlightLabCopilot with internet.
