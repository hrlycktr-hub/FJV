import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import numpy as np

# --- 1. SESSION STATE (HUKOMMELSE) ---
if 'tank_pct' not in st.session_state: st.session_state.tank_pct = 44
if 'basis' not in st.session_state: st.session_state.basis = 1260
if 'respons' not in st.session_state: st.session_state.respons = 45
if 'bud_elkedel' not in st.session_state: st.session_state.bud_elkedel = 50.0
if 'bud_motor' not in st.session_state: st.session_state.bud_motor = 800.0

TANK_A_MAX_MWH = 70.0  
LAT, LON = 55.79, 12.02

def get_bio_produktion(tank_pct):
    if tank_pct <= 30: return 1000
    elif tank_pct <= 60: return 750
    elif tank_pct <= 90: return 600
    return 0

st.set_page_config(page_title="Skuldelev Drifts-Agent", layout="wide")
st.title("Skuldelev Drifts-Agent ⚡")

# --- 2. DATA-HENTNING (OPDATERET TIL 2026 ENDPOINT) ---
@st.cache_data(ttl=300)
def hent_data(brug_testdata=False):
    el_res, vejr_res = pd.DataFrame(), pd.DataFrame()
    
    if not brug_testdata:
        try:
            # NYT 2026 ENDPOINT: DayAheadPrices i stedet for Elspotprices
            url_el = "https://api.energidataservice.dk/dataset/DayAheadPrices?limit=100&filter={'PriceArea':['DK2']}"
            r_el = requests.get(url_el, timeout=5).json()['records']
            el_res = pd.DataFrame(r_el)
            # Kolonnen hedder typisk HourDK eller HourUTC
            t_col = 'HourDK' if 'HourDK' in el_res.columns else 'HourUTC'
            el_res['Tid'] = pd.to_datetime(el_res[t_col]).dt.tz_localize(None)
            el_res = el_res.sort_values('Tid')
        except Exception as e:
            st.sidebar.error(f"Kunne ikke hente live-elpriser: {e}")

    # Hvis API fejler eller vi har valgt testdata
    if el_res.empty:
        tider = [datetime.now() + timedelta(hours=i) for i in range(48)]
        # Laver en realistisk svingende kurve (nat = billig, dag = dyr)
        priser = 400 + 300 * np.sin(np.linspace(0, 4*np.pi, 48)) 
        el_res = pd.DataFrame({'Tid': tider, 'SpotPriceDKK': priser})

    # Vejr data (met.no er normalt stabil)
    try:
        h = {'User-Agent': 'SkuldelevApp/9.0'}
        url_v = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={LAT}&lon={LON}"
        r_v = requests.get(url_v, headers=h, timeout=5).json()
        rows = []
        for entry in r_v['properties']['timeseries'][:48]:
            rows.append({
                'Tid': pd.to_datetime(entry['time']).tz_convert('Europe/Copenhagen').tz_localize(None),
                'Temp': entry['data']['instant']['details']['air_temperature'],
                'Vind': entry['data']['instant']['details']['wind_speed']
            })
        vejr_res = pd.DataFrame(rows)
    except:
        vejr_res = pd.DataFrame({'Tid': el_res['Tid'], 'Temp': [7.0]*48, 'Vind': [5.0]*48})
    
    return el_res, vejr_res

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header("Drifts-indstillinger")
    st.session_state.tank_pct = st.slider("Aktuel Tank %", 0, 100, st.session_state.tank_pct)
    st.session_state.bud_elkedel = st.number_input("Budpris Elkedel (kr)", value=st.session_state.bud_elkedel)
    st.session_state.bud_motor = st.number_input("Budpris Motor (kr)", value=st.session_state.bud_motor)
    st.divider()
    st.session_state.basis = st.number_input("SCADA Basis kW", value=st.session_state.basis)
    st.session_state.respons = st.number_input("SCADA Respons", value=st.session_state.respons)
    st.divider()
    test_mode = st.checkbox("Brug TEST-DATA (hvis API er nede)", value=False)

el_df, vejr_df = hent_data(test_mode)

# --- 4. BEREGNING AF PROGNOSE ---
prog = vejr_df.copy()
prog['Tidspunkt'] = prog['Tid'].dt.strftime('%H:%M')
beholdning = (st.session_state.tank_pct / 100) * TANK_A_MAX_MWH
b_log, a_log = [], []

for _, row in prog.iterrows():
    t_t = max(0, (15 - row['Temp']) * 0.8)
    v_t = 3.0 if row['Vind'] < 3 else min(10, 3 + (row['Vind'] - 3) * 0.77)
    aftag = st.session_state.basis + (t_t + v_t - 10.3) * st.session_state.respons
    a_log.append(aftag)
    bio = get_bio_produktion((beholdning/TANK_A_MAX_MWH)*100)
    beholdning = max(0, min(TANK_A_MAX_MWH, beholdning + (bio - aftag)/1000))
    b_log.append(beholdning)

prog['Tank_MWh'], prog['Aftag_kW'] = b_log, a_log

# --- 5. VISNING ---
st.header("mFRR Strategi & Elpriser (DK2)")
c1, c2, c3 = st.columns(3)

k_t = len(el_df[el_df['SpotPriceDKK'] <= st.session_state.bud_elkedel])
m_t = len(el_df[el_df['SpotPriceDKK'] >= st.session_state.bud_motor])

c1.metric("Elkedel Vindue", f"{k_t} timer")
c2.metric("Motor Vindue", f"{m_t} timer")
c3.metric("Spotpris Nu", f"{round(el_df['SpotPriceDKK'].iloc[0])} kr")

# Graf med budlinjer
el_plot = pd.DataFrame({
    'Tid': el_df['Tid'].dt.strftime('%d/%m %H:%M'),
    'Spotpris': el_df['SpotPriceDKK'].values,
    'Bud_Elkedel': [float(st.session_state.bud_elkedel)] * len(el_df),
    'Bud_Motor': [float(st.session_state.bud_motor)] * len(el_df)
}).set_index('Tid')

st.line_chart(el_plot)

st.divider()
col1, col2 = st.columns(2)
with col1:
    st.subheader("Forventet Aftag (kW)")
    st.line_chart(prog.set_index('Tidspunkt')['Aftag_kW'])
with col2:
    st.subheader("Tank A Prognose (MWh)")
    st.line_chart(prog.set_index('Tidspunkt')['Tank_MWh'])
