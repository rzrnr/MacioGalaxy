# Vorbereitete Vorschläge (nicht eingereicht)

Hier liegen Änderungen aus den Guglis Edits, die für die offiziellen Projekte nützlich wären,
fertig vorbereitet, aber **nicht eingereicht**. Ob und wann sie als Pull Request ans offizielle
Repo gehen, entscheidet Gugli selbst.

Jeder Vorschlag für MacioGalaxy ist ein eigener Branch auf dem Fork (rzrnr/MacioGalaxy), direkt
auf dem offiziellen `main`, ohne die anderen Guglis Edits. Gebaut und getestet wurde jeder Branch
einzeln:
- alle 84 offiziellen Testprogramme (ctest, ohne Timing-Tests und `native_rfl_render`);
- mindestens ein Stage-Lauf (headless).

Für den Build auf diesem Mac war lokal der CoreAudio-Linkfix nötig; der ist nicht Teil der Branches.

| Datei | Vorschlag | Branch | Art |
| --- | --- | --- | --- |
| `01-fix-observatory-talk.md` | Gespräche im Observatorium | `fix-observatory-talk` | erledigt: das offizielle Repo hat seit 23.10. eine eigene Korrektur |
| `02-fix-framework-allocations.md` | Speicher macOS-fremder Bibliotheken (Absturz mit AirPods) | `fix-framework-allocations` | Bugfix |
| `03-vsync-display-sync.md` | V-Sync: Spieltakt folgt dem Monitor | `vsync-display-sync` | erledigt: das offizielle Repo macht das seit 23.10. selbst |
| `04-input-latency.md` | Frische Eingaben, umsortierte Spielschleife | `input-latency` | Verbesserung |
| `petari-talk-branch-labels.md` + `.patch` | Derselbe Gesprächs-Fehler in der Decompilation Petari (SMGCommunity/Petari) | nur Patch | Bugfix |

Einreichen, wenn gewünscht (Beispiel für den ersten):

```sh
gh pr create --repo classicrob/MacioGalaxy --head rzrnr:fix-observatory-talk --base main \
  --title "Talk: Comet Observatory branch conditions as in the retail game" \
  --body-file guglis/vorschlaege/01-fix-observatory-talk.md
```

Vor dem Einreichen den Branch auf den dann aktuellen offiziellen Stand bringen
(`git rebase origin/main`), neu bauen und testen.

Die Branches `fix-framework-allocations` und `input-latency` stehen noch auf dem alten offiziellen
Stand (vor dem 23.10.2026) und müssen vor dem Einreichen neu aufgesetzt werden.
