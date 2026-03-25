import requests
import pandas as pd
from datetime import datetime

def hent_alle_data():
    el_df = pd.DataFrame()
    vejr_df = pd.DataFrame()
    
    # Hent Elpriser (DK2)
    try:
        url = "https://api.energidataservice.dk/dataset/DayAheadPrices?limit=50&filter={'PriceArea':['DK2']}"
        r = requests.get(url, timeout=5).json()['records']
        temp_el = pd.DataFrame(r)
        temp_el['Tid'] = pd.to_datetime(temp_el['HourDK']).dt.tz_localize(None)
        el_df = temp_el[['Tid', 'SpotPriceDKK']].sort_values('Tid').reset_index(drop=True)
    except:
        pass

    # Hent Vejr (Skuldelev)
    try:
        url_v = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=55.79&lon=12.02"
        headers = {'User-Agent': 'SkuldelevV1/1.0'}
        rv = requests.get(url_v, headers=headers, timeout=5).json()
        rows = [{'Tid': pd.to_datetime(e['time']).tz_convert('Europe/Copenhagen').tz_localize(None),
                 'Temp': e['data']['instant']['details']['air_temperature'],
                 'Vind': e['data']['instant']['details']['wind_speed']} 
                for e in rv['properties']['timeseries'][:48]]
        vejr_df = pd.DataFrame(rows)
    except:
        pass
        
    return el_df, vejr_df
