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
        # Whole or not at all: a running testbed may be reading the old file. The temporary file lies
        # beside files/ (same volume), where the game never looks for mod files.
        partial = root / f".{zone}.arc.partial"
        try:
            partial.write_bytes(data)
            os.replace(partial, path)
        finally:
            partial.unlink(missing_ok=True)
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
    """Starts the installed game; after a file is loaded it goes straight to the galaxy. A running testbed is
    closed first (two games on one GPU have crashed)."""
    if game_running():
        raise RuntimeError("Das Spiel läuft schon. Erst schließen, dann hier starten.")
    stop_testbed()
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


def testbed_command(command: str, timeout: float = 0.5, control: Path = CONTROL):
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
    """The running testbed's status as a dict (stage, scenario, control, reloads, launch, reload, pid, error), or
    None. The error, when there is one, is last and runs to the end of the line."""
    if not control.exists():
        return None
    reply = testbed_command("status", control=control)
    if not reply or not reply.startswith("ok "):
        return None
    text, _, error = reply[3:].partition(" error=")
    status = dict(item.split("=", 1) for item in text.split() if "=" in item)
    if error:
        status["error"] = error
    return status


_cached = [0.0, None]


def testbed_status_cached(max_age=2.0):
    """testbed_status at most every max_age seconds."""
    if time.time() - _cached[0] > max_age:
        _cached[:] = [time.time(), testbed_status()]
    return _cached[1]


def testbed_status_known():
    """The last status the 2 s timer (or an operator) fetched, without asking: for drawing, which must not
    wait on a socket."""
    return _cached[1]


_child = [None]  # the testbed this Blender started (subprocess.Popen), reaped here


def _alive(pid):
    """The process still runs. Our own child is asked through its Popen (an exited child that is not
    reaped would still answer kill 0)."""
    child = _child[0]
    if child is not None and child.pid == pid:
        return child.poll() is None
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_testbed(control: Path = CONTROL, timeout=8.0):
    """Asks the running testbed to quit. Only if it does not answer at all (hung) is it ended by its pid
    (our own test app, never the player's game)."""
    status = testbed_status(control)
    child = _child[0]
    pid = int(status.get("pid", 0)) if status else (child.pid if child is not None and child.poll() is None else 0)
    _cached[:] = [0.0, None]
    if running is not None:
        running.stopped = True  # a Testspielen under way ends quietly instead of starting it again
    answered = testbed_command("quit", control=control) is not None
    if pid <= 1 or pid == os.getpid():  # never a process group, init or Blender itself
        return answered
    end = time.time() + (timeout if answered else 1.0)
    while time.time() < end:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    for sig in (15, 9):
        try:
            os.kill(pid, sig)
        except OSError:
            return True
        end = time.time() + 2.0
        while time.time() < end:
            if not _alive(pid):
                return True
            time.sleep(0.05)
    return True


# The testbed's errors (status error=) in the editor's words.
ERRORS = {"the drive is busy": "das Spiel las gerade Dateien",
          "entry numbers would change": "Mod-Dateien kamen hinzu oder fehlen (Neustart nötig)",
          "could not be entered": "die Mission war nicht erreichbar"}


def error_text(error):
    return next((german for key, german in ERRORS.items() if key in error), error)


def seconds_text(seconds):
    """Seconds the German way: 9,2 s."""
    return f"{seconds:.1f}".replace(".", ",") + " s"


def testbed_app():
    """The testbed's .app bundle, or None."""
    binary = testbed_binary()
    return binary.parents[2] if binary is not None and binary.parent.name == "MacOS" else None


def show_testbed():
    """Brings the running testbed's window to the front (only a running one: open -a would start a bare one)."""
    app = testbed_app()
    if app is not None and testbed_status() is not None:
        subprocess.Popen(["open", "-a", str(app)])
        return True
    return False


# The Testspielen run in progress (one at a time): set by the operator, for the panels.
running = None


def _spawn_text(spawn):
    return ",".join(f"{v:.0f}" for v in spawn) if spawn is not None else "none"


