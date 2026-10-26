"""TV simulada para o modo demonstração e para gerar capturas de ecrã (não fala com nenhuma TV real).

Usa nomes de pacotes fictícios (com.exampletv.*) misturados com alguns nomes reais conhecidos, só para
mostrar como a interface funciona. Precisa do Pillow para desenhar o ecrã da TV.
"""
from __future__ import annotations

import io
import re

from .adb import AdbError

_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

PROTECTED_AND_SYSTEM = [
    "com.tcl.suspension", "com.tcl.ttvs", "com.tcl.tv", "com.tcl.tvinput", "com.tcl.providers.config",
    "com.tcl.initsetup", "com.google.android.tv.remote.service", "com.tcl.tcl_bt_rcu_service", "com.tcl.autopair",
    "com.android.vending", "com.google.android.gms", "com.google.android.gsf", "com.android.location.fused",
    "com.google.android.inputmethod.latin", "com.android.systemui", "com.android.settings",
    "com.android.providers.media", "com.google.android.tvlauncher",
    # grupo 1
    "com.exampletv.acr", "com.exampletv.analytics", "com.exampletv.adservice",
    # grupo 2
    "com.google.android.tvrecommendations", "com.exampletv.recommend", "com.exampletv.contentfeed",
    "com.exampletv.retaildemo",
    # grupo 3
    "com.exampletv.cleaner", "com.exampletv.boost",
    # grupo 4
    "com.google.android.videos", "com.google.android.play.games", "com.exampletv.weather",
    # grupo 5
    "com.netflix.ninja", "com.google.android.youtube.tv", "com.google.android.katniss",
    "com.google.android.apps.mediashell", "com.exampletv.ota",
    # não identificados
    "com.exampletv.helper", "com.exampletv.misc",
]
USER_PACKAGES = ["me.efesser.flauncher"]

PROPS = {
    "ro.product.brand": "TCL",
    "ro.product.model": "Smart TV Pro (simulada)",
    "ro.build.version.release": "12",
    "ro.build.version.sdk": "31",
    "sys.boot_completed": "1",
}

_HOME_ACTIVITIES = {
    "com.google.android.tvlauncher": "com.google.android.tvlauncher.MainActivity",
    "me.efesser.flauncher": "me.efesser.flauncher.MainActivity",
}


