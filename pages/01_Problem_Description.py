# pages/01_Problem_Description.py
import streamlit as st

st.set_page_config(page_title="Problem Description", layout="wide")

st.title("The Segura River Basin — Problem Description")
st.caption("Confederación Hidrográfica del Segura (CHS)")

st.divider()

# --- Overview ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Basin area", "18,870 km²")
col2.metric("Avg. rainfall", "385 mm/year")
col3.metric("Irrigated surface", "269,000 ha")
col4.metric("Aquifer bodies", "63")

st.divider()

# --- Geography ---
st.subheader("Geography & Climate")
st.markdown("""
The Segura River originates in the mountains of Jaén (Andalucía) and flows southeast through
semiarid lands before discharging into the Mediterranean Sea near Alicante. The basin spans
four autonomous communities — Murcia (60%), Castilla-La Mancha (25%), Andalucía (9%), and
Comunitat Valenciana (5%) — and covers nearly 19,000 km².

The basin is characterised by significant topographic variation: mountains in the northwest
frequently exceed 1,000 m, while coastal plains and river valleys sit below 200 m. This
variation drives strong climatic contrasts, from severe droughts and heat waves to torrential
rainfall events. Average annual precipitation is around 385 mm, with two-thirds typically
falling in autumn, but with extreme spatial and temporal variability across the basin.
""")

# --- Hydrogeology ---
st.subheader("Hydrogeology")
st.markdown("""
The basin has a complex hydrogeological structure, with 63 officially recognised groundwater
bodies managed by the Confederación Hidrográfica del Segura (CHS). Two main aquifer types
are present: **carbonate aquifers** (limestone and dolomite, ranging from Triassic–Jurassic
to Pliocene–Quaternary age) and **detrital aquifers** (gravel, sand, silt, and calcarenites).
Depending on local geology, these units behave either as independent systems or as
hydraulically connected networks.

Aquifer recharge occurs primarily through rainwater infiltration, river-aquifer interaction,
and irrigation return flows. Groundwater is particularly critical in coastal areas where
surface water resources are scarce or absent.
""")

# --- Water scarcity ---
st.subheader("Water Scarcity & Demand")

st.markdown("""
The Segura basin is one of the most water-scarce regions in Europe. Total average renewable
resources amount to approximately 1,400 Mm³/year, drawn from surface water, groundwater,
the Tagus-Segura Transfer (TST), wastewater reuse, and desalination — yet these resources
are insufficient to meet authorised demands.
""")

st.markdown("""
<div style="background-color: #c0392b; border-radius: 6px; padding: 0.85rem 1.1rem; color: white;">
    <strong>⚠️ Structural water deficit</strong><br>
    The basin faces a structural deficit of at least 400 Hm³ per year, driven by intensive
    agricultural expansion, population growth, and tourism pressure, compounded by a long-term
    decline in rainfall.
</div>
""", unsafe_allow_html=True)

st.markdown("")

col1, col2 = st.columns(2)

with col1:
    st.markdown("**Water sources (Hm³/year)**")
    st.markdown("""
    - Surface water: 640
    - Tagus-Segura Transfer: 540
    - Groundwater: 220
    - Wastewater reuse: 110
    """)

with col2:
    st.markdown("**Key demand drivers**")
    st.markdown("""
    - Agriculture: ~269,000 ha of irrigated land
    - Urban supply: ~2 million permanent residents (3M+ in summer)
    - Industry & tourism along the Mediterranean coast
    """)

# --- Groundwater overexploitation ---
st.subheader("Groundwater Overexploitation")

st.markdown("""
Intensive agricultural expansion since the 1960s has led to severe groundwater overexploitation
across the basin. Studies estimate cumulative overextraction of approximately 500 Hm³ between
1960 and 2021, causing progressive piezometric drawdown and aquifer depletion in multiple
groundwater bodies.
""")

st.markdown("""
<div style="background-color: #e67e22; border-radius: 6px; padding: 0.85rem 1.1rem; color: white;">
    <strong>🌍 Ground subsidence risk</strong><br>
    Sustained groundwater extraction leads to compaction of aquifer sediments, causing land
    subsidence — a key focus of this dashboard. Monitoring well data combined with remote
    sensing allows spatial analysis of subsidence patterns and their relationship to
    extraction rates across the basin.
</div>
""", unsafe_allow_html=True)

st.markdown("")

# --- Dashboard context ---
st.subheader("About This Dashboard")
st.markdown("""
This dashboard visualises the hydrogeological monitoring network of the DHSegura basin,
including the locations and attributes of active wells across the region. It is intended
as an analytical tool to support the study of groundwater dynamics, extraction patterns,
and their relationship to ground subsidence.

Data is sourced from the Confederación Hidrográfica del Segura (CHS) and covers active
monitoring and extraction wells across the basin boundary.
""")