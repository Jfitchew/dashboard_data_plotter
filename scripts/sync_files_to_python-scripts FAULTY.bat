@echo off
setlocal enabledelayedexpansion

REM ==========================================
REM CONFIGURATION
REM ==========================================

set "CONFIG=sync_config.txt"
set "DEST=C:\Users\user\OneDrive\Documents\Coding\BodyRocket\python-scripts\Jason_scripts\dashboard_data_plotter"

REM ==========================================
REM ENABLE ANSI COLOURS
REM ==========================================

for /f "delims=" %%A in ('echo prompt $E^| cmd') do set "ESC=%%A"

set "C_RESET=%ESC%[0m"
set "C_RED=%ESC%[31m"
set "C_GREEN=%ESC%[32m"
set "C_YELLOW=%ESC%[33m"
set "C_BLUE=%ESC%[34m"

REM ==========================================
REM TEMP FILES
REM ==========================================

set "TMP_FOLDERS=%TEMP%\sync_folders.tmp"
set "TMP_IGNORE_FILES=%TEMP%\sync_ignore_files.tmp"
set "TMP_IGNORE_DIRS=%TEMP%\sync_ignore_dirs.tmp"

del "%TMP_FOLDERS%" 2>nul
del "%TMP_IGNORE_FILES%" 2>nul
del "%TMP_IGNORE_DIRS%" 2>nul

REM ==========================================
REM PARSE CONFIG FILE SAFELY
REM ==========================================

set "MODE="

for /f "usebackq delims=" %%L in ("%CONFIG%") do (
    set "LINE=%%L"

    if "!LINE!"=="" (
        rem skip
    ) else (
        rem Skip comments
        echo "!LINE!" > "%TEMP%\_line.tmp"
        findstr /b "#" "%TEMP%\_line.tmp" >nul
        if !errorlevel! == 0 (
            rem skip
        ) else (
            rem Detect section headers safely
            set "IS_HEADER=0"
            findstr /x "\[FOLDERS\]" "%TEMP%\_line.tmp" >nul && (set "MODE=FOLDERS" & set "IS_HEADER=1")
            findstr /x "\[IGNORE_FILES\]" "%TEMP%\_line.tmp" >nul && (set "MODE=IGNORE_FILES" & set "IS_HEADER=1")
            findstr /x "\[IGNORE_DIRS\]" "%TEMP%\_line.tmp" >nul && (set "MODE=IGNORE_DIRS" & set "IS_HEADER=1")

            rem Append values
            if "!IS_HEADER!"=="0" (
                if "!MODE!"=="FOLDERS"       echo %%L>>"%TMP_FOLDERS%"
                if "!MODE!"=="IGNORE_FILES"  echo %%L>>"%TMP_IGNORE_FILES%"
                if "!MODE!"=="IGNORE_DIRS"   echo %%L>>"%TMP_IGNORE_DIRS%"
            )
        )
    )
)
del "%TEMP%\_line.tmp" 2>nul

REM ==========================================
REM SYNC USING ROBOCOPY
REM ==========================================

echo %C_BLUE%Syncing folders with ignore rules...%C_RESET%
echo -------------------------------------

for /f "usebackq delims=" %%S in ("%TMP_FOLDERS%") do (

    set "SRC=%%S"

    if exist "!SRC!" (
        echo %C_BLUE%Syncing: !SRC!%C_RESET%

        REM Build ignore args fresh each time (safe)
        set "IGNORE_ARGS="

        for /f "usebackq delims=" %%F in ("%TMP_IGNORE_FILES%") do (
            set "IGNORE_ARGS=!IGNORE_ARGS! /XF ""%%F"""
        )

        for /f "usebackq delims=" %%D in ("%TMP_IGNORE_DIRS%") do (
            set "IGNORE_ARGS=!IGNORE_ARGS! /XD ""%%D"""
        )

        robocopy "!SRC!" "%DEST%\%%~nS" /E /XO /COPY:DAT /R:1 /W:1 !IGNORE_ARGS! >nul
        set "RC=!ERRORLEVEL!"

        if !RC! LSS 8 (
            if !RC! EQU 0 (
                echo %C_YELLOW%No changes needed.%C_RESET%
            ) else (
                echo %C_GREEN%Updated (files copied or synced).%C_RESET%
            )
        ) else (
            echo %C_RED%Error during sync (code !RC!).%C_RESET%
        )

    ) else (
        echo %C_RED%[WARNING] Folder not found: !SRC!%C_RESET%
    )
)

echo.
echo %C_GREEN%Done.%C_RESET%
pause
