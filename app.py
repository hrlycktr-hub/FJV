import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- 1. KONFIGURATION (SCADA TAL) ---
TANK_A_MAX_MWH = 70.0  
ELKEDEL_MW = 2.0       
MOTOR_VARME_MW = 1.2   
LAT, LON = 55.79, 12.02

def get_bio_produktion(tank_pct):
    if tank_pct <= 30: return 1000
    elif tank_pct <= 40: return 900
    elif tank_pct <= 50: return 800
    elif tank_pct <= 60: return 700
    elif tank_pct <= 90: return 600
    return 0

st.set_page_config(page_title="Skuldelev Prognose", page_icon="⚡")
st.title("Skuldelev Drifts-Agent ⚡")

# --- 2. DATA-HENTNING ---
@st.cache_data(ttl=600)
def hent_data():
    el_df = pd.DataFrame()
    vejr_df = pd.DataFrame()
    
    # ELPRISER
    try:
        url_el = "https://api.energidataservice.dk/dataset/Elspotprices?limit=50&filter={'PriceArea':['DK2']}"
        res_el = requests.get(url_el, timeout=10).json()['records']
        el_df = pd.DataFrame(res_el)
        el_df['HourDK'] = pd.to_datetime(el_df['HourDK']).dt.tz_localize(None)
    except: pass

    # VEJR FRA YR.NO
    try:
        headers = {'User-Agent': 'SkuldelevApp/2.0 kontakt: fjv@mail.dk'}
        url_v = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={LAT}&lon={LON}"
        res_v = requests.get(url_v, headers=headers, timeout=10).json()
        rows = []
        for entry in res_v['properties']['timeseries'][:24]:
            rows.append({
                'Tid': pd.to_datetime(entry['time']).tz_convert('Europe/Copenhagen').tz_localize(None),
                'Temp': entry['data']['instant']['details']['air_temperature']
            })
        vejr_df = pd.DataFrame(rows)
    except: pass
    
    return el_df, vejr_df

el_df, vejr_df = hent_data()

# --- 3. INPUT ---
st.header("1. Status & SCADA")
tank_pct_nu = st.slider("Aktuel Tank A (%)", 0, 100, 44)
tank_mwh_nu = (tank_pct_nu / 100) * TANK_A_MAX_MWH

col_scada1, col_scada2 = st.columns(2)
basis_aftag = col_scada1.number_input("Basis v. 10°C (kW)", value=620)
vejr_faktor = col_scada2.number_input("kW stigning pr. grad fald", value=48)

# --- 4. BEREGNING AF PROGNOSE ---
if not vejr_df.empty:
    prognose = vejr_df.copy()
    beholdning = tank_mwh_nu
    beholdning_log = []
    aftag_log = []

    for i, row in prognose.iterrows():
        # Beregn aftag baseret på dine SCADA-tal
        aftag_kw = basis_aftag + ((10 - row['Temp']) * vejr_faktor)
        aftag_log.append(aftag_kw)
        
        # Beregn hvad biokedlen gør ved den beholdning
        bio_kw = get_bio_produktion((beholdning/TANK_A_MAX_MWH)*100)
        
        # Opdater tanken
        netto_mwh = (bio_kw - aftag_kw) / 1000
        beholdning = max(0, min(TANK_A_MAX_MWH, beholdning + netto_mwh))
        beholdning_log.append(beholdning)
    
    prognose['Tank_MWh'] = beholdning_log
    prognose['Aftag_kW'] = aftag_log

# --- 5. GRAFER ---
st.write("---")

# Graf 1: Elpris
st.subheader("Elpris (DK2)")
if not el_df.empty:
    st.line_chart(el_df.sort_values('HourDK'), x='HourDK', y='SpotPriceDKK')
    aktuel_pris = el_df.iloc[0]['SpotPriceDKK']
else:
    st.warning("Venter på elpriser...")
    aktuel_pris = 250

# Graf 2: Aftag pr. time (Det du bad om)
st.write("---")
st.subheader("Forventet Aftag pr. time (kW)")
if not vejr_df.empty:
    st.line_chart(prognose, x='Tid', y='Aftag_kW')
    st.caption(f"Baseret på temperaturudsigt for Skuldelev. Nu: {round(prognose['Aftag_kW'].iloc[0])} kW")

# Graf 3: Tank-beholdning
st.write("---")
st.subheader("Tank-prognose (MWh)")
if not vejr_df.empty:
    st.line_chart(prognose, x='Tid', y='Tank_MWh')
    st.caption("Viser tankens indhold hvis kun biokedlen kører.")

# --- 6. mFRR BEREGNER ---
st.write("---")
st.header("2. Aktiverings-tjek")
aftag_nu = prognose['Aftag_kW'].iloc[0] if not vejr_df.empty else 1000

col_btn1, col_btn2 = st.columns(2)
with col_btn1:
    if st.button("Tjek Elkedel nu"):
        bio = get_bio_produktion(tank_pct_nu)
        netto = (bio + 2000) - aftag_nu
        timer = (TANK_A_MAX_MWH - tank_mwh_nu) / (max(netto, 1) / 1000)
        st.error(f"Tank A rammer 100% om {round(timer, 1)} timer.")

with col_btn2:
    if st.button("Tjek Motor nu"):
        bio = get_bio_produktion(tank_pct_nu)
        netto = (bio + 1200) - aftag_nu
        timer = (TANK_A_MAX_MWH - tank_mwh_nu) / (max(netto, 1) / 1000)
        st.warning(f"Tank A rammer 100% om {round(timer, 1)} timer.")
