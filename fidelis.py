#!/usr/bin/env python3
"""Cross-platform launcher and prerequisite checker for FIDELIS."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
DOCKER_INSTALL_URL = "https://docs.docker.com/get-docker/"


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=PROJECT_DIR, check=check, text=True)


def fail(message: str) -> None:
    print(f"FIDELIS: {message}", file=sys.stderr)
    raise SystemExit(1)


def check_prerequisites() -> None:
    if shutil.which("docker") is None:
        fail(
            "Docker no está instalado o no está disponible en PATH.\n"
            f"Instala Docker Desktop/Engine desde {DOCKER_INSTALL_URL}, "
            "inícialo y vuelve a ejecutar este comando."
        )

    if run(["docker", "compose", "version"], check=False).returncode != 0:
        fail(
            "Docker Compose v2 no está disponible. Actualiza Docker Desktop "
            "o instala el plugin Compose: https://docs.docker.com/compose/install/"
        )

    if run(["docker", "info"], check=False).returncode != 0:
        fail(
            "Docker está instalado, pero el motor no responde. "
            "Abre Docker Desktop o inicia el servicio Docker."
        )

    print("FIDELIS: Docker y Compose están disponibles.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Comprueba los prerrequisitos y ejecuta FIDELIS."
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("up", "check", "down"),
        default="up",
        help="up (predeterminado), check o down",
    )
    parser.add_argument(
        "-d", "--detach", action="store_true", help="ejecutar los servicios en segundo plano"
    )
    args = parser.parse_args()

    check_prerequisites()
    if args.command == "check":
        return

    compose_command = ["docker", "compose", args.command]
    if args.command == "up":
        compose_command.append("--build")
        if args.detach:
            compose_command.append("--detach")
        print("FIDELIS: iniciando motor e interfaz en http://localhost:8000")

    try:
        run(compose_command)
    except KeyboardInterrupt:
        print("\nFIDELIS: ejecución interrumpida.")
    except subprocess.CalledProcessError as error:
        fail(f"Docker Compose terminó con el código {error.returncode}.")


if __name__ == "__main__":
    main()
