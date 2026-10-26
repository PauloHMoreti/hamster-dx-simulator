"""Configuração persistente do simulador (substitui o ``.env`` e o ``mocks/fingerprints.js``)."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from . import paths

DEFAULT_FINGERPRINTS: list[dict[str, Any]] = [
    {
        "id": 1,
        "fingerId": 1,
        "name": "user-01-right-thumb",
        "template": "AAAAAZCXZDSfe34t4fSIMULATED_FINGERPRINT_TEMPLATE_USER_01_RIGHT_THUMB",
        "fixture": "finger-01.png",
        "quality": 95,
    },
    {
        "id": 2,
        "fingerId": 2,
        "name": "user-01-right-index",
        "template": "AAAAAZCXZDSfe34t4fSIMULATED_FINGERPRINT_TEMPLATE_USER_01_RIGHT_INDEX",
        "fixture": "finger-02.png",
        "quality": 91,
    },
    {
        "id": 3,
        "fingerId": 1,
        "name": "user-02-right-thumb",
        "template": "AAAAAZCXZDSfe34t4fSIMULATED_FINGERPRINT_TEMPLATE_USER_02_RIGHT_THUMB",
        "fixture": "finger-01.png",
        "quality": 87,
    },
]


@dataclass
class AppConfig:
    # Servidor
    host: str = "127.0.0.1"
    port: int = 5000
    auto_start: bool = True

    # Simulação
    default_scenario: str = "success"
    force_scenario: bool = False  # ignora ?scenario= vindo da requisição
    capture_mode: str = "auto"  # "auto" (espera o atraso) | "manual" (espera clique na tela)
    capture_delay_ms: int = 1200
    timeout_delay_ms: int = 3000
    manual_timeout_ms: int = 15000
    low_quality_value: int = 18
    device_serial: str = "MOCK-HAMSTER-DX-000001"

    # Digitais
    current_fingerprint_id: int = 1
    fingerprints: list[dict[str, Any]] = field(default_factory=lambda: copy.deepcopy(DEFAULT_FINGERPRINTS))

    # ------------------------------------------------------------------ helpers
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        cfg = cls()
        known = {f.name: f for f in fields(cls)}
        for key, value in (data or {}).items():
            if key not in known:
                continue
            default = getattr(cfg, key)
            try:
                if isinstance(default, bool):
                    value = bool(value)
                elif isinstance(default, int):
                    value = int(value)
                elif isinstance(default, str):
                    value = str(value)
                elif isinstance(default, list):
                    if not isinstance(value, list):
                        continue
            except (TypeError, ValueError):
                continue
            setattr(cfg, key, value)
        cfg.fingerprints = [fp for fp in (_clean_fp(x) for x in cfg.fingerprints) if fp]
        return cfg

    @classmethod
    def from_env(cls, base: "AppConfig") -> "AppConfig":
        """Mantém compatibilidade com as variáveis do antigo ``.env``."""
        if os.environ.get("PORT"):
            try:
                base.port = int(os.environ["PORT"])
            except ValueError:
                pass
        if os.environ.get("MOCK_DEFAULT_SCENARIO"):
            base.default_scenario = os.environ["MOCK_DEFAULT_SCENARIO"]
        if os.environ.get("MOCK_CAPTURE_DELAY"):
            try:
                base.capture_delay_ms = int(os.environ["MOCK_CAPTURE_DELAY"])
            except ValueError:
                pass
        return base


def _clean_fp(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        return {
            "id": int(raw["id"]),
            "fingerId": int(raw.get("fingerId", 1)),
            "name": str(raw.get("name", f"finger-{raw['id']}")),
            "template": str(raw["template"]),
            "fixture": str(raw.get("fixture") or ""),
            "quality": max(0, min(100, int(raw.get("quality", 90)))),
        }
    except (KeyError, TypeError, ValueError):
        return None


def load(path: Path | None = None) -> AppConfig:
    path = path or paths.config_file()
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    return AppConfig.from_env(AppConfig.from_dict(data))


def save(cfg: AppConfig, path: Path | None = None) -> None:
    path = path or paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Escrita atômica para não corromper o arquivo se o app fechar no meio
    fd, tmp = tempfile.mkstemp(prefix="config.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(cfg.to_dict(), fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
