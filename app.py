import math
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)


def get_number(data, key, default=None, positive=True):
    """Read a numeric field from the request.
    default=None -> required; positive=True -> value > 0, otherwise value >= 0."""
    raw = data.get(key)
    if raw is None or str(raw).strip() == '':
        if default is None:
            raise ValueError(f'Missing value for "{key}"')
        return float(default)
    value = float(raw)
    if positive and value <= 0:
        raise ValueError(f'"{key}" must be greater than zero')
    if not positive and value < 0:
        raise ValueError(f'"{key}" cannot be negative')
    return value


@app.route('/')
def index():
    return render_template('index.html')


# ======================= PART 1: SEISMIC WEIGHT (Ws) =======================
@app.route('/calculate_seismic_weight', methods=['POST'])
def calculate_seismic_weight():
    try:
        d = request.json

        # ---- General / material data ----
        n_raw = get_number(d, 'N_floors')
        if n_raw != int(n_raw) or n_raw > 100:
            raise ValueError('Number of floors must be a whole number (max 100)')
        n = int(n_raw)
        gc = get_number(d, 'gamma_c', 25)
        gw = get_number(d, 'gamma_w', 20)

        # ---- Typical floor geometry ----
        As = get_number(d, 'As')
        Ds = get_number(d, 'Ds')
        Lb = get_number(d, 'Lb', 0, positive=False)
        bb = get_number(d, 'bb', 0, positive=False)
        Db = get_number(d, 'Db', 0, positive=False)
        sum_Ac = get_number(d, 'sum_Ac', 0, positive=False)
        Lw = get_number(d, 'Lw', 0, positive=False)
        Bw = get_number(d, 'Bw', 0, positive=False)

        # ---- Staircase ----
        st = {k: get_number(d, k, 0, positive=False) for k in
              ('st_n', 'st_tread', 'st_riser', 'st_twaist', 'st_width',
               'st_m', 'st_Ll', 'st_Bl', 'st_tl')}

        floors = d.get('floors')
        if not isinstance(floors, list) or len(floors) != n:
            raise ValueError('Floor-wise data is incomplete')
        if Lb > 0 and Db <= Ds:
            raise ValueError('Beam overall depth must be greater than slab thickness')

        # ---- Floor-independent members ----
        W_slab = As * Ds * gc
        W_beam = Lb * bb * max(Db - Ds, 0) * gc            # web only (slab overlap removed)

        # Staircase (intermediate floors only, per algorithm)
        W_steps = (st['st_n'] * (st['st_tread'] * st['st_riser'] / 2.0)
                   + st['st_n'] * math.hypot(st['st_tread'], st['st_riser']) * st['st_twaist']
                   ) * st['st_width'] * gc
        W_landing = st['st_m'] * (st['st_Ll'] * st['st_Bl'] * st['st_tl']) * gc
        W_stair = W_steps + W_landing

        rows, level, Ws = [], 0.0, 0.0
        for i, f in enumerate(floors):
            roof = (i == n - 1)
            h = get_number(f, 'h')
            LL = get_number(f, 'LL', 0, positive=False)
            if Lw > 0 and h <= Db:
                raise ValueError(f'Floor {i + 1}: storey height must be greater than beam depth')

            frac = 0.5 if roof else 1.0                    # roof: half-height columns & walls
            W_col = sum_Ac * h * frac * gc
            W_wall = Lw * Bw * max(h - Db, 0) * frac * gw
            W_st = (W_stair * frac) if f.get('stair') else 0.0   # roof: half of a normal floor's staircase

            DL = W_slab + W_beam + W_col + W_wall + W_st

            if roof:
                k, LL_s = 0.0, 0.0                         # roof imposed load ignored
            else:
                k = 0.25 if LL <= 3.0 else 0.50
                LL_s = k * LL * As

            Ws_i = DL + LL_s
            level += h
            Ws += Ws_i
            rows.append({
                'floor': i + 1, 'roof': roof, 'h': h, 'level': round(level, 3),
                'LL': LL, 'k': k,
                'W_slab': round(W_slab, 2), 'W_beam': round(W_beam, 2),
                'W_col': round(W_col, 2), 'W_wall': round(W_wall, 2),
                'W_stair': round(W_st, 2), 'DL': round(DL, 2),
                'LL_seismic': round(LL_s, 2), 'Ws_i': round(Ws_i, 2),
            })

        return jsonify({'N': n, 'rows': rows, 'Ws': round(Ws, 2)})

    except Exception as e:
        return jsonify({'error': str(e)}), 400


