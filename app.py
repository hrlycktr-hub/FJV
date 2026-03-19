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

st.set_page_config(page_title="Skuldelev Drift & Prognose", page_icon="⚡", layout="wide")
st.title("Skuldelev Drifts-Agent ⚡")

# --- 2. DATA HENTNING (SPOTPRIS + PROGNOSE) ---
@st.cache_data(ttl=300)
def hent_el_data():
    try:
        # Vi henter de sidste 24 timer og de næste 24 timer
        url = "https://api.energidataservice.dk/dataset/Elspotprices?limit=48&filter={'PriceArea':['DK2']}&sort=HourDK desc"
        res = requests.get(url).json()
        df = pd.DataFrame(res['records'])
        df['HourDK'] = pd.to_datetime(df['HourDK'])
        return df
    except: return pd.DataFrame()

el_df = hent_el_data()

# --- 3. STATUS & AFTAG ---
st.header("📍 1. Aktuel Status")
with st.container(border=True):
    col1, col2, col3 = st.columns(3)
    with col1:
        tank_pct = st.number_input("Tank A fyldning (%)", 0, 100, 50)
        tank_mwh = (tank_pct / 100) * TANK_A_MAX_MWH
    with col2:
        tank_b_mwh = st.number_input("Tank B (MWh)", 0.0, 80.0, 10.0)
    with col3:
        aftag_nu = st.number_input("Aktuelt Aftag (kW)", 0, 3000, 1000)

# --- 4. ELPRIS GRAF & PROGNOSE ---
if not el_df.empty:
    st.header("📈 Elpris-prognose (DK2)")
    # Vi viser de næste 24 timer i en graf
    nu = datetime.now()
    fremtid_df = el_df[el_df['HourDK'] >= (nu - timedelta(hours=1))].sort_values('HourDK')
    
    st.line_chart(fremtid_df, x='HourDK', y='SpotPriceDKK')
    
    aktuel_pris = fremtid_df.iloc[0]['SpotPriceDKK']
    st.info(f"**Pris lige nu:** {round(aktuel_pris, 2)} kr/MWh")
else:
    aktuel_pris = 200.0

# --- 5. mFRR SEKTIONER ---
col_el, col_mot = st.columns(2)

with col_el:
    st.header("🔌 mFRR Elkedel")
    with st.container(border=True):
        bud_elkedel = st.number_input("Bud (kr/MWh)", value=150, key="el_bud")
        
        # PROGNOSE-CHANCE: Ser vi på de næste 6 timer
        if not el_df.empty:
            billige_timer = len(fremtid_df.head(6)[fremtid_df['SpotPriceDKK'] < bud_elkedel])
            if billige_timer > 0:
                st.success(f"Høj chance! Der er {billige_timer} timer med priser under dit bud de næste 6 timer.")
            else:
                st.warning("Lav chance. Spotprisen ser ud til at ligge over dit bud lige nu.")

with col_mot:
    st.header("⚙️ mFRR Motor")
    with st.container(border=True):
        bud_motor = st.number_input("Bud (kr/MWh)", value=450, key="mot_bud")
        
        if not el_df.empty:
            dyre_timer = len(fremtid_df.head(6)[fremtid_df['SpotPriceDKK'] > bud_motor])
            if dyre_timer > 0:
                st.success(f"Høj chance! Markedet ser ud til at pege mod dit motor-bud snart.")
            else:
                st.info("Middel chance. Motoren vinder typisk i peak-timerne.")

# --- 6. BEREGN DRIFT ---
if st.button("BEREGN PROGNOSE FOR TANK A", type="primary"):
    bio = get_bio(tank_pct)
    netto_norm = bio - aftag_nu
    st.divider()
    st.write(f"Biokedel kører med **{bio} kW**. Netto-ændring: **{netto_norm} kW**.")
    
    if netto_norm > 0:
        timer = (TANK_A_MAX_MWH - tank_mwh) / (netto_norm / 1000)
        st.write(f"Tanken fyldes. 100% nås om ca. **{round(timer, 1)} timer**.")
    else:
        timer = tank_mwh / (abs(netto_norm) / 1000)
        st.write(f"Tanken tømmes. 0% nås om ca. **{round(timer, 1)} timer**.")

st.caption(f"Sidst opdateret: {datetime.now().strftime('%H:%M:%S')}")
