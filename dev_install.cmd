@echo off
REM Wrapper for dev_install.ps1.
REM
REM Windows blocks .ps1 files by default ("running scripts is disabled on this
REM system"), and weakening the machine's execution policy to run one dev
REM helper is not a trade worth making. A .cmd file is not subject to that
REM policy, and -ExecutionPolicy Bypass here applies to this one process only
REM -- nothing on the system is changed.
REM
REM   dev_install.cmd status
REM   dev_install.cmd dev
REM   dev_install.cmd prod
REM
REM -NoProfile keeps a slow or noisy PowerShell profile out of the way.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev_install.ps1" %*
