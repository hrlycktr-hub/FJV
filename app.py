import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- 1. KONFIGURATION & HUKOMMELSE (SESSION STATE) ---
TANK_A_MAX_MWH = 70.0  
LAT, LON = 55.79, 12.02

# Initialiser hukommelse hvis den ikke findes
if 'tank_pct' not in st.session_state: st.session_state.tank_pct = 44
if 'basis' not in st.session_state: st.session_state.basis = 1260
if 'respons' not in st.session_state: st.session_state.respons = 45
if 'bud_elkedel' not in st.session_state: st.session_state.bud_elkedel = 50
if 'bud_motor' not in st.session_state: st.session_state.bud_motor = 800

def get_bio_produktion(tank_pct):
    if tank_pct <= 30: return 1000
    elif tank_pct <= 40: return 900
    elif tank_pct <= 50: return 800
    elif tank_pct <= 60: return 700
    elif tank_pct <= 90: return 600
    return 0

st.set_page_config(page_title="Skuldelev 48t Drift", page_icon="⚡", layout="wide")
st.title("Skuldelev Drifts-Agent ⚡")

# --- 2. DATA-HENTNING ---
@st.cache_data(ttl=600)
def hent_data():
    el_df, vejr_df = pd.DataFrame(), pd.DataFrame()
    try:
        url_el = "https://api.energidataservice.dk/dataset/Elspotprices?limit=150&filter={'PriceArea':['DK2']}"
        res_el = requests.get(url_el, timeout=10).json()['records']
        df_el = pd.DataFrame(res_el)
        df_el['Tid'] = pd.to_datetime(df_el['HourDK']).dt.tz_localize(None)
        el_df = df_el.sort_values('Tid')
    except: pass
    try:
        headers = {'User-Agent': 'SkuldelevApp/4.0'}
        url_v = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={LAT}&lon={LON}"
        res_v = requests.get(url_v, headers=headers, timeout=10).json()
        rows = []
        for entry in res_v['properties']['timeseries'][:48]:
            tid = pd.to_datetime(entry['time']).tz_convert('Europe/Copenhagen').tz_localize(None)
            rows.append({
                'Tid': tid,
                'Temp': entry['data']['instant']['details']['air_temperature'],
                'Vind': entry['data']['instant']['details']['wind_speed']
            })
        vejr_df = pd.DataFrame(rows)
    except: pass
    return el_df, vejr_df

el_df, vejr_df = hent_data()

# --- 3. SIDEBAR (MED HUKOMMELSE) ---
with st.sidebar:
    st.header("1. Aktuel Status")
    st.session_state.tank_pct = st.slider("Tank A (%)", 0, 100, st.session_state.tank_pct)
    tank_mwh_nu = (st.session_state.tank_pct / 100) * TANK_A_MAX_MWH
    
    st.divider()
    st.header("2. SCADA Trimning")
    st.session_state.basis = st.number_input("Basis v. 7°C (kW)", value=st.session_state.basis)
    st.session_state.respons = st.number_input("Respons (kW/grad)", value=st.session_state.respons)
    
    st.divider()
    st.header("3. mFRR Bud")
    st.session_state.bud_elkedel = st.number_input("Elkedel bud (Nedreg)", value=st.session_state.bud_elkedel)
    
    # Pris-estimat boks
    if not el_df.empty:
        nu = datetime.now()
        el_48 = el_df[el_df['Tid'] >= nu - timedelta(hours=1)].head(48).copy()
        t_kedel = len(el_48[el_48['SpotPriceDKK'] <= st.session_state.bud_elkedel])
        st.info(f"🎯 Elkedel: {t_kedel} t under bud")

    st.session_state.bud_motor = st.number_input("Motor bud (Opreg)", value=st.session_state.bud_motor)
    if not el_df.empty:
        t_motor = len(el_48[el_48['SpotPriceDKK'] >= st.session_state.bud_motor])
        st.info(f"🎯 Motor: {t_motor} t over bud")

# --- 4. BEREGNING ---
if not vejr_df.empty:
    prognose = vejr_df.copy()
    prognose['Tidspunkt'] = prognose['Tid'].dt.strftime('%d/%m %H:%M')
    beholdning = tank_mwh_nu
    beholdning_log, aftag_log = [], []
    for i, row in prognose.iterrows():
        temp_t = max(0, (15 - row['Temp']) * 0.8)
        vind_t = 3.0 if row['Vind'] < 3 else min(10, 3 + (row['Vind'] - 3) * 0.77)
        aftag_kw = st.session_state.basis + (temp_t + vind_t - 10.3) * st.session_state.respons
        aftag_log.append(aftag_kw)
        bio_kw = get_bio_produktion((beholdning/TANK_A_MAX_MWH)*100)
        beholdning = max(0, min(TANK_A_MAX_MWH, beholdning + (bio_kw - aftag_kw)/1000))
        beholdning_log.append(beholdning)
    prognose['Tank_MWh'] = beholdning_log
    prognose['Aftag_kW'] = aftag_log

# --- 5. ØKONOMI GRAF ---
st.header("mFRR Strategi & Priser")
if not el_df.empty:
    # Vi laver et rent datasæt til grafen for at undgå fejl
    plot_df = pd.DataFrame({
        'Tidspunkt': el_48['Tid'].dt.strftime('%d/%m %H:%M'),
        'Spotpris': el_48['SpotPriceDKK'].values,
        'Elkedel Bud': [st.session_state.bud_elkedel] * len(el_48),
        'Motor Bud': [st.session_state.bud_motor] * len(el_48)
    })
    st.line_chart(plot_df.set_index('Tidspunkt'))

# --- 6. DRIFT ---
st.divider()
cl, cr = st.columns(2)
with cl:
    st.subheader("Forventet Aftag (kW)")
    st.line_chart(prognose.set_index('Tidspunkt')['Aftag_kW'])
with cr:
    st.subheader("Tank-prognose (MWh)")
    st.line_chart(prognose.set_index('Tidspunkt')['Tank_MWh'])

# --- 7. HURTIGTJEK ---
st.divider()
st.header("Hurtigtjek: mFRR Varighed")
aftag_nu = prognose['Aftag_kW'].iloc[0] if not vejr_df.empty else 1260
b1, b2, b3 = st.columns(3)
with b1:
    if st.button("Tjek Elkedel"):
        netto = (get_bio_produktion(st.session_state.tank_pct) + 2000) - aftag_nu
        st.error(f"Fuld om: {round((TANK_A_MAX_MWH-tank_mwh_nu)/(max(netto,1)/1000), 1)} t")
with b2:
    if st.button("Tjek Motor"):
        netto = (get_bio_produktion(st.session_state.tank_pct) + 1200) - aftag_nu
        st.warning(f"Fuld om: {round((TANK_A_MAX_MWH-tank_mwh_nu)/(max(netto,1)/1000), 1)} t")
with b3:
    if st.button("Tjek Kun Bio"):
        netto = get_bio_produktion(st.session_state.tank_pct) - aftag_nu
        t = (tank_mwh_nu if netto < 0 else TANK_A_MAX_MWH - tank_mwh_nu) / (abs(netto)/1000)
        st.success(f"{'Tom' if netto < 0 else 'Fuld'} om: {round(t,1)} t")
