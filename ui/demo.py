"""Modo demonstração: liga a janela a uma TV simulada (sem tocar em nenhuma TV real)."""
from __future__ import annotations

import time
from pathlib import Path

from core.sim import SimBackend


def enable_demo(app) -> None:
    import ui.app as m

    m.find_adb = lambda _d: Path("adb-simulado")
    m.CliBackend = lambda _p: SimBackend()
    m.port_open = lambda _h, _p, timeout=3.0: True
    app.sleep_fn = lambda s: time.sleep(min(s, 0.15))
    app.title(app.title() + " — MODO DEMONSTRAÇÃO (TV simulada)")
    app.v_ip.set("192.168.1.50")
    app.v_usb.set("nada")
    app._refresh_adb_status()
