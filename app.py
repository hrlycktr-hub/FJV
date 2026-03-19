import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- 1. KONFIGURATION & FUNKTIONER ---
TANK_A_MAX_MWH = 70.0  
ELKEDEL_MW = 2.0       
MOTOR_VARME_MW = 1.2   

# Vi definerer denne heroppe, så den virker i hele appen
def get_bio(p):
    if p <= 30: return 1000
    elif p <= 40: return 900
    elif p <= 50: return 800
    elif p <= 60: return 700
    elif p <= 90: return 600
    return 0

st.set_page_config(page_title="Skuldelev Drift & mFRR", page_icon="⚡", layout="wide")
st.title("Skuldelev Drifts-Agent ⚡")

# --- 2. OVERORDNET STATUS & AFTAG ---
st.header("📍 1. Aktuel Status")
with st.container(border=True):
    col1, col2, col3 = st.columns(3)
    with col1:
        tank_pct = st.number_input("Tank A fyldning (%)", 0, 100, 50)
        tank_mwh = (tank_pct / 100) * TANK_A_MAX_MWH
    with col2:
        tank_b_mwh = st.number_input("Tank B (MWh)", 0.0, 80.0, 10.0)
    with col3:
        aftag_nu = st.number_input("Aktuelt Aftag (kW)", 0, 3000, 1000)

# HENT SPOTPRIS
@st.cache_data(ttl=300)
def hent_spotpris():
    try:
        url = "https://api.energidataservice.dk/dataset/Elspotprices?limit=1&filter={'PriceArea':['DK2']}&sort=HourDK desc"
        res = requests.get(url).json()
        return res['records'][0]['SpotPriceDKK']
    except: return 200.0

spotpris = hent_spotpris()
st.info(f"**Aktuel Spotpris (DK2):** {round(spotpris, 2)} kr/MWh")

# --- 3. ELKEDEL SEKTION (Ned-regulering) ---
st.header("🔌 2. mFRR Elkedel (Ned)")
with st.container(border=True):
    col_el1, col_el2 = st.columns(2)
    with col_el1:
        bud_elkedel = st.number_input("Bud Elkedel (kr/MWh)", value=150, key="el_bud")
    with col_el2:
        chance_el = "Høj (>70%)" if bud_elkedel > spotpris + 40 else "Middel"
        st.write(f"**Aktiverings-chance:** {chance_el}")
        
    if st.button("Beregn Elkedel-scenarie"):
        bio = get_bio(tank_pct)
        netto_el = (bio + (ELKEDEL_MW * 1000)) - aftag_nu
        
        if netto_el > 0:
            timer = (TANK_A_MAX_MWH - tank_mwh) / (netto_el / 1000)
            st.error(f"Ved aktivering: Tank A rammer 100% om {round(timer, 1)} timer.")
        else:
            st.success("Tanken tømmes selv med elkedel-kørsel.")

# --- 4. MOTOR SEKTION (Op-regulering) ---
st.header("⚙️ 3. mFRR Motor (Op)")
with st.container(border=True):
    col_mot1, col_mot2 = st.columns(2)
    with col_mot1:
        bud_motor = st.number_input("Bud Motor (kr/MWh)", value=450, key="mot_bud")
    with col_mot2:
        chance_mot = "Høj (>70%)" if bud_motor < spotpris - 100 else "Middel"
        st.write(f"**Aktiverings-chance:** {chance_mot}")
        
    if st.button("Beregn Motor-scenarie"):
        bio = get_bio(tank_pct)
        netto_mot = (bio + (MOTOR_VARME_MW * 1000)) - aftag_nu
        
        if netto_mot > 0:
            timer = (TANK_A_MAX_MWH - tank_mwh) / (netto_mot / 1000)
            st.warning(f"Ved aktivering: Tank A rammer 100% om {round(timer, 1)} timer.")
        else:
            st.success("Tanken tømmes stadig med motoren kørende.")

# --- FODNOTE ---
st.divider()
st.caption(f"Biokedel last jvf. trin-automatik: {get_bio(tank_pct)} kW")
