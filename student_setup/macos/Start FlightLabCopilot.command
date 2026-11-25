#!/bin/zsh

# Double-click launcher for FlightLabCopilot.
# FlightLabCopilot is pinned so every student uses the same build.
#
# The first launch downloads uv, Python 3.12, and the promoted build into a
# FlightLabCopilot-only folder under ~/.local/share/flightlabcopilot.  Later launches
# start that installed copy directly, so nothing is downloaded or re-resolved
# again until the instructor promotes a new build.  The course, map,
# settings and recordings live in the same folder, outside the environment, so updates keep them.

set -u
set -o pipefail

FLIGHTLABCOPILOT_DEFAULT_COMMIT="b3043560e4919038bbd428350adbc5b5e415ed95"
FLIGHTLABCOPILOT_RELEASE_URL="https://raw.githubusercontent.com/byuflowlab/FlightLabCopilot/main/student_setup/release.txt"
FLIGHTLABCOPILOT_DATA_ROOT="${XDG_DATA_HOME:-${HOME}/.local/share}/flightlabcopilot"
FLIGHTLABCOPILOT_UV_DIR="${FLIGHTLABCOPILOT_DATA_ROOT}/uv"
FLIGHTLABCOPILOT_UV="${FLIGHTLABCOPILOT_UV_DIR}/uv"
FLIGHTLABCOPILOT_RELEASE_FILE="${FLIGHTLABCOPILOT_DATA_ROOT}/release.txt"
FLIGHTLABCOPILOT_RELEASE_TEMP="${FLIGHTLABCOPILOT_DATA_ROOT}/release-download.txt"
FLIGHTLABCOPILOT_ENV_DIR="${FLIGHTLABCOPILOT_DATA_ROOT}/env"
FLIGHTLABCOPILOT_ENV_TEMP="${FLIGHTLABCOPILOT_DATA_ROOT}/env-install"
FLIGHTLABCOPILOT_INSTALLED_FILE="${FLIGHTLABCOPILOT_DATA_ROOT}/installed.txt"
FLIGHTLABCOPILOT_PYTHON="${FLIGHTLABCOPILOT_ENV_DIR}/bin/python"
FLIGHTLABCOPILOT_TEST_ONLY="${FLIGHTLABCOPILOT_TEST_ONLY:-0}"

wait_for_key() {
    echo "Press any key to close this window."
    if [[ "${FLIGHTLABCOPILOT_TEST_ONLY}" != "1" ]]; then
        read -k 1
    fi
}

echo "FlightLabCopilot"
echo "=============================================="
echo

mkdir -p "${FLIGHTLABCOPILOT_DATA_ROOT}"

if [[ ! -x "${FLIGHTLABCOPILOT_UV}" ]]; then
    echo "First-time setup: downloading the FlightLabCopilot launcher..."
    echo "This does not need administrator access."
    echo
    mkdir -p "${FLIGHTLABCOPILOT_UV_DIR}"
    if ! curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="${FLIGHTLABCOPILOT_UV_DIR}" sh; then
        echo
        echo "Setup could not be downloaded. Check the internet connection and try again."
        wait_for_key
        exit 1
    fi
    if [[ ! -x "${FLIGHTLABCOPILOT_UV}" ]]; then
        echo
        echo "Setup finished without creating the launcher."
        echo "Take a screenshot of this window and send it to your TA."
        wait_for_key
        exit 1
    fi
fi

echo "Checking for an update..."
if curl -LsSf --connect-timeout 5 --max-time 15 \
    "${FLIGHTLABCOPILOT_RELEASE_URL}" -o "${FLIGHTLABCOPILOT_RELEASE_TEMP}" \
    && grep -Eq '^[0-9a-f]{40}$' "${FLIGHTLABCOPILOT_RELEASE_TEMP}"; then
    mv "${FLIGHTLABCOPILOT_RELEASE_TEMP}" "${FLIGHTLABCOPILOT_RELEASE_FILE}"
elif [[ -f "${FLIGHTLABCOPILOT_RELEASE_FILE}" ]] \
    && grep -Eq '^[0-9a-f]{40}$' "${FLIGHTLABCOPILOT_RELEASE_FILE}"; then
    echo "The update check was unavailable; using the most recent downloaded version."
