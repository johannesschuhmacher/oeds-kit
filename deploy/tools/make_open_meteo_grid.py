"""Build the 1-degree grid of the open_meteo crawler (crawler/data/open_meteo_grid.json).

Run once by hand; the crawler only reads the JSON file. Needs geopandas and the
Natural Earth 1:110m countries shapefile (public domain), e.g.
https://naturalearth.s3.amazonaws.com/110m_cultural/ne_110m_admin_0_countries.zip

    python make_open_meteo_grid.py ne_110m_admin_0_countries.shp

A grid point is kept when it lies on land of one of the ENTSO-E countries below;
offshore points are not included.
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import Point

COUNTRIES = "AL AT BA BE BG CH CZ DE DK EE ES FI FR GB GR HR HU IE IT LT LU LV ME MK NL NO PL PT RO RS SE SI SK XK".split()
LONGITUDES = np.arange(-10, 31.01, 1.0)
LATITUDES = np.arange(35, 71.01, 1.0)
OUT = Path(__file__).resolve().parents[2] / "packages/crawler-pack/src/crawler/data/open_meteo_grid.json"

shapes = gpd.read_file(sys.argv[1])
shapes = shapes[shapes["ISO_A2_EH"].isin(COUNTRIES)][["ISO_A2_EH", "NAME", "geometry"]]
points = gpd.GeoDataFrame(geometry=[Point(lon, lat) for lat in LATITUDES for lon in LONGITUDES], crs=shapes.crs)
joined = gpd.sjoin(points, shapes, predicate="within").sort_values(["ISO_A2_EH"])

grid = {
    "source": "1-degree grid on land of ENTSO-E countries, Natural Earth 1:110m countries",
    "countries": dict(sorted(zip(shapes["ISO_A2_EH"], shapes["NAME"]))),
    "points": [[row.ISO_A2_EH, round(row.geometry.y, 2), round(row.geometry.x, 2)] for row in joined.itertuples()],
}
OUT.write_text(json.dumps(grid, separators=(",", ":")) + "\n", encoding="utf-8")
print(f"{len(grid['points'])} points in {len(grid['countries'])} countries -> {OUT}")
