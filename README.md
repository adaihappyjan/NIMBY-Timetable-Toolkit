# NIMBY Timetable Toolkit

[English](README.md) · [简体中文](README.zh-CN.md)

A local operations and construction companion for **NIMBY Rails**. Inspect saves,
plan and edit timetables, generate track blueprints, draw railway maps, manage
depot joins, build vehicle mods and clean up generated copies.

**Save edits create a new file. The original save is never overwritten.**
Always inspect the output in the game before adopting it as your main save.

## Download and start

1. Download the Windows x64 portable ZIP from [Releases](https://github.com/adaihappyjan/NIMBY-Timetable-Toolkit/releases/latest).
2. Extract the **entire** archive. Do not run the EXE inside the ZIP or copy it out alone.
3. Run **NIMBYToolkit.exe**. Python, Node.js and desktop components are bundled; no separate installation or terminal window is needed.
4. Choose your save in **Overview & health** and run a health check.
5. Use the top language selector to switch between **English** and **简体中文**.

Read [START HERE.txt](START%20HERE.txt) for first-use instructions and troubleshooting.
Existing portable installations can use **Check for updates → Download update and restart**.
Installation requires confirmation; stable updates never install beta releases.

## What's new in 1.9.0

- English is the default language, with a saved Simplified Chinese option.
- Offline language resources cover navigation, tutorials, controls, map labels and diagnostic messages.
- Player-defined station, line and train names, file paths and save identifiers are preserved.
- English-first project overview, quick-start instructions, user guide and release notes.
- Existing timetable, routing, blueprint, map, cache and cleanup functionality is retained.
- **3D remains excluded. 2.0.0 beta is coming soon**, developed separately; capabilities and compatibility will be documented in its own release notes.

Changing language reloads the interface after confirmation. Finish active tasks and
save/export drafts first. It does not translate or rewrite your game data.

## Features

| Area | What you can do |
| --- | --- |
| Overview and health | Inspect saves, find supported issues, verify game exports and preview repairs. |
| Line workspace | Configure operating timetables, preview per-line differences and track in-game verification. |
| Timetables | Edit orders, days, entry/exit stops, timing points, repeats and ten offset groups; save reusable plans. |
| Depot joins | Bind Timetable garage join to existing trains. It does not build depots or bypass signals. |
| Automatic track laying | Follow local railway map data between endpoints and selected or discovered built/blueprint stations. |
| Blueprint avoidance | Raise or lower new blueprint sections around water, roads and player facilities; verify in game. |
| Route maps | Geographic, octolinear, metro, grid and strip layouts; branch grouping, interchange styles, SVG/JSON export. |
| Real-world reference | OpenRailwayMap layers, OpenStreetMap station/route lookup and planning pins. |
| Tile cache | Cache viewed ORM tiles locally, with optional silent launch alongside the game. No regional bulk downloads. |
| Vehicles and scripts | Generate private mods; inspect installed definitions and validate supported script structures. |
| Files and cleanup | Follow stable project files; protect important copies and preview recoverable cleanup. |
| Analysis and history | Compare exports, estimate headways and fleets, inspect weekly connections and accounting statistics. |

Read the [User guide](docs/USER_GUIDE.md). The in-app **Tutorials** page provides nine resumable lessons.

## Save and export workflow

Basic health checks and direct-save tools do **not** require JSON. For tools that do:

1. Pause NIMBY Rails and save.
2. Keep it paused and use the game's timetable export function.
3. Wait for the file whose name includes **Timetable Export**.
4. Select that JSON and its matching save, then verify the pair in the toolkit.

The toolkit cannot trigger that export for you. Its route-map JSON, reports,
GeoJSON and timetable plans are **not** substitutes. Save and export again after changes.

## Safety and limits

- Unknown save structures, changed inputs and ambiguous identities block writes.
- File verification is not proof that dispatching, signals or depot access work in game.
- Automatic track laying leaves station-connection gaps and does not configure signals or points.
- Partial generation requires confirmation; failed sections remain disconnected.
- Fleet estimates omit unknown waits, conflicts, depot moves and spare trains.
- Automatic cleanup is off by default. JSON exports require manual selection.
- Writes are serialized. Extra CPU workers accelerate suitable reads, not simultaneous writes.
- Language resources are offline. Save files are not sent to a translation service.

## Save directory and requirements

Common Windows, macOS, Linux and Steam Proton locations are detected automatically.
On Windows, the usual path is `Saved Games/Weird and Wry/NIMBY Rails`.
Use **Save directory** in the overview to choose another location.
`NIMBY_SAVE_DIR` overrides discovery and the interface setting.
Preferences are stored in the user configuration directory, separately from releases.

The portable EXE release targets **Windows 10/11 x64**. Source execution on other
systems depends on local desktop/compression libraries and is not equivalent to
the verified Windows bundle.

## Source installation and development

Python 3.10+ is required. Automatic routing also needs Node.js 22+.

```powershell
python -m pip install -r requirements.txt
python toolkit_webapp.py
python -m pytest -q tests
```

The app normally uses a desktop window. Without the desktop component, it falls
back to a local server and browser. No administrator rights are required.

See [Localization](docs/LOCALIZATION.md) for language resources. Use English for
new public documentation, release notes and contributor-facing text; include
Simplified Chinese translations for user-facing changes.

- [Automatic updates](docs/AUTO_UPDATE.md)
- [MCP interface](docs/MCP_SERVER.md)
- [Documentation index](docs/INDEX.md)

## Credits and license

Copyright © 2026 **adaihappyjan**. Released under the [MIT License](LICENSE).
Retain copyright and license notices when redistributing.

Map data and components retain their own licenses and attribution requirements.
See [NOTICE](NOTICE) and bundled third-party notices. Sources include OpenStreetMap,
OpenRailwayMap and CARTO; map display uses Leaflet.

This unofficial community project is not affiliated with or endorsed by NIMBY Rails
or Weird and Wry. Software is provided as-is, without warranty.
