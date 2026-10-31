@echo off
rem Rebuilds every mod and installs the result into the game's Mods folder.
rem Double-click this after changing anything under mods\ - close the game first.
cd /d "%~dp0"

rem --- prerequisites ---------------------------------------------------------------------
where py >nul 2>&1
if errorlevel 1 goto :no_python
py -3.7 -V >nul 2>&1
if errorlevel 1 goto :no_python37

rem --- the game keeps Mods\HouseRules locked while it runs -------------------------------
rem Full paths, so a git-bash/MSYS "find" earlier on PATH cannot shadow these.
"%SystemRoot%\System32\tasklist.exe" /fi "IMAGENAME eq TS4_x64.exe" 2>nul | "%SystemRoot%\System32\findstr.exe" /i /c:"TS4_x64.exe" >nul
if not errorlevel 1 goto :game_running
"%SystemRoot%\System32\tasklist.exe" /fi "IMAGENAME eq TS4.exe" 2>nul | "%SystemRoot%\System32\findstr.exe" /i /c:"TS4.exe" >nul
if not errorlevel 1 goto :game_running

rem --- tests, compile, install -----------------------------------------------------------
echo Building every mod and installing to the Mods folder...
echo.
py -3.7 tools\build.py || goto :failed
echo.
echo Done - start The Sims 4 to play with the new files.
echo If the mods do not show up, check Game Options ^> Other ^> Enable Script Mods.
echo.
pause
exit /b 0

:game_running
echo.
echo The Sims 4 is running. It holds Mods\HouseRules open, so installing
echo would fail. Close the game, then double-click this file again.
echo.
pause
exit /b 1

:failed
echo.
echo The build failed - see the messages above.
echo Nothing was installed when the tests fail; otherwise check that the
echo game is closed and that mods\ contains only valid tuning XML.
echo.
pause
exit /b 1

:no_python
echo.
echo The "py" launcher was not found, so the build cannot run.
echo.
echo   1. Install Python 3.7 from https://www.python.org/downloads/
echo      (tick "py launcher" in the installer).
echo   2. Double-click rebuild.cmd again.
echo.
pause
exit /b 1

:no_python37
echo.
echo Python 3.7 is not installed. The game only loads 3.7 bytecode,
echo so the mods must be built with it.
echo.
echo   1. Install Python 3.7 from https://www.python.org/downloads/
echo      (3.7 is under "Looking for a specific release").
echo   2. Double-click rebuild.cmd again.
echo.
pause
exit /b 1
