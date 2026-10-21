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
direkt. Auf Windows wird also nur kopiert, nicht umgewandelt. Der ganze Weg in
beide Richtungen wurde am 22.10.2026 mit Nebula 1.0.1 durchgespielt: Nebula hat
den Mac-Spielstand geladen, weitergespeichert, und der Mac hat ihn wieder
gelesen.

`convert_save.py` läuft auch unter Windows (Python 3): `inspect`, `to-wii`,
`to-native` und `bundle --from` gehen dort; `import`, `export` und `bundle`
ohne `--from` arbeiten mit dem Mac-Spielstand und gehören auf den Mac.

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
3. **Gibt es noch keine Datei,** reicht es, sie hineinzukopieren (Ordner
   anlegen, falls nötig). Nebula nimmt eine von Hand abgelegte `GameData.bin`
   an: Beim ersten Start hängt es selbst seinen NTFS-Datenstrom
   `galaxy.isfs.meta` (Besitzer und Rechte der Datei) an und schreibt
   `banner.bin`. Abgelehnte Spielstände legt Nebula in einen Ordner
   `saves-rejected-*`; taucht so einer auf, hat es nicht geklappt.
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

3. Einspielen, auf einem dieser Wege:
   - **Über Nebulas Launcher:** Advanced → Import saves → From a folder…, den
     entpackten Ordner wählen. Nebula kennt dort auch Dolphin-Spielstände und
     sichert den alten Stand selbst.
   - **Von Hand:** Gibt es schon eine Datei, ihren **Inhalt** ersetzen, damit
     Nebulas Datenstrom daran bleibt:

     ```powershell
     [IO.File]::WriteAllBytes($save, [IO.File]::ReadAllBytes("C:\Pfad\zur\GameData.bin"))
     ```

     Gibt es noch keine, einfach hineinkopieren (siehe „Vorher prüfen“, Punkt 3).

4. Nebula starten und die Dateiauswahl ansehen: Die Spieldateien sollten die
   Sterne vom Mac zeigen (der Nutzer weiß, wie viele es sind). Lädt Nebula den
   Spielstand nicht oder meldet ihn als beschädigt: Nebula beenden, die
   Sicherung aus Schritt 2 zurückkopieren (wieder mit `WriteAllBytes`) und dem
   Nutzer die Meldung zeigen.

`banner.bin` neben der Datei (das Symbol des Spielstands im Wii-Menü) nicht
anfassen; das Spiel schreibt es beim Speichern selbst.

## Windows → Mac (Spielstand von Nebula zurück)

1. Nebula beenden.
2. Nebulas Spielstand in eine einzige Datei packen, unverändert (nicht
   umwandeln: das macht der Mac). Mit dem mitgeschickten Tool:

   ```powershell
   python convert_save.py bundle --from "$env:LOCALAPPDATA\Nebula\saves\title\00010000\524d4745\data\GameData.bin" "$env:USERPROFILE\Desktop\Mario Galaxy Spielstand Windows $(Get-Date -Format 'yyyy-MM-dd HH-mm').zip"
   ```

   Das prüft das Format und die Prüfsumme und legt `GameData.bin`,
   `LIESMICH.txt`, diese Anleitung und das Tool in die ZIP. Ohne Python geht
   auch: nur `GameData.bin` kopieren. Der NTFS-Datenstrom geht dabei verloren,
   das ist egal; der Mac braucht ihn nicht. Was sich geändert hat (welche
   Spieldateien gespielt wurden), gern in eine Notiz dazulegen.
3. Die ZIP zum Mac bringen (Cloud-Ordner, Mail, Downloads). Dort, mit beendetem
   Spiel:

   ```sh
   python3 ~/Documents/Claude/MacioGalaxy/native/tools/convert_save.py import ~/Downloads/<die ZIP>.zip
   ```

   `import` nimmt die ZIP direkt (oder eine einzelne `GameData.bin`), sichert
   den bisherigen Mac-Spielstand in
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

## Nebula installieren: bekannte Stolperstelle

Windows Defender meldet den Launcher `Nebula.exe` (1.0.1) als
`Trojan:Win32/Yomal!rfn` und verschiebt ihn in die Quarantäne; das Setup bricht
dann ganz am Ende ab. `!rfn` heißt meist, dass Defender nach Reputation oder
Verhaltensmustern urteilt; andere Nutzer melden dasselbe (keepvaibin/nebula,
Issues 18 und 26). Ein Fehlalarm ist wahrscheinlich, aber nicht bestätigt: die
EXE ist nicht signiert und wird nicht nachvollziehbar aus dem Quellcode gebaut.
Ob man sie aus der Quarantäne holt, entscheidet der Nutzer, nicht Claude.

## Was nicht mitkommt

- Mac-Statistiken aus `progress.json` (Bestzeiten, Seite „My Progress“) bleiben
  auf dem Mac; sie stehen nicht im Spielstand.
- Einstellungen der Ports selbst (Grafik, Steuerung, Mods) gehören zu jeder
  App und werden nicht übertragen.
- Immer nur auf einem Rechner weiterspielen und dann übertragen. Zwei
  Spielstände lassen sich nicht zusammenführen; der zuletzt eingespielte gilt.
