<!-- Parte de la skill blender-model: léela cuando SKILL.md te mande aquí. -->

# Movimiento con ecuaciones (`motion`)
Para todo lo que oscila, rebota, cuelga o se bambolea, **no inventes claves**: en una entrada de
`animation` pon `motion` en vez de `keys`, con `property` (`location`, `rotation` en grados, `scale` o
`data.x`), `axis` (x/y/z) y `frames` (por defecto los de la escena). Se calcula un valor por fotograma y
se hornea como claves lineales en ese único canal, **sumado a su valor de reposo** (el que tenía la
primera vez; repetir `build` no lo corre ni duplica claves). Los otros ejes y animaciones no se tocan.

| kind | Para qué | Parámetros |
|---|---|---|
| `oscillate` | Cinemático: alas, ventiladores, respirar, flotar, una señal que parpadea | `frequency` (Hz), `amplitude`, `phase` (grados), `offset` |
| `noise` | Cinemático: variación suave y sin patrón (una llama, un motor, viento, un temblor) | `frequency` (Hz, sus componentes van de f/2 a 2f), `amplitude` (el máximo exacto), `seed` (otra semilla, otro ruido; la misma, el mismo), `offset` |
| `spring` | Simulado: rebota y se asienta (un golpe, una caída, un *squash*) | `frequency` + `dampingRatio` (0 sin pérdida, 1 crítico), o `mass` + `stiffness` + `damping`; `initial`, `velocity`, `force` |
| `pendulum` | Simulado: péndulo real, también con ángulos grandes | `length` (m), `initial` (grados), `velocity`, `damping`, `gravity` (9.81) |
| `follow` | Simulado: movimiento secundario (antenas, orejas, colas, cables) que sigue a otro objeto con retraso y rebote | `leader` (objeto), `leaderAxis` (eje de su aceleración en el mundo), `frequency`, `dampingRatio` (0.3), `gain` (grados o m que se inclina por cada m/s² del guía) |

- **Varios movimientos en un canal**: `motion` también acepta una lista y los suma (una llama:
  dos `noise` de frecuencias distintas; un balanceo con temblor: `pendulum` + `noise`).
- **Pivote**: la rotación es alrededor del origen del objeto. Para un ala, una antena o un péndulo crea
  un `empty` en la bisagra, emparenta la pieza (`parent`) y anima el empty (así lo hace
  `examples/libelula.json`).
- **Aliasing**: los fps tienen que alcanzar para la frecuencia. Con 2 fotogramas o menos por ciclo,
  build da error (se vería quieto o al revés); con menos de 8, aviso de que se verá entrecortado. Un
  aleteo real de 30 Hz no se puede mostrar a 24 fps: baja la frecuencia o sube `scene.fps`.
- El resultado de build trae `motions` (canal, `mode` kinematic u ode_simulated, fotogramas, máximo) y
  cada objeto guarda en `bs_motion` el modelo y sus parámetros. Dile al usuario si es cinemático
  (una fórmula) o simulado (una ecuación integrada): **no es física de choques ni de aerodinámica**.
- `follow` con `walk`: después de `walk`, crea la bisagra de la antena con `parent: "bs_walk_cabeza"`,
  cuelga la antena de ella y usa `leader: "bs_walk_cabeza"`, `leaderAxis: "z"` (el rebote del paso).
- Se exporta: el GLB lleva un canal de animación por cada motion (verificado).
- El paso de integración se achica solo si el sistema oscila rápido (estable aunque sea muy rígido) y
  hay un tope de cálculo: si una simulación lo pasa, build lo dice en vez de quedarse colgado.
  `motions` trae `elapsedMs`, `step` y `substeps`.

# Caminar (personajes de piezas, sin huesos)
`blender-cli walk -Spec caminata.json [-Save x.blend]` arma un ciclo de caminata para un personaje hecho
de piezas: pivotes en las caderas que balancean cada pierna, el pie que avanza se levanta, el cuerpo
sube, baja y se mece, la cabeza asiente y, si se piden, los brazos se balancean al revés que las piernas.
```json
{ "cycle": 24, "cycles": 2, "angle": 22, "lift": 0.035, "follow": "Camara",
  "legs": [ { "pivot": [-0.1, 0, 0.31], "parts": ["PieI", "PiernaI"], "foot": "PieI" },
            { "pivot": [ 0.1, 0, 0.31], "parts": ["PieD", "PiernaD"], "foot": "PieD" } ],
  "body": { "pivot": [0, 0, 0.33], "parts": ["Torso", "BrazoI", "BrazoD"] },
  "head": { "pivot": [0, 0, 0.79], "parts": ["Cabeza", "Cara"] },
  "arms": [ { "pivot": [-0.25, 0, 0.68], "parts": ["BrazoI"] } ] }
```
- El personaje debe mirar a **-Y** en reposo; `direction` [x, y] cambia hacia dónde camina.
- `pivot` de cada pierna = la cadera (donde gira); `foot` = la pieza que apoya: se mantiene plana.
- El rebote del cuerpo se **mide** en cada fotograma para que el pie de apoyo toque el piso: la
  respuesta trae `footMinZ`, que debe ser 0. Si el personaje sostiene algo con las manos, no pongas
  `arms`: los brazos van en `body`.
- `follow` hace que la cámara lo acompañe (el piso se desliza debajo): pon un piso con textura para que
  se note el avance. El ciclo se repite sin cortes; para un video, `render -Animation` (con `-Retro` si
  es estilo 32 bits) y une los fotogramas con ffmpeg.
