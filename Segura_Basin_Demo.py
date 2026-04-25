import streamlit as st
import pydeck as pdk
import json
import sqlite3
import pandas as pd
from shapely import wkb

st.set_page_config(page_title="Well-D: Well Detection software", layout="wide")
st.title("Well-D: Well Detection software")

st.write("Welcome to the Well-D demo! This application demonstrates the use of our software to detect unregistered wells in the Segura River Basin, Spain.\
         \n\nUse the sidebar to toggle the visibility of the Segura Basin boundary and the detected well locations.")

st.header("Unregistered Well Detection in the Segura River Basin, Spain")
st.write("This demo showcases the application of Well-D developed software to detect unregistered wells in the Segura River Basin, Spain.\
          The map below displays the boundary of theSegura river basin as well as the detected well locations. Use the sidebar to toggle layers and explore the data.")


st.header("Why is this problem important?")

st.markdown("""
    <div style="
        background-color: #736D6C;
        border-radius: 20px;
        padding: 0.75rem 1rem;
        font-size: 1rem;
        color: white;
            ">
    Unregistered wells can lead to over-extraction of groundwater, which in turn can cause land subsidence, reduced water quality, and depletion of water resources.\
             By identifying and monitoring these wells, governments struggling with water management can better manage water resources and mitigate potential environmental impacts.
    <br><br>More specifically, in the Segura River Basin, water scarcity is a significant issue, with the sustainable rate of water extraction from the Segura Basin aquifers\
             being exceeded 3- or 4-fold. Moreover, unregistered wells - which are estimated to account for around 45% of all extracted ground water\
             in the area -contribute to the over-extraction of groundwater. By using Well-D, we aim to help identify these wells and support\
              sustainable water management in the region.
    <br><br>The Water Authorities’ inability to stop this activity is due to lack of instruments for water management and law enforcement.\
              In some cases, there is also a lack of political willingness to allow the strict application of the law, which would discourage the ever-increasing illegal use.\
                Nevertheless, the main reason that water is abstracted illegally lies in the huge profits that are derived from its use (irrigation farming, urban development,\
              tourism). Because of this, river basin authorities are under great economic and political pressure, especially in those areas where the problem is more severe\
              (Andalusia, Castilla-La Mancha, Murcia, Valencia) resulting in illegal water use not being effectively tackled.
    <br><br>Thus, Well-D is designed to provide a cost-effective and scalable solution for detecting unregistered wells, enabling authorities to take informed actions\
              to manage water resources sustainably - even at a more central level of the Spanish central government, bypassing traditional limitations of relying on local enforcement.
    </div>
""", unsafe_allow_html=True)

geojson_path = "DHSegura.geojson"
gpkg_path = "well_datapoints.gpkg"


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
    # filter out inactive wells directly in the query
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


# --- Load data ---
geojson_data, gpkg_geojson = None, None
bounds_list = []

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

# --- Sidebar ---
st.sidebar.title("Map Layers")

show_geojson = st.sidebar.toggle("DHSegura boundary", value=True, disabled=geojson_data is None)
show_gpkg = st.sidebar.toggle("Well datapoints", value=True, disabled=gpkg_geojson is None)
st.sidebar.divider()
st.sidebar.subheader("Legend")
if geojson_data:
    st.sidebar.markdown(" 🔵 Segura Basin Boundary")
if gpkg_geojson:
    st.sidebar.markdown(" 🟠 Registered Well Datapoints")

# --- Render ---
view_state = compute_view_from_bounds(bounds_list) if bounds_list else pdk.ViewState(
    latitude=0, longitude=0, zoom=2
)



@st.fragment
def render_map(show_geojson, show_gpkg, view_state):
    layers = []
    if geojson_data and show_geojson:
        layers.append(pdk.Layer(
            "GeoJsonLayer", geojson_data,
            pickable=False, stroked=True, filled=True,
            get_fill_color=[0, 128, 128, 80],
            get_line_color=[0, 80, 160, 200],
            line_width_min_pixels=1,
        ))
    if gpkg_geojson and show_gpkg:
        layers.append(pdk.Layer(
            "GeoJsonLayer", gpkg_geojson,
            pickable=True, stroked=True, filled=True,
            get_fill_color=[245, 95, 116, 180],
            get_line_color=[200, 60, 0, 220],
            point_radius_min_pixels=4,
            line_width_min_pixels=1,
        ))
    if layers:
        st.pydeck_chart(pdk.Deck(
            layers=layers,
            initial_view_state=view_state,
            map_provider="carto",
            tooltip={"text": "📍 {Municipio}\n🏔 Elevation: {COTA_msnm}m\n💧 Use: {Usos_Agua}\n🔩 Type: {Naturaleza}"},
        ))
    else:
        st.info("All layers are hidden. Toggle a layer in the sidebar to show it.")

st.space("small")
render_map(show_geojson, show_gpkg, view_state)