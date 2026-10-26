@echo off
rem Starts the local LLM for NPC Routines' brain (see llm.json). Double-click before playing.
rem The first time, it installs Ollama and downloads the model (a few GB).
rem After that it follows the brain's log, so you can watch each prompt, answer and (for a
rem thinking model) its reasoning as the game asks.
cd /d "%~dp0"

rem --- prerequisites ---------------------------------------------------------------------
where py >nul 2>&1
if errorlevel 1 goto :no_python
py -3 -V >nul 2>&1
if errorlevel 1 goto :no_python

rem --- install once, then start ----------------------------------------------------------
py -3 tools\llm.py status >nul 2>&1
if errorlevel 1 (
  echo The local model isn't ready yet - installing it now ^(a few GB the first time^).
  py -3 tools\llm.py install || goto :failed
)
py -3 tools\llm.py start || goto :failed

echo.
echo ---------------------------------------------------------------
echo Watching the brain. Each decision shows the prompt, the answer,
echo and the model's thinking (for a thinking model). Close this
echo window to stop watching - the model keeps running.
echo ---------------------------------------------------------------
echo.
py -3 tools\llm_tail.py
exit /b 0

:no_python
echo.
echo Python 3 is required to start the local LLM, and the "py" launcher
echo was not found.
echo.
echo   1. Install Python 3 from https://www.python.org/downloads/
echo      (tick "py launcher" in the installer) or from the Microsoft Store.
echo   2. Double-click start-llm.cmd again.
echo.
pause
exit /b 1

:failed
echo.
echo The local LLM could not be started. Check, in this order:
echo   * Ollama is installed - get it from https://ollama.com/download if not.
echo   * You are online for the first model download (a few GB).
echo   * The port in llm.json (11434) is not used by another program.
echo   * Details: py -3 tools\llm.py status
echo.
pause
exit /b 1
