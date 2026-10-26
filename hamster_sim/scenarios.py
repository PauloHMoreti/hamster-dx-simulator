"""Cenários de simulação (equivalente a ``src/mocks/scenarios.js``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    description: str
    status: int = 200
    response: dict[str, Any] = field(default_factory=dict)
    # True quando o cenário usa a qualidade configurada para "baixa qualidade"
    low_quality: bool = False

    @property
    def is_success(self) -> bool:
        return self.status == 200


SCENARIOS: dict[str, Scenario] = {
    s.key: s
    for s in (
        Scenario("success", "Sucesso", "Captura normal com a digital selecionada."),
        Scenario(
            "lowQuality",
            "Baixa qualidade",
            "Captura com sucesso, mas com quality-FIR baixo.",
            low_quality=True,
        ),
        Scenario(
            "timeout",
            "Timeout",
            "Ninguém coloca o dedo; responde após o tempo de timeout.",
            400,
            {"message": "Timeout", "success": False},
        ),
        Scenario(
            "disconnected",
            "Leitor desconectado",
            "Simula o leitor fora da USB (DEVICE_NOT_FOUND).",
            400,
            {"message": "Error on Capture: DEVICE_NOT_FOUND", "success": False},
        ),
        Scenario(
            "sdkError",
            "SDK não inicializado",
            "Erro de inicialização do SDK (SDK_NOT_INITIALIZED).",
            400,
            {"message": "Error on Capture: SDK_NOT_INITIALIZED", "success": False},
        ),
        Scenario(
            "captureError",
            "Falha na captura",
            "Erro genérico de captura (CAPTURE_FAILED).",
            400,
            {"message": "Error on Capture: CAPTURE_FAILED", "success": False},
        ),
        Scenario(
            "cancelled",
            "Captura cancelada",
            "O usuário cancelou a janela de captura.",
            400,
            {"message": "Capture cancelled", "success": False},
        ),
    )
}

# Cenários que, no modo manual, respondem na hora (não há dedo a esperar)
IMMEDIATE_IN_MANUAL = {"disconnected", "sdkError"}


def get(key: str | None) -> Scenario | None:
    if not key:
        return None
    return SCENARIOS.get(key)
