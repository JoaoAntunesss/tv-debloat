"""Command guard: only what is on an allowlist gets through.

Implements rules 1, 2 and 5 of the original guide:
- no `pm uninstall` (only `pm disable-user --user 0`, reversible with `pm enable`);
- no root, bootloader, flash, rm, setprop...;
- one command per call (no `;`, `&&`, `|`, redirections...).

Anything that does not exactly match a pattern below is refused.
"""
from __future__ import annotations

import re


class CommandRefused(Exception):
    """O programa recusou-se a executar este comando na TV."""


_CHAIN = re.compile(r"[;&|`<>\n\r]|\$\(")
_PKG = r"[A-Za-z0-9_.]+"
_ANIM = r"(?:window_animation_scale|transition_animation_scale|animator_duration_scale)"
_TMP_APK = r"/data/local/tmp/tvdebloat-[A-Za-z0-9]{8,64}\.apk"

_ALLOWED = [
    re.compile(p)
    for p in (
        r"^pm list packages(?: -[fdse3])*$",
        rf"^pm disable-user --user 0 {_PKG}$",
        rf"^pm enable {_PKG}$",
        r"^pm trim-caches 999G$",
        rf"^pm path {_PKG}$",
        r"^getprop(?: [A-Za-z0-9_.\-]+)?$",
        r"^settings list (?:global|secure|system)$",
        rf"^settings get global {_ANIM}$",
        rf"^settings put global {_ANIM} [0-9](?:\.[0-9]+)?$",
        r"^dumpsys meminfo$",
        rf"^dumpsys package {_PKG}$",
        r"^dumpsys (?:window(?: windows)?|activity activities)$",
        r"^input keyevent KEYCODE_[A-Z0-9_]+$",
        rf"^monkey -p {_PKG} -c android\.intent\.category\.(?:LAUNCHER|LEANBACK_LAUNCHER) 1$",
        r"^cmd package query-activities -a android\.intent\.action\.MAIN -c android\.intent\.category\.HOME$",
        r"^cmd package resolve-activity --brief -a android\.intent\.action\.MAIN -c android\.intent\.category\.HOME$",
        rf"^cmd package set-home-activity {_PKG}/[A-Za-z0-9_.$]+$",
        rf"^cmd role add-role-holder --user 0 android\.app\.role\.HOME {_PKG}$",
        r"^cmd role get-role-holders --user 0 android\.app\.role\.HOME$",
        r"^reboot$",
        # install apps (never uninstall): only files this program pushed to the temp folder
        rf"^pm install -r {_TMP_APK}$",
        rf"^rm {_TMP_APK}$",
        # private DNS (reversible): only the three modes and a simple hostname
        r"^settings get global (?:private_dns_mode|private_dns_specifier)$",
        r"^settings put global private_dns_mode (?:hostname|opportunistic|off)$",
        r"^settings put global private_dns_specifier [A-Za-z0-9][A-Za-z0-9.-]{1,252}\.[A-Za-z]{2,63}$",
    )
]


def check_shell(cmd: str) -> str:
    """Devolve o comando limpo, ou levanta CommandRefused."""
    cmd = cmd.strip()
    if not cmd:
        raise CommandRefused("Empty command.")
    if _CHAIN.search(cmd):
        raise CommandRefused(
            "Recusado: um comando por chamada (sem ';', '&&', '|' nem redirecionamentos)."
        )
    if "uninstall" in cmd:
        raise CommandRefused("Refused: this program never uninstalls anything (rule 1).")
    for rx in _ALLOWED:
        if rx.match(cmd):
            return cmd
    raise CommandRefused(f"Refused: command is not on the safe-command list: {cmd!r}")
