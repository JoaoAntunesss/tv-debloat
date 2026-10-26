"""Main window: 0 Prepare · 1 Connect · 2 Backup · 3 Packages · 4 Home screen · 5 Final · 6 Ads & apps."""
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

from ui import theme
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
    "What this program NEVER does: uninstall (only 'pm disable-user --user 0', reversible with 'pm enable'), "
    "root/bootloader/ROM, run chained commands, or disable what the TV needs "
    "(HDMI inputs, Inputs menu, remote, keyboard, Play Store/Services, the current home screen)."
)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TV Debloat — safe Android TV cleanup over ADB")
        self.geometry("1280x900")
        self.minsize(1100, 760)
        theme.apply(self)

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
        self.sleep_fn = time.sleep  # demo mode swaps this for short waits

        self._build()
        self.after(80, self._poll)
        self._refresh_adb_status()

    # =============================================================== infrastructure
    def log(self, msg: str) -> None:
        self.q.put(("log", msg))

    def ui(self, fn) -> None:
        self.q.put(("call", fn))

    def bg(self, fn, ok=None) -> None:
        """Run `fn` in a thread (never block Tk) and call `ok(result)` on the main thread."""
        self._busy += 1
        self._update_busy()

        def work():
            try:
                res = fn()
            except BaseException as e:  # noqa: BLE001 - show everything to the user
                self.q.put(("err", e, traceback.format_exc()))
                return
            self.q.put(("ok", ok, res))

        threading.Thread(target=work, daemon=True).start()

    def _update_busy(self) -> None:
        if self._busy > 0:
            self.status.set("Working…")
            self.progress.start(12)
        else:
            self.status.set("Ready.")
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
        self._append_log(f"ERROR: {e}")
        if isinstance(e, CommandRefused):
            title = "Command refused"
        elif isinstance(e, (AdbError, SessionError, ApkError)):
            title = "Could not do this"
        else:
            title = "Unexpected error"
            self._append_log(tb)
        messagebox.showerror(title, str(e), parent=self)

    # =============================================================== construction
    NAV_TITLES = ("Prepare", "Connect", "Backup", "Packages", "Home screen", "Final", "Ads & apps")

    def _build(self) -> None:
        side = tk.Frame(self, bg=theme.SIDE, width=230)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Label(side, text="TV DEBLOAT", bg=theme.SIDE, fg=theme.ACCENT,
                 font=(theme.FONT[0], 16, "bold")).pack(anchor="w", padx=18, pady=(20, 0))
        tk.Label(side, text="safe · reversible cleanup", bg=theme.SIDE, fg=theme.MUTED,
                 font=(theme.FONT[0], 9)).pack(anchor="w", padx=18, pady=(0, 18))
        self.nav = []
        for i, title in enumerate(self.NAV_TITLES):
            row = tk.Frame(side, bg=theme.SIDE, cursor="hand2")
            row.pack(fill="x", padx=10, pady=2)
            num = tk.Label(row, text=str(i), bg=theme.SIDE, fg=theme.MUTED, width=2,
                           font=(theme.FONT[0], 11, "bold"))
            num.pack(side="left", padx=(8, 4), pady=8)
            lab = tk.Label(row, text=title, bg=theme.SIDE, fg=theme.TEXT, anchor="w", font=(theme.FONT[0], 11))
            lab.pack(side="left", fill="x", expand=True)
            for w in (row, num, lab):
                w.bind("<Button-1>", lambda _e, i=i: self._nav_click(i))
            self.nav.append((row, num, lab))
        self.status = tk.StringVar(value="Ready.")
        self.progress = ttk.Progressbar(side, mode="indeterminate", length=190)
        self.progress.pack(side="bottom", padx=18, pady=(4, 16))
        tk.Label(side, textvariable=self.status, bg=theme.SIDE, fg=theme.MUTED, wraplength=190, justify="left",
                 font=(theme.FONT[0], 9)).pack(side="bottom", anchor="w", padx=18)

        main = ttk.Frame(self)
        main.pack(side="left", fill="both", expand=True)
        self.next_step = tk.StringVar(value=NEXT["start"])
        banner = tk.Label(main, textvariable=self.next_step, wraplength=860, justify="left", anchor="w",
                          bg="#10382b", fg=theme.ACCENT, padx=14, pady=10, font=(theme.FONT[0], 10, "bold"))
        banner.pack(fill="x", padx=12, pady=(12, 4))
        self.nb = ttk.Notebook(main, style="Tabless.TNotebook")
        self.nb.pack(fill="both", expand=True, padx=8, pady=4)
        frames = []
        for title in self.NAV_TITLES:
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

        logf = ttk.LabelFrame(main, text="What is happening (in plain language)")
        logf.pack(fill="x", padx=12, pady=4)
        self.logbox = scrolledtext.ScrolledText(logf, height=8, state="disabled", wrap="word")
        theme.style_text(self.logbox)
        self.logbox.pack(fill="x", padx=4, pady=4)
        ttk.Label(main, text=RULES_TEXT, wraplength=860, foreground=theme.VIOLET, justify="left").pack(
            fill="x", padx=12, pady=(2, 8))
        self._refresh_nav()
        self.on_platform_change()  # only now do all the widgets it depends on exist
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _nav_click(self, i: int) -> None:
        if str(self.nb.tab(i, "state")) == "normal":
            self.nb.select(i)

    def _refresh_nav(self) -> None:
        cur = self.nb.index("current")
        for i, (row, num, lab) in enumerate(self.nav):
            on = str(self.nb.tab(i, "state")) == "normal"
            active = i == cur
            bg = "#1d2a27" if active else theme.SIDE
            fg = theme.ACCENT if active else (theme.TEXT if on else "#4a5063")
            for w in (row, num, lab):
                w.configure(bg=bg)
            num.configure(fg=fg if active else (theme.MUTED if on else "#3a3f50"))
            lab.configure(fg=fg)
        self.after(300, self._refresh_nav)

    def _on_tab_changed(self, _e=None) -> None:
        if self.nb.index("current") == TAB_FINAL and self.session:
            self.set_next(NEXT["final"])

    # ---------------------------------------------------------------- 0 Prepare / 1 Connect
    def _build_start(self, f) -> None:
        prof = ttk.LabelFrame(f, text="Which TV do you have? (choose the system and brand)")
        prof.pack(fill="x", pady=(0, 8))
        self._prof_frame = prof
        self.v_platform = tk.StringVar(value=PLATFORMS["androidtv"].name)
        self.v_brand = tk.StringVar()
        ttk.Label(prof, text="System").grid(row=0, column=0, padx=6, pady=4, sticky="w")
        self.cb_platform = ttk.Combobox(prof, textvariable=self.v_platform, state="readonly", width=44,
                                        values=[p.name for p in PLATFORMS.values()])
        self.cb_platform.grid(row=0, column=1, padx=6)
        ttk.Label(prof, text="Brand").grid(row=0, column=2, padx=6, sticky="w")
        self.cb_brand = ttk.Combobox(prof, textvariable=self.v_brand, state="readonly", width=48)
        self.cb_brand.grid(row=0, column=3, padx=6)
        self.profile_msg = tk.StringVar()
        ttk.Label(prof, textvariable=self.profile_msg, wraplength=900, justify="left",
                  foreground=theme.WARN).grid(row=1, column=0, columnspan=4, padx=6, pady=4, sticky="w")
        self.cb_platform.bind("<<ComboboxSelected>>", self.on_platform_change)
        self.cb_brand.bind("<<ComboboxSelected>>", self.on_brand_change)

        self.prep_frame = ttk.LabelFrame(f, text="Before you start — tick what you have already done (on the TV itself)")
        self.prep_frame.pack(fill="both", expand=True, pady=4)
        self.prep_vars: list[tk.BooleanVar] = []
        self.guide_box = scrolledtext.ScrolledText(f, height=11, wrap="word")
        theme.style_text(self.guide_box)
        self.btn_prep_go = ttk.Button(f, text="All done → go to 1 · Connect", command=self._go_connect)
        self.btn_prep_go.pack(anchor="w", pady=6)

    def _render_prep(self) -> None:
        for w in self.prep_frame.winfo_children():
            w.destroy()
        self.prep_vars = []
        steps = PREP_STEPS.get(self._platform().key, [])
        if not steps:
            ttk.Label(self.prep_frame, text="There is no ADB preparation for this TV: see the guide below.").pack(
                anchor="w", padx=8, pady=8)
        for i, (title, detail) in enumerate(steps, 1):
            v = tk.BooleanVar(value=False)
            v.trace_add("write", lambda *_a: self._prep_changed())
            self.prep_vars.append(v)
            ttk.Checkbutton(self.prep_frame, text=f"{i}. {title}", variable=v).pack(anchor="w", padx=8, pady=(6, 0))
            ttk.Label(self.prep_frame, text=detail, wraplength=900, justify="left", foreground=theme.MUTED).pack(
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
                "Preparation incomplete",
                "Some steps are not ticked yet. Without debugging on and the same network the connection will fail.\n\n"
                "Go to tab 1 anyway?", parent=self):
                return
        self.nb.select(TAB_CONNECT)

    def set_next(self, text: str) -> None:
        self.next_step.set(text)

    # ---------------------------------------------------------------- 1 Connect
    def _build_connect(self, f) -> None:
        self.adb_status = tk.StringVar()
        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Label(row, textvariable=self.adb_status).pack(side="left")
        ttk.Button(row, text="Install adb (Google platform-tools)", command=self.install_adb).pack(side="left", padx=10)

        form = ttk.LabelFrame(f, text="Your TV")
        form.pack(fill="x", pady=8)
        self.v_model = tk.StringVar()
        self.v_ip = tk.StringVar()
        self.v_port = tk.StringVar(value="5555")
        self.v_usb = tk.StringVar()
        for r, (lab, var, hint) in enumerate((
            ("Brand / model", self.v_model, "e.g. TCL Smart TV Pro"),
            ("IP address", self.v_ip, "TV > Settings > Network & Internet > Status"),
            ("Port", self.v_port, "5555 (the default)"),
            ("What is plugged into the TV's USB ports?", self.v_usb, "e.g. nothing / USB speaker / disk"),
        )):
            ttk.Label(form, text=lab).grid(row=r, column=0, sticky="w", padx=6, pady=3)
            ttk.Entry(form, textvariable=var, width=34).grid(row=r, column=1, padx=6, pady=3)
            ttk.Label(form, text=hint, foreground=theme.MUTED).grid(row=r, column=2, sticky="w")
        ttk.Label(
            f, wraplength=900, justify="left",
            text=("Before connecting: in the TV's Developer options 'USB / wireless debugging' must be on, "
                  "and the computer and TV must be on the same network. Some TVs cut power to the USB ports "
                  "while debugging is on — that is why I ask what is plugged in (fill in above)."),
        ).pack(anchor="w")

        pair = ttk.LabelFrame(f, text="Only if the TV asks for a pairing code (Android 11+, 'Wireless debugging' screen)")
        pair.pack(fill="x", pady=8)
        self.v_pair_addr = tk.StringVar()
        self.v_pair_code = tk.StringVar()
        ttk.Label(pair, text="Pairing IP:port").grid(row=0, column=0, padx=6, pady=3, sticky="w")
        ttk.Entry(pair, textvariable=self.v_pair_addr, width=24).grid(row=0, column=1)
        ttk.Label(pair, text="Code").grid(row=0, column=2, padx=6)
        ttk.Entry(pair, textvariable=self.v_pair_code, width=10).grid(row=0, column=3)
        ttk.Button(pair, text="Pair", command=self.do_pair).grid(row=0, column=4, padx=8)

        self.conn_msg = tk.StringVar(value="Not connected yet.")
        self.btn_connect = ttk.Button(f, text="Connect to TV", command=self.do_connect)
        self.btn_connect.pack(anchor="w", pady=6)
        ttk.Label(f, textvariable=self.conn_msg, foreground=theme.INFO, wraplength=900).pack(anchor="w")

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
            if self.conn_msg.get().startswith("This TV does not allow"):
                self.conn_msg.set("Not connected yet.")
        else:
            self.set_next(NEXT["no_adb"])
            self.guide_box.configure(state="normal")
            self.guide_box.delete("1.0", "end")
            self.guide_box.insert("end", network_guide(p.key))
            self.guide_box.configure(state="disabled")
            self.guide_box.pack(fill="x", pady=4, after=self.prep_frame)
            self.btn_connect.configure(state="disabled")
            self.conn_msg.set("This TV does not allow ADB: follow the guide above (network-level action and TV settings).")

    def _refresh_adb_status(self) -> None:
        path = find_adb(APP_DIR)
        if path:
            self.adb_status.set(f"✔ adb found: {path}")
        else:
            self.adb_status.set("✘ adb not found — press the button to install it automatically.")

    def install_adb(self) -> None:
        self.bg(lambda: install_platform_tools(APP_DIR, self.log), ok=lambda p: self._refresh_adb_status())

    def _ensure_adb(self) -> Adb:
        if self.adb is None:
            path = find_adb(APP_DIR)
            if not path:
                raise AdbError("adb is not installed. Use the 'Install adb' button.")
            self.adb = Adb(CliBackend(path), APP_DIR, self.log)
        return self.adb

    def do_pair(self) -> None:
        addr, code = self.v_pair_addr.get().strip(), self.v_pair_code.get().strip()
        if not addr or not code:
            messagebox.showinfo("Pairing", "Fill in the pairing IP:port and the code the TV shows.")
            return

        def work():
            msg = self._ensure_adb().pair(addr, code)
            self.log(msg)
            return msg

        self.bg(work, ok=lambda m: self.conn_msg.set("Paired. Now press 'Connect to TV'."))

    def do_connect(self) -> None:
        ip, port = self.v_ip.get().strip(), self.v_port.get().strip() or "5555"
        if not IPV4.match(ip) or not port.isdigit():
            messagebox.showwarning("Missing data", "Enter a valid IP address (e.g. 192.168.1.50) and the port.")
            return
        if not self.v_usb.get().strip():
            messagebox.showwarning("USB ports", "Say what is plugged into the TV's USB ports (you can write 'nothing').")
            return
        self.conn_msg.set("Connecting… if 'Allow USB debugging?' shows on the TV, choose Allow (and 'Always allow').")

        def work():
            adb = self._ensure_adb()
            if not port_open(ip, int(port)):
                raise AdbError(
                    f"The TV does not answer at {ip}:{port}. Check the IP and that wireless debugging is on.")
            adb.connect(ip, int(port))
            self.ui(lambda: self.conn_msg.set(
                "Connected. Accept the 'Allow USB debugging?' dialog on the TV screen, if it is still there."))
            if not adb.wait_authorized(90, on_wait=lambda: self.log("Waiting for you to approve the dialog on the TV…")):
                raise AdbError("The TV did not authorize this computer in time. Try again and press Allow.")
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
            f"✔ Connected to {self.model_info or 'TV'} (Android {props.get('ro.build.version.release', '?')}, "
            f"via {self.adb.backend_name}). Go to tab 2.")
        self.nb.tab(TAB_BACKUP, state="normal")
        self.nb.select(TAB_BACKUP)
        self.set_next(NEXT["connected"])

    # ---------------------------------------------------------------- 2 Backup
    def _build_backup(self, f) -> None:
        ttk.Label(
            f, wraplength=900, justify="left",
            text=("Before touching anything: I save the package list, the disabled ones, getprop, the settings "
                  "(global/secure/system) and memory, and create the restore script right away. At the end I "
                  "repeat the measurement and show you the before/after table."),
        ).pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=10)
        self.v_base = tk.StringVar(value=str(Path.home()))
        ttk.Label(row, text="Save the 'tv-debloat' folder in:").pack(side="left")
        ttk.Entry(row, textvariable=self.v_base, width=50).pack(side="left", padx=6)
        ttk.Button(row, text="Choose…", command=lambda: self.v_base.set(
            filedialog.askdirectory(parent=self, initialdir=self.v_base.get()) or self.v_base.get())).pack(side="left")
        ttk.Button(f, text="Back up and measure memory", command=self.do_backup).pack(anchor="w", pady=4)
        self.backup_msg = tk.StringVar()
        ttk.Label(f, textvariable=self.backup_msg, wraplength=900, justify="left", foreground=theme.INFO).pack(anchor="w", pady=6)

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

        # Read the Tk variables here (main thread): Tk is not safe from background threads.
        header = {
            "System": platform_.name,
            "Brand": brand.name if brand else "?",
            "TV": self.v_model.get().strip() or self.model_info or "?",
            "IP": target,
            "USB ports": self.v_usb.get().strip(),
            "Computer": platform.platform(),
        }

        def work():
            self.ws.log_header(header)
            bdir = self.session.backup()
            self.session.scan()
            return bdir

        self.bg(work, ok=self._backup_done)

    def _backup_done(self, bdir: Path) -> None:
        m = self.session.mem_before
        mem = (f"Total RAM {m.get('Total', 0) / 1024:.0f} MB, free {m.get('Free', 0) / 1024:.0f} MB, "
               f"used {m.get('Used', 0) / 1024:.0f} MB." if m else "Could not read memory.")
        self.backup_msg.set(
            f"✔ Backup in {bdir}\nRestore script: {self.ws.restore_path}\nMemory before: {mem}")
        p = self._platform()
        for i in (TAB_PACKAGES, TAB_FINAL, TAB_EXTRAS) + ((TAB_HOME,) if p.launcher_swap else ()):
            self.nb.tab(i, state="normal")
        if not p.launcher_swap:
            self.log(f"{p.name}: the home screen cannot be swapped, so tab 4 is disabled.")
        dns_state = "normal" if p.dns_on_device else "disabled"
        for b in self.dns_buttons:
            b.configure(state=dns_state)
        self.dns_note.set("" if p.dns_on_device else
                          f"On {p.name} DNS cannot be changed over ADB: use a filtering DNS on the router (NextDNS, AdGuard Home, Pi-hole).")
        self.cb_platform.configure(state="disabled")
        self.cb_brand.configure(state="disabled")
        self.refresh_tree()
        self.nb.select(TAB_PACKAGES)
        self.set_next(NEXT["backup_done"])

    # ---------------------------------------------------------------- 3 Packages
    def _build_packages(self, f) -> None:
        tb = ttk.Frame(f)
        tb.pack(fill="x")
        for text, cmd in (
            ("Rescan packages", self.rescan),
            ("Import debloat.txt…", self.import_list),
            ("Mark groups 1 and 2", self.mark_12),
            ("Group 5 checklist…", self.open_checklist5),
            ("Clear selection", self.clear_sel),
        ):
            ttk.Button(tb, text=text, command=cmd).pack(side="left", padx=3)

        mid = ttk.PanedWindow(f, orient="horizontal")
        mid.pack(fill="both", expand=True, pady=6)
        left = ttk.Frame(mid)
        mid.add(left, weight=3)
        self.tree = ttk.Treeview(left, columns=("sel", "why"), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Package")
        self.tree.heading("sel", text="Disable")
        self.tree.heading("why", text="Why")
        self.tree.column("#0", width=330)
        self.tree.column("sel", width=90, anchor="center")
        self.tree.column("why", width=240)
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        right = ttk.LabelFrame(mid, text="Details")
        mid.add(right, weight=2)
        self.detail = tk.StringVar(value="Select a package.")
        ttk.Label(right, textvariable=self.detail, wraplength=240, justify="left").pack(anchor="w", padx=6, pady=6)
        ttk.Button(right, text="See what it does (dumpsys package)", command=self.show_dumpsys).pack(anchor="w", padx=6)
        ttk.Label(
            right, wraplength=240, foreground=theme.MUTED, justify="left",
            text=("🔒 = untouchable (the TV needs it). Click the 'Disable' column to tick ☐/☑. "
                  "Group 5 is up to you: use the checklist. Unidentified packages (group ?) "
                  "are inspected before being disabled."),
        ).pack(anchor="w", padx=6, pady=10)

        bot = ttk.Frame(f)
        bot.pack(fill="x")
        ttk.Label(bot, text=f"Packages per batch (max. {MAX_BATCH}):").pack(side="left")
        self.batch_size = tk.IntVar(value=MAX_BATCH)
        ttk.Spinbox(bot, from_=1, to=MAX_BATCH, width=4, textvariable=self.batch_size).pack(side="left", padx=4)
        self.one_by_one = tk.BooleanVar(value=False)
        ttk.Checkbutton(bot, text="One by one (slower, safer)", variable=self.one_by_one).pack(side="left", padx=10)
        self.sel_count = tk.StringVar(value="0 selected")
        ttk.Label(bot, textvariable=self.sel_count).pack(side="left", padx=10)
        ttk.Button(bot, text="Disable selected (in batches, with verification)", command=self.start_disable).pack(side="right")

    def _mark(self, info) -> str:
        if info.verdict.group == 6:
            return "🔒"
        if info.disabled:
            return "✓ off"
        if info.name in self.bad:
            return "⚠ broke"
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
            label = f"Group {g if g else '?'} — {GROUP_LABELS[g]} ({len(items)})"
            parent = self.tree.insert("", "end", iid=f"grp{g}", text=label, open=f"grp{g}" in opened)
            for info in items:
                self.tree.insert(parent, "end", iid=info.name, text=info.name,
                                 values=(self._mark(info), info.verdict.reason))
        self.sel_count.set(f"{len(self.sel)} selected")

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
        self.sel_count.set(f"{len(self.sel)} selected")

    def on_tree_select(self, _e=None) -> None:
        sel = self.tree.selection()
        info = self.session.infos.get(sel[0]) if (sel and self.session) else None
        if not info:
            return
        v = info.verdict
        self.detail.set(
            f"{info.name}\n\nGroup: {v.group if v.group else '?'} — {GROUP_LABELS[v.group]}\n"
            f"What it is: {v.description}\nWhy: {v.reason}\nFile: {info.path or '—'}\n"
            f"State: {'disabled' if info.disabled else 'active'}")

    def show_dumpsys(self) -> None:
        sel = self.tree.selection()
        if not sel or sel[0] not in (self.session.infos if self.session else {}):
            return
        pkg = sel[0]

        def show(res):
            risks, summary = res
            txt = summary + ("\n\n⚠ CAUTION: " + "; ".join(risks) if risks else "\n\nNo signs of an essential service.")
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
        path = filedialog.askopenfilename(parent=self, title="Choose a debloat.txt (one package per line)")
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
        self.log(f"List imported: {added} packages ticked; {skipped} ignored "
                 f"(not on this TV, already disabled or untouchable).")
        self.refresh_tree()

    def open_checklist5(self) -> None:
        items = [i for i in self.session.infos.values()
                 if i.system and i.verdict.group == 5 and not i.disabled and i.name not in self.bad]
        if not items:
            messagebox.showinfo("Group 5", "There are no group 5 packages left to decide.", parent=self)
            return
        dlg = tk.Toplevel(self)
        dlg.title("Checklist: what do you want to KEEP?")
        dlg.transient(self)
        ttk.Label(dlg, wraplength=560, justify="left", text=(
            "These apps/services are up to you (streaming, voice assistant, Chromecast, mirroring, "
            "updates). Leave ticked what you use or want to keep. "
            "I only disable what you untick.")).pack(padx=10, pady=8)
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

        ttk.Button(dlg, text="Apply", command=ok).pack(pady=8)
        dlg.after(100, lambda: safe_grab(dlg))

    # ---- disable in batches
    def start_disable(self) -> None:
        chosen = [n for n in sorted(self.sel)
                  if n in self.session.infos and self.session.infos[n].verdict.group != 6
                  and not self.session.infos[n].disabled]
        if not chosen:
            messagebox.showinfo("Nothing selected", "Tick some packages first.", parent=self)
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
                "Packages the TV may need",
                "Removed from the selection (dumpsys shows essential services):\n\n"
                + "\n".join(f"• {n}: {', '.join(r)}" for n, r in risky.items()), parent=self)
            for n in risky:
                self.sel.discard(n)
                self.bad.add(n)
            chosen = [n for n in chosen if n not in risky]
        safe = {n: s for n, (r, s) in results.items() if not r}
        if safe:
            text = "\n\n".join(f"{n}\n{s}" for n, s in safe.items())
            if messagebox.askyesno(
                "Unidentified packages",
                "I cannot tell from the name alone what these packages do. This is what they declare:\n\n"
                f"{text[:2500]}\n\nNo signs of an essential service, but the decision is yours. Disable anyway?",
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
            "Confirm",
            f"I will disable {len(chosen)} packages in {len(batches)} batch(es) of up to {size}.\n\n"
            "• Nothing is uninstalled; each one is undone with 'pm enable'.\n"
            "• After each batch I stop and show you the TV screen so you can confirm.\n\nContinue?",
            parent=self):
            return
        self.batches = batches
        self.batch_no = 0
        self._run_next()

    def _run_next(self) -> None:
        if not self.batches:
            self.log("Queue finished.")
            self.set_next(NEXT["queue_done"])
            self.rescan()
            return
        batch = self.batches.pop(0)
        self.batch_no += 1
        label = f"Batch {self.batch_no}" + (" (one by one)" if len(batch) == 1 else "")
        self.bg(lambda: self.session.disable_batch(batch, label, self.confirmed_unknown),
                ok=lambda res: self._batch_done(res))

    def _batch_done(self, res) -> None:
        for p in res.ok:
            self.sel.discard(p)
        self.refresh_tree()
        if res.failed:
            p, out = res.failed[0]
            messagebox.showwarning("A package did not disable", f"{p}\n{out}\n\nStopping the queue.", parent=self)
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
                self.log(f"{pkgs[0]} was the culprit: it stays re-enabled and marked as 'broke'.")
                self.ws.log(f"- ⚠ `{pkgs[0]}` broke something; it was left re-enabled.")
            else:
                self.log("Batch re-enabled. I will test them one by one to find which broke it.")
                self.batches = [[p] for p in pkgs] + self.batches
            self.refresh_tree()
            self._run_next()

        self.bg(lambda: self.session.revert(pkgs), ok=after)

    def _batch_abort(self, pkgs) -> None:
        self.batches = []
        self.log("You closed the verification without deciding. The queue stopped; this batch's packages stay disabled — "
                 "check the TV and use 'Restore all' in tab 5 if needed.")

    # ---------------------------------------------------------------- 4 Home screen
    def _build_home(self, f) -> None:
        ttk.Label(f, wraplength=900, justify="left", text=(
            "The Google TV home screen is full of ads and recommendations. I swap it for FLauncher "
            "(free, open source, just a grid of apps). I only disable the original launcher once "
            "FLauncher is already the default.")).pack(anchor="w")
        self.home_msg = tk.StringVar(value="")
        steps = ttk.Frame(f)
        steps.pack(fill="x", pady=8)
        ttk.Label(steps, text="1. Install FLauncher on the TV (Play Store), then:").grid(row=0, column=0, sticky="w")
        ttk.Button(steps, text="Check it is installed", command=self.home_check).grid(row=0, column=1, padx=8, pady=3)
        ttk.Label(steps, text="2. See who claims the home screen:").grid(row=1, column=0, sticky="w")
        ttk.Button(steps, text="List", command=self.home_list).grid(row=1, column=1, padx=8, pady=3)
        ttk.Label(steps, text="3. Set FLauncher as the default:").grid(row=2, column=0, sticky="w")
        ttk.Button(steps, text="Set (or choose on the TV)", command=self.home_set).grid(row=2, column=1, padx=8, pady=3)
        ttk.Label(steps, text="4. Reboot and check FLauncher sticks:").grid(row=3, column=0, sticky="w")
        ttk.Button(steps, text="Reboot and check", command=self.home_reboot).grid(row=3, column=1, padx=8, pady=3)
        ttk.Label(steps, text="   If the setup wizard steals the screen:").grid(row=4, column=0, sticky="w")
        ttk.Button(steps, text="Disable wizard", command=self.home_wizard).grid(row=4, column=1, padx=8, pady=3)
        ttk.Label(steps, text="5. Disable the original launcher:").grid(row=5, column=0, sticky="w")
        ttk.Button(steps, text="Disable original launcher", command=self.home_stock).grid(row=5, column=1, padx=8, pady=3)
        self.home_list_box = tk.Listbox(f, height=6)
        theme.style_text(self.home_list_box)
        self.home_list_box.pack(fill="x", pady=6)
        ttk.Label(f, textvariable=self.home_msg, wraplength=900, foreground=theme.INFO).pack(anchor="w")
        ttk.Label(f, foreground=theme.MUTED, wraplength=900, text=(
            "Android 14 note: if you install an APK over adb and it hangs, it is waiting for a confirmation "
            "on the TV. Install FLauncher from the Play Store, which is simpler.")).pack(anchor="w", pady=6)
        self._home_components: list[str] = []

    def home_check(self) -> None:
        def done(p):
            self.home_msg.set(f"✔ FLauncher installed ({p})." if p else
                              "✘ I cannot find FLauncher yet. Install it from the TV's Play Store and try again.")
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
                self.home_list_box.insert("end", f"{comp}" + ("   ← default now" if pkg == default else ""))
            self.home_msg.set("These are the installed home screens. FLauncher should appear in the list.")

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
                "FLauncher", "First press 'List' so FLauncher appears. If it cannot be set "
                "from here, press Home on the remote and choose FLauncher on the TV ('Always').", parent=self)
            return

        def done(cur):
            ok = bool(cur and "flauncher" in cur.lower())
            self.home_msg.set("✔ FLauncher is now the default." if ok else
                              f"The default is still {cur}. Choose FLauncher on the TV when you press Home.")
            VerifyDialog(self, [], mode="view", title="Current home screen")

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
                self.home_msg.set(f"✔ After the reboot the home screen is still FLauncher ({focus.package}).")
            else:
                self.home_msg.set(f"✘ After the reboot the screen is '{focus.package}' (default: {cur}). "
                                  "If it is the setup wizard, use 'Disable wizard'.")
            VerifyDialog(self, [], mode="view", title="After the reboot")

        self.bg(work, ok=done)

    def _unlock_and_disable(self, pkgs_fn, label, then=None) -> None:
        def work():
            self.session.unlock_launcher_disable()
            pkgs = [p for p in pkgs_fn() if p in self.session.infos]
            if not pkgs:
                raise SessionError("I could not find that package on this TV.")
            return self.session.disable_batch(pkgs, label)

        def done(res):
            self.refresh_tree()
            if res.failed:
                messagebox.showwarning("Did not disable", f"{res.failed[0][0]}\n{res.failed[0][1]}", parent=self)
            if res.ok:
                VerifyDialog(self, res.ok, mode="decide",
                             on_ok=lambda: self.home_msg.set("✔ Confirmed."),
                             on_bad=lambda: self.bg(lambda: self.session.revert(res.ok), ok=lambda _r: self.refresh_tree()),
                             on_abort=lambda: None, title=label)

        self.bg(work, ok=done)

    def home_wizard(self) -> None:
        self._unlock_and_disable(lambda: [SETUP_WIZARD], "Setup wizard")

    def home_stock(self) -> None:
        if not messagebox.askyesno(
            "Original launcher",
            "Is FLauncher already the default and does the screen still work after the reboot?\n\n"
            "Only then do I disable the original launcher (reversible with 'pm enable').", parent=self):
            return
        self._unlock_and_disable(self.session.stock_launchers_present, "Original launcher")

    # ---------------------------------------------------------------- 5 Final
    def _build_final(self, f) -> None:
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        for text, cmd in (
            ("e) Halve animations", self.do_speedups),
            ("f) Clear caches", self.do_trim),
            ("g) Reboot and measure", self.do_final_measure),
            ("Generate report", self.do_report),
        ):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=4)
        ttk.Button(bar, text="Restore all", command=self.do_restore).pack(side="right", padx=4)
        self.report = scrolledtext.ScrolledText(f, height=22, wrap="word")
        theme.style_text(self.report)
        self.report.pack(fill="both", expand=True, pady=8)
        ttk.Label(f, foreground=theme.MUTED, wraplength=900, text=(
            "Tip: after everything, if something plugged into the TV's USB ports stopped working, "
            "turn off USB debugging in Developer options.")).pack(anchor="w")

    def do_speedups(self) -> None:
        self.bg(self.session.apply_speedups, ok=lambda _r: self.log("Animations at 0.5 (original values saved)."))

    def do_trim(self) -> None:
        self.bg(self.session.trim_caches, ok=lambda _r: self.log("Caches cleared."))

    def do_final_measure(self) -> None:
        def work():
            self.session.reboot_and_wait()
            self.session.measure_after()
            return self.session.final_report()

        def done(text):
            self._show_report(text)
            VerifyDialog(self, [], mode="view", title="After the final reboot")

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
        self.log(f"Report saved in {self.ws.log_path}")

    # ---------------------------------------------------------------- 6 Ads & apps
    def _build_extras(self, f) -> None:
        ttk.Label(f, wraplength=900, justify="left", text=(
            "What actually works against ads:\n"
            "• YouTube: DNS does not solve it (the ads come from the same servers as the video) and AdGuard for "
            "Android TV does not block them either. The way is an alternative client, SmartTube (below).\n"
            "• Streaming and telemetry: a filtering DNS cuts tracking and some ads, but not the "
            "ads that come inside the stream itself.\n"
            "• Home screen ads: solved with the debloat and FLauncher (tabs 3 and 4)."
        )).pack(anchor="w")

        dns = ttk.LabelFrame(f, text="DNS that filters ads and tracking (Android 9+ private DNS)")
        dns.pack(fill="x", pady=8)
        self.dns_presets = {"AdGuard DNS (ads and tracking)": "dns.adguard-dns.com", "Other (type it)": ""}
        self.v_dns_preset = tk.StringVar(value="AdGuard DNS (ads and tracking)")
        self.v_dns_custom = tk.StringVar()
        ttk.Combobox(dns, textvariable=self.v_dns_preset, values=list(self.dns_presets), state="readonly",
                     width=36).grid(row=0, column=0, padx=6, pady=6)
        ttk.Label(dns, text="Custom server:").grid(row=0, column=1, padx=(10, 2))
        ttk.Entry(dns, textvariable=self.v_dns_custom, width=34).grid(row=0, column=2)
        ttk.Label(dns, text="e.g. abc123.dns.nextdns.io", foreground=theme.MUTED).grid(row=0, column=3, padx=6)
        b1 = ttk.Button(dns, text="Apply DNS", command=self.do_dns_apply)
        b2 = ttk.Button(dns, text="Reset DNS (automatic)", command=self.do_dns_reset)
        b1.grid(row=1, column=0, padx=6, pady=4, sticky="w")
        b2.grid(row=1, column=1, columnspan=2, padx=6, pady=4, sticky="w")
        self.dns_buttons = [b1, b2]
        self.dns_note = tk.StringVar()
        ttk.Label(dns, textvariable=self.dns_note, wraplength=900, foreground=theme.WARN).grid(
            row=2, column=0, columnspan=4, padx=6, sticky="w")
        ttk.Label(dns, wraplength=900, foreground=theme.MUTED, justify="left", text=(
            "After applying, check that YouTube and Netflix still load. If the TV loses internet "
            "(some networks block private DNS), reset it. Not every TV honours this setting.")).grid(
            row=3, column=0, columnspan=4, padx=6, pady=(0, 6), sticky="w")

        apps = ttk.LabelFrame(f, text="Apps")
        apps.pack(fill="both", expand=True, pady=4)
        self.app_list = tk.Listbox(apps, height=6, exportselection=False)
        theme.style_text(self.app_list)
        for a in CATALOG:
            self.app_list.insert("end", f"{a.name} — {a.purpose}")
        self.app_list.pack(fill="x", padx=6, pady=6)
        self.app_list.bind("<<ListboxSelect>>", self.on_app_select)
        self.app_detail = tk.StringVar(value="Select an app to see how to install it.")
        ttk.Label(apps, textvariable=self.app_detail, wraplength=900, justify="left").pack(anchor="w", padx=6)
        self.app_warn = tk.StringVar()
        ttk.Label(apps, textvariable=self.app_warn, wraplength=900, justify="left",
                  foreground=theme.DANGER).pack(anchor="w", padx=6, pady=4)
        row = ttk.Frame(apps)
        row.pack(fill="x", padx=6, pady=6)
        self.btn_app_page = ttk.Button(row, text="Open the official page", command=self.open_app_page, state="disabled")
        self.btn_app_page.pack(side="left")
        ttk.Button(row, text="Install an APK I already downloaded…", command=self.install_apk_dialog).pack(
            side="left", padx=10)
        ttk.Label(apps, foreground=theme.MUTED, wraplength=900, text=(
            "I never download or install anything by myself: you download the APK from an official source and here "
            "you see the size and SHA-256 before confirming. To remove an app use the TV's Settings "
            "(this program never uninstalls).")).pack(anchor="w", padx=6, pady=(0, 6))

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
        path = filedialog.askopenfilename(parent=self, title="Choose the APK to install on the TV",
                                          filetypes=[("APK", "*.apk")])
        if not path:
            return
        a = self._selected_app()
        warn = f"\n\n⚠ {a.warning}" if a and a.warning else ""

        def confirm(info):
            ok = messagebox.askyesno(
                "Install on the TV?",
                f"File: {info['name']}\nSize: {info['size'] / 1048576:.1f} MB\nSHA-256:\n{info['sha256']}\n\n"
                "Check that you downloaded it from the official site and, if the project publishes the SHA-256, that it matches."
                f"{warn}\n\nInstall?", parent=self)
            if ok:
                self.bg(lambda: self.session.install_apk(path),
                        ok=lambda sha: self.log(f"✔ {info['name']} installed (SHA-256 {sha[:12]}…). Open it on the TV."))

        self.bg(lambda: validate_apk(path), ok=confirm)

    def _dns_host(self) -> str:
        return (self.v_dns_custom.get().strip() or self.dns_presets.get(self.v_dns_preset.get(), "")).lower()

    def do_dns_apply(self) -> None:
        host = self._dns_host()
        if not host:
            messagebox.showinfo("DNS", "Choose a server or type your own (e.g. abc123.dns.nextdns.io).", parent=self)
            return
        if not messagebox.askyesno(
            "Apply DNS",
            f"I will use the private DNS '{host}' on this TV (reversible: 'Reset DNS' or restore all). Continue?",
            parent=self):
            return

        def done(_r):
            VerifyDialog(
                self, [], mode="decide", title="DNS applied",
                ok_text="✔ The TV still has internet",
                bad_text="✘ No internet / something broke — reset DNS",
                on_ok=lambda: self.log("DNS kept."),
                on_bad=lambda: self.bg(self.session.reset_private_dns, ok=lambda _x: self.log("DNS reset.")),
                on_abort=lambda: self.log("DNS check closed without deciding; use 'Reset DNS' if needed."))

        self.bg(lambda: self.session.set_private_dns(host), ok=done)

    def do_dns_reset(self) -> None:
        self.bg(self.session.reset_private_dns, ok=lambda _r: self.log("Private DNS reset to automatic."))

    def do_restore(self) -> None:
        if not messagebox.askyesno(
            "Restore all",
            "I will re-enable every package in disabled.txt and reset the original animations. Continue?", parent=self):
            return
        self.bg(self.session.restore_all, ok=lambda pk: (self.log(f"{len(pk)} packages re-enabled."), self.refresh_tree()))
