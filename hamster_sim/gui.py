"""Tela de configuração do simulador (Tkinter, nativo do Python)."""

from __future__ import annotations

import os
import queue
import secrets
import subprocess
import sys
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from . import APP_NAME, APP_VERSION, config, paths, scenarios
from .config import DEFAULT_FINGERPRINTS, AppConfig
from .server import SimulatorServer
from .service import BiometricService

MAX_LOG_LINES = 1000
PREVIEW_SIZE = 180

COLOR_OK = "#1f9d55"
COLOR_OFF = "#c0392b"
COLOR_WAIT = "#d68910"
COLOR_MUTED = "#6b7280"


def _enable_dpi_awareness() -> None:
    """Deixa a tela nítida em monitores com escala (125%, 150%...) no Windows."""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass


class App:
    def __init__(self, root: tk.Tk, cfg: AppConfig) -> None:
        self.root = root
        self.cfg = cfg
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()

        self.service = BiometricService(cfg)
        self.service.subscribe(lambda ev, data: self.events.put((ev, data)))
        self.server = SimulatorServer(self.service, lambda entry: self.events.put(("log", entry)))

        self._save_job: str | None = None
        self._preview_img: tk.PhotoImage | None = None
        self._loading = True  # evita salvar enquanto os campos são preenchidos

        self._setup_window()
        self._build_header()
        self._build_notebook()
        self._loading = False

        self._refresh_fingerprints()
        self._refresh_memory()
        self._refresh_capture_strip()

        if cfg.auto_start:
            self.start_server(silent_errors=False)
        self._update_server_status()
        self.root.after(100, self._poll_events)

    # ================================================================ janela
    def _setup_window(self) -> None:
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("940x640")
        self.root.minsize(820, 560)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        style = ttk.Style(self.root)
        if os.name != "nt" and "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("Muted.TLabel", foreground=COLOR_MUTED)
        style.configure("Big.TButton", padding=(14, 6))

        icon_png = paths.assets_dir() / "icon.png"
        icon_ico = paths.assets_dir() / "icon.ico"
        try:
            if os.name == "nt" and icon_ico.is_file():
                self.root.iconbitmap(default=str(icon_ico))
            elif icon_png.is_file():
                self._icon = tk.PhotoImage(file=str(icon_png))
                self.root.iconphoto(True, self._icon)
        except tk.TclError:
            pass

    # ================================================================ topo
    def _build_header(self) -> None:
        top = ttk.Frame(self.root, padding=(12, 10, 12, 4))
        top.pack(fill="x")

        self.status_dot = tk.Canvas(top, width=14, height=14, highlightthickness=0, bg=self._bg())
        self.status_dot.grid(row=0, column=0, padx=(0, 8))
        self._dot = self.status_dot.create_oval(2, 2, 13, 13, fill=COLOR_OFF, outline="")

        self.status_var = tk.StringVar(value="Servidor parado")
        ttk.Label(top, textvariable=self.status_var, style="Title.TLabel").grid(row=0, column=1, sticky="w")

        btns = ttk.Frame(top)
        btns.grid(row=0, column=2, sticky="e")
        top.columnconfigure(1, weight=1)
        self.toggle_btn = ttk.Button(btns, text="Iniciar", command=self.toggle_server, width=10)
        self.toggle_btn.pack(side="left", padx=2)
        ttk.Button(btns, text="Copiar URL", command=self.copy_url).pack(side="left", padx=2)
        ttk.Button(btns, text="Abrir no navegador", command=self.open_browser).pack(side="left", padx=2)

        # Faixa do "leitor": o que vai acontecer na próxima captura
        strip = ttk.LabelFrame(self.root, text="Leitor simulado", padding=(10, 6))
        strip.pack(fill="x", padx=12, pady=(4, 6))
        strip.columnconfigure(0, weight=1)

        self.reader_var = tk.StringVar()
        ttk.Label(strip, textvariable=self.reader_var, wraplength=560).grid(row=0, column=0, sticky="w")
        self.pending_var = tk.StringVar()
        self.pending_lbl = ttk.Label(strip, textvariable=self.pending_var, style="Muted.TLabel")
        self.pending_lbl.grid(row=1, column=0, sticky="w", pady=(2, 0))

        self.release_btn = ttk.Button(strip, text="Colocar dedo no leitor", style="Big.TButton", command=self.service.release_finger)
        self.release_btn.grid(row=0, column=1, rowspan=2, padx=4)
        self.cancel_btn = ttk.Button(strip, text="Cancelar capturas", command=self.service.cancel_pending)
        self.cancel_btn.grid(row=0, column=2, rowspan=2, padx=4)

    def _bg(self) -> str:
        return ttk.Style(self.root).lookup("TFrame", "background") or self.root.cget("bg")

    # ================================================================ abas
    def _build_notebook(self) -> None:
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.notebook = nb
        nb.add(self._tab_simulation(nb), text="  Simulação  ")
        nb.add(self._tab_fingerprints(nb), text="  Digitais  ")
        nb.add(self._tab_memory(nb), text="  Memória  ")
        nb.add(self._tab_server(nb), text="  Servidor  ")
        self.log_tab = self._tab_log(nb)
        nb.add(self.log_tab, text="  Log de requisições  ")

    # ---------------------------------------------------------------- simulação
    def _tab_simulation(self, parent: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=12)
        tab.columnconfigure(0, weight=3)
        tab.columnconfigure(1, weight=2)

        box = ttk.LabelFrame(tab, text="Cenário padrão", padding=10)
        box.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 8))
        box.columnconfigure(1, weight=1)
        self.scenario_var = tk.StringVar(value=self.cfg.default_scenario)
        for i, sc in enumerate(scenarios.SCENARIOS.values()):
            ttk.Radiobutton(box, text=sc.label, value=sc.key, variable=self.scenario_var).grid(
                row=i, column=0, sticky="w", pady=2
            )
            ttk.Label(box, text=sc.description, style="Muted.TLabel", wraplength=270).grid(
                row=i, column=1, sticky="w", padx=(8, 0)
            )
        self.scenario_var.trace_add("write", lambda *_: self._set("default_scenario", self.scenario_var.get()))

        self.force_var = tk.BooleanVar(value=self.cfg.force_scenario)
        ttk.Checkbutton(
            box,
            text="Forçar este cenário (ignorar ?scenario= enviado pelo sistema)",
            variable=self.force_var,
            command=lambda: self._set("force_scenario", self.force_var.get()),
        ).grid(row=len(scenarios.SCENARIOS), column=0, columnspan=2, sticky="w", pady=(10, 0))

        cap = ttk.LabelFrame(tab, text="Captura", padding=10)
        cap.grid(row=0, column=1, sticky="nsew")
        cap.columnconfigure(1, weight=1)
        self.mode_var = tk.StringVar(value=self.cfg.capture_mode)
        ttk.Radiobutton(cap, text="Automática (responde após o atraso)", value="auto", variable=self.mode_var).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Radiobutton(cap, text="Manual (espera clicar em \"Colocar dedo\")", value="manual", variable=self.mode_var).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )
        self.mode_var.trace_add("write", lambda *_: self._set("capture_mode", self.mode_var.get()))

        self._int_field(cap, 2, "Atraso da captura (ms)", "capture_delay_ms", 0, 60000, 100)
        self._int_field(cap, 3, "Tempo do cenário Timeout (ms)", "timeout_delay_ms", 0, 120000, 500)
        self._int_field(cap, 4, "Timeout no modo manual (ms)", "manual_timeout_ms", 1000, 600000, 1000)
        self._int_field(cap, 5, "quality-FIR em \"Baixa qualidade\"", "low_quality_value", 0, 100, 1)

        dev = ttk.LabelFrame(tab, text="Dispositivo", padding=10)
        dev.grid(row=1, column=1, sticky="nsew", pady=(8, 0))
        dev.columnconfigure(0, weight=1)
        ttk.Label(dev, text="Serial retornado pelo /device-unique-id").grid(row=0, column=0, sticky="w")
        self.serial_var = tk.StringVar(value=self.cfg.device_serial)
        ttk.Entry(dev, textvariable=self.serial_var).grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.serial_var.trace_add("write", lambda *_: self._set("device_serial", self.serial_var.get().strip()))
        tab.rowconfigure(1, weight=1)
        return tab

    def _int_field(self, parent: ttk.Frame, row: int, label: str, key: str, lo: int, hi: int, step: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        var = tk.StringVar(value=str(getattr(self.cfg, key)))
        spin = ttk.Spinbox(parent, from_=lo, to=hi, increment=step, textvariable=var, width=9)
        spin.grid(row=row, column=1, sticky="e", padx=(8, 0))

        def on_change(*_: Any) -> None:
            try:
                value = int(var.get())
            except ValueError:
                return
            if lo <= value <= hi:
                self._set(key, value)

        var.trace_add("write", on_change)
        setattr(self, f"{key}_var", var)

    # ---------------------------------------------------------------- digitais
    def _tab_fingerprints(self, parent: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=12)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        cols = ("current", "id", "fingerId", "name", "quality", "fixture")
        tree = ttk.Treeview(tab, columns=cols, show="headings", selectmode="browse")
        for col, title, width, anchor in (
            ("current", "Atual", 50, "center"),
            ("id", "ID", 45, "center"),
            ("fingerId", "Finger ID", 70, "center"),
            ("name", "Nome", 200, "w"),
            ("quality", "Qualidade", 85, "center"),
            ("fixture", "Imagem", 150, "w"),
        ):
            tree.heading(col, text=title)
            tree.column(col, width=width, anchor=anchor, stretch=col in ("name", "fixture"))
        tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(tab, orient="vertical", command=tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=sb.set)
        tree.bind("<<TreeviewSelect>>", lambda _e: self._update_preview())
        tree.bind("<Double-1>", lambda _e: self.use_selected_finger())
        self.fp_tree = tree

        side = ttk.Frame(tab, padding=(12, 0, 0, 0))
        side.grid(row=0, column=2, sticky="ns")
        self.preview_lbl = ttk.Label(side, text="Sem imagem", anchor="center", relief="groove", width=24)
        self.preview_lbl.pack(ipady=4, fill="x")
        self.preview_info = ttk.Label(side, text="", style="Muted.TLabel", wraplength=220, justify="left")
        self.preview_info.pack(fill="x", pady=(6, 0))

        bar = ttk.Frame(tab)
        bar.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Button(bar, text="Usar como digital atual", command=self.use_selected_finger).pack(side="left")
        ttk.Button(bar, text="Nova…", command=self.add_finger).pack(side="left", padx=(12, 2))
        ttk.Button(bar, text="Editar…", command=self.edit_finger).pack(side="left", padx=2)
        ttk.Button(bar, text="Remover", command=self.remove_finger).pack(side="left", padx=2)
        ttk.Button(bar, text="Copiar template", command=self.copy_template).pack(side="left", padx=(12, 2))
        ttk.Button(bar, text="Restaurar padrão", command=self.reset_fingers).pack(side="right")
        return tab

    # ---------------------------------------------------------------- memória
    def _tab_memory(self, parent: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=12)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        ttk.Label(
            tab,
            text="Templates carregados via /load-to-memory (usados pelo /identification).",
            style="Muted.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        cols = ("id", "owner", "template")
        tree = ttk.Treeview(tab, columns=cols, show="headings")
        tree.heading("id", text="ID")
        tree.heading("owner", text="Digital mock correspondente")
        tree.heading("template", text="Template")
        tree.column("id", width=60, anchor="center", stretch=False)
        tree.column("owner", width=230, stretch=False)
        tree.column("template", width=400)
        tree.grid(row=1, column=0, sticky="nsew")
        sb = ttk.Scrollbar(tab, orient="vertical", command=tree.yview)
        sb.grid(row=1, column=1, sticky="ns")
        tree.configure(yscrollcommand=sb.set)
        self.mem_tree = tree

        bar = ttk.Frame(tab)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.mem_total_var = tk.StringVar(value="Total: 0")
        ttk.Label(bar, textvariable=self.mem_total_var).pack(side="left")
        ttk.Button(bar, text="Limpar memória", command=self.clear_memory).pack(side="right")
        ttk.Button(bar, text="Carregar digitais mock na memória", command=self.load_mocks_to_memory).pack(
            side="right", padx=6
        )
        return tab

    # ---------------------------------------------------------------- servidor
    def _tab_server(self, parent: ttk.Notebook) -> ttk.Frame:
        outer = ttk.Frame(parent, padding=12)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)
        tab = ttk.Frame(outer)
        tab.grid(row=0, column=0, sticky="nsew")
        tab.columnconfigure(1, weight=1)

        ttk.Label(tab, text="Endereço").grid(row=0, column=0, sticky="w", pady=4)
        self.host_var = tk.StringVar(value=self.cfg.host)
        host = ttk.Combobox(tab, textvariable=self.host_var, values=("127.0.0.1", "0.0.0.0", "localhost"), width=18)
        host.grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(
            tab,
            text="127.0.0.1 = só este computador (não aciona o Firewall do Windows). "
            "0.0.0.0 = aceita conexões da rede (o Windows vai pedir permissão no firewall).",
            style="Muted.TLabel",
            wraplength=340,
        ).grid(row=1, column=1, sticky="w", padx=8)

        ttk.Label(tab, text="Porta").grid(row=2, column=0, sticky="w", pady=(12, 4))
        self.port_var = tk.StringVar(value=str(self.cfg.port))
        ttk.Spinbox(tab, from_=1, to=65535, textvariable=self.port_var, width=8).grid(
            row=2, column=1, sticky="w", padx=8, pady=(12, 4)
        )

        self.autostart_var = tk.BooleanVar(value=self.cfg.auto_start)
        ttk.Checkbutton(
            tab,
            text="Iniciar o servidor automaticamente ao abrir o programa",
            variable=self.autostart_var,
            command=lambda: self._set("auto_start", self.autostart_var.get()),
        ).grid(row=3, column=1, sticky="w", padx=8, pady=8)

        ttk.Button(tab, text="Aplicar e reiniciar servidor", command=self.apply_server_settings).grid(
            row=4, column=1, sticky="w", padx=8, pady=(4, 16)
        )

        ttk.Separator(tab).grid(row=5, column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Label(tab, text="Configuração salva em").grid(row=6, column=0, sticky="nw")
        cfg_frame = ttk.Frame(tab)
        cfg_frame.grid(row=6, column=1, sticky="w", padx=8)
        ttk.Label(cfg_frame, text=str(paths.config_file()), style="Muted.TLabel", wraplength=340).pack(anchor="w")
        ttk.Button(cfg_frame, text="Abrir pasta", command=self.open_config_folder).pack(anchor="w", pady=(4, 0))

        ep_box = ttk.LabelFrame(outer, text="Endpoints", padding=10)
        ep_box.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        endpoints = (
            "Prefixo: /apiservice\n\n"
            "GET  /capture-hash?img=true\n"
            "GET  /capture-for-verify\n"
            "POST /match-one-on-one?img=true\n"
            "     {\"template\": \"…\"}\n"
            "GET  /identification?img=true\n"
            "POST /load-to-memory\n"
            "     [{\"id\": 1, \"template\": \"…\"}]\n"
            "GET  /delete-all-from-memory\n"
            "GET  /total-in-memory\n"
            "GET  /device-unique-id\n"
            "POST /join-templates\n"
            "     [{\"template\": \"…\"}, …]\n\n"
            "Exclusivos do simulador:\n"
            "GET  /mock/fingerprints\n"
            "POST /mock/fingerprints/{id}/select\n\n"
            "Captura e device-unique-id\naceitam ?scenario=<cenário>"
        )
        ttk.Label(ep_box, text=endpoints, font=("Consolas", 9), justify="left").pack(anchor="nw")
        return outer

    # ---------------------------------------------------------------- log
    def _tab_log(self, parent: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=12)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        text = tk.Text(tab, height=10, wrap="none", font=("Consolas", 9), state="disabled", relief="flat", borderwidth=1)
        text.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(tab, orient="vertical", command=text.yview)
        sb.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=sb.set)
        text.tag_configure("ok", foreground=COLOR_OK)
        text.tag_configure("err", foreground=COLOR_OFF)
        text.tag_configure("warn", foreground=COLOR_WAIT)
        text.tag_configure("muted", foreground=COLOR_MUTED)
        self.log_text = text

        bar = ttk.Frame(tab)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.autoscroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Rolar automaticamente", variable=self.autoscroll_var).pack(side="left")
        ttk.Button(bar, text="Limpar", command=self.clear_log).pack(side="right")
        return tab

    # ================================================================ config
    def _set(self, key: str, value: Any) -> None:
        if self._loading or getattr(self.cfg, key) == value:
            return
        setattr(self.cfg, key, value)
        self._refresh_capture_strip()
        self._schedule_save()

    def _schedule_save(self) -> None:
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(400, self._save_now)

    def _save_now(self) -> None:
        self._save_job = None
        try:
            config.save(self.cfg)
        except OSError as exc:
            self._log_line(f"Não foi possível salvar a configuração: {exc}", "err")

    # ================================================================ servidor
    def start_server(self, silent_errors: bool = False) -> bool:
        try:
            self.server.start(self.cfg.host, self.cfg.port)
        except OSError as exc:
            msg = f"Não foi possível iniciar em {self.cfg.host}:{self.cfg.port}.\n\n{exc}"
            if getattr(exc, "errno", None) in (98, 10048, 48) or getattr(exc, "winerror", None) == 10048:
                msg += "\n\nA porta já está em uso (outra instância do simulador ou o serviço real da FingerTech?)."
            self._log_line(msg.replace("\n\n", " "), "err")
            if not silent_errors:
                messagebox.showerror(APP_NAME, msg, parent=self.root)
            return False
        finally:
            self._update_server_status()
        self._log_line(f"Servidor iniciado em {self.base_url()}", "ok")
        return True

    def stop_server(self) -> None:
        self.server.stop()
        self._log_line("Servidor parado", "muted")
        self._update_server_status()

    def toggle_server(self) -> None:
        if self.server.running:
            self.stop_server()
        else:
            self.start_server()

    def apply_server_settings(self) -> None:
        host = self.host_var.get().strip() or "127.0.0.1"
        try:
            port = int(self.port_var.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_NAME, "Porta inválida (use 1–65535).", parent=self.root)
            return
        self._set("host", host)
        self._set("port", port)
        if self.server.running:
            self.server.stop()
        self.start_server()

    def base_url(self) -> str:
        host = self.cfg.host
        if host in ("0.0.0.0", "", "::"):
            host = "localhost"
        return f"http://{host}:{self.cfg.port}/apiservice"

    def _update_server_status(self) -> None:
        if self.server.running:
            self.status_var.set(f"Rodando em {self.base_url()}")
            self.status_dot.itemconfigure(self._dot, fill=COLOR_OK)
            self.toggle_btn.configure(text="Parar")
        else:
            self.status_var.set("Servidor parado")
            self.status_dot.itemconfigure(self._dot, fill=COLOR_OFF)
            self.toggle_btn.configure(text="Iniciar")

    def copy_url(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.base_url())

    def open_browser(self) -> None:
        webbrowser.open(self.base_url() + "/mock/fingerprints")

    def open_config_folder(self) -> None:
        folder = str(paths.config_file().parent)
        try:
            if os.name == "nt":
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except OSError:
            messagebox.showinfo(APP_NAME, folder, parent=self.root)

    # ================================================================ faixa do leitor
    def _refresh_capture_strip(self) -> None:
        fp = self.service.current_finger()
        sc = scenarios.get(self.cfg.default_scenario) or scenarios.SCENARIOS["success"]
        forced = " (forçado)" if self.cfg.force_scenario else ""
        mode = "manual" if self.cfg.capture_mode == "manual" else f"auto ({self.cfg.capture_delay_ms} ms)"
        finger = f"{fp['name']} (ID {fp['id']})" if fp else "nenhuma"
        self.reader_var.set(f"Digital: {finger}   ·   Cenário: {sc.label}{forced}   ·   Captura: {mode}")

        pending = self.service.pending_captures
        manual = self.cfg.capture_mode == "manual"
        if pending:
            hint = " — clique em \"Colocar dedo no leitor\"" if manual else ""
            self.pending_var.set(f"{pending} captura(s) aguardando o dedo{hint}")
            self.pending_lbl.configure(foreground=COLOR_WAIT)
        else:
            self.pending_var.set("Nenhuma captura em andamento")
            self.pending_lbl.configure(foreground=COLOR_MUTED)
        self.release_btn.state(["!disabled"] if pending else ["disabled"])
        self.cancel_btn.state(["!disabled"] if pending else ["disabled"])

    # ================================================================ digitais
    def _refresh_fingerprints(self, select_id: int | None = None) -> None:
        tree = self.fp_tree
        prev = select_id if select_id is not None else self._selected_fp_id()
        tree.delete(*tree.get_children())
        current = self.service.current_finger()
        current_id = current["id"] if current else None
        for fp in self.cfg.fingerprints:
            tree.insert(
                "",
                "end",
                iid=str(fp["id"]),
                values=(
                    "●" if fp["id"] == current_id else "",
                    fp["id"],
                    fp["fingerId"],
                    fp["name"],
                    fp["quality"],
                    os.path.basename(fp["fixture"]) or "—",
                ),
            )
        target = prev if prev is not None else current_id
        if target is not None and tree.exists(str(target)):
            tree.selection_set(str(target))
            tree.see(str(target))
        self._update_preview()
        self._refresh_capture_strip()

    def _selected_fp_id(self) -> int | None:
        sel = self.fp_tree.selection() if hasattr(self, "fp_tree") else ()
        return int(sel[0]) if sel else None

    def _selected_fp(self) -> dict[str, Any] | None:
        fp_id = self._selected_fp_id()
        return self.service.get_fingerprint(fp_id) if fp_id is not None else None

    def _update_preview(self) -> None:
        fp = self._selected_fp()
        self._preview_img = None
        if not fp:
            self.preview_lbl.configure(image="", text="Sem seleção")
            self.preview_info.configure(text="")
            return
        path = paths.resolve_image(fp["fixture"])
        if path is None:
            self.preview_lbl.configure(image="", text="Imagem não encontrada")
        else:
            try:
                img = tk.PhotoImage(file=str(path))
                factor = max(1, -(-max(img.width(), img.height()) // PREVIEW_SIZE))
                self._preview_img = img.subsample(factor, factor)
                self.preview_lbl.configure(image=self._preview_img, text="")
            except tk.TclError:
                self.preview_lbl.configure(image="", text="Pré-visualização\nindisponível\n(use PNG ou GIF)")
        template = fp["template"]
        short = template if len(template) <= 60 else template[:57] + "…"
        self.preview_info.configure(text=f"{fp['name']}\nTemplate: {short}")

    def use_selected_finger(self) -> None:
        fp_id = self._selected_fp_id()
        if fp_id is None:
            return
        if self.service.set_current_finger(fp_id):
            self._refresh_fingerprints(fp_id)
            self._schedule_save()

    def copy_template(self) -> None:
        fp = self._selected_fp()
        if fp:
            self.root.clipboard_clear()
            self.root.clipboard_append(fp["template"])

    def add_finger(self) -> None:
        next_id = max((f["id"] for f in self.cfg.fingerprints), default=0) + 1
        fixtures = paths.bundled_fixtures()
        draft = {
            "id": next_id,
            "fingerId": 1,
            "name": f"user-{next_id:02d}-finger",
            "template": _random_template(next_id),
            "fixture": fixtures[(next_id - 1) % len(fixtures)] if fixtures else "",
            "quality": 90,
        }
        FingerDialog(self.root, "Nova digital", draft, self._validate_fp(None), self._save_fp(None))

    def edit_finger(self) -> None:
        fp = self._selected_fp()
        if not fp:
            messagebox.showinfo(APP_NAME, "Selecione uma digital na lista.", parent=self.root)
            return
        FingerDialog(self.root, "Editar digital", dict(fp), self._validate_fp(fp["id"]), self._save_fp(fp["id"]))

    def _validate_fp(self, original_id: int | None) -> Callable[[dict[str, Any]], str | None]:
        def validate(data: dict[str, Any]) -> str | None:
            if any(f["id"] == data["id"] and f["id"] != original_id for f in self.cfg.fingerprints):
                return f"Já existe uma digital com ID {data['id']}."
            if not data["template"]:
                return "O template não pode ficar vazio."
            if not data["name"]:
                return "Informe um nome."
            return None

        return validate

    def _save_fp(self, original_id: int | None) -> Callable[[dict[str, Any]], None]:
        def save(data: dict[str, Any]) -> None:
            fps = self.cfg.fingerprints
            if original_id is None:
                fps.append(data)
            else:
                idx = next(i for i, f in enumerate(fps) if f["id"] == original_id)
                fps[idx] = data
                if self.cfg.current_fingerprint_id == original_id:
                    self.cfg.current_fingerprint_id = data["id"]
            self._refresh_fingerprints(data["id"])
            self._schedule_save()

        return save

    def remove_finger(self) -> None:
        fp = self._selected_fp()
        if not fp:
            return
        if len(self.cfg.fingerprints) == 1:
            messagebox.showwarning(APP_NAME, "É preciso manter pelo menos uma digital.", parent=self.root)
            return
        if not messagebox.askyesno(APP_NAME, f"Remover a digital \"{fp['name']}\"?", parent=self.root):
            return
        self.cfg.fingerprints = [f for f in self.cfg.fingerprints if f["id"] != fp["id"]]
        if self.cfg.current_fingerprint_id == fp["id"]:
            self.cfg.current_fingerprint_id = self.cfg.fingerprints[0]["id"]
        self._refresh_fingerprints(self.cfg.current_fingerprint_id)
        self._schedule_save()

    def reset_fingers(self) -> None:
        if not messagebox.askyesno(APP_NAME, "Substituir a lista pelas 3 digitais padrão?", parent=self.root):
            return
        import copy

        self.cfg.fingerprints = copy.deepcopy(DEFAULT_FINGERPRINTS)
        self.cfg.current_fingerprint_id = 1
        self._refresh_fingerprints(1)
        self._schedule_save()

    # ================================================================ memória
    def _refresh_memory(self) -> None:
        tree = self.mem_tree
        tree.delete(*tree.get_children())
        items = self.service.memory_snapshot()
        for item in items:
            owner = self.service.template_owner(item["template"]) or "—"
            tree.insert("", "end", values=(item["id"], owner, item["template"]))
        self.mem_total_var.set(f"Total: {len(items)}")

    def clear_memory(self) -> None:
        self.service.delete_all_from_memory()

    def load_mocks_to_memory(self) -> None:
        self.service.load_to_memory([{"id": f["id"], "template": f["template"]} for f in self.cfg.fingerprints])

    # ================================================================ log
    def _log_line(self, text: str, tag: str = "") -> None:
        widget = self.log_text
        widget.configure(state="normal")
        widget.insert("end", text + "\n", tag)
        lines = int(widget.index("end-1c").split(".")[0])
        if lines > MAX_LOG_LINES:
            widget.delete("1.0", f"{lines - MAX_LOG_LINES}.0")
        widget.configure(state="disabled")
        if self.autoscroll_var.get():
            widget.see("end")

    def _log_request(self, e: dict[str, Any]) -> None:
        status = e["status"]
        tag = "ok" if status < 300 else ("warn" if status < 500 else "err")
        line = f"{e['time']}  {e['method']:<7} {e['path']}  →  {status}  ({e['ms']} ms)"
        if e.get("message"):
            line += f"  {e['message']}"
        if e.get("error"):
            line += f"  [{e['error']}]"
        self._log_line(line, tag)

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ================================================================ eventos das threads
    def _poll_events(self) -> None:
        refresh_strip = refresh_mem = refresh_fp = False
        try:
            while True:
                event, data = self.events.get_nowait()
                if event == "log":
                    self._log_request(data)
                elif event == "pending":
                    refresh_strip = True
                elif event == "memory":
                    refresh_mem = True
                elif event == "finger":
                    refresh_fp = True
        except queue.Empty:
            pass
        if refresh_fp:
            self._refresh_fingerprints()
            self._schedule_save()
        if refresh_mem:
            self._refresh_memory()
        if refresh_strip:
            self._refresh_capture_strip()
        self.root.after(100, self._poll_events)

    # ================================================================ fechar
    def on_close(self) -> None:
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self._save_now()
        try:
            self.server.stop()
        finally:
            self.root.destroy()


class FingerDialog(tk.Toplevel):
    """Janela modal para criar/editar uma digital simulada."""

    def __init__(
        self,
        master: tk.Misc,
        title: str,
        data: dict[str, Any],
        validate: Callable[[dict[str, Any]], str | None],
        on_save: Callable[[dict[str, Any]], None],
    ) -> None:
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.resizable(True, False)
        self.validate, self.on_save = validate, on_save

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        self.vars: dict[str, tk.StringVar] = {k: tk.StringVar(value=str(v)) for k, v in data.items()}

        def row(r: int, label: str, widget: tk.Widget, extra: tk.Widget | None = None) -> None:
            ttk.Label(body, text=label).grid(row=r, column=0, sticky="w", pady=4)
            widget.grid(row=r, column=1, sticky="ew", padx=8, pady=4)
            if extra is not None:
                extra.grid(row=r, column=2, sticky="w", pady=4)

        row(0, "ID (usado no /identification)", ttk.Spinbox(body, from_=0, to=999999, textvariable=self.vars["id"], width=10))
        row(1, "Finger ID (fingers-id)", ttk.Spinbox(body, from_=0, to=10, textvariable=self.vars["fingerId"], width=10))
        row(2, "Nome", ttk.Entry(body, textvariable=self.vars["name"], width=40))
        row(3, "Qualidade (0–100)", ttk.Spinbox(body, from_=0, to=100, textvariable=self.vars["quality"], width=10))
        row(
            4,
            "Template",
            ttk.Entry(body, textvariable=self.vars["template"], width=60),
            ttk.Button(body, text="Gerar", command=self._gen_template),
        )
        row(
            5,
            "Imagem",
            ttk.Combobox(body, textvariable=self.vars["fixture"], values=paths.bundled_fixtures()),
            ttk.Button(body, text="Procurar…", command=self._browse),
        )
        ttk.Label(
            body,
            text="Use um arquivo da pasta fixtures ou um caminho completo. PNG/GIF têm pré-visualização.",
            style="Muted.TLabel",
        ).grid(row=6, column=1, columnspan=2, sticky="w", padx=8)

        bar = ttk.Frame(body)
        bar.grid(row=7, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(bar, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Salvar", command=self._save).pack(side="right", padx=6)

        self.bind("<Return>", lambda _e: self._save())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()
        self.focus_set()

    def _gen_template(self) -> None:
        try:
            fp_id = int(self.vars["id"].get())
        except ValueError:
            fp_id = 0
        self.vars["template"].set(_random_template(fp_id))

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Escolha a imagem da digital",
            filetypes=[("Imagens", "*.png *.gif *.bmp *.jpg *.jpeg"), ("Todos os arquivos", "*.*")],
        )
        if path:
            self.vars["fixture"].set(path)

    def _save(self) -> None:
        try:
            data = {
                "id": int(self.vars["id"].get()),
                "fingerId": int(self.vars["fingerId"].get()),
                "name": self.vars["name"].get().strip(),
                "template": self.vars["template"].get().strip(),
                "fixture": self.vars["fixture"].get().strip(),
                "quality": max(0, min(100, int(self.vars["quality"].get()))),
            }
        except ValueError:
            messagebox.showerror(APP_NAME, "ID, Finger ID e Qualidade precisam ser números.", parent=self)
            return
        error = self.validate(data)
        if error:
            messagebox.showerror(APP_NAME, error, parent=self)
            return
        self.on_save(data)
        self.destroy()


def _random_template(fp_id: int) -> str:
    return f"AAAAAZCXZDSfe34t4fSIMULATED_FINGERPRINT_TEMPLATE_{fp_id:02d}_{secrets.token_hex(6).upper()}"


def run_gui(host: str | None = None, port: int | None = None) -> int:
    _enable_dpi_awareness()
    cfg = config.load()
    if host:
        cfg.host = host
    if port:
        cfg.port = port
    root = tk.Tk()
    App(root, cfg)
    root.mainloop()
    return 0
