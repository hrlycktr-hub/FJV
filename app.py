import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import numpy as np

# --- 1. SETUP & HUKOMMELSE ---
if 'tank_pct' not in st.session_state: st.session_state.tank_pct = 44
if 'basis' not in st.session_state: st.session_state.basis = 1260
if 'respons' not in st.session_state: st.session_state.respons = 45
if 'bud_el' not in st.session_state: st.session_state.bud_el = 50.0
if 'bud_mo' not in st.session_state: st.session_state.bud_mo = 800.0
if 'temp_off' not in st.session_state: st.session_state.temp_off = 0.0
if 'vind_off' not in st.session_state: st.session_state.vind_off = 0.0

TANK_A_MAX_MWH = 70.0  

def get_bio_produktion(tank_pct):
    if tank_pct <= 30: return 1000
    elif tank_pct <= 60: return 750
    elif tank_pct <= 90: return 600
    return 0

st.set_page_config(page_title="Skuldelev V1", layout="wide")
st.title("Skuldelev Drifts-Agent ⚡")

# --- 2. DATA-HENTNING ---
@st.cache_data(ttl=600)
def hent_data():
    el_df, vejr_df = pd.DataFrame(), pd.DataFrame()
    try:
        url = "https://api.energidataservice.dk/dataset/DayAheadPrices?limit=100&filter={'PriceArea':['DK2']}"
        r = requests.get(url, timeout=5).json()['records']
        el_df = pd.DataFrame(r)
        el_df['Tid'] = pd.to_datetime(el_df['HourDK']).dt.tz_localize(None)
        el_df = el_df.sort_values('Tid').tail(48)
    except:
        tider = [datetime.now().replace(minute=0, second=0) + timedelta(hours=i) for i in range(48)]
        el_df = pd.DataFrame({'Tid': tider, 'SpotPriceDKK': 500.0})

    try:
        url_v = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=55.79&lon=12.02"
        r_v = requests.get(url_v, headers={'User-Agent': 'SkuldelevV1/1.5'}, timeout=5).json()
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

# --- 3. SIDEBAR: KONTROL & INFO ---
with st.sidebar:
    st.header("SCADA Trimning")
    
    # Her og nu effekt beregning
    nu_t = vejr_df['Temp'].iloc[0] + st.session_state.temp_off
    nu_v = max(0, vejr_df['Vind'].iloc[0] + st.session_state.vind_off)
    tf = max(0, (15 - nu_t) * 0.8)
    vf = 3.0 if nu_v < 3 else min(10, 3 + (nu_v - 3) * 0.77)
    effekt_nu = st.session_state.basis + (tf + vf - 10.3) * st.session_state.respons
    
    st.metric("Beregnet Effekt NU", f"{int(effekt_nu)} kW")
    st.caption(f"Aktuelt vejr: {round(nu_t,1)}°C / {round(nu_v,1)} m/s")
    
    st.divider()
    st.session_state.basis = st.number_input("Basis (kW)", value=st.session_state.basis)
    st.session_state.respons = st.number_input("Respons", value=st.session_state.respons)
    
    st.divider()
    st.subheader("mFRR Bud & Info")
    st.session_state.bud_el = st.number_input("Bud Elkedel", value=float(st.session_state.bud_el))
    t_kedel = len(el_df[el_df['SpotPriceDKK'] <= st.session_state.bud_el])
    st.info(f"💡 Kedel: {t_kedel} timer")
    
    st.session_state.bud_mo = st.number_input("Bud Motor", value=float(st.session_state.bud_mo))
    t_motor = len(el_df[el_df['SpotPriceDKK'] >= st.session_state.bud_mo])
    st.warning(f"💡 Motor: {t_motor} timer")

    st.divider()
    st.subheader("Vejr & Tank")
    st.session_state.temp_off = st.slider("Temp Offset", -5.0, 5.0, st.session_state.temp_off)
    st.session_state.vind_off = st.slider("Vind Offset", -10.0, 10.0, st.session_state.vind_off)
    st.session_state.tank_pct = st.slider("Aktuel Tank %", 0, 100, st.session_state.tank_pct)

# --- 4. DRIFTS-PROGNOSE (RENSER TID TIL 24T) ---
prog = vejr_df.copy()
# TVUNGET 24-TIMERS FORMAT TIL GRAFERNE
prog['Tid_24h'] = prog['Tid'].dt.strftime('%H:00')
tank_val = (st.session_state.tank_pct / 100) * TANK_A_MAX_MWH
b_log, a_log = [], []

for _, row in prog.iterrows():
    cur_t = row['Temp'] + st.session_state.temp_off
    cur_v = max(0, row['Vind'] + st.session_state.vind_off)
    tf = max(0, (15 - cur_t) * 0.8)
    vf = 3.0 if cur_v < 3 else min(10, 3 + (cur_v - 3) * 0.77)
    aftag = st.session_state.basis + (tf + vf - 10.3) * st.session_state.respons
    a_log.append(aftag)
    
    bio = get_bio_produktion((tank_val/TANK_A_MAX_MWH)*100)
    tank_val = max(0, min(TANK_A_MAX_MWH, tank_val + (bio - aftag)/1000))
    b_log.append(tank_val)

prog['Tank_MWh'], prog['Aftag_kW'] = b_log, a_log

# --- 5. VISNING ---
st.subheader("Elpriser & Budlinjer (24-timers visning)")
el_plot = pd.DataFrame({
    'Tid': el_df['Tid'].dt.strftime('%H:00'),
    'Spotpris': el_df['SpotPriceDKK'].values,
    'Bud Elkedel': [st.session_state.bud_el] * len(el_df),
    'Bud Motor': [st.session_state.bud_mo] * len(el_df)
}).set_index('Tid')
st.line_chart(el_plot, height=250)

st.divider()
c1, c2 = st.columns(2)
with c1:
    st.subheader("Forventet Aftag (kW)")
    st.line_chart(prog.set_index('Tid_24h')['Aftag_kW'], color="#FF4B4B")
with c2:
    st.subheader("Tank A Prognose (MWh)")
    st.line_chart(prog.set_index('Tid_24h')['Tank_MWh'], color="#0072B2")
