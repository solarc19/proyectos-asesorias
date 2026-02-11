#!/usr/bin/env python3
"""Checker de no-followback para Instagram, pragmático y simple.

Modos:
1) offline (recomendado): usa archivos JSON exportados por Instagram.
2) api (opcional): usa instaloader con sesión local + backoff.

Esto evita depender 100% de llamadas GraphQL que Instagram bloquea con
"Please wait a few minutes" / 401.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Set

RATE_LIMIT_HINTS = (
    "Please wait a few minutes",
    "401 Unauthorized",
    "feedback_required",
    "rate limit",
)


@dataclass
class Snapshot:
    generated_at: str
    source: str
    target: str
    followers: list[str]
    followees: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compara seguidores/seguidos de Instagram con enfoque pragmático: "
            "offline por export JSON o api con instaloader."
        )
    )
    subparsers = parser.add_subparsers(dest="mode")

    offline = subparsers.add_parser(
        "offline",
        help="Usa archivos JSON de export de Instagram (recomendado: cero rate limit).",
    )
    offline.add_argument(
        "--followers-file",
        required=True,
        help="Ruta a followers_1.json (o similar) dentro del export de Instagram",
    )
    offline.add_argument(
        "--following-file",
        required=True,
        help="Ruta a following.json (o similar) dentro del export de Instagram",
    )
    offline.add_argument(
        "--target",
        default="mi_cuenta",
        help="Nombre de cuenta para etiquetar resultados/snapshot",
    )
    offline.add_argument(
        "--snapshot-dir",
        default="data",
        help="Directorio para guardar snapshot JSON (default: data)",
    )

    api = subparsers.add_parser(
        "api",
        help="Consulta Instagram con instaloader (puede sufrir rate limit).",
    )
    api.add_argument("--username", required=True, help="Usuario con el que iniciás sesión")
    api.add_argument(
        "--target",
        required=True,
        help="Cuenta a consultar (puede ser la misma que --username)",
    )
    api.add_argument(
        "--snapshot-dir",
        default="data",
        help="Directorio para guardar snapshot JSON (default: data)",
    )
    api.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Cantidad de reintentos ante rate limit (default: 3)",
    )
    api.add_argument(
        "--base-wait",
        type=int,
        default=45,
        help="Segundos base para espera incremental (default: 45)",
    )

    parser.set_defaults(mode="offline")
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
                usernames.add(item["value"].strip().lstrip("@"))
            if "href" in item and isinstance(item["href"], str):
                href = item["href"].rstrip("/")
                if "/" in href:
                    usernames.add(href.split("/")[-1].strip().lstrip("@"))
            for value in item.values():
                walk(value)
        elif isinstance(item, list):
            for value in item:
                walk(value)

    walk(node)
    return {u for u in usernames if u}


def run_offline(args: argparse.Namespace) -> int:
    followers_path = Path(args.followers_file)
    following_path = Path(args.following_file)

    if not followers_path.exists() or not following_path.exists():
        print("❌ No se encontraron los JSON indicados.")
        print(f"   followers: {followers_path}")
        print(f"   following: {following_path}")
        return 2

    followers_data = json.loads(followers_path.read_text(encoding="utf-8"))
    following_data = json.loads(following_path.read_text(encoding="utf-8"))

    followers = extract_usernames(followers_data)
    followees = extract_usernames(following_data)

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
        print("   Alternativa recomendada: usar modo offline con export JSON de Instagram.")
        return None


def fetch_with_backoff(
    action: Callable[[], Iterable[Any]],
    *,
    label: str,
    retries: int,
    base_wait: int,
) -> Set[str]:
    for attempt in range(1, retries + 1):
        try:
            return {profile.username for profile in action()}
        except Exception as error:
            if not is_rate_limited(error) or attempt >= retries:
                raise
            wait_seconds = base_wait * attempt
            print(
                f"⚠️  {label}: rate limit temporal (intento {attempt}/{retries}). "
                f"Esperando {wait_seconds}s..."
            )
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
                print(f"   Snapshot: {out_path} ({cached.generated_at})")
                followers = set(cached.followers)
                followees = set(cached.followees)
            else:
                print("❌ Instagram limitó temporalmente y no hay snapshot API local.")
                print(f"   Detalle: {error}")
                print("💡 Recomendación: ejecutá modo offline con JSON exportado por Instagram.")
                return 2
        else:
            print(f"❌ Error inesperado: {error}")
            return 1

    print_summary(followers, followees)
    return 0


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


def main() -> int:
    args = parse_args()

    if args.mode == "offline":
        return run_offline(args)
    if args.mode == "api":
        return run_api(args)

    print("❌ Modo inválido")
    return 1


if __name__ == "__main__":
    sys.exit(main())
