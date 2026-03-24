import streamlit as st
import pandas as pd
import requests
import numpy as np
from datetime import datetime, timedelta

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
    st.session_state.gas_trin = 800
    st.session_state.sidste_el_data = pd.DataFrame()
    st.session_state.opdateret_tid = "Afventer..."
    st.session_state.init_done = True

TANK_A_MAX_MWH = 50.4  

def get_faktisk_bio(tank_pct, max_bio_limit):
    if tank_pct <= 30: return max_bio_limit
    elif tank_pct <= 60: return max_bio_limit * 0.75
    elif tank_pct <= 90: return max_bio_limit * 0.60
    return 0

st.set_page_config(page_title="Skuldelev V1 - 48t Drift", layout="wide")

# --- 2. DATA-HENTNING (48 TIMER) ---
@st.cache_data(ttl=300)
def hent_ekstern_data():
    el_out, vejr_out, update_str = pd.DataFrame(), pd.DataFrame(), ""
    try:
        url = "https://api.energidataservice.dk/dataset/DayAheadPrices?limit=50&filter={'PriceArea':['DK2']}"
        r = requests.get(url, timeout=5).json()['records']
        el_out = pd.DataFrame(r).sort_values('HourDK').reset_index(drop=True)
        el_out['Tid'] = pd.to_datetime(el_out['HourDK']).dt.tz_localize(None)
        update_str = datetime.now().strftime("%H:%M:%S")
    except: pass
    try:
        url_v = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=55.79&lon=12.02"
        rv = requests.get(url_v, headers={'User-Agent': 'SkuldelevV1/7.0'}, timeout=5).json()
        rows = [{'Tid': pd.to_datetime(e['time']).tz_convert('Europe/Copenhagen').tz_localize(None),
                 'Temp': e['data']['instant']['details']['air_temperature'],
                 'Vind': e['data']['instant']['details']['wind_speed']} 
                for e in rv['properties']['timeseries'][:48]] # 48 timer
        vejr_out = pd.DataFrame(rows)
    except: pass
    return el_out, vejr_out, update_str

raw_el, raw_vejr, update_tid = hent_ekstern_data()
if not raw_el.empty:
    st.session_state.sidste_el_data = raw_el
    st.session_state.opdateret_tid = update_tid

el_df = st.session_state.sidste_el_data
vejr_df = raw_vejr

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Parametre")
    with st.container(border=True):
        st.subheader("🔥 Gaskedel")
        st.radio("Effekt (kW)", [800, 1600], key='gas_trin')
    with st.container(border=True):
        st.subheader("📊 mFRR Bud")
        st.number_input("Elkedel", key='bud_el')
        st.number_input("Motor", key='bud_mo')
    with st.container(border=True):
        st.subheader("🔧 SCADA")
        st.slider("Tank %", 0, 100, key='tank_pct')
        st.number_input("Basis (kW)", key='basis')

# --- 4. PROGNOSE (48 TIMER) ---
tank_mwh_nu = (st.session_state.tank_pct / 100) * TANK_A_MAX_MWH
p_data = []
cur_tank = tank_mwh_nu
gas_aktiv = False

for i in range(len(vejr_df)):
    r_v = vejr_df.iloc[i]
    # Find pris (fallback hvis prisen mangler for timen)
    match_pris = el_df[el_df['Tid'].dt.hour == r_v['Tid'].hour]['SpotPriceDKK']
    p_s = match_pris.values[0] if not match_pris.empty else 500
    
    # Aftag
    t_c = r_v['Temp'] + st.session_state.temp_off
    v_c = max(0, r_v['Vind'] + st.session_state.vind_off)
    aftag = st.session_state.basis + (max(0,(15-t_c)*0.8) + (3.0 if v_c<3 else min(10,3+(v_c-3)*0.77)) - 10.3) * st.session_state.respons
    
    # Produktion
    pct_nu = (cur_tank / TANK_A_MAX_MWH) * 100
    prod = get_faktisk_bio(pct_nu, st.session_state.max_bio)
    if p_s <= st.session_state.bud_el: prod += st.session_state.max_elkedel
    if p_s >= st.session_state.bud_mo: prod += st.session_state.max_motor
    
    # Gas-automatik (6-10 MWh)
    if cur_tank <= 6.0: gas_aktiv = True
    if cur_tank >= 10.0: gas_aktiv = False
    
    gas_effekt = st.session_state.gas_trin if gas_aktiv else 0
    prod += gas_effekt
    
    cur_tank = max(0, min(TANK_A_MAX_MWH, cur_tank + (prod - aftag)/1000))
    
    # Formater tid til 24t format (HH:mm)
    tid_label = r_v['Tid'].strftime("%H:%M (%d/%m)")
    
    p_data.append({
        'Tid': tid_label,
        'Tank (MWh)': cur_tank,
        'Gas (kW)': gas_effekt,
        'Aftag (kW)': aftag
    })

df_prog = pd.DataFrame(p_data).set_index('Tid')

# --- 5. VISNING ---
st.title("Skuldelev Drifts-Agent ⚡ (48t Overblik)")
st.caption(f"Opdateret: {st.session_state.opdateret_tid}")

# KPI
k1, k2, k3 = st.columns(3)
k1.metric("Tank Nu", f"{round(tank_mwh_nu,1)} MWh", f"{st.session_state.tank_pct}%")
k2.metric("Gas Backup", "AKTIV" if gas_aktiv else "OFF")
k3.metric("Spotpris NU", f"{int(el_df.iloc[0]['SpotPriceDKK'])} kr")

st.divider()

# KOMBINERET VISNING
st.subheader("Tankniveau & Gaskedel Backup")
gas_color = "#FFD700" if st.session_state.gas_trin == 800 else "#FF4B4B"

# Vi viser dem under hinanden for maksimal læsbarhed af de 48 timer
st.line_chart(df_prog[['Tank (MWh)']], color="#0072B2")
st.area_chart(df_prog[['Gas (kW)']], color=gas_color)

with st.expander("Se Forbrugsprognose (kW)"):
    st.line_chart(df_prog[['Aftag (kW)']], color="#808080")
