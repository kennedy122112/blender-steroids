---
name: blender-model
description: Crea y modifica escenas 3D reales y editables en Blender a partir de lenguaje natural - objetos, muebles, productos, maquetas, escenarios, texto 3D, materiales, luces, cámara y animación simple - y las revisa renderizando. Úsala cuando el usuario diga "modela en Blender", "crea una escena / un objeto / un producto en 3D", "arma una maqueta", "pon luces y cámara", "cambia el material", "anima esto", "hazme un logo 3D", "build X in Blender".
---

# Modelar en Blender

Requiere conexión (`blender-connect`): en vivo o con `-File`. **blender-cli** está definido en `blender-setup`.

## Flujo
1. Entiende qué se pide y descomponlo en piezas simples con **medidas reales en metros** (una mesa
   mide ~0.75 m de alto, una taza ~0.1 m, una persona ~1.75 m, una puerta 0.9 × 2.1 m). Pregunta
   solo lo que cambie el resultado (estilo, colores de marca); lo demás, decídelo tú y dilo.
2. Lee la escena (`blender-cli scene`) para reutilizar materiales y objetos existentes.
3. Escribe un **spec JSON** (UTF-8) y ejecuta `blender-cli build -Spec escena.json` (en vivo) o
   `... -File escena.blend` (sin interfaz; guarda solo si el archivo era nuevo, si no, añade
   `-Save escena.blend`). Guarda el spec junto al `.blend` (`specs/NN-nombre.json`), nunca solo en una
   carpeta temporal: rehacer la escena es volver a correr `build`.
4. **Mira el resultado** antes de darlo por bueno: `blender-cli render -Path vista.png -Preview`
   (rápido, Workbench) y léelo. Para revisar formas, añade vistas `-View front|right|top` y
   `-Objects a,b` para acercarte a una pieza. Corrige piezas flotando, atravesadas o fuera de escala.
5. Cuéntale al usuario qué creó (por colección) y, si trabajaste sin interfaz, dónde quedó el `.blend`.

## Spec JSON
```json
{
  "removeDefaults": true,
  "scene": { "engine": "eevee", "resolution": [1920, 1080], "fps": 24, "frames": [1, 120],
             "samples": 64, "transparent": false, "viewTransform": "AgX",
             "world": { "color": "#20242c", "strength": 0.6, "hdri": "C:/hdri/estudio.exr" } },
  "materials": [
    { "name": "Madera", "color": "#8a5a32", "roughness": 0.55 },
    { "name": "Metal", "color": "#c9ccd1", "metallic": 1, "roughness": 0.3 },
    { "name": "Vidrio", "color": "#ffffff", "transmission": 1, "roughness": 0.05, "ior": 1.45 },
    { "name": "Neon", "color": "#000000", "emission": "#36c5ff", "emissionStrength": 8 },
    { "name": "Logo", "texture": "logo.png" }
  ],
  "collections": ["Mesa", { "name": "Luces", "parent": null }],
  "objects": [
    { "name": "Tablero", "type": "cube", "size": [1.6, 0.9, 0.05], "location": [0, 0, 0.75],
      "material": "Madera", "collection": "Mesa",
      "modifiers": [{ "type": "bevel", "width": 0.01, "segments": 3 }] },
    { "name": "Pata", "type": "cylinder", "radius": 0.03, "depth": 0.73, "origin": "bottom",
      "location": [-0.72, -0.37, 0], "material": "Metal", "smooth": true,
      "modifiers": [{ "type": "mirror", "axis": "XY", "mirrorObject": "Tablero" }] },
    { "name": "Key", "type": "light", "light": "area", "energy": 400, "size": 2,
      "location": [2.5, -2.5, 3.5], "lookAt": "Tablero" },
    { "name": "Camara", "type": "camera", "lens": 50, "frame": ["Tablero", "Pata"], "view": "iso" }
  ],
  "animation": [
    { "object": "Tablero", "property": "rotation", "interpolation": "linear",
      "keys": [{ "frame": 1, "value": [0, 0, 0] }, { "frame": 120, "value": [0, 0, 360] }] }
  ],
  "delete": []
}
```
Todo es opcional salvo `name` en cada objeto. Ejemplo completo: `examples/mesa-con-taza.json`.

### Objetos (`type`)
| type | Parámetros de forma |
|---|---|
| `cube` | `size`: número o `[x, y, z]` en metros (tamaño real, la escala queda en 1) |
| `plane`, `grid` | `size`: número o `[x, y]`; `xSegments`, `ySegments` |
| `uv_sphere` (`sphere`), `ico_sphere` | `radius`; `segments`, `rings` / `subdivisions` |
| `cylinder`, `cone` | `radius`, `radius2` (cono: radio de arriba, 0 = punta), `depth`, `segments` |
| `torus` | `majorRadius`, `minorRadius`, `segments`, `minorSegments` |
| `circle` | `radius`, `segments`, `fill` |
| `monkey` | — |
| `mesh` | `vertices: [[x,y,z]…]`, `faces: [[i,j,k,…]…]`, `edges` (formas a medida: perfiles, rampas, techos) |
| `text` | `text`, `size`, `extrude`, `bevelDepth`, `align` (left/center/right), `alignY` |
| `light` | `light`: point/sun/spot/area, `energy` (W; sol: intensidad ~3-5), `color`, `size`, `spotSize`° , `spotBlend` |
| `camera` | `lens` (mm), `ortho` + `orthoScale`, `focus` (objeto o distancia) + `fstop`, `active` (por defecto sí) |
| `empty` | `display` (plain_axes, arrows, cube…), `size` |

