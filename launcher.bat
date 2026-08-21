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
echo [NIMBY Rails Toolkit] 未找到兼容的 64 位 Python 3.10 或更高版本。
echo 请从 https://www.python.org/downloads/windows/ 安装官方 64 位 Python，
echo 安装时勾选 "Add python.exe to PATH"，然后重新双击“启动工具箱.cmd”。
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
start "" "%PYW%" %PYW_ARGS% "%~dp0toolkit_webapp.py"
exit /b

:zstd_invalid
echo.
echo [NIMBY Rails Toolkit] zstd 运行库缺失、损坏或架构不兼容。
echo 官方便携包已经内置 64 位 libzstd.dll。请重新下载完整 ZIP，
echo 完整解压后确认 libzstd.dll 与 toolkit_binary.py 位于同一目录。
echo 请勿只复制“启动工具箱.cmd”单个文件。
echo.
if /i "%~1"=="--check" exit /b 2
pause
exit /b 2
