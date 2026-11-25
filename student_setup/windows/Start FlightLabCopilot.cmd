@echo off
setlocal
title FlightLabCopilot

rem Double-click launcher for FlightLabCopilot.
rem FlightLabCopilot is pinned so every student uses the same build.
rem
rem The first launch downloads uv, Python 3.12, and the promoted build into a
rem FlightLabCopilot-only folder under %LOCALAPPDATA%\FlightLabCopilot. Later launches
rem start that installed copy directly, so nothing is downloaded or re-resolved
rem again until the instructor promotes a new build. The course, map,
rem settings and recordings live in the same folder, outside the environment, so updates keep them.

set "FLIGHTLABCOPILOT_DEFAULT_COMMIT=0000000000000000000000000000000000000000"
set "FLIGHTLABCOPILOT_RELEASE_URL=https://raw.githubusercontent.com/byuflowlab/FlightLabCopilot/main/student_setup/release.txt"
set "FLIGHTLABCOPILOT_DATA_ROOT=%LOCALAPPDATA%\FlightLabCopilot"
set "FLIGHTLABCOPILOT_UV_DIR=%FLIGHTLABCOPILOT_DATA_ROOT%\uv"
set "FLIGHTLABCOPILOT_UV=%FLIGHTLABCOPILOT_UV_DIR%\uv.exe"
set "FLIGHTLABCOPILOT_RELEASE_FILE=%FLIGHTLABCOPILOT_DATA_ROOT%\release.txt"
set "FLIGHTLABCOPILOT_RELEASE_TEMP=%FLIGHTLABCOPILOT_DATA_ROOT%\release-download.txt"
set "FLIGHTLABCOPILOT_ENV_DIR=%FLIGHTLABCOPILOT_DATA_ROOT%\env"
set "FLIGHTLABCOPILOT_ENV_TEMP=%FLIGHTLABCOPILOT_DATA_ROOT%\env-install"
set "FLIGHTLABCOPILOT_INSTALLED_FILE=%FLIGHTLABCOPILOT_DATA_ROOT%\installed.txt"
set "FLIGHTLABCOPILOT_PYTHON=%FLIGHTLABCOPILOT_ENV_DIR%\Scripts\python.exe"
set "FLIGHTLABCOPILOT_INSTALLED="

echo FlightLabCopilot
echo ==============================================
echo.

if not exist "%FLIGHTLABCOPILOT_DATA_ROOT%" mkdir "%FLIGHTLABCOPILOT_DATA_ROOT%"

if not exist "%FLIGHTLABCOPILOT_UV%" (
    echo First-time setup: downloading the FlightLabCopilot launcher...
    echo This does not need administrator access.
    echo.
    if not exist "%FLIGHTLABCOPILOT_UV_DIR%" mkdir "%FLIGHTLABCOPILOT_UV_DIR%"
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$env:UV_UNMANAGED_INSTALL='%FLIGHTLABCOPILOT_UV_DIR%'; irm 'https://astral.sh/uv/install.ps1' | iex"
    if errorlevel 1 goto setup_error
    if not exist "%FLIGHTLABCOPILOT_UV%" goto setup_error
)

echo Checking for an update...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$v=(Invoke-RestMethod -TimeoutSec 15 '%FLIGHTLABCOPILOT_RELEASE_URL%').Trim(); if ($v -notmatch '^[0-9a-f]{40}$') { exit 1 }; Set-Content -NoNewline -Path '%FLIGHTLABCOPILOT_RELEASE_TEMP%' -Value $v"
if errorlevel 1 goto update_unavailable
move /Y "%FLIGHTLABCOPILOT_RELEASE_TEMP%" "%FLIGHTLABCOPILOT_RELEASE_FILE%" >nul
goto update_ready

:update_unavailable
if exist "%FLIGHTLABCOPILOT_RELEASE_FILE%" (
    echo The update check was unavailable; using the most recent downloaded version.
    goto update_ready
)
echo The update check was unavailable; using the version included with this launcher.
>"%FLIGHTLABCOPILOT_RELEASE_FILE%" echo %FLIGHTLABCOPILOT_DEFAULT_COMMIT%

