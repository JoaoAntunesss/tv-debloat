"""Widgets auxiliares e o diálogo de verificação no ecrã da TV (regra 4)."""
from __future__ import annotations

import base64
import tkinter as tk
from tkinter import ttk


class ScrollFrame(ttk.Frame):
    def __init__(self, parent, height=320):
        super().__init__(parent)
        canvas = tk.Canvas(self, height=height, highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.inner = ttk.Frame(canvas)
        self.inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.inner, anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")


def safe_grab(win) -> None:
    """grab_set falha em alguns gestores de janelas se a janela ainda não está visível."""
    try:
        if win.winfo_exists():
            win.grab_set()
    except tk.TclError:
        pass


def png_to_photo(path, max_width=720):
    """Carrega um PNG para o Tk (8.6 lê PNG nativamente) e reduz se for grande."""
    with open(path, "rb") as f:
        img = tk.PhotoImage(data=base64.b64encode(f.read()))
    factor = max(1, -(-img.width() // max_width))  # ceil
    return img.subsample(factor, factor) if factor > 1 else img


class VerifyDialog(tk.Toplevel):
    """Mostra o ecrã da TV, deixa carregar nas teclas do comando e pede a decisão."""

    KEYS = [
        ("Home", "KEYCODE_HOME"), ("Voltar", "KEYCODE_BACK"),
        ("◀", "KEYCODE_DPAD_LEFT"), ("▲", "KEYCODE_DPAD_UP"), ("▼", "KEYCODE_DPAD_DOWN"),
        ("▶", "KEYCODE_DPAD_RIGHT"), ("OK", "KEYCODE_DPAD_CENTER"),
        ("Entradas/Source", "KEYCODE_TV_INPUT"), ("HDMI 1", "KEYCODE_TV_INPUT_HDMI_1"),
    ]

    def __init__(self, app, packages, mode="decide", on_ok=None, on_bad=None, on_abort=None,
                 title="Verificar a TV", ok_text="✔ Está tudo bem — continuar",
                 bad_text="✘ Algo partiu — reativar estes pacotes"):
        super().__init__(app)
        self.app, self.packages, self.mode = app, packages, mode
        self.ok_text, self.bad_text = ok_text, bad_text
        self.on_ok, self.on_bad, self.on_abort = on_ok, on_bad, on_abort
        self._img = None
        self._decided = False
        self.title(title)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self._close)

        what = ", ".join(packages) if packages else "—"
        ttk.Label(
            self,
            text=(f"Alterados agora: {what}\n"
                  "Confere no ecrã da TV: o ecrã inicial aparece? O menu Entradas abre? Dá para ir ao HDMI? "
                  "Netflix e YouTube abrem?"),
            wraplength=720, justify="left",
        ).pack(padx=10, pady=(10, 4), anchor="w")

        self.result = tk.StringVar(value="A verificar o ecrã inicial e a tirar uma captura…")
        ttk.Label(self, textvariable=self.result, wraplength=720, foreground="#1a5fb4").pack(padx=10, anchor="w")
        self.img_label = ttk.Label(self, text="(sem imagem ainda)")
        self.img_label.pack(padx=10, pady=6)

        keys = ttk.LabelFrame(self, text="Comando virtual (carrega e vê o ecrã)")
        keys.pack(fill="x", padx=10, pady=4)
        for label, code in self.KEYS:
            ttk.Button(keys, text=label, width=14 if len(label) > 5 else 6,
                       command=lambda c=code: self.do_key(c)).pack(side="left", padx=2, pady=4)
        apps = app.session.streaming_candidates() if app.session else []
        if apps:
            af = ttk.LabelFrame(self, text="Abrir apps")
            af.pack(fill="x", padx=10, pady=4)
            for label, pkg in apps:
                ttk.Button(af, text=f"Abrir {label}", command=lambda p=pkg: self.do_launch(p)).pack(side="left", padx=4, pady=4)
            ttk.Button(af, text="Capturar ecrã", command=self.do_shot).pack(side="left", padx=4)
        else:
            ttk.Button(keys, text="Capturar ecrã", command=self.do_shot).pack(side="left", padx=8)

        man = ttk.LabelFrame(self, text="O que um ecrã não mostra — confirma tu (só se for relevante)")
        man.pack(fill="x", padx=10, pady=4)
        for t in ("O som continua a funcionar", "Os botões do comando respondem", "O teclado no ecrã aparece"):
            ttk.Checkbutton(man, text=t).pack(side="left", padx=8, pady=4)

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=10)
        if mode == "decide":
            ttk.Button(bar, text=self.ok_text, command=self._ok).pack(side="left")
            ttk.Button(bar, text=self.bad_text, command=self._bad).pack(side="left", padx=10)
        else:
            ttk.Button(bar, text="Fechar", command=self._close).pack(side="left")

        self.after(150, self.auto_check)
        self.after(100, lambda: safe_grab(self))

    # --- decisões
    def _ok(self):
        self._decided = True
        self.destroy()
        if self.on_ok:
            self.on_ok()

    def _bad(self):
        self._decided = True
        self.destroy()
        if self.on_bad:
            self.on_bad()

    def _close(self):
        if self._decided:
            return
        self._decided = True
        self.destroy()
        if self.mode == "decide" and self.on_abort:
            self.on_abort()

    # --- ações na TV
    def auto_check(self):
        def work():
            s = self.app.session
            ok, detail = s.check_home()
            return (ok, detail, s.screenshot("auto"))

        self.app.bg(work, ok=self._show)

    def do_key(self, code):
        def work():
            s = self.app.session
            s.press(code)
            s.sleep(1.5)
            return (None, f"Tecla {code} enviada.", s.screenshot("tecla"))

        self.app.bg(work, ok=self._show)

    def do_launch(self, pkg):
        def work():
            s = self.app.session
            ok, detail = s.launch(pkg)
            return (ok, detail, s.screenshot("app"))

        self.app.bg(work, ok=self._show)

    def do_shot(self):
        self.app.bg(lambda: (None, "Captura atualizada.", self.app.session.screenshot("manual")), ok=self._show)

    def _show(self, res):
        if not self.winfo_exists():
            return
        ok, detail, path = res
        mark = "" if ok is None else ("✔ " if ok else "✘ ")
        self.result.set(mark + detail)
        try:
            self._img = png_to_photo(path)
            self.img_label.configure(image=self._img, text="")
        except tk.TclError as e:
            self.img_label.configure(text=f"Não consegui mostrar a imagem ({e}). Ficheiro: {path}")
