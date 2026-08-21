@echo off
rem Smart App Control directly checks Windows Script Host files such as VBS.
rem Keep the public entry point on cmd.exe and let the signed Python runtime
rem execute the local source instead.
call "%~dp0launcher.bat"
exit /b %errorlevel%
