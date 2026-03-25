# analyse.py
import pandas as pd
from sklearn.linear_model import LinearRegression

def optimer_profil(df_historisk):
    """
    df_historisk skal indeholde: 'temp', 'vind', 'faktisk_aftag'
    Returnerer den optimale Basis og Respons faktor.
    """
    # Vi forbereder data (Termisk led og Vind led som i din formel)
    df_historisk['termisk'] = (15 - df_historisk['temp']).clip(lower=0) * 0.8
    df_historisk['vind_effekt'] = df_historisk['vind'].apply(lambda x: 3.0 if x < 3 else min(10, 3 + (x - 3) * 0.77))
    
    X = df_historisk[['termisk', 'vind_effekt']]
    y = df_historisk['faktisk_aftag']
    
    model = LinearRegression()
    model.fit(X, y)
    
    # model.intercept_ svarer til din Basis
    # model.coef_ svarer til din Respons
    return model.intercept_, model.coef_[0]
