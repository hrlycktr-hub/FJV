import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import numpy as np

# --- 1. KONFIGURATION & HUKOMMELSE ---
if 'tank_pct' not in st.session_state: st.session_state.tank_pct = 44
if 'basis' not in st.session_state: st.session_state.basis = 1260
if 'respons' not in st.session_state: st.session_state.respons = 45
if 'bud_el' not in st.session_state: st.session_state.bud_el = 50.0
if 'bud_mo' not in st.session_state: st.session_state.bud_mo = 800.0

TANK_A_MAX_MWH = 70.0  

def get_bio_produktion(tank_pct):
    if tank_pct <= 30: return 1000
    elif tank_pct <= 60: return 750
    elif tank_pct <= 90: return 600
    return 0

st.set_page_config(page_title="Skuldelev Drifts-Agent", layout="wide")
st.title("Skuldelev Drifts-Agent ⚡")

# --- 2. DATA-HENTNING ---
@st.cache_data(ttl=600)
def hent_data():
    el_df = pd.DataFrame()
    try:
        url = "https://api.energidataservice.dk/dataset/DayAheadPrices?limit=50&filter={'PriceArea':['DK2']}"
        r = requests.get(url, timeout=5).json()['records']
        el_df = pd.DataFrame(r)
        t_col = 'HourDK' if 'HourDK' in el_df.columns else 'HourUTC'
        el_df['Tid'] = pd.to_datetime(el_df[t_col]).dt.tz_localize(None)
        el_df = el_df.sort_values('Tid')
    except:
        tider = [datetime.now() + timedelta(hours=i) for i in range(48)]
        el_df = pd.DataFrame({'Tid': tider, 'SpotPriceDKK': 500 + 200 * np.sin(np.linspace(0, 4*np.pi, 48))})

    try:
        url_v = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=55.79&lon=12.02"
        r_v = requests.get(url_v, headers={'User-Agent': 'SkuldelevApp/12.0'}, timeout=5).json()
        rows = []
        for entry in r_v['properties']['timeseries'][:48]:
            rows.append({
                'Tid': pd.to_datetime(entry['time']).tz_convert('Europe/Copenhagen').tz_localize(None),
                'Temp': entry['data']['instant']['details']['air_temperature'],
                'Vind': entry['data']['instant']['details']['wind_speed']
            })
        vejr_df = pd.DataFrame(rows)
    except:
        vejr_df = pd.DataFrame({'Tid': el_df['Tid'], 'Temp': [7.0]*48, 'Vind': [5.0]*48})
    
    return el_df, vejr_df

el_df, vejr_df = hent_data()

# --- 3. GLATNING AF BEREGNING (Fjerner savtakker) ---
prog = vejr_df.copy()
# Vi glatter temperatur og vind for at undgå voldsomme hop i grafen
prog['Temp_Smooth'] = prog['Temp'].rolling(window=3, center=True).mean().fillna(prog['Temp'])
prog['Tidspunkt'] = prog['Tid'].dt.strftime('%H:%M')

beholdning = (st.session_state.tank_pct / 100) * TANK_A_MAX_MWH
b_log, a_log = [], []

for _, row in prog.iterrows():
    # Beregn aftag baseret på de glattede værdier
    t_t = max(0, (15 - row['Temp_Smooth']) * 0.8)
    v_t = 3.0 if row['Vind'] < 3 else min(10, 3 + (row['Vind'] - 3) * 0.77)
    aftag = st.session_state.basis + (t_t + v_t - 10.3) * st.session_state.respons
    a_log.append(aftag)
    
    bio = get_bio_produktion((beholdning/TANK_A_MAX_MWH)*100)
    # Vi akkumulerer ændringen mere roligt
    beholdning = max(2, min(TANK_A_MAX_MWH - 2, beholdning + (bio - aftag)/1000))
    b_log.append(beholdning)

prog['Tank_MWh'], prog['Aftag_kW'] = b_log, a_log

# --- 4. VISNING ---
st.header("mFRR Overblik & Elpriser")
el_plot = pd.DataFrame({
    'Tid': el_df['Tid'].dt.strftime('%d/%m %H:%M'),
    'Spotpris': el_df['SpotPriceDKK'].values,
    'Bud_Elkedel': [st.session_state.bud_el] * len(el_df),
    'Bud_Motor': [st.session_state.bud_mo] * len(el_df)
}).set_index('Tid')
st.line_chart(el_plot, height=250)

st.divider()
c1, c2 = st.columns(2)
with c1:
    st.subheader("Forventet Aftag (kW)")
    # Vi bruger st.line_chart i stedet for area for at få en renere linje
    st.line_chart(prog.set_index('Tidspunkt')['Aftag_kW'], color="#FF4B4B")
with c2:
    st.subheader("Tank A Prognose (MWh)")
    # Vi fjerner index-navnet for at gøre aksen renere
    st.line_chart(prog.set_index('Tidspunkt')['Tank_MWh'], color="#0072B2")

# --- SIDEBAR ---
with st.sidebar:
    st.header("Drifts-kontrol")
    st.session_state.tank_pct = st.slider("Aktuel Tank %", 0, 100, st.session_state.tank_pct)
    st.session_state.bud_el = st.number_input("Bud Elkedel", value=float(st.session_state.bud_el))
    st.session_state.bud_mo = st.number_input("Bud Motor", value=float(st.session_state.bud_mo))
    st.divider()
    st.session_state.basis = st.number_input("Basis kW", value=st.session_state.basis)
    st.session_state.respons = st.number_input("Respons", value=st.session_state.respons)
