@echo off
setlocal
cd /d "%~dp0"

rem Use pythonw (no console). Python's official Windows installer provides it.
set "PYW=%NIMBY_TOOLKIT_PYTHONW%"
set "PYW_ARGS="
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe"
if defined PYW goto validate

where pythonw.exe >nul 2>nul
if not errorlevel 1 (
  set "PYW=pythonw.exe"
  goto validate
)

where pyw.exe >nul 2>nul
if not errorlevel 1 (
  set "PYW=pyw.exe"
  set "PYW_ARGS=-3"
  goto validate
)

:not_found
echo.
echo [NIMBY Rails Toolkit] 未找到 Python 3。
echo 请从 https://www.python.org/downloads/windows/ 安装官方 64 位 Python，
echo 安装时勾选 "Add python.exe to PATH"，然后重新双击“启动工具箱.cmd”。
echo.
pause
exit /b 1

:validate
"%PYW%" %PYW_ARGS% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto not_found

:launch
if /i "%~1"=="--check" (
  echo launcher-ok using "%PYW%" %PYW_ARGS%
  exit /b 0
)
start "" "%PYW%" %PYW_ARGS% "%~dp0toolkit_webapp.py"
exit /b
