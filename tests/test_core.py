import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.adb import AdbError
from core.apps import ApkError, validate_apk
from core.guard import CommandRefused, check_shell
from core.profiles import BRANDS, PLATFORMS, get_brand, network_guide
from core.packages import Classifier, risk_from_dumpsys
from core.session import MAX_BATCH, DebloatSession, SessionError, parse_home_activities, parse_pm_list
from core.workspace import Workspace, memory_rows, parse_meminfo

MEMINFO = """Applications Memory Usage (in Kilobytes):

Total RAM: 1,847,068K (status normal)
 Free RAM: 1,016,404K (  196,300K cached pss +   500,000K cached kernel +   320,104K free)
 Used RAM:   652,000K
 Lost RAM:    40,100K
"""

PM_F = """package:/system/priv-app/Foo/Foo.apk=com.tcl.suspension
package:/system/app/Bar.apk=com.sambatv.acr
package:/system/app/Baz.apk=com.example.promo.feed
package:/product/app/Qux.apk=com.example.mystery
package:/system/app/Netflix.apk=com.netflix.ninja
package:/data/app/~~x/me.efesser.flauncher-1/base.apk=me.efesser.flauncher
package:/apex/com.android.art/x.apk=com.android.art
package:/system/priv-app/Launcher.apk=com.google.android.tvlauncher
"""

HOME_OUT = """2 activities found:
  Activity #0:
    priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true
    ActivityInfo:
      name=com.google.android.tvlauncher.MainActivity
      packageName=com.google.android.tvlauncher
  Activity #1:
    ActivityInfo:
      name=me.efesser.flauncher.MainActivity
      packageName=me.efesser.flauncher
"""


class FakeAdb:
    def __init__(self):
        self.calls = []
        self.home_default = "com.google.android.tvlauncher"
        self.pushed = []
        self.install_ok = True
        self.settings = {"window_animation_scale": "1.0", "transition_animation_scale": "1.0",
                         "animator_duration_scale": "1.0"}

    def shell(self, cmd, timeout=60):
        cmd = check_shell(cmd)  # igual à fachada real: a guarda corre sempre
        self.calls.append(cmd)
        if cmd == "pm list packages -f":
            return PM_F
        if cmd == "pm list packages -d":
            return "package:com.disabled.already\n"
        if cmd.startswith("cmd package query-activities"):
            return HOME_OUT
        if cmd.startswith("cmd package resolve-activity"):
            return f"priority=0 preferredOrder=0\n{self.home_default}/.MainActivity\n"
        if cmd.startswith("cmd package set-home-activity"):
            self.home_default = cmd.split()[-1].split("/")[0]
            return "Success"
        if cmd.startswith("pm disable-user"):
            return f"Package {cmd.split()[-1]} new state: disabled-user"
        if cmd.startswith("pm enable"):
            return f"Package {cmd.split()[-1]} new state: enabled"
        if cmd == "dumpsys meminfo":
            return MEMINFO
        if cmd.startswith("pm install -r"):
            return "Success\n" if self.install_ok else "Failure [INSTALL_FAILED_OLDER_SDK]\n"
        if cmd.startswith("settings get global"):
            return self.settings.get(cmd.split()[-1], "null") + "\n"
        if cmd.startswith("settings put global"):
            return ""
        if cmd == "getprop" or cmd.startswith("settings list"):
            return "x=y\n"
        return ""

    def screencap(self):
        return b"\x89PNG" + b"0" * 20000

    def push(self, local, remote):
        if not re.fullmatch(r"/data/local/tmp/tvdebloat-[A-Za-z0-9]{8,64}\.apk", remote):
            raise AdbError("Destino de envio recusado.")
        self.pushed.append((str(local), remote))
        return "pushed"


