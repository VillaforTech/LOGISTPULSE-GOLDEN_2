# ADR-Tools incluido en el proyecto

Fuente: [npryce/adr-tools, versión 3.0.0](https://github.com/npryce/adr-tools/tree/3.0.0).
Commit: `b47d3837d452ca6d2509d2524c7a08c701e84367`.

Se copiaron `src/`, `LICENSE.txt` y `GPL.txt` sin modificaciones. `scripts/adr`
ejecuta esa copia local; `--version` lo proporciona nuestro wrapper. No hay
instalación global, actualización automática ni descarga durante CI.

Para reproducir la copia, descargar el archivo de GitHub del commit indicado,
extraerlo y copiar esos tres elementos. La descarga usada el 2026-09-13 desde
`https://api.github.com/repos/npryce/adr-tools/tarball/b47d3837d452ca6d2509d2524c7a08c701e84367`
tuvo SHA-256 `a5d448a33a683fdc5543106c2c1e901c16a0bc20d5874a3e55ff788afc7b712d`.
La identidad estable es el commit; GitHub puede regenerar el archivo comprimido.

La herramienta conserva su licencia GPL-3.0-or-later. Su aviso indica que el
contenido generado usa CC BY 4.0. Ver los avisos originales incluidos.
