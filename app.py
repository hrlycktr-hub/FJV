import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# KONFIGURATION
BIO_MAX = 1000  
FORBRUG_SNIT = 1150 # kW (Dit gennemsnitlige aftag i Skuldelev)
TANK_A_STOP = 70    # MWh (Hvor SRO slår fra)

st.set_page_config(page_title="Skuldelev Drift", page_icon="🔥")
st.title("Skuldelev Drifts-Agent ⚡")

# INPUT
st.header("Status på værket")
col1, col2 = st.columns(2)
with col1:
    tank_a = st.number_input("Tank A (MWh)", 0.0, 80.0, 35.0)
with col2:
    tank_b = st.number_input("Tank B (MWh)", 0.0, 80.0, 10.0)

vejr = st.selectbox("Vejrudsigt", ["Overskyet", "Nogen sol", "Fuld sol"])

# LOGIK FOR EFFEKT BASERET PÅ DINE REGLER
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
    overskud_kw = nu_effekt - FORBRUG_SNIT # Kan være negativ hvis vi tømmer tanken
    
    st.divider()
    
    # 1. VIS AKTUEL STATUS
    st.subheader(f"Aktuel drift: {nu_effekt} kW")
    
    # 2. BEREGN TID TIL STOP (Hvis vi producerer mere end vi bruger)
    if overskud_kw > 0:
        rest_mwh = TANK_A_STOP - tank_a
        timer_til_stop = rest_mwh / (overskud_kw / 1000) # Omregn kW til MW
        stop_tidspunkt = datetime.now() + timedelta(hours=timer_til_stop)
        
        st.warning(f"⚠️ **Tank A fyldes:** Med nuværende last rammer du 70 MWh om ca. **{round(timer_til_stop, 1)} timer**.")
        st.info(f"Forventet stop-tidspunkt: **kl. {stop_tidspunkt.strftime('%H:%M')}**")
    elif nu_effekt == 0:
        st.success("Kedlen er stoppet.")
    else:
        st.success(f"✅ **Stabil drift:** Du bruger mere varme ({FORBRUG_SNIT} kW) end kedlen giver ({nu_effekt} kW). Tanken tømmes langsomt.")

    # 3. TRIN-TABEL (Som reference)
    st.write("---")
    st.write("**Dine faste setpunkter:**")
    data = {
        "Tank A (%)": ["0-30%", "31-40%", "41-50%", "51-60%", "61-90%", ">90%"],
        "Effekt": ["1000 kW", "900 kW", "800 kW", "700 kW", "600 kW", "0 kW"]
    }
    st.table(pd.DataFrame(data))
