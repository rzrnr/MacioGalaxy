"""The game side: write edited zones as a mod, play them headless, or start the game there.

- write_mod: zone archives go to <user>/mods/<Mod>/files/StageData/<Zone>.arc (plain RARC, which the
  game reads as well as Yaz0); mod.txt is written when the mod is new, its priority raised above any
  enabled mod that supplies the same files (so the edit is what the game loads), and mods.txt gets
  Folder.<Mod>=on (other lines kept).
- Preview: the game's smoke run in a throwaway user folder (a copy of a marked stage-test folder, never
  the player's saves), headless, with pictures; refused while the player's game runs, since two games
  on one GPU have crashed the running one.
- Play: starts the installed game with --stage, straight into the galaxy after a file is loaded.
- Testplay: the level testbed ("Galaxy Testbed.app", native/app/testbed_main.cpp), the game's logic for
  one galaxy without title, file select or saves. Started once; while it runs, a save tells it over its
  socket to reload the edited zones and restart the mission in-process.
"""
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

from .galaxy import GameData

APP = Path("/Applications/Super Mario Galaxy.app")
PLAYER_BINARY = APP / "Contents/MacOS/Petari"
CACHE = Path.home() / "Library/Caches/MacioGalaxyEditor"
WHITEHOLE_PREVIEW = Path(__file__).resolve().parents[4] / "Whitehole/preview"
REPO = Path(__file__).resolve().parents[3]
TESTBED_APPS = [Path("/Applications/Galaxy Testbed.app"), REPO / "build/macos-gx/native/app/Galaxy Testbed.app"]
TESTBED = CACHE / "testbed"
CONTROL = TESTBED / "control.sock"


def game_running() -> bool:
    """The installed game runs: a process named Petari whose executable is the app's (pgrep -f would
    also match any command line that merely mentions the path)."""
    pids = subprocess.run(["pgrep", "-x", "Petari"], capture_output=True, text=True).stdout.split()
    for pid in pids:
        command = subprocess.run(["ps", "-o", "comm=", "-p", pid], capture_output=True, text=True).stdout.strip()
        if command == str(PLAYER_BINARY):
            return True
    return False


def write_mod(game: GameData, mod_name: str, zones: dict, description: str = "") -> list:
    """zones: zone name -> archive bytes. Returns the files written."""
    root = game.user / "mods" / mod_name
    target = root / "files/StageData"
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for zone, data in zones.items():
        path = target / f"{zone}.arc"
        path.write_bytes(data)
        written.append(path)
    info = root / "mod.txt"
    others = [m for m in game.enabled_mods() if m.name != mod_name and
              any((m.root / "files/StageData" / f"{z}.arc").exists() for z in zones)]
    needed = max([m.priority for m in others], default=-1) + 1
    if not info.exists():
        info.write_text(f"name={mod_name}\ndescription={description or 'Edited in Blender (MacioGalaxy editor)'}\n"
                        f"priority={max(needed, 0)}\n")
    else:
        text = info.read_text()
        match = re.search(r"^priority\s*=\s*(-?\d+)", text, re.M)
        current = int(match.group(1)) if match else 0
        if current < needed:
            text = re.sub(r"^priority\s*=.*$", f"priority={needed}", text, flags=re.M) if match else text + f"priority={needed}\n"
            info.write_text(text)
    mods_txt = game.user / "mods.txt"
    lines = mods_txt.read_text().splitlines() if mods_txt.exists() else []
    key = f"Folder.{mod_name}"
    lines = [line for line in lines if not re.match(rf"\s*{re.escape(key)}\s*=", line)] + [f"{key}=on"]
    mods_txt.write_text("\n".join(lines) + "\n")
    return written


def set_mod_enabled(game: GameData, mod_name: str, on: bool):
    """Folder.<Mod>=on|off in mods.txt (other lines kept)."""
    mods_txt = game.user / "mods.txt"
    lines = mods_txt.read_text().splitlines() if mods_txt.exists() else []
    key = f"Folder.{mod_name}"
    lines = [line for line in lines if not re.match(rf"\s*{re.escape(key)}\s*=", line)] + [f"{key}={'on' if on else 'off'}"]
    mods_txt.write_text("\n".join(lines) + "\n")


