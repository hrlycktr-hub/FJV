import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import numpy as np

# --- 1. SESSION STATE (HUKOMMELSE) ---
# Vi sikrer, at dine indtastninger gemmes
keys = {'tank_pct': 44, 'basis': 1260, 'respons': 45, 'bud_el': 50.0, 'bud_mo': 800.0}
for key, val in keys.items():
    if key not in st.session_state: st.session_state[key] = val

TANK_A_MAX_MWH = 70.0  

def get_bio_produktion(tank_pct):
    if tank_pct <= 30: return 1000
    elif tank_pct <= 60: return 750
    elif tank_pct <= 90: return 600
    return 0

st.set_page_config(page_title="Skuldelev Drifts-Agent", layout="wide")
st.title("Skuldelev Drifts-Agent ⚡")

# --- 2. ROBUST DATA-HENTNING ---
@st.cache_data(ttl=300)
def hent_data():
    el_df = pd.DataFrame()
    
    # Forsøg at hente fra det nye 2026 endpoint
    try:
        url = "https://api.energidataservice.dk/dataset/DayAheadPrices?limit=50&filter={'PriceArea':['DK2']}"
        response = requests.get(url, timeout=5)
        
        # Tjek om vi rent faktisk fik data tilbage (løser fejlen fra dit screenshot)
        if response.status_code == 200 and response.text.strip():
            r = response.json()['records']
            el_df = pd.DataFrame(r)
            t_col = 'HourDK' if 'HourDK' in el_df.columns else 'HourUTC'
            el_df['Tid'] = pd.to_datetime(el_df[t_col]).dt.tz_localize(None)
            el_df = el_df.sort_values('Tid')
        else:
            st.sidebar.warning("Energinet svarer tomt (Service Mode). Bruger nød-data.")
    except:
        st.sidebar.warning("Forbindelse til Energinet fejlede. Bruger nød-data.")

    # Hvis el_df er tom (pga. fejlen), laver vi nød-data så graferne virker
    if el_df.empty:
        tider = [datetime.now() + timedelta(hours=i) for i in range(48)]
        # En standard kurve for DK2 (nat 300 kr, dag 700 kr)
        priser = 500 + 200 * np.sin(np.linspace(0, 4*np.pi, 48))
        el_df = pd.DataFrame({'Tid': tider, 'SpotPriceDKK': priser})

    # Vejr data (met.no er heldigvis meget stabil)
    try:
        url_v = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=55.79&lon=12.02"
        r_v = requests.get(url_v, headers={'User-Agent': 'SkuldelevApp/10.0'}, timeout=5).json()
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

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header("Konfiguration")
    st.session_state.tank_pct = st.slider("Aktuel Tank %", 0, 100, st.session_state.tank_pct)
    st.session_state.bud_el = st.number_input("Bud Elkedel", value=float(st.session_state.bud_el))
    st.session_state.bud_mo = st.number_input("Bud Motor", value=float(st.session_state.bud_mo))
    st.divider()
    st.session_state.basis = st.number_input("Basis kW", value=st.session_state.basis)
    st.session_state.respons = st.number_input("Respons", value=st.session_state.respons)

# --- 4. PROGNOSE BEREGNING ---
prog = vejr_df.copy()
prog['Tidspunkt'] = prog['Tid'].dt.strftime('%H:%M')
beholdning = (st.session_state.tank_pct / 100) * TANK_A_MAX_MWH
b_log, a_log = [], []

for _, row in prog.iterrows():
    t_t = max(0, (15 - row['Temp']) * 0.8)
    v_t = 3.0 if row['Vind'] < 3 else min(10, 3 + (row['Vind'] - 3) * 0.77)
    aftag = st.session_state.basis + (t_t + v_t - 10.3) * st.session_state.respons
    a_log.append(aftag)
    bio = get_bio_produktion((beholdning/TANK_A_MAX_MWH)*100)
    beholdning = max(0, min(TANK_A_MAX_MWH, beholdning + (bio - aftag)/1000))
    b_log.append(beholdning)

prog['Tank_MWh'], prog['Aftag_kW'] = b_log, a_log

# --- 5. VISNING ---
st.header("mFRR Strategi & Priser (DK2)")
c1, c2, c3 = st.columns(3)
k_t = len(el_df[el_df['SpotPriceDKK'] <= st.session_state.bud_el])
m_t = len(el_df[el_df['SpotPriceDKK'] >= st.session_state.bud_mo])

c1.metric("Elkedel (Timer)", f"{k_t} t")
c2.metric("Motor (Timer)", f"{m_t} t")
c3.metric("Spotpris Nu", f"{round(el_df['SpotPriceDKK'].iloc[0])} kr")

# Graf-data strukturering
el_plot = pd.DataFrame({
    'Tid': el_df['Tid'].dt.strftime('%d/%m %H:%M'),
    'Spotpris': el_df['SpotPriceDKK'].values,
    'Bud_Elkedel': [st.session_state.bud_el] * len(el_df),
    'Bud_Motor': [st.session_state.bud_mo] * len(el_df)
}).set_index('Tid')

st.line_chart(el_plot)

st.divider()
col1, col2 = st.columns(2)
with col1:
    st.subheader("Forventet Aftag (kW)")
    st.line_chart(prog.set_index('Tidspunkt')['Aftag_kW'])
with col2:
    st.subheader("Tank A Prognose (MWh)")
    st.line_chart(prog.set_index('Tidspunkt')['Tank_MWh'])
