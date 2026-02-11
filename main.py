#!/usr/bin/env python3
"""Instagram followers utility with pragmatic rate-limit handling.

Uso simple:
  python main.py --username TU_USUARIO --target TU_CUENTA

- Guarda/reutiliza sesión local para evitar logins repetidos.
- Si Instagram responde con rate limit (Please wait a few minutes),
  aplica backoff y reintentos cortos.
- Si no puede consultar, cae al último snapshot local para no frenar flujo.
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
from typing import Callable, Iterable, Set

import instaloader


RATE_LIMIT_HINTS = (
    "Please wait a few minutes",
    "401 Unauthorized",
    "feedback_required",
    "rate limit",
)


@dataclass
class Snapshot:
    generated_at: str
    target: str
    followers: list[str]
    followees: list[str]


class InstagramRateLimited(RuntimeError):
    """Error explícito para manejo pragmático de rate limiting."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Descarga seguidores/seguidos con backoff y snapshot local."
    )
    parser.add_argument("--username", required=True, help="Usuario con el que iniciás sesión")
    parser.add_argument(
        "--target",
        required=True,
        help="Cuenta a consultar (puede ser la misma que --username)",
    )
    parser.add_argument(
        "--snapshot-dir",
        default="data",
        help="Directorio para guardar snapshot JSON (default: data)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Cantidad de reintentos ante rate limit (default: 3)",
    )
    parser.add_argument(
        "--base-wait",
        type=int,
        default=45,
        help="Segundos base para espera incremental (default: 45)",
    )
    return parser.parse_args()


def is_rate_limited(error: Exception) -> bool:
    message = str(error)
    lowered = message.lower()
    return any(hint.lower() in lowered for hint in RATE_LIMIT_HINTS)


def fetch_with_backoff(
    action: Callable[[], Iterable[instaloader.Profile]],
    *,
    label: str,
    retries: int,
    base_wait: int,
) -> Set[str]:
    for attempt in range(1, retries + 1):
        try:
            return {profile.username for profile in action()}
        except Exception as error:  # instaloader mezcla excepciones runtime/http
            if not is_rate_limited(error) or attempt >= retries:
                raise
            wait_seconds = base_wait * attempt
            print(
                f"⚠️  {label}: Instagram limitó temporalmente (intento {attempt}/{retries}). "
                f"Esperando {wait_seconds}s..."
            )
            time.sleep(wait_seconds)

    raise InstagramRateLimited(f"No se pudo consultar {label} luego de {retries} intentos")


def snapshot_path(snapshot_dir: Path, target: str) -> Path:
    safe_target = target.replace("/", "_")
    return snapshot_dir / f"{safe_target}-snapshot.json"


def save_snapshot(path: Path, target: str, followers: Set[str], followees: Set[str]) -> None:
    payload = Snapshot(
        generated_at=datetime.now(tz=timezone.utc).isoformat(),
        target=target,
        followers=sorted(followers),
        followees=sorted(followees),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")


def load_snapshot(path: Path) -> Snapshot | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Snapshot(
        generated_at=raw["generated_at"],
        target=raw["target"],
        followers=raw["followers"],
        followees=raw["followees"],
    )


def login(loader: instaloader.Instaloader, username: str) -> None:
    try:
        loader.load_session_from_file(username)
        print("✅ Sesión cargada desde archivo local")
        return
    except FileNotFoundError:
        pass

    password = getpass.getpass(f"Password para {username}: ")
    loader.login(username, password)
    loader.save_session_to_file()
    print("✅ Sesión iniciada y guardada")


def main() -> int:
    args = parse_args()

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
    out_path = snapshot_path(Path(args.snapshot_dir), args.target)

    print("📥 Obteniendo seguidores y seguidos...")
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
        save_snapshot(out_path, args.target, followers, followees)
        print(f"✅ Snapshot actualizado en {out_path}")
    except Exception as error:
        if is_rate_limited(error):
            cached = load_snapshot(out_path)
            if cached:
                print("⚠️  Instagram aplicó rate limit. Usando último snapshot local.")
                print(f"   Snapshot: {out_path} ({cached.generated_at})")
                followers = set(cached.followers)
                followees = set(cached.followees)
            else:
                print("❌ Instagram limitó temporalmente y no hay snapshot local para fallback.")
                print(f"   Detalle: {error}")
                return 2
        else:
            print(f"❌ Error inesperado: {error}")
            return 1

    no_me_siguen = sorted(followees - followers)

    print("\n=== RESUMEN ===")
    print(f"Followers: {len(followers)}")
    print(f"Followees: {len(followees)}")
    print(f"No te siguen de vuelta: {len(no_me_siguen)}")

    if no_me_siguen:
        print("\nUsuarios que no te siguen de vuelta:")
        for username in no_me_siguen:
            print(f"- {username}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
