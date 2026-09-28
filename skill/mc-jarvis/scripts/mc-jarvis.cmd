@echo off
rem Run mc-jarvis from this skill folder (Windows cmd and PowerShell).
rem A release bundles the package beside this file, at mc_jarvis\.
rem Without it, falls through to an installed mc-jarvis.
rem MC_JARVIS_INVOKED_AS is how the reader typed it, so a message naming
rem the next command names one that exists.
setlocal
set "MC_JARVIS_INVOKED_AS=%~f0"
if not exist "%~dp0mc_jarvis\__main__.py" goto installed
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
goto choose
:installed
where mc-jarvis >nul 2>nul
if errorlevel 1 goto choose
mc-jarvis %*
exit /b
:choose
if defined MC_JARVIS_PYTHON goto custom
rem The py launcher first: `python` may be the Microsoft Store stub.
where py >nul 2>nul
if errorlevel 1 goto plain
py -3 -m mc_jarvis %*
exit /b
:custom
"%MC_JARVIS_PYTHON%" -m mc_jarvis %*
exit /b
:plain
python -m mc_jarvis %*
exit /b
