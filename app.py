import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- 1. KONFIGURATION (SKULDELEV SCADA LOGIK) ---
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

st.set_page_config(page_title="Skuldelev 48t Drift", page_icon="⚡", layout="wide")
st.title("Skuldelev Drifts-Agent (48 Timer) ⚡")

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
        headers = {'User-Agent': 'SkuldelevApp/2.0 kontakt: fjv@mail.dk'}
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

# --- 3. DASHBOARD SIDEBAR / INPUT ---
with st.sidebar:
    st.header("Aktuel Status")
    tank_pct_nu = st.slider("Tank A Indhold (%)", 0, 100, 44)
    tank_mwh_nu = (tank_pct_nu / 100) * TANK_A_MAX_MWH
    
    st.divider()
    st.header("SCADA Trimning")
    basis_ved_7gr = st.number_input("Basis v. 7°C (kW)", value=1260)
    respons_faktor = st.number_input("Respons (kW/grad)", value=45)

# --- 4. BEREGNING ---
if not vejr_df.empty:
    prognose = vejr_df.copy()
    prognose['Tidspunkt'] = prognose['Tid'].dt.strftime('%d/%m %H:%M')
    
    beholdning = tank_mwh_nu
    beholdning_log = []
    aftag_log = []

    for i, row in prognose.iterrows():
        # SCADA Logik (Udetemp + Vind)
        temp_tillæg = max(0, (15 - row['Temp']) * 0.8)
        vind_tillæg = 3.0 if row['Vind'] < 3 else min(10, 3 + (row['Vind'] - 3) * 0.77)
        samlet_setpunkt_ændring = temp_tillæg + vind_tillæg
        
        # Aftag beregning
        aftag_kw = basis_ved_7gr + (samlet_setpunkt_ændring - 10.3) * respons_faktor
        aftag_log.append(aftag_kw)
        
        # Tank simulation
        bio_kw = get_bio_produktion((beholdning/TANK_A_MAX_MWH)*100)
        netto_mwh = (bio_kw - aftag_kw) / 1000
        beholdning = max(0, min(TANK_A_MAX_MWH, beholdning + netto_mwh))
        beholdning_log.append(beholdning)
    
    prognose['Tank_MWh'] = beholdning_log
    prognose['Aftag_kW'] = aftag_log

# --- 5. VISNING AF GRAFER ---
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Forventet Aftag (kW)")
    st.line_chart(prognose.set_index('Tidspunkt')['Aftag_kW'], color="#ff4b4b")
    st.info(f"Aftag nu: **{round(prognose['Aftag_kW'].iloc[0])} kW**")

with col_right:
    st.subheader("Tank-beholdning (MWh)")
    st.line_chart(prognose.set_index('Tidspunkt')['Tank_MWh'], color="#29b5e8")
    
    # Hurtig status under grafen
    slut_mwh = beholdning_log[-1]
    tendens = "STIGENDE" if slut_mwh > tank_mwh_nu else "FALDENDE"
    st.write(f"Tendens over 48 timer: **{tendens}** (Slut: {round(slut_mwh,1)} MWh)")

st.divider()

st.subheader("Elpris (DK2) - 48 timer frem")
if not el_df.empty:
    nu_tid = datetime.now()
    el_plot = el_df[el_df['Tid'] >= nu_tid - timedelta(hours=1)].head(48).copy()
    el_plot['Tidspunkt'] = el_plot['Tid'].dt.strftime('%d/%m %H:%M')
    st.line_chart(el_plot.set_index('Tidspunkt')['SpotPriceDKK'], color="#2ecc71")
else:
    st.warning("Venter på pris-opdatering fra Energi Data Service...")

# --- 6. mFRR AKTIVERINGSTJEK ---
st.divider()
st.header("mFRR Aktiverings-tjek")
aftag_nu_calc = prognose['Aftag_kW'].iloc[0] if not vejr_df.empty else 1260

c1, c2, c3 = st.columns(3)
with c1:
    if st.button("Kør Elkedel (2MW)"):
        netto = (get_bio_produktion(tank_pct_nu) + 2000) - aftag_nu_calc
        timer = (TANK_A_MAX_MWH - tank_mwh_nu) / (max(netto, 1) / 1000)
        st.error(f"Tank fuld om: {round(timer, 1)} timer")
with c2:
    if st.button("Kør Motor (1.2MW)"):
        netto = (get_bio_produktion(tank_pct_nu) + 1200) - aftag_nu_calc
        timer = (TANK_A_MAX_MWH - tank_mwh_nu) / (max(netto, 1) / 1000)
        st.warning(f"Tank fuld om: {round(timer, 1)} timer")
with c3:
    if st.button("Kun Biokedel"):
        netto = get_bio_produktion(tank_pct_nu) - aftag_nu_calc
        timer = (tank_mwh_nu if netto < 0 else TANK_A_MAX_MWH - tank_mwh_nu) / (abs(netto) / 1000)
        st.success(f"Tank {'tom' if netto < 0 else 'fuld'} om: {round(timer, 1)} timer")
