import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import numpy as np

# --- 1. SESSION STATE ---
for key, val in {
    'tank_pct': 44, 'basis': 1260, 'respons': 45, 
    'bud_elkedel': 50.0, 'bud_motor': 800.0
}.items():
    if key not in st.session_state: st.session_state[key] = val

TANK_A_MAX_MWH = 70.0  
LAT, LON = 55.79, 12.02

def get_bio_produktion(tank_pct):
    if tank_pct <= 30: return 1000
    elif tank_pct <= 60: return 750
    elif tank_pct <= 90: return 600
    return 0

st.set_page_config(page_title="Skuldelev 48t", layout="wide")
st.title("Skuldelev Drifts-Agent ⚡")

# --- 2. DATA-HENTNING (REVIDERET) ---
@st.cache_data(ttl=300)
def hent_data():
    # Forsøg med det nye 'latest' endpoint fra Energi Data Service
    try:
        # Vi henter de sidste 100 datapunkter for DK2
        url = "https://api.energidataservice.dk/dataset/Elspotprices?limit=100&filter={'PriceArea':['DK2']}"
        r = requests.get(url, timeout=5).json()['records']
        df = pd.DataFrame(r)
        df['Tid'] = pd.to_datetime(df['HourDK']).dt.tz_localize(None)
        el_res = df.sort_values('Tid').tail(48)
    except:
        # Backup: Lav fiktive priser hvis API er nede
        st.error("Kunne ikke hente live-priser. Viser estimerede priser.")
        tider = [datetime.now() + timedelta(hours=i) for i in range(48)]
        priser = 400 + 200 * np.sin(np.linspace(0, 4*np.pi, 48)) # Svingende kurve
        el_res = pd.DataFrame({'Tid': tider, 'SpotPriceDKK': priser})

    # Vejr data
    try:
        url_v = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={LAT}&lon={LON}"
        r_v = requests.get(url_v, headers={'User-Agent': 'SkuldelevApp/8.0'}, timeout=5).json()
        rows = []
        for entry in r_v['properties']['timeseries'][:48]:
            rows.append({
                'Tid': pd.to_datetime(entry['time']).tz_convert('Europe/Copenhagen').tz_localize(None),
                'Temp': entry['data']['instant']['details']['air_temperature'],
                'Vind': entry['data']['instant']['details']['wind_speed']
            })
        vejr_res = pd.DataFrame(rows)
    except:
        vejr_res = pd.DataFrame({'Tid': el_res['Tid'], 'Temp': [7.0]*48, 'Vind': [0.5]*48})
    
    return el_res, vejr_res

el_df, vejr_df = hent_data()

# --- 3. BEREGNINGER ---
prog = vejr_df.copy()
prog['Tidspunkt'] = prog['Tid'].dt.strftime('%H:%M')
beholdning = (st.session_state.tank_pct / 100) * TANK_A_MAX_MWH
b_log, a_log = [], []

for _, row in prog.iterrows():
    # SCADA logik baseret på dine grafer
    t_t = max(0, (15 - row['Temp']) * 0.8)
    v_t = 3.0 if row['Vind'] < 3 else min(10, 3 + (row['Vind'] - 3) * 0.77)
    aftag = st.session_state.basis + (t_t + v_t - 10.3) * st.session_state.respons
    a_log.append(aftag)
    bio = get_bio_produktion((beholdning/TANK_A_MAX_MWH)*100)
    beholdning = max(0, min(TANK_A_MAX_MWH, beholdning + (bio - aftag)/1000))
    b_log.append(beholdning)

prog['Tank_MWh'], prog['Aftag_kW'] = b_log, a_log

# --- 4. VISNING (ELPRIS & BUD) ---
st.subheader("mFRR Strategi (DK2)")
c1, c2, c3 = st.columns(3)

# Filter priser i forhold til bud
kedel_timer = el_df[el_df['SpotPriceDKK'] <= st.session_state.bud_elkedel]
motor_timer = el_df[el_df['SpotPriceDKK'] >= st.session_state.bud_motor]

c1.metric("Elkedel timer", f"{len(kedel_timer)} t", f"Bud: {st.session_state.bud_elkedel} kr")
c2.metric("Motor timer", f"{len(motor_timer)} t", f"Bud: {st.session_state.bud_motor} kr")
c3.metric("Pris netop nu", f"{round(el_df['SpotPriceDKK'].iloc[-1])} kr")

# Graf med TVUNGNE linjer
el_plot = pd.DataFrame({
    'Tid': el_df['Tid'].dt.strftime('%H:%M'),
    'Spotpris': el_df['SpotPriceDKK'].values,
    'Bud Elkedel': [float(st.session_state.bud_elkedel)] * len(el_df),
    'Bud Motor': [float(st.session_state.bud_motor)] * len(el_df)
}).set_index('Tid')

st.line_chart(el_plot)

# --- 5. DRIFT ---
st.divider()
col_l, col_r = st.columns(2)
with col_l:
    st.subheader("Forventet Aftag (kW)")
    st.line_chart(prog.set_index('Tidspunkt')['Aftag_kW'])
with col_r:
    st.subheader("Tank A Prognose (MWh)")
    st.line_chart(prog.set_index('Tidspunkt')['Tank_MWh'])

# --- SIDEBAR INPUT ---
with st.sidebar:
    st.header("Konfiguration")
    st.session_state.tank_pct = st.slider("Aktuel Tank %", 0, 100, st.session_state.tank_pct)
    st.session_state.bud_elkedel = st.number_input("Budpris Elkedel", value=st.session_state.bud_elkedel)
    st.session_state.bud_motor = st.number_input("Budpris Motor", value=st.session_state.bud_motor)
    st.divider()
    st.session_state.basis = st.number_input("Basis kW", value=st.session_state.basis)
    st.session_state.respons = st.number_input("Respons", value=st.session_state.respons)
