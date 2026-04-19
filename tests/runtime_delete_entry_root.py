from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.parse_args()
    history_path = Path(os.environ["DEEPLOOP_RUNTIME_HISTORY_PATH"])
    shutil.rmtree(history_path.parent, ignore_errors=True)
    print("deleted runtime entry root", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
