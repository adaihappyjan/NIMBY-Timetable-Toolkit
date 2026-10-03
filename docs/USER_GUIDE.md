# User guide

[English overview](../README.md) · [中文说明](../README.zh-CN.md)

## Start safely

Extract the complete portable release and open `NIMBYToolkit.exe`. Choose a save
in **Overview & health**. A health check reads the file without changing it.
Select **English** or **简体中文** in the header; the choice persists across launches.
Language changes reload the interface after confirmation. Finish tasks and save
or export drafts first. Game data and player-defined names are never translated.

## Work with timetables

Use the direct-save overview and line workspace without JSON. For fleet migration,
historical recovery, export-based analysis or extension binding, pause and save in
game, export timetable data while paused, then verify the matching save/JSON pair.
Do not substitute a toolkit map, report, plan or GeoJSON file.

The full editor supports operating days, lines, entry/exit stops, timing points,
repetitions, stacked orders and offset groups. Leave new IDs blank. Existing orders
cannot be deleted in safe mode. Preview differences before writing a new save.
Drafts and undo are local; they are not game writes.

An operating day starts an order; it does not terminate an infinite loop. Explicitly
plan the final return or ending connection when stopping service on weekends.

## Depots

`Timetable garage join` relaxes shift-position matching for existing trains. It does
not build a depot, create return orders or bypass occupancy/signals. Generate the
rule pack, install/enable it in game and save before batch binding to a verified
save/export pair. The read-only diagnostic mod is separate.

Check first departure, normal service, peak transitions, final depot return and
the following day. A successful write or planned depot stay does not prove that
trains can physically enter and leave the depot.

## Automatic track laying

Choose endpoints and intermediate stops. Automatic discovery uses only built or
blueprint stations in the selected save, following railway paths rather than a
straight-line corridor. Check the order, particularly on parallel lines.

Local game map data is discovered from Steam. Custom GeoJSON can be placed in the
save folder, its `routes` subfolder or the toolkit's `routes` folder. The portable
release includes Node.js; source installations require Node.js 22+.

Set ground, bridge and tunnel track types separately. Avoidance can raise or lower
new blueprint sections around water, roads and player facilities. Station-center
protection circles approximate the area, not its building outline. Layers are not
terrain elevations. Check gradients and clearances in game.

Preview every section. Partial generation requires explicit confirmation and leaves
failed sections empty. Removing a stop is different: it changes adjacency and needs
a new preview. The output is a new test save. Connect endpoint gaps and set signals
and points manually. Original saves are not overwritten.

## Maps and reference data

Load game timetable data, select lines, then draw a geographic, octolinear, metro,
grid or strip map. Search/sort does not cancel hidden selections. Branch grouping
merges shared sections of the same line, not unrelated lines with the same origin.
Override groups if needed. Interchanges require matching station IDs.

Export SVG for printing, or route-map JSON to preserve selected source data and
drawing settings. Set the export folder on the map page. This JSON cannot replace
a game timetable export or a track-laying GeoJSON route.

Real-world reference maps use online OpenStreetMap/OpenRailwayMap services. Follow
their usage policies and retain attribution. The local tile cache stores viewed
tiles only; it does not download entire regions. Read-only cache mode may show
older data. HTTP rate limits are respected rather than bypassed.

## Files and cleanup

Follow-latest checks stable files from the same project. It defers switching while
tasks or edits are active. Newest does not mean the save and export match.

Preview cleanup and protect copies worth retaining. Only unchanged toolkit outputs
with matching creation records are eligible automatically. Modified or unrecorded
copies are skipped. JSON exports require manual selection and are never deleted
by startup cleanup. Eligible files move to Recycle Bin on Windows. Protected copies
use a same-name `.keep` file; retain it when moving the save.

## Updates and diagnostics

Use **Check for updates**, then confirm installation. SHA-256 and per-file checks
run before replacement. Failed updates attempt rollback; if recovery is incomplete,
stop using the app, retain logs/backups and extract a complete release again.

Run `Diagnostics.exe` if startup fails. Read the report and
`%LOCALAPPDATA%/NIMBY_Timetable_Toolkit/logs/startup.log`. Redact private paths before
sharing. A passing runtime self-test does not certify in-game operation.

Stable updates exclude prereleases. 3D is not part of this version; 2.0.0 beta will
have separate release notes and verification requirements.
