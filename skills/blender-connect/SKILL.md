---
name: blender-connect
description: Conecta el agente con Blender abierto en esta PC (add-on puente local, sin MCP) o con un archivo .blend sin interfaz, y lee qué hay en la escena. Úsala cuando el usuario diga "conecta con Blender", "trabaja en mi Blender", "abre este .blend", "qué hay en mi escena", "revisa este archivo de Blender", cuando un comando blender-cli falle por conexión, o antes de cualquier tarea de modelado en Blender.
---

# Conectar con Blender

Si es la primera vez o blender-cli no existe, sigue antes `blender-setup` (allí se define **blender-cli**).

## 1. Elegir el modo
`blender-cli status`:
- `bridge: true` → **en vivo**: trabajas sobre lo que el usuario tiene abierto y ve los cambios al momento.
  `scene.file` dice qué archivo es (`null` = sin guardar).
- `bridge: false` → si el usuario quiere verlo, `blender-cli launch [-File x.blend]`; si nombró un
  archivo y no necesita verlo, trabaja **sin interfaz** con `-File x.blend` en cada comando.

Dile al usuario en qué archivo vas a trabajar antes de cambiar nada.

## 2. Leer la escena
- `blender-cli info` → archivo, motor, resolución, fotogramas, cámara activa y conteos.
- `blender-cli scene` → colecciones, cada objeto (tipo, posición, rotación en grados, escala,
  **dimensiones reales en metros**, colección, padre, materiales, modificadores, luz/cámara), los
  materiales con su color en hex y el mundo.
- `blender-cli scene -Object <nombre>` → un objeto a fondo: propiedades de cada modificador,
  restricciones y propiedades personalizadas.

Para **explicar o auditar** un archivo, resume desde `scene`: qué hay por colección, objetos sin
material, materiales sin uso (`users: 0`), escala no aplicada (`scale` ≠ 1 en objetos que se van a
exportar), objetos ocultos, cámaras y luces. Para verlo, pide una vista con `blender-render`.

## 3. Reglas de trabajo
- **Antes de modificar**, lee la escena para reutilizar objetos y materiales existentes por su nombre.
- `build` es idempotente por nombre: repetirlo actualiza, no duplica.
- No borres objetos sin confirmación explícita del usuario. `build` solo borra lo que pongas en
  `delete` o, con `removeDefaults`, el cubo, la luz y la cámara de la escena por defecto.
- En vivo cada `build` deja un paso de deshacer (Ctrl+Z en Blender). Sin interfaz no hay deshacer:
  si el `.blend` es valioso, trabaja sobre una copia o guarda con otro nombre (`-Save`).
- Si el usuario tiene cambios sin guardar (`unsaved: true`), no abras otro archivo con `open`
  sin preguntarle: se perderían.

No le muestres comandos ni JSON al usuario. Ejecútalos tú e informa en lenguaje sencillo.
