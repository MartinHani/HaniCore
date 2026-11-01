# tuning/

The generated tuning-project files for the image built from the same tree:
the `.ini` that describes the ECU's calibration page, live data and commands
(the INI format TunerStudio introduced and LibreTune reads), and a default
gauge layout. Tune HaniCore with [LibreTune](../README.md#first-setup).

```powershell
py tools\tuning\gen_ts_ini_me711.py
```

| file | |
|---|---|
| `hanicore_me711.ini` | the `.ini` for the current image |
| `hanicore_me711_<stem>.ini` | the same, under the image's name |
| `hanicore_me711_<stem>_forensic.ini` | developer project: adds the developer pages and the extended diagnostic channels |
| `hanicore_me711_<stem>_userdefined_fallback.ini` | fallback with the older dialog syntax |
| `HaniCore.dash` | default gauge cluster |

These files are generated locally and not committed; the release assets carry
them for each board.
