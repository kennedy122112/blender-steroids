@echo off
rem blender-cli.cmd - lanza blender_cli.py sin pasar por PowerShell.
rem PowerShell imprime avisos propios al arrancar (por ejemplo, «InitializeDefaultDrives» cuando una
rem unidad de red no responde) que un agente puede confundir con un fallo del comando. cmd no.
rem Usa el Python de la PC o, si no hay, el que trae Blender.
rem
rem   blender-cli.cmd status
rem   blender-cli.cmd build -Spec escena.json
setlocal EnableDelayedExpansion
set "PYTHONIOENCODING=utf-8"
set "PY="

rem el alias de la Microsoft Store (WindowsApps) abre la tienda en vez de ejecutar Python
for /f "delims=" %%P in ('where python 2^>nul') do (
  if not defined PY (
    echo %%P | findstr /i "WindowsApps" >nul || set "PY=%%P"
  )
)
if not defined PY (
  where py >nul 2>nul && set "PY=py"
)
if not defined PY (
  set "BROOT=%ProgramFiles%\Blender Foundation"
  if defined BLENDER_STEROIDS_BLENDER for %%B in ("%BLENDER_STEROIDS_BLENDER%") do set "BROOT=%%~dpB"
  for /f "delims=" %%F in ('dir /b /s "!BROOT!\python.exe" 2^>nul ^| findstr /i "\\python\\bin\\python.exe"') do (
    if not defined PY set "PY=%%F"
  )
)
if not defined PY (
  echo { "ok": false, "error": "No hay Python ni Blender instalados en esta PC. Instala Blender desde blender.org." }
  exit /b 1
)
"%PY%" -I "%~dp0blender_cli.py" %*
exit /b %ERRORLEVEL%
