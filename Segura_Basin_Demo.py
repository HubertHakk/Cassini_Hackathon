import streamlit as st
import pydeck as pdk
import json
import sqlite3
import pandas as pd
from shapely import wkb
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
import numpy as np
from PIL import Image
import io
import base64
import tempfile, os


st.markdown("""
<style>
.block-container {
    max-width: 90% !important;
    padding-left: 2rem;
    padding-right: 2rem;
}
</style>
""", unsafe_allow_html=True)


st.title("Well-D: Well Detection software")

st.write("Welcome to the Well-D demo! This application demonstrates the use of our software to detect unregistered wells in the Segura River Basin, Spain.\
         \n\nUse the sidebar to toggle the visibility of the Segura Basin boundary and the detected well locations.")

st.header("Unregistered Well Detection in the Segura River Basin, Spain")
st.write("")

st.markdown("""
    <div style="
        background-color: #8cc5e3;
        border-radius: 20px;
        padding: 0.75rem 1rem;
        font-size: 1rem;
        color: white;
            ">This demo showcases the application of Well-D developed software to detect unregistered wells in the Segura river basin, Spain.\
          The map below displays the boundary of the Segura river basin as well as the detected well locations. Use the sidebar to toggle layers and explore the data. </div>
""", unsafe_allow_html=True)
st.write("")


# --- Constants ---
COLORMAPS = {
    "RdBu (diverging)":   [(5,113,176),  (146,197,222), (247,247,247), (244,165,130), (202,0,32)],
    "RdYlBu (diverging)": [(44,123,182), (171,217,233), (255,255,191), (253,174,97),  (215,25,28)],
    "Spectral":           [(94,79,162),  (50,136,189),  (171,221,164), (253,174,75),  (213,62,79)],
    "Viridis":            [(68,1,84),    (59,82,139),   (33,145,140),  (94,201,98),   (253,231,37)],
    # Sequential colormaps better suited to distance/cost rasters
    "YlOrRd":             [(255,255,204),(254,217,142), (254,153,41),  (227,74,51),   (179,0,0)],
    "Blues":              [(239,243,255),(189,215,231), (107,174,214), (49,130,189),  (8,81,156)],
}

geojson_path = "DHSegura.geojson"
gpkg_path = "well_datapoints.gpkg"
velocity_path = "velocity.tif"
# ── NEW: paths for the two distance-weighted uphill rasters ──────────────────
dist_clipped_path  = "dist_weighted_uphill_strict_clipped.tif"
dist_full_path     = "dist_weighted_uphill_strict.tif"


# --- Cached loaders ---

@st.cache_data
def load_geojson(path, simplify_factor=15):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("type") == "Feature":
        data = {"type": "FeatureCollection", "features": [data]}
    elif data.get("type") == "Geometry":
        data = {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": data, "properties": {}}],
        }
    def simplify_coords(obj):
        if isinstance(obj, list):
            if len(obj) > 1 and isinstance(obj[0], list) and len(obj[0]) == 2:
                thinned = obj[::simplify_factor]
                if thinned[-1] != obj[-1]:
                    thinned.append(obj[-1])
                return thinned
            return [simplify_coords(item) for item in obj]
        return obj
    for feature in data["features"]:
        feature["geometry"]["coordinates"] = simplify_coords(feature["geometry"]["coordinates"])
    return data

@st.cache_data
def list_gpkg_layers(path):
    con = sqlite3.connect(path)
    tables = pd.read_sql("SELECT table_name FROM gpkg_contents", con)
    con.close()
    return tables["table_name"].tolist()

def create_velocity_legend(cmap_name, vmin, vmax, width=300, height=20):
    colors = COLORMAPS[cmap_name]
    n = len(colors) - 1
    gradient = np.zeros((height, width, 3), dtype=np.uint8)
    for x in range(width):
        t_global = x / (width - 1)
        i = min(int(t_global * n), n - 1)
        lo_t, hi_t = i / n, (i + 1) / n
        t = (t_global - lo_t) / (hi_t - lo_t)
        lo_c = np.array(colors[i])
        hi_c = np.array(colors[i + 1])
        color = (lo_c + t * (hi_c - lo_c)).astype(np.uint8)
        gradient[:, x, :] = color
    img = Image.fromarray(gradient, mode="RGB")
    return img

