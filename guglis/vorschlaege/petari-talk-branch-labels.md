Title: `TalkMessageCtrl::rootNodePre`: branch condition labels as in the retail jump table

`rootNodePre` gets the code right, but three case labels are swapped. The source has:

| Label | Value (US) | Condition in the source |
| --- | --- | --- |
| `TalkMessageCtrl_TypeB` | 11 | `isTimeKeepDemoActive` |
| `TalkMessageCtrl_TypeC` | 12 | `isOnMessageAlreadyRead` |
| `TalkMessageCtrl_TypeE` | 13 | `getBranchAstroGalaxyResult` |

The retail jump table in the US `main.dol` (`rootNodePre` at `0x802A03AC`, table at `0x805A2434`) maps the cases differently:

| Case | Retail target calls |
| --- | --- |
| 11 | `getBranchAstroGalaxyResult__12TalkFunctionFUs` (`0x8029FAE0`) |
| 12 | `isTimeKeepDemoActive__2MRFv` (`0x803C9F80`) |
| 13 | `isOnMessageAlreadyRead__2MRFSc` (`0x803CDBB8`) |

The message data agrees. In the US `.msbt` flows, every type-11 branch passes an observatory flag index (0 to 27), and type 13 passes a message ID.

The patch only changes the three labels. The order of the case blocks, and so the code, stays the same.

Result on RMGE01 (`python configure.py --version RMGE01 && ninja`, `build/RMGE01/report.json`, unit `main/Game/NPC/TalkMessageCtrl`):

| Section | Before | After |
| --- | --- | --- |
| `.text` | 100% | 100% |
| `.data` (the jump table) | 7.69% | 99.60% |

**RMGK01 is unverified.** The enum gives Korea `TypeD` (13) and `TypeE` (14). By the same pattern I would expect 13 = `isMsgLedPattern` and 14 = `isOnMessageAlreadyRead`, which is what the patch does, but I did not have a Korean DOL to check.

Patch: `petari-talk-branch-labels.patch`, against SMGCommunity/Petari `master` at 29986ad.
