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

# --- Cached loaders ---

@st.cache_data
def load_geojson(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("type") == "Feature":
        data = {"type": "FeatureCollection", "features": [data]}
    elif data.get("type") == "Geometry":
        data = {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": data, "properties": {}}],
        }
    return data

@st.cache_data
def list_gpkg_layers(path):
    con = sqlite3.connect(path)
    tables = pd.read_sql("SELECT table_name FROM gpkg_contents", con)
    con.close()
    return tables["table_name"].tolist()

@st.cache_data
def load_gpkg_layer(path, layer_name):
    con = sqlite3.connect(path)
    df = pd.read_sql(f'SELECT * FROM "{layer_name}"', con)
    geom_col = pd.read_sql(
        f"SELECT column_name FROM gpkg_geometry_columns WHERE table_name='{layer_name}'",
        con,
    )["column_name"].iloc[0]
    con.close()

    features = []
    for _, row in df.iterrows():
        raw = row[geom_col]
        if raw is None:
            continue
        flags = raw[3]
        envelope_type = (flags >> 1) & 0x07
        envelope_sizes = [0, 32, 48, 48, 64]
        header_len = 8 + envelope_sizes[envelope_type] if envelope_type < 5 else 8
        geom = wkb.loads(bytes(raw[header_len:]))
        props = {
            k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v)
            for k, v in row.items() if k != geom_col
        }
        features.append({
            "type": "Feature",
            "geometry": geom.__geo_interface__,
            "properties": props,
        })

    return {"type": "FeatureCollection", "features": features}

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

# --- Sidebar ---
st.sidebar.title("Map Layers")

layers = []
bounds_list = []

try:
    with open(geojson_path, "r", encoding="utf-8") as f:
        geojson_data = json.load(f)

    # Wrap bare Feature in a FeatureCollection
    if geojson_data.get("type") == "Feature":
        geojson_data = {"type": "FeatureCollection", "features": [geojson_data]}
    elif geojson_data.get("type") == "Geometry":
        geojson_data = {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": geojson_data, "properties": {}}],
        }

    geojson_layer = pdk.Layer(
        "GeoJsonLayer",
        geojson_data,
        pickable=True,
        stroked=True,
        filled=True,
        extruded=False,
        get_fill_color=[0, 128, 255, 80],
        get_line_color=[0, 80, 160, 200],
        line_width_min_pixels=1,
    )
    layers.append(geojson_layer)

    # Compute bounds from coordinates
    all_coords = []
    def recurse(obj):
        if isinstance(obj, list):
            if len(obj) >= 2 and all(isinstance(v, (int, float)) for v in obj[:2]):
                all_coords.append((obj[0], obj[1]))
            else:
                for item in obj:
                    recurse(item)
        elif isinstance(obj, dict):
            for v in obj.values():
                recurse(v)
    recurse(geojson_data)

    if all_coords:
        lons = [c[0] for c in all_coords]
        lats = [c[1] for c in all_coords]
        bounds_list.append((min(lons), min(lats), max(lons), max(lats)))

    st.success(f"GeoJSON loaded: {geojson_path}")

except FileNotFoundError:
    st.warning(f"GeoJSON file not found: {geojson_path}")
except json.JSONDecodeError:
    st.warning(f"Invalid GeoJSON format: {geojson_path}")
except Exception as e:
    st.warning(f"Could not load GeoJSON: {e}")

try:
    from shapely import wkb
    import sqlite3
    import struct

    con, available_layers = load_gpkg_with_sqlite(gpkg_path)
    selected_layer = st.selectbox("Select GeoPackage layer", available_layers)
    gpkg_geojson = gpkg_layer_to_geojson(con, selected_layer)
    con.close()

    gpkg_layer = pdk.Layer(
        "GeoJsonLayer",
        gpkg_geojson,
        pickable=True,
        stroked=True,
        filled=True,
        get_fill_color=[255, 100, 0, 120],
        get_line_color=[200, 60, 0, 220],
        point_radius_min_pixels=2.5,
        line_width_min_pixels=1,
    )
    layers.append(gpkg_layer)

    features = gpkg_geojson["features"]
    if features:
        lons = [f["geometry"]["coordinates"][0] for f in features if f["geometry"]["type"] == "Point"]
        lats = [f["geometry"]["coordinates"][1] for f in features if f["geometry"]["type"] == "Point"]
        if lons:
            bounds_list.append((min(lons), min(lats), max(lons), max(lats)))

    st.success(f"GeoPackage loaded: {len(features)} features from '{selected_layer}'")

except Exception as e:
    st.warning(f"Could not load GeoPackage: {e}")


# --- Layer toggles ---
st.sidebar.divider()
st.sidebar.subheader("Toggle layers")

show_geojson = st.sidebar.toggle("DHSegura boundary", value=True, disabled=geojson_data is None)
show_gpkg = st.sidebar.toggle("Well datapoints", value=True, disabled=gpkg_geojson is None)

# --- Sidebar legend ---
st.sidebar.divider()
st.sidebar.subheader("Legend")
if geojson_data:
    st.sidebar.markdown("🔵 DHSegura boundary")
if gpkg_geojson:
    st.sidebar.markdown("🟠 Well datapoints")

# --- Build active layers ---
if geojson_data and show_geojson:
    layers.append(pdk.Layer(
        "GeoJsonLayer", geojson_data,
        pickable=True, stroked=True, filled=True, extruded=False,
        get_fill_color=[0, 128, 255, 80],
        get_line_color=[0, 80, 160, 200],
        line_width_min_pixels=1,
    ))

if gpkg_geojson and show_gpkg:
    layers.append(pdk.Layer(
        "GeoJsonLayer", gpkg_geojson,
        pickable=True, stroked=True, filled=True,
        get_fill_color=[255, 100, 0, 120],
        get_line_color=[200, 60, 0, 220],
        point_radius_min_pixels=4,
        line_width_min_pixels=1,
    ))


# --- Render map ---
if layers:
    view_state = compute_view_from_bounds(bounds_list) if bounds_list else pdk.ViewState(
        latitude=0, longitude=0, zoom=2
    )

    st.pydeck_chart(
        pdk.Deck(
            layers=layers,
            initial_view_state=view_state,
            tooltip=False ,
        )
    )
else:
    st.error("No layers could be loaded. Please check your files.")


col1, col2, col3 = st.columns(3)

col4, col5= col3.columns(2)


col1.metric("1 Brazillion Wells!", 10000, delta=10, width="stretch")
col2.write("This is a metric showing the number of wells in the dataset, with a delta indicating recent changes.")
col4.metric("Average Depth", "2,500 ft", delta="-50 ft")
col5.metric("Average Production", "500 bbl/day", delta="+20 bbl/day")

st.sidebar.header("About This App")