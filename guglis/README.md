# Guglis Edits

Meine eigenen Änderungen an MacioGalaxy. Sie liegen als Branch `guglis-edits` über
dem offiziellen Repo (classicrob/MacioGalaxy, Remote `origin`), jede Änderung als
eigener Commit. `main` bleibt der unveränderte offizielle Stand. Gesichert ist der
Branch auf meinem Fork (rzrnr/MacioGalaxy, Remote `fork`).

## Was drin ist

Drei Arten von Änderungen, getrennt gehalten:

- **Bugfixes** machen das Spiel so, wie es auf der Wii war, oder beheben Fehler des Ports. Sie gehören
  alle ins offizielle Repo.
- **Allgemeine Verbesserungen** ändern nichts am Spielinhalt, nur Bedienung, Darstellung und Technik.
  Was davon allgemein nützlich ist, geht als Vorschlag ans offizielle Repo.
- **Inhalts-Mods** verändern oder erweitern das Spiel selbst. Sie sind standardmäßig aus und bleiben
  hier.

### Bugfixes

| Änderung | Was sie macht | Fürs offizielle Repo |
| --- | --- | --- |
| Grastextur Honeyhive | Negativer Textur-LOD-Bias wird auf arm64 richtig übersetzt, der Rasen ist wieder texturiert | vorgeschlagen: PR [#3](https://github.com/classicrob/MacioGalaxy/pull/3), Branch `fix-negative-lod-bias` |
| Gespräche im Observatorium | Die Bedingungen in den Gesprächen standen in falscher Reihenfolge, deshalb lasen die Figuren im Kometen-Observatorium ihren Spielfortschritt nie: Der Brief-Toad behielt seinen Brief, Toads, Rosalina und Lumas sagten nur ihre ersten Sätze. Jetzt wie im Original (geprüft an `main.dol`) | vorbereitet, nicht eingereicht: Branch `fix-observatory-talk`; für Petari nur als Patch, siehe [vorschlaege/](vorschlaege/README.md) |
| Speicher macOS-fremder Bibliotheken | Speicher, den macOS-Bibliotheken (CoreAudio, Core Animation) auf dem Spiel-Thread anlegen, landet nicht mehr im Wii-Speicher. Vorher stürzte das Spiel ab, sobald macOS ihn auf einem eigenen Thread freigab, zum Beispiel mit AirPods beim ersten Ton | vorbereitet, nicht eingereicht: Branch `fix-framework-allocations` |
| CoreAudio-Linkfix | Ohne ihn bricht der Build auf diesem Mac beim Linken ab | noch nicht vorgeschlagen |

### Allgemeine Verbesserungen

| Änderung | Was sie macht | Fürs offizielle Repo |
| --- | --- | --- |
| Lautstärkeregler (2 Commits) | F1-Menü: Schieberegler in 5-%-Schritten über „Restart from Title“, gespeichert in `sound.txt` | vorgeschlagen: PR [#1](https://github.com/classicrob/MacioGalaxy/pull/1), Branch `volume-slider` |
| Vollbild | Cmd+Return schaltet echtes Vollbild, der Mac-Mauszeiger ist dort ausgeblendet, gespeichert in `display.txt` | vorgeschlagen: PR [#2](https://github.com/classicrob/MacioGalaxy/pull/2), Branch `fullscreen-cursor` |
| Instant pointer | Schalter unter F1 → Mods → „Instant pointer“: Der Star Pointer wird in jedem Bild an der aktuellen Mausposition gezeichnet, ohne die Wiimote-Glättung. Details in `native/MODS.md` | noch nicht vorgeschlagen |
| Grafik-Seite | F1 → Graphics: Renderauflösung Display, 480p (Wii), 720p, 1080p, 1440p oder 4K; Upscaling mit FSR 1, Bicubic oder Bilinear; RCAS-Schärfe; FXAA; Statistik-Overlay mit FPS, Frame-Zeit-Graph und FPS im Fenstertitel. Details in `native/GRAPHICS.md` | noch nicht vorgeschlagen |
| 120 FPS mit Zwischenbildern | F1 → Graphics → Frame rate 120 (Prototyp): ein zusätzliches Bild zwischen zwei Spielschritten, Kamera und Modelle auf halbem Weg. Details in `native/FRAME_RATE.md` | noch nicht vorgeschlagen |
| V-Sync | F1 → Graphics → V-Sync (Off, On, Low latency, Variable für ProMotion im Vollbild): Der Spieltakt folgt dem Monitor, jedes Bild steht gleich lang, gegen Mikroruckler | vorbereitet, nicht eingereicht: Branch `vsync-display-sync` (Off, On und Low latency) |
| Input latency | F1 → Graphics → Input latency Reduced: Jeder Spielschritt wird im selben Bild gezeichnet statt im nächsten, dazu frischere Eingaben; eine Taste ist rund 17 ms früher im Bild | vorbereitet, nicht eingereicht: Branch `input-latency` |

### Inhalts-Mods

| Änderung | Was sie macht | Fürs offizielle Repo |
| --- | --- | --- |
| FineFur | Mod (F1 → Mods → „Fine fur“): Fell mit halb so breiten Haaren, schaltet sofort um. Details in `native/MODS.md` | noch nicht vorgeschlagen |
| Eigene Galaxien | Mods können ganze Galaxien hinzufügen: Miniatur in einer Kuppel, Namen und Dialoge aus einer `messages.txt`, neue Objekte mit eigener Logik. Ihr Fortschritt liegt getrennt in `ModProgress/`, `GameData.bin` bleibt unberührt. Beispiel „Guglis Testgalaxie“: `python3 native/tools/make_example_galaxy.py`, dann F1 → Mods → Mod folder. Eigener Planet aus Blender mit Anflug-Kamerafahrt, kleiner Aufgabe und eigenem Stern (eigener Zähler, getrennt von den Hauptsternen): `python3 native/mods/GuglisPlanet/build.py`. Details in `native/CUSTOM_GALAXY.md` | noch nicht vorgeschlagen |
| Themenfarbe Haselnuss | Alles Eigene der Mods ist haselnussbraun (#8A5A32): die Sterne der Mod-Galaxien samt Rückflug, ihr Zähler unter der Sternanzeige und ein eigener Startstern-Typ `SuperSpinDriverHazel` mit brauner Flugbahn. Die Originalfarben des Spiels bleiben. Dateien aus `native/mods/theme.py` | noch nicht vorgeschlagen |
| Cheat-Seite | F1 → Mods → Cheats: die 1-Ups einstellen (1 bis 99, Links/Rechts). „Keep 1-Ups when loading“ (an) behält die Anzahl im Spielstand: nach Speichern und Neuladen ist sie wieder da statt der üblichen 4. Gespeichert in `cheats.txt`; Details in `native/MODS.md` | nur im Fork |
| Himmelsinsel am Sternenschiff | Mod „Sternenschiff“: eine schwebende Insel östlich des Lumagartens (Modell aus Blender, `native/mods/Sternenschiff`) mit Toad, Sternenteilen und Schmetterlingen; haselnussbraune Startsterne hin und zurück. Das Sternenschiff selbst ist in Whitehole über MCP bearbeitet | noch nicht vorgeschlagen |

### Werkzeuge und Kleinigkeiten

Nur für diesen Fork, nicht fürs offizielle Repo gedacht:

| Änderung | Was sie macht | Fürs offizielle Repo |
| --- | --- | --- |
| Zuschau-Fenster | `PETARI_SMOKE_WATCH=1` zeigt Testläufe in einem Fenster ohne Fokus und ohne Eingabe | noch nicht vorgeschlagen |
| App-Icon | Die gebaute App bekommt ein eigenes Icon: ein goldener Stern vor der Feuerradgalaxie M101 (Bildnachweis unten). Quelle ist das Icon-Composer-Paket `guglis/icon/SuperMarioGalaxy.icon`, das beim Bauen kompiliert wird | noch nicht vorgeschlagen |
| Galaxie-Editor in Blender | Blender-Add-on (`native/blender`): eine Galaxie öffnen (Disc und Mods, Suche nach dem Namen im Spiel), mit den Modellen und Texturen des Spiels; Objekte, Map-Teile, Gravity, Areas und Paths mit Blenders Werkzeugen bearbeiten, die geänderten Zonen als Mod speichern und unsichtbar oder im Spiel anspielen. In Blender verlinkt nach `~/Library/Application Support/Blender/5.2/scripts/addons` | noch nicht vorgeschlagen |

`git log --oneline origin/main..guglis-edits` zeigt die Commits.

Außerhalb des Repos, das überlebt Updates von selbst:

- Getauschte Maustasten: `controls.txt` in `~/Library/Application Support/Petari`.
- Name und Spielpfad der App: die Info.plist von `/Applications/Super Mario Galaxy.app`.
  `update.sh` ersetzt dort nur Programm, Icon und Shader-Seeds.
- Das frühere Icon aus dem offiziellen Cover liegt nur lokal in
  `~/Documents/Claude/AppIcons`. Es gehört nicht ins Repo.

## Neue offizielle Version übernehmen

```sh
guglis/update.sh
```

Das Skript

1. holt das offizielle Repo und sichert den bisherigen Stand als Branch
   `guglis-edits-vor-<Datum>`,
2. setzt die Guglis Edits auf den neuen offiziellen Stand (`git rebase origin/main`),
3. baut das Spiel und die Tests und lässt die Tests laufen,
4. ersetzt Programm, Icon und Shader-Seeds in `/Applications/Super Mario Galaxy.app`
   und signiert die App neu.

`--no-tests` überspringt Schritt 3 bis auf den Spiel-Build, `--no-install` Schritt 4.
Das Spiel muss für Schritt 4 beendet sein.

Nach einem Rebase ist die Sicherung auf dem Fork älter als der lokale Branch. Das
Skript sagt das am Ende; erneuert wird sie mit
`git push --force-with-lease fork guglis-edits`.

Wenn ein Edit mit der neuen Version kollidiert, hält das Skript beim Rebase an.
Dann entweder den Konflikt lösen (oder Claude fragen), `git rebase --continue`
und `guglis/update.sh` erneut starten, oder mit `git rebase --abort` zum alten
Stand zurück.

Übernimmt das offizielle Repo einen der PRs unverändert, wird der Commit beim
Rebase leer und fällt von selbst weg. Wurde er geändert übernommen, gibt es
meist einen Konflikt. Dann gilt die offizielle Fassung: `git rebase --skip`
lässt den eigenen Commit weg. Danach die Tabelle oben anpassen.

Zurück zu einem gesicherten Stand: `git switch -C guglis-edits guglis-edits-vor-<Datum>`.

## Eine neue eigene Änderung

Auf `guglis-edits` arbeiten, die Änderung als eigenen Commit festhalten und hier in
die Tabelle eintragen, zunächst als noch nicht vorgeschlagen. Die kurze englische Tabelle in
`.github/README.md` (die Seite, die GitHub für den Fork zeigt) bekommt dieselbe Zeile. Je kleiner ein Edit die offiziellen
Dateien berührt, desto seltener kollidiert er bei Updates. Commits für einen
möglichen Vorschlag schreibt man wie fürs offizielle Repo: auf Englisch, ohne
Änderungen an `guglis/` und `.github/README.md`.

## Einen Edit doch vorschlagen

Die Edits sind einzelne Anpassungen. Ist eine fertig und für alle sinnvoll, geht sie
als Vorschlag ans offizielle Repo; wann, entscheide ich pro Edit. Zum Vorschlagen:

```sh
guglis/propose.sh <branch-name> <commit> [<commit>...]
```

Das legt den Branch `<branch-name>` vom offiziellen Stand an, mit nur diesen
Commits darauf, und zeigt die Befehle zum Hochladen auf den Fork (rzrnr) und für
den PR. Hochgeladen wird erst, wenn ich die Befehle selbst ausführe. Danach in der
Tabelle auf „vorgeschlagen“ umstellen.

Der Edit bleibt dabei auch in `guglis-edits`. Ändert sich ein Vorschlag nach
Rückmeldungen, kommt die Korrektur in beide Branches: als Commit auf den
PR-Branch und mit `git cherry-pick` auf `guglis-edits`.

## Bildnachweis

Hintergrund des App-Icons: [Pinwheel Galaxy (M101)](https://commons.wikimedia.org/wiki/File:M101_hires_STScI-PRC2006-10a.jpg),
Credit: [ESA/Hubble](https://esahubble.org/), Lizenz [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Geändert: Ausschnitt um den Kern, blau getönt und zum Rand abgedunkelt.
Der Stern ist selbst gezeichnet. Beides erzeugt `guglis/icon/make_layers.swift`
aus der 3840-px-Fassung des Bildes:

```sh
swift guglis/icon/make_layers.swift <M101 3840px.jpg> guglis/icon/SuperMarioGalaxy.icon/Assets
```
