<#
  Instala (o reinstala) blender-steroids en los agentes de esta PC.
  Las skills viven una sola vez en ~/.blender-steroids/skills y cada agente las ve por un enlace
  (junction), así que editarlas o actualizarlas aquí las cambia en todos.

  Sin clonar nada (descarga blender-steroids en ~/.blender-steroids o lo actualiza):
    irm https://raw.githubusercontent.com/kennedy122112/blender-steroids/main/install.ps1 | iex

  Desde una copia del repositorio:
    powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1
    ... -Uninstall   quita los enlaces (no borra los archivos)
#>
param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
$h = $env:USERPROFILE
$repo = 'https://github.com/kennedy122112/blender-steroids'

# Ejecutado con "irm … | iex": no hay archivo, así que se trae el repositorio y se instala desde ahí.
if (-not $PSCommandPath) {
  $dest = "$h\.blender-steroids"
  if (Test-Path "$dest\install.ps1") {
    if (Test-Path "$dest\.git") { git -C $dest pull -q --ff-only }
    else { Write-Host "Ya existe $dest (sin git): se reinstala tal como está." }
  } elseif (Test-Path $dest) {
    throw "$dest existe y no es blender-steroids: muévelo o bórralo antes de instalar."
  } elseif (Get-Command git -ErrorAction SilentlyContinue) {
    git clone -q "$repo.git" $dest
  } else {
    $zip = Join-Path $env:TEMP 'blender-steroids.zip'
    Invoke-WebRequest "$repo/archive/refs/heads/main.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive $zip -DestinationPath $env:TEMP -Force
    Move-Item (Join-Path $env:TEMP 'blender-steroids-main') $dest
    Remove-Item $zip
  }
  & powershell -NoProfile -ExecutionPolicy Bypass -File "$dest\install.ps1"
  return
}

$root = Split-Path -Parent $PSCommandPath

# Carpeta de skills de cada agente. Solo se instala donde el agente ya existe.
$destinos = [ordered]@{
  'Claude Code'             = @{ base = "$h\.claude";              skills = "$h\.claude\skills" }
  'Codex y otros (.agents)' = @{ base = "$h\.agents";              skills = "$h\.agents\skills" }
  'OpenCode'                = @{ base = "$h\.config\opencode";     skills = "$h\.config\opencode\skills" }
  'Antigravity'             = @{ base = "$h\.gemini\antigravity";  skills = "$h\.gemini\antigravity\skills" }
}

# Las skills llaman al puente por ~/.blender-steroids: si el repositorio está en otra carpeta,
# ~/.blender-steroids es un enlace hacia él.
$casa = "$h\.blender-steroids"
$rootReal = (Get-Item $root).FullName
$casaItem = Get-Item $casa -Force -ErrorAction SilentlyContinue
if (-not $Uninstall -and -not ($casaItem -and ($casaItem.FullName -eq $rootReal -or "$($casaItem.Target)" -eq $rootReal))) {
  if ($casaItem -and $casaItem.LinkType -ne 'Junction') { throw "$casa existe y es una carpeta real: muévela o bórrala antes de instalar." }
  if ($casaItem) { [IO.Directory]::Delete($casa) }
  New-Item -ItemType Junction -Path $casa -Target $rootReal | Out-Null
  "~/.blender-steroids             -> $rootReal"
}

$skills = Get-ChildItem "$root\skills" -Directory
foreach ($agente in $destinos.Keys) {
  $d = $destinos[$agente]
  if (-not (Test-Path $d.base)) { "{0,-24} no instalado, se omite" -f $agente; continue }
  if (-not $Uninstall) { New-Item -ItemType Directory -Force $d.skills | Out-Null }
  foreach ($s in $skills) {
    $link = Join-Path $d.skills $s.Name
    $item = Get-Item $link -Force -ErrorAction SilentlyContinue
    if ($item) {
      if ($item.LinkType -ne 'Junction') { "{0,-24} {1}: existe una carpeta real, no se toca" -f $agente, $s.Name; continue }
      [IO.Directory]::Delete($link)   # quita solo el enlace, nunca el contenido
    }
    if (-not $Uninstall) { New-Item -ItemType Junction -Path $link -Target $s.FullName | Out-Null }
  }
  "{0,-24} {1} ({2})" -f $agente, $(if ($Uninstall) { 'enlaces quitados' } else { "$($skills.Count) skills enlazadas" }), $d.skills
}
if (-not $Uninstall) { "blender-steroids instalado. Abre una sesión nueva en tu agente y pídele: «conecta con Blender»." }
