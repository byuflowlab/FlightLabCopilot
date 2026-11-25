#!/bin/sh

# Rebuild the ZIP files posted for students and TAs. Run from any directory.

set -eu

FLIGHTLABCOPILOT_SETUP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FLIGHTLABCOPILOT_DOWNLOAD_DIR="${FLIGHTLABCOPILOT_SETUP_DIR}/downloads"

mkdir -p "${FLIGHTLABCOPILOT_DOWNLOAD_DIR}"

cd "${FLIGHTLABCOPILOT_SETUP_DIR}/macos"
zip -q -r -FS "${FLIGHTLABCOPILOT_DOWNLOAD_DIR}/FlightLabCopilot-macOS.zip" .

cd "${FLIGHTLABCOPILOT_SETUP_DIR}/windows"
zip -q -r -FS "${FLIGHTLABCOPILOT_DOWNLOAD_DIR}/FlightLabCopilot-Windows.zip" .

cd "${FLIGHTLABCOPILOT_SETUP_DIR}/linux"
zip -q -r -FS "${FLIGHTLABCOPILOT_DOWNLOAD_DIR}/FlightLabCopilot-Linux.zip" .

echo "Student downloads are ready in:"
echo "${FLIGHTLABCOPILOT_DOWNLOAD_DIR}"
