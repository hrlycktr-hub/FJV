import streamlit as st
import pandas as pd
from data_hentning import hent_alle_data
from logik import get_faktisk_bio, beregn_aftag_nu

st.set_page_config(page_title="Skuldelev V1", layout="wide")

# Initialisering af Session State
if 'init' not in st.session_state:
    st.session_state.tank_pct = 50
    st.session_state.basis = 1260
    st.session_state.respons = 45
    st.session_state.init = True

# Hent data
el_df, vejr_df = hent_alle_data()

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Indstillinger")
    gas_valg = st.radio("Gaskedel (kW)", [800, 1600])
    st.slider("Aktuel Tank %", 0, 100, key='tank_pct')
    st.number_input("Basis (kW)", key='basis')
    st.number_input("Respons", key='respons')

# --- PROGNOSE LOOP ---
# (Her bruger vi funktionerne fra logik.py til at bygge df_prog)
st.title("Skuldelev Drifts-Agent ⚡")
st.write("Appen er nu modulariseret!")

# Her indsætter vi graferne som før...
