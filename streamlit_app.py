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