# tests/

Every gate. The directory a script is in is its kind; the runner derives the
gate list from this tree.

```powershell
py tests\run_gates.py fast
py tests\run_gates.py --tag dbw
py tests\run_gates.py tier1
py tests\run_gates.py full
py tests\run_gates.py --list -k <text>
```

| directory | kind |
|---|---|
| `host/` | portable C cores on a PC compiler, with negative controls |
| `firmware/<subsystem>/` | the linked image in the C167 simulator, or its map and bytes |
| `tunerstudio/` | the generated `.ini` against TunerStudio's rules and the firmware |
| `unit/` | tools and test suites |
| `simulator/` | the simulator's own models |
| `physical/` | hardware-in-the-loop checks on a real ECU; never run by a tier |
| `fixtures/` | recorded data the tests read |

`catalog.py` adds the fast and Tier 1 sets, tags, time budgets and
level-condition skips. Results and known red gates:
the maintainer's design notes.
