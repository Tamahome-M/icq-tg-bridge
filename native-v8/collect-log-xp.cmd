@echo off
setlocal EnableExtensions DisableDelayedExpansion
title TeleMotoMax V8 log collector
echo TeleMotoMax Native - Windows XP log collector
echo.
echo 1. On the phone, reproduce the problem and run collect-log.lin.
echo 2. Connect the phone in USB memory / mass storage mode.
echo.
set "tmm_source="
set "tmm_candidate=%~1"
if not "%~1"=="" call :probe
if defined tmm_source goto found
for %%D in (D E F G H I J K L M N O P Q R S T U V W X Y Z) do call :drive %%D
if defined tmm_source goto found
echo TeleMotoMax-log.txt was not found on the connected drives.
echo Run collect-log.lin on the phone before connecting USB memory.
echo You can also drag the phone's TeleMotoMax-Native folder onto this script,
echo or run: collect-log-xp.cmd F:\TeleMotoMax-Native
echo.
pause
exit /b 2

:drive
if defined tmm_source exit /b
set "tmm_candidate=%1:\"
call :probe
set "tmm_candidate=%1:\TeleMotoMax-Native"
call :probe
set "tmm_candidate=%1:\mystuff\TeleMotoMax-Native"
call :probe
set "tmm_candidate=%1:\download\mystuff\TeleMotoMax-Native"
call :probe
set "tmm_candidate=%1:\ezxlocal\download\mystuff\TeleMotoMax-Native"
call :probe
exit /b

:probe
if defined tmm_source exit /b
if exist "%tmm_candidate%\TeleMotoMax-log.txt" set "tmm_source=%tmm_candidate%\TeleMotoMax-log.txt"
exit /b

:found
if not defined USERPROFILE goto no_profile
set "tmm_output=%USERPROFILE%\TeleMotoMax-logs"
if not exist "%tmm_output%\" mkdir "%tmm_output%"
if not exist "%tmm_output%\" goto failed
set "tmm_index=0"
:next_name
set /a tmm_index+=1 >nul
set "tmm_report=%tmm_output%\TeleMotoMax-log-%tmm_index%.txt"
if exist "%tmm_report%" goto next_name
copy /b "%tmm_source%" "%tmm_report%" >nul
if errorlevel 1 goto failed
echo Saved:
echo "%tmm_report%"
echo.
echo Send this text file with your bug report.
echo.
pause
exit /b 0

:no_profile
echo USERPROFILE is missing. Run this script under your Windows account.
echo.
pause
exit /b 1

:failed
echo Could not copy the log. Check the USB connection and free disk space.
echo.
pause
exit /b 1