:update_ready
set /p FLIGHTLABCOPILOT_COMMIT=<"%FLIGHTLABCOPILOT_RELEASE_FILE%"
if exist "%FLIGHTLABCOPILOT_INSTALLED_FILE%" set /p FLIGHTLABCOPILOT_INSTALLED=<"%FLIGHTLABCOPILOT_INSTALLED_FILE%"
if not exist "%FLIGHTLABCOPILOT_PYTHON%" goto install
if not "%FLIGHTLABCOPILOT_INSTALLED%"=="%FLIGHTLABCOPILOT_COMMIT%" goto install
goto run

:install
set "FLIGHTLABCOPILOT_REQUIREMENT=flightlabcopilot[pinned] @ https://github.com/byuflowlab/FlightLabCopilot/archive/%FLIGHTLABCOPILOT_COMMIT%.zip"
echo Installing build %FLIGHTLABCOPILOT_COMMIT:~0,8%...
echo The first install downloads Python and FlightLabCopilot's libraries (about 30 MB)
echo and can take a few minutes. Later updates reuse what is already downloaded.
echo.
if exist "%FLIGHTLABCOPILOT_ENV_TEMP%" rmdir /s /q "%FLIGHTLABCOPILOT_ENV_TEMP%"
"%FLIGHTLABCOPILOT_UV%" python install 3.12
if errorlevel 1 goto install_failed
"%FLIGHTLABCOPILOT_UV%" venv --quiet --python 3.12 "%FLIGHTLABCOPILOT_ENV_TEMP%"
if errorlevel 1 goto install_failed
"%FLIGHTLABCOPILOT_UV%" pip install --python "%FLIGHTLABCOPILOT_ENV_TEMP%\Scripts\python.exe" "%FLIGHTLABCOPILOT_REQUIREMENT%"
if errorlevel 1 goto install_failed
if exist "%FLIGHTLABCOPILOT_ENV_DIR%" rmdir /s /q "%FLIGHTLABCOPILOT_ENV_DIR%"
move "%FLIGHTLABCOPILOT_ENV_TEMP%" "%FLIGHTLABCOPILOT_ENV_DIR%" >nul
if errorlevel 1 goto install_failed
>"%FLIGHTLABCOPILOT_INSTALLED_FILE%" echo %FLIGHTLABCOPILOT_COMMIT%
echo.
goto run

:install_failed
if exist "%FLIGHTLABCOPILOT_ENV_TEMP%" rmdir /s /q "%FLIGHTLABCOPILOT_ENV_TEMP%"
echo.
if not exist "%FLIGHTLABCOPILOT_PYTHON%" goto install_error
if "%FLIGHTLABCOPILOT_INSTALLED%"=="" goto install_error
echo The update could not be installed; starting the previously installed build instead.
set "FLIGHTLABCOPILOT_COMMIT=%FLIGHTLABCOPILOT_INSTALLED%"
goto run

:run
echo Build: %FLIGHTLABCOPILOT_COMMIT:~0,8%
echo Starting FlightLabCopilot. Your web browser will open when it is ready.
echo.
echo Keep this window open while using FlightLabCopilot.
echo Click Exit in the app, close this window, or press Control-C when you are finished.
echo.

rem The server runs until stopped, so the smoke test only imports the app.
if "%FLIGHTLABCOPILOT_TEST_ONLY%"=="1" (
    "%FLIGHTLABCOPILOT_PYTHON%" -c "import flightlabcopilot.app; print('FlightLabCopilot imports OK')"
) else (
    "%FLIGHTLABCOPILOT_PYTHON%" -m flightlabcopilot --data-dir "%FLIGHTLABCOPILOT_DATA_ROOT%"
)
if errorlevel 1 goto run_error
exit /b 0

:setup_error
echo.
echo Setup could not be downloaded. Check the internet connection and try again.
echo If the problem continues, take a screenshot of this window and send it to your TA.
if "%FLIGHTLABCOPILOT_TEST_ONLY%"=="1" exit /b 1
pause
exit /b 1

:install_error
echo FlightLabCopilot could not be installed. Check the internet connection and try again.
echo If the problem continues, take a screenshot of this window and send it to your TA.
if "%FLIGHTLABCOPILOT_TEST_ONLY%"=="1" exit /b 1
pause
exit /b 1

:run_error
echo.
echo FlightLabCopilot stopped because of an error.
echo Take a screenshot of this window and send it to your TA.
if "%FLIGHTLABCOPILOT_TEST_ONLY%"=="1" exit /b 1
pause
exit /b 1
