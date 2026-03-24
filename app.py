import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import numpy as np

# --- 1. KONFIGURATION & SESSION STATE ---
defaults = {
    'tank_pct': 44, 'basis': 1260, 'respons': 45, 
    'bud_el': 50.0, 'bud_mo': 800.0,
    'temp_off': 0.0, 'vind_off': 0.0  # Nye kalibrerings-værdier
}
for key, val in defaults.items():
    if key not in st.session_state: st.session_state[key] = val

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
        r_v = requests.get(url_v, headers={'User-Agent': 'SkuldelevV1/1.2'}, timeout=5).json()
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

# --- 3. SIDEBAR: SCADA & VEJR-KALIBRERING ---
with st.sidebar:
    st.header("Drifts-kontrol")
    st.session_state.tank_pct = st.slider("Aktuel Tank %", 0, 100, st.session_state.tank_pct)
    
    st.divider()
    st.subheader("Vejr-kalibrering")
    st.caption("Justér så det passer med din lokale vejrstation")
    st.session_state.temp_off = st.slider("Temp Offset (°C)", -5.0, 5.0, st.session_state.temp_off, step=0.1)
    st.session_state.vind_off = st.slider("Vind Offset (m/s)", -10.0, 10.0, st.session_state.vind_off, step=0.5)
    
    st.divider()
    st.subheader("SCADA Trimning")
    st.session_state.basis = st.number_input("Basis (kW)", value=st.session_state.basis)
    st.session_state.respons = st.number_input("Respons", value=st.session_state.respons)
    
    # --- HER OG NU BEREGNING MED KALIBRERING ---
    if not vejr_df.empty:
        # Påfør offset på her-og-nu data
        cal_temp = vejr_df['Temp'].iloc[0] + st.session_state.temp_off
        cal_vind = max(0, vejr_df['Vind'].iloc[0] + st.session_state.vind_off)
        
        t_fakt = max(0, (15 - cal_temp) * 0.8)
        v_fakt = 3.0 if cal_vind < 3 else min(10, 3 + (cal_vind - 3) * 0.77)
        effekt_nu = st.session_state.basis + (t_fakt + v_fakt - 10.3) * st.session_state.respons
        
        st.metric("Her og nu Effekt", f"{int(effekt_nu)} kW")
        st.write(f"Brugt vejr: {round(cal_temp,1)}°C / {round(cal_vind,1)}m/s")

# --- 4. BEREGNING AF PROGNOSE (GLATTE KURVER) ---
prog = vejr_df.copy()
# Vi påfører også offset på prognosen for sammenhæng
prog['Temp'] = prog['Temp'] + st.session_state.temp_off
prog['Vind'] = (prog['Vind'] + st.session_state.vind_off).clip(lower=0)
prog['Tidspunkt'] = prog['Tid'].dt.strftime('%H:%M')

tank_mwh = (st.session_state.tank_pct / 100) * TANK_A_MAX_MWH
b_log, a_log = [], []

for _, row in prog.iterrows():
    t_f = max(0, (15 - row['Temp']) * 0.8)
    v_f = 3.0 if row['Vind'] < 3 else min(10, 3 + (row['Vind'] - 3) * 0.77)
    aftag = st.session_state.basis + (t_f + v_f - 10.3) * st.session_state.respons
    a_log.append(aftag)
    bio = get_bio_produktion((tank_mwh/TANK_A_MAX_MWH)*100)
    tank_mwh = max(0, min(TANK_A_MAX_MWH, tank_mwh + (bio - aftag)/1000))
    b_log.append(tank_mwh)

prog['Tank_MWh'], prog['Aftag_kW'] = b_log, a_log

# --- 5. VISNING ---
st.subheader("Elpriser & Bud (DK2)")
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
    st.line_chart(prog.set_index('Tidspunkt')['Aftag_kW'], color="#FF0000")
with c2:
    st.subheader("Tank A Prognose (MWh)")
    st.line_chart(prog.set_index('Tidspunkt')['Tank_MWh'], color="#0000FF")
