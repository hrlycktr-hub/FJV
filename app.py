import streamlit as st
import pandas as pd
import requests
import numpy as np
from datetime import datetime, timedelta

# --- 1. SETUP ---
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
    st.session_state.sidste_el_data = pd.DataFrame(columns=['Tid', 'SpotPriceDKK'])
    st.session_state.opdateret_tid = "Ingen data"
    st.session_state.init_done = True

TANK_A_MAX_MWH = 50.4

def get_faktisk_bio(tank_pct, max_bio_limit):
    if tank_pct <= 30: return max_bio_limit
    elif tank_pct <= 60: return max_bio_limit * 0.75
    elif tank_pct <= 90: return max_bio_limit * 0.60
    return 0

st.set_page_config(page_title="Skuldelev V1", layout="wide")

# --- 2. DATA (48 TIMER) ---
@st.cache_data(ttl=300)
def hent_data():
    el_df = pd.DataFrame(columns=['Tid', 'SpotPriceDKK'])
    vejr_df = pd.DataFrame()
    opdateret = st.session_state.opdateret_tid

    try:
        url = "https://api.energidataservice.dk/dataset/DayAheadPrices?limit=48&filter={'PriceArea':['DK2']}"
        r = requests.get(url, timeout=5).json()['records']
        if r:
            temp_el = pd.DataFrame(r)
            temp_el['Tid'] = pd.to_datetime(temp_el['HourDK']).dt.tz_localize(None)
            el_df = temp_el[['Tid', 'SpotPriceDKK']].sort_values('Tid').reset_index(drop=True)
            st.session_state.sidste_el_data = el_df
            st.session_state.opdateret_tid = datetime.now().strftime("%H:%M:%S")
            opdateret = st.session_state.opdateret_tid
    except:
        el_df = st.session_state.sidste_el_data

    # Hvis alt fejler, lav nød-data så graferne ikke dør
    if el_df.empty:
        el_df = pd.DataFrame({'Tid': [datetime.now() + timedelta(hours=i) for i in range(48)], 'SpotPriceDKK': [500.0]*48})

    try:
        url_v = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=55.79&lon=12.02"
        rv = requests.get(url_v, headers={'User-Agent': 'SkuldelevV1/7.0'}, timeout=5).json()
        rows = [{'Tid': pd.to_datetime(e['time']).tz_convert('Europe/Copenhagen').tz_localize(None),
                 'Temp': e['data']['instant']['details']['air_temperature'],
                 'Vind': e['data']['instant']['details']['wind_speed']} 
                for e in rv['properties']['timeseries'][:48]]
        vejr_df = pd.DataFrame(rows)
    except:
        vejr_df = pd.DataFrame({'Tid': el_df['Tid'], 'Temp': [7.0]*48, 'Vind': [5.0]*48})
        
    return el_df, vejr_df, opdateret

el_df, vejr_df, update_tid = hent_data()

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Parametre")
    st.radio("Gaskedel trin (kW)", [800, 1600], key='gas_trin')
    st.number_input("Bud Elkedel", key='bud_el')
    st.number_input("Bud Motor", key='bud_mo')
    st.slider("Aktuel Tank %", 0, 100, key='tank_pct')
    st.number_input("Basis (kW)", key='basis')

# --- 4. BEREGNING (48 TIMER) ---
tank_mwh_nu = (st.session_state.tank_pct / 100) * TANK_A_MAX_MWH
p_data = []
cur_tank = tank_mwh_nu
gas_aktiv = False

for i in range(len(vejr_df)):
    rv = vejr_df.iloc[i]
    # Sikker hentning af spotpris
    try:
        p_s = el_df.iloc[i]['SpotPriceDKK']
    except:
        p_s = 500.0

    aftag = st.session_state.basis + (max(0,(15-(rv['Temp']+st.session_state.temp_off))*0.8) + 
            (3.0 if (rv['Vind']+st.session_state.vind_off)<3 else min(10,3+((rv['Vind']+st.session_state.vind_off)-3)*0.77)) - 10.3) * st.session_state.respons
    
    prod = get_faktisk_bio((cur_tank/TANK_A_MAX_MWH)*100, st.session_state.max_bio)
    if p_s <= st.session_state.bud_el: prod += st.session_state.max_elkedel
    if p_s >= st.session_state.bud_mo: prod += st.session_state.max_motor
    
    if cur_tank <= 6.0: gas_aktiv = True
    if cur_tank >= 10.0: gas_aktiv = False
    
    gas_effekt = st.session_state.gas_trin if gas_aktiv else 0
    prod += gas_effekt
    cur_tank = max(0, min(TANK_A_MAX_MWH, cur_tank + (prod - aftag)/1000))
    
    p_data.append({
        'Tid': rv['Tid'],
        'Tank': cur_tank,
        'Gas': gas_effekt
    })

df_prog = pd.DataFrame(p_data).set_index('Tid')

# --- 5. VISNING ---
st.title("Skuldelev Drifts-Agent ⚡")
st.caption(f"Opdateret: {update_tid} (24h format)")

# Kombineret graf
st.subheader("Tankniveau (Blå) & Gaskedel (Gul/Rød) - 48 Timer")
gas_color = "#FFD700" if st.session_state.gas_trin == 800 else "#FF4B4B"

# Vi bruger st.area_chart til gassen for at give den volumen
st.line_chart(df_prog[['Tank']], color="#0072B2")
st.area_chart(df_prog[['Gas']], color=gas_color)

# Info bokse
c1, c2 = st.columns(2)
c1.metric("Tank nu", f"{round(tank_mwh_nu,1)} MWh")
c2.metric("Gas Status", "KØRER" if gas_aktiv else "SLUKKET")
