import streamlit as st
import pandas as pd
import requests
import numpy as np
from datetime import datetime, timedelta
from scipy.interpolate import make_interp_spline

# --- 1. SESSION STATE INITIALISERING ---
if 'init_done' not in st.session_state:
    st.session_state.tank_pct = 50
    st.session_state.basis = 1260
    st.session_state.respons = 45
    st.session_state.bud_el = 50.0
    st.session_state.bud_mo = 800.0
    st.session_state.temp_off = 0.0
    st.session_state.vind_off = 0.0
    st.session_state.sidste_el_data = pd.DataFrame()
    st.session_state.opdateret_tid = "Afventer..."
    st.session_state.init_done = True

TANK_A_MAX_MWH = 50.4  

def get_bio_produktion(tank_pct):
    if tank_pct <= 30: return 1000
    elif tank_pct <= 60: return 750
    elif tank_pct <= 90: return 600
    return 0

st.set_page_config(page_title="Skuldelev V1 - Drift", layout="wide")

# --- 2. DATA-HENTNING ---
@st.cache_data(ttl=300)
def hent_ekstern_data():
    el_out, vejr_out, update_str = pd.DataFrame(), pd.DataFrame(), ""
    try:
        url = "https://api.energidataservice.dk/dataset/DayAheadPrices?limit=48&filter={'PriceArea':['DK2']}"
        r = requests.get(url, timeout=5).json()['records']
        el_out = pd.DataFrame(r)
        el_out['Tid'] = pd.to_datetime(el_out['HourDK']).dt.tz_localize(None)
        el_out = el_out.sort_values('Tid').reset_index(drop=True)
        update_str = datetime.now().strftime("%H:%M:%S")
    except: pass

    try:
        url_v = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=55.79&lon=12.02"
        rv = requests.get(url_v, headers={'User-Agent': 'SkuldelevV1/3.1'}, timeout=5).json()
        rows = []
        for e in rv['properties']['timeseries'][:48]:
            rows.append({
                'Tid': pd.to_datetime(e['time']).tz_convert('Europe/Copenhagen').tz_localize(None),
                'Temp': e['data']['instant']['details']['air_temperature'],
                'Vind': e['data']['instant']['details']['wind_speed']
            })
        vejr_out = pd.DataFrame(rows).sort_values('Tid').reset_index(drop=True)
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
        st.subheader("📊 mFRR Bud")
        st.number_input("Bud Elkedel", key='bud_el')
        st.number_input("Bud Motor", key='bud_mo')
    with st.container(border=True):
        st.subheader("🔧 SCADA Trimning")
        st.number_input("Basis (kW)", key='basis')
        st.number_input("Respons", key='respons')
        st.divider()
        st.slider("Temp Offset", -5.0, 5.0, key='temp_off')
        st.slider("Vind Offset", -10.0, 10.0, key='vind_off')
    with st.container(border=True):
        st.subheader("🔋 Tank Status")
        st.slider("Aktuel %", 0, 100, key='tank_pct')

# --- 4. BEREGNINGER ---
nu_t = vejr_df['Temp'].iloc[0] + st.session_state.temp_off
nu_v = max(0, vejr_df['Vind'].iloc[0] + st.session_state.vind_off)
tf = max(0, (15 - nu_t) * 0.8); vf = 3.0 if nu_v < 3 else min(10, 3 + (nu_v - 3) * 0.77)
effekt_nu = st.session_state.basis + (tf + vf - 10.3) * st.session_state.respons
tank_mwh_nu = (st.session_state.tank_pct / 100) * TANK_A_MAX_MWH

# Prognose-loop
p_data = []
cur_tank = tank_mwh_nu
for i in range(len(vejr_df)):
    r = vejr_df.iloc[i]
    tc = r['Temp'] + st.session_state.temp_off
    vc = max(0, r['Vind'] + st.session_state.vind_off)
    aftag = st.session_state.basis + (max(0,(15-tc)*0.8) + (3.0 if vc<3 else min(10,3+(vc-3)*0.77)) - 10.3) * st.session_state.respons
    cur_tank = max(0, min(TANK_A_MAX_MWH, cur_tank + (get_bio_produktion((cur_tank/TANK_A_MAX_MWH)*100) - aftag)/1000))
    p_data.append({'Tid_indeks': i, 'Aftag': aftag, 'Tank': cur_tank, 'RealTime': r['Tid']})
df_prog = pd.DataFrame(p_data)

# --- 5. GRAFER (Korrigeret Tid) ---
def smooth_chart(df, y_col, color, title):
    # Lav den matematiske udglatning på indeks (0 til 47)
    x = df['Tid_indeks'].values
    x_smooth = np.linspace(x.min(), x.max(), 300)
    spline = make_interp_spline(x, df[y_col], k=3)
    y_smooth = spline(x_smooth)
    
    # Map indeks tilbage til faktiske tidspunkter
    start_tid = df['RealTime'].min()
    tids_intervaller = [start_tid + timedelta(hours=val) for val in x_smooth]
    
    chart_df = pd.DataFrame({'Tid': tids_intervaller, y_col: y_smooth}).set_index('Tid')
    st.subheader(title)
    st.line_chart(chart_df, color=color)

# DASHBOARD
st.title("Skuldelev Drifts-Agent ⚡")
st.caption(f"Data sidst hentet: {st.session_state.opdateret_tid}")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Aktuel Effekt", f"{int(effekt_nu)} kW")
k2.metric("Vejr (Trimmet)", f"{round(nu_t,1)} °C", f"{round(nu_v,1)} m/s")
k3.metric("Tank Status", f"{st.session_state.tank_pct} %", f"{round(tank_mwh_nu,1)} MWh")
k4.metric("mFRR Timer", f"K:{len(el_df[el_df['SpotPriceDKK'] <= st.session_state.bud_el])}t / M:{len(el_df[el_df['SpotPriceDKK'] >= st.session_state.bud_mo])}t")

st.divider()
st.subheader("Spotpriser (DK2)")
st.line_chart(el_df.set_index('Tid')[['SpotPriceDKK']])

c1, c2 = st.columns(2)
with c1: smooth_chart(df_prog, 'Aftag', '#FF4B4B', 'Aftag Prognose (kW)')
with c2: smooth_chart(df_prog, 'Tank', '#0072B2', 'Tank Prognose (MWh)')
