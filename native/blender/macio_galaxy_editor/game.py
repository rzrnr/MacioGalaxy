"""The game side: write edited zones as a mod, play them headless, or start the game there.

- write_mod: zone archives go to <user>/mods/<Mod>/files/StageData/<Zone>.arc (plain RARC, which the
  game reads as well as Yaz0); mod.txt is written when the mod is new, its priority raised above any
  enabled mod that supplies the same files (so the edit is what the game loads), and mods.txt gets
  Folder.<Mod>=on (other lines kept).
- Preview: the game's smoke run in a throwaway user folder (a copy of a marked stage-test folder, never
  the player's saves), headless, with pictures; refused while the player's game runs, since two games
  on one GPU have crashed the running one.
- Play: starts the installed game with --stage, straight into the galaxy after a file is loaded.
"""
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from .galaxy import GameData

APP = Path("/Applications/Super Mario Galaxy.app")
PLAYER_BINARY = APP / "Contents/MacOS/Petari"
CACHE = Path.home() / "Library/Caches/MacioGalaxyEditor"
WHITEHOLE_PREVIEW = Path(__file__).resolve().parents[4] / "Whitehole/preview"


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
