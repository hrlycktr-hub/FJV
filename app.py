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

# --- 2. FORSIMPLET DATA-HENTNING ---
@st.cache_data(ttl=600)
def hent_el_data():
    try:
        # Vi henter rådata for DK2 uden komplicerede filtre
        url = "https://api.energidataservice.dk/dataset/Elspotprices?limit=100"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            raw_data = response.json()['records']
            df = pd.DataFrame(raw_data)
            # Sørg for at vi kun har Sjælland og korrekt tid
            df = df[df['PriceArea'] == 'DK2']
            df['HourDK'] = pd.to_datetime(df['HourDK'])
            return df.sort_values('HourDK', ascending=False)
        return pd.DataFrame()
    except:
        return pd.DataFrame()

el_df = hent_el_data()

# --- 3. STATUS & AFTAG ---
st.header("1. Aktuel Status")
col1, col2, col3 = st.columns(3)
with col1:
    tank_pct = st.number_input("Tank A (%)", 0, 100, 44)
    tank_mwh = (tank_pct / 100) * TANK_A_MAX_MWH
with col2:
    tank_b = st.number_input("Tank B (MWh)", 0.0, 80.0, 0.0)
with col3:
    aftag_nu = st.number_input("Aftag (kW)", 0, 3000, 1000)

# --- 4. VISNING AF PRIS & GRAF ---
st.write("---")
if not el_df.empty:
    nu = datetime.now()
    # Vis graf fra i dag og frem
    vis_df = el_df[(el_df['HourDK'] >= (nu - timedelta(hours=6)))].sort_values('HourDK')
    
    if not vis_df.empty:
        st.subheader("Elpris-prognose (DK2)")
        st.line_chart(vis_df, x='HourDK', y='SpotPriceDKK')
        
        # Hent den nyeste pris
        aktuel_pris = el_df.iloc[0]['SpotPriceDKK']
        st.info(f"**Spotpris lige nu:** {round(aktuel_pris, 2)} kr/MWh")
    else:
        st.warning("Data er hentet, men tidsformatet driller. Prøv igen om lidt.")
        aktuel_pris = 250.0
else:
    st.error("Kunne ikke få fat i el-børsen. Indtast prisen manuelt herunder for at se chancer:")
    aktuel_pris = st.number_input("Manuel Elpris (kr/MWh)", value=250)

# --- 5. mFRR SEKTIONER ---
st.header("2. mFRR Elkedel (Ned)")
bud_elkedel = st.number_input("Bud Elkedel (kr/MWh)", value=150, key="el_bud")

# Chance beregning
if aktuel_pris < bud_elkedel:
    st.success("**Aktiverings-chance: HØJ** (Prisen er under dit bud)")
else:
    st.warning(f"**Aktiverings-chance: LAV** (Prisen er {round(aktuel_pris-bud_elkedel)} kr for høj)")

if st.button("Beregn Elkedel-scenarie"):
    bio = get_bio(tank_pct)
    netto = (bio + (ELKEDEL_MW * 1000)) - aftag_nu
    timer = (TANK_A_MAX_MWH - tank_mwh) / (max(netto, 1) / 1000)
    st.error(f"Ved aktivering: Tank A er 100% fyldt om ca. {round(timer, 1)} timer.")

st.write("---")
st.header("3. mFRR Motor (Op)")
bud_motor = st.number_input("Bud Motor (kr/MWh)", value=450, key="mot_bud")

if aktuel_pris > bud_motor:
    st.success("**Aktiverings-chance: HØJ** (Prisen er over dit bud)")
else:
    st.info("**Aktiverings-chance: MIDDEL/LAV**")

if st.button("Beregn Motor-scenarie"):
    bio = get_bio(tank_pct)
    netto = (bio + (MOTOR_VARME_MW * 1000)) - aftag_nu
    timer = (TANK_A_MAX_MWH - tank_mwh) / (max(netto, 1) / 1000)
    st.warning(f"Ved aktivering: Tank A er 100% fyldt om ca. {round(timer, 1)} timer.")

# --- 6. NORMAL DRIFT ---
st.write("---")
if st.button("BEREGN NORMAL DRIFT (BIO)", type="primary"):
    bio = get_bio(tank_pct)
    netto = bio - aftag_nu
    st.write(f"Biokedel yder: {bio} kW")
    if netto > 0:
        timer = (TANK_A_MAX_MWH - tank_mwh) / (netto / 1000)
        st.write(f"Fuld om {round(timer, 1)} timer.")
    else:
        timer = tank_mwh / (abs(netto) / 1000)
        st.write(f"Tom om {round(timer, 1)} timer.")
