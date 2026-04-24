import streamlit as st
import pydeck as pdk
import geopandas as gpd
import json
import sqlite3
import pandas as pd

st.title("🎈 My new app")
st.write(
    "Let's start building! For help and inspiration, head over to [docs.streamlit.io](https://docs.streamlit.io/)."
)

st.set_page_config(page_title="DHSegura Map", layout="wide")
st.title("DHSegura GeoJSON Map")

### Setting paths to the relevant files
geojson_path = "DHSegura.geojson"
gpkg_path = "well_datapoints.gpkg"


###Loading the GeoPackage using sqlite3 to directly access the data without relying on external libraries like geopandas,
# which can be heavy and may have compatibility issues in some environments."""


def load_gpkg_with_sqlite(gpkg_path):
    con = sqlite3.connect(gpkg_path)

    # List available layers
    tables = pd.read_sql("SELECT table_name FROM gpkg_contents", con)
    available_layers = tables["table_name"].tolist()

    return con, available_layers

###Transforming the GeoPackage layer into a GeoJSON format that can be rendered by pydeck
def gpkg_layer_to_geojson(con, layer_name):
    """Convert a GeoPackage layer to a GeoJSON FeatureCollection."""
    df = pd.read_sql(f"SELECT * FROM \"{layer_name}\"", con)

    # Find the geometry column
    geom_col = pd.read_sql(
        f"SELECT column_name FROM gpkg_geometry_columns WHERE table_name='{layer_name}'",
        con
    )["column_name"].iloc[0]

    # Parse WKB geometry using shapely
    from shapely import wkb
    import struct

    features = []
    for _, row in df.iterrows():
        raw = row[geom_col]
        if raw is None:
            continue
        # GeoPackage WKB has a 2-byte magic + variable header before the WKB blob
        # Skip the gpkg header (magic 'GP' + version + flags + optional envelope)
        flags = raw[3]
        envelope_type = (flags >> 1) & 0x07
        envelope_sizes = [0, 32, 48, 48, 64]
        header_len = 8 + envelope_sizes[envelope_type] if envelope_type < 5 else 8
        geom = wkb.loads(bytes(raw[header_len:]))

        props = {k: v for k, v in row.items() if k != geom_col}
        # Convert non-serializable types
        props = {k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v)
                 for k, v in props.items()}

        features.append({
            "type": "Feature",
            "geometry": json.loads(geom.__geo_interface__.__str__().replace("'", '"'))
            if False else geom.__geo_interface__,
            "properties": props,
        })

    return {"type": "FeatureCollection", "features": features}

### Adjusting the map start location to be in the center of the provided data and at a reasonable zoom level###
def compute_view_from_bounds(bounds_list, zoom=7):
    """Compute center ViewState from a list of (minx, miny, maxx, maxy) bounds."""
    minx = min(b[0] for b in bounds_list)
    miny = min(b[1] for b in bounds_list)
    maxx = max(b[2] for b in bounds_list)
    maxy = max(b[3] for b in bounds_list)
    return pdk.ViewState(
        latitude=(miny + maxy) / 2,
        longitude=(minx + maxx) / 2,
        zoom=zoom,
        pitch=0,
    )

layers = []
bounds_list = []