def _template() -> Path:
    """A marked stage-test user folder: ours, else made from the Whitehole preview's."""
    template = CACHE / "preview/user-template"
    if not (template / ".petari-test-fixture").exists():
        source = WHITEHOLE_PREVIEW / "user-template"
        if not (source / ".petari-test-fixture").exists():
            raise RuntimeError("Kein Testordner für die Vorschau: native/tools/create_observatory_fixture.py --kind stage "
                               f"anlegen und nach {template} legen.")
        shutil.copytree(source, template)
    cache = CACHE / "preview/pipeline-cache"
    if not cache.exists() and (WHITEHOLE_PREVIEW / "pipeline-cache").is_dir():
        shutil.copytree(WHITEHOLE_PREVIEW / "pipeline-cache", cache)
    return template


class Preview:
    """A headless run started in the background; poll() until it is done."""

    def __init__(self, game: GameData, galaxy: str, scenario: int, warp=None, frames=4000, pictures=6):
        if game_running():
            raise RuntimeError("Das Spiel läuft: eine Vorschau daneben kann es abstürzen lassen (gleiche GPU). "
                               "Erst das Spiel schließen.")
        template = _template()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.run = CACHE / "preview/runs" / f"{stamp}-{galaxy}"
        self.user, self.pictures_dir = self.run / "user", self.run / "pictures"
        shutil.copytree(template, self.user)
        self.pictures_dir.mkdir(parents=True)
        mods = [m.name for m in game.enabled_mods()]
        for mod in game.enabled_mods():
            shutil.copytree(mod.root, self.user / "mods" / mod.name)
        env = dict(os.environ)
        env.update({
            "PETARI_SMOKE": "stage", "PETARI_STAGE": galaxy, "PETARI_SCENARIO": str(scenario),
            "PETARI_SMOKE_FRAMES": str(frames), "PETARI_STAGE_IDLE_FRAMES": "300", "PETARI_SMOKE_BACKGROUND": "1",
            "PETARI_PIPELINE_GLOBAL_PRECOMPILE": "0", "PETARI_PIPELINE_POLICY": "blocking",
            "PETARI_CACHE_DIR": str(CACHE / "preview/pipeline-cache"), "PETARI_MOD_FOLDERS": ",".join(mods) or "none",
            "SDL_AUDIO_DRIVER": "dummy", "PETARI_SURFACE_DUMP": str(self.pictures_dir), "PETARI_SURFACE_DUMP_EVERY": "30",
            "PETARI_SURFACE_DUMP_LABELS": "other,idle,walk,jump,camera", "PETARI_SURFACE_DUMP_SPAN": "900",
        })
        if warp is not None:
            env["PETARI_STAGE_WARP"] = ",".join(f"{v:.0f}" for v in warp)
        self.wanted = pictures
        self.log = self.run / "game.log"
        self._out = self.log.open("wb")
        self.process = subprocess.Popen([str(PLAYER_BINARY), "--disc", str(game.disc.parent), "--user", str(self.user),
                                         "--test-fixture", "stage"], env=env, stdout=self._out, stderr=subprocess.STDOUT,
                                        cwd=str(self.run))
        self.started = time.time()

    def poll(self, timeout=600):
        """None while running; then (passed, summary lines, pictures)."""
        if self.process.poll() is None:
            if time.time() - self.started < timeout:
                return None
            self.process.kill()
            self.process.wait()
        self._out.close()
        lines = self.log.read_text(errors="replace").splitlines()
        summary = [line for line in lines if line.startswith("PETARI SMOKE") and any(
            k in line for k in ("stage ready", "after the warp", "PASS", "FAIL", "RESULT"))]
        summary += [line for line in lines if "[mods] conflict" in line or "fatal" in line.lower()]
        shots = sorted(self.pictures_dir.glob("*.png"), key=lambda p: p.stat().st_mtime)
        chosen = [shots[round(i * (len(shots) - 1) / max(1, self.wanted - 1))] for i in range(min(self.wanted, len(shots)))]
        passed = any("RESULT: PASS" in line for line in lines)
        return passed, summary[-20:], list(dict.fromkeys(chosen))


def play(galaxy: str, scenario: int):
    """Starts the installed game; after a file is loaded it goes straight to the galaxy."""
    if game_running():
        raise RuntimeError("Das Spiel läuft schon. Erst schließen, dann hier starten.")
    subprocess.Popen(["open", "-a", str(APP), "--args", "--stage", galaxy, "--scenario", str(scenario)])