class GuardTests(unittest.TestCase):
    def test_allows_safe_commands(self):
        for c in (
            "pm disable-user --user 0 com.example.app",
            "pm enable com.example.app",
            "pm list packages -f",
            "pm list packages -d",
            "pm trim-caches 999G",
            "settings put global window_animation_scale 0.5",
            "input keyevent KEYCODE_HOME",
            "dumpsys meminfo",
            "cmd package set-home-activity me.efesser.flauncher/me.efesser.flauncher.MainActivity",
            "reboot",
        ):
            self.assertEqual(check_shell(c), c)

    def test_refuses_dangerous_commands(self):
        for c in (
            "pm uninstall com.example.app",
            "pm uninstall -k --user 0 com.example.app",
            "pm disable-user --user 0 com.a && pm disable-user --user 0 com.b",
            "pm disable-user --user 0 com.a; reboot",
            "pm disable-user --user 0 $(whoami)",
            "pm list packages | grep x",
            "pm disable com.example.app",
            "pm clear com.example.app",
            "su -c id",
            "reboot bootloader",
            "rm -rf /sdcard",
            "setprop persist.x 1",
            "settings put global device_name hacked",
            "settings put secure install_non_market_apps 1",
            "input text hello",
            "",
        ):
            with self.assertRaises(CommandRefused, msg=c):
                check_shell(c)


class GuardExtraTests(unittest.TestCase):
    def test_install_and_dns_allowed_only_in_strict_form(self):
        ok = (
            "pm install -r /data/local/tmp/tvdebloat-0123456789abcdef.apk",
            "rm /data/local/tmp/tvdebloat-0123456789abcdef.apk",
            "settings put global private_dns_mode hostname",
            "settings put global private_dns_mode opportunistic",
            "settings put global private_dns_specifier dns.adguard-dns.com",
            "settings get global private_dns_specifier",
        )
        for c in ok:
            self.assertEqual(check_shell(c), c)
        for c in (
            "pm install -r /sdcard/Download/x.apk",
            "pm install /data/local/tmp/tvdebloat-0123456789abcdef.apk",
            "pm install -r -d /data/local/tmp/tvdebloat-0123456789abcdef.apk",
            "rm /data/local/tmp/other.apk",
            "rm -rf /data/local/tmp/tvdebloat-0123456789abcdef.apk",
            "rm /data/local/tmp/tvdebloat-0123456789abcdef.apk /sdcard/a",
            "settings put global private_dns_mode strict",
            "settings put global private_dns_specifier evil",
            "settings put global private_dns_specifier a.b.com;reboot",
            "settings put global private_dns_specifier dns.example.com extra",
        ):
            with self.assertRaises(CommandRefused, msg=c):
                check_shell(c)


class ProfileTests(unittest.TestCase):
    def test_platform_capabilities(self):
        self.assertTrue(PLATFORMS["androidtv"].adb and PLATFORMS["androidtv"].launcher_swap)
        self.assertTrue(PLATFORMS["firetv"].adb)
        self.assertFalse(PLATFORMS["firetv"].launcher_swap)
        for k in ("tizen", "webos", "roku", "other"):
            self.assertFalse(PLATFORMS[k].adb, k)
            self.assertIn("DNS", network_guide(k))
        for k in PLATFORMS:
            self.assertTrue(BRANDS[k], k)
        self.assertIsNotNone(get_brand("androidtv", "TCL"))
        self.assertIsNone(get_brand("androidtv", "Inexistente"))

    def test_firetv_launcher_protected_and_no_swap(self):
        brand = get_brand("firetv", "Fire TV Stick / Cube")
        clf = Classifier(extra_protected=brand.extra_protected)
        self.assertEqual(clf.classify("com.amazon.tv.launcher").group, 6)


