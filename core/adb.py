"""ADB client: uses the `adb` binary; on macOS, if Local Network blocks it, falls back to `adb-shell` (Python)."""
from __future__ import annotations

import io
import platform
import re
import shutil
import socket
import subprocess
import threading
import time
import zipfile
from pathlib import Path
from urllib.request import urlopen

from .guard import check_shell


class AdbError(Exception):
    pass


_BASE = "https://dl.google.com/android/repository/"
_ZIPS = {
    "Windows": "platform-tools-latest-windows.zip",
    "Darwin": "platform-tools-latest-darwin.zip",
    "Linux": "platform-tools-latest-linux.zip",
}


def _exe() -> str:
    return "adb.exe" if platform.system() == "Windows" else "adb"


def find_adb(app_dir) -> Path | None:
    found = shutil.which("adb")
    if found:
        return Path(found)
    local = Path(app_dir) / "platform-tools" / _exe()
    return local if local.exists() else None


def install_platform_tools(app_dir, log=print) -> Path:
    """Download Google's official platform-tools into <app>/platform-tools."""
    system = platform.system()
    if system not in _ZIPS:
        raise AdbError(f"System not supported for automatic installation: {system}")
    dest = Path(app_dir).resolve()
    url = _BASE + _ZIPS[system]
    log(f"Downloading {url} …")
    data = urlopen(url, timeout=120).read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():
            target = (dest / member).resolve()
            if dest != target and dest not in target.parents:
                raise AdbError("The downloaded zip has suspicious paths; aborted.")
        z.extractall(dest)
    adb = dest / "platform-tools" / _exe()
    if system != "Windows":
        adb.chmod(0o755)
    log(f"adb installed at {adb}")
    return adb


def port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class CliBackend:
    name = "adb"

    def __init__(self, adb_path):
        self.adb = str(adb_path)
        self.target: str | None = None

    def _run(self, args, timeout=30):
        flags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        try:
            p = subprocess.run([self.adb, *args], capture_output=True, timeout=timeout, creationflags=flags)
        except subprocess.TimeoutExpired:
            raise AdbError(f"The command 'adb {' '.join(args[:2])}' took longer than {timeout}s.")
        except OSError as e:
            raise AdbError(f"Could not run adb: {e}")
        return p.returncode, p.stdout, p.stderr

    @staticmethod
    def _text(b: bytes) -> str:
        return b.decode("utf-8", "replace").strip()

    def connect(self, host, port):
        target = f"{host}:{port}"
        rc, out, err = self._run(["connect", target], 25)
        text = self._text(out + err)
        low = text.lower()
        if "connected to" not in low or any(w in low for w in ("failed", "cannot", "unable")):
            raise AdbError(text or "adb connect failed with no message.")
        self.target = target
        return text

    def pair(self, host_port, code):
        rc, out, err = self._run(["pair", host_port, code], 30)
        text = self._text(out + err)
        if "successfully paired" not in text.lower():
            raise AdbError(text or "Pairing failed.")
        return text

    def state(self):
        rc, out, err = self._run(["-s", self.target, "get-state"], 10)
        text = self._text(out + err).lower()
        if "unauthorized" in text:
            return "unauthorized"
        if rc == 0 and "device" in text:
            return "device"
        if "offline" in text:
            return "offline"
        return "disconnected"

    def shell(self, cmd, timeout=60):
        rc, out, err = self._run(["-s", self.target, "shell", cmd], timeout)
        e = self._text(err).lower()
        if "unauthorized" in e:
            raise AdbError("The TV has not yet authorized this computer ('Allow USB debugging?' dialog).")
        if any(w in e for w in ("device offline", "no devices", "not found", "closed")) and not out:
            raise AdbError(self._text(err))
        text = out.decode("utf-8", "replace")
        if not text.strip() and err:
            text = err.decode("utf-8", "replace")
        return text

    def screencap(self):
        rc, out, err = self._run(["-s", self.target, "exec-out", "screencap", "-p"], 40)
        if not out.startswith(b"\x89PNG"):
            raise AdbError("screencap did not return a PNG image: " + self._text(err or out[:200]))
        return out

    def push(self, local, remote):
        rc, out, err = self._run(["-s", self.target, "push", str(local), remote], 900)
        text = self._text(out + err)
        if rc != 0 or "error" in text.lower() and "pushed" not in text.lower():
            raise AdbError(text or "Sending the file to the TV failed.")
        return text

    def disconnect(self):
        if self.target:
            self._run(["disconnect", self.target], 10)


