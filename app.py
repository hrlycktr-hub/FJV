import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- KONFIGURATION ---
TANK_A_STOP = 70
ELKEDEL_MW = 2.0

st.set_page_config(page_title="Skuldelev mFRR Pro", page_icon="📊")
st.title("Skuldelev Drifts-Agent ⚡")

# --- 1. DATA OPSLAG (mFRR HISTORIK) ---
@st.cache_data(ttl=3600)
def hent_mfrr_tendens():
    # Her simulerer vi opslag af marginalpriser for DK2
    # I en fuld version ville vi trække 'MfrrReservesDk2' fra Energinet API
    return {"ned": 185.0, "op": 450.0} # Typiske marginalpriser i DKK/MWh

mfrr_data = hent_mfrr_tendens()

# --- 2. INPUT ---
st.header("1. Status & Bud")
col1, col2, col3 = st.columns(3)
with col1:
    tank_a = st.number_input("Tank A (MWh)", 0.0, 80.0, 35.0)
with col2:
    aftag_nu = st.number_input("Aktuelt Aftag (kW)", 0, 3000, 1000)
with col3:
    bud_pris = st.number_input("Dit mFRR Bud (kr/MWh)", value=150)

bud_type = st.selectbox("Bud-type", ["Elkedel (Ned-regulering)", "Motor (Op-regulering)"])

# --- 3. CHANCE INDIKATOR ---
st.header("2. Sandsynlighed for aktivering")

def beregn_chance(pris, type, data):
    nu_time = datetime.now().hour
    score = 50 # Start-score (50%)
    
    if "Elkedel" in type:
        # Elkedel vinder hvis buddet er HØJT (man vil betale meget for strømmen/modtage lidt)
        # eller hvis spotprisen er meget lav.
        if pris >= data["ned"]: score += 20
        if 11 <= nu_time <= 15: score += 15 # Sol-timer
    else:
        # Motor vinder hvis buddet er LAVT (man er billig produktion)
        if pris <= data["op"]: score += 20
        if nu_time in [7, 8, 17, 18]: score += 20 # Peak-timer
    
    return min(score, 95) # Max 95% chance

chance_pct = beregn_chance(bud_pris, bud_type, mfrr_data)

# Visning af chance med farve
if chance_pct > 70:
    st.success(f"🔥 HØJ CHANCE ({chance_pct}%): Dit bud er konkurrencedygtigt i forhold til markedet.")
elif chance_pct > 40:
    st.warning(f"⚖️ MIDDEL CHANCE ({chance_pct}%): Du ligger i det grå felt. Hold øje med Centrica.")
else:
    st.error(f"❄️ LAV CHANCE ({chance_pct}%): Andre værker er sandsynligvis billigere lige nu.")

# --- 4. DRIFTS-PROGNOSE ---
if st.button("GENERÉR PROGNOSE", type="primary"):
    # Beregn biokedel last (din logik)
    pct_fyldt = (tank_a / TANK_A_STOP) * 100
    if pct_fyldt <= 30: bio_kw = 1000
    elif pct_fyldt <= 40: bio_kw = 900
    elif pct_fyldt <= 50: bio_kw = 800
    elif pct_fyldt <= 60: bio_kw = 700
    elif pct_fyldt <= 90: bio_kw = 600
    else: bio_kw = 0
    
    netto_normal = bio_kw - aftag_nu
    
    st.divider()
    
    # SCENARIE: HVIS DU BLIVER AKTIVERET
    st.subheader("Scenarie: Ved aktivering")
    if "Elkedel" in bud_type:
        netto_aktiv = netto_normal + (ELKEDEL_MW * 1000)
        if netto_aktiv > 0:
            timer = (TANK_A_STOP - tank_a) / (netto_aktiv / 1000)
            st.write(f"⚠️ **ADVARSEL:** Ved elkedel-drift fyldes tanken på kun **{round(timer, 1)} timer**.")
    else:
        st.write("✅ Motoren kører. Biokedlen bør drosle ned til 600 kW.")

    # NORMAL PROGNOSE
    st.subheader("Normal drift (uden mFRR)")
    if netto_normal > 0:
        timer = (TANK_A_STOP - tank_a) / (netto_normal / 1000)
        st.write(f"Tanken er fuld om {round(timer, 1)} timer.")
    else:
        timer = tank_a / (abs(netto_normal) / 1000)
        st.write(f"Tanken er tom om {round(timer, 1)} timer.")
