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

# --- 2. DATA HENTNING (FORBEDRET) ---
@st.cache_data(ttl=300)
def hent_el_data():
    try:
        # Vi henter lidt flere timer for at være sikre på at have både fortid og fremtid
        url = "https://api.energidataservice.dk/dataset/Elspotprices?limit=100&filter={'PriceArea':['DK2']}&sort=HourDK desc"
        res = requests.get(url, timeout=5).json()
        df = pd.DataFrame(res['records'])
        df['HourDK'] = pd.to_datetime(df['HourDK'])
        return df
    except Exception as e:
        st.error(f"Kunne ikke hente elpriser: {e}")
        return pd.DataFrame()

el_df = hent_el_data()

# --- 3. STATUS & AFTAG ---
st.header("1. Aktuel Status")
col1, col2, col3 = st.columns(3)
with col1:
    tank_pct = st.number_input("Tank A (%)", 0, 100, 50)
    tank_mwh = (tank_pct / 100) * TANK_A_MAX_MWH
with col2:
    tank_b = st.number_input("Tank B (MWh)", 0.0, 80.0, 10.0)
with col3:
    aftag_nu = st.number_input("Aftag (kW)", 0, 3000, 1000)

# --- 4. ELPRIS & GRAF VISNING ---
st.write("---")
if not el_df.empty:
    nu = datetime.now()
    # Filtrer så vi ser fra 4 timer siden til 20 timer frem
    vis_df = el_df[(el_df['HourDK'] >= (nu - timedelta(hours=4))) & 
                   (el_df['HourDK'] <= (nu + timedelta(hours=20)))].sort_values('HourDK')
    
    if not vis_df.empty:
        st.subheader("Elpris-prognose (DK2)")
        # Vi laver grafen lidt højere her
        st.line_chart(vis_df, x='HourDK', y='SpotPriceDKK')
        
        # Find den aktuelle pris (nærmeste time)
        aktuel_pris = vis_df.iloc[0]['SpotPriceDKK']
        st.info(f"**Spotpris lige nu:** {round(aktuel_pris, 2)} kr/MWh")
    else:
        st.warning("Ingen prisdata fundet for de næste timer.")
        aktuel_pris = 200.0
else:
    st.warning("Venter på data fra Energidataservice... Prøv at opdatere om lidt.")
    aktuel_pris = 200.0

# --- 5. mFRR ELKEDEL ---
st.header("2. mFRR Elkedel (Ned)")
bud_elkedel = st.number_input("Bud Elkedel (kr/MWh)", value=150, key="el_bud")

if not el_df.empty:
    # Chance beregning: Vi kigger på de næste 6 timer
    fremtid = el_df[el_df['HourDK'] >= datetime.now()].sort_values('HourDK').head(6)
    billige_timer = len(fremtid[fremtid['SpotPriceDKK'] < bud_elkedel])
    
    if billige_timer > 0:
        st.success(f"**Aktiverings-chance: HØJ** ({billige_timer} ud af de næste 6 timer er under dit bud)")
    else:
        st.warning("**Aktiverings-chance: LAV** (Spotprisen er lige nu højere end dit bud)")

if st.button("Beregn Elkedel-scenarie"):
    bio = get_bio(tank_pct)
    netto = (bio + (ELKEDEL_MW * 1000)) - aftag_nu
    if netto > 0:
        timer = (TANK_A_MAX_MWH - tank_mwh) / (netto / 1000)
        st.error(f"Ved aktivering: Tank A er 100% fyldt om ca. {round(timer, 1)} timer.")
    else:
        st.success("Tanken tømmes stadig selvom elkedlen kører.")

# --- 6. mFRR MOTOR ---
st.header("3. mFRR Motor (Op)")
bud_motor = st.number_input("Bud Motor (kr/MWh)", value=450, key="mot_bud")

if not el_df.empty:
    fremtid = el_df[el_df['HourDK'] >= datetime.now()].sort_values('HourDK').head(6)
    dyre_timer = len(fremtid[fremtid['SpotPriceDKK'] > bud_motor])
    
    if dyre_timer > 0:
        st.success(f"**Aktiverings-chance: HØJ** ({dyre_timer} ud af de næste 6 timer er over dit bud)")
    else:
        st.info("**Aktiverings-chance: MIDDEL** (Typisk bedst chance i peak-timerne)")

if st.button("Beregn Motor-scenarie"):
    bio = get_bio(tank_pct)
    netto = (bio + (MOTOR_VARME_MW * 1000)) - aftag_nu
    if netto > 0:
        timer = (TANK_A_MAX_MWH - tank_mwh) / (netto / 1000)
        st.warning(f"Ved aktivering: Tank A er 100% fyldt om ca. {round(timer, 1)} timer.")
    else:
        st.success("Tanken tømmes stadig selvom motoren kører.")

# --- 7. BEREGN NORMAL DRIFT ---
st.write("---")
if st.button("BEREGN NORMAL DRIFT (BIO)", type="primary"):
    bio = get_bio(tank_pct)
    netto = bio - aftag_nu
    st.write(f"Biokedel: {bio} kW. Netto: {netto} kW.")
    if netto > 0:
        timer = (TANK_A_MAX_MWH - tank_mwh) / (netto / 1000)
        st.write(f"Tank A er 100% om ca. {round(timer, 1)} timer.")
    else:
        timer = tank_mwh / (abs(netto) / 1000)
        st.write(f"Tank A er tom (0%) om ca. {round(timer, 1)} timer.")

st.caption(f"Opdateret: {datetime.now().strftime('%H:%M:%S')}")
