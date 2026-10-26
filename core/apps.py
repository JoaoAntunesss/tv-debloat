"""Catálogo de apps úteis e validação de APKs. Nada é descarregado automaticamente."""
from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path

MAX_APK_BYTES = 600 * 1024 * 1024


@dataclass(frozen=True)
class AppEntry:
    key: str
    name: str
    purpose: str
    page_url: str | None
    how: str
    warning: str = ""


CATALOG = [
    AppEntry(
        "smarttube",
        "SmartTube",
        "YouTube sem anúncios (com SponsorBlock). Cliente alternativo, de código aberto (MIT).",
        "https://smarttubeapp.github.io",
        "Descarrega o APK da página oficial (ou na própria TV com a app Downloader, código kutt.to/stn_stable) "
        "e instala-o aqui com 'Instalar um APK'. Tem atualizador próprio.",
        "O programador publicou um aviso de segurança: o ambiente de build esteve infetado e as chaves públicas "
        "de assinatura podem ter sido comprometidas. Usa só a versão mais recente do site oficial e confirma o "
        "SHA-256 com o que o projeto publicar. Não é a app oficial do YouTube e vai contra os termos do YouTube. "
        "Não funciona em Fire TV novas (VegaOS).",
    ),
    AppEntry(
        "downloader",
        "Downloader (AFTVnews)",
        "Instala APKs a partir de um endereço ou código, diretamente na TV.",
        None,
        "Procura 'Downloader' (AFTVnews) na loja da tua TV (Play Store ou Amazon Appstore).",
    ),
    AppEntry(
        "iptv",
        "Leitor de IPTV (ex.: IPTV Smarters Pro)",
        "Reprodutor de listas IPTV/M3U e Xtream. É só o leitor: não traz canais.",
        None,
        "Procura o leitor na loja da TV. Se só existir em APK, descarrega-o apenas do site oficial do produto "
        "e instala-o aqui com 'Instalar um APK'.",
        "Não incluo nem recomendo listas ou serviços de canais: muitos serviços 'IPTV' vendem acesso não "
        "autorizado a conteúdos protegidos. Usa só listas a que tens direito (o teu operador, canais públicos "
        "gratuitos).",
    ),
    AppEntry(
        "flauncher",
        "FLauncher",
        "Ecrã inicial sem anúncios, só com a grelha das tuas apps (Android TV/Google TV).",
        None,
        "Instala-o pela Play Store da TV e depois usa o separador 4 · Ecrã inicial.",
    ),
]


class ApkError(Exception):
    pass


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_apk(path) -> dict:
    """Confere que o ficheiro parece um APK (zip com AndroidManifest.xml) e devolve nome, tamanho e SHA-256."""
    p = Path(path)
    if not p.is_file():
        raise ApkError("O ficheiro não existe.")
    if p.suffix.lower() != ".apk":
        raise ApkError("Só aceito ficheiros .apk (não aceito .xapk, .apks nem .zip).")
    size = p.stat().st_size
    if size == 0 or size > MAX_APK_BYTES:
        raise ApkError("Tamanho de ficheiro inválido para um APK.")
    try:
        with zipfile.ZipFile(p) as z:
            if "AndroidManifest.xml" not in z.namelist():
                raise ApkError("Este ficheiro não tem AndroidManifest.xml: não parece um APK.")
    except zipfile.BadZipFile:
        raise ApkError("Este ficheiro não é um APK válido (zip corrompido).")
    return {"name": p.name, "size": size, "sha256": sha256_file(p)}
