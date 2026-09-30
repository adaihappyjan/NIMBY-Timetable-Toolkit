# Local PMTiles / MLT decoder

Runtime file: `tiles.mjs`. No network access: bounded local random-access reads.
Node.js 22+ is an optional user-installed prerequisite.

Pinned direct dependencies:

- `@maplibre/mlt` 1.2.1 — https://github.com/maplibre/maplibre-tile-spec (MIT choice)
- `pmtiles` 4.3.0 — https://github.com/protomaps/PMTiles (BSD-3-Clause)
- Transitive `@mapbox/point-geometry` and `fflate`: exact versions/integrity in
  `scripts/autotrack/package-lock.json`. Full licenses in `LICENSES.txt`.

Rebuild from repository source (development only):

```text
cd scripts/autotrack
npm ci --ignore-scripts
npm run build
```

Entry point: `scripts/autotrack_tiles.mjs`; bundler: esbuild 0.25.12. The minified
ES module is packaged and started only with a fixed Node command, memory limit
and timeout. It does not run user scripts or fetch maps. Neither game files nor
the game's full map archive are distributed.
