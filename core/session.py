"""Sessão de debloat: orquestra backup, análise, lotes, verificação, ecrã inicial e relatório."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .packages import (
    GROUP_LABELS,
    STOCK_LAUNCHERS,
    Classifier,
    Verdict,
    risk_from_dumpsys,
    summarize_dumpsys,
)
from .apps import validate_apk
from .workspace import Workspace, memory_rows, parse_meminfo

MAX_BATCH = 10
BLANK_PNG_BYTES = 6000  # um PNG 1080p todo preto é minúsculo
ANIM_KEYS = ("window_animation_scale", "transition_animation_scale", "animator_duration_scale")
SYSTEM_PREFIXES = ("/system/", "/vendor/", "/product/", "/system_ext/", "/odm/", "/oem/")

# (ficheiro, comando, pode vir vazio)
BACKUP_COMMANDS = [
    ("pm_list_packages_f.txt", "pm list packages -f", False),
    ("pm_list_packages_d.txt", "pm list packages -d", True),
    ("getprop.txt", "getprop", False),
    ("settings_global.txt", "settings list global", False),
    ("settings_secure.txt", "settings list secure", False),
    ("settings_system.txt", "settings list system", False),
    ("dumpsys_meminfo_antes.txt", "dumpsys meminfo", False),
]


class SessionError(Exception):
    pass


@dataclass
class PackageInfo:
    name: str
    path: str
    system: bool
    disabled: bool
    verdict: Verdict


@dataclass
class BatchResult:
    label: str
    ok: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class FocusInfo:
    raw: str
    package: str | None
    crashed: bool


def parse_pm_list(out: str) -> dict[str, str]:
    res: dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("package:"):
            continue
        body = line[len("package:"):]
        if "=" in body:
            path, name = body.rsplit("=", 1)
        else:
            path, name = "", body
        name = name.split()[0] if name.split() else ""
        if name:
            res[name] = path.strip()
    return res


_ACT = re.compile(r"ActivityInfo:\s*\n\s*name=(\S+)\s*\n\s*packageName=(\S+)")


def parse_home_activities(out: str) -> list[tuple[str, str]]:
    """[(pacote, 'pacote/Classe')] dos pacotes que reclamam o ecrã inicial."""
    comps = [(pkg, f"{pkg}/{name}") for name, pkg in _ACT.findall(out)]
    if not comps:
        comps = [(p, p) for p in re.findall(r"packageName=(\S+)", out)]
    seen, res = set(), []
    for pkg, comp in comps:
        if comp not in seen:
            seen.add(comp)
            res.append((pkg, comp))
    return res


class DebloatSession:
    def __init__(self, adb, workspace: Workspace, log=print, sleep=time.sleep, brand=None, platform=None):
        self.adb = adb
        self.ws = workspace
        self.log = log
        self.sleep = sleep
        self.brand = brand  # core.profiles.Brand | None
        self.platform = platform  # core.profiles.Platform | None
        self.infos: dict[str, PackageInfo] = {}
        self.installed: set[str] = set()
        self.home: list[tuple[str, str]] = []
        self.backup_done = False
        self.backup_dir: Path | None = None
        self.mem_before: dict[str, int] = {}
        self.mem_after: dict[str, int] = {}
        self.launcher_unlocked = False

    # ------------------------------------------------------------------ backup
    def backup(self) -> Path:
        self.log("A criar o script de restauro e a guardar uma cópia do estado atual da TV…")
        self.ws.start_restore()
        bdir = self.ws.new_backup_dir()
        for fname, cmd, may_be_empty in BACKUP_COMMANDS:
            self.log(f"  • {cmd}")
            out = self.adb.shell(cmd, timeout=120)
            if not out.strip() and not may_be_empty:
                raise SessionError(f"O backup falhou: '{cmd}' não devolveu nada. Nada foi alterado.")
            (bdir / fname).write_text(out, encoding="utf-8")
        self.mem_before = parse_meminfo((bdir / "dumpsys_meminfo_antes.txt").read_text(encoding="utf-8"))
        self.backup_dir = bdir
        self.backup_done = True
        self.ws.log(f"- Backup guardado em `{bdir.name}/` (pacotes, definições, getprop, meminfo).")
        return bdir

    # ------------------------------------------------------------------ análise
    def query_home(self) -> list[tuple[str, str]]:
        out = self.adb.shell(
            "cmd package query-activities -a android.intent.action.MAIN -c android.intent.category.HOME"
        )
        self.home = parse_home_activities(out)
        return self.home

    def default_home(self) -> str | None:
        out = self.adb.shell(
            "cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME"
        )
        for line in reversed([l.strip() for l in out.splitlines() if l.strip()]):
            if "/" in line:
                return line.split("/")[0]
        return None

    def scan(self) -> list[PackageInfo]:
        self.log("A listar os pacotes instalados e a classificá-los…")
        all_out = self.adb.shell("pm list packages -f", timeout=120)
        dis_out = self.adb.shell("pm list packages -d", timeout=60)
        paths = parse_pm_list(all_out)
        disabled = set(parse_pm_list(dis_out))
        self.installed = set(paths)
        self.query_home()
        clf = self._classifier()
        self.infos = {}
        for name, path in paths.items():
            system = (not path) or path.startswith(SYSTEM_PREFIXES)
            self.infos[name] = PackageInfo(name, path, system, name in disabled, clf.classify(name))
        self.log(f"Encontrei {sum(1 for i in self.infos.values() if i.system)} pacotes de sistema.")
        return list(self.infos.values())

    def _classifier(self) -> Classifier:
        extra = dict(self.brand.extra_protected) if self.brand else {}
        allow = self.launcher_unlocked and (self.platform is None or self.platform.launcher_swap)
        return Classifier({p for p, _ in self.home}, allow, extra)

    def reclassify(self) -> None:
        clf = self._classifier()
        for info in self.infos.values():
            info.verdict = clf.classify(info.name)

    # ------------------------------------------------------------------ inspeção
    def inspect(self, pkg: str) -> tuple[list[str], str]:
        out = self.adb.shell(f"dumpsys package {pkg}", timeout=90)
        return risk_from_dumpsys(out), summarize_dumpsys(out)

    # ------------------------------------------------------------------ lotes
    def disable_batch(self, pkgs: list[str], label: str, confirmed_unknown=()) -> BatchResult:
        if not self.backup_done:
            raise SessionError("Faz primeiro o backup e a medição (regra 3).")
        if not pkgs:
            raise SessionError("Lote vazio.")
        if len(pkgs) > MAX_BATCH:
            raise SessionError(f"Um lote tem no máximo {MAX_BATCH} pacotes (regra 5).")
        current_home = self.default_home()
        for p in pkgs:
            info = self.infos.get(p)
            if info is None:
                raise SessionError(f"{p}: não existe nesta TV (volta a procurar os pacotes).")
            if info.verdict.group == 6:
                raise SessionError(f"{p} é intocável: {info.verdict.reason}.")
            if p == current_home:
                raise SessionError(f"{p} é o ecrã inicial atual.")
            if info.verdict.group == 0 and p not in set(confirmed_unknown):
                raise SessionError(f"{p} não está identificado; inspeciona-o e confirma antes.")
        self.ws.log_section(label)
        res = BatchResult(label)
        for p in pkgs:  # um comando pm por chamada (regra 5)
            info = self.infos[p]
            self.log(
                f"A desativar {p} — fica desligado mas continua instalado; "
                f"dá para voltar a ligar com 'pm enable {p}'."
            )
            out = self.adb.shell(f"pm disable-user --user 0 {p}")
            if "disabled-user" in out:
                info.disabled = True
                self.ws.record_disable(p, info.verdict.group, info.verdict.description, label)
                res.ok.append(p)
            else:
                res.failed.append((p, out.strip()))
                self.log(f"  ✘ {p}: {out.strip() or 'sem resposta'}")
                break
        return res

    def revert(self, pkgs: list[str], why: str = "reativado (algo partiu)") -> list[str]:
        done = []
        for p in pkgs:
            self.log(f"A reativar {p}…")
            self.adb.shell(f"pm enable {p}")
            if p in self.infos:
                self.infos[p].disabled = False
            self.ws.remove_disabled(p, why)
            done.append(p)
        return done

    # ------------------------------------------------------------------ verificação
    def press(self, key: str) -> None:
        self.adb.shell(f"input keyevent {key}")

    def focus(self) -> FocusInfo:
        out = self.adb.shell("dumpsys window", timeout=90)
        m = re.search(r"mCurrentFocus=Window\{([^}]*)\}", out)
        raw = m.group(1) if m else ""
        crashed = any(s in raw for s in ("Not Responding", "Application Error", "has stopped", "keeps stopping"))
        pm = re.search(r"\s([A-Za-z0-9_.]+)/[A-Za-z0-9_.$]+\s*$", raw)
        return FocusInfo(raw, pm.group(1) if pm else None, crashed)

    def check_home(self) -> tuple[bool, str]:
        self.press("KEYCODE_HOME")
        self.sleep(2.5)
        f = self.focus()
        if f.crashed:
            return False, f"Aparece um erro no ecrã: {f.raw}"
        home_pkgs = {p for p, _ in self.home} | ({d} if (d := self.default_home()) else set())
        if f.package and f.package in home_pkgs:
            return True, f"Ecrã inicial a funcionar ({f.package})."
        if f.package is None:
            return False, "Não consegui ver que janela está no ecrã."
        return False, f"Em vez do ecrã inicial está '{f.package}'."

    def launch(self, pkg: str) -> tuple[bool, str]:
        out = self.adb.shell(f"monkey -p {pkg} -c android.intent.category.LEANBACK_LAUNCHER 1", timeout=60)
        if "No activities found" in out:
            out = self.adb.shell(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1", timeout=60)
        self.sleep(4)
        f = self.focus()
        if f.crashed:
            return False, f"{pkg}: aparece um erro ({f.raw})"
        if f.package == pkg:
            return True, f"{pkg} abriu."
        return False, f"{pkg} não abriu (em primeiro plano: {f.package})."

    def streaming_candidates(self) -> list[tuple[str, str]]:
        res = []
        for p in sorted(self.installed):
            if "netflix" in p:
                res.append(("Netflix", p))
        if "com.google.android.youtube.tv" in self.installed:
            res.append(("YouTube", "com.google.android.youtube.tv"))
        return res

    def screenshot(self, tag: str = "shot") -> Path:
        data = self.adb.screencap()
        if len(data) < BLANK_PNG_BYTES:
            self.log("O ecrã parece vazio (Live TV/HDMI?). Carrego em Home e repito a captura.")
            self.press("KEYCODE_HOME")
            self.sleep(2.5)
            data = self.adb.screencap()
        path = self.ws.next_shot_path(tag)
        path.write_bytes(data)
        return path

    # ------------------------------------------------------------------ ecrã inicial
    def find_flauncher(self) -> str | None:
        out = parse_pm_list(self.adb.shell("pm list packages -f", timeout=120))
        self.installed = set(out)
        for p in sorted(out):
            if "flauncher" in p.lower():
                return p
        return None

    def set_home(self, component: str) -> str | None:
        if "/" not in component:
            raise SessionError("Preciso do componente completo (pacote/Atividade). Escolhe o FLauncher na TV.")
        self.log(f"A definir {component} como ecrã inicial predefinido…")
        self.adb.shell(f"cmd package set-home-activity {component}")
        self.sleep(1.5)
        cur = self.default_home()
        self.ws.log(f"- Ecrã inicial predefinido: `{component}` (agora: `{cur}`).")
        return cur

    def unlock_launcher_disable(self) -> None:
        if self.platform is not None and not self.platform.launcher_swap:
            raise SessionError(f"Em {self.platform.name} não se troca o ecrã inicial.")
        cur = self.default_home()
        if not cur or "flauncher" not in cur.lower():
            raise SessionError(
                "O FLauncher ainda não é o ecrã inicial predefinido. "
                "Só desativo o launcher original depois disso."
            )
        self.launcher_unlocked = True
        self.reclassify()

    def stock_launchers_present(self) -> list[str]:
        return [p for p in sorted(STOCK_LAUNCHERS) if p in self.installed]

    # ------------------------------------------------------------------ extras finais
    def apply_speedups(self) -> None:
        self.log("A reduzir as animações para metade (a TV parece mais rápida).")
        for k in ANIM_KEYS:
            old = self.adb.shell(f"settings get global {k}")
            self.ws.record_setting(k, old)
            self.adb.shell(f"settings put global {k} 0.5")

    # ------------------------------------------------------------------ apps e DNS
    def install_apk(self, apk_path) -> str:
        """Envia o APK para a pasta temporária e instala-o com `pm install -r` (sem desinstalar nada)."""
        info = validate_apk(apk_path)
        remote = f"/data/local/tmp/tvdebloat-{info['sha256'][:16]}.apk"
        self.log(f"A enviar {info['name']} para a TV…")
        self.adb.push(apk_path, remote)
        try:
            self.log("A instalar (pode demorar; em Android 14 não deve pedir confirmação na TV)…")
            out = self.adb.shell(f"pm install -r {remote}", timeout=600)
        finally:
            try:
                self.adb.shell(f"rm {remote}")
            except Exception:
                pass
        if "Success" not in out:
            raise SessionError(f"A instalação falhou: {out.strip() or 'sem resposta da TV'}")
        self.ws.log(
            f"- App instalada: `{info['name']}` (SHA-256 `{info['sha256']}`). "
            "Para a remover usa Definições > Aplicações na própria TV (este programa nunca desinstala)."
        )
        return info["sha256"]

    def set_private_dns(self, hostname: str) -> None:
        """Ativa um DNS privado (DoT) que filtra anúncios/rastreio. Valores originais ficam guardados."""
        if self.platform is not None and not self.platform.dns_on_device:
            raise SessionError(f"Em {self.platform.name} o DNS não se muda por aqui; usa o router.")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{1,252}\.[A-Za-z]{2,63}", hostname):
            raise SessionError("O nome do servidor DNS não é válido (ex.: dns.adguard-dns.com).")
        mode = self.adb.shell("settings get global private_dns_mode")
        spec = self.adb.shell("settings get global private_dns_specifier")
        self.ws.record_setting("private_dns_mode", mode, null_value="opportunistic")
        if spec.strip() not in ("", "null"):
            self.ws.record_setting("private_dns_specifier", spec)
        self.adb.shell(f"settings put global private_dns_specifier {hostname}")
        self.adb.shell("settings put global private_dns_mode hostname")
        self.ws.log(f"- DNS privado ativado: `{hostname}`. Desfazer: `adb shell settings put global private_dns_mode opportunistic`")

    def reset_private_dns(self) -> None:
        self.adb.shell("settings put global private_dns_mode opportunistic")
        self.ws.log("- DNS privado reposto em modo automático.")

    def trim_caches(self) -> None:
        self.log("A limpar as caches de todas as apps (não apaga dados).")
        self.adb.shell("pm trim-caches 999G", timeout=180)
        self.ws.log("- `pm trim-caches 999G` executado (caches limpas; sem perda de dados).")

    def reboot_and_wait(self, timeout: int = 240) -> None:
        self.log("A reiniciar a TV… (vai demorar um ou dois minutos)")
        try:
            self.adb.shell("reboot")
        except Exception:
            pass  # a ligação cai ao reiniciar
        self.sleep(20)
        end = time.time() + timeout
        while time.time() < end:
            try:
                self.adb.reconnect()
                if self.adb.shell("getprop sys.boot_completed").strip() == "1":
                    self.sleep(8)
                    self.log("A TV voltou.")
                    return
            except Exception:
                pass
            self.sleep(5)
        raise SessionError("A TV não voltou a ligar ao ADB. Confirma que arrancou e que a depuração sem fios continua ligada.")

    def measure_after(self) -> dict[str, int]:
        out = self.adb.shell("dumpsys meminfo", timeout=120)
        if self.backup_dir:
            (self.backup_dir / "dumpsys_meminfo_depois.txt").write_text(out, encoding="utf-8")
        self.mem_after = parse_meminfo(out)
        return self.mem_after

    def restore_all(self) -> list[str]:
        pkgs = self.ws.read_disabled()
        for p in pkgs:
            self.log(f"A reativar {p}…")
            self.adb.shell(f"pm enable {p}")
            if p in self.infos:
                self.infos[p].disabled = False
        for k, v in self.ws.read_original_settings().items():
            self.adb.shell(f"settings put global {k} {v}")
        self.ws.log("- Restauro completo executado pela interface (pacotes reativados e animações repostas).")
        return pkgs

    # ------------------------------------------------------------------ relatório
    def final_report(self) -> str:
        rows = memory_rows(self.mem_before, self.mem_after)
        lines = ["# Resultado do debloat", "", "## Memória (antes / depois)", "",
                 "| Medida | Antes | Depois | Diferença |", "|---|---|---|---|"]
        lines += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in rows]
        lines += ["", "## Pacotes desativados", ""]
        entries = self.ws.read_disabled_entries()
        if not entries:
            lines.append("(nenhum)")
        for pkg, ts, group, desc in entries:
            lines.append(f"- `{pkg}` — {desc or GROUP_LABELS.get(int(group or 0), '')}")
        lines += ["", "## Como desfazer", "",
                  f"- Tudo de uma vez: `{self.ws.undo_all_command()}`",
                  "- Um pacote: `adb shell pm enable <pacote>`",
                  f"- Script: `{self.ws.restore_path}`",
                  "", "## Lembrete", "",
                  "Se algo ligado às portas USB da TV (coluna, disco…) deixou de funcionar, desliga a "
                  "depuração USB nas Opções de programador."]
        return "\n".join(lines)
