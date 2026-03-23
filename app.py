import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- 1. SESSION STATE (HUKOMMELSE) ---
if 'tank_pct' not in st.session_state: st.session_state.tank_pct = 44
if 'basis' not in st.session_state: st.session_state.basis = 1260
if 'respons' not in st.session_state: st.session_state.respons = 45
if 'bud_elkedel' not in st.session_state: st.session_state.bud_elkedel = 50.0
if 'bud_motor' not in st.session_state: st.session_state.bud_motor = 800.0

TANK_A_MAX_MWH = 70.0  
LAT, LON = 55.79, 12.02

def get_bio_produktion(tank_pct):
    if tank_pct <= 30: return 1000
    elif tank_pct <= 40: return 900
    elif tank_pct <= 50: return 800
    elif tank_pct <= 60: return 700
    elif tank_pct <= 90: return 600
    return 0

st.set_page_config(page_title="Skuldelev 48t Drift", layout="wide")
st.title("Skuldelev Drifts-Agent ⚡")

# --- 2. DATA-HENTNING ---
@st.cache_data(ttl=300)
def hent_data():
    el_res, vejr_res = pd.DataFrame(), pd.DataFrame()
    # Henter Elspot priser
    try:
        url_el = "https://api.energidataservice.dk/dataset/Elspotprices?limit=100&filter={'PriceArea':['DK2']}"
        r_el = requests.get(url_el, timeout=10).json()['records']
        el_res = pd.DataFrame(r_el)
        el_res['Tid'] = pd.to_datetime(el_res['HourDK']).dt.tz_localize(None)
        el_res = el_res.sort_values('Tid')
    except: st.warning("Kunne ikke hente EL-data")

    # Henter Vejr
    try:
        h = {'User-Agent': 'SkuldelevApp/7.0'}
        url_v = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={LAT}&lon={LON}"
        r_v = requests.get(url_v, headers=h, timeout=10).json()
        rows = []
        for entry in r_v['properties']['timeseries'][:48]:
            rows.append({
                'Tid': pd.to_datetime(entry['time']).tz_convert('Europe/Copenhagen').tz_localize(None),
                'Temp': entry['data']['instant']['details']['air_temperature'],
                'Vind': entry['data']['instant']['details']['wind_speed']
            })
        vejr_res = pd.DataFrame(rows)
    except: st.warning("Kunne ikke hente VEJR-data")
    
    return el_res, vejr_res

el_df, vejr_df = hent_data()

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header("Indstillinger")
    st.session_state.tank_pct = st.slider("Tank A (%)", 0, 100, st.session_state.tank_pct)
    st.session_state.basis = st.number_input("Basis v. 7°C (kW)", value=st.session_state.basis)
    st.session_state.respons = st.number_input("Respons (kW/grad)", value=st.session_state.respons)
    st.divider()
    st.session_state.bud_elkedel = st.number_input("Elkedel bud", value=float(st.session_state.bud_elkedel))
    st.session_state.bud_motor = st.number_input("Motor bud", value=float(st.session_state.bud_motor))

# --- 4. BEREGNING AF DRIFT ---
if not vejr_df.empty:
    prog = vejr_df.copy()
    prog['Tidspunkt'] = prog['Tid'].dt.strftime('%H:%M')
    beholdning = (st.session_state.tank_pct / 100) * TANK_A_MAX_MWH
    b_log, a_log = [], []
    for i, row in prog.iterrows():
        t_t = max(0, (15 - row['Temp']) * 0.8)
        v_t = 3.0 if row['Vind'] < 3 else min(10, 3 + (row['Vind'] - 3) * 0.77)
        aftag = st.session_state.basis + (t_t + v_t - 10.3) * st.session_state.respons
        a_log.append(aftag)
        bio = get_bio_produktion((beholdning/TANK_A_MAX_MWH)*100)
        beholdning = max(0, min(TANK_A_MAX_MWH, beholdning + (bio - aftag)/1000))
        b_log.append(beholdning)
    prog['Tank_MWh'] = b_log
    prog['Aftag_kW'] = a_log

# --- 5. ØKONOMI & ELPRIS (HOVEDSKÆRM) ---
st.header("mFRR Overblik & Elpriser")
if not el_df.empty:
    # Vi tager alle tilgængelige priser i datasættet
    el_nu = el_df.copy()
    el_nu['Tidspunkt'] = el_nu['Tid'].dt.strftime('%d/%m %H:%M')
    
    # Beregn timer
    t_kedel = len(el_nu[el_nu['SpotPriceDKK'] <= st.session_state.bud_elkedel])
    t_motor = len(el_nu[el_nu['SpotPriceDKK'] >= st.session_state.bud_motor])
    
    # VISNING AF BOKSE
    c1, c2, c3 = st.columns(3)
    c1.success(f"**Elkedel:** {t_kedel} timer fundet")
    c2.warning(f"**Motor:** {t_motor} timer fundet")
    c3.info(f"**Pris nu:** {round(el_nu['SpotPriceDKK'].iloc[-1])} kr")

    # GRAF MED BUDLINJER
    el_nu['Elkedel_Bud'] = float(st.session_state.bud_elkedel)
    el_nu['Motor_Bud'] = float(st.session_state.bud_motor)
    st.line_chart(el_nu.set_index('Tidspunkt')[['SpotPriceDKK', 'Elkedel_Bud', 'Motor_Bud']])
else:
    st.error("Ingen elpris-data fundet. Tjek om api.energidataservice.dk er nede.")

# --- 6. DRIFT ---
st.divider()
cl, cr = st.columns(2)
if not vejr_df.empty:
    with cl:
        st.subheader("Forventet Aftag (kW)")
        st.line_chart(prog.set_index('Tidspunkt')['Aftag_kW'])
    with cr:
        st.subheader("Tank-prognose (MWh)")
        st.line_chart(prog.set_index('Tidspunkt')['Tank_MWh'])

# --- 7. HURTIGTJEK ---
st.divider()
if not vejr_df.empty:
    aftag_nu = prog['Aftag_kW'].iloc[0]
    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("Tjek Elkedel"):
            n = (get_bio_produktion(st.session_state.tank_pct) + 2000) - aftag_nu
            st.write(f"Fuld om: **{round((TANK_A_MAX_MWH-(st.session_state.tank_pct/100*TANK_A_MAX_MWH))/(max(n,1)/1000), 1)} t**")
    with b2:
        if st.button("Tjek Motor"):
            n = (get_bio_produktion(st.session_state.tank_pct) + 1200) - aftag_nu
            st.write(f"Fuld om: **{round((TANK_A_MAX_MWH-(st.session_state.tank_pct/100*TANK_A_MAX_MWH))/(max(n,1)/1000), 1)} t**")
    with b3:
        if st.button("Kun Bio"):
            n = get_bio_produktion(st.session_state.tank_pct) - aftag_nu
            t = (st.session_state.tank_pct/100*TANK_A_MAX_MWH if n < 0 else TANK_A_MAX_MWH-(st.session_state.tank_pct/100*TANK_A_MAX_MWH)) / (abs(n)/1000)
            st.write(f"Fuld/Tom om: **{round(t,1)} t**")
