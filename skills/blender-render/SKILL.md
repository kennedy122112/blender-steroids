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

**Look retro de 32 bits**: `-Retro [-RetroWidth 320] [-RetroScale 4]` renderiza chico (320 de ancho,
con el formato de la escena), pasa el color a 15 bits (5 por canal) con tramado ordenado y amplía x4
con píxeles duros. Vale también con `-Animation` (procesa cada fotograma). Combínalo con texturas
`pixels` y sombreado plano (ver `blender-model`).

Sin cámara en la escena, se crea una temporal en vista `iso`. Siempre **lee la imagen** antes de
enseñarla: si algo se ve mal, corrígelo con `blender-model` y vuelve a renderizar.
Avisa el tiempo antes de un render largo (Cycles a 1080p con 256 muestras puede tardar minutos).

## Comparar con una referencia
`blender-cli compare -Reference ref.png -Path comparar.png [-View front|...] [-Objects a,b] [-Camera n] [-Preview]`
renderiza con fondo transparente y el formato de la referencia, detecta la figura en las dos imágenes
(en la referencia la separa del fondo, también de un visor con degradado y cuadrícula) y **alinea** el
render: misma altura de figura, centrado y apoyado en la misma base. Entrega una imagen con tres
paneles: referencia | render alineado | siluetas superpuestas (cian = referencia, magenta = render),
con guías cada 10 % del alto de la figura. Y medidas en `alignment`:
- `silhouetteIoU` (0-1): cuánto coinciden las siluetas; sirve para ver si una vuelta mejoró.
- `aspectReference` / `aspectRender`: ancho/alto de la figura.
- `widthByGuideReference` / `widthByGuideRender`: ancho de la figura en cada décimo de su alto, de
  abajo arriba, en fracción del alto. Compáralos guía a guía: «en la 7 la referencia mide 0.61 y el render 0.54».
- `zByGuide`: la altura del mundo (m) de lo que se ve en cada décimo de la figura (10 valores, de abajo
  arriba), calculada con los vértices reales proyectados por la cámara, así que vale en perspectiva.
- `edgesByGuide`: en cada décimo, qué pieza forma el borde izquierdo y cuál el derecho. Es la respuesta
  directa a «¿qué hace ancha esta guía?».

**Ángulo de cámara**: usa `-View` con el lado de la referencia si lo sabes (`front`, `iso`, `"0.5,-1,0.2"`).
Si no, `-FitView` prueba 33 ángulos (azimut -75° a 75°, elevación 0-30°) con renders rápidos de silueta y
usa el que más se parece; `fitView` en la respuesta dice cuál y los tres mejores. Tarda ~35 s. Funciona
bien con figuras asimétricas (una cola o un arma de un lado). En figuras casi simétricas la silueta
distingue poco el ángulo (los mejores difieren en centésimas): entonces elige tú el lado mirando la
imagen (hacia dónde apunta el hocico, qué brazo se ve más).

**Varias vistas**: repite `-Reference` y `-View` en orden (`-Reference a.png -Reference perfil.png -View
"0.4,-1,0.2" -View right`). Hace una comparación por vista (`comparar_1.png`, `comparar_2.png`) y
devuelve `views` con el IoU de cada una y `meanIoU`.

`-NoAlign` (sin alinear), `-NoOverlay` (sin panel de siluetas), `-NoGuides`. Úsalo en cada vuelta de un
trabajo con referencia (ver `blender-model`) y describe las diferencias con estas medidas, no de memoria.

**Cómo separa la figura**: se queda con la región más grande y con las partes sueltas que midan al
menos el 10 % de ella, conserva las partes finas y las que quedan separadas en una misma fila (dientes,
cuernos, dedos, un brazo despegado del torso) y borra líneas de hasta 2 px (cuadrícula del visor).
**Huecos** (`-Holes`): con `fill` (por defecto) tapa los huecos cerrados y las zonas interiores que
solo se abren al fondo por una rendija de ~6 px, en la referencia y en el render por igual: así una
zona del mismo color que el fondo (una barriga blanca sobre fondo blanco) no cuenta como agujero.
Con `keep` los conserva: úsalo para piezas con agujeros reales (engranajes, logos, una dona). `fit`
acepta el mismo `-Holes`.

Si la referencia tiene varias vistas o barras del programa, recórtala antes a una sola vista: una
segunda figura o un panel grande en la imagen entran en la silueta. Desde 1.11 la silueta es más fiel
y el IoU suele salir unas centésimas más alto que con versiones anteriores para el mismo modelo
(no compares números entre versiones).

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
