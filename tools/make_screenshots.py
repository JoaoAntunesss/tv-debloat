"""Gera as capturas de docs/screenshots/ a partir da janela real, contra a TV simulada.

Precisa de um ecrã X (em Linux sem ambiente gráfico: Xvfb) e de ImageMagick (`import`):
    Xvfb :99 -screen 0 1400x1100x24 &
    DISPLAY=:99 python tools/make_screenshots.py docs/screenshots
"""
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from tkinter import messagebox

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.app import (TAB_BACKUP, TAB_CONNECT, TAB_EXTRAS, TAB_FINAL, TAB_PACKAGES, TAB_START, App)  # noqa: E402
from ui.demo import enable_demo  # noqa: E402
from ui.widgets import VerifyDialog  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
OUT.mkdir(parents=True, exist_ok=True)

# Sem diálogos modais a bloquear: respondemos "sim" ao que o utilizador confirmaria.
messagebox.askyesno = lambda *a, **k: True
messagebox.showinfo = messagebox.showwarning = messagebox.showerror = lambda *a, **k: None


def settle(app, idle_needed=12, timeout=60):
    idle, t0 = 0, time.time()
    while time.time() - t0 < timeout:
        app.update()
        time.sleep(0.05)
        idle = idle + 1 if (app._busy == 0 and app.q.empty()) else 0
        if idle >= idle_needed:
            return
    raise TimeoutError("a interface não assentou")


def shot(app_or_win, name):
    app_or_win.update()
    time.sleep(0.2)
    path = OUT / f"{name}.png"
    subprocess.run(["import", "-window", hex(app_or_win.winfo_id()), str(path)], check=True)
    print("capturada:", path)


def dialogs(app):
    return [w for w in app.winfo_children() if isinstance(w, VerifyDialog)]


app = App()
enable_demo(app)
app.geometry("1140x900+0+0")
settle(app)

# 0 · Preparar (com alguns passos já marcados)
for v in app.prep_vars[:3]:
    v.set(True)
app.nb.select(TAB_START)
shot(app, "0-preparar")
for v in app.prep_vars:
    v.set(True)
settle(app)

# 0b · uma TV sem ADB (Samsung)
app.v_platform.set("Samsung (Tizen)")
app.on_platform_change()
settle(app)
shot(app, "0b-samsung-sem-adb")
app.v_platform.set("Android TV / Google TV")
app.on_platform_change()
app.v_brand.set("TCL")
app.on_brand_change()
for v in app.prep_vars:
    v.set(True)
app.v_model.set("TCL Smart TV Pro")

# 1 · Ligar
app.nb.select(TAB_CONNECT)
shot(app, "1-ligar")
app.do_connect()
settle(app)
app.v_base.set(tempfile.mkdtemp(prefix="tv-debloat-demo-"))

# 2 · Backup
app.do_backup()
settle(app)
app.nb.select(TAB_BACKUP)
shot(app, "2-backup")

# 3 · Pacotes
app.nb.select(TAB_PACKAGES)
app.mark_12()
app.refresh_tree()
app.tree.item("grp1", open=True)
app.tree.item("grp2", open=True)
app.tree.item("grp6", open=True)
app.tree.selection_set("com.exampletv.acr")
app.tree.see("com.exampletv.acr")
app.on_tree_select()
settle(app)
shot(app, "3-pacotes")

# 3b · desativar em lote + ecrã de verificação
app.sel |= {"com.exampletv.cleaner", "com.exampletv.weather"}
app.start_disable()
settle(app)
dlg = dialogs(app)[0]
dlg.geometry("+40+10")
settle(app)
shot(dlg, "4-verificacao")
dlg._ok()  # "Está tudo bem — continuar"
settle(app)

# 6 · Anúncios e apps
app.nb.select(TAB_EXTRAS)
app.app_list.selection_set(0)
app.on_app_select()
shot(app, "6-anuncios-apps")

# 5 · Final (reinicia a TV simulada, mede e gera o relatório)
app.nb.select(TAB_FINAL)
app.do_speedups()
settle(app)
app.do_final_measure()
settle(app)
for d in dialogs(app):
    d._close()
settle(app)
app.nb.select(TAB_FINAL)
shot(app, "5-final")
app.destroy()
