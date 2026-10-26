"""Catalog of useful apps and APK validation. Nothing is downloaded automatically."""
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
        "Ad-free YouTube (with SponsorBlock). Alternative open-source client (MIT).",
        "https://smarttubeapp.github.io",
        "Download the APK from the official page (or on the TV itself with the Downloader app, code "
        "kutt.to/stn_stable) and install it here with 'Install an APK'. It has its own updater.",
        "The developer published a security notice: the build environment was compromised and the public "
        "signing keys may have been exposed. Use only the latest version from the official site and compare "
        "the SHA-256 with what the project publishes. It is not the official YouTube app and goes against "
        "YouTube's terms. It does not work on new Fire TVs (VegaOS).",
    ),
    AppEntry(
        "downloader",
        "Downloader (AFTVnews)",
        "Installs APKs from an address or code, directly on the TV.",
        None,
        "Search for 'Downloader' (AFTVnews) in your TV's store (Play Store or Amazon Appstore).",
    ),
    AppEntry(
        "iptv",
        "IPTV player (e.g. IPTV Smarters Pro)",
        "Player for IPTV/M3U and Xtream lists. It is only the player: it comes with no channels.",
        None,
        "Look for the player in the TV's store. If it only exists as an APK, download it only from the "
        "product's official site and install it here with 'Install an APK'.",
        "I do not include or recommend channel lists or services: many 'IPTV' services sell unauthorized "
        "access to protected content. Use only lists you are entitled to (your own provider, free public "
        "channels).",
    ),
    AppEntry(
        "flauncher",
        "FLauncher",
        "Ad-free home screen with just a grid of your apps (Android TV/Google TV).",
        None,
        "Install it from the TV's Play Store, then use tab 4 · Home screen.",
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
    """Check that the file looks like an APK (zip with AndroidManifest.xml); return name, size and SHA-256."""
    p = Path(path)
    if not p.is_file():
        raise ApkError("The file does not exist.")
    if p.suffix.lower() != ".apk":
        raise ApkError("Only .apk files are accepted (not .xapk, .apks or .zip).")
    size = p.stat().st_size
    if size == 0 or size > MAX_APK_BYTES:
        raise ApkError("Invalid file size for an APK.")
    try:
        with zipfile.ZipFile(p) as z:
            if "AndroidManifest.xml" not in z.namelist():
                raise ApkError("This file has no AndroidManifest.xml: it does not look like an APK.")
    except zipfile.BadZipFile:
        raise ApkError("This file is not a valid APK (corrupt zip).")
    return {"name": p.name, "size": size, "sha256": sha256_file(p)}
