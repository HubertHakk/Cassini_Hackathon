import streamlit as st
import pydeck as pdk
import json
import sqlite3
import pandas as pd
from shapely import wkb

st.set_page_config(page_title="DHSegura Map", layout="wide")
st.title("DHSegura GeoJSON Map")

geojson_path = "DHSegura.geojson"
gpkg_path = "DHSegura.gpkg"


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


def compute_view_from_bounds(bounds_list, zoom=12):
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

# --- GeoJSON layer ---
geojson_data = None
try:
    geojson_data = load_geojson(geojson_path)

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
        lons, lats = [c[0] for c in all_coords], [c[1] for c in all_coords]
        bounds_list.append((min(lons), min(lats), max(lons), max(lats)))

except FileNotFoundError:
    st.sidebar.warning("DHSegura.geojson not found")
except Exception as e:
    st.sidebar.warning(f"GeoJSON error: {e}")

    geojson_data = None
try:
    geojson_data = load_geojson(geojson_path)

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
        lons, lats = [c[0] for c in all_coords], [c[1] for c in all_coords]
        bounds_list.append((min(lons), min(lats), max(lons), max(lats)))

except FileNotFoundError:
    st.sidebar.warning("DHSegura.geojson not found")
except Exception as e:
    st.sidebar.warning(f"GeoJSON error: {e}")


# --- GeoPackage layer ---
gpkg_geojson = None
selected_layer = None
try:
    available_layers = list_gpkg_layers(gpkg_path)
    selected_layer = st.sidebar.selectbox("GeoPackage layer", available_layers)
    gpkg_geojson = load_gpkg_layer(gpkg_path, selected_layer)

    features = gpkg_geojson["features"]
    point_features = [f for f in features if f["geometry"]["type"] == "Point"]
    if point_features:
        lons = [f["geometry"]["coordinates"][0] for f in point_features]
        lats = [f["geometry"]["coordinates"][1] for f in point_features]
        bounds_list.append((min(lons), min(lats), max(lons), max(lats)))

except FileNotFoundError:
    st.sidebar.warning("GeoPackage file not found")
except Exception as e:
    st.sidebar.warning(f"GeoPackage error: {e}")

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
    st.pydeck_chart(pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        tooltip={"text": "{name}"},
    ))
elif geojson_data is None and gpkg_geojson is None:
    st.error("No layers could be loaded. Please check your files.")
else:
    st.info("All layers are hidden. Toggle a layer in the sidebar to show it.")