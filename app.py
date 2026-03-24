import streamlit as st
import pandas as pd
import requests
import numpy as np
from datetime import datetime, timedelta
from scipy.interpolate import make_interp_spline

# --- 1. SETUP & SESSION STATE ---
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
        rv = requests.get(url_v, headers={'User-Agent': 'SkuldelevV1/2.2'}, timeout=5).json()
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

# --- 3. SIDEBAR: SCADA TRIMNING & INFO ---
with st.sidebar:
    st.header("SCADA Trimning")
    
    # Her og nu effekt beregning (Kalibreret med offsets)
    nu_t = vejr_df['Temp'].iloc[0] + st.session_state.temp_off
    nu_v = max(0, vejr_df['Vind'].iloc[0] + st.session_state.vind_off)
    tf = max(0, (15 - nu_t) * 0.8)
    vf = 3.0 if nu_v < 3 else min(10, 3 + (nu_v - 3) * 0.77)
    effekt_nu = st.session_state.basis + (tf + vf - 10.3) * st.session_state.respons
    
    st.metric("Beregnet Effekt NU", f"{int(effekt_nu)} kW")
    st.caption(f"Trimmet vejr: {round(nu_t,1)}°C / {round(nu_v,1)} m/s")
    
    st.divider()
    st.subheader("Basis & Respons")
    st.session_state.basis = st.number_input("Basis (kW)", value=st.session_state.basis)
    st.session_state.respons = st.number_input("Respons", value=st.session_state.respons)
    
    st.divider()
    st.subheader("Vejr-Offset (Kalibrering)")
    st.session_state.temp_off = st.slider("Temp Offset (°C)", -5.0, 5.0, st.session_state.temp_off)
    st.session_state.vind_off = st.slider("Vind Offset (m/s)", -10.0, 10.0, st.session_state.vind_off)
    
    st.divider()
    st.subheader("Tank & mFRR")
    st.session_state.tank_pct = st.slider("Aktuel Tank %", 0, 100, st.session_state.tank_pct)
    st.session_state.bud_el = st.number_input("Bud Elkedel", value=float(st.session_state.bud_el))
    st.session_state.bud_mo = st.number_input("Bud Motor", value=float(st.session_state.bud_mo))

# --- 4. DRIFTS-BEREGNING (MED INTERPOLERING) ---
p_data = []
tank_v = (st.session_state.tank_pct / 100) * TANK_A_MAX_MWH
for i in range(len(vejr_df)):
    r = vejr_df.iloc[i]
    tc = r['Temp'] + st.session_state.temp_off
    vc = max(0, r['Vind'] + st.session_state.vind_off)
    aftag = st.session_state.basis + (max(0,(15-tc)*0.8) + (3.0 if vc<3 else min(10,3+(vc-3)*0.77)) - 10.3) * st.session_state.respons
    tank_v = max(0, min(TANK_A_MAX_MWH, tank_v + (get_bio_produktion((tank_v/70)*100) - aftag)/1000))
    p_data.append({'Tid': i, 'Aftag': aftag, 'Tank': tank_v})
df_prog = pd.DataFrame(p_data)

# --- 5. GRAFER (SCIPY SPLINES FOR OVERBLIK) ---
def smooth_chart(df, y_col, color, title, y_range=None):
    x = df['Tid'].values
    x_new = np.linspace(x.min(), x.max(), 300)
    spline = make_interp_spline(x, df[y_col], k=3)
    y_smooth = spline(x_new)
    
    chart_df = pd.DataFrame({'Time': x_new, y_col: y_smooth}).set_index('Time')
    st.subheader(title)
    st.line_chart(chart_df, color=color)

# Elpris (24-timers tekst)
st.subheader("Elpriser & Bud (DK2)")
el_plot = pd.DataFrame({
    'Tid': el_df['Tid'].dt.strftime('%H:00'),
    'Spotpris': el_df['SpotPriceDKK'].values,
    'Bud Elkedel': [st.session_state.bud_el] * 48,
    'Bud Motor': [st.session_state.bud_mo] * 48
}).set_index('Tid')
st.line_chart(el_plot)

st.divider()
c1, c2 = st.columns(2)
with c1:
    smooth_chart(df_prog, 'Aftag', '#FF4B4B', 'Aftag (kW) - Udglattet')
with c2:
    smooth_chart(df_prog, 'Tank', '#0072B2', 'Tank A Prognose (MWh)', y_range=[0, 70])
