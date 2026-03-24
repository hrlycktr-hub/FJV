import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import numpy as np

# --- 1. KONFIGURATION & HUKOMMELSE ---
# Dette sikrer at dine indtastninger overlever genindlæsning
if 'tank_pct' not in st.session_state: st.session_state.tank_pct = 44
if 'basis' not in st.session_state: st.session_state.basis = 1260
if 'respons' not in st.session_state: st.session_state.respons = 45
if 'bud_el' not in st.session_state: st.session_state.bud_el = 50.0
if 'bud_mo' not in st.session_state: st.session_state.bud_mo = 800.0

TANK_A_MAX_MWH = 70.0  
LAT, LON = 55.79, 12.02

def get_bio_produktion(tank_pct):
    if tank_pct <= 30: return 1000
    elif tank_pct <= 60: return 750
    elif tank_pct <= 90: return 600
    return 0

st.set_page_config(page_title="Skuldelev V1", layout="wide")
st.title("Skuldelev Drifts-Agent ⚡ (v1.0)")

# --- 2. DATA-HENTNING (2026 DayAhead) ---
@st.cache_data(ttl=600)
def hent_data():
    el_df = pd.DataFrame()
    # Prøv Energinet (DayAheadPrices er det nye standard-sæt i 2026)
    try:
        url = "https://api.energidataservice.dk/dataset/DayAheadPrices?limit=100&filter={'PriceArea':['DK2']}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200 and res.text.strip():
            records = res.json()['records']
            el_df = pd.DataFrame(records)
            t_col = 'HourDK' if 'HourDK' in el_df.columns else 'HourUTC'
            el_df['Tid'] = pd.to_datetime(el_df[t_col]).dt.tz_localize(None)
            el_df = el_df.sort_values('Tid').tail(48)
    except:
        pass

    # Backup-data hvis API fejler (så graferne altid vises)
    if el_df.empty:
        tider = [datetime.now() + timedelta(hours=i) for i in range(48)]
        el_df = pd.DataFrame({'Tid': tider, 'SpotPriceDKK': 500 + 300 * np.sin(np.linspace(0, 4*np.pi, 48))})

    # Vejr-data
    try:
        url_v = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={LAT}&lon={LON}"
        r_v = requests.get(url_v, headers={'User-Agent': 'SkuldelevV1/1.0'}, timeout=5).json()
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

# --- 3. SIDEBAR (KONTROL & INFO) ---
with st.sidebar:
    st.header("Drifts-parametre")
    st.session_state.tank_pct = st.slider("Aktuel Tank %", 0, 100, st.session_state.tank_pct)
    
    st.divider()
    st.subheader("mFRR Bud")
    st.session_state.bud_el = st.number_input("Elkedel (DKK)", value=float(st.session_state.bud_el))
    t_kedel = len(el_df[el_df['SpotPriceDKK'] <= st.session_state.bud_el])
    st.info(f"✅ Kedel kører i {t_kedel} timer")
    
    st.session_state.bud_mo = st.number_input("Motor (DKK)", value=float(st.session_state.bud_mo))
    t_motor = len(el_df[el_df['SpotPriceDKK'] >= st.session_state.bud_mo])
    st.warning(f"✅ Motor kører i {t_motor} timer")
    
    st.divider()
    st.subheader("SCADA Trimning")
    st.session_state.basis = st.number_input("Basis (kW)", value=st.session_state.basis)
    st.session_state.respons = st.number_input("Respons", value=st.session_state.respons)

# --- 4. BEREGNING (GLAT PROGNOSE) ---
prog = vejr_df.copy()
prog['Tidspunkt'] = prog['Tid'].dt.strftime('%H:%M')
tank_mwh = (st.session_state.tank_pct / 100) * TANK_A_MAX_MWH
b_log, a_log = [], []

for _, row in prog.iterrows():
    # Aftags-beregning
    t_fakt = max(0, (15 - row['Temp']) * 0.8)
    v_fakt = 3.0 if row['Vind'] < 3 else min(10, 3 + (row['Vind'] - 3) * 0.77)
    aftag_nu = st.session_state.basis + (t_fakt + v_fakt - 10.3) * st.session_state.respons
    a_log.append(aftag_nu)
    
    # Tank-logik (Time for time)
    bio_nu = get_bio_produktion((tank_mwh/TANK_A_MAX_MWH)*100)
    tank_mwh = max(0, min(TANK_A_MAX_MWH, tank_mwh + (bio_nu - aftag_nu)/1000))
    b_log.append(tank_mwh)

prog['Tank_MWh'], prog['Aftag_kW'] = b_log, a_log

# --- 5. VISNING AF GRAFER ---
st.subheader("Elpriser & Budgrænser (DK2)")
chart_el = pd.DataFrame({
    'Tid': el_df['Tid'].dt.strftime('%d/%m %H:%M'),
    'Spotpris': el_df['SpotPriceDKK'].values,
    'Bud Elkedel': [st.session_state.bud_el] * len(el_df),
    'Bud Motor': [st.session_state.bud_mo] * len(el_df)
}).set_index('Tid')
st.line_chart(chart_el, height=300)

st.divider()
c1, c2 = st.columns(2)
with c1:
    st.subheader("Forventet Aftag (kW)")
    st.line_chart(prog.set_index('Tidspunkt')['Aftag_kW'], color="#FF0000")
with c2:
    st.subheader("Tank A Prognose (MWh)")
    st.line_chart(prog.set_index('Tidspunkt')['Tank_MWh'], color="#0000FF")
