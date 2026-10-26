"""Supported TV systems and brands, what each allows, and known warnings.

Sources (researched 2026-10-26): the cleanyourtv (MIT, Android TV/Google TV) and dumbtv
(MIT, Fire TV; docs/OTHER-TVS.md for Samsung/LG/Roku) repositories. Concrete per-model package names
live in those projects' lists: only what is safe to generalize is kept here.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    adb: bool  # allows pm disable-user over ADB?
    launcher_swap: bool  # allows swapping the home screen?
    dns_on_device: bool  # allows Android private DNS via ADB?
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Brand:
    name: str
    notes: tuple[str, ...] = ()
    extra_protected: dict = field(default_factory=dict)  # package -> reason


PLATFORMS: dict[str, Platform] = {
    "androidtv": Platform(
        "androidtv", "Android TV / Google TV", adb=True, launcher_swap=True, dns_on_device=True,
        notes=("The best-supported case: disable packages over ADB and swap the home screen.",),
    ),
    "firetv": Platform(
        "firetv", "Amazon Fire TV (Fire OS)", adb=True, launcher_swap=False, dns_on_device=False,
        notes=(
            "Fire OS does not let a third-party launcher take over the Home button: only debloat is possible.",
            "Blocking Amazon servers via DNS can also block Fire OS updates.",
            "The 2015 Fire TV Box (Fire OS 5) rejects all 'pm' commands.",
            "New Fire TVs running VegaOS are not supported (not even by SmartTube).",
        ),
    ),
    "tizen": Platform(
        "tizen", "Samsung (Tizen)", adb=False, launcher_swap=False, dns_on_device=False,
        notes=("No shell or package changes on the device.",),
    ),
    "webos": Platform(
        "webos", "LG (webOS)", adb=False, launcher_swap=False, dns_on_device=False,
        notes=("Packages only in developer/homebrew mode; no launcher swap.",),
    ),
    "roku": Platform(
        "roku", "Roku (and Roku TVs)", adb=False, launcher_swap=False, dns_on_device=False,
        notes=("No shell, no packages, no alternative launcher.",),
    ),
    "other": Platform(
        "other", "Other (Vidaa, Netrange, manufacturer Linux…)", adb=False, launcher_swap=False,
        dns_on_device=False,
        notes=("Usually closed: you can only act via the network or the TV settings.",),
    ),
}

_GEN = "Always back up first; per-model lists are heuristics and the TV may have packages I do not know."

BRANDS: dict[str, list[Brand]] = {
    "androidtv": [
        Brand("TCL", (
            "There are known traps (Inputs menu, updates, Wi-Fi, remote): they are protected.",
            "Some Chinese-market models refuse any alternative launcher.",
        )),
        Brand("Sony", ("Some models have firmware/region quirks. " + _GEN,)),
        Brand("Xiaomi / Redmi", (
            "The Redmi TV MiTV-ANTL0 runs Android 5.1.1 and is not Android TV: check your model.",
        )),
        Brand("Philips", (_GEN,)),
        Brand("Hisense", (_GEN,)),
        Brand("Skyworth", ("The 8R40_K5C model runs Android 8.0 and is not Google TV.",)),
        Brand("Panasonic", (_GEN,)),
        Brand("Sharp", (_GEN,)),
        Brand("Thomson", (_GEN,)),
        Brand("JVC", (_GEN,)),
        Brand("Haier", (_GEN,)),
        Brand("OnePlus", (_GEN,)),
        Brand("NVIDIA Shield", (_GEN,)),
        Brand("Google (Chromecast with Google TV / TV Streamer)", (
            "May require 'Wireless debugging' with a pairing code (use the pairing field).",
        )),
        Brand("Other brand", (_GEN,)),
    ],
    "firetv": [
        Brand("Fire TV Stick / Cube", (), {"com.amazon.tv.launcher": "Fire OS home screen (cannot be replaced)"}),
        Brand("Fire TV Edition (Insignia, Toshiba TVs, etc.)", (),
              {"com.amazon.tv.launcher": "Fire OS home screen (cannot be replaced)"}),
    ],
    "tizen": [Brand("Samsung")],
    "webos": [Brand("LG")],
    "roku": [Brand("Roku / Roku TV")],
    "other": [Brand("Vidaa (Hisense)"), Brand("Other")],
}

# Text for platforms without ADB (the possible action is at network level or in the TV settings).
_NETWORK_COMMON = (
    "What works on any closed TV, without modifying it:\n"
    "• Block ads and telemetry at the router/network with a filtering DNS: NextDNS, AdGuard Home or Pi-hole.\n"
    "• If you use the TV only as a screen (HDMI, external box), do not give it internet access.\n"
    "• Ads inside streaming/YouTube apps remain: for that use an Android TV/Fire TV box (e.g. with SmartTube) "
    "connected over HDMI.\n"
)

_ON_TV = {
    "tizen": (
        "TV settings (names vary by year and version; check your menu):\n"
        "• Terms & privacy: turn off 'Viewing information services' and interest-based ads.\n"
        "• Do not accept optional services/terms at first start-up."
    ),
    "webos": (
        "TV settings (names vary by year and version; check your menu):\n"
        "• Turn off 'Live Plus' (content recognition) and limit ad tracking.\n"
        "• Turn off recommendations/promotions on the home screen, if present."
    ),
    "roku": (
        "TV settings (names vary by version; check your menu):\n"
        "• Privacy: turn off 'Use info from TV inputs' (content recognition).\n"
        "• Limit ad tracking."
    ),
    "other": "Look in the privacy settings for content recognition (ACR) and personalized ads.",
}


def network_guide(platform_key: str) -> str:
    return _NETWORK_COMMON + "\n" + _ON_TV.get(platform_key, "")


def get_brand(platform_key: str, name: str) -> Brand | None:
    for b in BRANDS.get(platform_key, []):
        if b.name == name:
            return b
    return None