class ClassifierTests(unittest.TestCase):
    def setUp(self):
        self.clf = Classifier(home_packages={"com.google.android.tvlauncher", "me.efesser.flauncher"})

    def test_tcl_traps_are_protected(self):
        for p in (
            "com.tcl.suspension", "com.tcl.ttvs", "com.tcl.tv", "com.tcl.tvinput",
            "com.tcl.providers.config", "com.tcl.initsetup",
            "com.google.android.tv.remote.service", "com.tcl.tcl_bt_rcu_service", "com.tcl.autopair",
        ):
            self.assertEqual(self.clf.classify(p).group, 6, p)

    def test_always_protected(self):
        for p in (
            "com.android.vending", "com.google.android.gms", "com.google.android.gsf",
            "com.android.location.fused", "com.google.android.inputmethod.latin",
            "com.android.inputmethod.latin", "com.google.android.tv.inputmethod.pinyin",
            "com.android.bluetooth", "com.android.providers.media", "com.google.android.webview",
        ):
            self.assertEqual(self.clf.classify(p).group, 6, p)

    def test_launcher_protected_until_unlocked(self):
        self.assertEqual(self.clf.classify("com.google.android.tvlauncher").group, 6)
        self.assertEqual(self.clf.classify("com.google.android.apps.tv.launcherx").group, 6)
        self.assertEqual(self.clf.classify("me.efesser.flauncher").group, 6)
        unlocked = Classifier({"me.efesser.flauncher"}, allow_launcher_disable=True)
        self.assertEqual(unlocked.classify("com.google.android.tvlauncher").group, 4)
        self.assertEqual(unlocked.classify("me.efesser.flauncher").group, 6)  # nunca o novo

    def test_groups(self):
        self.assertEqual(self.clf.classify("com.sambatv.acr").group, 1)
        self.assertEqual(self.clf.classify("com.example.analytics").group, 1)
        self.assertEqual(self.clf.classify("com.google.android.tvrecommendations").group, 2)
        self.assertEqual(self.clf.classify("com.example.retaildemo").group, 2)
        self.assertEqual(self.clf.classify("com.example.cleaner").group, 3)
        self.assertEqual(self.clf.classify("com.google.android.videos").group, 4)
        self.assertEqual(self.clf.classify("com.netflix.ninja").group, 5)
        self.assertEqual(self.clf.classify("com.google.android.apps.mediashell").group, 5)
        self.assertEqual(self.clf.classify("com.google.android.katniss").group, 5)
        self.assertEqual(self.clf.classify("com.example.mystery").group, 0)

    def test_dumpsys_risks(self):
        self.assertTrue(risk_from_dumpsys('Action: "android.media.tv.TvInputService"'))
        self.assertEqual(risk_from_dumpsys('Action: "android.intent.action.VIEW"'), [])