class Testplay:
    """Testspielen: the running testbed reloads (same galaxy and mission), else a new one starts. poll() until
    Mario can be played; the times are the testbed's own (launch to control, reload request to control)."""

    def __init__(self, game: GameData, galaxy: str, scenario: int, spawn=None, control: Path = CONTROL,
                 user: Path = TESTBED / "user", background=False, fresh=False):
        if running is not None and running.mode == "launch" and not running.done:
            raise RuntimeError("Das Testspiel startet noch: einen Moment warten")
        self.control, self.started = control, time.time()
        self.process, self.pid, self.restarted = None, 0, None
        self.failure, self.stopped, self.follow = None, False, False
        _cached[0] = 0.0
        status = testbed_status(control)
        if status and not fresh and (status.get("stage"), status.get("scenario")) == (galaxy, str(scenario)):
            reply = testbed_command(f"reload {_spawn_text(spawn)}", control=control)
            if reply and reply.startswith("ok"):
                self.mode, self.reloads, self.pid = "reload", int(status.get("reloads", 0)), int(status.get("pid", 0))
                self.done = False
                return
        if status:
            # Another galaxy or scenario (or a reload refused): a fresh start is the fast way there.
            self.restarted = "retry" if fresh else "other"
            stop_testbed(control)
        if game_running():
            raise RuntimeError("Das Spiel läuft noch: erst beenden, dann Testspielen (beide zusammen können abstürzen)")
        binary = testbed_binary()
        if binary is None:
            raise RuntimeError("„Galaxy Testbed“ fehlt: im MacioGalaxy-Ordner bauen (cmake --build build/macos-gx "
                               "--target petari_testbed) oder die App in den Programme-Ordner legen")
        TESTBED.mkdir(parents=True, exist_ok=True)
        args = [str(binary), "--stage", galaxy, "--scenario", str(scenario), "--disc", str(game.disc.parent),
                "--player-user", str(game.user), "--user", str(user), "--control", str(control)]
        if spawn is not None:
            args += ["--spawn", _spawn_text(spawn)]
        if background or os.environ.get("MGE_TESTBED_BACKGROUND") == "1":  # hidden, for tests of the UI
            args.append("--background")
        self.log = TESTBED / "testbed.log"
        env = {k: v for k, v in os.environ.items() if k != "PETARI_MOD_FOLDERS"}
        with self.log.open("wb") as out:
            self.process = subprocess.Popen(args, env=env, stdout=out, stderr=subprocess.STDOUT, cwd=str(TESTBED))
        _child[0] = self.process
        self.mode, self.reloads, self.done = "launch", 0, False

    def follow_reload(self):
        """A save while it still starts: once it is ready, wait for the restart that takes the save."""
        self.follow = True

    def progress(self):
        """What to show while waiting: a line with the seconds so far."""
        seconds = time.time() - self.started
        if self.mode == "reload":
            if seconds > 20:
                return f"Wartet, bis Mario steuerbar ist ({seconds:.0f} s; offenes Pausenmenü schließen)"
            return f"Lädt Änderungen … {seconds:.0f} s von etwa 8 s"
        first = {"other": "Anderes Szenario: Testspiel startet neu", "retry": "Testspiel startet neu"}.get(
            self.restarted, "Testspiel startet")
        return f"{first} … {seconds:.0f} s von etwa 10 s"

    def poll(self, timeout=None):
        """None while loading; then (ok, seconds as the testbed measured them, message). After a failure,
        self.failure says why: "error" (the testbed refused the reload: a fresh start may help), "gone",
        "timeout" or "stopped" (closed on purpose)."""
        result = self._poll(timeout)
        if result is not None and result[0] and self.mode == "launch" and self.follow:
            # Ready, and a save came while it started: now wait for that restart.
            self.mode, self.follow, self.started, self.reloads = "reload", False, time.time(), 0
            return None
        self.done = result is not None
        return result

    def _poll(self, timeout):
        timeout = timeout or (60 if self.mode == "reload" else 150)
        if self.stopped:
            self.failure = "stopped"
            return False, None, "Testspiel beendet"
        self.failure = "gone"
        if self.process is not None and self.process.poll() is not None:
            return False, None, f"Testspiel wurde geschlossen oder ist abgestürzt (Protokoll: {self.log})"
        if self.pid > 1 and not _alive(self.pid):
            return False, None, "Testspiel wurde geschlossen oder ist abgestürzt"
        status = testbed_status(self.control)
        if status:
            if status.get("error"):
                self.failure = "error"
                return False, None, f"Neuladen ging nicht: {error_text(status['error'])}"
            if self.mode == "launch" and status.get("control") == "1" and float(status.get("launch", -1)) >= 0:
                return True, float(status["launch"]), "bereit"
            if self.mode == "reload" and int(status.get("reloads", 0)) > self.reloads and status.get("control") == "1":
                return True, float(status["reload"]), "neu geladen"
        if time.time() - self.started > timeout:
            self.failure = "timeout"
            return False, None, "Testspiel reagiert nicht: sein Fenster schließen und nochmal Testspielen"
        self.failure = None
        return None

