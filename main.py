#!/usr/bin/env python3
"""Checker de no-followback para Instagram, pragmático y simple.

Modos:
1) web (recomendado para revisión manual desde instagram.com):
   levanta una mini web local para pegar listas de usuarios.
2) offline: usa archivos JSON exportados por Instagram.
3) api (opcional): usa instaloader con sesión local + backoff.
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Set

RATE_LIMIT_HINTS = (
    "Please wait a few minutes",
    "401 Unauthorized",
    "feedback_required",
    "rate limit",
)


WEB_HTML = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Instagram checker local</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 24px; max-width: 1100px; }
    h1 { margin: 0 0 12px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    textarea { width: 100%; min-height: 220px; font-family: ui-monospace, monospace; }
    button { padding: 10px 14px; margin-top: 8px; }
    .card { border: 1px solid #ddd; border-radius: 10px; padding: 12px; }
    code { background: #f6f6f6; padding: 2px 4px; border-radius: 4px; }
    ul { max-height: 320px; overflow: auto; }
  </style>
</head>
<body>
  <h1>Instagram no-followback checker (local)</h1>
  <p>Pegá listas desde la web de Instagram (followers/following). Acepta texto por línea, @usuario, CSV o URLs.</p>

  <div class="grid">
    <div class="card">
      <h3>Followers (te siguen)</h3>
      <textarea id="followers" placeholder="alice\nbob\n..."></textarea>
    </div>
    <div class="card">
      <h3>Following (vos seguís)</h3>
      <textarea id="following" placeholder="alice\ncarol\n..."></textarea>
    </div>
  </div>

  <button id="run">Calcular</button>

  <div id="summary" class="card" style="margin-top:16px;"></div>

<script>
function parseUsers(text) {
  const tokens = text
    .split(/[\n,;\t ]+/)
    .map(t => t.trim())
    .filter(Boolean)
    .map(t => t.replace(/^@+/, '').replace(/\/$/, ''))
    .map(t => {
      const m = t.match(/instagram\.com\/([A-Za-z0-9._]+)/i);
      if (m) return m[1];
      return t;
    })
    .map(t => t.toLowerCase())
    .filter(t => /^[a-z0-9._]+$/.test(t));
  return Array.from(new Set(tokens));
}

document.getElementById('run').onclick = () => {
  const followers = parseUsers(document.getElementById('followers').value);
  const following = parseUsers(document.getElementById('following').value);

  const fset = new Set(followers);
  const gset = new Set(following);

  const noFollowback = following.filter(u => !fset.has(u)).sort();
  const fans = followers.filter(u => !gset.has(u)).sort();

  const html = `
    <h3>Resumen</h3>
    <p><b>Followers:</b> ${followers.length} | <b>Following:</b> ${following.length}</p>
    <p><b>No te siguen de vuelta:</b> ${noFollowback.length}</p>
    <p><b>Te siguen y vos no seguís:</b> ${fans.length}</p>
    <h4>No te siguen de vuelta</h4>
    <ul>${noFollowback.map(u => `<li>${u}</li>`).join('')}</ul>
  `;
  document.getElementById('summary').innerHTML = html;
};
</script>
</body>
</html>
"""


