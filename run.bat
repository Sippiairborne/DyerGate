@echo off
echo ==^> Preparing directories...
if not exist "data" mkdir data
if not exist "app" mkdir app

if not exist ".env" (
    echo ==^> Copying .env.example to .env
    copy .env.example .env
)

echo ==^> Building DyerGate container...
docker compose build

echo ==^> Starting DyerGate...
docker compose up -d

echo ==^> Waiting for health...
:loop
curl -fsS http://localhost:8080/healthz >nul 2>&1
if %errorlevel% equ 0 (
    echo STATUS: DyerGate online!
    echo.
    echo Platform is running at http://localhost:8080
    echo Analytics Dashboard at http://localhost:8080/analytics
    echo Studio UI at http://localhost:8080/studio
    goto :end
)
timeout /t 2 >nul
goto :loop

:end
