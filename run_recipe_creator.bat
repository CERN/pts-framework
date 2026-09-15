@echo off
REM SPDX-FileCopyrightText: 2026 CERN <home.cern>
REM
REM SPDX-License-Identifier: LGPL-2.1-or-later
REM
REM Starts the Recipe Creator via run_recipe_creator.py.
REM Uses the repository's .venv when there is one, otherwise "python" on PATH.

setlocal
set "REPO_ROOT=%~dp0"
set "PYTHON=%REPO_ROOT%.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

"%PYTHON%" "%REPO_ROOT%run_recipe_creator.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

REM Keep the window open on failure when started by double-click, so the error can be read.
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
