---
name: blender-render
description: Renderiza y exporta desde Blender - imágenes finales o vistas rápidas de revisión, secuencias de animación, y modelos en GLB/glTF, FBX, OBJ, STL (impresión 3D), PLY o USD. Úsala cuando el usuario diga "renderiza", "saca una imagen", "muéstrame cómo quedó", "haz un render en Cycles", "exporta a glb / fbx / stl", "pásalo a Unity / Unreal / la web", "para imprimir en 3D", "renderiza la animación".
---

# Renderizar y exportar desde Blender

Requiere conexión (`blender-connect`): en vivo o con `-File`. **blender-cli** está definido en `blender-setup`.

En vivo, `render` y `export` guardan una copia del archivo abierto y trabajan sobre ella con Blender
en segundo plano: **el Blender del usuario no se congela** y su archivo no cambia.

## Imágenes
`blender-cli render -Path salida.png [opciones]` (`.jpg` también):

| Opción | Para qué |
|---|---|
| `-Preview` | Vista de revisión rápida: Workbench, 50 %, con sombras. Úsala para comprobar tu trabajo |
| `-View iso\|front\|back\|right\|left\|top` | Cámara temporal que encuadra la escena desde ese lado (no queda en el archivo). También una dirección propia: `-View "0.9,0.5,0.25"` (de dónde mira, p. ej. tres cuartos por detrás) |
| `-Objects a,b` | Con `-View` o sin cámara: encuadra solo esos objetos |
| `-Engine eevee\|cycles\|workbench` | EEVEE es rápido y bonito; Cycles, fotorrealista y lento |
| `-Samples N` | Calidad: EEVEE 32-64 bastan; Cycles 128-512 (más = menos ruido, más tiempo) |
| `-Resolution 1920x1080`, `-Percentage 50` | Tamaño de la imagen |
| `-Camera nombre`, `-Frame N`, `-Transparent` | Otra cámara, otro fotograma, fondo transparente (PNG) |

Sin cámara en la escena, se crea una temporal en vista `iso`. Siempre **lee la imagen** antes de
enseñarla: si algo se ve mal, corrígelo con `blender-model` y vuelve a renderizar.
Avisa el tiempo antes de un render largo (Cycles a 1080p con 256 muestras puede tardar minutos).

## Animación
`blender-cli render -Path carpeta/toma.png -Animation [-Frames 1-120]` deja `toma_0001.png`,
`toma_0002.png`... (`pattern` en la respuesta). Para un video, únelos con ffmpeg si está instalado
(`ffmpeg -framerate 24 -i toma_%04d.png -pix_fmt yuv420p toma.mp4`) o pásalos a HyperFrames.
Antes de una animación larga, renderiza 2-3 fotogramas sueltos (`-Frame`) para revisar.

## Exportar modelos
`blender-cli export -Path modelo.<ext> [-Objects a,b]` (sin `-Objects`, toda la escena; los
modificadores se aplican en el archivo exportado, no en el `.blend`):

| Extensión | Para |
|---|---|
| `.glb` / `.gltf` | Web (three.js, model-viewer), AR, Godot. Lleva materiales PBR |
| `.fbx` | Unity, Unreal |
| `.obj` | Intercambio general |
| `.stl` | Impresión 3D. Revisa antes que la pieza sea cerrada y esté en milímetros correctos (1 m de Blender = 1000 mm) |
| `.ply`, `.usd/.usdc/.usdz` | Escaneo y nubes de puntos; USD para pipelines y AR de Apple |

Cuéntale al usuario dónde quedó cada archivo y su tamaño.

No le muestres comandos al usuario salvo que lo pida.
