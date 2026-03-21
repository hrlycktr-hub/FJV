import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- 1. GRUNDLÆGGENDE KONFIGURATION ---
TANK_A_MAX_MWH = 70.0  
ELKEDEL_MW = 2.0       
MOTOR_VARME_MW = 1.2   
LAT, LON = 55.79, 12.02  # Skuldelev

def get_bio_produktion(tank_pct):
    """Regulerer biokedel baseret på tankens fyldningsgrad"""
    if tank_pct <= 30: return 1000
    elif tank_pct <= 40: return 900
    elif tank_pct <= 50: return 800
    elif tank_pct <= 60: return 700
    elif tank_pct <= 90: return 600
    return 0

st.set_page_config(page_title="Skuldelev Drift & Prognose", page_icon="⚡", layout="wide")
st.title("Skuldelev Drifts-Agent ⚡")

# --- 2. DATA-HENTNING (EL + VEJR) ---
@st.cache_data(ttl=600)
def hent_alle_data():
    # ELPRISER (Energi Data Service)
    el_df = pd.DataFrame()
    try:
        url_el = "https://api.energidataservice.dk/dataset/Elspotprices?limit=100&filter={'PriceArea':['DK2']}"
        res_el = requests.get(url_el, timeout=10).json()['records']
        el_df = pd.DataFrame(res_el)
        el_df['HourDK'] = pd.to_datetime(el_df['HourDK']).dt.tz_localize(None)
    except: pass

    # VEJR (Yr.no API)
    vejr_df = pd.DataFrame()
    try:
        headers = {'User-Agent': 'SkuldelevFJV/2.0 kontakt: fjv@skuldelev.dk'}
        url_v = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={LAT}&lon={LON}"
        res_v = requests.get(url_v, headers=headers, timeout=10).json()
        rows = []
        for entry in res_v['properties']['timeseries'][:48]: # Næste 48 timer
            rows.append({
                'Tid': pd.to_datetime(entry['time']).tz_convert('Europe/Copenhagen').tz_localize(None),
                'Temp': entry['data']['instant']['details']['air_temperature']
            })
        vejr_df = pd.DataFrame(rows)
    except: pass
    
    return el_df, vejr_df

el_df, vejr_df = hent_alle_data()

# --- 3. INPUT SEKTION (SCADA-BASERET) ---
st.header("1. Aktuel Status & SCADA-faktorer")
col1, col2, col3, col4 = st.columns(4)

with col1:
    tank_pct_nu = st.number_input("Tank A (%)", 0, 100, 44)
    tank_mwh_nu = (tank_pct_nu / 100) * TANK_A_MAX_MWH
with col2:
    # Baseret på jeres tal: 7000 MWh produktion / 4800 MWh salg
    basis_aftag = st.number_input("Basis-aftag v. 10°C (kW)", value=620)
with col3:
    vejr_faktor = st.number_input("Vejr-faktor (kW pr. grad)", value=48)
with col4:
    tarif_el = st.number_input("Tarif/Afgift (kr/MWh)", value=150)

# --- 4. ØKONOMI OG CHANCER ---
st.write("---")
if not el_df.empty:
    aktuel_pris = el_df.iloc[0]['SpotPriceDKK']
    total_el_pris = aktuel_pris + tarif_el
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Spotpris (DK2)", f"{round(aktuel_pris)} kr")
    c2.metric("Total Elkedel Pris", f"{round(total_el_pris)} kr")
    
    # Budforslag
    st.info(f"💡 **Bud-guide:** Elkedel: >{round(aktuel_pris+60)} kr ({round(aktuel_pris+25)} kr) | Motor: <{round(aktuel_pris-70)} kr ({round(aktuel_pris-30)} kr)")
else:
    aktuel_pris = 250.0

# --- 5. TANK-PROGNOSE (DYNAMISK) ---
if not vejr_df.empty:
    st.header("2. Fremtids-prognose (Næste 24 timer)")
    
    # Beregn time for time
    prognose = vejr_df.copy().head(24)
    nu_beholdning = tank_mwh_nu
    beholdning_liste = []
    aftag_liste = []

    for i, row in prognose.iterrows():
        # 1. Beregn aftag for denne time
        temp = row['Temp']
        aftag_kw = basis_aftag + ((10 - temp) * vejr_faktor)
        aftag_liste.append(aftag_kw)
        
        # 2. Beregn biokedel produktion
        aktuel_pct = (nu_beholdning / TANK_A_MAX_MWH) * 100
        bio_kw = get_bio_produktion(aktuel_pct)
        
        # 3. Opdater beholdning (Netto MWh)
        netto_mwh = (bio_kw - aftag_kw) / 1000
        nu_beholdning = max(0, min(TANK_A_MAX_MWH, nu_beholdning + netto_mwh))
        beholdning_liste.append(nu_beholdning)

    prognose['Forventet Aftag (kW)'] = aftag_liste
    prognose['Tank Indhold (MWh)'] = beholdning_liste

    # Vis grafer
    tab1, tab2 = st.tabs(["Tank-beholdning", "Vejr & Aftag"])
    with tab1:
        st.line_chart(prognose, x='Tid', y='Tank Indhold (MWh)')
        st.caption("Grafen viser hvordan tanken bevæger sig KUN med biokedel + vejr-aftag.")
    with tab2:
        st.line_chart(prognose, x='Tid', y=['Temp', 'Forventet Aftag (kW)'])

# --- 6. mFRR BEREGNER ---
st.write("---")
st.header("3. Aktiverings-beregner")
col_b1, col_b2 = st.columns(2)

# Beregn aktuelt aftag for nuværende time
temp_nu = vejr_df.iloc[0]['Temp'] if not vejr_df.empty else 10
aftag_nu = basis_aftag + ((10 - temp_nu) * vejr_faktor)

with col_b1:
    st.subheader("Elkedel (Ned)")
    if st.button("Beregn Elkedel"):
        bio = get_bio_produktion(tank_pct_nu)
        netto = (bio + (ELKEDEL_MW * 1000)) - aftag_nu
        timer = (TANK_A_MAX_MWH - tank_mwh_nu) / (max(netto, 1) / 1000)
        st.error(f"Ved aktivering: Tank A er 100% fyldt om {round(timer, 1)} timer.")

with col_b2:
    st.subheader("Motor (Op)")
    if st.button("Beregn Motor"):
        bio = get_bio_produktion(tank_pct_nu)
        netto = (bio + (MOTOR_VARME_MW * 1000)) - aftag_nu
        if netto > 0:
            timer = (TANK_A_MAX_MWH - tank_mwh_nu) / (netto / 1000)
            st.warning(f"Ved aktivering: Tank A er 100% fyldt om {round(timer, 1)} timer.")
        else:
            timer = tank_mwh_nu / (abs(netto) / 1000)
            st.success(f"Tanken tømmes stadig. 0% om {round(timer, 1)} timer.")