else
    echo "The update check was unavailable; using the version included with this launcher."
    printf '%s\n' "${FLIGHTLABCOPILOT_DEFAULT_COMMIT}" > "${FLIGHTLABCOPILOT_RELEASE_FILE}"
fi

read -r FLIGHTLABCOPILOT_COMMIT < "${FLIGHTLABCOPILOT_RELEASE_FILE}"
FLIGHTLABCOPILOT_INSTALLED=""
if [[ -f "${FLIGHTLABCOPILOT_INSTALLED_FILE}" ]]; then
    read -r FLIGHTLABCOPILOT_INSTALLED < "${FLIGHTLABCOPILOT_INSTALLED_FILE}"
fi

if [[ ! -x "${FLIGHTLABCOPILOT_PYTHON}" || "${FLIGHTLABCOPILOT_INSTALLED}" != "${FLIGHTLABCOPILOT_COMMIT}" ]]; then
    FLIGHTLABCOPILOT_REQUIREMENT="flightlabcopilot[pinned] @ https://github.com/byuflowlab/FlightLabCopilot/archive/${FLIGHTLABCOPILOT_COMMIT}.zip"
    echo "Installing build ${FLIGHTLABCOPILOT_COMMIT[1,8]}..."
    echo "The first install downloads Python and FlightLabCopilot's libraries (about 30 MB)"
    echo "and can take a few minutes. Later updates reuse what is already downloaded."
    echo
    rm -rf "${FLIGHTLABCOPILOT_ENV_TEMP}"
    if "${FLIGHTLABCOPILOT_UV}" python install 3.12 \
        && "${FLIGHTLABCOPILOT_UV}" venv --quiet --python 3.12 "${FLIGHTLABCOPILOT_ENV_TEMP}" \
        && "${FLIGHTLABCOPILOT_UV}" pip install --python "${FLIGHTLABCOPILOT_ENV_TEMP}/bin/python" "${FLIGHTLABCOPILOT_REQUIREMENT}"; then
        rm -rf "${FLIGHTLABCOPILOT_ENV_DIR}"
        mv "${FLIGHTLABCOPILOT_ENV_TEMP}" "${FLIGHTLABCOPILOT_ENV_DIR}"
        printf '%s\n' "${FLIGHTLABCOPILOT_COMMIT}" > "${FLIGHTLABCOPILOT_INSTALLED_FILE}"
        echo
    else
        rm -rf "${FLIGHTLABCOPILOT_ENV_TEMP}"
        echo
        if [[ -x "${FLIGHTLABCOPILOT_PYTHON}" && -n "${FLIGHTLABCOPILOT_INSTALLED}" ]]; then
            echo "The update could not be installed; starting the previously installed build instead."
            FLIGHTLABCOPILOT_COMMIT="${FLIGHTLABCOPILOT_INSTALLED}"
        else
            echo "FlightLabCopilot could not be installed. Check the internet connection and try again."
            echo "If the problem continues, take a screenshot of this window and send it to your TA."
            wait_for_key
            exit 1
        fi
    fi
fi

echo "Build: ${FLIGHTLABCOPILOT_COMMIT[1,8]}"
echo "Starting FlightLabCopilot. Your web browser will open when it is ready."
echo
echo "Keep this window open while using FlightLabCopilot."
echo "Click Exit in the app, close this window, or press Control-C when you are finished."
echo

if [[ "${FLIGHTLABCOPILOT_TEST_ONLY}" == "1" ]]; then
    # The server runs until stopped, so the smoke test only imports the app.
    "${FLIGHTLABCOPILOT_PYTHON}" -c "import flightlabcopilot.app; print('FlightLabCopilot imports OK')"
else
    "${FLIGHTLABCOPILOT_PYTHON}" -m flightlabcopilot --data-dir "${FLIGHTLABCOPILOT_DATA_ROOT}"
fi

FLIGHTLABCOPILOT_STATUS=$?
if [[ ${FLIGHTLABCOPILOT_STATUS} -ne 0 && ${FLIGHTLABCOPILOT_STATUS} -ne 130 ]]; then
    echo
    echo "FlightLabCopilot stopped because of an error."
    echo "Take a screenshot of this window and send it to your TA."
    wait_for_key
fi

exit ${FLIGHTLABCOPILOT_STATUS}
