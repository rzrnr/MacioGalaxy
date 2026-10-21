# Spielstand zwischen Mac (MacioGalaxy) und Windows (Nebula) übertragen

Diese Anleitung ist für Claude auf dem Windows-Rechner gedacht: Lies sie ganz,
prüfe die Punkte unter „Vorher prüfen“, und führe dann den passenden Ablauf aus.
Frag den Nutzer, bevor du einen vorhandenen Spielstand überschreibst.

## Worum es geht

Super Mario Galaxy speichert alles in einer Datei `GameData.bin` (alle sechs
Spieldateien, Mario und Luigi, Einstellungen). Es gibt sie in zwei
Byte-Reihenfolgen:

- **Wii-Format (Big-Endian):** Wii, Dolphin und Nebula.
- **Mac-Format (Little-Endian):** MacioGalaxy, der native Mac-Port.

Der Aufbau ist sonst identisch. Das Tool `native/tools/convert_save.py` in
diesem Repo (github.com/rzrnr/MacioGalaxy, Branch `guglis-edits`) dreht die
Felder um, rechnet die Prüfsumme neu und prüft jedes Ergebnis durch
Rückumwandlung.

**Wichtig:** Die Umwandlung passiert immer auf dem Mac. Auf Windows kommt nur
eine Datei an, die schon im Wii-Format ist, und Nebula liest dieses Format
direkt. Auf Windows wird also nur kopiert, nicht umgewandelt.

## Vorher prüfen (Windows)

1. **Nebula ist beendet.** Kein `Nebula.exe` und kein Spielprozess von Nebula
   in der Prozessliste (`Get-Process | Where-Object { $_.Name -like "*nebula*" }`).
2. **Speicherort finden.** Nach Nebulas README liegt der Spielstand der
   US-Version (RMGE01) hier:

   ```
   %LOCALAPPDATA%\Nebula\saves\title\00010000\524d4745\data\GameData.bin
   ```

   Prüfe, ob die Datei dort existiert:
   `Get-ChildItem -Recurse "$env:LOCALAPPDATA\Nebula" -Filter GameData.bin`.
   Liegt sie woanders (andere Nebula-Version, eigener Datenordner), nimm den
   gefundenen Pfad. `524d4745` steht für die US-Disc; die europäische hätte
   `524d4750`. Der Mac-Spielstand stammt von der **US-Version**. Passt Nebulas
   Disc nicht dazu, abbrechen und dem Nutzer sagen.
3. **Gibt es noch keine Datei,** dann Nebula einmal starten, eine Spieldatei
   anlegen, im Spiel speichern und beenden. Nebula legt die Datei samt ihren
   Verwaltungsdaten an. Nebula hält zu jeder NAND-Datei Besitzer- und
   Rechte-Angaben in einem NTFS-Datenstrom neben der Datei. Die bleiben nur
   erhalten, wenn du den **Inhalt** der vorhandenen Datei ersetzt, statt sie
   durch eine neue zu tauschen (siehe unten).
4. **Die mitgeschickte Datei prüfen.** Sie muss 48.640 Bytes groß sein (die
   Größe ist bei diesem Spiel fest) und mit dem Wii-Format beginnen. Ist Python
   da, sagt das Tool es direkt:

   ```
   python convert_save.py inspect GameData.bin
   ```

   Erwartet: `Wii (big-endian: Wii, Dolphin, Nebula)`. Steht dort `native
   (little-endian ...)`, ist die Datei noch im Mac-Format: nicht einspielen,
   sondern auf dem Mac mit `export` umwandeln lassen. Ohne Python reicht ein
   Blick auf die ersten 16 Bytes: Bytes 4–7 sind `00 00 00 02` (Version 2 im
   Wii-Format), Bytes 8–11 `00 00 00 13` (19 Einträge). Im Mac-Format wären es
   `02 00 00 00` und `13 00 00 00`.

   ```powershell
   Format-Hex -Path GameData.bin -Count 16
   ```

## Mac → Windows (Spielstand in Nebula einspielen)

1. Vorher-prüfen-Punkte 1–4 abarbeiten.
2. Den vorhandenen Nebula-Spielstand sichern, mit Datum im Namen:

   ```powershell
   $save = "$env:LOCALAPPDATA\Nebula\saves\title\00010000\524d4745\data\GameData.bin"
   Copy-Item $save "$save.backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
   ```

3. Den **Inhalt** ersetzen, damit Nebulas Datenströme an der Datei bleiben
   (nicht `Copy-Item` über die Datei, das tauscht sie aus):

   ```powershell
   [IO.File]::WriteAllBytes($save, [IO.File]::ReadAllBytes("C:\Pfad\zur\GameData.bin"))
   ```

4. Nebula starten und die Dateiauswahl ansehen: Die Spieldateien sollten die
   Sterne vom Mac zeigen (der Nutzer weiß, wie viele es sind). Lädt Nebula den
   Spielstand nicht oder meldet ihn als beschädigt: Nebula beenden, die
   Sicherung aus Schritt 2 zurückkopieren (wieder mit `WriteAllBytes`) und dem
   Nutzer die Meldung zeigen.

`banner.bin` neben der Datei (das Symbol des Spielstands im Wii-Menü) nicht
anfassen; das Spiel schreibt es beim Speichern selbst.

## Windows → Mac (Spielstand von Nebula zurück)

1. Nebula beenden.
2. Nebulas `GameData.bin` (Pfad wie oben) unverändert kopieren, z. B. in einen
   geteilten Cloud-Ordner oder per Mail an den Nutzer. Nicht umwandeln: das
   macht der Mac.
3. Auf dem Mac, mit beendetem Spiel:

   ```sh
   python3 ~/Documents/Claude/MacioGalaxy/native/tools/convert_save.py import ~/Downloads/GameData.bin
   ```

   Das Tool sichert den bisherigen Mac-Spielstand in
   `~/Library/Application Support/Petari/save-backups`, wandelt um, prüft und
   spielt ein.

## Auf dem Mac exportieren (für den Weg Mac → Windows)

Am einfachsten: `guglis/Spielstand exportieren.command` im Finder doppelklicken
(am besten mit beendetem Spiel). Auf dem Schreibtisch liegt dann eine einzige
Datei, `Mario Galaxy Spielstand <Datum>.zip`, mit `GameData.bin` im Wii-Format,
`LIESMICH.txt` (wann gespeichert, welche Spieldateien), dieser Anleitung und
`convert_save.py`. Diese ZIP auf den Windows-Rechner bringen und entpacken.

Im Terminal geht dasselbe mit `convert_save.py bundle`; nur die Datei gibt
`convert_save.py export ~/Desktop/GameData.bin`.

## Was nicht mitkommt

- Mac-Statistiken aus `progress.json` (Bestzeiten, Seite „My Progress“) bleiben
  auf dem Mac; sie stehen nicht im Spielstand.
- Einstellungen der Ports selbst (Grafik, Steuerung, Mods) gehören zu jeder
  App und werden nicht übertragen.
- Immer nur auf einem Rechner weiterspielen und dann übertragen. Zwei
  Spielstände lassen sich nicht zusammenführen; der zuletzt eingespielte gilt.