Comunes a todos: `location` [m], `rotation` [grados XYZ], `scale`, `dimensions` (fuerza el tamaño final),
`origin: "bottom"` (el origen en la base: así `location` z=0 lo apoya en el piso), `material` o
`materials` + `faceMaterials` (índice por cara), `collection`, `parent` (la `location` que das es la del
mundo), `smooth`, `hidden`, `hideRender`, `display` (wire, solid…), `lookAt` (objeto o `[x,y,z]`;
con `track: true` lo sigue siempre), `cutter: true` (pieza para restar: alámbrica y fuera del render).

**Cámara automática**: `"frame": ["A", "B"]` (o `"all"`) la coloca para que esos objetos entren
enteros, desde `"view"`: `iso`, `front`, `back`, `right`, `left`, `top` o un vector `[x, y, z]`;
`margin` (1.1) deja aire alrededor. Úsala en vez de calcular posiciones de cámara a mano.

### Modificadores
`modifiers: [{ "type": ..., ...propiedades }]`, en orden. Las propiedades usan el nombre de Blender
en camelCase (`segments`, `width`, `levels`, `renderLevels`, `thickness`, `count`, `angleLimit`°...).
Atajos: `bevel` (`width`, `segments`), `subsurf`/`subdivision` (`levels`), `solidify` (`thickness`),
`array` (`count`, `offset` relativo `[x,y,z]` o `constantOffset` en metros), `mirror` (`axis`: "X", "XY"…,
`mirrorObject`), `boolean` (`object`, `operation`: difference/union/intersect), `weld`, `triangulate`,
`displace`, `wireframe`, `screw`, `simple_deform`. Si una propiedad no existe, sale en `warnings`.
Al repetir `build`, los modificadores que ya no estén en el spec se quitan (solo los que puso `build`).

### Materiales
Principled BSDF: `color`, `metallic`, `roughness`, `ior`, `alpha`, `transmission`, `emission` +
`emissionStrength`, `coat`, `sheen`, `subsurface`, `specular`, `texture` (imagen como color base; ruta
absoluta o relativa al spec). Colores en hex como en cualquier selector (`#rrggbb`); blender-cli los
convierte al espacio lineal de Blender.

### Animación
`animation: [{ object, property, keys: [{frame, value}], interpolation }]`. `property`: `location`,
`rotation` (grados), `scale`, o un dato del objeto con `data.` (`data.energy` de una luz, `data.lens` de
una cámara). Al repetir `build` las claves de esa propiedad se reemplazan. Fija `scene.frames`.

### Actualizar lo que existe
Un objeto que ya existe se busca por `name` y solo cambia lo que pongas: `{ "name": "Tablero", "material": "Rojo" }`
le cambia el material sin tocar su forma. La malla se rehace solo si das parámetros de forma
distintos (`size`, `radius`...): **eso descarta las ediciones a mano** que el usuario hizo en esa malla;
avísale antes.

## Cómo modelar bien con primitivas
- Piensa en piezas: cada parte reconocible (tablero, pata, asa) es un objeto con nombre en el idioma
  del usuario, agrupado en una colección por conjunto.
- Apoya las cosas: con `origin: "bottom"` la z de `location` es la altura del suelo o de la superficie.
  Calcula las alturas sumando (tablero en 0.75 → taza en 0.775).
- `bevel` pequeño (1-2 % del tamaño) en casi todo lo rígido: los bordes perfectos se ven falsos.
- Repetición → `array` o `mirror` en vez de copiar objetos. Huecos → `boolean` con un `cutter`.
- Formas orgánicas → `subsurf` sobre una malla simple; perfiles → `mesh` con vértices y caras.
- Luz de estudio: una `area` principal a 45°, una de relleno más débil al otro lado y el mundo oscuro;
  exteriores: `sun` + mundo azul claro o un HDRI.
- Escenas de más de ~40 objetos: varios `build` por colección.

## Lo que `build` no cubre
Para edición de malla avanzada, nodos de geometría, partículas, rigs, físicas o cualquier otra cosa
de `bpy`, escribe un script y ejecútalo con `blender-cli exec -Script script.py` (en vivo, o con
`-File` y `-Save`). El script tiene `bpy`, `bmesh`, `math`, `Vector` y `ops` (funciones de
blender-steroids, p. ej. `ops.frame_camera(cam, ["A"], "front")`); lo que dejes en la variable
`result` vuelve como JSON y lo que imprimas, en `stdout`. Usa `bpy.data` y `bmesh` en vez de
`bpy.ops` siempre que puedas: los operadores dependen del contexto de la ventana.

No le muestres comandos ni JSON al usuario salvo que lo pida.
