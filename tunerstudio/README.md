# tunerstudio/

Generated TunerStudio files for the image built from the same tree, and the
published connection plugin.

```powershell
py tools\tunerstudio\gen_ts_ini_me711.py
```

| file | |
|---|---|
| `hanicore_me711.ini` | the `.ini` for the current image |
| `hanicore_me711_<stem>.ini` | the same, under the image's name |
| `hanicore_me711_<stem>_forensic.ini` | developer project: adds the developer pages and the extended diagnostic channels |
| `hanicore_me711_<stem>_userdefined_fallback.ini` | fallback for older TunerStudio dialog syntax |
| `HaniCore.dash` | default gauge cluster |
| `plugin/HaniCore_KLine_Transport_<version>.jar` | K-line connection plugin, with its build record (`.json`) |

The `.ini` and dashboard are generated locally and not committed. Guide:
the maintainer's design notes.
