"""Classificação de pacotes em grupos (1-5), não identificados (0) e intocáveis (6).

Grupo 6 = regra 6 do guia original: nunca se desativa, seja qual for a marca.
A classificação é por nomes (heurística): serve para sugerir, nunca para decidir
sozinha. Pacotes não identificados (0) exigem inspeção com `dumpsys package`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

GROUP_LABELS = {
    1: "Telemetria, rastreio de anúncios (ACR) e analytics do fabricante",
    2: "Anúncios e conteúdos do fabricante (linhas recomendadas, feeds, modo demo)",
    3: "Serviços em segundo plano dispensáveis (limpadores, otimizadores)",
    4: "Apps pré-instaladas",
    5: "Depende de ti (streaming, assistente de voz, Chromecast, espelhamento, atualizações)",
    0: "Não identificados (verificar antes de mexer)",
    6: "Intocáveis (a TV precisa disto)",
}

GROUP_DEFAULT_DESC = {
    1: "Telemetria, rastreio ou analytics",
    2: "Anúncios ou conteúdos recomendados do fabricante",
    3: "Serviço em segundo plano dispensável",
    4: "App pré-instalada",
    5: "App ou serviço que depende de ti",
    0: "Pacote não identificado",
    6: "Necessário para a TV funcionar",
}

STOCK_LAUNCHERS = {
    "com.google.android.apps.tv.launcherx",  # Google TV
    "com.google.android.tvlauncher",  # Android TV
}
SETUP_WIZARD = "com.google.android.tungsten.setupwraith"
LAUNCHER_RELATED = STOCK_LAUNCHERS | {SETUP_WIZARD}

PROTECTED_EXACT = {
    "android": "núcleo do sistema Android",
    "com.android.vending": "Play Store",
    "com.google.android.gms": "Google Play Services",
    "com.google.android.gsf": "Google Services Framework",
    "com.android.location.fused": "localização do sistema (desativar causa boot loop)",
    "com.android.tv": "app de TV (entradas e canais)",
    "com.android.systemui": "interface do sistema",
    "com.android.settings": "definições",
    "com.android.shell": "shell do sistema",
    "com.tcl.suspension": "menu Entradas/Source do comando (permite mudar para HDMI)",
    "com.tcl.ttvs": "atualizações do sistema (Rede/USB)",
    "com.tcl.tv": "serviço de entradas HDMI/antena",
    "com.tcl.tvinput": "serviço de entradas HDMI/antena",
    "com.tcl.providers.config": "configuração base (desativar corta o Wi-Fi)",
    "com.tcl.initsetup": "configuração inicial (desativar corta o Wi-Fi)",
    "com.google.android.tv.remote.service": "comando",
    "com.tcl.tcl_bt_rcu_service": "comando Bluetooth",
    "com.tcl.autopair": "emparelhamento do comando",
}

PROTECTED_REGEX = [
    (re.compile(p), reason)
    for p, reason in (
        (r"(^|\.)inputmethod(\.|$)", "teclado no ecrã"),
        (r"^com\.google\.android\.gms(\.|$)", "Google Play Services"),
        (r"^com\.android\.vending(\.|$)", "Play Store"),
        (r"^com\.google\.android\.gsf(\.|$)", "Google Services Framework"),
        (r"^com\.android\.providers\.", "fornecedor de dados do sistema"),
        (
            r"^com\.android\.(bluetooth|networkstack|wifi|nfc|phone|server\.telecom|keychain|"
            r"certinstaller|inputdevices|externalstorage|documentsui|storagemanager|"
            r"permissioncontroller|packageinstaller)",
            "serviço essencial do sistema",
        ),
        (
            r"^com\.google\.android\.(permissioncontroller|packageinstaller|ext\.services|ext\.shared)",
            "serviço essencial do sistema",
        ),
        (r"webview", "WebView (muitas apps dependem dele)"),
        (r"bluetooth|(^|[._])btservice|(^|[._])bt_", "Bluetooth"),
        (r"(^|[._])(rcu|autopair|remotecontrol)([._]|$)", "comando"),
        (r"remote\.service", "comando"),
        (r"tvinput|tvservice|tvsettings|(^|[._])tuner([._]|$)", "entradas HDMI/antena"),
        (r"quickpanel|inputsource|input_source|sourceswitch", "menu Entradas/Source"),
        (r"(^|[._])(hdmi|hdmicec|cec)([._]|$)", "HDMI/CEC"),
        (r"(^|\.)settings(\.|$)", "definições"),
        (r"overlay|\.theme\.|^com\.android\.internal", "recursos/overlays do sistema"),
    )
]

# Marcadores no `dumpsys package` que tornam um pacote intocável.
RISK_MARKERS = {
    "android.media.tv.TvInputService": "serviço de entradas de TV (HDMI/antena)",
    "android.view.InputMethod": "teclado no ecrã",
    "android.intent.category.HOME": "reclama o ecrã inicial",
    "android.bluetooth.": "Bluetooth",
    "android.accounts.AccountAuthenticator": "autenticador de contas",
    "android.telecom.": "telefonia",
}

KNOWN_DESCRIPTIONS = {
    "com.google.android.tvrecommendations": "Linhas de recomendações do ecrã inicial original",
    "com.google.android.videos": "Google TV / Play Filmes",
    "com.google.android.play.games": "Play Jogos",
    "com.google.android.music": "Google Play Música",
    "com.google.android.youtube.tvmusic": "YouTube Music",
    "com.google.android.feedback": "Agente de feedback da Google",
    "com.google.android.katniss": "Pesquisa por voz / Assistente (microfone do comando)",
    "com.google.android.googlequicksearchbox": "Aplicação Google / Assistente",
    "com.google.android.apps.mediashell": "Chromecast integrado",
    "com.google.android.apps.tv.launcherx": "Ecrã inicial original da Google TV",
    "com.google.android.tvlauncher": "Ecrã inicial original da Android TV",
    SETUP_WIZARD: "Assistente de configuração (pode roubar o ecrã inicial)",
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
        self.extra_protected = dict(extra_protected or {})  # proteções específicas da marca/sistema

    def classify(self, pkg: str) -> Verdict:
        low = pkg.lower()
        desc = KNOWN_DESCRIPTIONS.get(pkg)

        if pkg in self.extra_protected:
            return Verdict(6, self.extra_protected[pkg], desc or GROUP_DEFAULT_DESC[6])

        if "flauncher" in low:
            return Verdict(6, "novo ecrã inicial (FLauncher)", "FLauncher, o ecrã inicial novo")

        if pkg in LAUNCHER_RELATED:
            if self.allow_launcher_disable:
                return Verdict(4, "ecrã inicial original (FLauncher já é o predefinido)", desc or "Ecrã inicial original")
            return Verdict(
                6,
                "ecrã inicial atual — só depois de instalar o FLauncher e o definir como predefinido",
                desc or "Ecrã inicial original",
            )
        if pkg in self.home_packages:
            return Verdict(6, "reclama o ecrã inicial", desc or "Ecrã inicial")

        if pkg in PROTECTED_EXACT:
            return Verdict(6, PROTECTED_EXACT[pkg], desc or GROUP_DEFAULT_DESC[6])
        for rx, reason in PROTECTED_REGEX:
            if rx.search(low):
                return Verdict(6, reason, desc or GROUP_DEFAULT_DESC[6])

        tokens = _tokens(low)

        if pkg in _G4_EXACT:
            return Verdict(4, "app pré-instalada conhecida", desc or GROUP_DEFAULT_DESC[4])
        if pkg in _G2_EXACT:
            return Verdict(2, "linhas de recomendação", desc or GROUP_DEFAULT_DESC[2])
        if pkg in _G3_EXACT:
            return Verdict(3, "serviço de feedback", desc or GROUP_DEFAULT_DESC[3])

        # Grupo 5 antes dos restantes: o que depende de ti nunca é sugerido por defeito.
        if _has_sub(low, _G5_STREAMING):
            return Verdict(5, "app de streaming — pergunta-se a ti", desc or GROUP_DEFAULT_DESC[5])
        if _has_sub(low, _G5_VOICE):
            return Verdict(5, "assistente de voz — pergunta-se a ti", desc or GROUP_DEFAULT_DESC[5])
        if _has_sub(low, _G5_CAST) or tokens & _G5_CAST_TOKENS:
            return Verdict(5, "Chromecast/espelhamento — pergunta-se a ti", desc or GROUP_DEFAULT_DESC[5])
        if tokens & _G5_UPDATE_TOKENS or _has_sub(low, _G5_UPDATE_SUB):
            return Verdict(5, "atualizações do sistema — pergunta-se a ti", desc or GROUP_DEFAULT_DESC[5])

        if _has_sub(low, _G1_SUB) or tokens & _G1_TOKENS:
            return Verdict(1, "nome indica telemetria/rastreio/anúncios", desc or GROUP_DEFAULT_DESC[1])
        if _has_sub(low, _G2_SUB) or tokens & _G2_TOKENS:
            return Verdict(2, "nome indica recomendações/conteúdos/demo", desc or GROUP_DEFAULT_DESC[2])
        if tokens & _G3_TOKENS:
            return Verdict(3, "nome indica limpador/otimizador", desc or GROUP_DEFAULT_DESC[3])
        if tokens & _G4_TOKENS:
            return Verdict(4, "app pré-instalada provável", desc or GROUP_DEFAULT_DESC[4])

        return Verdict(0, "nome não diz o que faz — inspecionar com dumpsys package", GROUP_DEFAULT_DESC[0])


def risk_from_dumpsys(text: str) -> list[str]:
    """Razões pelas quais o `dumpsys package` mostra que o pacote é intocável."""
    return [reason for marker, reason in RISK_MARKERS.items() if marker in text]


_COMPONENT = re.compile(r"\s[0-9a-f]+ (\S+/\S+) filter ")
_ACTION = re.compile(r'Action: "([^"]+)"')


def summarize_dumpsys(text: str, limit: int = 12) -> str:
    """Resumo legível: atividades/serviços/recetores declarados e ações dos filtros."""
    sections = {"Activity Resolver Table": "Atividades", "Receiver Resolver Table": "Recetores",
                "Service Resolver Table": "Serviços"}
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
        out.append("Ações declaradas: " + ", ".join(actions[:limit]) + (" …" if len(actions) > limit else ""))
    return "\n".join(out) or "(o dumpsys não mostrou atividades/serviços declarados)"
