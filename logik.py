def get_faktisk_bio(tank_pct, max_bio):
    if tank_pct <= 30: return max_bio
    elif tank_pct <= 60: return max_bio * 0.75
    elif tank_pct <= 90: return max_bio * 0.60
    return 0

def beregn_aftag_nu(temp, vind, basis, respons, t_off, v_off):
    tc = temp + t_off
    vc = max(0, vind + v_off)
    tf = max(0, (15 - tc) * 0.8)
    vf = 3.0 if vc < 3 else min(10, 3 + (vc - 3) * 0.77)
    return basis + (tf + vf - 10.3) * respons
