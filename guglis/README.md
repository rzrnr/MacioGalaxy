# Guglis Edits

Meine eigenen Änderungen an MacioGalaxy. Sie liegen als Branch `guglis-edits` über
dem offiziellen Repo (classicrob/MacioGalaxy, Remote `origin`), jede Änderung als
eigener Commit. `main` bleibt der unveränderte offizielle Stand. Gesichert ist der
Branch auf meinem Fork (rzrnr/MacioGalaxy, Remote `fork`).

## Was drin ist

| Änderung | Was sie macht | Fürs offizielle Repo |
| --- | --- | --- |
| Lautstärkeregler (2 Commits) | F1-Menü: Schieberegler in 5-%-Schritten über „Restart from Title“, gespeichert in `sound.txt` | vorgeschlagen: PR [#1](https://github.com/classicrob/MacioGalaxy/pull/1), Branch `volume-slider` |
| Vollbild | Cmd+Return schaltet echtes Vollbild, der Mac-Mauszeiger ist dort ausgeblendet, gespeichert in `display.txt` | vorgeschlagen: PR [#2](https://github.com/classicrob/MacioGalaxy/pull/2), Branch `fullscreen-cursor` |
| Grastextur Honeyhive | Negativer Textur-LOD-Bias wird auf arm64 richtig übersetzt, der Rasen ist wieder texturiert | vorgeschlagen: PR [#3](https://github.com/classicrob/MacioGalaxy/pull/3), Branch `fix-negative-lod-bias` |
| CoreAudio-Linkfix | Ohne ihn bricht der Build auf diesem Mac beim Linken ab | privat |
| FineFur | Mod (F1 → Mods → „Fine fur“): Fell mit halb so breiten Haaren, schaltet sofort um. Details in `native/MODS.md` | privat |
| Zuschau-Fenster | `PETARI_SMOKE_WATCH=1` zeigt Testläufe in einem Fenster ohne Fokus und ohne Eingabe | privat |
| App-Icon | Die gebaute App bekommt ein eigenes Icon: ein goldener Stern vor der Feuerradgalaxie M101 (Bildnachweis unten). Quelle ist das Icon-Composer-Paket `guglis/icon/SuperMarioGalaxy.icon`, das beim Bauen kompiliert wird | privat |

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
die Tabelle eintragen, zunächst als privat. Je kleiner ein Edit die offiziellen
Dateien berührt, desto seltener kollidiert er bei Updates. Commits für einen
möglichen Vorschlag schreibt man wie fürs offizielle Repo: auf Englisch, ohne
Änderungen an `guglis/`.

## Einen Edit doch vorschlagen

Ob ein Edit privat bleibt oder vorgeschlagen wird, entscheide ich pro Edit. Zum
Vorschlagen:

```sh
guglis/propose.sh <branch-name> <commit> [<commit>...]
```

Das legt den Branch `<branch-name>` vom offiziellen Stand an, mit nur diesen
Commits darauf, und zeigt die Befehle zum Hochladen auf den Fork (rzrnr) und für
den PR. Hochgeladen wird erst, wenn ich die Befehle selbst ausführe. Danach in der
Tabelle von „privat“ auf „vorgeschlagen“ umstellen.

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
