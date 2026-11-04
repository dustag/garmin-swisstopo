# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- French departments (`FRANCE_DEPTS`, tested with Haute-Savoie), with Swiss data keeping priority:
  - terrain, contours, slopes and hill shading from IGN RGE ALTI 5 m, merged with swissALTI3D;
  - base map from IGN BD TOPO, with rock and scree areas from OpenStreetMap;
  - GR routes (red) and other marked hiking routes (yellow);
  - nature reserves and protection orders in the winter overlay;
  - Camptocamp ski touring routes, as tracks or as points with name and grade.
- Coverage `dept:NN[,MM]` and combined coverages joined with `+`, e.g. `canton:VS+dept:74`.

### Changed

- Downloads send a user agent, required by the IGN download service.
- Tiles are rebuilt automatically when a French department becomes available.

### Fixed

- Large coverages failed on Windows: mkgmap options are now passed through a config file instead of the
  command line, and tile descriptions are cut to the 50 characters Garmin allows.

## [0.1.0] - 2026-11-03

First release.

### Added

- Download of the data (`download.py`), resumable:
  - swissALTI3D, only the tiles needed by the coverage, resampled to 5 m at download time
    (~3.5 GB for all of Switzerland instead of ~40 GB at 2 m);
  - swissTLM3D;
  - the swisstopo ski touring and snowshoe routes;
  - mkgmap.
- Base map:
  - land cover, buildings, streams, aerial ropeways, railways, power lines;
  - roads, and paths with the Swiss hiking categories;
  - summits with elevation, passes, huts, place names;
  - 10/50/100 m contour lines and hill shading, computed from swissALTI3D;
  - an opaque background over Switzerland only, so the map hides Garmin's TopoActive maps in Switzerland
    but not abroad.
- Transparent winter overlay with:
  - slope classes over 30°;
  - the ski touring network, with arrows oriented from the terrain model;
  - SAC route numbers and grades;
  - snowshoe routes;
  - wildlife quiet zones and protection areas, with their allowed routes.
- Fixed 10 km LV95 tile grid: each tile is built once, in parallel, cached, and has a fixed Garmin map id.
- Coverages: named areas (`telliers`, `chavornay`), `switzerland`, `canton:XX[,YY]` and
  `bbox:E0,N0,E1,N1`, through `--coverage` or `COVERAGE` in `.env`. Each coverage has its own Garmin
  family id.
- Build options `--no-dem`, `--step`, `--force` and `--jobs`.
- Single legend definition (`legend.py`) generating the mkgmap style and the TYP file.
- Configurable label language (`fr`, `de`, `it`, `rm`, `en`) with a multilingual TYP legend.
- Local configuration through `.env`.
- Instructions to install the maps on a Garmin fēnix 7X Pro, and to enable them per activity for summer
  and winter.

[Unreleased]: https://github.com/dustag/garmin-swisstopo/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/dustag/garmin-swisstopo/releases/tag/v0.1.0
