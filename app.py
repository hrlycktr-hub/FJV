import streamlit as st
import pandas as pd
import requests
import plotly.express as px
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
st.title("Skuldelev Drifts-Agent ⚡ (Udglattet visning)")

# --- 2. DATA-HENTNING ---
@st.cache_data(ttl=300)
def hent_data():
    try:
        url = "https://api.energidataservice.dk/dataset/DayAheadPrices?limit=48&filter={'PriceArea':['DK2']}"
        r = requests.get(url, timeout=5).json()['records']
        el_df = pd.DataFrame(r)
        el_df['Tid'] = pd.to_datetime(el_df['HourDK']).dt.tz_localize(None)
        el_df = el_df.sort_values('Tid').reset_index(drop=True)
    except:
        tider = [datetime.now().replace(minute=0,second=0) + timedelta(hours=i) for i in range(48)]
        el_df = pd.DataFrame({'Tid': tider, 'SpotPriceDKK': [400+100*np.sin(i/3) for i in range(48)]})

    try:
        url_v = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=55.79&lon=12.02"
        r_v = requests.get(url_v, headers={'User-Agent': 'SkuldelevV1/1.8'}, timeout=5).json()
        v_rows = []
        for entry in r_v['properties']['timeseries'][:48]:
            v_rows.append({
                'Tid': pd.to_datetime(entry['time']).tz_convert('Europe/Copenhagen').tz_localize(None),
                'Temp': entry['data']['instant']['details']['air_temperature'],
                'Vind': entry['data']['instant']['details']['wind_speed']
            })
        vejr_df = pd.DataFrame(v_rows).sort_values('Tid').reset_index(drop=True)
    except:
        vejr_df = pd.DataFrame({'Tid': el_df['Tid'], 'Temp': [7.0]*48, 'Vind': [5.0]*48})
    
    return el_df, vejr_df

el_df, vejr_df = hent_data()

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header("Drifts-kontrol")
    nu_t = vejr_df['Temp'].iloc[0] + st.session_state.temp_off
    nu_v = max(0, vejr_df['Vind'].iloc[0] + st.session_state.vind_off)
    tf = max(0, (15 - nu_t) * 0.8); vf = 3.0 if nu_v < 3 else min(10, 3 + (nu_v - 3) * 0.77)
    effekt_nu = st.session_state.basis + (tf + vf - 10.3) * st.session_state.respons
    st.metric("Effekt NU", f"{int(effekt_nu)} kW")
    st.write(f"Vejr: {round(nu_t,1)}°C / {round(nu_v,1)} m/s")
    st.divider()
    st.session_state.basis = st.number_input("Basis (kW)", value=st.session_state.basis)
    st.session_state.respons = st.number_input("Respons", value=st.session_state.respons)
    st.divider()
    st.session_state.bud_el = st.number_input("Bud Elkedel", value=float(st.session_state.bud_el))
    st.info(f"💡 Kedel: {len(el_df[el_df['SpotPriceDKK'] <= st.session_state.bud_el])} timer")
    st.session_state.bud_mo = st.number_input("Bud Motor", value=float(st.session_state.bud_mo))
    st.warning(f"💡 Motor: {len(el_df[el_df['SpotPriceDKK'] >= st.session_state.bud_mo])} timer")
    st.divider()
    st.session_state.temp_off = st.slider("Temp Offset", -5.0, 5.0, st.session_state.temp_off)
    st.session_state.vind_off = st.slider("Vind Offset", -10.0, 10.0, st.session_state.vind_off)
    st.session_state.tank_pct = st.slider("Aktuel Tank %", 0, 100, st.session_state.tank_pct)

# --- 4. BEREGNING AF PROGNOSE ---
prog_data = []
tank_mwh = (st.session_state.tank_pct / 100) * TANK_A_MAX_MWH
for i in range(len(vejr_df)):
    v_row = vejr_df.iloc[i]
    t_cal = v_row['Temp'] + st.session_state.temp_off
    v_cal = max(0, v_row['Vind'] + st.session_state.vind_off)
    tf = max(0, (15 - t_cal) * 0.8); vf = 3.0 if v_cal < 3 else min(10, 3 + (v_cal - 3) * 0.77)
    aftag_i = st.session_state.basis + (tf + vf - 10.3) * st.session_state.respons
    bio = get_bio_produktion((tank_mwh/TANK_A_MAX_MWH)*100)
    tank_mwh = max(0, min(TANK_A_MAX_MWH, tank_mwh + (bio - aftag_i)/1000))
    prog_data.append({'Tid': v_row['Tid'], 'Aftag_kW': aftag_i, 'Tank_MWh': tank_mwh})
df_p = pd.DataFrame(prog_data)

# --- 5. VISNING (PLOTLY SPLINE GRAFER) ---
def plot_spline(df, y_col, color, title, y_range=None):
    fig = px.line(df, x='Tid', y=y_col, title=title, render_mode='svg')
    fig.update_traces(line_shape='spline', line_smoothing=1.3, line_color=color)
    fig.update_layout(xaxis_tickformat='%H:00', hovermode='x unified', height=350, margin=dict(l=20, r=20, t=40, b=20))
    if y_range: fig.update_yaxes(range=y_range)
    return fig

# Elpris graf
el_melt = el_df.copy()
el_melt['Bud Elkedel'] = st.session_state.bud_el
el_melt['Bud Motor'] = st.session_state.bud_mo
fig_el = px.line(el_melt, x='Tid', y=['SpotPriceDKK', 'Bud Elkedel', 'Bud Motor'], title="Elpriser & Bud (DK2)")
fig_el.update_traces(line_shape='hv') # Elpriser er ofte bedre som trappetrin (hv)
fig_el.update_layout(xaxis_tickformat='%H:00', height=300)
st.plotly_chart(fig_el, use_container_width=True)

st.divider()
c1, c2 = st.columns(2)
with c1:
    st.plotly_chart(plot_spline(df_p, 'Aftag_kW', '#FF4B4B', 'Forventet Aftag (kW)'), use_container_width=True)
with c2:
    st.plotly_chart(plot_spline(df_p, 'Tank_MWh', '#0072B2', 'Tank A Prognose (MWh)', y_range=[0, 70]), use_container_width=True)
