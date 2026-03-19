import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- 1. KONFIGURATION ---
TANK_A_MAX_MWH = 70.0  
ELKEDEL_MW = 2.0       
MOTOR_VARME_MW = 1.2   

def get_bio(p):
    if p <= 30: return 1000
    elif p <= 40: return 900
    elif p <= 50: return 800
    elif p <= 60: return 700
    elif p <= 90: return 600
    return 0

st.set_page_config(page_title="Skuldelev Drift", page_icon="⚡")
st.title("Skuldelev Drifts-Agent ⚡")

# --- 2. DATA-HENTNING ---
@st.cache_data(ttl=600)
def hent_el_data():
    try:
        url = "https://api.energidataservice.dk/dataset/Elspotprices?limit=100"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            raw_data = response.json()['records']
            df = pd.DataFrame(raw_data)
            df = df[df['PriceArea'] == 'DK2']
            df['HourDK'] = pd.to_datetime(df['HourDK'])
            return df.sort_values('HourDK', ascending=False)
        return pd.DataFrame()
    except:
        return pd.DataFrame()

el_df = hent_el_data()

# --- 3. STATUS & GRÆNSER ---
st.header("1. Aktuel Status & Max-priser")
col_s1, col_s2 = st.columns(2)
with col_s1:
    tank_pct = st.number_input("Tank A (%)", 0, 100, 44)
    tank_mwh = (tank_pct / 100) * TANK_A_MAX_MWH
with col_s2:
    aftag_nu = st.number_input("Aftag (kW)", 0, 3000, 1000)

# Økonomiske stop-grænser
col_m1, col_m2 = st.columns(2)
with col_m1:
    max_pris_el = st.number_input("Max pris Elkedel (kr/MWh)", value=400)
with col_m2:
    max_pris_mot = st.number_input("Max pris Motor (kr/MWh)", value=800)

# --- 4. VISNING AF PRIS ---
st.write("---")
if not el_df.empty:
    nu = datetime.now()
    vis_df = el_df[(el_df['HourDK'] >= (nu - timedelta(hours=6)))].sort_values('HourDK')
    aktuel_pris = el_df.iloc[0]['SpotPriceDKK']
    
    st.subheader(f"Spotpris lige nu: {round(aktuel_pris, 2)} kr")
    st.line_chart(vis_df, x='HourDK', y='SpotPriceDKK')
else:
    aktuel_pris = st.number_input("Manuel Elpris (kr/MWh)", value=250)

# --- 5. mFRR ELKEDEL (NED) ---
st.header("2. mFRR Elkedel (Ned)")

# Tjek om spotprisen er for høj til elkedel-drift
if aktuel_pris > max_pris_el:
    st.error(f"🚫 Økonomisk Stop: Spotprisen er for høj til elkedel-drift (> {max_pris_el} kr)")

anbefalet_el = aktuel_pris + 60
budloeb_el = aktuel_pris + 25
st.markdown(f"💡 *Anbefalet bud for aktivering:* **>{round(anbefalet_el)} kr** ({round(budloeb_el)} kr)")

bud_elkedel = st.number_input("Dit bud Elkedel (kr/MWh)", value=int(anbefalet_el), key="el_bud")

if st.button("Beregn Elkedel-scenarie"):
    bio = get_bio(tank_pct)
    netto = (bio + (ELKEDEL_MW * 1000)) - aftag_nu
    timer = (TANK_A_MAX_MWH - tank_mwh) / (max(netto, 1) / 1000)
    st.error(f"Ved aktivering: Tank A er 100% fyldt om ca. {round(timer, 1)} timer.")

# --- 6. mFRR MOTOR (OP) ---
st.write("---")
st.header("3. mFRR Motor (Op)")

# Tjek om spotprisen er for høj til rentabel motordrift
if aktuel_pris > max_pris_mot:
    st.error(f"🚫 Økonomisk Stop: Spotprisen er for høj til motordrift (> {max_pris_mot} kr)")

anbefalet_mot = aktuel_pris - 70
budloeb_mot = aktuel_pris - 30
st.markdown(f"💡 *Anbefalet bud for aktivering:* **<{round(anbefalet_mot)} kr** ({round(budloeb_mot)} kr)")

bud_motor = st.number_input("Dit bud Motor (kr/MWh)", value=int(anbefalet_mot), key="mot_bud")

if st.button("Beregn Motor-scenarie"):
    bio = get_bio(tank_pct)
    netto = (bio + (MOTOR_VARME_MW * 1000)) - aftag_nu
    timer = (TANK_A_MAX_MWH - tank_mwh) / (max(netto, 1) / 1000)
    st.warning(f"Ved aktivering: Tank A er 100% fyldt om ca. {round(timer, 1)} timer.")

# --- 7. NORMAL DRIFT ---
st.write("---")
if st.button("BEREGN NORMAL DRIFT", type="primary"):
    bio = get_bio(tank_pct)
    netto = bio - aftag_nu
    st.info(f"Biokedel last: {bio} kW")
    if netto > 0:
        timer = (TANK_A_MAX_MWH - tank_mwh) / (netto / 1000)
        st.write(f"Tanken er fuld om ca. {round(timer, 1)} timer.")
    else:
        timer = tank_mwh / (abs(netto) / 1000)
        st.write(f"Tanken er tom om ca. {round(timer, 1)} timer.")
