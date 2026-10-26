"""Servidor HTTP compatível com a BiometricServiceAPI (substitui Express + cors + morgan).

Usa apenas ``http.server`` da biblioteca padrão. Não há dependências externas.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlsplit

from . import APP_NAME
from .service import BiometricService, Result

MAX_BODY = 10 * 1024 * 1024  # mesmo limite do express.json({ limit: "10mb" })
API_PREFIX = "/apiservice"

LogFn = Callable[[dict[str, Any]], None]


def _bool(value: str | None) -> bool:
    return value in ("true", "1")


class _Request:
    def __init__(self, handler: "Handler", body: Any) -> None:
        self.handler = handler
        parts = urlsplit(handler.path)
        self.query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        self.body = body

    def q(self, name: str) -> str | None:
        return self.query.get(name)


# ---------------------------------------------------------------- controllers
def _capture_hash(svc: BiometricService, req: _Request, _m) -> Result:
    return svc.capture_hash(img=_bool(req.q("img")), scenario=req.q("scenario"))


def _capture_for_verify(svc: BiometricService, req: _Request, _m) -> Result:
    return svc.capture_for_verify(scenario=req.q("scenario"))


def _match_one_on_one(svc: BiometricService, req: _Request, _m) -> Result:
    template = req.body.get("template") if isinstance(req.body, dict) else None
    if not template:
        return 400, {"message": "Template is required", "success": False}
    return svc.match_one_on_one(template=template, img=_bool(req.q("img")), scenario=req.q("scenario"))


def _identification(svc: BiometricService, req: _Request, _m) -> Result:
    return svc.identification(img=_bool(req.q("img")), scenario=req.q("scenario"))


def _load_to_memory(svc: BiometricService, req: _Request, _m) -> Result:
    return svc.load_to_memory(req.body)


def _delete_all(svc: BiometricService, _req: _Request, _m) -> Result:
    return svc.delete_all_from_memory()


def _total(svc: BiometricService, _req: _Request, _m) -> Result:
    return svc.total_in_memory()


def _device_id(svc: BiometricService, req: _Request, _m) -> Result:
    return svc.device_unique_id(scenario=req.q("scenario"))


def _join(svc: BiometricService, req: _Request, _m) -> Result:
    return svc.join_templates(req.body)


def _list_mock(svc: BiometricService, _req: _Request, _m) -> Result:
    return 200, {"fingerprints": svc.list_fingerprints(), "success": True}


def _select_mock(svc: BiometricService, _req: _Request, match: re.Match) -> Result:
    fp_id = unquote(match.group(1))
    if not svc.set_current_finger(fp_id):
        return 404, {"message": "Mock fingerprint not found", "success": False}
    return 200, {"message": f"Mock fingerprint {fp_id} selected", "success": True}


def _root(_svc, _req, _m) -> Result:
    return 200, {"name": APP_NAME, "status": "running", "success": True}


ROUTES: list[tuple[str, re.Pattern, Callable]] = [
    ("GET", re.compile(r"^/$"), _root),
    ("GET", re.compile(rf"^{API_PREFIX}/capture-hash$"), _capture_hash),
    ("GET", re.compile(rf"^{API_PREFIX}/capture-for-verify$"), _capture_for_verify),
    ("POST", re.compile(rf"^{API_PREFIX}/match-one-on-one$"), _match_one_on_one),
    ("GET", re.compile(rf"^{API_PREFIX}/identification$"), _identification),
    ("POST", re.compile(rf"^{API_PREFIX}/load-to-memory$"), _load_to_memory),
    ("GET", re.compile(rf"^{API_PREFIX}/delete-all-from-memory$"), _delete_all),
    ("GET", re.compile(rf"^{API_PREFIX}/total-in-memory$"), _total),
    ("GET", re.compile(rf"^{API_PREFIX}/device-unique-id$"), _device_id),
    ("POST", re.compile(rf"^{API_PREFIX}/join-templates$"), _join),
    # exclusivos do simulador
    ("GET", re.compile(rf"^{API_PREFIX}/mock/fingerprints$"), _list_mock),
    ("POST", re.compile(rf"^{API_PREFIX}/mock/fingerprints/([^/]+)/select$"), _select_mock),
]


class Handler(BaseHTTPRequestHandler):
    server_version = "HamsterDXSimulator"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # preenchidos por make_server()
    service: BiometricService
    log_fn: LogFn | None = None

    # BaseHTTPRequestHandler escreve em sys.stderr, que é None no .exe sem console.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    # ---------------------------------------------------------------- verbs
    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def do_OPTIONS(self) -> None:
        # Pré-voo CORS, igual ao pacote "cors" com configuração padrão
        started = time.perf_counter()
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET,HEAD,PUT,PATCH,POST,DELETE")
        requested = self.headers.get("Access-Control-Request-Headers")
        if requested:
            self.send_header("Access-Control-Allow-Headers", requested)
            self.send_header("Vary", "Access-Control-Request-Headers")
        self.send_header("Content-Length", "0")
        self.end_headers()
        self._log("OPTIONS", 204, started)

    # ---------------------------------------------------------------- core
    def _dispatch(self, method: str) -> None:
        started = time.perf_counter()
        path = urlsplit(self.path).path
        norm = path.rstrip("/").lower() or "/"  # Express: case-insensitive, barra final opcional

        body: Any = None
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._send(413, {"message": "Payload too large", "success": False}, method, started)
            return
        if length:
            raw = self.rfile.read(length)
            ctype = (self.headers.get("Content-Type") or "").lower()
            if "json" in ctype or not ctype:
                try:
                    body = json.loads(raw.decode("utf-8")) if raw.strip() else None
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._send(400, {"message": "Invalid JSON body", "success": False}, method, started)
                    return

        for route_method, pattern, controller in ROUTES:
            if route_method != method:
                continue
            match = pattern.match(norm)
            if match:
                try:
                    status, payload = controller(self.service, _Request(self, body), match)
                except Exception as exc:  # noqa: BLE001
                    status, payload = 500, {"message": "Internal simulator error", "success": False}
                    self._log(method, 500, started, error=repr(exc))
                    self._write(status, payload)
                    return
                self._send(status, payload, method, started)
                return

        self._send(404, {"message": "Endpoint not found", "success": False}, method, started)

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")

    def _write(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            self.send_response(status)
            self._cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # cliente desistiu da requisição (ex.: timeout do front-end)

    def _send(self, status: int, payload: dict[str, Any], method: str, started: float) -> None:
        self._write(status, payload)
        self._log(method, status, started, message=payload.get("message"))

    def _log(self, method: str, status: int, started: float, **extra: Any) -> None:
        if self.log_fn is None:
            return
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "method": method,
            "path": self.path,
            "status": status,
            "ms": round((time.perf_counter() - started) * 1000, 1),
            "client": self.client_address[0] if self.client_address else "",
        }
        entry.update({k: v for k, v in extra.items() if v})
        try:
            self.log_fn(entry)
        except Exception:  # noqa: BLE001
            pass


class _HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # No Windows SO_REUSEADDR deixaria duas instâncias ouvirem a mesma porta.
    allow_reuse_address = os.name != "nt"


class SimulatorServer:
    """Liga/desliga o servidor HTTP em uma thread de fundo."""

    def __init__(self, service: BiometricService, log_fn: LogFn | None = None) -> None:
        self.service = service
        self.log_fn = log_fn
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def address(self) -> tuple[str, int] | None:
        if not self._httpd:
            return None
        host, port = self._httpd.server_address[:2]
        return str(host), int(port)

    def start(self, host: str, port: int) -> None:
        if self._httpd:
            return
        log_fn = staticmethod(self.log_fn) if self.log_fn else None
        handler = type("BoundHandler", (Handler,), {"service": self.service, "log_fn": log_fn})
        httpd = _HTTPServer((host, port), handler)
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever, name="http-server", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        httpd, self._httpd = self._httpd, None
        if not httpd:
            return
        self.service.cancel_pending()  # destrava requisições presas no modo manual
        httpd.shutdown()
        httpd.server_close()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
