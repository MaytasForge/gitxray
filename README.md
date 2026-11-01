# 🩻 gitxray



!\[demo](screenshot.png)

**X-ray for any git repository.** One file, zero dependencies, one command.

```bash
python gitxray.py /path/to/repo
```

## What it finds

|||
|-|-|
|🔥 **Hotspots**|Files that change often *and* are big, where bugs breed|
|🚌 **Bus factor = 1**|Files only one person has ever touched|
|👻 **Orphans**|Files nobody references anywhere (deletion candidates)|
|⏳ **Ancient TODOs**|`TODO/FIXME/HACK` sorted by age, with the author (via `git blame`)|
|📊 **Health score**|A playful 0–100 number you can brag about (or hide)|

It also writes a self-contained, dark/light-mode `gitxray-report.html`.

## Options

```
--out FILE    HTML report path (default: gitxray-report.html)
--top N       rows in the hotspot table (default: 15)
--no-blame    skip TODO age lookup (faster on huge repos)
```

## Requirements

Python 3.8+ and `git` in PATH. That's it.

## Notes

Orphan detection is a heuristic (it looks for the file name mentioned in any other
tracked text file). Always double-check before deleting anything.

## License

MIT

