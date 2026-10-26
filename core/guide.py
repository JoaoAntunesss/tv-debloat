"""Step-by-step texts: TV preparation and the "next step" banner messages.

Menu names vary by brand and system version; the texts always give the typical path.
"""
from __future__ import annotations

PREP_STEPS: dict[str, list[tuple[str, str]]] = {
    "androidtv": [
        ("Turn on the TV and this computer on the same network",
         "Both on the same router, over Wi-Fi or cable. Avoid guest/visitor networks (they isolate devices)."),
        ("Enable Developer mode on the TV",
         "Settings → System → About → press 'Build' 7 times. A message says you are now a developer. "
         "On Google TV: Settings → System → About → 'Android TV OS build'."),
        ("Turn on debugging",
         "Settings → System → Developer options: enable 'USB debugging' and, if present, 'Wireless debugging' "
         "(Android 11 or newer)."),
        ("Find the TV's IP address",
         "Settings → Network & Internet → your network (or 'Status'). It looks like 192.168.1.50. You will type "
         "it in tab 1."),
        ("If 'Wireless debugging' exists: open it and note the pairing code",
         "Under 'Pair device with pairing code' you get an IP:port and a 6-digit code. You will use them in "
         "tab 1 (the pairing port is different from 5555)."),
        ("Keep the remote at hand and check what is plugged into the TV's USB ports",
         "The TV will ask 'Allow USB debugging?' and you must choose Allow. Some TVs cut power to the USB "
         "ports while debugging is on (speakers, disks): tell me what you have there in tab 1."),
    ],
    "firetv": [
        ("Turn on the Fire TV and this computer on the same network",
         "Both on the same router, over Wi-Fi or cable. Avoid guest/visitor networks."),
        ("Enable Developer options",
         "Settings → My Fire TV → About → press the device name 7 times. 'Developer options' then appear in "
         "My Fire TV."),
        ("Turn on ADB debugging",
         "Developer options → 'ADB debugging' on. To install APKs also enable 'Apps from unknown sources'."),
        ("Find the IP address",
         "Settings → My Fire TV → About → Network. It looks like 192.168.1.50."),
        ("Keep the remote at hand",
         "The Fire TV will ask 'Allow USB debugging?': choose Allow (and 'Always allow')."),
    ],
}

NEXT = {
    "start": "Step 0 — follow the preparation checklist (tab 0) and choose your TV's system and brand.",
    "prep_done": ("✔ Preparation done. Step 1 — go to tab '1 · Connect', type the TV's IP and press "
                  "'Connect to TV'. When the TV asks 'Allow USB debugging?', choose Allow."),
    "no_adb": ("This TV does not allow ADB, so there are no more steps in this app: follow the guide above "
               "(network-level action and TV settings)."),
    "connected": ("✔ Connected. Step 2 — tab '2 · Backup': choose the folder and press 'Back up'. "
                  "Nothing is changed on the TV yet."),
    "backup_done": ("✔ Backup done (and the restore script already exists). Step 3 — tab '3 · Packages': press "
                    "'Mark groups 1 and 2', review the list and press 'Disable selected'. After each batch "
                    "you confirm on the verification screen."),
    "verify": ("Check the TV: does the home screen appear? Does the Inputs menu open? Can you reach HDMI? If all is "
               "fine, 'continue'; if something broke, re-enable the batch."),
    "queue_done": ("✔ Batches finished. Next (in order): step 4 swaps the home screen for an ad-free one, "
                   "step 6 filters ads via DNS and installs apps, and step 5 lowers animations, reboots and "
                   "measures memory before/after."),
    "final": "Step 5 — generate the report: you get the before/after table and the command that undoes everything.",
}
