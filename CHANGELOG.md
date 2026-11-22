# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Cycling overlay (`--maps velo`, **Vélo (surcouche)** in the window), a third transparent map: cycling
  routes by network level and mountain bike routes by difficulty, with single trails and route numbers.
  SwitzerlandMobility (Veloland, Mountainbikeland) in Switzerland and Liechtenstein, the bicycle and
  mtb routes of OpenStreetMap elsewhere, read from the Geofabrik extracts (French regions included).

### Fixed

- Geofabrik moved each extract into its own folder: the Italian, Spanish and German extracts could no
  longer be downloaded.
- Downloads wait and try again while a server is unavailable (Geofabrik answered "503" for minutes) or the
  network drops, resuming the partial file.

## [0.8.0] - 2026-11-18

### Added

- `build.py --basecamp`, and **Aussi pour Garmin BaseCamp** in the window: the maps are also written as
  `.gmap` folders (`OUTPUT_DIR/basecamp`) to view them in BaseCamp on the PC.
- README: how to view the maps on a PC, with QMapShack or BaseCamp.

### Fixed

- Buildings had wavy, odd shapes: their many vertices along the sides were each rounded to the Garmin
  grid (about 2.4 m). They are now simplified to their corners (1 m tolerance) before writing; all tiles
  are rebuilt once.
- Unnamed roads showed "NAN" as their label.

## [0.7.2] - 2026-11-18

### Fixed

- The device ignored the colours and patterns of the maps: the TYP file inside them was named
  `BASE.TYP.TYP`, not a valid Garmin name, and Garmin's default styles were drawn instead. Among
  others, the hiking trails, which have no default style, did not show at all.
- Unnamed lines (railways, streams…) showed the copyright message as their label.
- A network drop during a build made the Swiss tiles fail: the requests for the wildlife zones now wait
  and try again.

### Changed

- Roads carrying a hiking route are filled with its colour (yellow, red or blue) instead of being edged;
  main roads are white and wide, so as not to be mistaken for them.
- Hiking trails are drawn one pixel wider.

## [0.7.1] - 2026-11-15

### Fixed

- Swiss hiking routes running on roads were drawn as plain roads, so that most of them did not show
  on the Plateau: these roads are now edged with the colour of the route (yellow, red or blue).
- Download and build spent minutes on nothing: the Alps perimeter was widened again for every zone and
  every tile, and the swissALTI3D catalogue was queried even when every tile was there. A download with
  all the data present now takes seconds, and building the tiles of the Alps is faster.

## [0.7.0] - 2026-11-09

### Added

- All the Alps of France, Switzerland, Italy and Austria: every zone with land in the perimeter of the
  Alpine Convention (2025), the zones mostly outside it being cut to the perimeter:
  - France: Savoie, Isère, Hautes-Alpes, Alpes-de-Haute-Provence, Alpes-Maritimes, Drôme, Var, Vaucluse;
  - Italy: Turin (replacing the Gran Paradiso zone), Cuneo, Biella, Vercelli, Novara, Imperia, Savona,
    Lecco, Bergamo, Brescia, Trentino, Verona, Vicenza, Belluno, Treviso, Pordenone, Udine, Gorizia;
  - Austria: Steyr-Kirchdorf, Graz, Eastern and Western Styria, Sankt Pölten, Vienna surroundings,
    Burgenland;
  - Liechtenstein as a zone of its own (`canton:LI`).
- Regions (`config.REGIONS`): `alpes-ouest`, `alpes-est`, `jura` and `pyrenees`, whose maps never share a
  tile; the default zones of each country are those of the regions.
- Configuration window: **Jura**, **Alpes occidentales** and **Alpes orientales** buttons; a selection made
  of exactly one region is built as that region.
- Configuration window: a coarse shaded relief under the zones (Copernicus GLO-90, `relief_*.png`).

### Changed

- The `alpes` coverage is replaced by `alpes-ouest` and `alpes-est`: together the Alps would exceed what one
  Garmin file can hold.
- The **Toute la Suisse** button is removed.
- IGN downloads wait and retry when the server asks to slow down (HTTP 429).
- OpenStreetMap queries (Overpass) try several public servers in turn; when all of them are down, a
  French department is downloaded without its rock and scree areas, which the next run adds.

### Fixed

- A selection of many zones in the window made mkgmap fail ("Description is too long"): long coverage
  names are shortened with a fingerprint, and every name given to mkgmap is capped at 50 characters.
- A brief network drop no longer stops a download.

