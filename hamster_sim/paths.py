"""Resolução de caminhos que funciona tanto no código-fonte quanto no executável.

- Código-fonte: os recursos ficam na raiz do projeto (pasta acima de ``hamster_sim``).
- PyInstaller: os recursos são copiados para ``sys._MEIPASS``.
- Nuitka (standalone): os recursos ficam ao lado do executável.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME


def resource_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def fixtures_dir() -> Path:
    return resource_dir() / "fixtures"


def assets_dir() -> Path:
    return resource_dir() / "assets"


def config_dir() -> Path:
    """Pasta gravável para o arquivo de configuração do usuário."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / APP_NAME.replace(" ", "")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        path = Path(base) / "hamster-dx-simulator"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    override = os.environ.get("HAMSTER_SIM_CONFIG")
    if override:
        return Path(override)
    return config_dir() / "config.json"


def resolve_image(fixture: str | None) -> Path | None:
    """Aceita o nome de um arquivo da pasta ``fixtures`` ou um caminho absoluto."""
    if not fixture:
        return None
    candidate = Path(fixture)
    if not candidate.is_absolute():
        candidate = fixtures_dir() / fixture
    return candidate if candidate.is_file() else None


def bundled_fixtures() -> list[str]:
    folder = fixtures_dir()
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if p.suffix.lower() in {".png", ".gif", ".bmp", ".jpg", ".jpeg"})
