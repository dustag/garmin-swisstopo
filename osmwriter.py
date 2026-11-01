"""Write shapely geometries (LV95) as OSM XML (WGS84) for mkgmap.

mkgmap expects nodes before ways and relations: each section is written to a
temporary file and they are concatenated on close.
"""
import shutil
from pathlib import Path
from xml.sax.saxutils import quoteattr

import numpy as np
import shapely
from pyproj import Transformer

_LV95_TO_WGS84 = Transformer.from_crs(2056, 4326, always_xy=True)


def to_wgs84(geom):
    return shapely.transform(geom, lambda xy: np.column_stack(_LV95_TO_WGS84.transform(xy[:, 0], xy[:, 1])))


class OsmWriter:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._parts = [self.path.with_suffix(f".{s}.tmp") for s in ("n", "w", "r")]
        self._nodes, self._ways, self._rels = (open(p, "w", encoding="utf-8") for p in self._parts)
        self._id = 0

    def _next(self):
        self._id -= 1
        return self._id

    @staticmethod
    def _tags(tags):
        return "".join(f"<tag k={quoteattr(k)} v={quoteattr(str(v))}/>" for k, v in tags.items() if v not in (None, ""))

    def _write_nodes(self, coords):
        ids = []
        for lon, lat in coords:
            nid = self._next()
            self._nodes.write(f'<node id="{nid}" lat="{lat:.7f}" lon="{lon:.7f}"/>\n')
            ids.append(nid)
        return ids

    def _way(self, coords, tags, closed=False):
        coords = list(coords)
        if closed:
            coords = coords[:-1]
        if len(coords) < (3 if closed else 2):
            return None
        ids = self._write_nodes(coords)
        if closed:
            ids.append(ids[0])
        wid = self._next()
        refs = "".join(f'<nd ref="{i}"/>' for i in ids)
        self._ways.write(f'<way id="{wid}">{refs}{self._tags(tags)}</way>\n')
        return wid

    def point(self, geom, tags):
        lon, lat = to_wgs84(geom).coords[0][:2]
        nid = self._next()
        self._nodes.write(f'<node id="{nid}" lat="{lat:.7f}" lon="{lon:.7f}">{self._tags(tags)}</node>\n')

    def line(self, geom, tags):
        for part in shapely.get_parts(to_wgs84(shapely.force_2d(geom))):
            self._way(part.coords, tags)

    def polygon(self, geom, tags):
        for poly in shapely.get_parts(to_wgs84(shapely.force_2d(geom))):
            if not poly.interiors:
                self._way(poly.exterior.coords, tags, closed=True)
                continue
            members = [("outer", self._way(poly.exterior.coords, {}, closed=True))]
            members += [("inner", self._way(r.coords, {}, closed=True)) for r in poly.interiors]
            refs = "".join(f'<member type="way" ref="{w}" role="{role}"/>' for role, w in members if w)
            self._rels.write(f'<relation id="{self._next()}">{refs}'
                             f'{self._tags({"type": "multipolygon", **tags})}</relation>\n')

    def add(self, geom, tags):
        """Dispatch on geometry type."""
        if geom is None or geom.is_empty:
            return
        kind = geom.geom_type
        if "Point" in kind:
            for p in shapely.get_parts(geom):
                self.point(p, tags)
        elif "LineString" in kind:
            self.line(geom, tags)
        elif "Polygon" in kind:
            self.polygon(geom, tags)
        elif kind == "GeometryCollection":
            for part in shapely.get_parts(geom):
                self.add(part, tags)

    def close(self):
        for f in (self._nodes, self._ways, self._rels):
            f.close()
        with open(self.path, "w", encoding="utf-8") as out:
            out.write("<?xml version='1.0' encoding='UTF-8'?>\n<osm version='0.6' generator='swisstopo-garmin'>\n")
            for p in self._parts:
                with open(p, encoding="utf-8") as f:
                    shutil.copyfileobj(f, out)
                p.unlink()
            out.write("</osm>\n")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
