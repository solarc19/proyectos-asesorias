# proyectos-asesorias

Enfoque **pragmático y simple** para saber quién no te sigue de vuelta en Instagram, evitando depender siempre de requests que Instagram bloquea (`401`, `Please wait a few minutes`).

## TL;DR (recomendado)

Usá modo **offline** con export oficial de Instagram (sin scraping live, sin rate limit):

```bash
python main.py offline \
  --followers-file /ruta/followers_1.json \
  --following-file /ruta/following.json \
  --target tu_usuario
```

## Modos disponibles

### 1) `offline` (recomendado)

- Lee JSON exportados por Instagram.
- No hace consultas GraphQL en vivo.
- Cero dependencia de bloqueos temporales por rate limit.

### 2) `api` (opcional)

- Usa `instaloader` con sesión local.
- Tiene backoff + fallback a snapshot local.
- Puede volver a fallar si Instagram insiste con bloqueos.

```bash
python main.py api --username TU_USUARIO --target TU_USUARIO
```

## Cómo obtener los JSON para `offline`

1. Instagram → **Configuración** → **Tu información y permisos** (o Centro de cuentas) → **Descargar tu información**.
2. Pedí formato **JSON**.
3. Cuando te llegue el ZIP, buscá archivos tipo:
   - `followers_1.json`
   - `following.json`
4. Ejecutá el comando `offline` con esas rutas.

## Nota sobre "F11/F12"

Si antes usabas una web/app donde tenías que tocar teclas del navegador en Instagram, eso suele ser un workaround frágil. Este repo ahora prioriza el flujo estable: **export JSON + análisis local**.

## Salida

El script imprime:
- cantidad de followers,
- cantidad de followees,
- lista de cuentas que no te siguen de vuelta,
- y guarda snapshot en `data/`.
