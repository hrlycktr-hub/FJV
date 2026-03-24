import streamlit as st
import pandas as pd
import requests
import numpy as np
from datetime import datetime, timedelta
from scipy.interpolate import make_interp_spline

# --- 1. SETUP & INITIALISERING (Kun første gang) ---
def init_state(key, value):
    if key not in st.session_state:
        st.session_state[key] = value

init_state('tank_pct', 44)
init_state('basis', 1260)
init_state('respons', 45)
init_state('bud_el', 50.0)
init_state('bud_mo', 800.0)
init_state('temp_off', 0.0)
init_state('vind_off', 0.0)

TANK_A_MAX_MWH = 70.0  

def get_bio_produktion(tank_pct):
    if tank_pct <= 30: return 1000
    elif tank_pct <= 60: return 750
    elif tank_pct <= 90: return 600
    return 0

st.set_page_config(page_title="Skuldelev V1", layout="wide")

# --- 2. DATA-HENTNING ---
@st.cache_data(ttl=300)
def hent_data():
    el_df, vejr_df = pd.DataFrame(), pd.DataFrame()
    try:
        url = "https://api.energidataservice.dk/dataset/DayAheadPrices?limit=48&filter={'PriceArea':['DK2']}"
        r = requests.get(url, timeout=5).json()['records']
        el_df = pd.DataFrame(r)
        el_df['Tid'] = pd.to_datetime(el_df['HourDK']).dt.tz_localize(None)
        el_df = el_df.sort_values('Tid').reset_index(drop=True)
    except:
        tider = [datetime.now().replace(minute=0, second=0) + timedelta(hours=i) for i in range(48)]
        el_df = pd.DataFrame({'Tid': tider, 'SpotPriceDKK': [500.0]*48})

    try:
        url_v = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=55.79&lon=12.02"
        rv = requests.get(url_v, headers={'User-Agent': 'SkuldelevV1/2.6'}, timeout=5).json()
        rows = []
        for e in rv['properties']['timeseries'][:48]:
            rows.append({
                'Tid': pd.to_datetime(e['time']).tz_convert('Europe/Copenhagen').tz_localize(None),
                'Temp': e['data']['instant']['details']['air_temperature'],
                'Vind': e['data']['instant']['details']['wind_speed']
            })
        vejr_df = pd.DataFrame(rows).sort_values('Tid').reset_index(drop=True)
    except:
        vejr_df = pd.DataFrame({'Tid': el_df['Tid'], 'Temp': [7.0]*48, 'Vind': [5.0]*48})
    
    return el_df, vejr_df

el_df, vejr_df = hent_data()

# --- 3. SIDEBAR: FASTE BOKSE MED KEYS ---
with st.sidebar:
    st.header("⚙️ Kontrolpanel")
    
    # BOKS 1: mFRR & BUD
    with st.container(border=True):
        st.subheader("📊 mFRR Bud")
        st.number_input("Bud Elkedel", key='bud_el')
        st.number_input("Bud Motor", key='bud_mo')
    
    # BOKS 2: SCADA TRIMNING
    with st.container(border=True):
        st.subheader("🔧 SCADA Trimning")
        st.number_input("Basis (kW)", key='basis')
        st.number_input("Respons", key='respons')
        st.divider()
        st.slider("Temp Offset", -5.0, 5.0, key='temp_off')
        st.slider("Vind Offset", -10.0, 10.0, key='vind_off')

    # BOKS 3: TANK
    with st.container(border=True):
        st.subheader("🔋 Tank Status")
        st.slider("Aktuel %", 0, 100, key='tank_pct')

# --- 4. BEREGNINGER (Bruger nu session_state direkte) ---
nu_t = vejr_df['Temp'].iloc[0] + st.session_state.temp_off
nu_v = max(0, vejr_df['Vind'].iloc[0] + st.session_state.vind_off)
tf = max(0, (15 - nu_t) * 0.8)
vf = 3.0 if nu_v < 3 else min(10, 3 + (nu_v - 3) * 0.77)
effekt_nu = st.session_state.basis + (tf + vf - 10.3) * st.session_state.respons

t_kedel = len(el_df[el_df['SpotPriceDKK'] <= st.session_state.bud_el])
t_motor = len(el_df[el_df['SpotPriceDKK'] >= st.session_state.bud_mo])
tank_mwh_nu = (st.session_state.tank_pct / 100) * TANK_A_MAX_MWH

# --- 5. HOVEDSKÆRM: DASHBOARD ---
st.title("Skuldelev Drifts-Agent ⚡")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Aktuel Effekt", f"{int(effekt_nu)} kW")
k2.metric("Vejr (Trimmet)", f"{round(nu_t,1)} °C", f"{round(nu_v,1)} m/s")
k3.metric("Tank Status", f"{st.session_state.tank_pct} %", f"{round(tank_mwh_nu,1)} MWh")
k4.metric("mFRR Timer", f"K:{t_kedel}t / M:{t_motor}t")

st.divider()

# PROGNOSE BEREGNING
p_data = []
temp_tank = tank_mwh_nu
for i in range(len(vejr_df)):
    r = vejr_df.iloc[i]
    tc = r['Temp'] + st.session_state.temp_off
    vc = max(0, r['Vind'] + st.session_state.vind_off)
    aftag = st.session_state.basis + (max(0,(15-tc)*0.8) + (3.0 if vc<3 else min(10,3+(vc-3)*0.77)) - 10.3) * st.session_state.respons
    temp_tank = max(0, min(TANK_A_MAX_MWH, temp_tank + (get_bio_produktion((temp_tank/70)*100) - aftag)/1000))
    p_data.append({'Tid': i, 'Aftag': aftag, 'Tank': temp_tank})
df_prog = pd.DataFrame(p_data)

# GRAFER
def smooth_chart(df, y_col, color, title):
    x = df['Tid'].values
    x_new = np.linspace(x.min(), x.max(), 300)
    spline = make_interp_spline(x, df[y_col], k=3)
    y_smooth = spline(x_new)
    st.subheader(title)
    st.line_chart(pd.DataFrame({y_col: y_smooth}), color=color)

st.subheader("Spotpris & Bud")
st.line_chart(pd.DataFrame({
    'Spot': el_df['SpotPriceDKK'].values,
    'Kedel': [st.session_state.bud_el]*48,
    'Motor': [st.session_state.bud_mo]*48
}))

c1, c2 = st.columns(2)
with c1: smooth_chart(df_prog, 'Aftag', '#FF4B4B', 'Aftag Prognose (kW)')
with c2: smooth_chart(df_prog, 'Tank', '#0072B2', 'Tank Prognose (MWh)')