@st.cache_data
def load_gpkg_layer(path, layer_name):
    con = sqlite3.connect(path)
    geom_col = pd.read_sql(
        f"SELECT column_name FROM gpkg_geometry_columns WHERE table_name='{layer_name}'",
        con,
    )["column_name"].iloc[0]
    useful_cols = [
        "Municipio", "Provincia", "COTA_msnm", "Usos_Agua", "Naturaleza",
        "PROF_m", "Caudal_Referencia_L_s", "FECHA_OBRA",
        "Sistema_Acuifero", "Unidad_Hidrogeologica", "Cuenca_Hidrografica",
        geom_col,
    ]
    df = pd.read_sql(
        f'SELECT {", ".join(useful_cols)} FROM "{layer_name}" WHERE "Usos_Agua" NOT IN ("No se utiliza", "Desconocido")',
        con
    )
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


def compute_view_from_bounds(bounds_list, zoom=8):
    minx = min(b[0] for b in bounds_list)
    miny = min(b[1] for b in bounds_list)
    maxx = max(b[2] for b in bounds_list)
    maxy = max(b[3] for b in bounds_list)
    return pdk.ViewState(latitude=(miny + maxy) / 2, longitude=(minx + maxx) / 2, zoom=zoom, pitch=0)

@st.cache_data
def load_velocity_tif(path, downsample=2):
    with rasterio.open(path) as src:
        if src.crs.to_epsg() != 4326:
            transform, width, height = calculate_default_transform(
                src.crs, "EPSG:4326", src.width, src.height, *src.bounds
            )
            data = np.zeros((height, width), dtype=np.float32)
            reproject(
                source=rasterio.band(src, 1),
                destination=data,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=transform,
                dst_crs="EPSG:4326",
                resampling=Resampling.bilinear,
            )
            nodata = src.nodata
            bounds = rasterio.transform.array_bounds(height, width, transform)
        else:
            data = src.read(1).astype(np.float32)
            transform = src.transform
            nodata = src.nodata
            bounds = src.bounds
    data = data[::downsample, ::downsample]
    mask = np.isnan(data)
    if nodata is not None:
        mask |= (data == nodata)
    return data, mask, [bounds[0], bounds[1], bounds[2], bounds[3]]


# ── NEW: loader for the distance-weighted uphill rasters ─────────────────────
@st.cache_data
def load_dist_tif(path, downsample=2):
    """
    Load a distance-weighted uphill TIF (EPSG:32630) and reproject to WGS84.
    Masks nodata (-9999) AND inf values which are present in these rasters.
    Returns (data, mask, [west, south, east, north]).
    """
    with rasterio.open(path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, "EPSG:4326", src.width, src.height, *src.bounds
        )
        data = np.zeros((height, width), dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=data,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=transform,
            dst_crs="EPSG:4326",
            resampling=Resampling.bilinear,
        )
        nodata = src.nodata
        bounds = rasterio.transform.array_bounds(height, width, transform)

    data = data[::downsample, ::downsample]

    # Mask nodata, NaN, and inf — all present in these rasters
    mask = np.isnan(data) | np.isinf(data)
    if nodata is not None:
        mask |= (data == nodata)

    return data, mask, [bounds[0], bounds[1], bounds[2], bounds[3]]


