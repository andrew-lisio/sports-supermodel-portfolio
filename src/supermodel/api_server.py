from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .service_runtime import build_health
from .security import SecuritySettings, SlidingWindowRateLimiter


class ReadOnlyAPI:
    def __init__(self, runtime_root: str | Path = "runtime") -> None:
        self.runtime_root = Path(runtime_root)

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def response(self, path: str) -> tuple[int, dict[str, Any]]:
        normalized = urlparse(path).path.rstrip("/") or "/"
        if normalized == "/healthz":
            return HTTPStatus.OK, build_health("api").to_record()
        if normalized == "/readyz":
            health = build_health(
                "api",
                require_shared_storage=os.environ.get(
                    "SPORTS_SUPERMODEL_REQUIRE_SHARED_STORAGE", "0"
                )
                == "1",
            )
            status = HTTPStatus.OK if health.status == "PASS" else HTTPStatus.SERVICE_UNAVAILABLE
            return status, health.to_record()
        resources = {
            "/api/v1/slate/latest": self.runtime_root / "state" / "slate_publisher.json",
            "/api/v1/refresh/latest": self.runtime_root / "state" / "platform_refresh.json",
            "/api/v1/performance/latest": self.runtime_root / "performance" / "latest.json",
        }
        target = resources.get(normalized)
        if target is None:
            return HTTPStatus.NOT_FOUND, {"status": "NOT_FOUND", "path": normalized}
        payload = self._read_json(target)
        if payload is None:
            return HTTPStatus.SERVICE_UNAVAILABLE, {
                "status": "UNAVAILABLE",
                "path": normalized,
                "resource": str(target),
            }
        return HTTPStatus.OK, payload


def handler_factory(api: ReadOnlyAPI):
    security = SecuritySettings.from_env()
    limiter = SlidingWindowRateLimiter(
        limit=security.rate_limit_requests,
        window_seconds=security.rate_limit_window_seconds,
    )

    class Handler(BaseHTTPRequestHandler):
        server_version = "SportsSuperModelAPI/1"

        def do_GET(self) -> None:  # noqa: N802
            forwarded = self.headers.get("X-Forwarded-For") if security.trust_proxy_headers else None
            client_key = (forwarded or self.client_address[0]).split(",")[0].strip()
            if not limiter.allow(client_key):
                status, payload = HTTPStatus.TOO_MANY_REQUESTS, {"status": "RATE_LIMITED"}
            else:
                status, payload = api.response(self.path)
            encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: Any) -> None:
            if os.environ.get("SPORTS_SUPERMODEL_API_ACCESS_LOG", "1") != "0":
                super().log_message(format, *args)

    return Handler


def serve(*, host: str = "0.0.0.0", port: int = 8080, runtime_root: str | Path = "runtime") -> None:
    api = ReadOnlyAPI(runtime_root)
    server = ThreadingHTTPServer((host, int(port)), handler_factory(api))
    server.serve_forever()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sports-supermodel-api")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    parser.add_argument("--runtime-root", type=Path, default=Path("runtime"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    serve(host=args.host, port=args.port, runtime_root=args.runtime_root)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
