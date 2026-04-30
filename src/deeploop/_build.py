from __future__ import annotations

import shutil
from pathlib import Path

from setuptools.command.build_py import build_py as _build_py


class build_py(_build_py):
    def run(self) -> None:
        super().run()
        self._copy_runtime_assets()

    def _copy_runtime_assets(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        asset_root = Path(self.build_lib) / "deeploop" / "_assets"
        asset_dirs = (
            "configs",
            "schemas",
            "scripts/mission",
            "scripts/runtime",
        )
        for relative_dir in asset_dirs:
            source = repo_root / relative_dir
            if not source.exists():
                continue
            destination = asset_root / relative_dir
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(
                source,
                destination,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
