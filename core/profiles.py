"""Sistemas e marcas de TV suportados, com o que cada um permite e os avisos conhecidos.

Fontes (pesquisa de 2026-10-26): repositórios cleanyourtv (MIT, Android TV/Google TV) e dumbtv
(MIT, Fire TV; docs/OTHER-TVS.md para Samsung/LG/Roku). Os nomes concretos de pacotes por modelo
vivem nas listas desses projetos: aqui só se guarda o que é seguro generalizar.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    adb: bool  # permite pm disable-user por ADB?
    launcher_swap: bool  # permite trocar o ecrã inicial?
    dns_on_device: bool  # permite DNS privado do Android pelo ADB?
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Brand:
    name: str
    notes: tuple[str, ...] = ()
    extra_protected: dict = field(default_factory=dict)  # pacote -> razão


PLATFORMS: dict[str, Platform] = {
    "androidtv": Platform(
        "androidtv", "Android TV / Google TV", adb=True, launcher_swap=True, dns_on_device=True,
        notes=("É o caso com mais suporte: desativa pacotes por ADB e troca o ecrã inicial.",),
    ),
    "firetv": Platform(
        "firetv", "Amazon Fire TV (Fire OS)", adb=True, launcher_swap=False, dns_on_device=False,
        notes=(
            "O Fire OS não deixa um launcher de terceiros ficar com o botão Home: só se faz o debloat.",
            "Bloquear servidores da Amazon por DNS também pode bloquear atualizações do Fire OS.",
            "Fire TV Box de 2015 (Fire OS 5) recusa todos os comandos 'pm'.",
            "Fire TV novas com VegaOS não são suportadas (nem pelo SmartTube).",
        ),
    ),
    "tizen": Platform(
        "tizen", "Samsung (Tizen)", adb=False, launcher_swap=False, dns_on_device=False,
        notes=("Sem shell nem alteração de pacotes no aparelho.",),
    ),
    "webos": Platform(
        "webos", "LG (webOS)", adb=False, launcher_swap=False, dns_on_device=False,
        notes=("Pacotes só em modo programador/homebrew; sem trocar o launcher.",),
    ),
    "roku": Platform(
        "roku", "Roku (e TVs com Roku)", adb=False, launcher_swap=False, dns_on_device=False,
        notes=("Sem shell, sem pacotes, sem launcher alternativo.",),
    ),
    "other": Platform(
        "other", "Outro (Vidaa, Netrange, Linux do fabricante…)", adb=False, launcher_swap=False,
        dns_on_device=False,
        notes=("Normalmente fechado: só dá para agir pela rede ou pelas definições da TV.",),
    ),
}

_GEN = "Faz sempre o backup primeiro; as listas por modelo são heurísticas e a TV pode ter pacotes que não conheço."

BRANDS: dict[str, list[Brand]] = {
    "androidtv": [
        Brand("TCL", (
            "Há armadilhas conhecidas (menu Entradas, atualizações, Wi-Fi, comando): estão protegidas.",
            "Alguns modelos do mercado chinês recusam qualquer launcher alternativo.",
        )),
        Brand("Sony", ("Há modelos com particularidades de firmware/região. " + _GEN,)),
        Brand("Xiaomi / Redmi", (
            "O Redmi TV MiTV-ANTL0 corre Android 5.1.1 e não é Android TV: confirma o teu modelo.",
        )),
        Brand("Philips", (_GEN,)),
        Brand("Hisense", (_GEN,)),
        Brand("Skyworth", ("O modelo 8R40_K5C corre Android 8.0 e não é Google TV.",)),
        Brand("Panasonic", (_GEN,)),
        Brand("Sharp", (_GEN,)),
        Brand("Thomson", (_GEN,)),
        Brand("JVC", (_GEN,)),
        Brand("Haier", (_GEN,)),
        Brand("OnePlus", (_GEN,)),
        Brand("NVIDIA Shield", (_GEN,)),
        Brand("Google (Chromecast com Google TV / TV Streamer)", (
            "Pode exigir 'Depuração sem fios' com código de pareamento (usa o campo de pareamento).",
        )),
        Brand("Outra marca", (_GEN,)),
    ],
    "firetv": [
        Brand("Fire TV Stick / Cube", (), {"com.amazon.tv.launcher": "ecrã inicial do Fire OS (não substituível)"}),
        Brand("Fire TV Edition (TVs Insignia, Toshiba, etc.)", (),
              {"com.amazon.tv.launcher": "ecrã inicial do Fire OS (não substituível)"}),
    ],
    "tizen": [Brand("Samsung")],
    "webos": [Brand("LG")],
    "roku": [Brand("Roku / TV com Roku")],
    "other": [Brand("Vidaa (Hisense)"), Brand("Outra")],
}

# Texto para plataformas sem ADB (a ação possível é a nível de rede ou nas definições da TV).
_NETWORK_COMMON = (
    "O que funciona em qualquer TV fechada, sem a modificar:\n"
    "• Bloquear anúncios e telemetria no router/rede com um DNS que filtra: NextDNS, AdGuard Home ou Pi-hole.\n"
    "• Se usas a TV só como ecrã (HDMI, caixa externa), não lhe dês acesso à internet.\n"
    "• Anúncios dentro de apps de streaming/YouTube continuam: para isso usa uma caixa Android TV/Fire TV "
    "(ex.: com SmartTube) ligada por HDMI.\n"
)

_ON_TV = {
    "tizen": (
        "Definições na TV (os nomes variam com o ano e a versão; confirma no teu menu):\n"
        "• Termos e privacidade: desligar 'Serviços de informação de visualização' e anúncios por interesses.\n"
        "• Não aceitar serviços/termos opcionais no arranque."
    ),
    "webos": (
        "Definições na TV (os nomes variam com o ano e a versão; confirma no teu menu):\n"
        "• Desligar 'Live Plus' (reconhecimento de conteúdo) e limitar o rastreio de anúncios.\n"
        "• Desligar recomendações/promoções no ecrã inicial, se existirem."
    ),
    "roku": (
        "Definições na TV (os nomes variam com a versão; confirma no teu menu):\n"
        "• Privacidade: desligar 'Usar informação das entradas da TV' (reconhecimento de conteúdo).\n"
        "• Limitar o rastreio de anúncios."
    ),
    "other": "Procura nas definições de privacidade o reconhecimento de conteúdo (ACR) e os anúncios personalizados.",
}


def network_guide(platform_key: str) -> str:
    return _NETWORK_COMMON + "\n" + _ON_TV.get(platform_key, "")


def get_brand(platform_key: str, name: str) -> Brand | None:
    for b in BRANDS.get(platform_key, []):
        if b.name == name:
            return b
    return None
