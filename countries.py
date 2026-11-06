"""Zones of the countries mapped from OpenStreetMap: outline, Geofabrik extract and
terrain model of each zone.

- Italy: provinces (ISTAT abbreviation, e.g. AO) and GP, the Piedmont side of the Gran
  Paradiso; terrain TINITALY 10 m.
- Austria: NUTS 3 regions (e.g. AT332); terrain DGM Österreich 10 m.
- Germany: NUTS 3 regions (e.g. DE27E); terrain DGM1 in Bavaria, Copernicus elsewhere.
- Spain: NUTS 3 provinces (e.g. ES241); terrain MDT 5 m of the IGN.
- Andorra: AD; terrain Copernicus GLO-30.
"""
from dataclasses import dataclass
from pathlib import Path

import shapely

import config
import coverage
import demsrc
import italy

# Outlines are generalised (ISTAT, GISCO 1:1 million): zones are widened so that no gap is
# left along Switzerland and France, whose precise outlines take back what lies beyond.
ZONE_MARGIN = 1000  # m
# Geofabrik extracts: Italy by ISTAT region, Germany and Spain by NUTS 2 region
ITALY_EXTRACTS = {1: "nord-ovest", 2: "nord-ovest", 3: "nord-ovest", 7: "nord-ovest",
                  4: "nord-est", 5: "nord-est", 6: "nord-est", 8: "nord-est"}
GERMANY_EXTRACTS = {"DE11": "baden-wuerttemberg", "DE12": "baden-wuerttemberg", "DE13": "baden-wuerttemberg",
                    "DE14": "baden-wuerttemberg", "DE21": "bayern/oberbayern", "DE22": "bayern/niederbayern",
                    "DE23": "bayern/oberpfalz", "DE24": "bayern/oberfranken", "DE25": "bayern/mittelfranken",
                    "DE26": "bayern/unterfranken", "DE27": "bayern/schwaben"}
SPAIN_EXTRACTS = {"ES11": "galicia", "ES12": "asturias", "ES13": "cantabria", "ES21": "pais-vasco",
                  "ES22": "navarra", "ES23": "la-rioja", "ES24": "aragon", "ES41": "castilla-y-leon",
                  "ES51": "cataluna", "ES52": "valencia"}


@dataclass(frozen=True)
class Zone:
    country: str   # key of config.OSM_ZONES
    code: str

    @property
    def key(self):
        return self.country, self.code

    @property
    def dir(self) -> Path:
        return config.DOWNLOAD_DIR / self.country / self.code

    @property
    def ready(self) -> bool:
        return (self.dir / "ready").exists()

    def outline(self):
        if self.country == "it":
            return coverage.italy_zone(self.code)
        return coverage.nuts_zone(self.country, self.code)

    def area(self):
        return self.outline().buffer(ZONE_MARGIN)

    @property
    def extract(self) -> str:
        """Path of the Geofabrik extract containing the zone."""
        if self.country == "it":
            return "europe/italy/" + ITALY_EXTRACTS[coverage.italy_zone_code(self.code, "region")]
        if self.country == "at":
            return "europe/austria"
        if self.country == "ad":
            return "europe/andorra"
        table = {"de": GERMANY_EXTRACTS, "es": SPAIN_EXTRACTS}[self.country]
        if self.code[:4] not in table:
            raise ValueError(f"zone {self.code}: no OpenStreetMap extract configured for {self.code[:4]}")
        return f"europe/{'germany' if self.country == 'de' else 'spain'}/{table[self.code[:4]]}"

    @property
    def dem(self):
        """Terrain provider: function(area, fetch) filling its km2 cells."""
        if self.country == "it":
            return italy.tinitaly
        if self.country == "at":
            return demsrc.austria
        if self.country == "de":
            return demsrc.bavaria if self.code.startswith("DE2") else demsrc.copernicus
        if self.country == "es":
            return demsrc.spain
        return demsrc.copernicus


def configured() -> list[Zone]:
    """Zones whose data is used, in priority order."""
    return [Zone(c, code) for c, codes in config.OSM_ZONES.items() for code in codes]


def in_tile(bounds) -> list[Zone]:
    """Configured zones with downloaded data that have land in the tile."""
    box = shapely.box(*bounds)
    return [z for z in configured() if z.ready and z.area().intersects(box)]