@st.cache_data
def render_velocity_image(data, mask, cmap_name):
    colors = COLORMAPS[cmap_name]
    n = len(colors) - 1
    vmin, vmax = np.percentile(data[~mask], 2), np.percentile(data[~mask], 98)
    norm = np.clip((data - vmin) / (vmax - vmin), 0, 1)
    h, w = data.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    for i in range(n):
        lo_t, hi_t = i / n, (i + 1) / n
        in_range = (norm >= lo_t) & (norm < hi_t) & ~mask
        t = (norm[in_range] - lo_t) / (hi_t - lo_t)
        lo_c, hi_c = np.array(colors[i]), np.array(colors[i + 1])
        rgba[in_range, :3] = (lo_c + t[:, None] * (hi_c - lo_c)).astype(np.uint8)
        rgba[in_range, 3] = 200
    at_max = (norm >= 1.0) & ~mask
    rgba[at_max, :3] = colors[-1]
    rgba[at_max, 3] = 200
    img = Image.fromarray(rgba, mode="RGBA")
    tmp_path = os.path.join(tempfile.gettempdir(), f"velocity_{cmap_name}.png")
    img.save(tmp_path, format="PNG")
    return tmp_path, float(vmin), float(vmax)


# ── NEW: renderer shared by both distance rasters ────────────────────────────
@st.cache_data
def render_dist_image(data, mask, cmap_name, cache_key):
    """
    Render a distance-weighted uphill raster to a PNG and return its path
    together with the p2/p98 value range used for the legend.
    cache_key distinguishes the two rasters so @st.cache_data keeps them separate.
    """
    colors = COLORMAPS[cmap_name]
    n = len(colors) - 1

    valid = data[~mask]
    vmin, vmax = np.percentile(valid, 2), np.percentile(valid, 98)
    norm = np.clip((data - vmin) / (vmax - vmin), 0, 1)

    h, w = data.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)

    for i in range(n):
        lo_t, hi_t = i / n, (i + 1) / n
        in_range = (norm >= lo_t) & (norm < hi_t) & ~mask
        t = (norm[in_range] - lo_t) / (hi_t - lo_t)
        lo_c, hi_c = np.array(colors[i]), np.array(colors[i + 1])
        rgba[in_range, :3] = (lo_c + t[:, None] * (hi_c - lo_c)).astype(np.uint8)
        rgba[in_range, 3] = 180   # slightly more transparent than velocity layer

    at_max = (norm >= 1.0) & ~mask
    rgba[at_max, :3] = colors[-1]
    rgba[at_max, 3] = 180

    img = Image.fromarray(rgba, mode="RGBA")
    tmp_path = os.path.join(tempfile.gettempdir(), f"dist_{cache_key}_{cmap_name}.png")
    img.save(tmp_path, format="PNG")
    return tmp_path, float(vmin), float(vmax)


def sample_velocity_at_points(gpkg_geojson, velocity_data):
    data, mask, bounds = velocity_data
    west, south, east, north = bounds
    h, w = data.shape

    def lonlat_to_pixel(lon, lat):
        x = int((lon - west) / (east - west) * (w - 1))
        y = int((north - lat) / (north - south) * (h - 1))
        return x, y

    for feature in gpkg_geojson["features"]:
        if feature["geometry"]["type"] != "Point":
            continue
        lon, lat = feature["geometry"]["coordinates"]
        x, y = lonlat_to_pixel(lon, lat)
        if 0 <= x < w and 0 <= y < h and not mask[y, x]:
            velocity = float(data[y, x])
        else:
            velocity = None
        feature["properties"]["velocity"] = (
            round(float(velocity), 3) if velocity is not None else None
        )
    return gpkg_geojson


# --- Load data ---
geojson_data, gpkg_geojson = None, None
bounds_list = []
velocity_data = None
dist_clipped_data, dist_full_data = None, None

try:
    velocity_data = load_velocity_tif(velocity_path, downsample=2)
except Exception as e:
    st.sidebar.warning(f"Velocity layer error: {e}")

# ── NEW: load distance rasters ───────────────────────────────────────────────
try:
    dist_clipped_data = load_dist_tif(dist_clipped_path, downsample=2)
except Exception as e:
    st.sidebar.warning(f"Distance (clipped) layer error: {e}")

try:
    dist_full_data = load_dist_tif(dist_full_path, downsample=2)
except Exception as e:
    st.sidebar.warning(f"Distance (full) layer error: {e}")

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
except Exception as e:
    st.sidebar.warning(f"GeoJSON error: {e}")

