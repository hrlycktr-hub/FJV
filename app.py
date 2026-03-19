import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- KONFIGURATION SKULDELEV ---
TANK_A_MAX_MWH = 70.0  # 100%
ELKEDEL_MW = 2.0       # Forbrug ved mFRR ned
MOTOR_VARME_MW = 1.2   # Varmebidrag fra motor ved mFRR op (anslået)

st.set_page_config(page_title="Skuldelev mFRR Pro", page_icon="📊")
st.title("Skuldelev Drifts-Agent ⚡")

# --- 1. STATUS & INPUT ---
st.header("1. Status på anlægget")
col1, col2, col3 = st.columns(3)

with col1:
    tank_pct = st.number_input("Tank A fyldning (%)", 0, 100, 50)
    tank_mwh = (tank_pct / 100) * TANK_A_MAX_MWH
with col2:
    aftag_nu = st.number_input("Aktuelt Aftag (kW)", 0, 3000, 1000)
with col3:
    bud_pris = st.number_input("mFRR Bud (kr/MWh)", value=150)

bud_type = st.selectbox("Aktiv type", ["Elkedel (Ned-regulering)", "Motor (Op-regulering)"])

# --- 2. LOGIK FOR BIOKEDEL ---
def beregn_bio_effekt(pct):
    if pct <= 30: return 1000
    if pct <= 40: return 900
    if pct <= 50: return 800
    if pct <= 60: return 700
    if pct <= 90: return 600
    return 0

bio_kw = beregn_bio_effekt(tank_pct)

# --- 3. mFRR CHANCE & PRIS ---
@st.cache_data(ttl=300)
def hent_spotpris():
    try:
        url = "https://api.energidataservice.dk/dataset/Elspotprices?limit=1&filter={'PriceArea':['DK2']}&sort=HourDK desc"
        res = requests.get(url).json()
        return res['records'][0]['SpotPriceDKK']
    except: return 200.0

spotpris = hent_spotpris()
st.metric("Aktuel Spotpris (DK2)", f"{round(spotpris, 2)} kr")

# Chance-logik
if "Elkedel" in bud_type:
    chance = "Høj (>70%)" if bud_pris > spotpris + 50 else "Middel"
else:
    chance = "Høj (>70%)" if bud_pris < spotpris - 50 else "Middel"

st.subheader(f"Sandsynlighed for aktivering: {chance}")

# --- 4. DRIFTS-PROGNOSE ---
if st.button("BEREGN PROGNOSE", type="primary"):
    netto_normal_kw = bio_kw - aftag_nu
    
    st.divider()
    st.write(f"### Prognose ved {bud_type}")
    
    # Her var fejlen - parenteserne er nu på plads:
    if "Elkedel" in bud_type:
        netto_aktiv_kw = netto_normal_kw + (ELKEDEL_MW * 1000)
    else:
        netto_aktiv_kw = netto_normal_kw + (MOTOR_VAR
