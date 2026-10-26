"""Regras de negócio do simulador (equivalente a ``src/services/biometric.service.js``).

Todos os métodos são thread-safe: o servidor HTTP atende cada requisição em uma
thread e a interface gráfica altera a configuração ao mesmo tempo.
"""

from __future__ import annotations

import base64
import hashlib
import threading
import time
from typing import Any, Callable

from . import paths, scenarios
from .config import AppConfig

Result = tuple[int, dict[str, Any]]
Listener = Callable[[str, Any], None]


class BiometricService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.memory: list[dict[str, Any]] = []

        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._cancel_gen = 0
        self._release_gen = 0
        self._pending = 0

        self._image_cache: dict[str, tuple[float, str]] = {}
        self._listeners: list[Listener] = []

    # ------------------------------------------------------------- eventos
    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def _emit(self, event: str, payload: Any = None) -> None:
        for listener in list(self._listeners):
            try:
                listener(event, payload)
            except Exception:  # noqa: BLE001 - um ouvinte com erro não derruba a API
                pass

    # ------------------------------------------------------------- cenários
    def resolve_scenario(self, requested: str | None) -> scenarios.Scenario:
        cfg = self.config
        if not cfg.force_scenario:
            chosen = scenarios.get(requested)
            if chosen:
                return chosen
        return scenarios.get(cfg.default_scenario) or scenarios.SCENARIOS["success"]

    # ------------------------------------------------------------- captura
    @property
    def pending_captures(self) -> int:
        with self._lock:
            return self._pending

    def release_finger(self) -> None:
        """Modo manual: "coloca o dedo" no leitor e libera as capturas pendentes."""
        with self._cond:
            self._release_gen += 1
            self._cond.notify_all()

    def cancel_pending(self) -> None:
        """Cancela todas as capturas em andamento (respondem "Capture cancelled")."""
        with self._cond:
            self._cancel_gen += 1
            self._cond.notify_all()

    def _wait_capture(self, scenario: scenarios.Scenario) -> str:
        """Simula o tempo até o dedo ser lido.

        Retorna ``"ok"``, ``"cancelled"`` ou ``"timeout"`` (este último só no modo manual).
        """
        cfg = self.config
        manual = cfg.capture_mode == "manual"

        # can_release: o botão "Colocar dedo" encerra a espera antes do prazo.
        # (no cenário Timeout ninguém coloca o dedo, então ele não vale)
        if scenario.key == "timeout":
            seconds, can_release = cfg.timeout_delay_ms / 1000, False
        elif manual and scenario.key in scenarios.IMMEDIATE_IN_MANUAL:
            return "ok"
        elif manual:
            seconds, can_release = cfg.manual_timeout_ms / 1000, True
        else:
            seconds, can_release = cfg.capture_delay_ms / 1000, True

        with self._cond:
            cancel_gen, release_gen = self._cancel_gen, self._release_gen
            self._pending += 1
        self._emit("pending", self.pending_captures)
        try:
            deadline = time.monotonic() + max(0.0, seconds)
            with self._cond:
                while True:
                    if self._cancel_gen != cancel_gen:
                        return "cancelled"
                    if can_release and self._release_gen != release_gen:
                        return "ok"
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        # manual: o prazo esgotou sem dedo => Timeout
                        return "timeout" if manual and scenario.key != "timeout" else "ok"
                    self._cond.wait(remaining)
        finally:
            with self._cond:
                self._pending -= 1
            self._emit("pending", self.pending_captures)

    def _capture(self, requested: str | None) -> tuple[scenarios.Scenario, Result | None]:
        """Executa a espera e devolve um erro pronto quando o cenário/espera falha."""
        scenario = self.resolve_scenario(requested)
        outcome = self._wait_capture(scenario)
        if outcome == "cancelled":
            return scenario, _scenario_result(scenarios.SCENARIOS["cancelled"])
        if outcome == "timeout":
            return scenario, _scenario_result(scenarios.SCENARIOS["timeout"])
        if not scenario.is_success:
            return scenario, _scenario_result(scenario)
        return scenario, None

    # ------------------------------------------------------------- digitais
    def list_fingerprints(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"id": f["id"], "fingerId": f["fingerId"], "name": f["name"], "quality": f["quality"]}
                for f in self.config.fingerprints
            ]

    def get_fingerprint(self, fp_id: Any) -> dict[str, Any] | None:
        try:
            wanted = int(fp_id)
        except (TypeError, ValueError):
            return None
        with self._lock:
            return next((f for f in self.config.fingerprints if f["id"] == wanted), None)

    def current_finger(self) -> dict[str, Any] | None:
        with self._lock:
            fp = self.get_fingerprint(self.config.current_fingerprint_id)
            if fp is None and self.config.fingerprints:
                fp = self.config.fingerprints[0]
            return dict(fp) if fp else None

    def set_current_finger(self, fp_id: Any) -> bool:
        fp = self.get_fingerprint(fp_id)
        if not fp:
            return False
        with self._lock:
            self.config.current_fingerprint_id = fp["id"]
        self._emit("finger", fp["id"])
        return True

    def image_base64(self, fixture: str | None) -> str | None:
        path = paths.resolve_image(fixture)
        if path is None:
            return None
        key = str(path)
        mtime = path.stat().st_mtime
        cached = self._image_cache.get(key)
        if cached and cached[0] == mtime:
            return cached[1]
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        self._image_cache[key] = (mtime, data)
        return data

    # ------------------------------------------------------------- API FingerTech
    def capture_hash(self, img: bool = False, scenario: str | None = None) -> Result:
        sc, error = self._capture(scenario)
        if error:
            return error
        fp = self.current_finger()
        if fp is None:
            return _no_fingerprint()
        quality = self.config.low_quality_value if sc.low_quality else fp["quality"]
        response: dict[str, Any] = {
            "fingers-registered": 1,
            "template": fp["template"],
            "fingers-id": [fp["fingerId"]],
            "quality-FIR": quality,
            "success": True,
        }
        if img:
            response["images"] = [self.image_base64(fp["fixture"])]
        return 200, response

    def capture_for_verify(self, scenario: str | None = None) -> Result:
        _, error = self._capture(scenario)
        if error:
            return error
        fp = self.current_finger()
        if fp is None:
            return _no_fingerprint()
        return 200, {"template": fp["template"], "image": self.image_base64(fp["fixture"]), "success": True}

    def match_one_on_one(self, template: str, img: bool = False, scenario: str | None = None) -> Result:
        _, error = self._capture(scenario)
        if error:
            return error
        fp = self.current_finger()
        if fp is None:
            return _no_fingerprint()
        matches = template == fp["template"]
        response: dict[str, Any] = {
            "message": "Fingerprint matches" if matches else "Fingerprint doesnt match",
            "success": matches,
        }
        if img:
            response["image"] = self.image_base64(fp["fixture"])
        return 200, response

    def identification(self, img: bool = False, scenario: str | None = None) -> Result:
        _, error = self._capture(scenario)
        if error:
            return error
        fp = self.current_finger()
        if fp is None:
            return _no_fingerprint()
        with self._lock:
            match = next((m for m in self.memory if m["template"] == fp["template"]), None)
        if match:
            response: dict[str, Any] = {"message": "Fingerprint match found", "id": match["id"], "success": True}
        else:
            response = {"message": "Fingerprint match not found", "id": 0, "success": False}
        if img:
            response["image"] = self.image_base64(fp["fixture"])
        return 200, response

    def load_to_memory(self, fingers: Any) -> Result:
        if not isinstance(fingers, list):
            return 400, {"message": "Invalid templates array", "success": False}
        parsed = []
        for finger in fingers:
            if not isinstance(finger, dict) or finger.get("id") is None or not finger.get("template"):
                return 400, {"message": "Error on AddFIR: invalid template", "success": False}
            try:
                parsed.append({"id": int(finger["id"]), "template": str(finger["template"])})
            except (TypeError, ValueError):
                return 400, {"message": "Error on AddFIR: invalid template", "success": False}
        with self._lock:
            self.memory = parsed
        self._emit("memory", len(parsed))
        return 200, {"message": "Templates loaded to memory", "success": True}

    def delete_all_from_memory(self) -> Result:
        with self._lock:
            self.memory = []
        self._emit("memory", 0)
        return 200, {"message": "All templates deleted from memory", "success": True}

    def total_in_memory(self) -> Result:
        with self._lock:
            return 200, {"total": len(self.memory), "success": True}

    def device_unique_id(self, scenario: str | None = None) -> Result:
        if self.resolve_scenario(scenario).key == "disconnected":
            return 400, {"message": "Device not found", "success": False}
        return 200, {"serial": self.config.device_serial, "success": True}

    def join_templates(self, fingers: Any) -> Result:
        if not isinstance(fingers, list) or len(fingers) < 2:
            return 400, {
                "message": "Error creating template: at least two templates required",
                "success": False,
            }
        templates = [f.get("template") for f in fingers if isinstance(f, dict) and f.get("template")]
        if len(templates) != len(fingers):
            return 400, {"message": "Error creating template: invalid template", "success": False}
        digest = hashlib.sha256("|".join(map(str, templates)).encode("utf-8")).digest()
        combined = base64.b64encode(digest).decode("ascii")
        return 200, {
            "template": f"MOCK_JOINED_{combined}",
            "message": "Templates joined successfully",
            "success": True,
        }

    # ------------------------------------------------------------- memória (GUI)
    def memory_snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(m) for m in self.memory]

    def template_owner(self, template: str) -> str:
        """Nome da digital mock que tem esse template (para exibir na tela)."""
        with self._lock:
            for fp in self.config.fingerprints:
                if fp["template"] == template:
                    return fp["name"]
        return ""


def _scenario_result(scenario: scenarios.Scenario) -> Result:
    return scenario.status, dict(scenario.response)


def _no_fingerprint() -> Result:
    return 400, {"message": "Error on Capture: no mock fingerprint configured", "success": False}