try:
    available_layers = list_gpkg_layers(gpkg_path)
    gpkg_geojson = load_gpkg_layer(gpkg_path, available_layers[0])
    features = gpkg_geojson["features"]
    point_features = [f for f in features if f["geometry"]["type"] == "Point"]
    if point_features:
        lons = [f["geometry"]["coordinates"][0] for f in point_features]
        lats = [f["geometry"]["coordinates"][1] for f in point_features]
        bounds_list.append((min(lons), min(lats), max(lons), max(lats)))
except Exception as e:
    st.sidebar.warning(f"GeoPackage error: {e}")

if gpkg_geojson and velocity_data:
    gpkg_geojson = sample_velocity_at_points(gpkg_geojson, velocity_data)


# --- Sidebar ---
st.sidebar.title("Map Colour Scheme")
MAP_STYLES = {
    "Streets (light)": "light",
    "Streets (dark)":  "dark",
}

selected_style = st.sidebar.selectbox("Base map", list(MAP_STYLES.keys()))
selected_cmap  = st.sidebar.selectbox(
    "Subsidence velocity colormap",
    list(COLORMAPS.keys()),
    disabled=velocity_data is None,
)

# ── NEW: separate colormaps for the two distance layers ──────────────────────
selected_cmap_dist_clipped = st.sidebar.selectbox(
    "Distance (clipped) colormap",
    list(COLORMAPS.keys()),
    index=4,           # defaults to "YlOrRd" — a sequential map that suits cost rasters
    disabled=dist_clipped_data is None,
)
selected_cmap_dist_full = st.sidebar.selectbox(
    "Distance (full basin) colormap",
    list(COLORMAPS.keys()),
    index=5,           # defaults to "Blues"
    disabled=dist_full_data is None,
)

st.session_state.selected_style = MAP_STYLES[selected_style]

st.sidebar.title("Map Layers")
show_geojson       = st.sidebar.toggle("Segura Basin boundary",              value=True,  disabled=geojson_data is None)
show_gpkg          = st.sidebar.toggle("Well datapoints",                    value=True,  disabled=gpkg_geojson is None)
show_velocity      = st.sidebar.toggle("Subsidence velocity",                value=True,  disabled=velocity_data is None)
# ── NEW toggles ──────────────────────────────────────────────────────────────
show_dist_clipped  = st.sidebar.toggle("Watershed (Segura Basin)", value=False, disabled=dist_clipped_data is None)
show_dist_full     = st.sidebar.toggle("Watershed (Surrounding Segura area)",    value=False, disabled=dist_full_data is None)

st.sidebar.divider()
st.sidebar.subheader("Legend")
if geojson_data:
    st.sidebar.markdown("🟡 Segura Basin Boundary")
if gpkg_geojson:
    st.sidebar.markdown("🟢 Registered Well Datapoints")
#if dist_clipped_data:
#    st.sidebar.markdown("🟠 Watershed (clipped)")
#if dist_full_data:
#    st.sidebar.markdown("🔵 Watershed (Surrounding Segura area)")


# --- Render ---
view_state = compute_view_from_bounds(bounds_list) if bounds_list else pdk.ViewState(
    latitude=0, longitude=0, zoom=2
)