class SimBackend:
    name = "simulada"

    def __init__(self):
        self.target = None
        self.disabled: set[str] = set()
        self.home_default = "com.google.android.tvlauncher"
        self.focus = self.home_default
        self.overlay = None  # "inputs"
        self.settings = {
            "window_animation_scale": "1.0", "transition_animation_scale": "1.0",
            "animator_duration_scale": "1.0", "private_dns_mode": "opportunistic",
        }
        self.total_kb = 1_847_068
        self.base_free_kb = 612_000
        self.rebooted = False
        self.installed_apks = []

    # ------------------------------------------------------------------ ligação
    def connect(self, host, port):
        self.target = f"{host}:{port}"
        return f"connected to {self.target} (TV simulada)"

    def pair(self, host_port, code):
        return "Successfully paired (simulado)"

    def state(self):
        return "device"

    def disconnect(self):
        pass

    def push(self, local, remote):
        self.installed_apks.append(remote)
        return "pushed"

    # ------------------------------------------------------------------ estado
    def _free_kb(self):
        extra = 14_000 * len([p for p in self.disabled if p in PROTECTED_AND_SYSTEM])
        if self.rebooted:
            extra += 60_000
        return self.base_free_kb + extra

    def _meminfo(self):
        free = self._free_kb()
        used = self.total_kb - free - 38_000
        return (
            "Applications Memory Usage (in Kilobytes):\n\n"
            f"Total RAM: {self.total_kb:,}K (status normal)\n"
            f" Free RAM: {free:,}K (  196,300K cached pss +   500,000K cached kernel +   {free - 696_300:,}K free)\n"
            f" Used RAM: {used:,}K\n"
            f" Lost RAM:    38,000K\n"
        )

    def _all_packages(self):
        for p in PROTECTED_AND_SYSTEM:
            yield p, f"/system/app/{p}/{p}.apk"
        for p in USER_PACKAGES:
            yield p, f"/data/app/~~sim/{p}-1/base.apk"

    def _installed(self, pkg):
        return any(pkg == p for p, _ in self._all_packages())

    # ------------------------------------------------------------------ comandos
    def shell(self, cmd, timeout=60):
        if cmd == "pm list packages -f":
            return "\n".join(f"package:{path}={name}" for name, path in self._all_packages()) + "\n"
        if cmd == "pm list packages -d":
            return "".join(f"package:{p}\n" for p in sorted(self.disabled))
        if cmd == "getprop":
            return "".join(f"[{k}]: [{v}]\n" for k, v in PROPS.items())
        if cmd.startswith("getprop "):
            return PROPS.get(cmd.split()[1], "") + "\n"
        if cmd.startswith("settings list"):
            return "".join(f"{k}={v}\n" for k, v in self.settings.items()) or "x=y\n"
        if cmd.startswith("settings get global"):
            return self.settings.get(cmd.split()[-1], "null") + "\n"
        if cmd.startswith("settings put global"):
            _, _, _, key, val = cmd.split()
            self.settings[key] = val
            return ""
        if cmd == "dumpsys meminfo":
            return self._meminfo()
        if cmd.startswith("dumpsys package "):
            pkg = cmd.split()[-1]
            return (
                f"Packages:\n  Package [{pkg}]\nActivity Resolver Table:\n  Non-Data Actions:\n"
                f"      android.intent.action.MAIN:\n        1a2b3c {pkg}/.MainActivity filter 4d5e6f\n"
                '          Action: "android.intent.action.MAIN"\n'
                f"Service Resolver Table:\n  Non-Data Actions:\n      com.exampletv.action.SYNC:\n"
                f"        7a8b9c {pkg}/.SyncService filter 0d1e2f\n          Action: \"com.exampletv.action.SYNC\"\n"
            )
        if cmd.startswith("dumpsys window"):
            return (f"WINDOW MANAGER\n  mCurrentFocus=Window{{abc123 u0 {self.focus}/"
                    f"{self.focus}.MainActivity}}\n")
        if cmd.startswith("input keyevent"):
            key = cmd.split()[-1]
            if key == "KEYCODE_HOME":
                self.focus, self.overlay = self.home_default, None
            elif key == "KEYCODE_TV_INPUT":
                self.overlay = "inputs"
            elif key == "KEYCODE_TV_INPUT_HDMI_1":
                self.focus, self.overlay = "com.tcl.tvinput", None
            elif key == "KEYCODE_BACK":
                self.overlay = None
            return ""
        if cmd.startswith("monkey -p"):
            pkg = cmd.split()[2]
            if self._installed(pkg) and pkg not in self.disabled:
                self.focus, self.overlay = pkg, None
                return "Events injected: 1\n"
            return "** No activities found to run, monkey aborted.\n"
        if cmd.startswith("cmd package query-activities"):
            out = "2 activities found:\n"
            for i, (pkg, act) in enumerate(_HOME_ACTIVITIES.items()):
                out += f"  Activity #{i}:\n    ActivityInfo:\n      name={act}\n      packageName={pkg}\n"
            return out
        if cmd.startswith("cmd package resolve-activity"):
            return f"priority=0 preferredOrder=0\n{self.home_default}/.MainActivity\n"
        if cmd.startswith("cmd package set-home-activity"):
            self.home_default = cmd.split()[-1].split("/")[0]
            return "Success\n"
        m = re.match(r"pm disable-user --user 0 (\S+)$", cmd)
        if m:
            if not self._installed(m.group(1)):
                return f"Unknown package: {m.group(1)}\n"
            self.disabled.add(m.group(1))
            return f"Package {m.group(1)} new state: disabled-user\n"
        m = re.match(r"pm enable (\S+)$", cmd)
        if m:
            self.disabled.discard(m.group(1))
            return f"Package {m.group(1)} new state: enabled\n"
        if cmd.startswith("pm install -r"):
            return "Success\n"
        if cmd == "pm trim-caches 999G":
            return ""
        if cmd == "reboot":
            self.rebooted = True
            self.focus, self.overlay = self.home_default, None
            return ""
        if cmd.startswith("rm "):
            return ""
        raise AdbError(f"A TV simulada não conhece o comando: {cmd}")

    # ------------------------------------------------------------------ ecrã
    def screencap(self):
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            raise AdbError("O modo demonstração precisa do Pillow: pip install pillow")
        W, H = 960, 540
        img = Image.new("RGB", (W, H), (14, 18, 32))
        d = ImageDraw.Draw(img)
        for y in range(H):  # fundo em gradiente
            c = int(18 + 30 * y / H)
            d.line([(0, y), (W, y)], fill=(c // 2, c // 2 + 6, c + 20))

        def font(size):
            try:
                return ImageFont.truetype(_FONT, size)
            except OSError:
                return ImageFont.load_default(size=size)

        def tile(x, y, w, h, color, label, sub=None):
            d.rounded_rectangle([x, y, x + w, y + h], radius=14, fill=color)
            d.text((x + 14, y + h - 34), label, font=font(20), fill=(255, 255, 255))
            if sub:
                d.text((x + 14, y + 10), sub, font=font(14), fill=(255, 235, 150))

        if self.overlay == "inputs" and self.focus == self.home_default:
            self._draw_home(d, font, tile, W, H)
            d.rectangle([0, 0, 300, H], fill=(10, 10, 14))
            d.text((24, 28), "Entradas", font=font(28), fill=(255, 255, 255))
            for i, name in enumerate(("TV (antena)", "HDMI 1", "HDMI 2", "AV")):
                d.rounded_rectangle([20, 90 + i * 70, 280, 140 + i * 70], radius=10,
                                    fill=(60, 90, 160) if i == 1 else (36, 38, 52))
                d.text((38, 102 + i * 70), name, font=font(22), fill=(255, 255, 255))
        elif self.focus == "com.tcl.tvinput":
            d.text((W // 2 - 150, H // 2 - 40), "HDMI 1", font=font(60), fill=(255, 255, 255))
            d.text((W // 2 - 110, H // 2 + 40), "Sem sinal", font=font(28), fill=(170, 170, 180))
        elif self.focus != self.home_default:
            d.rectangle([0, 0, W, H], fill=(24, 24, 28))
            d.text((W // 2 - 220, H // 2 - 30), self.focus.split(".")[-1].upper() + " (simulada)",
                   font=font(44), fill=(255, 255, 255))
        else:
            self._draw_home(d, font, tile, W, H)

        d.text((18, H - 30), "TV SIMULADA — captura de demonstração", font=font(16), fill=(255, 220, 120))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    def _draw_home(self, d, font, tile, W, H):
        if self.home_default == "me.efesser.flauncher":
            d.text((40, 24), "FLauncher", font=font(30), fill=(255, 255, 255))
            colors = [(120, 70, 160), (30, 120, 140), (160, 70, 70), (60, 120, 70), (140, 110, 40),
                      (70, 80, 150), (110, 60, 110), (40, 110, 110)]
            names = ["Apps", "Vídeo", "Música", "Jogos", "Definições", "Ficheiros", "Fotos", "Mais"]
            for i, (c, n) in enumerate(zip(colors, names)):
                tile(40 + (i % 4) * 225, 100 + (i // 4) * 190, 205, 170, c, n)
        else:
            d.text((40, 24), "Início", font=font(30), fill=(255, 255, 255))
            tile(40, 90, 880, 150, (150, 60, 60), "Em destaque para ti", sub="PATROCINADO")
            d.text((40, 258), "Recomendado", font=font(22), fill=(220, 220, 230))
            for i, c in enumerate([(70, 80, 150), (60, 120, 70), (140, 110, 40), (110, 60, 110)]):
                tile(40 + i * 225, 296, 205, 140, c, f"Sugestão {i + 1}", sub="ANÚNCIO" if i == 1 else None)
