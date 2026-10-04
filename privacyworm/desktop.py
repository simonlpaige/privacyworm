"""Operating-system integration: app-menu shortcuts and check-up reminders.

Everything here is best-effort and reversible:

- ``create_shortcut()`` adds "PrivacyWorm" to the Start menu (Windows),
  ~/Applications (macOS) or the app launcher (Linux).
- ``enable_reminders()`` registers a once-a-day job with the OS scheduler
  (Task Scheduler, launchd, or a systemd user timer / cron). The job runs
  ``privacyworm remind``, which does nothing unless a re-check is due.
  When one is, it pops PrivacyWorm open (Windows/macOS) or shows a
  desktop notification (Linux).

No passphrase or personal data is stored for this. The only thing the
reminder reads is ``schedule.json``: the date the next check-up is due.
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess  # nosec B404 - fixed argv to OS schedulers, never a shell
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from privacyworm.config import get_config_dir

APP_NAME = "PrivacyWorm"
TASK_NAME = "PrivacyWorm Reminder"
LAUNCHD_LABEL = "com.privacyworm.reminder"
SYSTEMD_UNIT = "privacyworm-reminder"
CRON_TAG = "# privacyworm-reminder"
REMIND_HOUR = 10
# Don't nag more than this often, even if the user ignores the reminder.
RENAG_DAYS = 3
DEFAULT_INTERVAL_DAYS = 30


def platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)  # nosec B603


def _ps(script: str) -> subprocess.CompletedProcess:
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script])


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


# -- Finding our own executable --------------------------------------------


def app_executable() -> str:
    """Absolute path to the ``privacyworm`` launcher."""
    found = shutil.which("privacyworm")
    if found:
        return str(Path(found).absolute())
    argv0 = Path(sys.argv[0])
    if argv0.name.lower().startswith("privacyworm") and argv0.exists():
        return str(argv0.resolve())
    # Last resort: run the module with this interpreter.
    return sys.executable


def _app_command() -> list[str]:
    exe = app_executable()
    if exe == sys.executable:
        return [exe, "-m", "privacyworm"]
    return [exe]


def _remind_command() -> list[str]:
    """The command the scheduler runs. Windowless on Windows."""
    if platform() == "windows":
        exe = Path(app_executable())
        gui = exe.with_name("privacyworm-remind.exe")
        if gui.exists():
            return [str(gui)]
        found = shutil.which("privacyworm-remind")
        if found:
            return [found]
    return _app_command() + ["remind"]


# -- Schedule file (plaintext, holds only a date) ---------------------------


def _schedule_path() -> Path:
    return get_config_dir() / "schedule.json"


def read_schedule() -> dict:
    try:
        return json.loads(_schedule_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_schedule(data: dict) -> None:
    path = _schedule_path()
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def set_next_due(next_due_iso: str | None) -> None:
    """Record when the next check-up is due (called after each check-up)."""
    data = read_schedule()
    if not next_due_iso:
        next_due_iso = (datetime.now(timezone.utc) + timedelta(days=DEFAULT_INTERVAL_DAYS)).isoformat()
    data["next_due"] = next_due_iso
    data.pop("last_reminded", None)
    write_schedule(data)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def next_due() -> datetime | None:
    return _parse(read_schedule().get("next_due"))


def is_due(now: datetime | None = None) -> bool:
    due = next_due()
    now = now or datetime.now(timezone.utc)
    return due is not None and due <= now


def should_remind(now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if not is_due(now):
        return False
    last = _parse(read_schedule().get("last_reminded"))
    return last is None or now - last >= timedelta(days=RENAG_DAYS)


# -- Shortcuts ---------------------------------------------------------------


def _mac_app_dir() -> Path:
    return Path.home() / "Applications" / f"{APP_NAME}.app"


def _linux_desktop_file() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "applications" / "privacyworm.desktop"


def _windows_shortcut_paths() -> list[Path]:
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    start_menu = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_NAME}.lnk"
    desktop = Path.home() / "Desktop" / f"{APP_NAME}.lnk"
    return [start_menu, desktop]


def create_shortcut() -> str:
    """Add PrivacyWorm to the app menu. Returns a human description."""
    cmd = _app_command()
    plat = platform()
    if plat == "windows":
        made = []
        for lnk in _windows_shortcut_paths():
            if not lnk.parent.exists():
                continue
            args = " ".join(cmd[1:])
            script = (
                "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(" + _ps_quote(str(lnk)) + ");"
                "$s.TargetPath=" + _ps_quote(cmd[0]) + ";"
                "$s.Arguments=" + _ps_quote(args) + ";"
                "$s.WorkingDirectory=" + _ps_quote(str(Path.home())) + ";"
                "$s.Description='Find and remove your data-broker listings';"
                "$s.Save()"
            )
            if _ps(script).returncode == 0:
                made.append("Start menu" if "Start Menu" in str(lnk) else "Desktop")
        return f"Added PrivacyWorm to your {' and '.join(made)}." if made else ""
    if plat == "mac":
        app = _mac_app_dir()
        macos = app / "Contents" / "MacOS"
        res = app / "Contents" / "Resources"
        macos.mkdir(parents=True, exist_ok=True)
        res.mkdir(parents=True, exist_ok=True)
        command_file = res / f"{APP_NAME}.command"
        quoted = " ".join(_sh_quote(c) for c in cmd)
        command_file.write_text(f"#!/bin/sh\nclear\nexec {quoted}\n", encoding="utf-8")
        command_file.chmod(0o755)
        launcher = macos / APP_NAME
        launcher.write_text(
            f'#!/bin/sh\nopen -a Terminal {_sh_quote(str(command_file))}\n', encoding="utf-8"
        )
        launcher.chmod(0o755)
        with open(app / "Contents" / "Info.plist", "wb") as f:
            plistlib.dump({
                "CFBundleName": APP_NAME,
                "CFBundleDisplayName": APP_NAME,
                "CFBundleIdentifier": "com.privacyworm.app",
                "CFBundleExecutable": APP_NAME,
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": "1",
            }, f)
        return "Added PrivacyWorm to your Applications folder (search for it with Spotlight)."
    # linux
    desktop = _linux_desktop_file()
    desktop.parent.mkdir(parents=True, exist_ok=True)
    exec_line = " ".join(_desktop_quote(c) for c in cmd)
    desktop.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Find and remove your data-broker listings\n"
        f"Exec={exec_line}\n"
        "Terminal=true\n"
        "Icon=security-high\n"
        "Categories=Utility;Security;\n",
        encoding="utf-8",
    )
    return "Added PrivacyWorm to your app launcher."


def remove_shortcut() -> None:
    plat = platform()
    if plat == "windows":
        for lnk in _windows_shortcut_paths():
            lnk.unlink(missing_ok=True)
    elif plat == "mac":
        shutil.rmtree(_mac_app_dir(), ignore_errors=True)
    else:
        _linux_desktop_file().unlink(missing_ok=True)


def _sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _desktop_quote(s: str) -> str:
    if any(c in s for c in ' "\\`$'):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$") + '"'
    return s


# -- Reminders: enable / disable / status ------------------------------------


def _launchd_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def _systemd_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "systemd" / "user"


def _has_systemd_user() -> bool:
    if not shutil.which("systemctl"):
        return False
    r = _run(["systemctl", "--user", "show-environment"])
    return r.returncode == 0


def reminders_enabled() -> bool:
    plat = platform()
    if plat == "windows":
        return _run(["schtasks", "/Query", "/TN", TASK_NAME]).returncode == 0
    if plat == "mac":
        return _launchd_plist().exists()
    if (_systemd_dir() / f"{SYSTEMD_UNIT}.timer").exists():
        return True
    if shutil.which("crontab"):
        r = _run(["crontab", "-l"])
        return r.returncode == 0 and CRON_TAG in r.stdout
    return False


def enable_reminders() -> tuple[bool, str]:
    """Register the daily check. Returns (ok, message)."""
    cmd = _remind_command()
    plat = platform()
    if not next_due():
        set_next_due(None)
    if plat == "windows":
        script = (
            "$a = New-ScheduledTaskAction -Execute " + _ps_quote(cmd[0])
            + (f" -Argument {_ps_quote(' '.join(cmd[1:]))}" if cmd[1:] else "") + ";"
            f"$t = New-ScheduledTaskTrigger -Daily -At '{REMIND_HOUR}:00';"
            "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries "
            "-DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5);"
            "Register-ScheduledTask -TaskName " + _ps_quote(TASK_NAME)
            + " -Action $a -Trigger $t -Settings $s -Force | Out-Null"
        )
        r = _ps(script)
        if r.returncode == 0:
            return True, "Reminders are on. Windows will open PrivacyWorm when a check-up is due."
        return False, f"Windows Task Scheduler said no: {(r.stderr or r.stdout).strip()[:300]}"
    if plat == "mac":
        plist = _launchd_plist()
        plist.parent.mkdir(parents=True, exist_ok=True)
        with open(plist, "wb") as f:
            plistlib.dump({
                "Label": LAUNCHD_LABEL,
                "ProgramArguments": cmd,
                "StartCalendarInterval": {"Hour": REMIND_HOUR, "Minute": 0},
                "RunAtLoad": False,
                "StandardOutPath": str(get_config_dir() / "reminder.log"),
                "StandardErrorPath": str(get_config_dir() / "reminder.log"),
            }, f)
        uid = os.getuid()  # type: ignore[attr-defined,unused-ignore]
        _run(["launchctl", "bootout", f"gui/{uid}", str(plist)])
        r = _run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)])
        if r.returncode != 0:
            r = _run(["launchctl", "load", "-w", str(plist)])
        if r.returncode == 0:
            return True, "Reminders are on. Your Mac will open PrivacyWorm when a check-up is due."
        return False, f"launchctl said no: {(r.stderr or r.stdout).strip()[:300]}"
    # linux
    exec_line = " ".join(_desktop_quote(c) for c in cmd)
    if _has_systemd_user():
        d = _systemd_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{SYSTEMD_UNIT}.service").write_text(
            "[Unit]\nDescription=PrivacyWorm check-up reminder\n\n"
            f"[Service]\nType=oneshot\nExecStart={exec_line}\n",
            encoding="utf-8",
        )
        (d / f"{SYSTEMD_UNIT}.timer").write_text(
            "[Unit]\nDescription=Daily PrivacyWorm check-up reminder\n\n"
            f"[Timer]\nOnCalendar=*-*-* {REMIND_HOUR:02d}:00:00\nPersistent=true\n\n"
            "[Install]\nWantedBy=timers.target\n",
            encoding="utf-8",
        )
        _run(["systemctl", "--user", "daemon-reload"])
        r = _run(["systemctl", "--user", "enable", "--now", f"{SYSTEMD_UNIT}.timer"])
        if r.returncode == 0:
            return True, "Reminders are on. You'll get a desktop notification when a check-up is due."
        return False, f"systemd said no: {(r.stderr or r.stdout).strip()[:300]}"
    if shutil.which("crontab"):
        current = _run(["crontab", "-l"])
        lines = [ln for ln in (current.stdout if current.returncode == 0 else "").splitlines() if CRON_TAG not in ln]
        lines.append(f"0 {REMIND_HOUR} * * * {exec_line} {CRON_TAG}")
        r = subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True,  # nosec B603 B607
                           capture_output=True, check=False)
        if r.returncode == 0:
            return True, "Reminders are on (via cron). You'll get a desktop notification when a check-up is due."
        return False, f"crontab said no: {r.stderr.strip()[:300]}"
    return False, "Couldn't find a scheduler (systemd or cron) on this computer."


def disable_reminders() -> tuple[bool, str]:
    plat = platform()
    if plat == "windows":
        _ps(f"Unregister-ScheduledTask -TaskName {_ps_quote(TASK_NAME)} -Confirm:$false")
    elif plat == "mac":
        plist = _launchd_plist()
        if plist.exists():
            uid = os.getuid()  # type: ignore[attr-defined,unused-ignore]
            r = _run(["launchctl", "bootout", f"gui/{uid}", str(plist)])
            if r.returncode != 0:
                _run(["launchctl", "unload", "-w", str(plist)])
            plist.unlink(missing_ok=True)
    else:
        d = _systemd_dir()
        if (d / f"{SYSTEMD_UNIT}.timer").exists():
            _run(["systemctl", "--user", "disable", "--now", f"{SYSTEMD_UNIT}.timer"])
            (d / f"{SYSTEMD_UNIT}.timer").unlink(missing_ok=True)
            (d / f"{SYSTEMD_UNIT}.service").unlink(missing_ok=True)
            _run(["systemctl", "--user", "daemon-reload"])
        if shutil.which("crontab"):
            current = _run(["crontab", "-l"])
            if current.returncode == 0 and CRON_TAG in current.stdout:
                lines = [ln for ln in current.stdout.splitlines() if CRON_TAG not in ln]
                subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True,  # nosec B603 B607
                               capture_output=True, check=False)
    return True, "Reminders are off."


# -- The reminder itself ------------------------------------------------------


def _notify(title: str, message: str) -> None:
    plat = platform()
    if plat == "mac":
        script = f"display notification {json.dumps(message)} with title {json.dumps(title)}"
        _run(["osascript", "-e", script])
    elif plat == "linux" and shutil.which("notify-send"):
        _run(["notify-send", "--app-name", APP_NAME, title, message])


def _open_app_window() -> bool:
    """Open PrivacyWorm in a terminal window. Returns True if it launched."""
    plat = platform()
    try:
        if plat == "windows":
            flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            exe = Path(app_executable())
            console = exe.with_name("privacyworm.exe")
            cmd = [str(console)] if console.exists() else _app_command()
            subprocess.Popen(cmd + ["--reminder"], creationflags=flags)  # nosec B603
            return True
        if plat == "mac":
            app = _mac_app_dir()
            if not app.exists():
                create_shortcut()
            return _run(["open", str(app)]).returncode == 0
        for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "xterm"):
            if shutil.which(term):
                sep = ["--"] if term == "gnome-terminal" else ["-e"]
                subprocess.Popen([term, *sep, *_app_command(), "--reminder"])  # nosec B603
                return True
    except OSError:
        return False
    return False


def remind(force: bool = False) -> str:
    """Run by the OS scheduler once a day. Quiet unless a check-up is due."""
    if not force and not should_remind():
        return "not due"
    data = read_schedule()
    data["last_reminded"] = datetime.now(timezone.utc).isoformat()
    write_schedule(data)
    _notify(APP_NAME, "Time for your privacy check-up. Brokers re-list people every few months.")
    if platform() in ("windows", "mac"):
        _open_app_window()
    return "reminded"


def remind_entrypoint() -> None:
    """Windowless entry point (``privacyworm-remind``) for Windows Task Scheduler."""
    try:
        remind()
    except Exception:  # noqa: BLE001 - a reminder must never show a crash dialog
        pass
