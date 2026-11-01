# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Test area `chavornay` (village and municipality of Chavornay, VD).
- Fixed 10 km LV95 tile grid: each tile is built once, in parallel, cached, and has a fixed Garmin map id.
- Coverages: named areas, `switzerland`, `canton:XX[,YY]` and `bbox:E0,N0,E1,N1`, through `--coverage` or
  `COVERAGE` in `.env`.
- Build options `--force` and `--jobs`.
- Opaque background limited to Switzerland, so the map hides Garmin's TopoActive maps in Switzerland
  only.

### Changed

- swissALTI3D is resampled to 5 m at download time and the 2 m originals deleted, which makes all of
  Switzerland practical (~3.5 GB instead of ~40 GB).
- Intermediate OSM files are gzipped.
- Hill shading files are assembled from the tiles and zipped.
- Draw priorities raised to 40 (base) and 41 (winter), above Garmin's own maps.
- `ZONE` in `.env` is replaced by `COVERAGE`.

### Fixed

- Each coverage gets its own Garmin family id, so maps of several coverages no longer conflict on the
  device.
- Hill shading no longer warns about missing elevation files next to the map bounds.

## [0.1.0] - 2026-11-01

### Added

- Resumable download of swissALTI3D tiles (area only), swissTLM3D, the swisstopo ski touring and snowshoe
  routes, and mkgmap (`download.py`).
- Base map: land cover, buildings, roads and paths with the Swiss hiking categories, streams, aerial
  ropeways, railways, power lines, summits with elevation, passes, huts, place names.
- 10/50/100 m contour lines and hill shading (`.hgt`) computed from swissALTI3D.
- Transparent winter overlay with:
  - slope classes over 30°;
  - the ski touring network, with arrows oriented from the terrain model;
  - SAC route numbers and grades;
  - snowshoe routes;
  - wildlife quiet zones and protection areas, with their allowed routes.
- Single legend definition (`legend.py`) generating the mkgmap style and the TYP file.
- Configurable label language (`fr`, `de`, `it`, `rm`, `en`) with a multilingual TYP legend.
- Local configuration through `.env`.
- First test area: Les Monts Telliers from the Grand-St-Bernard tunnel (`telliers`).