## [0.6.0] - 2026-11-06

### Added

- Austrian Alps (`AUSTRIA_ZONES`, 19 NUTS 3 regions from Vorarlberg to Lower Austria), the Allgäu
  (`GERMANY_ZONES`), the Spanish Pyrenees (`SPAIN_ZONES`: Navarre, Huesca, Lleida, Girona) and Andorra,
  mapped from OpenStreetMap like Italy, with Swiss, French, then Italian data keeping priority:
  - terrain from DGM Österreich 10 m, the Bavarian DGM1 (averaged to 5 m), the Spanish IGN MDT 5 m and
    Copernicus GLO-30 for Andorra;
  - zone outlines from Eurostat (GISCO NUTS 3).
- French Pyrenees: departments 64, 65, 31, 09 and 66 added to the default `FRANCE_DEPTS`.
- Coverages `at:`, `de:`, `es:`, `ad`, and the aliases `alpes` and `pyrenees`: two maps that can be
  installed together.
- Ski touring routes mapped in OpenStreetMap, in the winter overlay outside Switzerland.
- Configuration window: the new zones, and the Pyrenees in a framed inset below the Alps.

### Changed

- The Italian terrain and map code is shared by all the countries mapped from OpenStreetMap
  (`osmzone.py`, `countries.py`, `demsrc.py`); the Italian zones are extracted again once, for the ski
  touring routes.
- A coverage outside Switzerland no longer downloads the Swiss data.
- Neighbouring OpenStreetMap zones are cut along their borders, without the 1 km margin kept towards
  Switzerland and France: the extracts barely go past their borders.

### Fixed

- Hill shading west of Greenwich: the elevation files are named `W…`.

## [0.5.0] - 2026-11-04

### Added

- Standalone application for Windows (folder in a zip) and macOS, Apple silicon and Intel (app in a dmg),
  with Python, the libraries, a minimal Java runtime and mkgmap: `packaging/build_app.py`, and a GitHub
  workflow that builds the three and attaches them to each published release.

### Changed

- The bundled Java runtime is used when `JAVA_EXE` is not set; the window keeps the Java field empty by
  default.
- `download.py` no longer downloads mkgmap when it is already there.
- Java runs without a console window when the build is started from the window on Windows.

## [0.4.0] - 2026-11-04

### Added

- Configuration window (`python gui.py`, PySide6): the cantons, French departments and Italian zones
  are picked on a map, with the maps to build (summer, winter or both), the label language, hill shading
  and folders, and an estimate of the map size; the window runs the download and the build, shows their
  log and progress, and can cancel them.
- `build.py --maps base|hiver`: compile only the base map or only the winter overlay.
- The window and the zone names follow the label language (French, German, Italian or English); at first
  start, the system language, or English if it is none of them.

### Removed

- Romansh (`LANG_LABELS=rm`): the labels are in French, German, Italian or English.

## [0.3.0] - 2026-11-04

### Added

- Italian Alps along the Swiss border (`ITALY_ZONES`): the provinces of Aosta, Verbano-Cusio-Ossola,
  Varese, Como, Sondrio and Bolzano, and the Piedmont side of the Gran Paradiso, with Swiss and French
  data keeping priority:
  - terrain, contours, slopes and hill shading from INGV TINITALY 10 m;
  - base map from OpenStreetMap, with paths in the Swiss hiking colours after their SAC scale;
  - parks and nature reserves, and Camptocamp ski touring routes, in the winter overlay.
- Coverage `it:XX[,YY]`, and `it` for all the Italian zones.

### Changed

- The nature reserve legend entries now read "(FR/IT)".
- Maps are named "Swisstopo base/hiver …" instead of "Swisstopo CAS …": the project is independent of
  the Swiss Alpine Club.

## [0.2.0] - 2026-11-04

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
- swissALTI3D downloads retry on transient network errors instead of stopping the whole download.

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

[Unreleased]: https://github.com/dustag/garmin-swisstopo/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/dustag/garmin-swisstopo/compare/v0.7.2...v0.8.0
[0.7.2]: https://github.com/dustag/garmin-swisstopo/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/dustag/garmin-swisstopo/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/dustag/garmin-swisstopo/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/dustag/garmin-swisstopo/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/dustag/garmin-swisstopo/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/dustag/garmin-swisstopo/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/dustag/garmin-swisstopo/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/dustag/garmin-swisstopo/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/dustag/garmin-swisstopo/releases/tag/v0.1.0
