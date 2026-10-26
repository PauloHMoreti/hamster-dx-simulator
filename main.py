"""Ponto de entrada do Hamster DX Simulator.

    python main.py            -> abre a tela de configuração (Tkinter)
    python main.py --nogui    -> só o servidor, no terminal (útil em CI/Docker)
"""

from __future__ import annotations

import argparse
import sys

from hamster_sim import APP_NAME, APP_VERSION, config
from hamster_sim.service import BiometricService


def run_headless(args: argparse.Namespace) -> int:
    import time

    from hamster_sim.server import SimulatorServer

    cfg = config.load()
    if args.host:
        cfg.host = args.host
    if args.port:
        cfg.port = args.port
    service = BiometricService(cfg)

    def log(entry: dict) -> None:
        print(f"{entry['time']} {entry['method']} {entry['path']} {entry['status']} - {entry['ms']} ms", flush=True)

    server = SimulatorServer(service, log)
    server.start(cfg.host, cfg.port)
    print(f"{APP_NAME} running on http://{cfg.host}:{cfg.port}/apiservice  (Ctrl+C para sair)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="HamsterDXSimulator", description=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument("--nogui", action="store_true", help="roda só o servidor, sem a tela")
    parser.add_argument("--host", help="endereço de escuta (padrão: o da configuração)")
    parser.add_argument("--port", type=int, help="porta (padrão: a da configuração)")
    args = parser.parse_args()

    if args.nogui:
        return run_headless(args)

    from hamster_sim.gui import run_gui

    return run_gui(host=args.host, port=args.port)


if __name__ == "__main__":
    sys.exit(main())