@st.fragment
def render_map(show_geojson, show_gpkg, show_velocity, show_dist_clipped, show_dist_full,
               view_state, selected_cmap, selected_cmap_dist_clipped, selected_cmap_dist_full):
    layers = []

    # Velocity layer
    if velocity_data and show_velocity:
        data, mask, bounds = velocity_data
        img_path, vmin, vmax = render_velocity_image(data, mask, selected_cmap)
        west, south, east, north = bounds
        layers.append(pdk.Layer(
            "BitmapLayer",
            image=img_path,
            bounds=[west, south, east, north],
            opacity=0.8,
            pickable=False,
        ))

    # ── NEW: Distance-weighted uphill (clipped) layer ────────────────────────
    if dist_clipped_data and show_dist_clipped:
        data, mask, bounds = dist_clipped_data
        img_path, _, _ = render_dist_image(data, mask, selected_cmap_dist_clipped, "clipped")
        west, south, east, north = bounds
        layers.append(pdk.Layer(
            "BitmapLayer",
            image=img_path,
            bounds=[west, south, east, north],
            opacity=0.75,
            pickable=False,
        ))

    # ── NEW: Distance-weighted uphill (full basin) layer ─────────────────────
    if dist_full_data and show_dist_full:
        data, mask, bounds = dist_full_data
        img_path, _, _ = render_dist_image(data, mask, selected_cmap_dist_full, "full")
        west, south, east, north = bounds
        layers.append(pdk.Layer(
            "BitmapLayer",
            image=img_path,
            bounds=[west, south, east, north],
            opacity=0.75,
            pickable=False,
        ))

    if geojson_data and show_geojson:
        layers.append(pdk.Layer(
            "GeoJsonLayer", geojson_data,
            pickable=False, stroked=True, filled=False,
            get_fill_color=[0, 128, 128, 80],
            get_line_color=[255, 220, 0],
            line_width_min_pixels=3,
        ))

    if gpkg_geojson and show_gpkg:
        layers.append(pdk.Layer(
            "GeoJsonLayer", gpkg_geojson,
            pickable=True, stroked=True, filled=True,
            get_fill_color=[0, 255, 120, 220],
            get_line_color=[0, 0, 0, 255],
            point_radius_min_pixels=4,
            line_width_min_pixels=1,
        ))

    if not layers:
        st.info("All layers are hidden.")
        return

    st.pydeck_chart(pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        map_provider="carto",
        map_style=st.session_state.selected_style,
        tooltip={
            "text": "📍 {Municipio}\n🏔 {COTA_msnm}m\n💧 {Usos_Agua}\n📉 Velocity: {velocity} mm/yr"
        },
    ))


render_map(
    show_geojson, show_gpkg, show_velocity, show_dist_clipped, show_dist_full,
    view_state, selected_cmap, selected_cmap_dist_clipped, selected_cmap_dist_full,
)


# --- Legends below map ---
if velocity_data and show_velocity:
    data, mask, _ = velocity_data
    vmin = np.percentile(data[~mask], 2)
    vmax = np.percentile(data[~mask], 98)
    legend_img = create_velocity_legend(selected_cmap, vmin, vmax)
    st.markdown("### Subsidence velocity (mm/year)")
    col1, col2, col3 = st.columns([1, 6, 1])
    with col1:
        st.write(f"{vmin:.1f}")
    with col2:
        st.image(legend_img, use_container_width=True)
    with col3:
        st.write(f"{vmax:.1f}")

# ── NEW: legends for the two distance layers ─────────────────────────────────
if dist_clipped_data and show_dist_clipped:
    data, mask, _ = dist_clipped_data
    vmin = np.percentile(data[~mask], 2)
    vmax = np.percentile(data[~mask], 98)
    legend_img = create_velocity_legend(selected_cmap_dist_clipped, vmin, vmax)
    st.markdown("### Distance-weighted cost — Segura Basin")
    col1, col2, col3 = st.columns([1, 6, 1])
    with col1:
        st.write(f"{vmin:.0f}")
    with col2:
        st.image(legend_img, use_container_width=True)
    with col3:
        st.write(f"{vmax:.0f}")

if dist_full_data and show_dist_full:
    data, mask, _ = dist_full_data
    vmin = np.percentile(data[~mask], 2)
    vmax = np.percentile(data[~mask], 98)
    legend_img = create_velocity_legend(selected_cmap_dist_full, vmin, vmax)
    st.markdown("### Distance-weighted cost — full Segura area")
    col1, col2, col3 = st.columns([1, 6, 1])
    with col1:
        st.write(f"{vmin:.0f}")
    with col2:
        st.image(legend_img, use_container_width=True)
    with col3:
        st.write(f"{vmax:.0f}")