"""Package classification into groups (1-5), unidentified (0) and untouchable (6).

Group 6 = rule 6 of the original guide: never disabled, whatever the brand.
Classification is name-based (heuristic): it suggests, it never decides on its own.
Unidentified packages (0) must be inspected with `dumpsys package`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

GROUP_LABELS = {
    1: "Telemetry, ad tracking (ACR) and manufacturer analytics",
    2: "Manufacturer ads and content (recommendation rows, feeds, demo mode)",
    3: "Dispensable background services (cleaners, optimizers)",
    4: "Preinstalled apps",
    5: "Up to you (streaming, voice assistant, Chromecast, mirroring, updates)",
    0: "Unidentified (check before touching)",
    6: "Untouchable (the TV needs these)",
}

GROUP_DEFAULT_DESC = {
    1: "Telemetry, tracking or analytics",
    2: "Manufacturer ads or recommended content",
    3: "Dispensable background service",
    4: "Preinstalled app",
    5: "App or service that is up to you",
    0: "Unidentified package",
    6: "Required for the TV to work",
}

STOCK_LAUNCHERS = {
    "com.google.android.apps.tv.launcherx",  # Google TV
    "com.google.android.tvlauncher",  # Android TV
}
SETUP_WIZARD = "com.google.android.tungsten.setupwraith"
LAUNCHER_RELATED = STOCK_LAUNCHERS | {SETUP_WIZARD}

PROTECTED_EXACT = {
    "android": "Android system core",
    "com.android.vending": "Play Store",
    "com.google.android.gms": "Google Play Services",
    "com.google.android.gsf": "Google Services Framework",
    "com.android.location.fused": "system location (disabling causes a boot loop)",
    "com.android.tv": "TV app (inputs and channels)",
    "com.android.systemui": "system UI",
    "com.android.settings": "settings",
    "com.android.shell": "system shell",
    "com.tcl.suspension": "remote's Inputs/Source menu (lets you switch to HDMI)",
    "com.tcl.ttvs": "system updates (Network/USB)",
    "com.tcl.tv": "HDMI/antenna input service",
    "com.tcl.tvinput": "HDMI/antenna input service",
    "com.tcl.providers.config": "base configuration (disabling cuts Wi-Fi)",
    "com.tcl.initsetup": "initial setup (disabling cuts Wi-Fi)",
    "com.google.android.tv.remote.service": "remote",
    "com.tcl.tcl_bt_rcu_service": "Bluetooth remote",
    "com.tcl.autopair": "remote pairing",
}

PROTECTED_REGEX = [
    (re.compile(p), reason)
    for p, reason in (
        (r"(^|\.)inputmethod(\.|$)", "on-screen keyboard"),
        (r"^com\.google\.android\.gms(\.|$)", "Google Play Services"),
        (r"^com\.android\.vending(\.|$)", "Play Store"),
        (r"^com\.google\.android\.gsf(\.|$)", "Google Services Framework"),
        (r"^com\.android\.providers\.", "system data provider"),
        (
            r"^com\.android\.(bluetooth|networkstack|wifi|nfc|phone|server\.telecom|keychain|"
            r"certinstaller|inputdevices|externalstorage|documentsui|storagemanager|"
            r"permissioncontroller|packageinstaller)",
            "essential system service",
        ),
        (
            r"^com\.google\.android\.(permissioncontroller|packageinstaller|ext\.services|ext\.shared)",
            "essential system service",
        ),
        (r"webview", "WebView (many apps depend on it)"),
        (r"bluetooth|(^|[._])btservice|(^|[._])bt_", "Bluetooth"),
        (r"(^|[._])(rcu|autopair|remotecontrol)([._]|$)", "remote"),
        (r"remote\.service", "remote"),
        (r"tvinput|tvservice|tvsettings|(^|[._])tuner([._]|$)", "HDMI/antenna inputs"),
        (r"quickpanel|inputsource|input_source|sourceswitch", "Inputs/Source menu"),
        (r"(^|[._])(hdmi|hdmicec|cec)([._]|$)", "HDMI/CEC"),
        (r"(^|\.)settings(\.|$)", "settings"),
        (r"overlay|\.theme\.|^com\.android\.internal", "system resources/overlays"),
    )
]

# `dumpsys package` markers that make a package untouchable.
RISK_MARKERS = {
    "android.media.tv.TvInputService": "TV input service (HDMI/antenna)",
    "android.view.InputMethod": "on-screen keyboard",
    "android.intent.category.HOME": "claims the home screen",
    "android.bluetooth.": "Bluetooth",
    "android.accounts.AccountAuthenticator": "account authenticator",
    "android.telecom.": "telephony",
}

KNOWN_DESCRIPTIONS = {
    "com.google.android.tvrecommendations": "Recommendation rows of the original home screen",
    "com.google.android.videos": "Google TV / Play Movies",
    "com.google.android.play.games": "Play Games",
    "com.google.android.music": "Google Play Music",
    "com.google.android.youtube.tvmusic": "YouTube Music",
    "com.google.android.feedback": "Google feedback agent",
    "com.google.android.katniss": "Voice search / Assistant (remote microphone)",
    "com.google.android.googlequicksearchbox": "Google app / Assistant",
    "com.google.android.apps.mediashell": "Built-in Chromecast",
    "com.google.android.apps.tv.launcherx": "Original Google TV home screen",
    "com.google.android.tvlauncher": "Original Android TV home screen",
    SETUP_WIZARD: "Setup wizard (can steal the home screen)",
}

_G2_EXACT = {"com.google.android.tvrecommendations"}
_G3_EXACT = {"com.google.android.feedback"}
_G4_EXACT = {
    "com.google.android.videos",
    "com.google.android.play.games",
    "com.google.android.music",
    "com.google.android.youtube.tvmusic",
}
_G5_STREAMING = (
    "netflix", "youtube", "amazon", "primevideo", "disney", "hbo", "hulu", "spotify",
    "plex", "tubi", "pluto", "twitch", "appletv", "rakuten", "dazn", "tidal", "deezer",
    "crunchyroll", "peacock", "paramount", "discovery", "globo", "skygo", "vudu",
)
_G5_VOICE = ("katniss", "googlequicksearchbox", "voicesearch", "assistant", "alexa", "voiceassist")
_G5_CAST = ("mediashell", "chromecast", "miracast", "airplay", "dlna", "screenshare",
            "screenmirror", "wfd", "castservice")
_G5_CAST_TOKENS = {"cast", "mirror", "mirroring"}
_G5_UPDATE_TOKENS = {"ota", "update", "updater", "systemupdate", "swupdate", "upgrade", "sysupdate"}
_G5_UPDATE_SUB = ("systemupdate", "swupdate", "otaupdate")

_G1_SUB = ("samba", "alphonso", "anoki", "analytics", "telemetry", "tracking", "tracker",
           "advert", "adservice", "datacollect", "crashlytics", "acrcloud")
_G1_TOKENS = {"ads", "ad", "acr", "metrics", "stats", "statistics"}
_G2_SUB = ("recommend", "retaildemo", "storedemo", "contentfeed")
_G2_TOKENS = {"feed", "feeds", "demo", "promo", "promotions", "sponsored", "newsfeed"}
_G3_TOKENS = {"cleaner", "clean", "booster", "boost", "optimizer", "optimize", "speedup",
              "memclean", "cleanmaster"}
_G4_TOKENS = {"weather", "games", "game", "gallery", "tvmusic"}


@dataclass(frozen=True)
class Verdict:
    group: int
    reason: str
    description: str


def _tokens(low: str) -> set[str]:
    return set(re.split(r"[._]", low))


def _has_sub(low: str, subs) -> bool:
    return any(s in low for s in subs)


class Classifier:
    def __init__(self, home_packages=(), allow_launcher_disable: bool = False, extra_protected=None):
        self.home_packages = set(home_packages)
        self.allow_launcher_disable = allow_launcher_disable
        self.extra_protected = dict(extra_protected or {})  # brand/system-specific protections

    def classify(self, pkg: str) -> Verdict:
        low = pkg.lower()
        desc = KNOWN_DESCRIPTIONS.get(pkg)

        if pkg in self.extra_protected:
            return Verdict(6, self.extra_protected[pkg], desc or GROUP_DEFAULT_DESC[6])

        if "flauncher" in low:
            return Verdict(6, "new home screen (FLauncher)", "FLauncher, the new home screen")

        if pkg in LAUNCHER_RELATED:
            if self.allow_launcher_disable:
                return Verdict(4, "original home screen (FLauncher is already the default)", desc or "Original home screen")
            return Verdict(
                6,
                "current home screen — only after installing FLauncher and setting it as default",
                desc or "Original home screen",
            )
        if pkg in self.home_packages:
            return Verdict(6, "claims the home screen", desc or "Home screen")

        if pkg in PROTECTED_EXACT:
            return Verdict(6, PROTECTED_EXACT[pkg], desc or GROUP_DEFAULT_DESC[6])
        for rx, reason in PROTECTED_REGEX:
            if rx.search(low):
                return Verdict(6, reason, desc or GROUP_DEFAULT_DESC[6])

        tokens = _tokens(low)

        if pkg in _G4_EXACT:
            return Verdict(4, "known preinstalled app", desc or GROUP_DEFAULT_DESC[4])
        if pkg in _G2_EXACT:
            return Verdict(2, "recommendation rows", desc or GROUP_DEFAULT_DESC[2])
        if pkg in _G3_EXACT:
            return Verdict(3, "feedback service", desc or GROUP_DEFAULT_DESC[3])

        # Group 5 before the rest: what is up to you is never suggested by default.
        if _has_sub(low, _G5_STREAMING):
            return Verdict(5, "streaming app — your call", desc or GROUP_DEFAULT_DESC[5])
        if _has_sub(low, _G5_VOICE):
            return Verdict(5, "voice assistant — your call", desc or GROUP_DEFAULT_DESC[5])
        if _has_sub(low, _G5_CAST) or tokens & _G5_CAST_TOKENS:
            return Verdict(5, "Chromecast/mirroring — your call", desc or GROUP_DEFAULT_DESC[5])
        if tokens & _G5_UPDATE_TOKENS or _has_sub(low, _G5_UPDATE_SUB):
            return Verdict(5, "system updates — your call", desc or GROUP_DEFAULT_DESC[5])

        if _has_sub(low, _G1_SUB) or tokens & _G1_TOKENS:
            return Verdict(1, "name suggests telemetry/tracking/ads", desc or GROUP_DEFAULT_DESC[1])
        if _has_sub(low, _G2_SUB) or tokens & _G2_TOKENS:
            return Verdict(2, "name suggests recommendations/content/demo", desc or GROUP_DEFAULT_DESC[2])
        if tokens & _G3_TOKENS:
            return Verdict(3, "name suggests cleaner/optimizer", desc or GROUP_DEFAULT_DESC[3])
        if tokens & _G4_TOKENS:
            return Verdict(4, "probably a preinstalled app", desc or GROUP_DEFAULT_DESC[4])

        return Verdict(0, "name does not say what it does — inspect with dumpsys package", GROUP_DEFAULT_DESC[0])


def risk_from_dumpsys(text: str) -> list[str]:
    """Reasons why `dumpsys package` shows the package is untouchable."""
    return [reason for marker, reason in RISK_MARKERS.items() if marker in text]


_COMPONENT = re.compile(r"\s[0-9a-f]+ (\S+/\S+) filter ")
_ACTION = re.compile(r'Action: "([^"]+)"')


def summarize_dumpsys(text: str, limit: int = 12) -> str:
    """Readable summary: declared activities/services/receivers and filter actions."""
    sections = {"Activity Resolver Table": "Activities", "Receiver Resolver Table": "Receivers",
                "Service Resolver Table": "Services"}
    current = None
    comps: dict[str, list[str]] = {v: [] for v in sections.values()}
    actions: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.rstrip(":") in sections:
            current = sections[stripped.rstrip(":")]
            continue
        m = _COMPONENT.search(line)
        if m and current and m.group(1) not in comps[current]:
            comps[current].append(m.group(1))
        a = _ACTION.search(line)
        if a and a.group(1) not in actions:
            actions.append(a.group(1))
    out = []
    for name, items in comps.items():
        if items:
            out.append(f"{name} ({len(items)}): " + ", ".join(items[:limit]) + (" …" if len(items) > limit else ""))
    if actions:
        out.append("Declared actions: " + ", ".join(actions[:limit]) + (" …" if len(actions) > limit else ""))
    return "\n".join(out) or "(dumpsys showed no declared activities/services)"
