@echo off
echo Building Nomad Media Transfer Tool...
echo.

set PROJECT_PATH=tools\NomadTransferTool\NomadTransferTool.csproj
set OUTPUT_PATH=tools\NomadTransferTool\publish

if not exist tools\NomadTransferTool (
    echo Error: Could not find tools\NomadTransferTool directory.
    pause
    exit /b 1
)

echo Cleaning old builds...
if exist %OUTPUT_PATH% rd /s /q %OUTPUT_PATH%

echo.
echo Publishing standalone EXE (win-x64)...
dotnet publish %PROJECT_PATH% -c Release -r win-x64 --self-contained true /p:PublishSingleFile=true /p:PublishReadyToRun=true /p:IncludeNativeLibrariesForSelfExtract=true -o %OUTPUT_PATH%

if %ERRORLEVEL% EQU 0 (
    echo.
    echo SUCCESS! Standalone tool created at: %OUTPUT_PATH%\NomadTransferTool.exe
) else (
    echo.
    echo FAILED to build Nomad Media Transfer Tool.
)

echo.
pause
