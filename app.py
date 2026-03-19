import streamlit as st
import pandas as pd
import requests

# KONFIGURATION SKULDELEV
BIO_MIN = 700
BIO_MAX = 1200
TANK_A_LIMIT = 70

st.set_page_config(page_title="Skuldelev Drift", page_icon="🔥")
st.title("Skuldelev Drifts-Agent ⚡")

# INPUT FRA DIG
st.header("Status på værket")
col1, col2 = st.columns(2)
with col1:
    tank_a = st.number_input("Tank A (MWh)", 0.0, 80.0, 35.0)
with col2:
    tank_b = st.number_input("Tank B (MWh)", 0.0, 80.0, 10.0)

vejr = st.selectbox("Vejrudsigt", ["Overskyet", "Nogen sol", "Fuld sol"])

# HENT ELPRISER (DK2)
@st.cache_data(ttl=3600)
def hent_el():
    try:
        url = "https://api.energidataservice.dk/dataset/Elspotprices?limit=24&filter={'PriceArea':['DK2']}&sort=HourDK desc"
        res = requests.get(url).json()
        return pd.DataFrame(res['records'])
    except:
        return pd.DataFrame()

if st.button("BEREGN PLAN", type="primary"):
    el_df = hent_el()
    billige_timer = 0
    if not el_df.empty:
        billige_timer = len(el_df[el_df['SpotPriceDKK'] < 150])
    
    st.divider()
    
    # LOGIK FOR SLUK/DRIFT
    total = tank_a + tank_b
    if total > 35 and (vejr == "Fuld sol" or billige_timer > 3):
        st.success("✅ ANBEFALING: SLUK BIOKEDEL HELT")
        st.write(f"Du har {total} MWh på lager. Sol/El bør dække behovet.")
    else:
        st.warning("🔥 KØR BIOKEDEL (REDUCERET LAST)")
        
        # TRIN-TABEL
        data = {
            "Tank A (MWh)": ["0-25", "26-45", "46-65", ">68"],
            "Biokedel Last": ["1200 kW", "900 kW", f"{BIO_MIN} kW", "0 kW (STOP)"]
        }
        st.table(pd.DataFrame(data))
    
    if tank_a > 62:
        st.error(f"OBS: Tank A er på {tank_a} MWh. SRO skifter til Tank B ved 70 MWh!")