@dataclass
class Snapshot:
    generated_at: str
    source: str
    target: str
    followers: list[str]
    followees: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compara seguidores/seguidos de Instagram.")
    subparsers = parser.add_subparsers(dest="mode")

    web = subparsers.add_parser("web", help="Levanta mini web local para pegar listas.")
    web.add_argument("--host", default="127.0.0.1", help="Host de la mini web (default 127.0.0.1)")
    web.add_argument("--port", type=int, default=8765, help="Puerto de la mini web (default 8765)")

    offline = subparsers.add_parser("offline", help="Usa archivos JSON exportados por Instagram.")
    offline.add_argument("--followers-file", required=True, help="Ruta a followers_1.json")
    offline.add_argument("--following-file", required=True, help="Ruta a following.json")
    offline.add_argument("--target", default="mi_cuenta", help="Etiqueta para resultados/snapshot")
    offline.add_argument("--snapshot-dir", default="data", help="Directorio de snapshots")

    api = subparsers.add_parser("api", help="Consulta Instagram con instaloader (puede fallar por rate limit).")
    api.add_argument("--username", required=True, help="Usuario con el que iniciás sesión")
    api.add_argument("--target", required=True, help="Cuenta a consultar")
    api.add_argument("--snapshot-dir", default="data", help="Directorio de snapshots")
    api.add_argument("--retries", type=int, default=3, help="Reintentos ante rate limit")
    api.add_argument("--base-wait", type=int, default=45, help="Segundos base de backoff")

    parser.set_defaults(mode="web")
    return parser.parse_args()


def is_rate_limited(error: Exception) -> bool:
    lowered = str(error).lower()
    return any(hint.lower() in lowered for hint in RATE_LIMIT_HINTS)


def snapshot_path(snapshot_dir: Path, target: str, source: str) -> Path:
    safe_target = target.replace("/", "_")
    safe_source = source.replace("/", "_")
    return snapshot_dir / f"{safe_target}-{safe_source}-snapshot.json"


