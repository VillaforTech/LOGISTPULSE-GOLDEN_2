# Decisiones de arquitectura

La herramienta está instalada dentro del repositorio: [ADR-Tools 3.0.0](../../tools/adr-tools/UPSTREAM.md).
Se necesitan Bash, utilidades Unix y Python 3.9 o superior para el validador.
No hay que ejecutar Homebrew, pip ni modificar el PATH global.

Desde la raíz del clon:

```bash
./scripts/adr --version
./scripts/adr list
./scripts/adr new "Describe the architectural decision"
python3 scripts/check_adrs.py
python3 -m unittest discover -s tests/adr -v
```

`new` crea el siguiente archivo y abre el editor indicado por `VISUAL` o `EDITOR`.
Para crear sin abrir editor: `VISUAL=true ./scripts/adr new "Decision title"`.
Completar los campos `PENDIENTE:` antes de enviar el PR. Se usan títulos cortos
sin tildes para generar nombres portables; el cuerpo puede escribirse en español.
Ejecutar en una ruta sin espacios por las limitaciones de los scripts upstream.

`.adr-dir` apunta a `docs/adr`; ya fue creado con `./scripts/adr init docs/adr`.
No repetir `init` en este repositorio porque crearía otro registro de adopción.
El template local inicia decisiones como `Proposed`. Los encabezados y estados
se conservan en inglés para que ADR-Tools pueda enlazar y reemplazar registros.
`Accepted` se usa para decisiones ya adoptadas; una propuesta necesita revisión.

Para reemplazar una decisión aceptada:

```bash
./scripts/adr new -s 2 "Describe the replacement"
```

ADR-Tools enlaza ambos registros y marca el anterior como `Superceded by`
(ortografía de la versión oficial). Revisar el cambio completo en el PR.

## Qué bloquea CI

El job existente `architecture-contract` ejecuta el CLI, el validador y siete
pruebas. Un ADR sin decisión, fecha válida, estado admitido, número único,
secciones completas o enlaces locales válidos hace fallar el job. También se
rechaza el texto pendiente de las plantillas. Los ejemplos heredados
`ADR-TEMPLATE*.md`, esta guía y `templates/` no son registros numerados.

Las pruebas crean un directorio temporal: ejecutan `init`, `new` y `list`, y
comprueban que entradas inválidas fallan. No crean registros de prueba en el
repositorio. Los checks de Compose, integración y Release gate siguen activos.
Este control documental no prueba las reglas de negocio de El Falso Verde.

## Referencias

- [Manual oficial de ADR-Tools](https://github.com/npryce/adr-tools/tree/3.0.0).
- [Instalación oficial desde una distribución](https://github.com/npryce/adr-tools/blob/3.0.0/INSTALL.md).
- [Origen del formato, Michael Nygard](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).
- [Ownership del proyecto](../architecture/DATA-OWNERSHIP.md).
