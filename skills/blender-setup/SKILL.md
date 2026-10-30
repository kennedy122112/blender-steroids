---
name: blender-setup
description: Primer arranque de blender-steroids. Comprueba que esta PC puede controlar Blender (instalado, versión, puente blender-cli), instala y activa el add-on puente, y deja Blender abierto y respondiendo. Úsala la primera vez, cuando el usuario diga "configura Blender", "prepara Blender", "set up Blender", "no conecta con Blender", o cuando blender-cli falle.
---

# Preparar Blender (blender-steroids)

blender-steroids controla **Blender** en local con su API de Python (`bpy`). No usa MCP, ni API key,
ni nube. Hay dos piezas:

- **blender-cli**, el puente que ejecutas tú. En el resto de las skills de Blender, **blender-cli** significa:
  - **Windows**: `"%USERPROFILE%\.blender-steroids\bin\blender-cli.cmd" <comando> ...`
    (desde PowerShell: `& "$env:USERPROFILE\.blender-steroids\bin\blender-cli.cmd" <comando> ...`;
    desde bash/Git Bash: `"$USERPROFILE/.blender-steroids/bin/blender-cli.cmd" <comando> ...`).
    El `.cmd` no pasa por PowerShell. Si solo puedes usar el `.ps1`, funciona igual, pero PowerShell
    puede imprimir antes avisos propios (p. ej. «InitializeDefaultDrives» por una unidad de red caída)
    que **no** son fallos del comando.
  - **macOS y Linux**: `bash ~/.blender-steroids/bin/blender-cli <comando> ...`

  Usa siempre la copia instalada en `~/.blender-steroids`, nunca una que descargues o clones tú: esa
  es la que coincide con estas skills y con el add-on de Blender. Usa el Python de la máquina o, si no
  hay, el que trae Blender. Las opciones valen en los dos estilos (`-Path x` o `--path x`).

  **Toda salida es JSON por stdout**, también los errores (`ok: false`, `error`, y casi siempre `hint`
  con qué hacer). Fíjate en `ok` y en `warnings`, no en lo que aparezca por stderr. Si una respuesta
  trae `warnings` (otra copia de blender-steroids, add-on desactualizado en el Blender abierto),
  cuéntaselo al usuario.
- **El add-on `blender_steroids`**, que corre dentro de Blender y abre el puerto local `127.0.0.1:9777`
  por el que blender-cli le habla. Tiene un panel en la Vista 3D → barra lateral (N) → «Steroids».

## 1. ¿Está instalado Blender?
`blender-cli status`:
- `blender: null` → no está instalado. Pídele al usuario que lo instale desde blender.org (gratis;
  probado con **Blender 5.2 LTS**, sirve desde 4.2) y espera. Si lo tiene en otra carpeta, define
  la variable `BLENDER_STEROIDS_BLENDER` con la ruta del ejecutable (`blender.exe` en Windows;
  `/Applications/Blender.app/Contents/MacOS/Blender` en macOS; `blender` en Linux).
- `addonInstalled: false` → paso 2.
- `bridge: true` → listo: Blender abierto y respondiendo; informa el archivo y qué hay en la escena.

## 2. Instalar el add-on
`blender-cli setup` enlaza el add-on en la carpeta de complementos del usuario de esa versión de
Blender y lo deja activado en sus preferencias (es un enlace: actualizar blender-steroids lo actualiza).
Si devuelve `note` (Blender ya estaba abierto), ese Blender no lo cargó todavía: dile al usuario que
lo cierre y lo abra de nuevo, o que lo active en *Edición > Preferencias > Complementos*
(en macOS: *Blender > Preferencias > Complementos*).

## 3. Abrir Blender listo para trabajar
- Si el usuario ya tiene Blender abierto con el add-on activo, `status` da `bridge: true` y no hay que hacer nada.
- Si no: `blender-cli launch [-File escena.blend]` abre Blender con el puente activo (aunque el
  add-on no esté instalado) y espera a que responda.
- **Sin interfaz**: todos los comandos aceptan `-File archivo.blend` y trabajan sobre ese archivo con
  Blender en segundo plano (si no existe, se crea). Sirve cuando el usuario no quiere ver Blender, en
  un servidor, o para lotes. Es más lento por pedido (Blender arranca cada vez, unos segundos).

## Cuando algo falla: `blender-cli doctor`
Revisa todo de una vez: versión y ubicación de blender-cli (avisa si es una copia distinta de la
instalada), Python, Blender y su versión, el add-on y a qué copia apunta, el puerto (libre, ocupado
por otro programa o bloqueado por un sandbox), si el Blender abierto tiene cargado un add-on de otra
versión, unidades de red caídas y la carpeta temporal. Cada revisión trae `ok`, `detail` y, si falla,
`fix`; `fixes` las junta. Ejecútalo antes de intentar otra vía y aplica o cuenta los `fix`.

## Problemas frecuentes
- **«Error al intentar realizar la operación InitializeDefaultDrives»**: lo imprime PowerShell, no
  blender-cli; hay una unidad de red que no responde. El comando funcionó si el JSON dice `ok: true`.
  Usa `blender-cli.cmd`. Para quitarlo, el usuario reconecta la red/VPN o borra la unidad.
- **Aviso de add-on de otra versión**: el Blender abierto cargó el add-on antes de actualizar
  blender-steroids. Pide al usuario que cierre y abra Blender.
- **`bridge: false` con Blender abierto**: ese Blender no tiene el add-on activo (se abrió antes del
  `setup`), o lo detuvo el usuario en el panel «Steroids». Que lo active ahí, o reabrirlo.
- **Dos Blender abiertos**: solo el primero que arrancó tiene el puerto; el otro avisa en su consola.
  `info` dice en qué archivo estás trabajando: confírmalo antes de escribir.
- **El puerto 9777 está ocupado por otro programa**: define `BLENDER_STEROIDS_PORT` (mismo valor
  para Blender y para blender-cli) y reabre Blender.
- **Blender no responde**: puede estar renderizando o con un diálogo abierto; espera o pídele que lo cierre.
- **Sandbox del agente** (Codex por defecto): el puerto local o lanzar Blender pueden estar bloqueados.
  Vuelve a ejecutar pidiendo acceso completo en vez de buscar otra vía.

No le muestres comandos al usuario. Ejecútalos tú y cuéntale el resultado en lenguaje sencillo.
