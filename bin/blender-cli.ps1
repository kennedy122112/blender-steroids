<#
  blender-cli.ps1 - lanza blender_cli.py con el Python que haya en esta PC.
  Si no hay Python instalado usa el que trae Blender, así que no hace falta instalar nada más.

    blender-cli.ps1 status
    blender-cli.ps1 build -Spec escena.json
    blender-cli.ps1 render -Path vista.png -Preview
#>
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$cli = Join-Path $PSScriptRoot 'blender_cli.py'

$py = $null
foreach ($c in 'python', 'py') {
  $cmd = Get-Command $c -ErrorAction SilentlyContinue
  # el alias de la Microsoft Store (WindowsApps) abre la tienda en vez de ejecutar Python
  if ($cmd -and $cmd.Source -notmatch 'WindowsApps') { $py = $cmd.Source; break }
}
if (-not $py) {
  $blender = if ($env:BLENDER_STEROIDS_BLENDER) { Split-Path $env:BLENDER_STEROIDS_BLENDER } else {
    Get-ChildItem "$env:ProgramFiles\Blender Foundation" -Directory -ErrorAction SilentlyContinue |
      Sort-Object Name -Descending | Select-Object -First 1 -ExpandProperty FullName }
  if ($blender) {
    $py = Get-ChildItem $blender -Filter python.exe -Recurse -Depth 4 -ErrorAction SilentlyContinue |
      Where-Object { $_.FullName -match '\\python\\bin\\' } | Select-Object -First 1 -ExpandProperty FullName
  }
}
if (-not $py) {
  '{ "ok": false, "error": "No hay Python ni Blender instalados en esta PC. Instala Blender desde blender.org." }'
  exit 1
}
& $py -I $cli @args
exit $LASTEXITCODE