def save_snapshot(path: Path, source: str, target: str, followers: Set[str], followees: Set[str]) -> None:
    payload = Snapshot(
        generated_at=datetime.now(tz=timezone.utc).isoformat(),
        source=source,
        target=target,
        followers=sorted(followers),
        followees=sorted(followees),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")


def load_snapshot(path: Path) -> Optional[Snapshot]:
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Snapshot(
        generated_at=raw["generated_at"],
        source=raw.get("source", "unknown"),
        target=raw["target"],
        followers=raw["followers"],
        followees=raw["followees"],
    )


def extract_usernames(node: Any) -> Set[str]:
    usernames: Set[str] = set()

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            if "value" in item and isinstance(item["value"], str):
                usernames.add(normalize_username(item["value"]))
            if "href" in item and isinstance(item["href"], str):
                usernames.add(normalize_username(item["href"]))
            for value in item.values():
                walk(value)
        elif isinstance(item, list):
            for value in item:
                walk(value)

    walk(node)
    return {u for u in usernames if u}


def normalize_username(raw: str) -> str:
    text = raw.strip().lstrip("@").rstrip("/")
    m = re.search(r"instagram\.com/([A-Za-z0-9._]+)", text, flags=re.IGNORECASE)
    if m:
        text = m.group(1)
    return text.lower() if re.fullmatch(r"[A-Za-z0-9._]+", text) else ""


def parse_pasted_usernames(text: str) -> Set[str]:
    chunks = re.split(r"[\n,;\t ]+", text)
    return {u for u in (normalize_username(chunk) for chunk in chunks) if u}


def print_summary(followers: Set[str], followees: Set[str]) -> None:
    no_me_siguen = sorted(followees - followers)
    te_siguen_y_no_seguidos = sorted(followers - followees)

    print("\n=== RESUMEN ===")
    print(f"Followers: {len(followers)}")
    print(f"Followees: {len(followees)}")
    print(f"No te siguen de vuelta: {len(no_me_siguen)}")
    print(f"Te siguen y vos no seguís: {len(te_siguen_y_no_seguidos)}")
    if no_me_siguen:
        print("\nUsuarios que no te siguen de vuelta:")
        for username in no_me_siguen:
            print(f"- {username}")


def run_offline(args: argparse.Namespace) -> int:
    followers_path = Path(args.followers_file)
    following_path = Path(args.following_file)
    if not followers_path.exists() or not following_path.exists():
        print("❌ No se encontraron los JSON indicados.")
        print(f"   followers: {followers_path}")
        print(f"   following: {following_path}")
        return 2

    followers = extract_usernames(json.loads(followers_path.read_text(encoding="utf-8")))
    followees = extract_usernames(json.loads(following_path.read_text(encoding="utf-8")))
    out_path = snapshot_path(Path(args.snapshot_dir), args.target, "offline")
    save_snapshot(out_path, "offline", args.target, followers, followees)

    print("✅ Modo offline completado (sin llamadas a Instagram API).")
    print(f"✅ Snapshot guardado: {out_path}")
    print_summary(followers, followees)
    return 0


def import_instaloader_or_exit():
    try:
        import instaloader  # type: ignore

        return instaloader
    except ModuleNotFoundError:
        print("❌ Falta dependencia opcional: instaloader")
        print("   Instalá con: python -m pip install instaloader")
        print("   Alternativa recomendada: python main.py web")
        return None


def fetch_with_backoff(action: Callable[[], Iterable[Any]], *, label: str, retries: int, base_wait: int) -> Set[str]:
    for attempt in range(1, retries + 1):
        try:
            return {profile.username for profile in action()}
        except Exception as error:
            if not is_rate_limited(error) or attempt >= retries:
                raise
            wait_seconds = base_wait * attempt
            print(f"⚠️  {label}: rate limit temporal ({attempt}/{retries}), esperando {wait_seconds}s...")
            time.sleep(wait_seconds)
    raise RuntimeError(f"No se pudo consultar {label} luego de {retries} intentos")


def login(loader: Any, username: str) -> None:
    try:
        loader.load_session_from_file(username)
        print("✅ Sesión cargada desde archivo")
        return
    except FileNotFoundError:
        pass

    password = getpass.getpass(f"Password para {username}: ")
    loader.login(username, password)
    loader.save_session_to_file()
    print("✅ Sesión iniciada y guardada")


def run_api(args: argparse.Namespace) -> int:
    instaloader = import_instaloader_or_exit()
    if instaloader is None:
        return 3

    loader = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
    )

    login(loader, args.username)
    target_profile = instaloader.Profile.from_username(loader.context, args.target)
    out_path = snapshot_path(Path(args.snapshot_dir), args.target, "api")

    print("📥 Obteniendo seguidores y seguidos por API...")
    try:
        followers = fetch_with_backoff(
            target_profile.get_followers,
            label="followers",
            retries=args.retries,
            base_wait=args.base_wait,
        )
        followees = fetch_with_backoff(
            target_profile.get_followees,
            label="followees",
            retries=args.retries,
            base_wait=args.base_wait,
        )
        save_snapshot(out_path, "api", args.target, followers, followees)
        print(f"✅ Snapshot actualizado en {out_path}")
    except Exception as error:
        if is_rate_limited(error):
            cached = load_snapshot(out_path)
            if cached:
                print("⚠️  Instagram aplicó rate limit. Usando último snapshot API local.")
                followers = set(cached.followers)
                followees = set(cached.followees)
            else:
                print("❌ Instagram limitó temporalmente y no hay snapshot API local.")
                print(f"   Detalle: {error}")
                print("💡 Probá: python main.py web")
                return 2
        else:
            print(f"❌ Error inesperado: {error}")
            return 1

    print_summary(followers, followees)
    return 0


def run_web(args: argparse.Namespace) -> int:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path not in ("/", "/index.html"):
                self.send_error(404)
                return
            content = WEB_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format: str, *args: Any) -> None:  # silence
            return

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"🌐 Mini web lista en http://{args.host}:{args.port}")
    print("   1) Abrí Instagram web (followers/following)")
    print("   2) Copiá/pegá usuarios en esta mini web")
    print("   3) Click en Calcular")
    print("   Ctrl+C para salir")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Cerrando mini web")
    finally:
        server.server_close()
    return 0


def main() -> int:
    args = parse_args()
    if args.mode == "web":
        return run_web(args)
    if args.mode == "offline":
        return run_offline(args)
    if args.mode == "api":
        return run_api(args)
    print("❌ Modo inválido")
    return 1


if __name__ == "__main__":
    sys.exit(main())
