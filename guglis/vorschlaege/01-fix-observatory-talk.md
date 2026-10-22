The Comet Observatory's NPCs never read the game's progress flags: the Mail Toad shows his envelope but only ever says his default line, and the letter stays; Toads, Rosalina and the Lumas fall back to their earliest lines.

## Cause

`TalkMessageCtrl::rootNodePre` numbers its branch condition cases 11 to 14 in code order. The retail game's jump table says otherwise. Checked in the US `main.dol` (`rootNodePre` at `0x802A03AC`, `cmplwi 13`, table at `0x805A2434`):

| Case | Retail target calls |
| --- | --- |
| 11 | `TalkFunction::getBranchAstroGalaxyResult` (`0x8029FAE0`) |
| 12 | `MR::isTimeKeepDemoActive` (`0x803C9F80`) |
| 13 | `MR::isOnMessageAlreadyRead` (`0x803CDBB8`) |

The message data agrees. Every type-11 branch passes an observatory flag index (0 to 27), and type 13 passes a message ID. No type 12 or 14 appears in the US data. With 11 asking for the time keep demo, every observatory flag read false.

`TalkDirector::getBranchResult` also read the flags at offset `0x70`. That is their offset in the Wii's 32-bit layout only; on the 64-bit host it lands inside pointer fields. The native build now indexes from the first flag.

## Change

- `TalkMessageCtrl.cpp`: case 11 is `getBranchAstroGalaxyResult`, 12 `isTimeKeepDemoActive`, 13 `isOnMessageAlreadyRead`, 14 `isMsgLedPattern` (Korean only; not in the US data).
- `TalkDirector.cpp`, under `PETARI_NATIVE`: the flags from `mIsKinopioExplorerRescued` on, index-checked.

## Testing

- All 84 ctest programs pass (without the timing label and `native_rfl_render`).
- The AstroGalaxy stage smoke passes.
- Not yet checked: a save with a pending letter, played to the Mail Toad.

The same label mix-up is in Petari. A patch that keeps the code byte-identical and makes the jump table match the retail data is prepared separately.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
