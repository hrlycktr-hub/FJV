import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# KONFIGURATION
TANK_A_STOP = 70    # MWh (Grænsen hvor SRO skifter)

st.set_page_config(page_title="Skuldelev Drift", page_icon="🔥")
st.title("Skuldelev Drifts-Agent ⚡")

# --- 1. INPUT FRA DIG ---
st.header("Status på værket")
col1, col2 = st.columns(3)
with col1:
    tank_a = st.number_input("Tank A (MWh)", 0.0, 80.0, 35.0)
with col2:
    tank_b = st.number_input("Tank B (MWh)", 0.0, 80.0, 10.0)
with col3:
    # HER INDTASTER DU HVAD BYEN BRUGER LIGE NU
    aftag_nu = st.number_input("Aktuelt Aftag (kW)", 0, 3000, 1150)

vejr = st.selectbox("Vejrudsigt", ["Overskyet", "Nogen sol", "Fuld sol"])

# --- 2. LOGIK FOR BIOKEDEL EFFEKT ---
def beregn_bio_effekt(mwh):
    pct = (mwh / TANK_A_STOP) * 100
    if pct <= 30: return 1000 # 100%
    if pct <= 40: return 900  # 90%
    if pct <= 50: return 800  # 80%
    if pct <= 60: return 700  # 70%
    if pct <= 90: return 600  # 60%
    return 0

if st.button("BEREGN PROGNOSE", type="primary"):
    nu_effekt = beregn_bio_effekt(tank_a)
    
    # Det faktiske overskud/underskud i tanken
    netto_kw = nu_effekt - aftag_nu
    
    st.divider()
    
    # STATUS VISNING
    col_a, col_b = st.columns(2)
    col_a.metric("Kedel Effekt", f"{nu_effekt} kW")
    col_b.metric("Byens Forbrug", f"{aftag_nu} kW")

    # --- 3. PROGNOSE LOGIK ---
    if netto_kw > 0:
        # Vi producerer mere end vi bruger -> Tanken fyldes
        rest_mwh = TANK_A_STOP - tank_a
        timer_til_stop = rest_mwh / (netto_kw / 1000)
        stop_tid = datetime.now() + timedelta(hours=timer_til_stop)
        
        st.warning(f"⚠️ **Tanken fyldes:** Du rammer 70 MWh om ca. **{round(timer_til_stop, 1)} timer**.")
        st.info(f"Forventet stop: **kl. {stop_tid.strftime('%H:%M')}**")
        
    elif netto_kw < 0:
        # Vi bruger mere end vi producerer -> Tanken tømmes
        timer_til_tom = tank_a / (abs(netto_kw) / 1000)
        tom_tid = datetime.now() + timedelta(hours=timer_til_tom)
        
        st.success(f"📉 **Tanken tømmes:** Med nuværende forbrug er Tank A tom om ca. **{round(timer_til_tom, 1)} timer**.")
        st.info(f"Forventet tom tank: **kl. {tom_tid.strftime('%H:%M')}**")
    else:
        st.info("⚖️ **Balance:** Kedlen leverer præcis det, byen bruger.")

    # TRIN-TABEL
    st.write("---")
    st.write("**Reference (Dine setpunkter):**")
    st.table(pd.DataFrame({
        "Tank A (%)": ["0-30%", "31-40%", "41-50%", "51-60%", "61-90%", ">90%"],
        "Effekt (kW)": [1000, 900, 800, 700, 600, 0]
    }))
