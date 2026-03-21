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

    # VEJR
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
tank_pct_nu = st.slider("Tank A (%)", 0, 100, 44)
tank_mwh_nu = (tank_pct_nu / 100) * TANK_A_MAX_MWH

col_scada1, col_scada2 = st.columns(2)
basis_aftag = col_scada1.number_input("Basis v. 10°C (kW)", value=620)
vejr_faktor = col_scada2.number_input("kW pr. grad fald", value=48)

# --- 4. ELPRIS GRAF ---
st.write("---")
st.subheader("Elpris (DK2)")
if not el_df.empty:
    # Vi sikrer os at vi kun viser relevante timer
    el_plot = el_df.sort_values('HourDK')
    st.line_chart(el_plot, x='HourDK', y='SpotPriceDKK')
    aktuel_pris = el_df.iloc[0]['SpotPriceDKK']
    st.info(f"Pris nu: {round(aktuel_pris)} kr/MWh")
else:
    st.error("Kunne ikke hente el-grafer")
    aktuel_pris = 250.0

# --- 5. TANK & VEJR PROGNOSE ---
st.write("---")
st.subheader("Tank-prognose (Næste 24 timer)")
if not vejr_df.empty:
    # Simulation
    prognose = vejr_df.copy()
    beholdning = tank_mwh_nu
    log = []

    for i, row in prognose.iterrows():
        aftag_kw = basis_aftag + ((10 - row['Temp']) * vejr_faktor)
        bio_kw = get_bio_produktion((beholdning/TANK_A_MAX_MWH)*100)
        netto_mwh = (bio_kw - aftag_kw) / 1000
        beholdning = max(0, min(TANK_A_MAX_MWH, beholdning + netto_mwh))
        log.append(beholdning)
    
    prognose['Tank_MWh'] = log
    st.line_chart(prognose, x='Tid', y='Tank_MWh')
    
    nu_temp = vejr_df.iloc[0]['Temp']
    st.write(f"Temperatur lige nu: **{nu_temp}°C**")
else:
    st.warning("Vejr-data mangler, så tank-prognosen kan ikke tegnes.")

# --- 6. mFRR BEREGNER ---
st.write("---")
st.header("2. Aktiverings-tjek")
temp_nu = vejr_df.iloc[0]['Temp'] if not vejr_df.empty else 10
aftag_nu = basis_aftag + ((10 - temp_nu) * vejr_faktor)

if st.button("Hvad sker der hvis ELKEDEL kører nu?"):
    bio = get_bio_produktion(tank_pct_nu)
    netto = (bio + 2000) - aftag_nu
    timer = (TANK_A_MAX_MWH - tank_mwh_nu) / (max(netto, 1) / 1000)
    st.error(f"Tank A rammer 100% om ca. {round(timer, 1)} timer.")

if st.button("Hvad sker der hvis MOTOR kører nu?"):
    bio = get_bio_produktion(tank_pct_nu)
    netto = (bio + 1200) - aftag_nu
    timer = (TANK_A_MAX_MWH - tank_mwh_nu) / (max(netto, 1) / 1000)
    st.warning(f"Tank A rammer 100% om ca. {round(timer, 1)} timer.")
