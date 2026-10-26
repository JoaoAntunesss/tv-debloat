"""Pasta `tv-debloat`: backups, disabled.txt, restore.sh/.ps1 e DEBLOAT-LOG.md (regras 3 e 8)."""
from __future__ import annotations

import platform
import re
from datetime import datetime
from pathlib import Path


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class Workspace:
    def __init__(self, base, target: str = "", windows: bool | None = None):
        self.dir = Path(base) / "tv-debloat"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.target = target
        self.windows = (platform.system() == "Windows") if windows is None else windows
        self.restore_path = self.dir / ("restore.ps1" if self.windows else "restore.sh")
        self.disabled_path = self.dir / "disabled.txt"
        self.log_path = self.dir / "DEBLOAT-LOG.md"
        self.settings_path = self.dir / "settings_originais.txt"
        self.shots_dir = self.dir / "shots"
        self._shot_n = 0

    # ---------- backups ----------
    def new_backup_dir(self) -> Path:
        d = self.dir / f"backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def next_shot_path(self, tag: str = "shot") -> Path:
        self.shots_dir.mkdir(parents=True, exist_ok=True)
        self._shot_n += 1
        return self.shots_dir / f"{datetime.now().strftime('%H%M%S')}-{self._shot_n:03d}-{tag}.png"

    # ---------- restore script ----------
    def start_restore(self) -> None:
        """Cria o script de restauro logo no início (antes de qualquer alteração)."""
        if not self.restore_path.exists():
            if self.windows:
                head = (
                    "# restore.ps1 - reverte tudo o que o TV Debloat desativou.\n"
                    "# Uso: powershell -ExecutionPolicy Bypass -File restore.ps1\n"
                    f'$Target = "{self.target}"\n'
                    "adb connect $Target\n"
                )
            else:
                head = (
                    "#!/bin/sh\n"
                    "# restore.sh - reverte tudo o que o TV Debloat desativou.\n"
                    "# Uso: sh restore.sh\n"
                    f'TARGET="{self.target}"\n'
                    'adb connect "$TARGET"\n'
                    'ADB="adb -s $TARGET"\n'
                )
            self.restore_path.write_text(head, encoding="utf-8", newline="\n")
            if not self.windows:
                self.restore_path.chmod(0o755)
        else:
            self._append(self.restore_path, f"# --- nova sessão {_ts()} ({self.target}) ---\n")
        self._ensure_log()

    def _restore_line(self, shell_cmd: str, comment: str) -> str:
        comment = _one_line(comment)
        if self.windows:
            return f"adb -s $Target shell {shell_cmd}  # {comment}\n"
        return f"$ADB shell {shell_cmd}  # {comment}\n"

    @staticmethod
    def _append(path: Path, text: str) -> None:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def undo_all_command(self) -> str:
        if self.windows:
            return f'powershell -ExecutionPolicy Bypass -File "{self.restore_path}"'
        return f'sh "{self.restore_path}"'

    # ---------- disabled.txt ----------
    def read_disabled_entries(self) -> list[tuple[str, str, str, str]]:
        """[(pacote, data, grupo, descrição)]"""
        if not self.disabled_path.exists():
            return []
        rows = []
        for line in self.disabled_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            parts = line.split("\t") + ["", "", ""]
            rows.append((parts[0], parts[1], parts[2], parts[3]))
        return rows

    def read_disabled(self) -> list[str]:
        return [r[0] for r in self.read_disabled_entries()]

    def record_disable(self, pkg: str, group: int, desc: str, batch: str = "") -> None:
        if pkg not in self.read_disabled():
            self._append(self.disabled_path, f"{pkg}\t{_ts()}\t{group}\t{_one_line(desc)}\n")
        self._append(self.restore_path, self._restore_line(f"pm enable {pkg}", f"{_ts()} {desc}"))
        self.log(f"- `{pkg}` — {desc}. Desfazer: `adb shell pm enable {pkg}`")

    def remove_disabled(self, pkg: str, why: str = "reativado") -> None:
        rows = [r for r in self.read_disabled_entries() if r[0] != pkg]
        text = "".join(f"{p}\t{t}\t{g}\t{d}\n" for p, t, g, d in rows)
        self.disabled_path.write_text(text, encoding="utf-8", newline="\n")
        self.log(f"- `{pkg}` {why}.")

    # ---------- definições (animações) ----------
    def record_setting(self, key: str, old: str, null_value: str = "1.0") -> None:
        """Guarda o valor ORIGINAL (só da primeira vez) e acrescenta a linha de restauro."""
        old = old.strip()
        if old in ("", "null"):
            old = null_value
        known = self._read_settings()
        if key in known:
            return
        self._append(self.settings_path, f"{key}\t{old}\n")
        self._append(self.restore_path, self._restore_line(f"settings put global {key} {old}", "valor original"))
        self.log(f"- definição `{key}` (era `{old}`). Desfazer: `adb shell settings put global {key} {old}`")

    def _read_settings(self) -> dict[str, str]:
        if not self.settings_path.exists():
            return {}
        out = {}
        for line in self.settings_path.read_text(encoding="utf-8").splitlines():
            if "\t" in line:
                k, v = line.split("\t", 1)
                out[k] = v
        return out

    def read_original_settings(self) -> dict[str, str]:
        return self._read_settings()

    # ---------- DEBLOAT-LOG.md ----------
    def _ensure_log(self) -> None:
        if not self.log_path.exists():
            self.log_path.write_text(
                "# Registo do debloat\n\n"
                "Tudo o que foi feito, porquê, e o comando exato para desfazer cada alteração.\n"
                f"Script de restauro completo: `{self.restore_path.name}`\n\n",
                encoding="utf-8",
                newline="\n",
            )

    def log(self, md: str) -> None:
        self._ensure_log()
        self._append(self.log_path, md.rstrip("\n") + "\n")

    def log_section(self, title: str) -> None:
        self.log(f"\n### {title} ({_ts()})\n")

    def log_header(self, info: dict[str, str]) -> None:
        lines = [f"\n## Sessão {_ts()}\n"]
        for k, v in info.items():
            lines.append(f"- {k}: {v}")
        self.log("\n".join(lines) + "\n")


# ---------- medição de memória ----------
_MEM = re.compile(r"^\s*(Total|Free|Used|Lost) RAM:\s*([\d.,\s]+)K", re.M)


def parse_meminfo(text: str) -> dict[str, int]:
    """{'Total': kB, 'Free': kB, 'Used': kB, 'Lost': kB} a partir do `dumpsys meminfo`."""
    res: dict[str, int] = {}
    for name, num in _MEM.findall(text):
        digits = re.sub(r"\D", "", num)
        if digits and name not in res:
            res[name] = int(digits)
    return res


def memory_rows(before: dict[str, int], after: dict[str, int]) -> list[tuple[str, str, str, str]]:
    rows = []
    for key, label in (("Total", "RAM total"), ("Free", "RAM livre"), ("Used", "RAM usada")):
        b, a = before.get(key), after.get(key)
        if b is None or a is None:
            rows.append((label, "—" if b is None else f"{b / 1024:.0f} MB", "—" if a is None else f"{a / 1024:.0f} MB", "—"))
        else:
            d = (a - b) / 1024
            rows.append((label, f"{b / 1024:.0f} MB", f"{a / 1024:.0f} MB", f"{d:+.0f} MB"))
    return rows
