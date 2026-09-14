@echo off
setlocal

set ORIGEN=C:\David\Personal\ProyectoBetPredictor
set DESTINO=C:\xampp\htdocs\ProyectoBetPredictor

echo Copiando archivos modificados a la carpeta de Apache...
echo.

if not exist "%ORIGEN%" (
    echo ERROR: No existe la carpeta origen "%ORIGEN%"
    pause
    exit /b 1
)

if not exist "%DESTINO%" (
    echo ERROR: No existe la carpeta destino "%DESTINO%"
    pause
    exit /b 1
)

copy /Y "%ORIGEN%\estadisticas_ultimos_cinco_mobile.py" "%DESTINO%\estadisticas_ultimos_cinco_mobile.py"
if errorlevel 1 (
    echo ERROR: No se pudo copiar estadisticas_ultimos_cinco_mobile.py
    pause
    exit /b 1
)
echo OK: estadisticas_ultimos_cinco_mobile.py copiado

copy /Y "%ORIGEN%\run_stats.php" "%DESTINO%\run_stats.php"
if errorlevel 1 (
    echo ERROR: No se pudo copiar run_stats.php
    pause
    exit /b 1
)
echo OK: run_stats.php copiado

copy /Y "%ORIGEN%\clasificacion_partidos.php" "%DESTINO%\clasificacion_partidos.php" >nul 2>&1
if not errorlevel 1 echo OK: clasificacion_partidos.php copiado

copy /Y "%ORIGEN%\refresh_partidos.py" "%DESTINO%\refresh_partidos.py" >nul 2>&1
if not errorlevel 1 echo OK: refresh_partidos.py copiado

copy /Y "%ORIGEN%\refresh_partidos.php" "%DESTINO%\refresh_partidos.php" >nul 2>&1
if not errorlevel 1 echo OK: refresh_partidos.php copiado

echo.
echo Copia completada. Recarga http://localhost/ProyectoBetPredictor/clasificacion_partidos.php
pause
