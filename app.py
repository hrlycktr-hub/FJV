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
    
    try:
        url_el = "https://api.energidataservice.dk/dataset/Elspotprices?limit=100&filter={'PriceArea':['DK2']}"
        res_el = requests.get(url_el, timeout=10).json()['records']
        df_el = pd.DataFrame(res_el)
        df_el['Tid'] = pd.to_datetime(df_el['HourDK']).dt.tz_localize(None)
        el_df = df_el.sort_values('Tid')
    except: pass

    try:
        headers = {'User-Agent': 'SkuldelevApp/2.0 kontakt: fjv@mail.dk'}
        url_v = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={LAT}&lon={LON}"
        res_v = requests.get(url_v, headers=headers, timeout=10).json()
        rows = []
        for entry in res_v['properties']['timeseries'][:24]:
            tid = pd.to_datetime(entry['time']).tz_convert('Europe/Copenhagen').tz_localize(None)
            rows.append({
                'Tid': tid,
                'Temp': entry['data']['instant']['details']['air_temperature']
            })
        vejr_df = pd.DataFrame(rows)
    except: pass
    
    return el_df, vejr_df

el_df, vejr_df = hent_data()

# --- 3. INPUT (OPTIMERET TIL 1260 KW VED ~5.5 GRADER) ---
st.header("1. Status & SCADA")
tank_pct_nu = st.slider("Aktuel Tank A (%)", 0, 100, 44)
tank_mwh_nu = (tank_pct_nu / 100) * TANK_A_MAX_MWH

col_scada1, col_scada2 = st.columns(2)
# Disse tal er nu fintrimmet til jeres 1260 kW observation
basis_aftag = col_scada1.number_input("Basis v. 10°C (kW)", value=950)
vejr_faktor = col_scada2.number_input("kW stigning pr. grad fald", value=70)

# --- 4. BEREGNING AF PROGNOSE ---
if not vejr_df.empty:
    prognose = vejr_df.copy()
    # 24-timers format til graferne
    prognose['Klokkeslæt'] = prognose['Tid'].dt.strftime('%H:%M')
    
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

# --- 5. GRAFER (24-TIMERS FORMAT) ---
st.write("---")

# ELPRIS
if not el_df.empty:
    nu_tid = datetime.now()
    el_plot = el_df[el_df['Tid'] >= nu_tid - timedelta(hours=1)].head(24).copy()
    el_plot['Klokkeslæt'] = el_plot['Tid'].dt.strftime('%H:%M')
    st.subheader("Elpris (kr/MWh)")
    st.line_chart(el_plot.set_index('Klokkeslæt')['SpotPriceDKK'])

# AFTAG
st.write("---")
st.subheader("Forventet Aftag (kW)")
if not vejr_df.empty:
    st.line_chart(prognose.set_index('Klokkeslæt')['Aftag_kW'])
    st.info(f"Beregnet aftag nu: **{round(prognose['Aftag_kW'].iloc[0])} kW** (ved {vejr_df.iloc[0]['Temp']}°C)")

# TANK
st.write("---")
st.subheader("Tank-prognose (MWh)")
if not vejr_df.empty:
    st.line_chart(prognose.set_index('Klokkeslæt')['Tank_MWh'])

# --- 6. mFRR BEREGNER ---
st.write("---")
st.header("2. Aktiverings-tjek")
aftag_nu_calc = prognose['Aftag_kW'].iloc[0] if not vejr_df.empty else 1260

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
