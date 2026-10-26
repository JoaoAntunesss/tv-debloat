"""Janela principal: 1 Ligar · 2 Backup · 3 Pacotes · 4 Ecrã inicial · 5 Final."""
from __future__ import annotations

import platform
import queue
import re
import threading
import time
import traceback
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from core.adb import Adb, AdbError, CliBackend, find_adb, install_platform_tools, port_open
from core.apps import CATALOG, ApkError, validate_apk
from core.guard import CommandRefused
from core.guide import NEXT, PREP_STEPS
from core.packages import GROUP_LABELS, SETUP_WIZARD
from core.profiles import BRANDS, PLATFORMS, get_brand, network_guide
from core.session import MAX_BATCH, DebloatSession, SessionError
from core.workspace import Workspace
from ui.widgets import ScrollFrame, VerifyDialog, safe_grab

APP_DIR = Path(__file__).resolve().parent.parent
IPV4 = re.compile(r"^(\d{1,3})(\.\d{1,3}){3}$")
GROUP_ORDER = [1, 2, 3, 4, 5, 0, 6]
TAB_START, TAB_CONNECT, TAB_BACKUP, TAB_PACKAGES, TAB_HOME, TAB_FINAL, TAB_EXTRAS = range(7)

RULES_TEXT = (
    "O que este programa NUNCA faz: desinstalar (só 'pm disable-user --user 0', reversível com 'pm enable'), "
    "root/bootloader/ROM, executar vários comandos encadeados, ou desativar o que a TV precisa "
    "(entradas HDMI, menu Entradas, comando, teclado, Play Store/Services, ecrã inicial atual)."
)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TV Debloat — limpeza segura de Android TV por ADB")
        self.geometry("1140x860")
        self.minsize(980, 720)
        try:  # tema moderno, opcional (pip install sv-ttk); sem ele fica o aspeto padrão
            import sv_ttk

            sv_ttk.set_theme("light")
        except Exception:
            pass

        self.q: queue.Queue = queue.Queue()
        self._busy = 0
        self.adb: Adb | None = None
        self.session: DebloatSession | None = None
        self.ws: Workspace | None = None
        self.sel: set[str] = set()
        self.bad: set[str] = set()
        self.confirmed_unknown: set[str] = set()
        self.batches: list[list[str]] = []
        self.batch_no = 0
        self.model_info = ""
        self.sleep_fn = time.sleep  # o modo demonstração troca por esperas curtas

        self._build()
        self.after(80, self._poll)
        self._refresh_adb_status()

    # =============================================================== infraestrutura
    def log(self, msg: str) -> None:
        self.q.put(("log", msg))

    def ui(self, fn) -> None:
        self.q.put(("call", fn))

    def bg(self, fn, ok=None) -> None:
        """Corre `fn` numa thread (nunca bloquear o Tk) e chama `ok(resultado)` na thread principal."""
        self._busy += 1
        self._update_busy()

        def work():
            try:
                res = fn()
            except BaseException as e:  # noqa: BLE001 - mostramos tudo ao utilizador
                self.q.put(("err", e, traceback.format_exc()))
                return
            self.q.put(("ok", ok, res))

        threading.Thread(target=work, daemon=True).start()

    def _update_busy(self) -> None:
        if self._busy > 0:
            self.status.set("A trabalhar…")
            self.progress.start(12)
        else:
            self.status.set("Pronto.")
            self.progress.stop()

    def _poll(self) -> None:
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._append_log(item[1])
                elif kind == "call":
                    self._safe(item[1])
                elif kind == "ok":
                    self._busy = max(0, self._busy - 1)
                    self._update_busy()
                    if item[1]:
                        self._safe(lambda cb=item[1], r=item[2]: cb(r))
                elif kind == "err":
                    self._busy = max(0, self._busy - 1)
                    self._update_busy()
                    self._on_error(item[1], item[2])
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _safe(self, fn) -> None:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            self._on_error(e, traceback.format_exc())

    def _append_log(self, msg: str) -> None:
        self.logbox.configure(state="normal")
        self.logbox.insert("end", time.strftime("%H:%M:%S ") + msg + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _on_error(self, e: BaseException, tb: str) -> None:
        self._append_log(f"ERRO: {e}")
        if isinstance(e, CommandRefused):
            title = "Comando recusado"
        elif isinstance(e, (AdbError, SessionError, ApkError)):
            title = "Não consegui fazer isto"
        else:
            title = "Erro inesperado"
            self._append_log(tb)
        messagebox.showerror(title, str(e), parent=self)

    # =============================================================== construção
    def _build(self) -> None:
        ttk.Label(self, text=RULES_TEXT, wraplength=1080, foreground="#8a2be2", justify="left").pack(
            fill="x", padx=10, pady=(8, 2))
        self.next_step = tk.StringVar(value=NEXT["start"])
        banner = tk.Label(self, textvariable=self.next_step, wraplength=1080, justify="left", anchor="w",
                          bg="#e6f4ea", fg="#14532d", padx=10, pady=6, font=("TkDefaultFont", 10, "bold"))
        banner.pack(fill="x", padx=8, pady=(2, 4))
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=4)
        frames = []
        for title in ("0 · Preparar", "1 · Ligar", "2 · Backup", "3 · Pacotes", "4 · Ecrã inicial", "5 · Final",
                      "6 · Anúncios e apps"):
            f = ttk.Frame(self.nb, padding=10)
            self.nb.add(f, text=title)
            frames.append(f)
        self._build_start(frames[TAB_START])
        self._build_connect(frames[TAB_CONNECT])
        self._build_backup(frames[TAB_BACKUP])
        self._build_packages(frames[TAB_PACKAGES])
        self._build_home(frames[TAB_HOME])
        self._build_final(frames[TAB_FINAL])
        self._build_extras(frames[TAB_EXTRAS])
        for i in (TAB_BACKUP, TAB_PACKAGES, TAB_HOME, TAB_FINAL, TAB_EXTRAS):
            self.nb.tab(i, state="disabled")

        logf = ttk.LabelFrame(self, text="O que se está a passar (em linguagem simples)")
        logf.pack(fill="x", padx=8, pady=4)
        self.logbox = scrolledtext.ScrolledText(logf, height=9, state="disabled", wrap="word")
        self.logbox.pack(fill="x", padx=4, pady=4)
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=(0, 6))
        self.status = tk.StringVar(value="Pronto.")
        ttk.Label(bar, textvariable=self.status).pack(side="left")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=160)
        self.progress.pack(side="right")
        self.on_platform_change()  # só agora existem todos os widgets de que depende
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _on_tab_changed(self, _e=None) -> None:
        if self.nb.index("current") == TAB_FINAL and self.session:
            self.set_next(NEXT["final"])

    # ---------------------------------------------------------------- 0 Preparar / 1 Ligar
    def _build_start(self, f) -> None:
        prof = ttk.LabelFrame(f, text="Que TV tens? (escolhe o sistema e a marca)")
        prof.pack(fill="x", pady=(0, 8))
        self._prof_frame = prof
        self.v_platform = tk.StringVar(value=PLATFORMS["androidtv"].name)
        self.v_brand = tk.StringVar()
        ttk.Label(prof, text="Sistema").grid(row=0, column=0, padx=6, pady=4, sticky="w")
        self.cb_platform = ttk.Combobox(prof, textvariable=self.v_platform, state="readonly", width=44,
                                        values=[p.name for p in PLATFORMS.values()])
        self.cb_platform.grid(row=0, column=1, padx=6)
        ttk.Label(prof, text="Marca").grid(row=0, column=2, padx=6, sticky="w")
        self.cb_brand = ttk.Combobox(prof, textvariable=self.v_brand, state="readonly", width=48)
        self.cb_brand.grid(row=0, column=3, padx=6)
        self.profile_msg = tk.StringVar()
        ttk.Label(prof, textvariable=self.profile_msg, wraplength=1040, justify="left",
                  foreground="#8a5a00").grid(row=1, column=0, columnspan=4, padx=6, pady=4, sticky="w")
        self.cb_platform.bind("<<ComboboxSelected>>", self.on_platform_change)
        self.cb_brand.bind("<<ComboboxSelected>>", self.on_brand_change)

        self.prep_frame = ttk.LabelFrame(f, text="Antes de começar — vai marcando o que já fizeste (na própria TV)")
        self.prep_frame.pack(fill="both", expand=True, pady=4)
        self.prep_vars: list[tk.BooleanVar] = []
        self.guide_box = scrolledtext.ScrolledText(f, height=11, wrap="word")
        self.btn_prep_go = ttk.Button(f, text="Já fiz tudo → ir para 1 · Ligar", command=self._go_connect)
        self.btn_prep_go.pack(anchor="w", pady=6)

    def _render_prep(self) -> None:
        for w in self.prep_frame.winfo_children():
            w.destroy()
        self.prep_vars = []
        steps = PREP_STEPS.get(self._platform().key, [])
        if not steps:
            ttk.Label(self.prep_frame, text="Para esta TV não há preparação por ADB: vê o guia abaixo.").pack(
                anchor="w", padx=8, pady=8)
        for i, (title, detail) in enumerate(steps, 1):
            v = tk.BooleanVar(value=False)
            v.trace_add("write", lambda *_a: self._prep_changed())
            self.prep_vars.append(v)
            ttk.Checkbutton(self.prep_frame, text=f"{i}. {title}", variable=v).pack(anchor="w", padx=8, pady=(6, 0))
            ttk.Label(self.prep_frame, text=detail, wraplength=1020, justify="left", foreground="gray").pack(
                anchor="w", padx=34)
        self.btn_prep_go.configure(state="normal" if steps else "disabled")
        self._prep_changed()

    def _prep_changed(self) -> None:
        if self._platform().adb and self.prep_vars and all(v.get() for v in self.prep_vars):
            self.set_next(NEXT["prep_done"])
        elif self._platform().adb:
            self.set_next(NEXT["start"])

    def _go_connect(self) -> None:
        if self.prep_vars and not all(v.get() for v in self.prep_vars):
            if not messagebox.askyesno(
                "Preparação incompleta",
                "Ainda há passos por marcar. Sem a depuração ligada e sem a mesma rede a ligação vai falhar.\n\n"
                "Ir para o separador 1 mesmo assim?", parent=self):
                return
        self.nb.select(TAB_CONNECT)

    def set_next(self, text: str) -> None:
        self.next_step.set(text)

    # ---------------------------------------------------------------- 1 Ligar
    def _build_connect(self, f) -> None:
        self.adb_status = tk.StringVar()
        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Label(row, textvariable=self.adb_status).pack(side="left")
        ttk.Button(row, text="Instalar adb (Google platform-tools)", command=self.install_adb).pack(side="left", padx=10)

        form = ttk.LabelFrame(f, text="A tua TV")
        form.pack(fill="x", pady=8)
        self.v_model = tk.StringVar()
        self.v_ip = tk.StringVar()
        self.v_port = tk.StringVar(value="5555")
        self.v_usb = tk.StringVar()
        for r, (lab, var, hint) in enumerate((
            ("Marca / modelo", self.v_model, "ex.: TCL Smart TV Pro"),
            ("Endereço IP", self.v_ip, "TV > Definições > Rede e Internet > Estado"),
            ("Porta", self.v_port, "5555 (a predefinida)"),
            ("O que está ligado às portas USB da TV?", self.v_usb, "ex.: nada / coluna USB / disco"),
        )):
            ttk.Label(form, text=lab).grid(row=r, column=0, sticky="w", padx=6, pady=3)
            ttk.Entry(form, textvariable=var, width=34).grid(row=r, column=1, padx=6, pady=3)
            ttk.Label(form, text=hint, foreground="gray").grid(row=r, column=2, sticky="w")
        ttk.Label(
            f, wraplength=1050, justify="left",
            text=("Antes de ligar: nas Opções de programador da TV tens de ter a 'Depuração USB / sem fios' ligada, "
                  "e o computador e a TV têm de estar na mesma rede. Algumas TVs cortam a energia às portas USB "
                  "enquanto a depuração está ligada — por isso pergunto o que lá tens (preenche acima)."),
        ).pack(anchor="w")

        pair = ttk.LabelFrame(f, text="Só se a TV pedir código de pareamento (Android 11+, ecrã 'Depuração sem fios')")
        pair.pack(fill="x", pady=8)
        self.v_pair_addr = tk.StringVar()
        self.v_pair_code = tk.StringVar()
        ttk.Label(pair, text="IP:porta de pareamento").grid(row=0, column=0, padx=6, pady=3, sticky="w")
        ttk.Entry(pair, textvariable=self.v_pair_addr, width=24).grid(row=0, column=1)
        ttk.Label(pair, text="Código").grid(row=0, column=2, padx=6)
        ttk.Entry(pair, textvariable=self.v_pair_code, width=10).grid(row=0, column=3)
        ttk.Button(pair, text="Parear", command=self.do_pair).grid(row=0, column=4, padx=8)

        self.conn_msg = tk.StringVar(value="Ainda não estás ligado.")
        self.btn_connect = ttk.Button(f, text="Ligar à TV", command=self.do_connect)
        self.btn_connect.pack(anchor="w", pady=6)
        ttk.Label(f, textvariable=self.conn_msg, foreground="#1a5fb4", wraplength=1050).pack(anchor="w")

    def _platform(self):
        for p in PLATFORMS.values():
            if p.name == self.v_platform.get():
                return p
        return PLATFORMS["androidtv"]

    def on_platform_change(self, _e=None) -> None:
        names = [b.name for b in BRANDS[self._platform().key]]
        self.cb_brand.configure(values=names)
        self.v_brand.set(names[0])
        self.on_brand_change()

    def on_brand_change(self, _e=None) -> None:
        p = self._platform()
        b = get_brand(p.key, self.v_brand.get())
        lines = list(p.notes) + (list(b.notes) if b else [])
        self.profile_msg.set("\n".join("• " + line for line in lines))
        self._render_prep()
        if p.adb:
            self.guide_box.pack_forget()
            self.btn_connect.configure(state="normal")
            if self.conn_msg.get().startswith("Esta TV não permite"):
                self.conn_msg.set("Ainda não estás ligado.")
        else:
            self.set_next(NEXT["no_adb"])
            self.guide_box.configure(state="normal")
            self.guide_box.delete("1.0", "end")
            self.guide_box.insert("end", network_guide(p.key))
            self.guide_box.configure(state="disabled")
            self.guide_box.pack(fill="x", pady=4, after=self.prep_frame)
            self.btn_connect.configure(state="disabled")
            self.conn_msg.set("Esta TV não permite ADB: segue o guia acima (ação ao nível da rede e das definições da TV).")

    def _refresh_adb_status(self) -> None:
        path = find_adb(APP_DIR)
        if path:
            self.adb_status.set(f"✔ adb encontrado: {path}")
        else:
            self.adb_status.set("✘ adb não encontrado — carrega no botão para o instalar automaticamente.")

    def install_adb(self) -> None:
        self.bg(lambda: install_platform_tools(APP_DIR, self.log), ok=lambda p: self._refresh_adb_status())

    def _ensure_adb(self) -> Adb:
        if self.adb is None:
            path = find_adb(APP_DIR)
            if not path:
                raise AdbError("O adb não está instalado. Usa o botão 'Instalar adb'.")
            self.adb = Adb(CliBackend(path), APP_DIR, self.log)
        return self.adb

    def do_pair(self) -> None:
        addr, code = self.v_pair_addr.get().strip(), self.v_pair_code.get().strip()
        if not addr or not code:
            messagebox.showinfo("Pareamento", "Preenche o IP:porta de pareamento e o código que a TV mostra.")
            return

        def work():
            msg = self._ensure_adb().pair(addr, code)
            self.log(msg)
            return msg

        self.bg(work, ok=lambda m: self.conn_msg.set("Pareado. Agora carrega em 'Ligar à TV'."))

    def do_connect(self) -> None:
        ip, port = self.v_ip.get().strip(), self.v_port.get().strip() or "5555"
        if not IPV4.match(ip) or not port.isdigit():
            messagebox.showwarning("Dados em falta", "Escreve um endereço IP válido (ex.: 192.168.1.50) e a porta.")
            return
        if not self.v_usb.get().strip():
            messagebox.showwarning("Portas USB", "Diz o que está ligado às portas USB da TV (podes escrever 'nada').")
            return
        self.conn_msg.set("A ligar… se aparecer 'Permitir depuração USB?' na TV, escolhe Permitir (e 'Permitir sempre').")

        def work():
            adb = self._ensure_adb()
            if not port_open(ip, int(port)):
                raise AdbError(
                    f"A TV não responde em {ip}:{port}. Confirma o IP e que a depuração sem fios está ligada.")
            adb.connect(ip, int(port))
            self.ui(lambda: self.conn_msg.set(
                "Ligado. Aceita o diálogo 'Permitir depuração USB?' no ecrã da TV, se ainda estiver lá."))
            if not adb.wait_authorized(90, on_wait=lambda: self.log("À espera de aprovares o diálogo na TV…")):
                raise AdbError("A TV não autorizou este computador a tempo. Tenta outra vez e carrega em Permitir.")
            props = {}
            for key in ("ro.product.brand", "ro.product.model", "ro.build.version.release", "ro.build.version.sdk"):
                props[key] = adb.shell(f"getprop {key}").strip()
            return props

        self.bg(work, ok=self._connected)

    def _connected(self, props: dict) -> None:
        brand, model = props.get("ro.product.brand", ""), props.get("ro.product.model", "")
        self.model_info = f"{brand} {model}".strip()
        if not self.v_model.get().strip():
            self.v_model.set(self.model_info)
        self.conn_msg.set(
            f"✔ Ligado a {self.model_info or 'TV'} (Android {props.get('ro.build.version.release', '?')}, "
            f"via {self.adb.backend_name}). Passa ao separador 2.")
        self.nb.tab(TAB_BACKUP, state="normal")
        self.nb.select(TAB_BACKUP)
        self.set_next(NEXT["connected"])

    # ---------------------------------------------------------------- 2 Backup
    def _build_backup(self, f) -> None:
        ttk.Label(
            f, wraplength=1050, justify="left",
            text=("Antes de mexer em seja o que for: guardo a lista de pacotes, os desativados, getprop, as definições "
                  "(global/secure/system) e a memória, e crio já o script de restauro. No fim repito a medição "
                  "e mostro-te a tabela antes/depois."),
        ).pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=10)
        self.v_base = tk.StringVar(value=str(Path.home()))
        ttk.Label(row, text="Guardar a pasta 'tv-debloat' em:").pack(side="left")
        ttk.Entry(row, textvariable=self.v_base, width=50).pack(side="left", padx=6)
        ttk.Button(row, text="Escolher…", command=lambda: self.v_base.set(
            filedialog.askdirectory(parent=self, initialdir=self.v_base.get()) or self.v_base.get())).pack(side="left")
        ttk.Button(f, text="Fazer backup e medir a memória", command=self.do_backup).pack(anchor="w", pady=4)
        self.backup_msg = tk.StringVar()
        ttk.Label(f, textvariable=self.backup_msg, wraplength=1050, justify="left", foreground="#1a5fb4").pack(anchor="w", pady=6)

    def do_backup(self) -> None:
        if not self.adb:
            return
        base = Path(self.v_base.get()).expanduser()
        target = f"{self.adb.host}:{self.adb.port}"
        platform_ = self._platform()
        brand = get_brand(platform_.key, self.v_brand.get())
        self.ws = Workspace(base, target)
        self.session = DebloatSession(self.adb, self.ws, log=self.log, sleep=self.sleep_fn,
                                      brand=brand, platform=platform_)

        # Ler as variáveis do Tk aqui (thread principal): o Tk não é seguro a partir de threads de fundo.
        header = {
            "Sistema": platform_.name,
            "Marca": brand.name if brand else "?",
            "TV": self.v_model.get().strip() or self.model_info or "?",
            "IP": target,
            "Portas USB": self.v_usb.get().strip(),
            "Computador": platform.platform(),
        }

        def work():
            self.ws.log_header(header)
            bdir = self.session.backup()
            self.session.scan()
            return bdir

        self.bg(work, ok=self._backup_done)

    def _backup_done(self, bdir: Path) -> None:
        m = self.session.mem_before
        mem = (f"RAM total {m.get('Total', 0) / 1024:.0f} MB, livre {m.get('Free', 0) / 1024:.0f} MB, "
               f"usada {m.get('Used', 0) / 1024:.0f} MB." if m else "Não consegui ler a memória.")
        self.backup_msg.set(
            f"✔ Backup em {bdir}\nScript de restauro: {self.ws.restore_path}\nMemória antes: {mem}")
        p = self._platform()
        for i in (TAB_PACKAGES, TAB_FINAL, TAB_EXTRAS) + ((TAB_HOME,) if p.launcher_swap else ()):
            self.nb.tab(i, state="normal")
        if not p.launcher_swap:
            self.log(f"{p.name}: o ecrã inicial não se troca, por isso o separador 4 fica desativado.")
        dns_state = "normal" if p.dns_on_device else "disabled"
        for b in self.dns_buttons:
            b.configure(state=dns_state)
        self.dns_note.set("" if p.dns_on_device else
                          f"Em {p.name} o DNS não se muda por ADB: usa um DNS que filtra no router (NextDNS, AdGuard Home, Pi-hole).")
        self.cb_platform.configure(state="disabled")
        self.cb_brand.configure(state="disabled")
        self.refresh_tree()
        self.nb.select(TAB_PACKAGES)
        self.set_next(NEXT["backup_done"])

    # ---------------------------------------------------------------- 3 Pacotes
    def _build_packages(self, f) -> None:
        tb = ttk.Frame(f)
        tb.pack(fill="x")
        for text, cmd in (
            ("Procurar pacotes de novo", self.rescan),
            ("Importar debloat.txt…", self.import_list),
            ("Marcar grupos 1 e 2", self.mark_12),
            ("Checklist do grupo 5…", self.open_checklist5),
            ("Limpar seleção", self.clear_sel),
        ):
            ttk.Button(tb, text=text, command=cmd).pack(side="left", padx=3)

        mid = ttk.PanedWindow(f, orient="horizontal")
        mid.pack(fill="both", expand=True, pady=6)
        left = ttk.Frame(mid)
        mid.add(left, weight=3)
        self.tree = ttk.Treeview(left, columns=("sel", "why"), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Pacote")
        self.tree.heading("sel", text="Desativar")
        self.tree.heading("why", text="Porquê")
        self.tree.column("#0", width=380)
        self.tree.column("sel", width=90, anchor="center")
        self.tree.column("why", width=300)
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        right = ttk.LabelFrame(mid, text="Detalhes")
        mid.add(right, weight=2)
        self.detail = tk.StringVar(value="Seleciona um pacote.")
        ttk.Label(right, textvariable=self.detail, wraplength=330, justify="left").pack(anchor="w", padx=6, pady=6)
        ttk.Button(right, text="Ver o que faz (dumpsys package)", command=self.show_dumpsys).pack(anchor="w", padx=6)
        ttk.Label(
            right, wraplength=330, foreground="gray", justify="left",
            text=("🔒 = intocável (a TV precisa). Clica na coluna 'Desativar' para marcar ☐/☑. "
                  "Grupo 5 depende de ti: usa a checklist. Pacotes não identificados (grupo ?) "
                  "são inspecionados antes de se desativar."),
        ).pack(anchor="w", padx=6, pady=10)

        bot = ttk.Frame(f)
        bot.pack(fill="x")
        ttk.Label(bot, text=f"Pacotes por lote (máx. {MAX_BATCH}):").pack(side="left")
        self.batch_size = tk.IntVar(value=MAX_BATCH)
        ttk.Spinbox(bot, from_=1, to=MAX_BATCH, width=4, textvariable=self.batch_size).pack(side="left", padx=4)
        self.one_by_one = tk.BooleanVar(value=False)
        ttk.Checkbutton(bot, text="Um a um (mais lento, mais seguro)", variable=self.one_by_one).pack(side="left", padx=10)
        self.sel_count = tk.StringVar(value="0 selecionados")
        ttk.Label(bot, textvariable=self.sel_count).pack(side="left", padx=10)
        ttk.Button(bot, text="Desativar selecionados (em lotes, com verificação)", command=self.start_disable).pack(side="right")

    def _mark(self, info) -> str:
        if info.verdict.group == 6:
            return "🔒"
        if info.disabled:
            return "✓ off"
        if info.name in self.bad:
            return "⚠ partiu"
        return "☑" if info.name in self.sel else "☐"

    def refresh_tree(self) -> None:
        if not self.session:
            return
        opened = {i for i in self.tree.get_children() if self.tk.getboolean(self.tree.item(i, "open"))}
        opened = opened or {"grp1", "grp2"}
        self.tree.delete(*self.tree.get_children())
        groups: dict[int, list] = {}
        for info in sorted(self.session.infos.values(), key=lambda i: i.name):
            if info.system:
                groups.setdefault(info.verdict.group, []).append(info)
        for g in GROUP_ORDER:
            items = groups.get(g, [])
            label = f"Grupo {g if g else '?'} — {GROUP_LABELS[g]} ({len(items)})"
            parent = self.tree.insert("", "end", iid=f"grp{g}", text=label, open=f"grp{g}" in opened)
            for info in items:
                self.tree.insert(parent, "end", iid=info.name, text=info.name,
                                 values=(self._mark(info), info.verdict.reason))
        self.sel_count.set(f"{len(self.sel)} selecionados")

    def rescan(self) -> None:
        self.bg(self.session.scan, ok=lambda _r: self.refresh_tree())

    def on_tree_click(self, event) -> None:
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        iid = self.tree.identify_row(event.y)
        info = self.session.infos.get(iid) if self.session else None
        if not info or info.verdict.group == 6 or info.disabled or iid in self.bad:
            return
        if iid in self.sel:
            self.sel.discard(iid)
        else:
            self.sel.add(iid)
        self.tree.set(iid, "sel", self._mark(info))
        self.sel_count.set(f"{len(self.sel)} selecionados")

    def on_tree_select(self, _e=None) -> None:
        sel = self.tree.selection()
        info = self.session.infos.get(sel[0]) if (sel and self.session) else None
        if not info:
            return
        v = info.verdict
        self.detail.set(
            f"{info.name}\n\nGrupo: {v.group if v.group else '?'} — {GROUP_LABELS[v.group]}\n"
            f"O que é: {v.description}\nPorquê: {v.reason}\nFicheiro: {info.path or '—'}\n"
            f"Estado: {'desativado' if info.disabled else 'ativo'}")

    def show_dumpsys(self) -> None:
        sel = self.tree.selection()
        if not sel or sel[0] not in (self.session.infos if self.session else {}):
            return
        pkg = sel[0]

        def show(res):
            risks, summary = res
            txt = summary + ("\n\n⚠ CUIDADO: " + "; ".join(risks) if risks else "\n\nSem sinais de serviço essencial.")
            messagebox.showinfo(f"dumpsys package {pkg}", txt, parent=self)

        self.bg(lambda: self.session.inspect(pkg), ok=show)

    def mark_12(self) -> None:
        for info in self.session.infos.values():
            if info.system and info.verdict.group in (1, 2) and not info.disabled and info.name not in self.bad:
                self.sel.add(info.name)
        self.refresh_tree()

    def clear_sel(self) -> None:
        self.sel.clear()
        self.refresh_tree()

    def import_list(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Escolhe um debloat.txt (um pacote por linha)")
        if not path:
            return
        wanted = []
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.split("#")[0].strip()
            if line:
                wanted.append(line.replace("package:", "").split()[0])
        added = skipped = 0
        for name in wanted:
            info = self.session.infos.get(name)
            if info and info.system and info.verdict.group != 6 and not info.disabled:
                self.sel.add(name)
                added += 1
            else:
                skipped += 1
        self.log(f"Lista importada: {added} pacotes marcados; {skipped} ignorados "
                 f"(não existem nesta TV, já estão desativados ou são intocáveis).")
        self.refresh_tree()

    def open_checklist5(self) -> None:
        items = [i for i in self.session.infos.values()
                 if i.system and i.verdict.group == 5 and not i.disabled and i.name not in self.bad]
        if not items:
            messagebox.showinfo("Grupo 5", "Não há pacotes do grupo 5 por decidir.", parent=self)
            return
        dlg = tk.Toplevel(self)
        dlg.title("Checklist: o que queres MANTER?")
        dlg.transient(self)
        ttk.Label(dlg, wraplength=560, justify="left", text=(
            "Estas apps/serviços dependem de ti (streaming, assistente de voz, Chromecast, espelhamento, "
            "atualizações). Deixa marcado o que usas ou queres manter. "
            "Só desativo o que desmarcares.")).pack(padx=10, pady=8)
        sf = ScrollFrame(dlg, height=300)
        sf.pack(fill="both", expand=True, padx=10)
        vars_ = {}
        for info in sorted(items, key=lambda i: i.name):
            v = tk.BooleanVar(value=info.name not in self.sel)
            vars_[info.name] = v
            ttk.Checkbutton(sf.inner, text=f"{info.name} — {info.verdict.reason}", variable=v).pack(anchor="w")

        def ok():
            for name, v in vars_.items():
                (self.sel.discard if v.get() else self.sel.add)(name)
            dlg.destroy()
            self.refresh_tree()

        ttk.Button(dlg, text="Aplicar", command=ok).pack(pady=8)
        dlg.after(100, lambda: safe_grab(dlg))

    # ---- desativar em lotes
    def start_disable(self) -> None:
        chosen = [n for n in sorted(self.sel)
                  if n in self.session.infos and self.session.infos[n].verdict.group != 6
                  and not self.session.infos[n].disabled]
        if not chosen:
            messagebox.showinfo("Nada selecionado", "Marca primeiro alguns pacotes.", parent=self)
            return
        unknown = [n for n in chosen if self.session.infos[n].verdict.group == 0
                   and n not in self.confirmed_unknown]
        if unknown:
            def work():
                return {n: self.session.inspect(n) for n in unknown}

            self.bg(work, ok=lambda res: self._after_inspect(chosen, res))
        else:
            self._confirm_plan(chosen)

    def _after_inspect(self, chosen, results) -> None:
        risky = {n: r for n, (r, _s) in results.items() if r}
        if risky:
            messagebox.showwarning(
                "Pacotes que a TV pode precisar",
                "Retirei da seleção (o dumpsys mostra serviços essenciais):\n\n"
                + "\n".join(f"• {n}: {', '.join(r)}" for n, r in risky.items()), parent=self)
            for n in risky:
                self.sel.discard(n)
                self.bad.add(n)
            chosen = [n for n in chosen if n not in risky]
        safe = {n: s for n, (r, s) in results.items() if not r}
        if safe:
            text = "\n\n".join(f"{n}\n{s}" for n, s in safe.items())
            if messagebox.askyesno(
                "Pacotes não identificados",
                "Não consigo dizer só pelo nome o que estes pacotes fazem. Isto é o que declaram:\n\n"
                f"{text[:2500]}\n\nSem sinais de serviço essencial, mas a decisão é tua. Desativar mesmo assim?",
                parent=self):
                self.confirmed_unknown |= set(safe)
            else:
                chosen = [n for n in chosen if n not in safe]
                for n in safe:
                    self.sel.discard(n)
        self.refresh_tree()
        if chosen:
            self._confirm_plan(chosen)

    def _confirm_plan(self, chosen) -> None:
        size = 1 if self.one_by_one.get() else max(1, min(MAX_BATCH, int(self.batch_size.get() or MAX_BATCH)))
        batches = [chosen[i:i + size] for i in range(0, len(chosen), size)]
        if not messagebox.askyesno(
            "Confirmar",
            f"Vou desativar {len(chosen)} pacotes em {len(batches)} lote(s) de até {size}.\n\n"
            "• Nada é desinstalado; cada um desfaz-se com 'pm enable'.\n"
            "• Depois de cada lote paro e mostro-te o ecrã da TV para confirmares.\n\nContinuar?",
            parent=self):
            return
        self.batches = batches
        self.batch_no = 0
        self._run_next()

    def _run_next(self) -> None:
        if not self.batches:
            self.log("Fila concluída.")
            self.set_next(NEXT["queue_done"])
            self.rescan()
            return
        batch = self.batches.pop(0)
        self.batch_no += 1
        label = f"Lote {self.batch_no}" + (" (um a um)" if len(batch) == 1 else "")
        self.bg(lambda: self.session.disable_batch(batch, label, self.confirmed_unknown),
                ok=lambda res: self._batch_done(res))

    def _batch_done(self, res) -> None:
        for p in res.ok:
            self.sel.discard(p)
        self.refresh_tree()
        if res.failed:
            p, out = res.failed[0]
            messagebox.showwarning("Um pacote não desativou", f"{p}\n{out}\n\nPara a fila.", parent=self)
            self.batches = []
        if not res.ok:
            return
        self.set_next(NEXT["verify"])
        VerifyDialog(
            self, res.ok, mode="decide",
            on_ok=lambda: self._run_next(),
            on_bad=lambda: self._batch_bad(res.ok),
            on_abort=lambda: self._batch_abort(res.ok),
        )

    def _batch_bad(self, pkgs) -> None:
        def after(_):
            if len(pkgs) == 1:
                self.bad.add(pkgs[0])
                self.log(f"{pkgs[0]} era o culpado: fica reativado e marcado como 'partiu'.")
                self.ws.log(f"- ⚠ `{pkgs[0]}` partiu algo; ficou reativado.")
            else:
                self.log("Reativei o lote. Vou testá-los um a um para descobrir qual partiu.")
                self.batches = [[p] for p in pkgs] + self.batches
            self.refresh_tree()
            self._run_next()

        self.bg(lambda: self.session.revert(pkgs), ok=after)

    def _batch_abort(self, pkgs) -> None:
        self.batches = []
        self.log("Fechaste a verificação sem decidir. A fila parou; os pacotes deste lote ficam desativados — "
                 "verifica a TV e usa 'Restaurar tudo' no separador 5 se for preciso.")

    # ---------------------------------------------------------------- 4 Ecrã inicial
    def _build_home(self, f) -> None:
        ttk.Label(f, wraplength=1050, justify="left", text=(
            "O ecrã inicial da Google TV está cheio de anúncios e recomendações. Troco-o pelo FLauncher "
            "(grátis, código aberto, só uma grelha de apps). Só desativo o launcher original quando o "
            "FLauncher já for o predefinido.")).pack(anchor="w")
        self.home_msg = tk.StringVar(value="")
        steps = ttk.Frame(f)
        steps.pack(fill="x", pady=8)
        ttk.Label(steps, text="1. Instala o FLauncher na TV (Play Store) e depois:").grid(row=0, column=0, sticky="w")
        ttk.Button(steps, text="Verificar se está instalado", command=self.home_check).grid(row=0, column=1, padx=8, pady=3)
        ttk.Label(steps, text="2. Ver quem reclama o ecrã inicial:").grid(row=1, column=0, sticky="w")
        ttk.Button(steps, text="Listar", command=self.home_list).grid(row=1, column=1, padx=8, pady=3)
        ttk.Label(steps, text="3. Definir o FLauncher como predefinido:").grid(row=2, column=0, sticky="w")
        ttk.Button(steps, text="Definir (ou escolhe na TV)", command=self.home_set).grid(row=2, column=1, padx=8, pady=3)
        ttk.Label(steps, text="4. Reiniciar e ver se o FLauncher se mantém:").grid(row=3, column=0, sticky="w")
        ttk.Button(steps, text="Reiniciar e verificar", command=self.home_reboot).grid(row=3, column=1, padx=8, pady=3)
        ttk.Label(steps, text="   Se o assistente de configuração roubar o ecrã:").grid(row=4, column=0, sticky="w")
        ttk.Button(steps, text="Desativar assistente", command=self.home_wizard).grid(row=4, column=1, padx=8, pady=3)
        ttk.Label(steps, text="5. Desativar o launcher original:").grid(row=5, column=0, sticky="w")
        ttk.Button(steps, text="Desativar launcher original", command=self.home_stock).grid(row=5, column=1, padx=8, pady=3)
        self.home_list_box = tk.Listbox(f, height=6)
        self.home_list_box.pack(fill="x", pady=6)
        ttk.Label(f, textvariable=self.home_msg, wraplength=1050, foreground="#1a5fb4").pack(anchor="w")
        ttk.Label(f, foreground="gray", wraplength=1050, text=(
            "Nota Android 14: se instalares um APK por adb e ficar pendurado, é porque espera uma confirmação "
            "na TV. Instala o FLauncher pela Play Store, que é mais simples.")).pack(anchor="w", pady=6)
        self._home_components: list[str] = []

    def home_check(self) -> None:
        def done(p):
            self.home_msg.set(f"✔ FLauncher instalado ({p})." if p else
                              "✘ Ainda não encontro o FLauncher. Instala-o na Play Store da TV e tenta de novo.")
            if p:
                self.bg(self.session.scan, ok=lambda _r: self.refresh_tree())

        self.bg(self.session.find_flauncher, ok=done)

    def home_list(self) -> None:
        def work():
            return self.session.query_home(), self.session.default_home()

        def done(res):
            comps, default = res
            self._home_components = [c for _p, c in comps]
            self.home_list_box.delete(0, "end")
            for pkg, comp in comps:
                self.home_list_box.insert("end", f"{comp}" + ("   ← predefinido agora" if pkg == default else ""))
            self.home_msg.set("Estes são os ecrãs iniciais instalados. O FLauncher deve aparecer na lista.")

        self.bg(work, ok=done)

    def _flauncher_component(self) -> str | None:
        idx = self.home_list_box.curselection()
        if idx:
            return self._home_components[idx[0]]
        for c in self._home_components:
            if "flauncher" in c.lower():
                return c
        return None

    def home_set(self) -> None:
        comp = self._flauncher_component()
        if not comp or "/" not in comp:
            messagebox.showinfo(
                "FLauncher", "Primeiro carrega em 'Listar' para o FLauncher aparecer. Se não conseguir ser definido "
                "por aqui, carrega em Home no comando e escolhe o FLauncher na TV ('Sempre').", parent=self)
            return

        def done(cur):
            ok = bool(cur and "flauncher" in cur.lower())
            self.home_msg.set("✔ O FLauncher é agora o predefinido." if ok else
                              f"O predefinido continua a ser {cur}. Escolhe o FLauncher na TV ao carregar em Home.")
            VerifyDialog(self, [], mode="view", title="Ecrã inicial atual")

        self.bg(lambda: self.session.set_home(comp), ok=done)

    def home_reboot(self) -> None:
        def work():
            self.session.reboot_and_wait()
            self.session.press("KEYCODE_HOME")
            self.session.sleep(2.5)
            return self.session.default_home(), self.session.focus()

        def done(res):
            cur, focus = res
            ok = bool(cur and "flauncher" in cur.lower())
            wizard = bool(focus.package and "setupwraith" in focus.package)
            if ok and not wizard:
                self.home_msg.set(f"✔ Depois do reinício o ecrã inicial continua a ser o FLauncher ({focus.package}).")
            else:
                self.home_msg.set(f"✘ Depois do reinício o ecrã é '{focus.package}' (predefinido: {cur}). "
                                  "Se for o assistente de configuração, usa 'Desativar assistente'.")
            VerifyDialog(self, [], mode="view", title="Depois do reinício")

        self.bg(work, ok=done)

    def _unlock_and_disable(self, pkgs_fn, label, then=None) -> None:
        def work():
            self.session.unlock_launcher_disable()
            pkgs = [p for p in pkgs_fn() if p in self.session.infos]
            if not pkgs:
                raise SessionError("Não encontrei esse pacote nesta TV.")
            return self.session.disable_batch(pkgs, label)

        def done(res):
            self.refresh_tree()
            if res.failed:
                messagebox.showwarning("Não desativou", f"{res.failed[0][0]}\n{res.failed[0][1]}", parent=self)
            if res.ok:
                VerifyDialog(self, res.ok, mode="decide",
                             on_ok=lambda: self.home_msg.set("✔ Confirmado."),
                             on_bad=lambda: self.bg(lambda: self.session.revert(res.ok), ok=lambda _r: self.refresh_tree()),
                             on_abort=lambda: None, title=label)

        self.bg(work, ok=done)

    def home_wizard(self) -> None:
        self._unlock_and_disable(lambda: [SETUP_WIZARD], "Assistente de configuração")

    def home_stock(self) -> None:
        if not messagebox.askyesno(
            "Launcher original",
            "O FLauncher já é o predefinido e o ecrã continua a funcionar depois do reinício?\n\n"
            "Só então desativo o launcher original (fica reversível com 'pm enable').", parent=self):
            return
        self._unlock_and_disable(self.session.stock_launchers_present, "Launcher original")

    # ---------------------------------------------------------------- 5 Final
    def _build_final(self, f) -> None:
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        for text, cmd in (
            ("e) Animações a metade", self.do_speedups),
            ("f) Limpar caches", self.do_trim),
            ("g) Reiniciar e medir", self.do_final_measure),
            ("Gerar relatório", self.do_report),
        ):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=4)
        ttk.Button(bar, text="Restaurar tudo", command=self.do_restore).pack(side="right", padx=4)
        self.report = scrolledtext.ScrolledText(f, height=22, wrap="word")
        self.report.pack(fill="both", expand=True, pady=8)
        ttk.Label(f, foreground="gray", wraplength=1050, text=(
            "Dica: depois de tudo, se algo ligado às portas USB da TV deixou de funcionar, "
            "desliga a depuração USB nas Opções de programador.")).pack(anchor="w")

    def do_speedups(self) -> None:
        self.bg(self.session.apply_speedups, ok=lambda _r: self.log("Animações a 0.5 (valores originais guardados)."))

    def do_trim(self) -> None:
        self.bg(self.session.trim_caches, ok=lambda _r: self.log("Caches limpas."))

    def do_final_measure(self) -> None:
        def work():
            self.session.reboot_and_wait()
            self.session.measure_after()
            return self.session.final_report()

        def done(text):
            self._show_report(text)
            VerifyDialog(self, [], mode="view", title="Depois do reinício final")

        self.bg(work, ok=done)

    def do_report(self) -> None:
        def work():
            if not self.session.mem_after:
                self.session.measure_after()
            return self.session.final_report()

        self.bg(work, ok=self._show_report)

    def _show_report(self, text: str) -> None:
        self.report.delete("1.0", "end")
        self.report.insert("end", text)
        self.ws.log("\n" + text)
        self.log(f"Relatório guardado em {self.ws.log_path}")

    # ---------------------------------------------------------------- 6 Anúncios e apps
    def _build_extras(self, f) -> None:
        ttk.Label(f, wraplength=1050, justify="left", text=(
            "O que realmente funciona contra anúncios:\n"
            "• YouTube: o DNS não resolve (os anúncios vêm dos mesmos servidores do vídeo) e o AdGuard para "
            "Android TV também não os bloqueia. O caminho é um cliente alternativo, o SmartTube (abaixo).\n"
            "• Streaming e telemetria: um DNS que filtra corta rastreio e parte dos anúncios, mas não os "
            "anúncios que vêm dentro do próprio stream.\n"
            "• Anúncios do ecrã inicial: resolvem-se com o debloat e com o FLauncher (separadores 3 e 4)."
        )).pack(anchor="w")

        dns = ttk.LabelFrame(f, text="DNS que filtra anúncios e rastreio (DNS privado do Android 9+)")
        dns.pack(fill="x", pady=8)
        self.dns_presets = {"AdGuard DNS (anúncios e rastreio)": "dns.adguard-dns.com", "Outro (escrever)": ""}
        self.v_dns_preset = tk.StringVar(value="AdGuard DNS (anúncios e rastreio)")
        self.v_dns_custom = tk.StringVar()
        ttk.Combobox(dns, textvariable=self.v_dns_preset, values=list(self.dns_presets), state="readonly",
                     width=36).grid(row=0, column=0, padx=6, pady=6)
        ttk.Label(dns, text="Servidor próprio:").grid(row=0, column=1, padx=(10, 2))
        ttk.Entry(dns, textvariable=self.v_dns_custom, width=34).grid(row=0, column=2)
        ttk.Label(dns, text="ex.: abc123.dns.nextdns.io", foreground="gray").grid(row=0, column=3, padx=6)
        b1 = ttk.Button(dns, text="Aplicar DNS", command=self.do_dns_apply)
        b2 = ttk.Button(dns, text="Repor DNS (automático)", command=self.do_dns_reset)
        b1.grid(row=1, column=0, padx=6, pady=4, sticky="w")
        b2.grid(row=1, column=1, columnspan=2, padx=6, pady=4, sticky="w")
        self.dns_buttons = [b1, b2]
        self.dns_note = tk.StringVar()
        ttk.Label(dns, textvariable=self.dns_note, wraplength=1000, foreground="#8a5a00").grid(
            row=2, column=0, columnspan=4, padx=6, sticky="w")
        ttk.Label(dns, wraplength=1000, foreground="gray", justify="left", text=(
            "Depois de aplicar, confirma que o YouTube e a Netflix ainda carregam. Se a TV ficar sem internet "
            "(há redes que bloqueiam DNS privado), repõe. Nem todas as TVs respeitam esta definição.")).grid(
            row=3, column=0, columnspan=4, padx=6, pady=(0, 6), sticky="w")

        apps = ttk.LabelFrame(f, text="Apps")
        apps.pack(fill="both", expand=True, pady=4)
        self.app_list = tk.Listbox(apps, height=6, exportselection=False)
        for a in CATALOG:
            self.app_list.insert("end", f"{a.name} — {a.purpose}")
        self.app_list.pack(fill="x", padx=6, pady=6)
        self.app_list.bind("<<ListboxSelect>>", self.on_app_select)
        self.app_detail = tk.StringVar(value="Seleciona uma app para ver como instalar.")
        ttk.Label(apps, textvariable=self.app_detail, wraplength=1040, justify="left").pack(anchor="w", padx=6)
        self.app_warn = tk.StringVar()
        ttk.Label(apps, textvariable=self.app_warn, wraplength=1040, justify="left",
                  foreground="#a40000").pack(anchor="w", padx=6, pady=4)
        row = ttk.Frame(apps)
        row.pack(fill="x", padx=6, pady=6)
        self.btn_app_page = ttk.Button(row, text="Abrir a página oficial", command=self.open_app_page, state="disabled")
        self.btn_app_page.pack(side="left")
        ttk.Button(row, text="Instalar um APK que já descarreguei…", command=self.install_apk_dialog).pack(
            side="left", padx=10)
        ttk.Label(apps, foreground="gray", wraplength=1040, text=(
            "Nunca descarrego nem instalo nada sozinho: tu descarregas o APK de uma fonte oficial e aqui "
            "vês o tamanho e o SHA-256 antes de confirmar. Para remover uma app usa as Definições da TV "
            "(este programa nunca desinstala).")).pack(anchor="w", padx=6, pady=(0, 6))

    def _selected_app(self):
        idx = self.app_list.curselection()
        return CATALOG[idx[0]] if idx else None

    def on_app_select(self, _e=None) -> None:
        a = self._selected_app()
        if not a:
            return
        self.app_detail.set(f"{a.name}: {a.how}")
        self.app_warn.set(("⚠ " + a.warning) if a.warning else "")
        self.btn_app_page.configure(state="normal" if a.page_url else "disabled")

    def open_app_page(self) -> None:
        a = self._selected_app()
        if a and a.page_url:
            webbrowser.open(a.page_url)

    def install_apk_dialog(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Escolhe o APK a instalar na TV",
                                          filetypes=[("APK", "*.apk")])
        if not path:
            return
        a = self._selected_app()
        warn = f"\n\n⚠ {a.warning}" if a and a.warning else ""

        def confirm(info):
            ok = messagebox.askyesno(
                "Instalar na TV?",
                f"Ficheiro: {info['name']}\nTamanho: {info['size'] / 1048576:.1f} MB\nSHA-256:\n{info['sha256']}\n\n"
                "Confirma que o descarregaste do site oficial e, se o projeto publicar o SHA-256, que coincide."
                f"{warn}\n\nInstalar?", parent=self)
            if ok:
                self.bg(lambda: self.session.install_apk(path),
                        ok=lambda sha: self.log(f"✔ {info['name']} instalada (SHA-256 {sha[:12]}…). Abre-a na TV."))

        self.bg(lambda: validate_apk(path), ok=confirm)

    def _dns_host(self) -> str:
        return (self.v_dns_custom.get().strip() or self.dns_presets.get(self.v_dns_preset.get(), "")).lower()

    def do_dns_apply(self) -> None:
        host = self._dns_host()
        if not host:
            messagebox.showinfo("DNS", "Escolhe um servidor ou escreve o teu (ex.: abc123.dns.nextdns.io).", parent=self)
            return
        if not messagebox.askyesno(
            "Aplicar DNS",
            f"Vou usar o DNS privado '{host}' nesta TV (reversível: 'Repor DNS' ou restaurar tudo). Continuar?",
            parent=self):
            return

        def done(_r):
            VerifyDialog(
                self, [], mode="decide", title="DNS aplicado",
                ok_text="✔ A TV continua com internet",
                bad_text="✘ Sem internet / algo partiu — repor DNS",
                on_ok=lambda: self.log("DNS mantido."),
                on_bad=lambda: self.bg(self.session.reset_private_dns, ok=lambda _x: self.log("DNS reposto.")),
                on_abort=lambda: self.log("Verificação do DNS fechada sem decidir; usa 'Repor DNS' se for preciso."))

        self.bg(lambda: self.session.set_private_dns(host), ok=done)

    def do_dns_reset(self) -> None:
        self.bg(self.session.reset_private_dns, ok=lambda _r: self.log("DNS privado reposto em automático."))

    def do_restore(self) -> None:
        if not messagebox.askyesno(
            "Restaurar tudo",
            "Vou reativar todos os pacotes de disabled.txt e repor as animações originais. Continuar?", parent=self):
            return
        self.bg(self.session.restore_all, ok=lambda pk: (self.log(f"{len(pk)} pacotes reativados."), self.refresh_tree()))
