# proyectos-asesorias

Solución pragmática para consultar seguidores/seguidos de Instagram con `instaloader` sin romperte por rate limit en cada ejecución.

## Idea simple (estilo Linux dev)

- Reusar sesión local siempre que se pueda.
- Hacer pocos reintentos con espera incremental cuando aparezca `Please wait a few minutes`.
- Guardar un snapshot local (`JSON`) para fallback cuando Instagram limita temporalmente.

## Requisitos

```bash
python -m pip install instaloader
```

## Uso

```bash
python main.py --username TU_USUARIO --target CUENTA_OBJETIVO
```

Opciones útiles:

- `--retries 3`: reintentos ante rate limit.
- `--base-wait 45`: espera base en segundos (se multiplica por intento).
- `--snapshot-dir data`: carpeta de snapshot local.

## Qué resuelve de tu error 401

Cuando Instagram responde:

- `401 Unauthorized`
- `Please wait a few minutes before you try again`

el script:
1. espera y reintenta,
2. y si no alcanza, usa el último snapshot local (si existe),
3. para que puedas seguir trabajando sin cortar el flujo.
