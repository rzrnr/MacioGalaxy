#!/bin/zsh
# Doppelklick: legt eine einzige Datei auf den Schreibtisch, "Mario Galaxy Spielstand <Datum>.zip",
# mit dem aktuellen Spielstand im Wii-Format (für Nebula oder Dolphin unter Windows) und der
# Anleitung guglis/SPIELSTAND_WINDOWS.md. Am besten mit beendetem Spiel.
cd -- "$(dirname -- "$0")/.."
python3 native/tools/convert_save.py bundle
status=$?
echo
if (( status == 0 )); then
    echo "Fertig. Die ZIP-Datei liegt auf dem Schreibtisch."
    open -R ~/Desktop/"Mario Galaxy Spielstand "*.zip(om[1]) 2>/dev/null
else
    echo "Export fehlgeschlagen (siehe oben)."
fi
read -k 1 "?Taste drücken zum Schließen."
