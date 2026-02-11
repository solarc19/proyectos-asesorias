# proyectos-asesorias

Visión simple y pragmática: **revisar desde la web de Instagram**, pero calcular resultados en una mini herramienta local.

## Uso recomendado (sin pelear con rate limit)

```bash
python main.py
```

Eso levanta una mini web local en `http://127.0.0.1:8765` donde pegás:
- lista de followers,
- lista de following,
y te devuelve quién no te sigue de vuelta.

## ¿Por qué este enfoque?

Instagram bloquea seguido consultas automáticas (`401`, `Please wait a few minutes`).
En vez de depender de scraping en vivo, este flujo es estable:
- vos abrís Instagram web,
- copiás usuarios,
- pegás en la web local,
- listo.

## Otros modos (opcionales)

### Offline por export JSON

```bash
python main.py offline \
  --followers-file /ruta/followers_1.json \
  --following-file /ruta/following.json \
  --target tu_usuario
```

### API con Instaloader (puede fallar por rate limit)

```bash
python main.py api --username TU_USUARIO --target TU_USUARIO
```

## Tip práctico para copiar desde Instagram web

- Abrí tu lista de seguidores/seguidos.
- Hacé scroll para cargar más elementos.
- Copiá usernames (línea por línea, con `@`, CSV o URLs; la mini web normaliza todo).

## Salida

Se muestra:
- cantidad de followers,
- cantidad de following,
- quién no te sigue de vuelta,
- y quién te sigue pero vos no seguís.
