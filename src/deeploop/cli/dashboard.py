"""Serve a read-only HTML dashboard for a DeepLoop mission.

Uses only stdlib ``http.server`` plus the existing ``rich`` dependency
for markdown-to-terminal rendering.  No additional dependencies required.

Usage::

    python -m deeploop.cli.dashboard --state-path <mission_state.json> [--port 8080]
"""

from __future__ import annotations

import argparse
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from deeploop.mission._monitor_snapshot import build_mission_snapshot
from deeploop.mission._monitor_render import render_mission_snapshot


class DashboardHandler(BaseHTTPRequestHandler):
    state_path: Path = Path(".")

    def do_GET(self) -> None:
        qs = parse_qs(urlparse(self.path).query)
        state = qs.get("state_path", [str(self.state_path)])[0]
        path = Path(state).expanduser().resolve()
        if not path.exists():
            self._respond(404, f"<h1>Not Found</h1><p>{path}</p>")
            return
        try:
            snapshot = build_mission_snapshot(path)
            md = render_mission_snapshot(snapshot)
            from rich.markdown import Markdown
            from rich.console import Console
            console = Console(file=StringIO(), width=120, force_terminal=False, no_color=True)
            console.print(Markdown(md))
            body = console.file.getvalue()
        except Exception as exc:
            self._respond(500, f"<h1>Error</h1><pre>{exc}</pre>")
            return
        html = (
            "<!DOCTYPE html>\n<html><head>"
            "<title>DeepLoop Mission</title>"
            '<meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            "<style>"
            "body{font-family:monospace;padding:2em;background:#0d1117;color:#c9d1d9;max-width:1200px;margin:0 auto}"
            "pre{white-space:pre-wrap;line-height:1.5}"
            "</style></head><body><pre>"
            + body +
            "</pre></body></html>"
        )
        self._respond(200, html)

    def _respond(self, code: int, body: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, fmt: str, *args: object) -> None:
        pass  # suppress access logs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve a DeepLoop mission dashboard")
    parser.add_argument("--state-path", required=True, help="Path to mission_state.json")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    args = parser.parse_args(argv)

    state_path = Path(args.state_path).expanduser().resolve()
    if not state_path.exists():
        print(f"Mission state not found: {state_path}", file=sys.stderr)
        return 1

    DashboardHandler.state_path = state_path
    server = HTTPServer(("0.0.0.0", args.port), DashboardHandler)
    print(f"DeepLoop dashboard: http://localhost:{args.port}/")
    print(f"Mission: {state_path.parent.name}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
