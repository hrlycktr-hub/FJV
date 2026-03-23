import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- 1. KONFIGURATION ---
TANK_A_MAX_MWH = 70.0  
LAT, LON = 55.79, 12.02

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
    el_df = pd.DataFrame()
    vejr_df = pd.DataFrame()
    try:
        url_el = "https://api.energidataservice.dk/dataset/Elspotprices?limit=150&filter={'PriceArea':['DK2']}"
        res_el = requests.get(url_el, timeout=10).json()['records']
        df_el = pd.DataFrame(res_el)
        df_el['Tid'] = pd.to_datetime(df_el['HourDK']).dt.tz_localize(None)
        el_df = df_el.sort_values('Tid')
    except: pass
    try:
        headers = {'User-Agent': 'SkuldelevApp/3.0'}
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

# --- 3. SIDEBAR MED ØKONOMISK ESTIMAT ---
with st.sidebar:
    st.header("1. Aktuel Status")
    tank_pct_nu = st.slider("Tank A Indhold (%)", 0, 100, 44)
    tank_mwh_nu = (tank_pct_nu / 100) * TANK_A_MAX_MWH
    
    st.divider()
    st.header("2. SCADA Trimning")
    basis_ved_7gr = st.number_input("Basis v. 7°C (kW)", value=1260)
    respons_faktor = st.number_input("Respons (kW/grad)", value=45)
    
    st.divider()
    st.header("3. mFRR Bud & Estimater")
    
    # Elkedel bud
    pris_elkedel = st.number_input("Elkedel bud (Nedreg)", value=50)
    if not el_df.empty:
        nu = datetime.now()
        el_48 = el_df[el_df['Tid'] >= nu - timedelta(hours=1)].head(48)
        t_kedel = len(el_48[el_48['SpotPriceDKK'] <= pris_elkedel])
        st.caption(f"🎯 Prisen er under dit bud i **{t_kedel} ud af 48 timer**.")
    
    st.write("") # Mellemrum
    
    # Motor bud
    pris_motor = st.number_input("Motor bud (Opreg)", value=800)
    if not el_df.empty:
        t_motor = len(el_48[el_48['SpotPriceDKK'] >= pris_motor])
        st.caption(f"🎯 Prisen er over dit bud i **{t_motor} ud af 48 timer**.")

# --- 4. BEREGNING AF DRIFT ---
if not vejr_df.empty:
    prognose = vejr_df.copy()
    prognose['Tidspunkt'] = prognose['Tid'].dt.strftime('%d/%m %H:%M')
    beholdning = tank_mwh_nu
    beholdning_log, aftag_log = [], []
    for i, row in prognose.iterrows():
        temp_tillæg = max(0, (15 - row['Temp']) * 0.8)
        vind_tillæg = 3.0 if row['Vind'] < 3 else min(10, 3 + (row['Vind'] - 3) * 0.77)
        aftag_kw = basis_ved_7gr + (temp_tillæg + vind_tillæg - 10.3) * respons_faktor
        aftag_log.append(aftag_kw)
        bio_kw = get_bio_produktion((beholdning/TANK_A_MAX_MWH)*100)
        beholdning = max(0, min(TANK_A_MAX_MWH, beholdning + (bio_kw - aftag_kw)/1000))
        beholdning_log.append(beholdning)
    prognose['Tank_MWh'] = beholdning_log
    prognose['Aftag_kW'] = aftag_log

# --- 5. VISNING ---
st.header("mFRR Strategi & Priser")
if not el_df.empty:
    el_plot_data = el_48[['Tid', 'SpotPriceDKK']].copy()
    el_plot_data['Elkedel bud'] = pris_elkedel
    el_plot_data['Motor bud'] = pris_motor
    el_plot_data['Tidspunkt'] = el_plot_data['Tid'].dt.strftime('%d/%m %H:%M')
    st.line_chart(el_plot_data.set_index('Tidspunkt')[['SpotPriceDKK', 'Elkedel bud', 'Motor bud']])

st.divider()
cl, cr = st.columns(2)
with cl:
    st.subheader("Forventet Aftag (kW)")
    st.line_chart(prognose.set_index('Tidspunkt')['Aftag_kW'])
with cr:
    st.subheader("Tank-prognose (MWh)")
    st.line_chart(prognose.set_index('Tidspunkt')['Tank_MWh'])

st.divider()
st.header("Hurtigtjek: mFRR Varighed")
aftag_nu = prognose['Aftag_kW'].iloc[0] if not vejr_df.empty else 1260
b1, b2, b3 = st.columns(3)
with b1:
    if st.button("Tjek Elkedel"):
        netto = (get_bio_produktion(tank_pct_nu) + 2000) - aftag_nu
        st.error(f"Fuld om: {round((TANK_A_MAX_MWH-tank_mwh_nu)/(max(netto,1)/1000), 1)} t")
with b2:
    if st.button("Tjek Motor"):
        netto = (get_bio_produktion(tank_pct_nu) + 1200) - aftag_nu
        st.warning(f"Fuld om: {round((TANK_A_MAX_MWH-tank_mwh_nu)/(max(netto,1)/1000), 1)} t")
with b3:
    if st.button("Tjek Kun Bio"):
        netto = get_bio_produktion(tank_pct_nu) - aftag_nu
        t = (tank_mwh_nu if netto < 0 else TANK_A_MAX_MWH - tank_mwh_nu) / (abs(netto)/1000)
        st.success(f"{'Tom' if netto < 0 else 'Fuld'} om: {round(t,1)} t")
