import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- 1. KONFIGURATION (SKULDELEV) ---
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
        # Henter lidt ekstra el-data for at sikre 48 timer frem
        url_el = "https://api.energidataservice.dk/dataset/Elspotprices?limit=150&filter={'PriceArea':['DK2']}"
        res_el = requests.get(url_el, timeout=10).json()['records']
        df_el = pd.DataFrame(res_el)
        df_el['Tid'] = pd.to_datetime(df_el['HourDK']).dt.tz_localize(None)
        el_df = df_el.sort_values('Tid')
    except: pass

    try:
        headers = {'User-Agent': 'SkuldelevApp/3.0 kontakt: fjv@mail.dk'}
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

# --- 3. SIDEBAR / INPUT ---
with st.sidebar:
    st.header("1. Aktuel Status")
    tank_pct_nu = st.slider("Tank A Indhold (%)", 0, 100, 44)
    tank_mwh_nu = (tank_pct_nu / 100) * TANK_A_MAX_MWH
    
    st.divider()
    st.header("2. SCADA Trimning")
    basis_ved_7gr = st.number_input("Basis v. 7°C (kW)", value=1260)
    respons_faktor = st.number_input("Respons (kW/grad)", value=45)
    
    st.divider()
    st.header("3. mFRR Budpriser (kr/MWh)")
    # Her indtaster du dine grænser
    pris_elkedel = st.number_input("Elkedel bud (Nedregulering)", value=50, help="Ved hvilken spotpris vil du køre elkedel?")
    pris_motor = st.number_input("Motor bud (Opregulering)", value=800, help="Ved hvilken spotpris vil du starte motoren?")

# --- 4. BEREGNING ---
if not vejr_df.empty:
    prognose = vejr_df.copy()
    prognose['Tidspunkt'] = prognose['Tid'].dt.strftime('%d/%m %H:%M')
    
    beholdning = tank_mwh_nu
    beholdning_log, aftag_log = [], []

    for i, row in prognose.iterrows():
        # SCADA Logik
        temp_tillæg = max(0, (15 - row['Temp']) * 0.8)
        vind_tillæg = 3.0 if row['Vind'] < 3 else min(10, 3 + (row['Vind'] - 3) * 0.77)
        aftag_kw = basis_ved_7gr + (temp_tillæg + vind_tillæg - 10.3) * respons_faktor
        aftag_log.append(aftag_kw)
        
        # Tank simulation
        bio_kw = get_bio_produktion((beholdning/TANK_A_MAX_MWH)*100)
        netto_mwh = (bio_kw - aftag_kw) / 1000
        beholdning = max(0, min(TANK_A_MAX_MWH, beholdning + netto_mwh))
        beholdning_log.append(beholdning)
    
    prognose['Tank_MWh'] = beholdning_log
    prognose['Aftag_kW'] = aftag_log

# --- 5. ØKONOMISK ANALYSE ---
st.header("Økonomisk Overblik (mFRR Strategi)")
if not el_df.empty:
    nu_tid = datetime.now()
    el_48 = el_df[el_df['Tid'] >= nu_tid - timedelta(hours=1)].head(48).copy()
    
    # Tæl gunstige timer
    timer_elkedel = len(el_48[el_48['SpotPriceDKK'] <= pris_elkedel])
    timer_motor = len(el_48[el_48['SpotPriceDKK'] >= pris_motor])
    
    col_eco1, col_eco2, col_eco3 = st.columns(3)
    col_eco1.metric("Elkedel-vindue (48t)", f"{timer_elkedel} timer", f"Pris <= {pris_elkedel} kr")
    col_eco2.metric("Motor-vindue (48t)", f"{timer_motor} timer", f"Pris >= {pris_motor} kr")
    col_eco3.metric("Spotpris lige nu", f"{round(el_48['SpotPriceDKK'].iloc[0])} kr")

# --- 6. GRAFER ---
st.divider()
c_left, c_right = st.columns(2)
with c_left:
    st.subheader("Forventet Aftag (kW)")
    st.line_chart(prognose.set_index('Tidspunkt')['Aftag_kW'], color="#ff4b4b")
with c_right:
    st.subheader("Tank-prognose (MWh)")
    st.line_chart(prognose.set_index('Tidspunkt')['Tank_MWh'], color="#29b5e8")

st.subheader("Elpriser (kr/MWh) med bud-grænser")
if not el_df.empty:
    el_48['Klokkeslæt'] = el_48['Tid'].dt.strftime('%d/%m %H:%M')
    # Vi tilføjer bud-linjerne til grafen så man kan se dem visuelt
    el_48['Elkedel bud'] = pris_elkedel
    el_48['Motor bud'] = pris_motor
    st.line_chart(el_48.set_index('Klokkeslæt')[['SpotPriceDKK', 'Elkedel bud', 'Motor bud']], color=["#2ecc71", "#ff9f43", "#ee5253"])

# --- 7. mFRR AKTIVERINGSTJEK ---
st.divider()
st.header("Hurtigtjek: Hvor længe kan jeg køre?")
aftag_nu_calc = prognose['Aftag_kW'].iloc[0] if not vejr_df.empty else 1260
c1, c2, c3 = st.columns(3)
with c1:
    if st.button("Tjek Elkedel (Nedreg)"):
        netto = (get_bio_produktion(tank_pct_nu) + 2000) - aftag_nu_calc
        st.error(f"Tank fuld om {round((TANK_A_MAX_MWH-tank_mwh_nu)/(max(netto,1)/1000), 1)} t")
with c2:
    if st.button("Tjek Motor (Opreg)"):
        netto = (get_bio_produktion(tank_pct_nu) + 1200) - aftag_nu_calc
        st.warning(f"Tank fuld om {round((TANK_A_MAX_MWH-tank_mwh_nu)/(max(netto,1)/1000), 1)} t")
with c3:
    if st.button("Tjek Kun Bio"):
        netto = get_bio_produktion(tank_pct_nu) - aftag_nu_calc
        tid = (tank_mwh_nu if netto < 0 else TANK_A_MAX_MWH - tank_mwh_nu) / (abs(netto) / 1000)
        st.success(f"Fuld/tom om {round(tid, 1)} t")
