import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- 1. KONFIGURATION & FUNKTIONER ---
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

# --- 2. DATA HENTNING (FORBEDRET API-LOGIK) ---
@st.cache_data(ttl=300)
def hent_el_data():
    try:
        # Ny URL-struktur der er mere stabil
        url = "https://api.energidataservice.dk/dataset/Elspotprices?filter={'PriceArea':['DK2']}&sort=HourDK desc&limit=50"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if 'records' in data and len(data['records']) > 0:
                df = pd.DataFrame(data['records'])
                df['HourDK'] = pd.to_datetime(df['HourDK'])
                return df
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

# Knap til manuel opdatering hvis API driller
if st.button("🔄 Opdater Elpriser"):
    st.cache_data.clear()
    st.rerun()

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

# --- 4. ELPRIS & GRAF ---
st.write("---")
aktuel_pris = 200.0 # Standard hvis alt fejler

if not el_df.empty:
    nu = datetime.now()
    vis_df = el_df[(el_df['HourDK'] >= (nu - timedelta(hours=4))) & 
                   (el_df['HourDK'] <= (nu + timedelta(hours=20)))].sort_values('HourDK')
    
    if not vis_df.empty:
        st.subheader("Elpris-prognose (DK2)")
        st.line_chart(vis_df, x='HourDK', y='SpotPriceDKK')
        aktuel_pris = vis_df.iloc[-1]['SpotPriceDKK'] # Hent nyeste
        st.info(f"**Spotpris lige nu:** {round(aktuel_pris, 2)} kr/MWh")
    else:
        st.warning("Data modtaget, men kunne ikke sorteres. Prøv 'Opdater'.")
else:
    st.error("Kunne ikke hente live-data fra Energidataservice lige nu. Bruger standard-pris (200 kr).")

# --- 5. mFRR ELKEDEL ---
st.header("2. mFRR Elkedel (Ned)")
bud_elkedel = st.number_input("Bud Elkedel (kr/MWh)", value=150, key="el_bud")

if not el_df.empty:
    fremtid = el_df[el_df['HourDK'] >= datetime.now()].sort_values('HourDK').head(6)
    billige_timer = len(fremtid[fremtid['SpotPriceDKK'] < bud_elkedel])
    if billige_timer > 0:
        st.success(f"**Aktiverings-chance: HØJ** ({billige_timer} timer under bud)")
    else:
        st.warning("**Aktiverings-chance: LAV** (Spotpris er højere)")

if st.button("Beregn Elkedel-scenarie"):
    bio = get_bio(tank_pct)
    netto = (bio + (ELKEDEL_MW * 1000)) - aftag_nu
    if netto > 0:
        timer = (TANK_A_MAX_MWH - tank_mwh) / (netto / 1000)
        st.error(f"Ved aktivering: Tank A er 100% fyldt om ca. {round(timer, 1)} timer.")
    else:
        st.success("Tanken tømmes stadig.")

# --- 6. mFRR MOTOR ---
st.header("3. mFRR Motor (Op)")
bud_motor = st.number_input("Bud Motor (kr/MWh)", value=450, key="mot_bud")

if not el_df.empty:
    fremtid = el_df[el_df['HourDK'] >= datetime.now()].sort_values('HourDK').head(6)
    dyre_timer = len(fremtid[fremtid['SpotPriceDKK'] > bud_motor])
    if dyre_timer > 0:
        st.success(f"**Aktiverings-chance: HØJ** ({dyre_timer} timer over bud)")
    else:
        st.info("**Aktiverings-chance: MIDDEL**")

if st.button("Beregn Motor-scenarie"):
    bio = get_bio(tank_pct)
    netto = (bio + (MOTOR_VARME_MW * 1000)) - aftag_nu
    if netto > 0:
        timer = (TANK_A_MAX_MWH - tank_mwh) / (netto / 1000)
        st.warning(f"Ved aktivering: Tank A er 100% fyldt om ca. {round(timer, 1)} timer.")
    else:
        st.success("Tanken tømmes stadig.")

# --- 7. BEREGN NORMAL DRIFT ---
st.write("---")
if st.button("BEREGN NORMAL DRIFT (BIO)", type="primary"):
    bio = get_bio(tank_pct)
    netto = bio - aftag_nu
    st.write(f"Biokedel: {bio} kW. Netto: {netto} kW.")
    if netto > 0:
        timer = (TANK_A_MAX_MWH - tank_mwh) / (netto / 1000)
        st.write(f"Fuld (100%) om ca. {round(timer, 1)} timer.")
    else:
        timer = tank_mwh / (abs(netto) / 1000)
        st.write(f"Tom (0%) om ca. {round(timer, 1)} timer.")
