#!/usr/bin/env bash
# Instala (o reinstala) blender-steroids en los agentes de esta máquina (macOS y Linux).
# Las skills viven una sola vez en ~/.blender-steroids/skills y cada agente las ve por un enlace
# simbólico, así que editarlas o actualizarlas aquí las cambia en todos.
#
# Sin clonar nada (descarga blender-steroids en ~/.blender-steroids o lo actualiza):
#   curl -fsSL https://raw.githubusercontent.com/kennedy122112/blender-steroids/main/install.sh | bash
#
# Desde una copia del repositorio:
#   bash install.sh
#   bash install.sh --uninstall   quita los enlaces (no borra los archivos)
set -eu

repo='https://github.com/kennedy122112/blender-steroids'
casa="$HOME/.blender-steroids"
uninstall=0
[ "${1:-}" = "--uninstall" ] && uninstall=1

# Ejecutado con "curl … | bash": no hay archivo, así que se trae el repositorio y se instala desde ahí.
src="${BASH_SOURCE[0]:-}"
if [ -z "$src" ] || [ ! -f "$src" ]; then
  if [ -f "$casa/install.sh" ]; then
    if [ -d "$casa/.git" ]; then git -C "$casa" pull -q --ff-only
    else echo "Ya existe $casa (sin git): se reinstala tal como está."; fi
  elif [ -e "$casa" ]; then
    echo "$casa existe y no es blender-steroids: muévelo o bórralo antes de instalar." >&2; exit 1
  elif command -v git >/dev/null 2>&1; then
    git clone -q "$repo.git" "$casa"
  else
    tmp="$(mktemp -d)"
    curl -fsSL "$repo/archive/refs/heads/main.tar.gz" | tar -xz -C "$tmp"
    mv "$tmp/blender-steroids-main" "$casa"
  fi
  exec bash "$casa/install.sh" "$@"
fi

root="$(cd "$(dirname "$src")" && pwd -P)"
chmod +x "$root/bin/blender-cli" 2>/dev/null || true

# Las skills llaman al puente por ~/.blender-steroids: si el repositorio está en otra carpeta,
# ~/.blender-steroids es un enlace hacia él.
if [ "$uninstall" = 0 ]; then
  if [ -L "$casa" ]; then
    [ "$(cd "$casa" && pwd -P)" = "$root" ] || { rm "$casa"; ln -s "$root" "$casa"; echo "~/.blender-steroids -> $root"; }
  elif [ -e "$casa" ]; then
    [ "$(cd "$casa" && pwd -P)" = "$root" ] || { echo "$casa existe y es una carpeta real: muévela o bórrala antes de instalar." >&2; exit 1; }
  else
    ln -s "$root" "$casa"; echo "~/.blender-steroids -> $root"
  fi
fi

# Carpeta de skills de cada agente. Solo se instala donde el agente ya existe.
agentes=("Claude Code|$HOME/.claude"
         "Codex y otros (.agents)|$HOME/.agents"
         "OpenCode|$HOME/.config/opencode"
         "Antigravity|$HOME/.gemini/antigravity")
for a in "${agentes[@]}"; do
  nombre="${a%%|*}"; base="${a#*|}"; dest="$base/skills"
  if [ ! -d "$base" ]; then printf '%-24s no instalado, se omite\n' "$nombre"; continue; fi
  [ "$uninstall" = 0 ] && mkdir -p "$dest"
  n=0
  for s in "$root"/skills/*/; do
    s="${s%/}"; link="$dest/$(basename "$s")"
    if [ -e "$link" ] && [ ! -L "$link" ]; then
      printf '%-24s %s: existe una carpeta real, no se toca\n' "$nombre" "$(basename "$s")"; continue
    fi
    rm -f "$link"   # quita solo el enlace, nunca el contenido
    if [ "$uninstall" = 0 ]; then ln -s "$s" "$link"; n=$((n + 1)); fi
  done
  if [ "$uninstall" = 1 ]; then printf '%-24s enlaces quitados (%s)\n' "$nombre" "$dest"
  else printf '%-24s %d skills enlazadas (%s)\n' "$nombre" "$n" "$dest"; fi
done
[ "$uninstall" = 0 ] && echo "blender-steroids instalado. Abre una sesión nueva en tu agente y pídele: «conecta con Blender»."
exit 0
