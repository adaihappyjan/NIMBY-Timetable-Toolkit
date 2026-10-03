@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0NIMBYToolkit.exe" if /i not "%~1"=="--check" (
  start "" "%~dp0NIMBYToolkit.exe"
  exit /b 0
)

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
echo [NIMBY Rails Toolkit] Compatible 64-bit Python 3.10+ was not found.
echo Use the portable EXE release, or install official 64-bit Python from:
echo https://www.python.org/downloads/windows/ and enable "Add python.exe to PATH".
echo.
pause
exit /b 1

:validate
"%PYW%" %PYW_ARGS% -c "import struct,sys; raise SystemExit(0 if sys.version_info >= (3, 10) and struct.calcsize('P') == 8 else 1)" >nul 2>nul
if errorlevel 1 goto not_found

rem Verify the actual zstd runtime before opening a window. Official portable
rem releases include a pinned AMD64 libzstd.dll next to toolkit_binary.py.
"%PYW%" %PYW_ARGS% -c "from toolkit_binary import Zstd; Zstd()" >nul 2>nul
if errorlevel 1 goto zstd_invalid

:launch
if /i "%~1"=="--check" (
  echo launcher-ok using "%PYW%" %PYW_ARGS%
  exit /b 0
)
rem Use the logged no-console entry point, same as the portable EXE.
start "" "%PYW%" %PYW_ARGS% "%~dp0toolkit_start.py"
exit /b

:zstd_invalid
echo.
echo [NIMBY Rails Toolkit] zstd is missing, damaged or incompatible.
echo The official portable release includes 64-bit libzstd.dll.
echo Extract the complete ZIP. Keep libzstd.dll beside toolkit_binary.py.
echo Do not copy the launcher out by itself.
echo.
if /i "%~1"=="--check" exit /b 2
pause
exit /b 2
