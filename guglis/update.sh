#!/bin/zsh
# Guglis Edits auf den neuesten offiziellen Stand setzen, bauen, testen und installieren (guglis/README.md).
# Aufruf: guglis/update.sh [--no-tests] [--no-install]
set -eu

branch=guglis-edits
app="/Applications/Super Mario Galaxy.app"
build=build/macos-gx
built_app="$build/native/app/Petari.app"

tests=1 install=1
for arg in "$@"; do
    case $arg in
        --no-tests) tests=0 ;;
        --no-install) install=0 ;;
        *) print -u2 -- "Unbekannte Option: $arg (erlaubt: --no-tests, --no-install)"; exit 2 ;;
    esac
done

cd -- "$(dirname -- "$0")/.."

if [[ "$(git branch --show-current)" != $branch ]]; then
    print -u2 -- "Nicht auf $branch. Erst: git switch $branch"
    exit 1
fi
if [[ -n "$(git status --porcelain)" ]]; then
    print -u2 -- "Ungesicherte Änderungen. Erst committen oder mit git stash -u beiseitelegen:"
    git status --short >&2
    exit 1
fi

print -- "== Offizielles Repo holen"
git fetch origin
if [[ -z "$(git rev-list HEAD..origin/main)" ]]; then
    print -- "Nichts Neues, die Guglis Edits sitzen schon auf dem aktuellen Stand."
else
    backup="$branch-vor-$(date +%Y-%m-%d-%H%M)"
    git branch "$backup"
    print -- "Bisheriger Stand gesichert als Branch $backup"
    print -- "Neu im offiziellen Repo:"
    git log --oneline HEAD..origin/main
    if ! git rebase origin/main; then
        print -u2 -- ""
        print -u2 -- "Konflikt beim Übernehmen. Lösen, dann git rebase --continue und guglis/update.sh erneut starten,"
        print -u2 -- "oder mit git rebase --abort zurück zum alten Stand."
        exit 1
    fi
fi
print -- "Guglis Edits:"
git log --oneline origin/main..HEAD

print -- "== Bauen"
cmake -S . -B "$build" >/dev/null
cmake --build "$build" --target petari -j 8
if (( tests )); then
    cmake --build "$build" -j 8
    cmake --build "$build" --target petari_tests -j 8
    print -- "== Tests"
    # native_rfl_render rendert einen Mii von der Disc und schlägt auf diesem Mac fehl,
    # unabhängig von den Guglis Edits. Timing-Tests brauchen einen ruhigen Mac.
    ctest --test-dir "$build" -LE timing -E '^native_rfl_render$' -j 6
fi

if (( ! install )); then
    print -- "Fertig, nicht installiert (--no-install)."
    exit 0
fi
print -- "== Installieren"
if [[ ! -d "$app" ]]; then
    print -u2 -- "$app fehlt. Die App mit Icon und Spielpfad muss einmal eingerichtet sein."
    exit 1
fi
if pgrep -x Petari >/dev/null; then
    print -u2 -- "Das Spiel läuft noch. Beenden und dann guglis/update.sh --no-tests starten."
    exit 1
fi
# Programm, Shader-Seeds und Icon; die Info.plist der App (Name, Spielpfad) bleibt.
ditto "$built_app/Contents/MacOS/Petari" "$app/Contents/MacOS/Petari"
rsync -a --delete "$built_app/Contents/Resources/pipeline-seeds/" "$app/Contents/Resources/pipeline-seeds/"
for icon in Assets.car SuperMarioGalaxy.icns; do
    if [[ -f "$built_app/Contents/Resources/$icon" ]]; then
        ditto "$built_app/Contents/Resources/$icon" "$app/Contents/Resources/$icon"
    fi
done
touch "$app"  # Finder and Dock pick up a changed icon
codesign --force --sign - "$app"
codesign --verify "$app"
print -- "Installiert: $app"