class PyBackend:
    """Pure-Python ADB client (`adb-shell` package), for macOS when adb says 'No route to host'."""

    name = "adb-shell"

    def __init__(self, key_dir):
        self.key_dir = Path(key_dir)
        self.dev = None
        self.target = None

    def _signer(self):
        try:
            from adb_shell.auth.keygen import keygen
            from adb_shell.auth.sign_pythonrsa import PythonRSASigner
        except ImportError:
            raise AdbError("The 'adb-shell' package is missing. Install it with: pip install adb-shell")
        self.key_dir.mkdir(parents=True, exist_ok=True)
        priv = self.key_dir / "adbkey"
        if not priv.exists():
            keygen(str(priv))
        pub = Path(str(priv) + ".pub")
        return PythonRSASigner(pub.read_text(), priv.read_text())

    def connect(self, host, port):
        try:
            from adb_shell.adb_device import AdbDeviceTcp
        except ImportError:
            raise AdbError("The 'adb-shell' package is missing. Install it with: pip install adb-shell")
        signer = self._signer()
        self.dev = AdbDeviceTcp(host, int(port), default_transport_timeout_s=15.0)
        try:
            self.dev.connect(rsa_keys=[signer], auth_timeout_s=60)
        except Exception as e:  # the library raises several types
            raise AdbError(f"adb-shell could not connect: {e}")
        self.target = f"{host}:{port}"
        return f"connected to {self.target} (adb-shell)"

    def pair(self, host_port, code):
        raise AdbError("Pairing by code only works with the adb binary.")

    def state(self):
        return "device" if self.dev is not None and self.dev.available else "disconnected"

    def shell(self, cmd, timeout=60):
        try:
            return self.dev.shell(cmd, timeout_s=timeout, read_timeout_s=timeout)
        except Exception as e:
            raise AdbError(f"adb-shell failed: {e}")

    def screencap(self):
        try:
            try:
                data = self.dev.exec_out("screencap -p", timeout_s=40, decode=False)
            except AttributeError:
                data = self.dev.shell("screencap -p", timeout_s=40, decode=False)
        except Exception as e:
            raise AdbError(f"adb-shell failed on screencap: {e}")
        if not data.startswith(b"\x89PNG"):
            raise AdbError("screencap did not return a PNG image.")
        return data

    def push(self, local, remote):
        try:
            self.dev.push(str(local), remote)
        except Exception as e:
            raise AdbError(f"adb-shell failed sending the file: {e}")
        return "pushed"

    def disconnect(self):
        if self.dev is not None:
            try:
                self.dev.close()
            except Exception:
                pass


class Adb:
    """Facade: every command goes through the guard (core.guard) before reaching the TV."""

    def __init__(self, backend, app_dir=".", log=print):
        self.backend = backend
        self.app_dir = Path(app_dir)
        self.log = log
        self.host = None
        self.port = 5555
        self._lock = threading.Lock()  # one command at a time on the TV (the dialog and the queue use threads)

    @property
    def backend_name(self):
        return self.backend.name

    def connect(self, host, port=5555):
        self.host, self.port = host, int(port)
        try:
            return self.backend.connect(host, self.port)
        except AdbError as e:
            if (
                platform.system() == "Darwin"
                and "no route to host" in str(e).lower()
                and isinstance(self.backend, CliBackend)
            ):
                self.log(
                    "O macOS bloqueou o adb (Local Network). Em vez de insistir, passo a usar o "
                    "cliente Python 'adb-shell'."
                )
                self.backend = PyBackend(self.app_dir / "keys")
                return self.backend.connect(host, self.port)
            raise

    def pair(self, host_port, code):
        return self.backend.pair(host_port, code)

    def state(self):
        return self.backend.state()

    def wait_authorized(self, timeout=90, on_wait=None):
        end = time.time() + timeout
        while time.time() < end:
            st = self.backend.state()
            if st == "device":
                return True
            if st == "unauthorized" and on_wait:
                on_wait()
            time.sleep(2)
        return False

    def reconnect(self):
        if not self.host:
            raise AdbError("There has never been a connection to a TV.")
        return self.backend.connect(self.host, self.port)

    def shell(self, cmd, timeout=60):
        cmd = check_shell(cmd)
        with self._lock:
            return self.backend.shell(cmd, timeout)

    def screencap(self):
        with self._lock:
            return self.backend.screencap()

    def push(self, local, remote):
        """Only push to the temp folder and with this program's prefix (see guard)."""
        if not re.fullmatch(r"/data/local/tmp/tvdebloat-[A-Za-z0-9]{8,64}\.apk", remote):
            raise AdbError("Push destination refused.")
        with self._lock:
            return self.backend.push(local, remote)

    def disconnect(self):
        self.backend.disconnect()
