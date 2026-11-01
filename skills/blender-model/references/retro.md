<!-- Parte de la skill blender-model: léela cuando SKILL.md te mande aquí. -->

# Estilo retro de 32 bits (low-poly y pixel art)
Para el look de los juegos 3D de consolas de 32 bits:
- **Geometría**: pocas caras y sombreado plano: `"smooth": false`, `segments` 4-8 en cilindros y tubos,
  `ico_sphere` con `subdivisions: 1`, sin `subsurf` ni biseles redondeados.
- **Texturas pixeladas en el spec**: un material con `pixels` dibuja la imagen carácter a carácter y la
  muestra sin suavizar:
  `{"name": "Cara", "emissionStrength": 1.5, "pixels": {"rows": ["........", ".GG..GG.", "..GGGG.."],
  "palette": {".": "#08110b", "G": "#5dff7a"}, "plane": [0.3, 0.19], "axes": "XZ"}}`.
  `plane` es el tamaño (m) del área que cubre la imagen sobre la pieza (centrada en su origen), `axes`
  "XZ" para un frente y "XY" para un piso; `"repeat": true` repite (baldosas). Imágenes chicas (8-32
  píxeles de lado) y paletas cortas. Pon la textura en una pieza fina pegada a la cara (pantalla, panel).
- **Render**: `blender-cli render -Path x.png -Retro` (ver `blender-render`) y `viewTransform: "Standard"`
  para que los colores de la paleta salgan tal cual.