# ======================= PART 2: BASE SHEAR (Vb) =======================
ZONE_FACTOR = {'II': 0.10, 'III': 0.16, 'IV': 0.24, 'V': 0.36}
IMPORTANCE = {'Important Service & Community': 1.5,
              'Residential / Simple Commercial': 1.2,
              'All Other': 1.0}
RESPONSE_REDUCTION = {'OMRF': 3.0, 'SMRF': 5.0, 'OBF Concentric': 4.0,
                      'SBF Concentric': 4.5, 'SBF Eccentric': 5.0}
# soil type -> (plateau end period, constant C in C/T, value beyond T = 4 s)
SOIL_SPECTRUM = {'I': (0.40, 1.00, 0.25),
                 'II': (0.55, 1.36, 0.34),
                 'III': (0.67, 1.67, 0.42)}


def sa_by_g(soil, T):
    t_plateau, c, tail = SOIL_SPECTRUM[soil]
    if T <= t_plateau:
        return 2.5
    if T <= 4.0:
        return c / T
    return tail


@app.route('/calculate_base_shear', methods=['POST'])
def calculate_base_shear():
    try:
        d = request.json
        zone, soil = d.get('zone'), d.get('soil')
        category, frame = d.get('category'), d.get('frame')
        if zone not in ZONE_FACTOR:
            raise ValueError('Invalid seismic zone')
        if soil not in SOIL_SPECTRUM:
            raise ValueError('Invalid soil type')
        if category not in IMPORTANCE:
            raise ValueError('Invalid building category')
        if frame not in RESPONSE_REDUCTION:
            raise ValueError('Invalid frame system')
        Ta = get_number(d, 'Ta')

        # Seismic weights / heights come from Part 1 output
        Ws_list = [float(x) for x in d.get('Ws_i', [])]
        h_list = [float(x) for x in d.get('h_i', [])]
        if not Ws_list or len(Ws_list) != len(h_list):
            raise ValueError('Calculate seismic weight first (floor data missing)')
        if any(w <= 0 for w in Ws_list) or any(h <= 0 for h in h_list):
            raise ValueError('Floor weights and heights must be positive')

        Z = ZONE_FACTOR[zone]
        I = IMPORTANCE[category]
        R = RESPONSE_REDUCTION[frame]
        Sa_g = sa_by_g(soil, Ta)
        Ah = (Z * I) / (2.0 * R) * Sa_g

        Ws = sum(Ws_list)
        Vb = Ah * Ws

        denom = sum(w * h ** 2 for w, h in zip(Ws_list, h_list))
        Q = [Vb * w * h ** 2 / denom for w, h in zip(Ws_list, h_list)]

        # Storey shear = sum of lateral forces at and above each floor
        storey_shear = [sum(Q[i:]) for i in range(len(Q))]

        rows = [{'floor': i + 1, 'Ws_i': round(w, 2), 'h_i': round(h, 3),
                 'Wh2': round(w * h ** 2, 2), 'Q_i': round(Q[i], 2),
                 'V_storey': round(storey_shear[i], 2)}
                for i, (w, h) in enumerate(zip(Ws_list, h_list))]

        return jsonify({'Z': Z, 'I': I, 'R': R, 'Sa_g': round(Sa_g, 4),
                        'Ah': round(Ah, 5), 'Ws': round(Ws, 2), 'Vb': round(Vb, 2),
                        'rows': rows})

    except Exception as e:
        return jsonify({'error': str(e)}), 400


if __name__ == '__main__':
    app.run(debug=True, port=5000)
