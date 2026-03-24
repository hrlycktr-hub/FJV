import streamlit as st
import pandas as pd
import requests
import numpy as np
from datetime import datetime, timedelta
from scipy.interpolate import make_interp_spline

# --- 1. SESSION STATE ---
if 'init_done' not in st.session_state:
    st.session_state.tank_pct = 50
    st.session_state.basis = 1260
    st.session_state.respons = 45
    st.session_state.bud_el = 50.0
    st.session_state.bud_mo = 800.0
    st.session_state.temp_off = 0.0
    st.session_state.vind_off = 0.0
    st.session_state.max_elkedel = 2500
    st.session_state.max_motor = 1200
    st.session_state.max_bio = 1000
    st.session_state.gas_trin = 800 # Manuel indstilling (800 el. 1600)
    st.session_state.sidste_el_data = pd.DataFrame()
    st.session_state.opdateret_tid = "Afventer..."
    st.session_state.init_done = True

TANK_A_MAX_MWH = 50.4  

def get_faktisk_bio(tank_pct, max_bio_limit):
    if tank_pct <= 30: return max_bio_limit
    elif tank_pct <= 60: return max_bio_limit * 0.75
    elif tank_pct <= 90: return max_bio_limit * 0.60
    return 0

st.set_page_config(page_title="Skuldelev V1 - Gas Backup", layout="wide")

# --- 2. DATA-HENTNING ---
@st.cache_data(ttl=300)
def hent_ekstern_data():
    el_out, vejr_out, update_str = pd.DataFrame(), pd.DataFrame(), ""
    try:
        url = "https://api.energidataservice.dk/dataset/DayAheadPrices?limit=48&filter={'PriceArea':['DK2']}"
        r = requests.get(url, timeout=5).json()['records']
        el_out = pd.DataFrame(r).sort_values('HourDK').reset_index(drop=True)
        el_out['Tid'] = pd.to_datetime(el_out['HourDK']).dt.tz_localize(None)
        update_str = datetime.now().strftime("%H:%M:%S")
    except: pass
    try:
        url_v = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=55.79&lon=12.02"
        rv = requests.get(url_v, headers={'User-Agent': 'SkuldelevV1/5.0'}, timeout=5).json()
        rows = [{'Tid': pd.to_datetime(e['time']).tz_convert('Europe/Copenhagen').tz_localize(None),
                 'Temp': e['data']['instant']['details']['air_temperature'],
                 'Vind': e['data']['instant']['details']['wind_speed']} 
                for e in rv['properties']['timeseries'][:48]]
        vejr_out = pd.DataFrame(rows)
    except: pass
    return el_out, vejr_out, update_str

raw_el, raw_vejr, update_tid = hent_ekstern_data()
if not raw_el.empty:
    st.session_state.sidste_el_data = raw_el
    st.session_state.opdateret_tid = update_tid

el_df = st.session_state.sidste_el_data
if el_df.empty: el_df = pd.DataFrame({'Tid': [datetime.now()]*48, 'SpotPriceDKK': [500.0]*48})
vejr_df = raw_vejr
if vejr_df.empty: vejr_df = pd.DataFrame({'Tid': el_df['Tid'], 'Temp': [7.0]*48, 'Vind': [5.0]*48})

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Kontrolpanel")
    
    with st.container(border=True):
        st.subheader("🔥 Gaskedel (Backup)")
        st.radio("Manuelt Gas-trin (kW)", [800, 1600], key='gas_trin')
        st.caption("Starter ved 6 MWh, slukker ved 10 MWh")

    with st.container(border=True):
        st.subheader("📊 mFRR Bud")
        st.number_input("Bud Elkedel", key='bud_el')
        st.number_input("Bud Motor", key='bud_mo')
    
    with st.container(border=True):
        st.subheader("🔧 SCADA & Tank")
        st.number_input("Basis (kW)", key='basis')
        st.number_input("Respons", key='respons')
        st.slider("Aktuel Tank %", 0, 100, key='tank_pct')

# --- 4. PROGNOSE-BEREGNING MED GAS-LOGIK ---
tank_mwh_nu = (st.session_state.tank_pct / 100) * TANK_A_MAX_MWH
p_data = []
cur_tank = tank_mwh_nu
gas_aktiv = False

for i in range(len(vejr_df)):
    r_v = vejr_df.iloc[i]
    p_s = el_df.iloc[i]['SpotPriceDKK'] if i < len(el_df) else 500
    
    # Aftag
    t_c = r_v['Temp'] + st.session_state.temp_off
    v_c = max(0, r_v['Vind'] + st.session_state.vind_off)
    aftag = st.session_state.basis + (max(0,(15-t_c)*0.8) + (3.0 if v_c<3 else min(10,3+(v_c-3)*0.77)) - 10.3) * st.session_state.respons
    
    # Normal Produktion
    pct_nu = (cur_tank / TANK_A_MAX_MWH) * 100
    prod = get_faktisk_bio(pct_nu, st.session_state.max_bio)
    if p_s <= st.session_state.bud_el: prod += st.session_state.max_elkedel
    if p_s >= st.session_state.bud_mo: prod += st.session_state.max_motor
    
    # GAS-LOGIK
    if cur_tank <= 6.0: gas_aktiv = True
    if cur_tank >= 10.0: gas_aktiv = False
    
    nu_gas_effekt = 0
    if gas_aktiv:
        nu_gas_effekt = st.session_state.gas_trin
        prod += nu_gas_effekt
    
    cur_tank = max(0, min(TANK_A_MAX_MWH, cur_tank + (prod - aftag)/1000))
    
    p_data.append({
        'RealTime': r_v['Tid'],
        'Tank': cur_tank,
        'Gas': nu_gas_effekt,
        'Aftag': aftag
    })

df_prog = pd.DataFrame(p_data).set_index('RealTime')

# --- 5. DASHBOARD & VISNING ---
st.title("Skuldelev Drifts-Agent ⚡")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Tank Status", f"{st.session_state.tank_pct} %", f"{round(tank_mwh_nu,1)} MWh")
k2.metric("Gas Backup", "AKTIV" if gas_aktiv else "Standby", delta="- Gas kører" if gas_aktiv else None)
k3.metric("Beregnet Aftag", f"{int(df_prog['Aftag'].iloc[0])} kW")
k4.metric("Spotpris NU", f"{int(el_df.iloc[0]['SpotPriceDKK'])} kr")

st.divider()

# Tank Graf
st.subheader("Tank Prognose (MWh)")
st.line_chart(df_prog[['Tank']], color="#0072B2")

# Gas Graf (Gul for 800, Rød for 1600)
st.subheader("Gaskedel Ydelse (kW)")
gas_farve = "#FFD700" if st.session_state.gas_trin == 800 else "#FF0000"
st.area_chart(df_prog[['Gas']], color=gas_farve)

# Aftag Graf
st.subheader("Forbrug Prognose (kW)")
st.line_chart(df_prog[['Aftag']], color="#FF4B4B")
