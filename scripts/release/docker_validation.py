from __future__ import annotations

import argparse
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOCKERFILE = REPO_ROOT / "docker" / "release-validation.Dockerfile"
DEFAULT_IMAGE_PREFIX = "deeploop-release-validation"
DEFAULT_PYTHON_IMAGE = "python:3.11-slim"


def load_project_version() -> str:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(pyproject["project"]["version"])


def default_install_spec() -> str:
    return f"deeploop=={load_project_version()}"


def _sanitize_tag_suffix(raw: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "-", raw.lower()).strip("-") or "validation"


def default_image_tag(mode: str, *, install_spec: str | None = None) -> str:
    if mode == "dist":
        suffix = f"dist-{load_project_version()}"
    elif install_spec and install_spec.startswith("deeploop=="):
        suffix = f"pypi-{install_spec.split('==', 1)[1]}"
    else:
        suffix = "pypi-custom"
    return f"{DEFAULT_IMAGE_PREFIX}:{_sanitize_tag_suffix(suffix)}"


def build_docker_build_command(
    *,
    mode: str,
    docker_bin: str,
    dockerfile: Path,
    image_tag: str,
    python_image: str,
    pull: bool,
    install_spec: str | None = None,
) -> list[str]:
    target = "artifact-validation" if mode == "dist" else "pypi-validation"
    command = [
        docker_bin,
        "build",
        "--file",
        str(dockerfile),
        "--target",
        target,
        "--tag",
        image_tag,
        "--build-arg",
        f"PYTHON_IMAGE={python_image}",
    ]
    if pull:
        command.append("--pull")
    if mode == "pypi":
        command.extend(["--build-arg", f"DEEPLOOP_INSTALL_SPEC={install_spec or default_install_spec()}"])
    command.append(str(REPO_ROOT))
    return command


def _run(command: list[str]) -> int:
    print(f"+ {shlex.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
    return int(completed.returncode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build and run DeepLoop's Docker clean-room release validation harness.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--docker-bin", default="docker", help="Docker-compatible CLI to invoke.")
    parser.add_argument("--dockerfile", default=str(DEFAULT_DOCKERFILE), help="Path to the validation Dockerfile.")
    parser.add_argument("--python-image", default=DEFAULT_PYTHON_IMAGE, help="Base Python image for the harness.")
    parser.add_argument("--no-pull", action="store_true", help="Skip docker build --pull.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    dist_parser = subparsers.add_parser(
        "validate-dist",
        help="Build DeepLoop artifacts in Docker, install the wheel in a fresh container, and run the clean-room smoke helper.",
    )
    dist_parser.add_argument("--tag", help="Optional image tag override for the artifact-validation build.")

    pypi_parser = subparsers.add_parser(
        "validate-pypi",
        help="Install DeepLoop from PyPI in Docker and run the clean-room smoke helper.",
    )
    pypi_parser.add_argument("--install-spec", default=default_install_spec(), help="Requirement specifier to install in the PyPI validation stage.")
    pypi_parser.add_argument("--tag", help="Optional image tag override for the pypi-validation build.")

    args = parser.parse_args(argv)

    if shutil.which(args.docker_bin) is None:
        print(f"docker-validation: required CLI `{args.docker_bin}` was not found on PATH", file=sys.stderr)
        return 2

    mode = "dist" if args.command == "validate-dist" else "pypi"
    install_spec = getattr(args, "install_spec", None)
    image_tag = args.tag or default_image_tag(mode, install_spec=install_spec)
    command = build_docker_build_command(
        mode=mode,
        docker_bin=args.docker_bin,
        dockerfile=Path(args.dockerfile).expanduser().resolve(),
        image_tag=image_tag,
        python_image=args.python_image,
        pull=not args.no_pull,
        install_spec=install_spec,
    )
    return _run(command)


if __name__ == "__main__":
    raise SystemExit(main())
