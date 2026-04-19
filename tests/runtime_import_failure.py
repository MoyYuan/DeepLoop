from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.parse_args()
    import definitely_missing_runtime_dependency  # noqa: F401

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
