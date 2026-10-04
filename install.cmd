@echo off
rem Double-click this file to install (or update) PrivacyWorm on Windows.
rem It runs install.ps1 - from this folder if it's here, otherwise the latest from GitHub.
rem If Windows shows "Windows protected your PC", click "More info" then "Run anyway".
title PrivacyWorm installer
if exist "%~dp0install.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/simonlpaige/privacyworm/main/install.ps1 | iex"
)
echo.
pause
