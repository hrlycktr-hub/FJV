import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- 1. KONFIGURATION ---
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

st.set_page_config(page_title="Skuldelev Drifts-Agent", page_icon="⚡")
st.title("Skuldelev Drifts-Agent ⚡")

# --- 2. DATA-HENTNING ---
@st.cache_data(ttl=600)
def hent_data():
    el_df = pd.DataFrame()
    vejr_df = pd.DataFrame()
    
    # ELPRISER - Henter de nyeste og sorterer dem
    try:
        url_el = "https://api.energidataservice.dk/dataset/Elspotprices?limit=100&filter={'PriceArea':['DK2']}"
        res_el = requests.get(url_el, timeout=10).json()['records']
        el_df = pd.DataFrame(res_el)
        el_df['Tid'] = pd.to_datetime(el_df['HourDK']).dt.tz_localize(None)
        el_df = el_df.sort_values('Tid')
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
basis_aftag = col_scada1.number_input("Basis v. 10°C (kW)", value=850)
vejr_faktor = col_scada2.number_input("kW stigning pr. grad fald", value=65)

# --- 4. BEREGNING AF PROGNOSE ---
if not vejr_df.empty:
    prognose = vejr_df.copy()
    beholdning = tank_mwh_nu
    beholdning_log = []
    aftag_log = []

    for i, row in prognose.iterrows():
        aftag_kw = basis_aftag + ((10 - row['Temp']) * vejr_faktor)
        aftag_log.append(aftag_kw)
        bio_kw = get_bio_produktion((beholdning/TANK_A_MAX_MWH)*100)
        netto_mwh = (bio_kw - aftag_kw) / 1000
        beholdning = max(0, min(TANK_A_MAX_MWH, beholdning + netto_mwh))
        beholdning_log.append(beholdning)
    
    prognose['Tank_MWh'] = beholdning_log
    prognose['Aftag_kW'] = aftag_log

# --- 5. VISNING AF GRAFER ---
st.write("---")

# GRAF 1: ELPRIS (Fremadrettet)
st.subheader("Elpris næste 24 timer (kr/MWh)")
if not el_df.empty:
    nu = datetime.now()
    el_fremtid = el_df[el_df['Tid'] >= nu - timedelta(hours=1)].head(24)
    st.line_chart(el_fremtid.set_index('Tid')['SpotPriceDKK'])
    st.info(f"Pris lige nu: **{round(el_fremtid['SpotPriceDKK'].iloc[0])} kr**")

# GRAF 2: AFTAG
st.write("---")
st.subheader("Aftags-prognose (kW)")
if not vejr_df.empty:
    # Vi bruger set_index('Tid') for at få klokkeslæt på aksen
    st.line_chart(prognose.set_index('Tid')['Aftag_kW'])
    st.caption(f"Forventet aftag nu: {round(prognose['Aftag_kW'].iloc[0])} kW")

# GRAF 3: TANK
st.write("---")
st.subheader("Tank-beholdning (MWh)")
if not vejr_df.empty:
    st.line_chart(prognose.set_index('Tid')['Tank_MWh'])

# --- 6. mFRR BEREGNER ---
st.write("---")
st.header("2. Aktiverings-tjek")
aftag_nu_calc = prognose['Aftag_kW'].iloc[0] if not vejr_df.empty else 1300

c1, c2 = st.columns(2)
with c1:
    if st.button("Tjek Elkedel"):
        bio = get_bio_produktion(tank_pct_nu)
        netto = (bio + 2000) - aftag_nu_calc
        timer = (TANK_A_MAX_MWH - tank_mwh_nu) / (max(netto, 1) / 1000)
        st.error(f"Tank A fuld om ca. {round(timer, 1)} timer.")

with c2:
    if st.button("Tjek Motor"):
        bio = get_bio_produktion(tank_pct_nu)
        netto = (bio + 1200) - aftag_nu_calc
        if netto > 0:
            timer = (TANK_A_MAX_MWH - tank_mwh_nu) / (netto / 1000)
            st.warning(f"Tank A fuld om ca. {round(timer, 1)} timer.")
        else:
            timer = tank_mwh_nu / (abs(netto) / 1000)
            st.success(f"Tank tømmes. 0% om {round(timer, 1)} timer.")