def testbed_binary():
    """The testbed's executable: MGE_TESTBED, else the installed app, else the repository's build."""
    if os.environ.get("MGE_TESTBED"):
        return Path(os.environ["MGE_TESTBED"])
    for app in TESTBED_APPS:
        binary = app / "Contents/MacOS/Galaxy Testbed"
        if binary.exists():
            return binary
    return None


def testbed_command(command: str, timeout: float = 2.0, control: Path = CONTROL):
    """One command to the running testbed; its reply line, or None when none answers."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(str(control))
            connection.sendall((command + "\n").encode())
            reply = b""
            while not reply.endswith(b"\n"):
                chunk = connection.recv(512)
                if not chunk:
                    break
                reply += chunk
            return reply.decode(errors="replace").strip()
    except OSError:
        return None


def testbed_status(control: Path = CONTROL):
    """The running testbed's status as a dict (stage, scenario, control, reloads, launch, reload, pid), or None."""
    reply = testbed_command("status", control=control)
    if not reply or not reply.startswith("ok "):
        return None
    return dict(item.split("=", 1) for item in reply[3:].split() if "=" in item)


def _spawn_text(spawn):
    return ",".join(f"{v:.0f}" for v in spawn) if spawn is not None else "none"


class Testplay:
    """Testspielen: the running testbed reloads (same galaxy and mission), else a new one starts. poll() until
    Mario can be played; the times are the testbed's own (launch to control, reload request to control)."""

    def __init__(self, game: GameData, galaxy: str, scenario: int, spawn=None, control: Path = CONTROL,
                 user: Path = TESTBED / "user", background=False, fresh=False):
        self.control, self.started = control, time.time()
        self.process = None
        status = testbed_status(control)
        if status and not fresh and (status.get("stage"), status.get("scenario")) == (galaxy, str(scenario)):
            reply = testbed_command(f"reload {_spawn_text(spawn)}", control=control)
            if reply and reply.startswith("ok"):
                self.mode, self.reloads = "reload", int(status.get("reloads", 0))
                return
        if status:
            # Another galaxy or mission (or a reload refused): a fresh start is the fast way there.
            testbed_command("quit", control=control)
            self._wait_gone(int(status.get("pid", 0)))
        if game_running():
            raise RuntimeError("Das Spiel läuft: das Testbed daneben kann es abstürzen lassen (gleiche GPU). "
                               "Erst das Spiel schließen.")
        binary = testbed_binary()
        if binary is None:
            raise RuntimeError("Kein „Galaxy Testbed.app“: im Repository mit "
                               "cmake --build build/macos-gx --target petari_testbed bauen.")
        TESTBED.mkdir(parents=True, exist_ok=True)
        args = [str(binary), "--stage", galaxy, "--scenario", str(scenario), "--disc", str(game.disc.parent),
                "--player-user", str(game.user), "--user", str(user), "--control", str(control)]
        if spawn is not None:
            args += ["--spawn", _spawn_text(spawn)]
        if background:
            args.append("--background")
        self.log = TESTBED / "testbed.log"
        env = {k: v for k, v in os.environ.items() if k != "PETARI_MOD_FOLDERS"}
        with self.log.open("wb") as out:
            self.process = subprocess.Popen(args, env=env, stdout=out, stderr=subprocess.STDOUT, cwd=str(TESTBED))
        self.mode, self.reloads = "launch", 0

    @staticmethod
    def _wait_gone(pid, timeout=10.0):
        end = time.time() + timeout
        while pid and time.time() < end:
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.1)

    def poll(self, timeout=180):
        """None while loading; then (ok, seconds as the testbed measured them, message)."""
        if self.process is not None and self.process.poll() is not None:
            return False, None, f"Testbed beendet (Status {self.process.returncode}), siehe {self.log}"
        status = testbed_status(self.control)
        if status:
            if status.get("error"):
                return False, None, f"Neuladen fehlgeschlagen: {status['error']}"
            if self.mode == "launch" and status.get("control") == "1" and float(status.get("launch", -1)) >= 0:
                return True, float(status["launch"]), "gestartet"
            if self.mode == "reload" and int(status.get("reloads", 0)) > self.reloads and status.get("control") == "1":
                return True, float(status["reload"]), "neu geladen"
        if time.time() - self.started > timeout:
            return False, None, "Zeitüberschreitung beim Laden"
        return None