class WorkspaceTests(unittest.TestCase):
    def test_meminfo(self):
        m = parse_meminfo(MEMINFO)
        self.assertEqual(m["Total"], 1847068)
        self.assertEqual(m["Free"], 1016404)
        self.assertEqual(m["Used"], 652000)
        rows = memory_rows({"Total": 1024, "Free": 512, "Used": 512}, {"Total": 1024, "Free": 768, "Used": 256})
        self.assertEqual(rows[1], ("RAM livre", "0 MB", "1 MB", "+0 MB"))

    def test_record_and_restore_sh(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(d, "192.168.1.50:5555", windows=False)
            ws.start_restore()
            ws.record_disable("com.a", 1, "Telemetria")
            ws.record_disable("com.a", 1, "Telemetria")  # sem duplicados em disabled.txt
            ws.record_disable("com.b", 2, "Anúncios")
            self.assertEqual(ws.read_disabled(), ["com.a", "com.b"])
            restore = ws.restore_path.read_text(encoding="utf-8")
            self.assertIn("pm enable com.a", restore)
            self.assertIn("pm enable com.b", restore)
            self.assertTrue(restore.startswith("#!/bin/sh"))
            self.assertIn("pm enable com.b", ws.log_path.read_text(encoding="utf-8"))
            ws.remove_disabled("com.a")
            self.assertEqual(ws.read_disabled(), ["com.b"])

    def test_restore_ps1(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(d, "10.0.0.2:5555", windows=True)
            ws.start_restore()
            ws.record_disable("com.a", 1, "x")
            self.assertEqual(ws.restore_path.name, "restore.ps1")
            self.assertIn("adb -s $Target shell pm enable com.a", ws.restore_path.read_text(encoding="utf-8"))

    def test_original_setting_kept_on_second_run(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(d, "x:5555", windows=False)
            ws.start_restore()
            ws.record_setting("window_animation_scale", "1.0\n")
            ws.record_setting("window_animation_scale", "0.5\n")  # não pode sobrepor o original
            self.assertEqual(ws.read_original_settings(), {"window_animation_scale": "1.0"})
            self.assertEqual(ws.restore_path.read_text(encoding="utf-8").count("window_animation_scale"), 1)


class ParsingTests(unittest.TestCase):
    def test_pm_list(self):
        res = parse_pm_list(PM_F)
        self.assertEqual(res["com.tcl.suspension"], "/system/priv-app/Foo/Foo.apk")
        self.assertIn("me.efesser.flauncher", res)

    def test_home(self):
        self.assertEqual(
            parse_home_activities(HOME_OUT),
            [("com.google.android.tvlauncher", "com.google.android.tvlauncher/com.google.android.tvlauncher.MainActivity"),
             ("me.efesser.flauncher", "me.efesser.flauncher/me.efesser.flauncher.MainActivity")],
        )


class SessionTests(unittest.TestCase):
    def make(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.adb = FakeAdb()
        ws = Workspace(self.tmp.name, "192.168.1.50:5555", windows=False)
        s = DebloatSession(self.adb, ws, log=lambda m: None, sleep=lambda s: None)
        return s

    def test_backup_first_rule(self):
        s = self.make()
        s.scan()
        with self.assertRaises(SessionError):
            s.disable_batch(["com.sambatv.acr"], "Lote 1")  # sem backup
        s.backup()
        self.assertTrue(s.ws.restore_path.exists())  # restore criado com o backup
        names = {p.name for p in s.backup_dir.iterdir()}
        self.assertEqual(len(names), 7)
        self.assertEqual(s.mem_before["Total"], 1847068)

    def test_scan_skips_user_apps_and_apex(self):
        s = self.make()
        infos = {i.name: i for i in s.scan()}
        self.assertFalse(infos["me.efesser.flauncher"].system)
        self.assertTrue(infos["com.sambatv.acr"].system)

    def test_disable_flow_and_protections(self):
        s = self.make()
        s.backup()
        s.scan()
        res = s.disable_batch(["com.sambatv.acr", "com.example.promo.feed"], "Lote 1")
        self.assertEqual(res.ok, ["com.sambatv.acr", "com.example.promo.feed"])
        self.assertIn("pm disable-user --user 0 com.sambatv.acr", self.adb.calls)
        self.assertEqual(s.ws.read_disabled(), ["com.sambatv.acr", "com.example.promo.feed"])
        for bad in ("com.tcl.suspension", "com.google.android.tvlauncher"):
            with self.assertRaises(SessionError, msg=bad):
                s.disable_batch([bad], "x")
        with self.assertRaises(SessionError):  # desconhecido sem confirmação
            s.disable_batch(["com.example.mystery"], "x")
        s.disable_batch(["com.example.mystery"], "x", confirmed_unknown={"com.example.mystery"})
        self.assertFalse(any("uninstall" in c for c in self.adb.calls))

    def test_batch_limit(self):
        s = self.make()
        s.backup()
        s.scan()
        with self.assertRaises(SessionError):
            s.disable_batch(["com.sambatv.acr"] * (MAX_BATCH + 1), "x")

    def test_revert(self):
        s = self.make()
        s.backup()
        s.scan()
        s.disable_batch(["com.sambatv.acr"], "Lote 1")
        s.revert(["com.sambatv.acr"])
        self.assertEqual(s.ws.read_disabled(), [])
        self.assertIn("pm enable com.sambatv.acr", self.adb.calls)
        self.assertFalse(s.infos["com.sambatv.acr"].disabled)

    def test_launcher_only_after_flauncher_is_default(self):
        s = self.make()
        s.backup()
        s.scan()
        with self.assertRaises(SessionError):
            s.unlock_launcher_disable()  # o predefinido ainda é o launcher original
        cur = s.set_home("me.efesser.flauncher/me.efesser.flauncher.MainActivity")
        self.assertEqual(cur, "me.efesser.flauncher")
        s.unlock_launcher_disable()
        res = s.disable_batch(["com.google.android.tvlauncher"], "Ecrã inicial")
        self.assertEqual(res.ok, ["com.google.android.tvlauncher"])

    def test_speedups_and_restore_all(self):
        s = self.make()
        s.backup()
        s.scan()
        s.apply_speedups()
        s.apply_speedups()  # repetir não perde os valores originais
        self.assertEqual(s.ws.read_original_settings()["animator_duration_scale"], "1.0")
        s.disable_batch(["com.sambatv.acr"], "Lote 1")
        s.restore_all()
        self.assertIn("pm enable com.sambatv.acr", self.adb.calls)
        self.assertIn("settings put global window_animation_scale 1.0", self.adb.calls)

    def _apk(self, name="app.apk", manifest=True):
        p = Path(self.tmp.name) / name
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("AndroidManifest.xml" if manifest else "readme.txt", "x")
        return p

    def test_install_apk(self):
        s = self.make()
        sha = s.install_apk(self._apk())
        self.assertEqual(len(self.adb.pushed), 1)
        remote = self.adb.pushed[0][1]
        self.assertIn(sha[:16], remote)
        self.assertIn(f"pm install -r {remote}", self.adb.calls)
        self.assertIn(f"rm {remote}", self.adb.calls)  # limpa a pasta temporária
        self.assertIn(sha, s.ws.log_path.read_text(encoding="utf-8"))
        self.assertFalse(any("uninstall" in c for c in self.adb.calls))

    def test_install_apk_failure_and_validation(self):
        s = self.make()
        self.adb.install_ok = False
        with self.assertRaises(SessionError):
            s.install_apk(self._apk())
        self.assertTrue(any(c.startswith("rm /data/local/tmp/tvdebloat-") for c in self.adb.calls))
        with self.assertRaises(ApkError):
            validate_apk(self._apk("x.apk", manifest=False))
        notzip = Path(self.tmp.name) / "y.apk"
        notzip.write_bytes(b"not a zip")
        with self.assertRaises(ApkError):
            validate_apk(notzip)
        with self.assertRaises(ApkError):
            validate_apk(self._apk("z.xapk"))

    def test_private_dns_keeps_originals(self):
        s = self.make()
        s.ws.start_restore()
        self.adb.settings["private_dns_mode"] = "opportunistic"
        s.set_private_dns("dns.adguard-dns.com")
        self.assertIn("settings put global private_dns_mode hostname", self.adb.calls)
        self.assertEqual(s.ws.read_original_settings()["private_dns_mode"], "opportunistic")
        s.reset_private_dns()
        self.assertEqual(self.adb.calls[-1], "settings put global private_dns_mode opportunistic")
        with self.assertRaises(SessionError):
            s.set_private_dns("not a host;rm")

    def test_dns_refused_on_platforms_without_it(self):
        s = self.make()
        s.platform = PLATFORMS["firetv"]
        with self.assertRaises(SessionError):
            s.set_private_dns("dns.adguard-dns.com")
        with self.assertRaises(SessionError):
            s.unlock_launcher_disable()

    def test_firetv_brand_protection_applies_in_scan(self):
        s = self.make()
        s.brand = get_brand("firetv", "Fire TV Stick / Cube")
        s.platform = PLATFORMS["firetv"]
        s.scan()
        s.infos["com.example.mystery"].verdict  # existe
        clf = s._classifier()
        self.assertEqual(clf.classify("com.amazon.tv.launcher").group, 6)

    def test_report(self):
        s = self.make()
        s.backup()
        s.scan()
        s.disable_batch(["com.sambatv.acr"], "Lote 1")
        s.measure_after()
        rep = s.final_report()
        self.assertIn("| RAM total |", rep)
        self.assertIn("com.sambatv.acr", rep)
        self.assertIn("restore.sh", rep)


if __name__ == "__main__":
    unittest.main()
