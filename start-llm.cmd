@echo off
rem Starts the local LLM for NPC Routines' brain (see llm.json). Double-click before playing.
rem The first time, it installs Ollama and downloads the model (a few GB).
cd /d "%~dp0"
py -3 tools\llm.py status >nul 2>&1
if errorlevel 1 (
  py -3 tools\llm.py install || goto :failed
)
py -3 tools\llm.py start || goto :failed
echo.
pause
exit /b 0

:failed
echo.
echo Something went wrong - see the message above.
pause
exit /b 1
