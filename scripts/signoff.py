#!/usr/bin/env python3
"""signoff.py — the sign-off page for one or more routed boards.

Reads, per output directory:
  <board>-klayout-result.json   the router's verdict + "si" facts (DRC/ERC,
                                DDR groups vs two-tier budgets, homes, shares,
                                pairs as laid, the stack)
  si-report/{segments,vias,pads}.csv   the reflection export (ODT judge)
  si-report/fullwave.json       optional: field-solver impedances written by
                                scripts/fullwave/ (net -> Z ohm, kind, method)
and writes signoff.html — verdict strip, results-against-gates table,
conditions per board (measured -> required, with the remedy), method notes.
Every condition is derived from a gate the board misses; nothing is typed in.
Usage:  python3 scripts/signoff.py OUT_DIR [OUT_DIR ...] [-o signoff.html]
        [--label BUILD]
Dependency-free (uses si_report.py beside it for the ODT judge)."""
import sys, os, json, csv, re, html, time, subprocess, math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import si_report as SR

ODT = (40, 48, 60, 80, 120, 240)                # LPDDR4 per-leg bins (MR11)
LEGAL_SE = (40, 48, 60, 80)                       # bins a member line is matched to
REMEDY = {  # gate -> the unit that closes it (kept honest by hand as units land)
    'lane_target':   'Attempt tiebreak toward target-meeting attempts; serpentine room from the gap/convergence unit.',
    'addr_target':   'Gap/convergence unit (serpentine room on the open side).',
    'lane_spec':     'Lane skew beyond spec: matching/serpentine unit.',
    'share':         'Home-layer share: escape/dogbone discipline on the home layer.',
    'pair_bin':      'Pair outside a legal 2x ODT bin: gap unit (pull-together, constant gap), judged in the field solver.',
    'pair_coupling': 'Pair legs uncoupled: gap unit (hold the solved gap through the run).',
    'member_bins':   'Members in two bins: size the ball-field boxes to the array, then widen uniformly (fair ladder).',
    'member_bin':    'Member outside every legal bin: per-landed-layer width on this stack.',
    'drc':           'DRC/ERC must be zero: rerun after the responsible unit; warnings are in scope.',
}


def read_dir(d):
    """Everything the page needs from one output directory."""
    res = None
    for f in os.listdir(d):
        if f.endswith('-klayout-result.json'):
            res = json.load(open(os.path.join(d, f)))
    if not res:
        raise SystemExit(f'{d}: no *-klayout-result.json')
    b = {'dir': d, 'name': os.path.basename(os.path.abspath(d)), 'res': res}
    rep = os.path.join(d, 'si-report')
    b['has_report'] = os.path.exists(os.path.join(rep, 'segments.csv'))
    fw = os.path.join(rep, 'fullwave.json')
    b['fullwave'] = json.load(open(fw)) if os.path.exists(fw) else None
    si = res.get('si') or {}
    b['layers'] = si.get('copper_layers') or 0
    b['short'] = f"{b['layers']}L" if b['layers'] else b['name']
    return b


def judge(b):
    """The ODT judge on the reflection export: settings per group, pass counts."""
    if not b['has_report']:
        return None
    rep = os.path.join(b['dir'], 'si-report')
    segs = SR.read_csv(os.path.join(rep, 'segments.csv'))
    vias = SR.read_csv(os.path.join(rep, 'vias.csv'))
    pads = SR.read_csv(os.path.join(rep, 'pads.csv'))
    bynet = {}
    for s in segs:
        bynet.setdefault(s['net'], []).append(s)
    ladders = {}
    for net in sorted(bynet):
        ladder, length = SR.chain(net, bynet[net], vias, pads)
        if ladder:
            ladders[net] = ladder
    def group_of(net):
        n = net.upper()
        return 'CA' if any(k in n for k in ('_CA', '_CS', '_CKE', '_CK')) else 'DQ'
    def median_z(ladder):
        w = sorted((z, L) for z, _, L in ladder)
        half, acc = sum(L for _, L in w) / 2, 0
        for z, L in w:
            acc += L
            if acc >= half:
                return z
        return w[-1][0]
    out = {'groups': {}, 'npass': 0, 'n': 0}
    for grp in ('DQ', 'CA'):
        nets = [n for n in ladders if group_of(n) == grp]
        if not nets:
            continue
        zmed = sorted(median_z(ladders[n]) for n in nets)[len(nets) // 2]
        below = [o for o in SR.DRAM_ODT if o <= zmed]; above = [o for o in SR.DRAM_ODT if o >= zmed]
        odts = sorted({(below[-1] if below else SR.DRAM_ODT[0]), (above[0] if above else SR.DRAM_ODT[-1]), SR.RT})
        cands = [(rs, rt) for rt in odts for rs in (40.0, 48.0)] + [(SR.RS, SR.RT)]
        best = None
        for rs, rt in cands:
            npass, worst = 0, 0
            for n in nets:
                t, vr, _ = SR.bounce(ladders[n], rs, rt)
                over, ring, settle, ok = SR.metrics(t, vr)
                npass += ok; worst = max(worst, over)
            key = (npass, -worst, -rt)
            if best is None or key > best[0]:
                best = (key, rs, rt, npass)
        _, rs, rt, npass = best
        out['groups'][grp] = {'drive': rs, 'odt': rt, 'npass': npass, 'n': len(nets)}
        out['npass'] += npass; out['n'] += len(nets)
    return out


DATA_RATE_MTS = float(os.environ.get('KLAYOUT_DATA_RATE', 4267))  # MT/s; LPDDR4-4267 unless told otherwise
UI_PS = 1e6 / DATA_RATE_MTS               # 234.4 ps
MASK_H_V, MASK_W_UI = 0.140, 0.22         # JEDEC LPDDR4 Rx mask at 4267: VdIVW 140 mV, TdIVW 0.22 UI
# Jitter budget, in UI, taken off the eye width (the channel model is noiseless):
# transmitter duty-cycle distortion + random jitter of the SoC PHY and the
# residual DQS-to-DQ skew after training. 0.20 UI is the LPDDR4-4267 planning
# figure used here (KLAYOUT_JITTER_UI overrides); the reviewer's number for the
# actual SoC PHY replaces it.
JITTER_UI = float(os.environ.get('KLAYOUT_JITTER_UI', 0.20))
DRAM_PDDS = 40.0                          # LPDDR4 DRAM pull-down drive strength for reads (MR3 default)
PS_MM = {'strip': 6.9, 'micro': 5.9}      # propagation, ps/mm (the gates document's values)


def step_response(ladder, rs, rt):
    """Receiver voltage vs time for a 0 -> VDDQ step (the bounce sim)."""
    t, vr, _ = SR.bounce(ladder, rs, rt)
    return t, vr


def prbs7():
    reg, out = 0x7f, []
    for _ in range(127):
        bit = ((reg >> 6) ^ (reg >> 5)) & 1
        out.append(reg & 1); reg = ((reg << 1) | bit) & 0x7f
    return out


def eye(ladder, rs, rt):
    """The bounce-model eye of a net (lossless lines, reflections only)."""
    return eye_from_step(*step_response(ladder, rs, rt))


def eye_from_step(t, v, aggressors=()):
    """PRBS-7 eye by superposition of the step response, and the worst-case
    (peak-distortion) eye height/width. `aggressors`: step responses of
    crosstalk paths into this receiver (aggressor driven 0 -> VDDQ), whose
    pulse taps add to the distortion and whose PRBS adds to the drawn eye.
    Returns dict with traces (list of (t_ui, v) polylines over 2 UI),
    height_v, width_ui, vref."""
    dt = t[1] - t[0] if len(t) > 1 else 1.0
    n_ui = max(1, int(round(UI_PS / dt)))
    vlo, vhi = v[0], v[-1]                    # settled levels (POD: low = divider, high = VDDQ)
    # pulse response p = s(t) - s(t - UI), as a list
    p = [v[i] - (v[i - n_ui] if i >= n_ui else vlo) for i in range(len(v))]
    ic = max(range(len(p)), key=lambda i: p[i])  # cursor: pulse peak
    swing = vhi - vlo
    # PDA: eye height at the cursor = 2*p(cursor) - swing - sum of |ISI taps| ... in level terms:
    # high-eye edge = vlo + p(ic) - sum_k max(0,-p(ic+kUI))... use the symmetric bound
    # crosstalk pulse responses on the same time grid (resampled by index)
    xps = []
    for (ta, va) in aggressors:
        if len(ta) < 2: continue
        dta = ta[1] - ta[0]
        vr = [va[min(len(va) - 1, int(round(i * dt / dta)))] for i in range(len(v))]
        xps.append([vr[i] - (vr[i - n_ui] if i >= n_ui else vr[0]) for i in range(len(vr))])
    def xtalk(i):  # worst-case crosstalk amplitude at sample i (any aggressor phase): the largest |tap| sum window
        tot = 0.0
        for xp in xps:
            tot += max(sum(abs(xp[j + k * n_ui]) for k in range(-8, 9) if 0 <= j + k * n_ui < len(xp)) for j in range(max(0, i - n_ui // 2), min(len(xp), i + n_ui // 2 + 1), max(1, n_ui // 8)))
        return tot
    # worst-case levels at a sampling instant i (peak distortion): the lowest
    # "1" and the highest "0" over every bit pattern, crosstalk included
    def bounds(i):
        hi1 = vlo + p[i]; lo0 = vlo
        for k in range(-8, 9):
            if k == 0 or not (0 <= i + k * n_ui < len(p)): continue
            tap = p[i + k * n_ui]
            if tap < 0: hi1 += tap
            else: lo0 += tap
        xt = xtalk(i)
        return hi1 - xt, lo0 + xt
    # the sampling point the DRAM trains to: where the worst-case opening is
    # largest, searched over one UI around the pulse peak; V_ref at its centre
    best, ic2 = -1e9, ic
    for i in range(max(0, ic - n_ui // 2), min(len(p), ic + n_ui // 2 + 1)):
        a, b2 = bounds(i)
        if a - b2 > best: best, ic2 = a - b2, i
    ic = ic2
    top, bot = bounds(ic)
    height = max(0.0, top - bot)
    vref = (top + bot) / 2 if height > 0 else (vlo + vhi) / 2
    def opening(i):
        if i < 0 or i >= len(p): return -1
        a, b2 = bounds(i); return a - b2
    # width: the samples around the trained point where the worst-case opening stays > 0, less the jitter budget
    lo = ic
    while lo > 0 and opening(lo - 1) > 0: lo -= 1
    hi = ic
    while hi < len(p) - 1 and opening(hi + 1) > 0: hi += 1
    width_ui = max(0.0, (hi - lo + 1) * dt / UI_PS - JITTER_UI) if height > 0 else 0.0
    # the mask box is centred on the trained point: fold the drawing so it sits at 1 UI
    ic_draw = (lo + hi) // 2
    # PRBS-7 superposition, folded on 2 UI windows around the cursor phase
    bits = prbs7(); traces = []
    for k in range(2, len(bits)):
        seg = []
        for j in range(0, 2 * n_ui, max(1, n_ui // 40)):
            i = ic_draw + j - n_ui  # sample index relative to the eye centre of bit k
            val = vlo
            for m in range(0, 12):  # bits k-m contribute their pulse responses
                if k - m < 0: break
                if bits[k - m]:
                    idx = i + m * n_ui
                    if 0 <= idx < len(p): val += p[idx]
                    elif idx >= len(p): val += p[-1]
                for xp in xps:  # an aggressor running the same PRBS shifted by 3 bits
                    kk = k - m - 3
                    if kk >= 0 and bits[kk % len(bits)]:
                        idx = i + m * n_ui
                        if 0 <= idx < len(xp): val += xp[idx]
            seg.append((j / n_ui, val))
        # the jitter budget smears every edge by ±JITTER/2: draw each trace at both extremes
        traces.append([(u - JITTER_UI / 2, v2) for u, v2 in seg])
        traces.append([(u + JITTER_UI / 2, v2) for u, v2 in seg])
    return {'traces': traces, 'height_v': height, 'width_ui': width_ui, 'vref': vref, 'vlo': vlo, 'vhi': vhi}


def _load_ports(csvp):
    rows = list(csv.reader(open(csvp)))
    return [[float(v) for v in r] for r in rows[1:]]


def sparam_channel(slice_dir, rs, rt, pair=False, xtalk_ports=None):
    """The receiver step response of a measured channel: the slice's S
    parameters (50 ohm reference, 0.2-4 GHz) renormalised to the driver
    (rs, Thevenin step to VDDQ) and the ODT (rt to VDDQ) through the Z
    matrix, H(f) = V_load/V_source, extrapolated to DC (|H| held, phase
    from the group delay), zero-padded above 4 GHz (an ideal low-pass
    at the measurement's edge: 100 ps edges keep most of their content,
    the 3rd harmonic of a 4267 MT/s pattern does not), inverse-FFT to an
    impulse response and integrated. Pairs use the differential mixed-
    mode parameters and 2*rs / 2*rt. Returns (t_ps[], v[]) or None."""
    import cmath, math
    R = os.path.join(slice_dir, 'ems', 'results')
    try:
        d0 = _load_ports(os.path.join(R, 'Port_0_data.csv'))
        d2 = _load_ports(os.path.join(R, 'Port_2_data.csv')) if pair else None
    except OSError:
        return None
    n = 4 if (pair or xtalk_ports) else 2
    if xtalk_ports:  # a 4-port victim+aggressor slice: excitation port a (aggressor near end), response at v (victim far end)
        a_port, v_port = xtalk_ports
        try:
            da = _load_ports(os.path.join(R, 'Port_%d_data.csv' % a_port))
        except OSError:
            return None
    def S(d, i): return cmath.rect(d[1 + i], d[1 + n + i])
    z0 = 100.0 if pair else 50.0
    rs2, rt2 = (2 * rs, 2 * rt) if pair else (rs, rt)
    f, H = [], []
    for k, a in enumerate(d0 if not xtalk_ports else da):
        if xtalk_ports:
            # the aggressor's own reflection and its transfer into the victim's receiver, both terminated as the bus is
            s11, s21 = S(a, xtalk_ports[0]), S(a, xtalk_ports[1]); s12, s22 = s21, s11
        elif pair:
            b = d2[k]; sa = [S(a, i) for i in range(4)]; sb = [S(b, i) for i in range(4)]
            s11 = (sa[0] - sb[0] - sa[2] + sb[2]) / 2; s21 = (sa[1] - sb[1] - sa[3] + sb[3]) / 2
            s12 = s21; s22 = s11  # reciprocal, assumed symmetric (one excitation per side measured)
        else:
            s11, s21 = S(a, 0), S(a, 1); s12, s22 = s21, s11
        # S -> Z (reference z0)
        det = (1 - s11) * (1 - s22) - s12 * s21
        if abs(det) < 1e-12:
            continue
        z11 = z0 * ((1 + s11) * (1 - s22) + s12 * s21) / det
        z12 = z0 * 2 * s12 / det; z21 = z0 * 2 * s21 / det
        z22 = z0 * ((1 - s11) * (1 + s22) + s12 * s21) / det
        h = z21 * rt2 / ((z11 + rs2) * (z22 + rt2) - z12 * z21)  # V_load / V_source
        f.append(a[0] * 1e6); H.append(h)
    if len(f) < 10:
        return None
    # uniform grid from DC to fmax: df = f[1]-f[0]; below f[0] hold |H| with linear phase
    df = f[1] - f[0]; fmax = f[-1]
    nf = int(round(fmax / df)) + 1
    # group delay near the low end for the phase extrapolation
    ph = [cmath.phase(h) for h in H]
    # unwrap
    for i in range(1, len(ph)):
        while ph[i] - ph[i - 1] > math.pi: ph[i] -= 2 * math.pi
        while ph[i] - ph[i - 1] < -math.pi: ph[i] += 2 * math.pi
    slope = (ph[min(9, len(ph) - 1)] - ph[0]) / (f[min(9, len(f) - 1)] - f[0])
    Hg = []
    for i in range(nf):
        fi = i * df
        if fi < f[0] - 1e-3:
            h = cmath.rect(abs(H[0]), ph[0] + slope * (fi - f[0]))
        else:
            j = min(len(f) - 1, max(0, int(round((fi - f[0]) / df))))
            h = H[j]
        # raised-cosine taper over the top quarter of the band: a brick-wall
        # edge at fmax rings (Gibbs) through the whole step response
        if fi > 0.75 * fmax:
            h *= 0.5 * (1 + math.cos(math.pi * (fi - 0.75 * fmax) / (0.25 * fmax)))
        Hg.append(h)
    # zero-pad to 5x the band for a finer time step (ideal LPF at fmax)
    pad = 5
    N = 1
    while N < 2 * (nf - 1) * pad: N <<= 1  # power of two: zeros above fmax raise the sample rate, df stays
    spec = [0j] * N
    for i in range(nf):
        spec[i] = Hg[i]
        if 0 < i < nf - 1: spec[N - i] = Hg[i].conjugate()
    # inverse DFT via a simple radix-agnostic FFT (numpy-free): use a mixed approach
    imp = _ifft(spec)
    dt_ps = 1e12 / (N * df)
    step, acc = [], 0.0
    for x in imp:
        acc += x.real; step.append(acc)
    if xtalk_ports:
        # crosstalk: the victim's receiver deviation for an aggressor step of (VDDQ - vlo): scale by the
        # source swing through the same divider; no DC normalisation (the transfer has no DC gain)
        vlo = SR.VDDQ * rt2 / (rs2 + rt2)
        v = [(SR.VDDQ - vlo) * x * (rs2 + rt2) / rt2 for x in step[: len(step) // 2]]
        t = [i * dt_ps for i in range(len(v))]
        keep = int(15000 / dt_ps)
        return t[:keep], v[:keep]
    # normalise: DC gain of the channel is H(0); the source step is VDDQ from the POD low level
    vlo = SR.VDDQ * rt2 / (rs2 + rt2)  # POD divider (the bounce sim's convention at DC)
    # the receiver settles to VDDQ: scale the step so its final value spans vlo -> VDDQ
    final = step[len(step) // 2] if step else 1.0
    if abs(final) < 1e-9:
        return None
    v = [vlo + (SR.VDDQ - vlo) * (x / final) for x in step[: len(step) // 2]]
    t = [i * dt_ps for i in range(len(v))]
    # keep 15 ns like the bounce sim
    keep = int(15000 / dt_ps)
    return t[:keep], v[:keep]


def _ifft(x):
    """Inverse FFT, power-of-two length: conj(fft(conj x)) / n."""
    n = len(x)
    return [c.conjugate() / n for c in _fft_pow2([v.conjugate() for v in x])]


def _fft_pow2(x):
    import cmath, math
    n = len(x)
    if n == 1: return list(x)
    even = _fft_pow2(x[0::2]); odd = _fft_pow2(x[1::2])
    out = [0j] * n
    for k in range(n // 2):
        t = cmath.exp(-2j * math.pi * k / n) * odd[k]
        out[k] = even[k] + t; out[k + n // 2] = even[k] - t
    return out


def sparam_svg(slice_dir, pair=False, w=300, h=150):
    """|S21| and |S11| (or SDD21/SDD11) in dB vs frequency, from the slice."""
    import cmath
    R = os.path.join(slice_dir, 'ems', 'results')
    try:
        d0 = _load_ports(os.path.join(R, 'Port_0_data.csv'))
        d2 = _load_ports(os.path.join(R, 'Port_2_data.csv')) if pair else None
    except OSError:
        return ''
    n = 4 if pair else 2
    def S(d, i): return cmath.rect(d[1 + i], d[1 + n + i])
    pts11, pts21 = [], []
    for k, a in enumerate(d0):
        if pair:
            b = d2[k]; sa = [S(a, i) for i in range(4)]; sb = [S(b, i) for i in range(4)]
            s11 = (sa[0] - sb[0] - sa[2] + sb[2]) / 2; s21 = (sa[1] - sb[1] - sa[3] + sb[3]) / 2
        else:
            s11, s21 = S(a, 0), S(a, 1)
        f = a[0] / 1000.0
        pts11.append((f, 20 * math.log10(max(abs(s11), 1e-6)))); pts21.append((f, 20 * math.log10(max(abs(s21), 1e-6))))
    def X(f): return 36 + (f - 0.2) / 3.8 * (w - 44)
    def Y(db): return 8 + (0 - db) / 40 * (h - 26)
    out = [f'<svg viewBox="0 0 {w} {h}" class="eye">']
    for db in (0, -10, -20, -30, -40):
        out.append(f'<line x1="36" x2="{w-8}" y1="{Y(db):.1f}" y2="{Y(db):.1f}" stroke="var(--rule-2)"/><text x="32" y="{Y(db)+3:.1f}" text-anchor="end" font-size="8" fill="var(--ink-3)" font-family="IBM Plex Mono,monospace">{db}</text>')
    for f in (1, 2, 3, 4):
        out.append(f'<text x="{X(f):.1f}" y="{h-6}" text-anchor="middle" font-size="8" fill="var(--ink-3)" font-family="IBM Plex Mono,monospace">{f} GHz</text>')
    for pts, col, lab in ((pts21, 'var(--copper)', 'S21'), (pts11, 'var(--ink-3)', 'S11')):
        d = ' '.join(f'{"M" if i == 0 else "L"}{X(f):.1f} {Y(max(-40, db)):.1f}' for i, (f, db) in enumerate(pts[::4]))
        out.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="1.2"/>')
    out.append(f'<text x="{w-10}" y="14" text-anchor="end" font-size="9" fill="var(--copper)" font-family="IBM Plex Mono,monospace">{"SDD21" if pair else "S21"}</text><text x="{w-10}" y="26" text-anchor="end" font-size="9" fill="var(--ink-3)" font-family="IBM Plex Mono,monospace">{"SDD11" if pair else "S11"} dB</text></svg>')
    return ''.join(out)


def tdr_profile(slice_dir, pair=False):
    """Impedance along the trace from the reflection: the step response of
    S11 (renormalised at the port reference) integrated to Gamma(t), Z(t) =
    Z0 (1+G)/(1-G), mapped to distance at the stripline velocity (half the
    round trip). Returns [(mm, ohm)] or []."""
    import cmath
    R = os.path.join(slice_dir, 'ems', 'results')
    try:
        d0 = _load_ports(os.path.join(R, 'Port_0_data.csv'))
        d2 = _load_ports(os.path.join(R, 'Port_2_data.csv')) if pair else None
    except OSError:
        return []
    n = 4 if pair else 2
    def S(d, i): return cmath.rect(d[1 + i], d[1 + n + i])
    z0 = 100.0 if pair else 50.0
    f, H = [], []
    for k, a in enumerate(d0):
        if pair:
            b = d2[k]; sa = [S(a, i) for i in range(4)]; sb = [S(b, i) for i in range(4)]
            g = (sa[0] - sb[0] - sa[2] + sb[2]) / 2
        else:
            g = S(a, 0)
        f.append(a[0] * 1e6); H.append(g)
    df = f[1] - f[0]; fmax = f[-1]; nf = int(round(fmax / df)) + 1
    ph = [cmath.phase(x) for x in H]
    for i in range(1, len(ph)):
        while ph[i] - ph[i - 1] > math.pi: ph[i] -= 2 * math.pi
        while ph[i] - ph[i - 1] < -math.pi: ph[i] += 2 * math.pi
    slope = (ph[9] - ph[0]) / (f[9] - f[0])
    Hg = []
    for i in range(nf):
        fi = i * df
        hh = cmath.rect(abs(H[0]), ph[0] + slope * (fi - f[0])) if fi < f[0] - 1e-3 else H[min(len(H) - 1, int(round((fi - f[0]) / df)))]
        if fi > 0.75 * fmax: hh *= 0.5 * (1 + math.cos(math.pi * (fi - 0.75 * fmax) / (0.25 * fmax)))
        Hg.append(hh)
    N = 1
    while N < 2 * (nf - 1) * 5: N <<= 1
    spec = [0j] * N
    for i in range(nf):
        spec[i] = Hg[i]
        if 0 < i < nf - 1: spec[N - i] = Hg[i].conjugate()
    imp = _ifft(spec); dt_ps = 1e12 / (N * df)
    out, acc = [], 0.0
    v_mm_ps = 1 / PS_MM['strip']  # mm per ps (stripline)
    for i in range(min(len(imp) // 2, int(2 * 60 * PS_MM['strip'] / dt_ps))):  # up to 60 mm of trace
        acc += imp[i].real
        g = max(-0.95, min(0.95, acc))
        out.append((i * dt_ps * v_mm_ps / 2, z0 * (1 + g) / (1 - g)))
    return out


def tdr_svg(prof, target, w=300, h=150):
    if not prof: return ''
    zmax = max(max(z for _, z in prof), target * 1.6); zmin = min(min(z for _, z in prof), target * 0.4)
    zmin, zmax = max(0, zmin - 10), zmax + 10; xmax = prof[-1][0]
    def X(mm): return 36 + mm / xmax * (w - 44)
    def Y(z): return 8 + (zmax - z) / (zmax - zmin) * (h - 26)
    out = [f'<svg viewBox="0 0 {w} {h}" class="eye">']
    out.append(f'<rect x="36" y="{Y(target*1.15):.1f}" width="{w-44}" height="{Y(target*0.85)-Y(target*1.15):.1f}" fill="var(--pass-bg)"/>')
    for z in range(int(zmin // 20 * 20), int(zmax) + 1, 20):
        out.append(f'<line x1="36" x2="{w-8}" y1="{Y(z):.1f}" y2="{Y(z):.1f}" stroke="var(--rule-2)"/><text x="32" y="{Y(z)+3:.1f}" text-anchor="end" font-size="8" fill="var(--ink-3)" font-family="IBM Plex Mono,monospace">{z}</text>')
    for mm in range(0, int(xmax) + 1, 10):
        out.append(f'<text x="{X(mm):.1f}" y="{h-6}" text-anchor="middle" font-size="8" fill="var(--ink-3)" font-family="IBM Plex Mono,monospace">{mm} mm</text>')
    d = ' '.join(f'{"M" if i == 0 else "L"}{X(mm):.1f} {Y(max(zmin, min(zmax, z))):.1f}' for i, (mm, z) in enumerate(prof[::2]))
    out.append(f'<path d="{d}" fill="none" stroke="var(--copper)" stroke-width="1.4"/><text x="{w-10}" y="14" text-anchor="end" font-size="9" fill="var(--copper)" font-family="IBM Plex Mono,monospace">TDR Z(ohm), target {target:.0f} ±15%</text></svg>')
    return ''.join(out)


def eye_svg_compact(e):
    """A lighter drawing for the build history: every 4th PRBS segment."""
    e2 = dict(e); e2['traces'] = e['traces'][::4]
    return eye_svg(e2, 200, 130)


def eye_svg(e, w=230, h=150):
    """One eye as inline SVG: PRBS traces, the Rx mask centred at vref."""
    vlo, vhi = e['vlo'] - 0.15, e['vhi'] + 0.15
    def X(u): return 8 + u / 2 * (w - 16)
    def Y(v): return h - 8 - (v - vlo) / (vhi - vlo) * (h - 16)
    parts = [f'<svg viewBox="0 0 {w} {h}" class="eye">']
    parts.append(f'<rect x="{X(1 - MASK_W_UI/2):.1f}" y="{Y(e["vref"] + MASK_H_V/2):.1f}" width="{X(1 + MASK_W_UI/2) - X(1 - MASK_W_UI/2):.1f}" height="{Y(e["vref"] - MASK_H_V/2) - Y(e["vref"] + MASK_H_V/2):.1f}" fill="var(--cond-bg)" stroke="var(--cond)" stroke-width="0.8"/>')
    parts.append(f'<line x1="8" x2="{w-8}" y1="{Y(e["vref"]):.1f}" y2="{Y(e["vref"]):.1f}" stroke="var(--rule)" stroke-dasharray="3 3"/>')
    for seg in e['traces']:
        d = ' '.join(f'{"M" if i == 0 else "L"}{X(u):.1f} {Y(v):.1f}' for i, (u, v) in enumerate(seg))
        parts.append(f'<path d="{d}" fill="none" stroke="var(--copper)" stroke-opacity="0.35" stroke-width="0.9"/>')
    parts.append('</svg>')
    return ''.join(parts)


def eyes(b, jd):
    """Per group the worst eye (smallest PDA height) with its drawing, and
    the group's worst height/width for the table."""
    if not b['has_report'] or not jd:
        return None
    rep = os.path.join(b['dir'], 'si-report')
    segs = SR.read_csv(os.path.join(rep, 'segments.csv')); vias = SR.read_csv(os.path.join(rep, 'vias.csv')); pads = SR.read_csv(os.path.join(rep, 'pads.csv'))
    bynet = {}
    for s in segs: bynet.setdefault(s['net'], []).append(s)
    out = {}
    out['_nets'] = []  # every net's eyes, both directions, for the per-net table
    for net in sorted(bynet):
        ladder, _ = SR.chain(net, bynet[net], vias, pads)
        if not ladder: continue
        n = net.upper()
        grp = 'CA' if any(k in n for k in ('_CA', '_CS', '_CKE', '_CK')) else ('DQS' if '_DQS' in n else 'DQ')
        jg = jd['groups'].get('CA' if grp == 'CA' else 'DQ')
        if not jg: continue
        e = eye(ladder, jg['drive'], jg['odt'])  # write direction: SoC drives, DRAM ODT
        # read direction (DQ/DQS only): the DRAM drives with its pull-down strength (PDDS,
        # MR3; 40 ohm default) into the SoC PHY's ODT, through the same copper reversed
        er = None
        if grp != 'CA':
            rl = [(z, d, L) for z, d, L in reversed(ladder)]
            er = eye(rl, DRAM_PDDS, jg['odt'])
        out['_nets'].append({'net': net, 'grp': grp, 'write': (e['height_v'], e['width_ui']), 'read': (er['height_v'], er['width_ui']) if er else None})
        g = out.setdefault(grp, {'worst': None, 'worst_net': '', 'height_v': 9, 'width_ui': 9, 'n': 0, 'nfail': 0, 'measured': {}, 'margin': 9})
        g['n'] += 1
        if e['height_v'] < MASK_H_V or e['width_ui'] < MASK_W_UI: g['nfail'] += 1
        for cand, direction in ((e, 'write'), (er, 'read')):
            if cand is None: continue
            margin = min(cand['height_v'] / MASK_H_V, cand['width_ui'] / MASK_W_UI)  # the tighter of the two against the mask
            if margin < g['margin']:
                g['margin'] = margin; g['height_v'] = cand['height_v']; g['width_ui'] = cand['width_ui']; g['worst'] = cand; g['worst_net'] = net + (' (read)' if direction == 'read' else '')
        # the measured channel (field-solver S-parameters), when a slice exists for this net or its pair
        fw = b['fullwave'] or {}
        key = net if net in fw else (net[:-2] if net.endswith(('_P', '_N')) and net[:-2] in fw else None)
        if key and fw[key].get('slice'):
            pair = fw[key].get('kind') == 'pair'
            sr = sparam_channel(fw[key]['slice'], jg['drive'], jg['odt'], pair=pair)
            aggr = []
            for ag in fw[key].get('aggressors', []):  # crosstalk paths measured into this net
                ar = sparam_channel(ag['slice'], jg['drive'], jg['odt'], pair=False, xtalk_ports=ag.get('ports'))
                if ar: aggr.append(ar)
            if sr:
                em = eye_from_step(sr[0], sr[1], aggr)
                em['net'] = net; em['aggressors'] = len(aggr)
                mm = min(em['height_v'] / MASK_H_V, em['width_ui'] / MASK_W_UI)
                if key not in g['measured'] or mm < min(g['measured'][key]['height_v'] / MASK_H_V, g['measured'][key]['width_ui'] / MASK_W_UI):
                    g['measured'][key] = em
    return out


# Receiver masks by standard and speed bin (JEDEC data-input valid window):
# height in V, width in UI. LPDDR4 (JESD209-4B, 4267/3733/3200): VdIVW_total
# 140 mV, TdIVW_total 0.22 UI. DDR4 (JESD79-4C, 3200): VdIVW 0.13 V (DQ Rx
# mask), TdIVW 0.2 UI. DDR5 (JESD79-5): Rx mask with DFE, 0.125 V x 0.2 UI at
# 4800 — the page prints the mask it used.
RX_MASKS = {
    'LPDDR4': {'h': 0.140, 'w': 0.22, 'note': 'JESD209-4 tDIVW 0.22 UI × VdIVW 140 mV'},
    'DDR4':   {'h': 0.130, 'w': 0.20, 'note': 'JESD79-4 Rx mask VdIVW 130 mV × tDIVW 0.2 UI'},
    'DDR5':   {'h': 0.125, 'w': 0.20, 'note': 'JESD79-5 Rx mask (DFE) 125 mV × 0.2 UI'},
}


def board_stack(b):
    """Copper layer depths (mm from the top) and total thickness from the
    board's own stackup block, for the via-stub analysis."""
    import re
    pcb = [f for f in os.listdir(b['dir']) if f.endswith('.kicad_pcb')]
    if not pcb:
        return None
    src = open(os.path.join(b['dir'], pcb[0])).read()
    m = re.search(r'\(stackup(.*?)\n\t\t\)\n', src, re.S)
    if not m:
        return None
    depth, z, names = [], 0.0, []
    for lm in re.finditer(r'\(layer\s+"([^"]+)"\s*(.*?)\n\t\t\t\)', m.group(1), re.S):
        nm, body = lm.group(1), lm.group(2)
        t = (re.search(r'\(type\s+"([^"]+)"\)', body) or [None, ''])[1]
        th = re.search(r'\(thickness\s+([\d.]+)', body)
        if 'copper' in t:
            names.append(nm); depth.append(z); z += float(th.group(1)) if th else 0.035
        elif th:
            z += float(th.group(1))
    return {'names': names, 'depth': depth, 'total': z}


def via_stubs(b):
    """Per SI net the longest through-via stub: a via is drilled through the
    board, so a signal that turns at layer L leaves the copper below (or
    above) it as an open stub. Stub = the board below the deepest layer the
    net runs on (or above the shallowest when it enters from the back).
    Returns {net: stub_mm}; the quarter-wave resonance f = c/(4·stub·sqrt(er))."""
    st = board_stack(b)
    if not st or not b['has_report']:
        return {}
    rows = list(csv.DictReader(open(os.path.join(b['dir'], 'si-report', 'segments.csv'))))
    layers = {}
    for r in rows:
        layers.setdefault(r['net'], set()).add(int(r['layer']))
    vias = list(csv.DictReader(open(os.path.join(b['dir'], 'si-report', 'vias.csv'))))
    has_via = {v['net'] for v in vias}
    out = {}
    for net, ls in layers.items():
        if net not in has_via:
            out[net] = 0.0; continue
        deep = max(ls); shallow = min(ls)
        below = st['total'] - st['depth'][deep] if deep < len(st['depth']) else 0
        above = st['depth'][shallow] if shallow < len(st['depth']) else 0
        # the signal enters on the pad layer (top for a BGA) and turns at its deepest layer: the stub is below it
        out[net] = max(0.0, below - 0.035)
    return out


def census(b):
    """Per-net widths and model impedance from the export: dominant width,
    share above the class neck, model Z by length (members and pair legs)."""
    if not b['has_report']:
        return None
    rows = list(csv.DictReader(open(os.path.join(b['dir'], 'si-report', 'segments.csv'))))
    out = {}
    for role, label in (('3', 'members'), ('2', 'pairs')):
        rr = [r for r in rows if r['role'] == role]
        if not rr:
            continue
        per = {}
        for r in rr:
            per.setdefault(r['net'], {}).setdefault(r['width_mm'], 0.0)
            per[r['net']][r['width_mm']] += float(r['len_mm'])
        widths = sorted({float(w) for v in per.values() for w in v})
        neck = widths[0] if widths else 0
        tot = sum(sum(v.values()) for v in per.values())
        wide = sum(l for v in per.values() for w, l in v.items() if float(w) > neck + 1e-6)
        out[label] = {'above_neck': wide / tot if tot else 0, 'neck_mm': neck,
                      'dominant': {n: max(v, key=v.get) for n, v in per.items()}}
    return out


def nearest_bin(z, bins):
    return min(bins, key=lambda o: abs(o - z))


def fullwave_rows(b):
    """Field-solver numbers: pair Zdiff (+coupling), member Zse per net."""
    fw = b['fullwave'] or {}
    pairs = {k: v for k, v in fw.items() if v.get('kind') == 'pair'}
    members = {k: v for k, v in fw.items() if v.get('kind') == 'member'}
    return pairs, members


def conditions(b, jd, cs):
    """Conditions for sign-off, derived from the gates the board misses."""
    si = b['res'].get('si') or {}
    conds = []
    drc = b['res'].get('drc', {})
    erc = b['res'].get('erc') or {}
    if drc.get('error_violations') or drc.get('warnings') or drc.get('unconnected_items') or erc.get('errors') or erc.get('warnings'):
        conds.append(('DRC/ERC', f"{drc.get('error_violations',0)} / {drc.get('warnings',0)} / {drc.get('unconnected_items',0)}, ERC {erc.get('errors',0)}/{erc.get('warnings',0)}", 'all zero', REMEDY['drc']))
    for g in si.get('ddr_groups', []):
        lane = 'lane' in g['label'].lower() or g['label'].upper().startswith('DQS')
        if g['worst_skew_mm'] > g['spec_mm'] + 1e-9:
            conds.append((f"{g['label']} skew", f"{g['worst_skew_mm']:.2f} mm", f"under the {g['spec_mm']:.0f} mm spec", REMEDY['lane_spec']))
        elif g['worst_skew_mm'] > g['target_mm'] + 1e-9:
            conds.append((f"{g['label']} skew", f"{g['worst_skew_mm']:.2f} mm (in spec {g['spec_mm']:.0f})", f"under the {g['target_mm']:.0f} mm target", REMEDY['lane_target' if lane else 'addr_target']))
        if g['members_under_share']:
            conds.append((f"{g['label']} home share", f"{100*g['worst_share']:.0f}% ({g['worst_share_net']})", f">= {100*g['share_min']:.0f}% on {g['home_layer']}", REMEDY['share']))
    pairs, members = fullwave_rows(b)
    zt_pair = si.get('z_target_pair') or 80
    for name, v in pairs.items():
        z = v['z_ohm']; bins = [2 * o for o in ODT]
        nb = nearest_bin(z, bins)
        if abs(z - nb) > 0.15 * nb:
            conds.append((f"{name} Z_diff", f"{z:.0f} Ω (field solver)", f"within 15% of a legal bin ({nb} Ω) toward {zt_pair:.0f}", REMEDY['pair_bin']))
        if v.get('next_db') is not None and v['next_db'] < -30:
            conds.append((f"{name} coupling", f"NEXT {v['next_db']:.0f} dB", 'legs coupled through the run', REMEDY['pair_coupling']))
    if len(members) >= 2:
        zs = {n: v['z_ohm'] for n, v in members.items()}
        # one bin must cover every measured member (12% tolerance)
        common = [b for b in LEGAL_SE if all(abs(z - b) <= 0.15 * b for z in zs.values())]
        if not common:
            conds.append(('DQ members', ', '.join(f"{n.split('_')[-1]} {z:.0f} Ω" for n, z in zs.items()), f"one legal bin ({'/'.join(str(x) for x in LEGAL_SE)} Ω, ±15%)", REMEDY['member_bins']))
        for n, z in zs.items():
            nb = nearest_bin(z, LEGAL_SE)
            if abs(z - nb) > 0.15 * nb:
                conds.append((f"{n.split('_')[-1]} Z_se", f"{z:.0f} Ω", f"within 15% of {nb} Ω", REMEDY['member_bin']))
    return conds


def eye_conditions(b):
    """A worst-case eye under the receiver mask is a condition: the group's
    worst net, measured or bounce, whichever is smaller."""
    out = []
    for grp, g in (b.get('eyes') or {}).items():
        if grp.startswith('_'): continue
        cands = [(g['height_v'], g['width_ui'], g['worst_net'], 'bounce')]
        cands += [(em['height_v'], em['width_ui'], em['net'], 'measured') for em in g.get('measured', {}).values()]
        h, w, net, src = min(cands, key=lambda c: (c[1] / MASK_W_UI, c[0] / MASK_H_V))
        if h < MASK_H_V or w < MASK_W_UI:
            out.append((f"{grp} eye ({net.replace('LPDDR4_', '')}, {src})", f"{1000*h:.0f} mV × {w:.2f} UI", f"≥ {1000*MASK_H_V:.0f} mV × {MASK_W_UI} UI (Rx mask, net of {JITTER_UI:.2f} UI jitter)",
                        'Eye under the mask: reflections on the path (gap/serpentine unit) or the termination setting; see the eye section.'))
    return out


def verdict(b, conds):
    """Signed off when nothing is open; failed when DRC/ERC or a spec is
    missed or the impedance is out of every bin; conditional otherwise."""
    if not conds:
        return 'pass', 'Signed off'
    hard = any(c[0] == 'DRC/ERC' or 'spec' in c[2] or c[3] == REMEDY['member_bin'] for c in conds)
    return ('fail', 'Not ready') if hard else ('cond', 'Conditional')


def settings_line(jd):
    if not jd:
        return 'reflection export not present'
    parts = []
    for grp, g in jd['groups'].items():
        parts.append(f"{grp} ODT {g['odt']:.0f} Ω · drive {g['drive']:.0f} Ω ({g['npass']}/{g['n']})")
    return '<br>'.join(parts)


CSS = """
:root{--bg:#f3f5f7;--paper:#fff;--ink:#18212b;--ink-2:#4a5561;--ink-3:#7c8792;--rule:#d7dde3;--rule-2:#e9edf0;--copper:#b5622a;--copper-soft:#f3e4d8;--pass:#1e7f4f;--pass-bg:#e3f2e9;--cond:#9a6b07;--cond-bg:#f8efd4;--fail:#b3261e;--fail-bg:#f9e2df}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#0f1418;--paper:#161c22;--ink:#e6eaee;--ink-2:#aab4be;--ink-3:#7d8893;--rule:#2a333c;--rule-2:#202830;--copper:#d98c4f;--copper-soft:#3a2a1e;--pass:#5fc48f;--pass-bg:#173225;--cond:#e0b24a;--cond-bg:#3a2f12;--fail:#f08a83;--fail-bg:#3f1f1c}}
:root[data-theme="dark"]{--bg:#0f1418;--paper:#161c22;--ink:#e6eaee;--ink-2:#aab4be;--ink-3:#7d8893;--rule:#2a333c;--rule-2:#202830;--copper:#d98c4f;--copper-soft:#3a2a1e;--pass:#5fc48f;--pass-bg:#173225;--cond:#e0b24a;--cond-bg:#3a2f12;--fail:#f08a83;--fail-bg:#3f1f1c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:15px;line-height:1.5}
.page{max-width:1120px;margin:0 auto;padding:40px 28px 72px}h1,h2,h3{font-family:"IBM Plex Sans Condensed","IBM Plex Sans",sans-serif;font-weight:600;margin:0;text-wrap:balance}
h1{font-size:34px;line-height:1.1}h2{font-size:21px;margin-bottom:12px}h3{font-size:17px}
.eyebrow{font-family:"IBM Plex Mono",monospace;font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3)}
header{display:flex;flex-wrap:wrap;gap:18px 40px;align-items:flex-end;justify-content:space-between;padding-bottom:22px;border-bottom:2px solid var(--copper)}
header .meta{font-family:"IBM Plex Mono",monospace;font-size:12.5px;color:var(--ink-2);display:grid;gap:3px;text-align:right}header .meta b{color:var(--ink);font-weight:500}
.lede{max-width:68ch;color:var(--ink-2);margin:18px 0 0}.num{font-family:"IBM Plex Mono",monospace;font-variant-numeric:tabular-nums}
.verdicts{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin:30px 0 8px}
.card{background:var(--paper);border:1px solid var(--rule);border-radius:6px;padding:16px 18px 18px;display:grid;gap:10px;align-content:start}
.card .board{display:flex;align-items:baseline;justify-content:space-between;gap:10px}.card .board h3{font-size:24px}
.chip{display:inline-block;font-family:"IBM Plex Mono",monospace;font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;padding:3px 9px;border-radius:3px;font-weight:500;white-space:nowrap}
.chip.pass{background:var(--pass-bg);color:var(--pass)}.chip.cond{background:var(--cond-bg);color:var(--cond)}.chip.fail{background:var(--fail-bg);color:var(--fail)}
.card p{margin:0;color:var(--ink-2);font-size:14px}.card .settings{font-family:"IBM Plex Mono",monospace;font-size:12.5px;border-top:1px solid var(--rule-2);padding-top:10px;line-height:1.55}
section{margin-top:44px}.tablewrap{overflow-x:auto;background:var(--paper);border:1px solid var(--rule);border-radius:6px}
table{border-collapse:collapse;width:100%;min-width:760px;font-size:14px}th,td{padding:10px 14px;text-align:left;vertical-align:top;border-bottom:1px solid var(--rule-2)}
thead th{font-family:"IBM Plex Sans Condensed",sans-serif;font-size:15px;background:var(--bg);border-bottom:1px solid var(--rule)}tbody th{font-weight:500;color:var(--ink-2);width:250px}
tbody tr:last-child td,tbody tr:last-child th{border-bottom:0}.ok{color:var(--pass)}.warn{color:var(--cond)}.bad{color:var(--fail)}.was{color:var(--ink-3);font-size:12px;white-space:nowrap}
tr.group th,tr.group td{background:var(--copper-soft);color:var(--copper);font-family:"IBM Plex Mono",monospace;font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;padding:6px 14px;border-bottom:1px solid var(--rule)}
.conds{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}.cond-block{background:var(--paper);border:1px solid var(--rule);border-radius:6px;padding:18px 20px}
.cond-block h3{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:12px}.cond-block ol{margin:0;padding-left:20px;display:grid;gap:9px;font-size:14px}
.cond-block ol li::marker{color:var(--copper);font-family:"IBM Plex Mono",monospace;font-size:12px}.now{color:var(--ink-2)}.need{font-weight:500}.fix{display:block;color:var(--ink-3);font-size:13px;margin-top:2px}
.methods{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px 32px}.methods dl{margin:0;display:grid;gap:4px;font-size:14px}.methods dt{font-weight:600;font-family:"IBM Plex Sans Condensed",sans-serif;font-size:15px}.methods dd{margin:0 0 8px;color:var(--ink-2);max-width:60ch}

.eyes{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px}.eyebox.measured{border-color:var(--copper)}.eyebox{background:var(--paper);border:1px solid var(--rule);border-radius:6px;padding:10px 12px 8px}.eyehead{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;font-size:13px;margin-bottom:6px}.eyehead b{font-family:"IBM Plex Sans Condensed",sans-serif}.eye{width:100%;height:auto;display:block}
footer{margin-top:44px;padding-top:16px;border-top:1px solid var(--rule);font-family:"IBM Plex Mono",monospace;font-size:12px;color:var(--ink-3);display:flex;flex-wrap:wrap;gap:8px 28px}
"""


def cls(ok):
    return 'ok' if ok == 1 else ('warn' if ok == 0 else 'bad')


def render(boards, label):
    E = html.escape
    boards = sorted(boards, key=lambda b: -b['layers'])
    # per-board derived data
    for b in boards:
        b['judge'] = judge(b)
        b['census'] = census(b)
        b['eyes'] = eyes(b, b['judge'])
        b['stubs'] = via_stubs(b)
        b['conds'] = conditions(b, b['judge'], b['census']) + eye_conditions(b)
        b['verdict'] = verdict(b, b['conds'])
    counts = {'pass': 0, 'cond': 0, 'fail': 0}
    for b in boards:
        counts[b['verdict'][0]] += 1
    title = 'LPDDR4 Sign-off' if any((b['res'].get('si') or {}).get('ddr_groups') for b in boards) else 'SI Sign-off'
    h = ['<meta charset="utf-8">', f'<title>{E(title)}</title>',
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">',
         f'<style>{CSS}</style><div class="page">']
    summary = ', '.join(f"{v} {k}" for k, v in (('signed off', counts['pass']), ('conditional', counts['cond']), ('not ready', counts['fail'])) if v)
    h.append(f'<header><div><div class="eyebrow">Router sign-off · {E(", ".join(b["short"] for b in boards))}</div><h1 style="margin-top:8px">{E(title)}</h1>'
             f'<p class="lede">{E(summary)}. Every condition is a gate the board misses, printed as measured → required with the unit that closes it. Impedance is judged on the laid copper in a field solver where a measurement exists; the router\'s own model is shown beside it.</p></div>'
             f'<div class="meta"><div><span>build</span> <b>{E(label)}</b></div><div><span>date</span> <b>{time.strftime("%Y-%m-%d")}</b></div><div><span>rate</span> <b>{DATA_RATE_MTS:.0f} MT/s</b></div><div><span>solver</span> <b>openEMS via gerber2ems</b></div><div><span>status</span> <b>generated — unsigned</b></div></div></header>')
    # verdict strip
    h.append('<div class="verdicts">')
    for b in boards:
        v, vt = b['verdict']
        first = b['conds'][0] if b['conds'] else None
        blurb = 'No open conditions.' if not b['conds'] else f"{len(b['conds'])} open: {first[0]} {first[1]} → {first[2]}" + (' …' if len(b['conds']) > 1 else '')
        h.append(f'<div class="card"><div class="board"><h3>{E(b["short"])}</h3><span class="chip {v}">{E(vt)}</span></div><p>{E(blurb)}</p><div class="settings">{settings_line(b["judge"])}</div></div>')
    h.append('</div>')
    # table
    h.append('<section><h2>Results against the gates</h2><div class="tablewrap"><table><thead><tr><th>Gate</th>' + ''.join(f'<th>{E(b["short"])}</th>' for b in boards) + '</tr></thead><tbody>')
    def row(label, cells, group=None):
        if group:
            h.append(f'<tr class="group"><th>{E(group[0])}</th><td colspan="{len(boards)}">{E(group[1])}</td></tr>')
        h.append(f'<tr><th>{label}</th>' + ''.join(cells) + '</tr>')
    cells = []
    for b in boards:
        d = b['res'].get('drc', {}); e = b['res'].get('erc') or {}
        ok = not (d.get('error_violations') or d.get('warnings') or d.get('unconnected_items') or e.get('errors') or e.get('warnings'))
        cells.append(f'<td class="num {"ok" if ok else "bad"}">{d.get("error_violations",0)} / {d.get("warnings",0)} / {d.get("unconnected_items",0)} · ERC {e.get("errors","-")}/{e.get("warnings","-")}</td>')
    row('DRC errors / warnings / unconnected · ERC', cells, ('Design rules', 'KiCad DRC + ERC + schematic parity, all zero'))
    # timing rows: union of group labels
    labels = []
    for b in boards:
        for g in (b['res'].get('si') or {}).get('ddr_groups', []):
            if g['label'] not in labels:
                labels.append(g['label'])
    first = True
    for lab in labels:
        cells = []
        for b in boards:
            g = next((x for x in (b['res'].get('si') or {}).get('ddr_groups', []) if x['label'] == lab), None)
            if not g:
                cells.append('<td class="num">—</td>'); continue
            st = 1 if g['worst_skew_mm'] <= g['target_mm'] else (0 if g['worst_skew_mm'] <= g['spec_mm'] else -1)
            tag = '' if st == 1 else (' <span class="was">spec</span>' if st == 0 else ' <span class="was">over spec</span>')
            cells.append(f'<td class="num {cls(st)}">{g["worst_skew_mm"]:.2f} mm{tag}</td>')
        grp = ('Timing', 'worst member-to-strobe skew per group: target / spec tiers from the standard') if first else None
        row(f'{E(lab)} skew (target/spec)', cells, grp); first = False
    cells = []
    for b in boards:
        gs = (b['res'].get('si') or {}).get('ddr_groups', [])
        cells.append('<td>' + E(', '.join(f"{g['label']} {g['home_layer']} {100*g['worst_share']:.0f}%" for g in gs)) + '</td>')
    row('Home layers (worst share)', cells)
    # impedance: field solver
    first = True
    pnames = []
    for b in boards:
        for n in fullwave_rows(b)[0]:
            if n not in pnames: pnames.append(n)
    for n in pnames:
        cells = []
        for b in boards:
            v = fullwave_rows(b)[0].get(n)
            if not v:
                cells.append('<td class="num was">not measured</td>'); continue
            nb = nearest_bin(v['z_ohm'], [2 * o for o in ODT]); st = 1 if abs(v["z_ohm"] - nb) <= 0.15 * nb else 0
            nx = f' <span class="was">NEXT {v["next_db"]:.0f} dB</span>' if v.get('next_db') is not None else ''
            cells.append(f'<td class="num {cls(st)}">{v["z_ohm"]:.0f} Ω <span class="was">bin {nb}</span>{nx}</td>')
        row(f'{E(n)} Z<sub>diff</sub>', cells, ('Impedance — field solver', 'characteristic Z of the laid copper, 0.2–2 GHz (openEMS); legal LPDDR4 ODT bins per leg 40/48/60/80/120 Ω, pairs 2×') if first else None); first = False
    mnames = []
    for b in boards:
        for n in fullwave_rows(b)[1]:
            if n not in mnames: mnames.append(n)
    for n in mnames:
        cells = []
        for b in boards:
            v = fullwave_rows(b)[1].get(n)
            if not v:
                cells.append('<td class="num was">not measured</td>'); continue
            nb = nearest_bin(v['z_ohm'], LEGAL_SE); st = 1 if abs(v['z_ohm'] - nb) <= 0.12 * nb else 0
            cells.append(f'<td class="num {cls(st)}">{v["z_ohm"]:.0f} Ω <span class="was">bin {nb}</span></td>')
        row(f'{E(n)} Z<sub>se</sub>', cells, ('Impedance — field solver', 'characteristic Z of the laid copper (openEMS)') if first else None); first = False
    # router model
    cells = []
    for b in boards:
        si = b['res'].get('si') or {}
        pz = [p['zdiff_laid_ohm'] for p in si.get('pairs', []) if p['zdiff_laid_ohm'] > 0]
        dz = [g['z_laid_ohm'] for g in si.get('ddr_groups', []) if g['z_laid_ohm'] > 0]
        cells.append(f'<td class="num">{(f"{min(pz):.0f}–{max(pz):.0f}" if pz else "—")} / {(f"{min(dz):.0f}–{max(dz):.0f}" if dz else "—")} Ω</td>')
    row('Router model, pairs / members as laid', cells, ('Impedance — router model', 'the router\'s own stackup model on the same copper (for reference; reads 4–10 Ω low on inner striplines)'))
    cells = []
    for b in boards:
        c = b['census']
        cells.append('<td class="num">' + (f"members {100*c['members']['above_neck']:.0f}%" if c and 'members' in c else '—') + (f" · pairs {100*c['pairs']['above_neck']:.0f}%" if c and 'pairs' in c else '') + '</td>')
    row('Copper above the class neck', cells)
    cells = []
    for b in boards:
        jd = b['judge']
        cells.append(f'<td class="num">{jd["npass"]} / {jd["n"]}</td>' if jd else '<td class="num was">not run</td>')
    row('Nets passing the masks', cells, ('Reflection judge', 'lossless-line bounce on router-model impedances, vendor-calibrated masks, best legal ODT/drive per group'))
    cells = []
    for b in boards:
        ey = b['eyes']
        if not ey: cells.append('<td class="num was">not run</td>'); continue
        parts = []
        for grp in ('DQ', 'DQS', 'CA'):
            g = ey.get(grp)
            if not g: continue
            ok = g['height_v'] >= MASK_H_V and g['width_ui'] >= MASK_W_UI
            parts.append(f'<span class="{"ok" if ok else "warn"}">{grp} {1000*g["height_v"]:.0f} mV × {g["width_ui"]:.2f} UI</span>')
            for key, em in g.get('measured', {}).items():
                okm = em['height_v'] >= MASK_H_V and em['width_ui'] >= MASK_W_UI
                parts.append(f'<span class="{"ok" if okm else "warn"}">{grp} measured {1000*em["height_v"]:.0f} mV × {em["width_ui"]:.2f} UI</span>')
        cells.append('<td class="num">' + ' · '.join(parts) + '</td>')
    row('Worst eye per group (PDA)', cells, ('Eye diagrams', f'PRBS-7 at {DATA_RATE_MTS:.0f} MT/s (UI {UI_PS:.0f} ps) on the bounce model with the chosen settings; worst-case opening by peak-distortion analysis against the JEDEC Rx mask {1000*MASK_H_V:.0f} mV × {MASK_W_UI} UI'))
    cells = []
    for b in boards:
        stubs = b.get('stubs') or {}
        if not stubs: cells.append('<td class="num was">—</td>'); continue
        worst = max(stubs.values()); wn = max(stubs, key=stubs.get)
        fres = 3e8 / (4 * worst * 1e-3 * 4.3 ** 0.5) / 1e9 if worst > 0.05 else float('inf')
        f3 = 3 * DATA_RATE_MTS / 2 / 1000  # third harmonic of the data fundamental, GHz
        ok = fres > 2 * f3
        cells.append(f'<td class="num {"ok" if ok else "warn"}">{worst:.2f} mm ({E(wn.replace("LPDDR4_",""))}) · λ/4 at {fres:.1f} GHz</td>')
    row('Worst through-via stub', cells, ('Via stubs', f'through-vias leave the board below the deepest layer as an open stub; its quarter-wave resonance should sit well above the 3rd harmonic ({3*DATA_RATE_MTS/2000:.1f} GHz at {DATA_RATE_MTS:.0f} MT/s) or the layer/back-drill must change'))
    cells = [f'<td><span class="chip {b["verdict"][0]}">{E(b["verdict"][1])}</span></td>' for b in boards]
    row('Sign-off', cells, ('Verdict', ''))
    h.append('</tbody></table></div></section>')
    # eyes
    h.append(f'<section><h2>Eye diagrams</h2><p class="lede" style="margin:0 0 14px"><b>Method.</b> Stimulus PRBS-7 at {DATA_RATE_MTS:.0f} MT/s (UI {UI_PS:.0f} ps), 100 ps edges. Channel: the bounce model (every segment a lossless line at its as-laid impedance — reflections only) or, where a field-solver slice exists, the openEMS S-parameters of the actual copper renormalised to the terminations (loss, reflections, and crosstalk from the sliced aggressor). Terminations: the legal LPDDR4 setting chosen per group above; write direction SoC PHY → DRAM ODT to VDDQ (POD), read direction DRAM PDDS {DRAM_PDDS:.0f} Ω → SoC ODT. Analysis: worst-case peak-distortion over every bit pattern (sum of the ISI and crosstalk taps), sampled at the point the DRAM trains to (the largest opening) with V<sub>ref</sub> at its centre; width net of a {JITTER_UI:.2f} UI jitter budget (transmitter DCD/RJ and residual tDQS2DQ), drawn as edge smear. Mask: JESD209-4 data-input valid window tDIVW {MASK_W_UI} UI × VdIVW {1000*MASK_H_V:.0f} mV (the amber rectangle). Drawings show the PRBS pattern folded on two UI; the numbers are the worst case, not the drawing\'s.</p><div class="eyes">')
    for b in boards:
        ey = b['eyes']
        if not ey: continue
        for grp in ('DQ', 'DQS', 'CA'):
            g = ey.get(grp)
            if not g or not g['worst']: continue
            ok = g['height_v'] >= MASK_H_V and g['width_ui'] >= MASK_W_UI
            h.append(f'<div class="eyebox"><div class="eyehead"><b>{E(b["short"])} · {grp}</b> <span class="was">bounce · {E(g["worst_net"])}</span> <span class="chip {"pass" if ok else "fail"}">{"PASS" if ok else "FAIL"} · {1000*g["height_v"]:.0f} mV × {g["width_ui"]:.2f} UI</span></div>{eye_svg(g["worst"])}</div>')
            for key, em in g.get('measured', {}).items():
                okm = em['height_v'] >= MASK_H_V and em['width_ui'] >= MASK_W_UI
                tag = 'field solver' + (f' + {em["aggressors"]} aggressor(s)' if em.get('aggressors') else ', no crosstalk')
                h.append(f'<div class="eyebox measured"><div class="eyehead"><b>{E(b["short"])} · {grp}</b> <span class="was">{E(tag)} · {E(em["net"])}</span> <span class="chip {"pass" if okm else "fail"}">{"PASS" if okm else "FAIL"} · {1000*em["height_v"]:.0f} mV × {em["width_ui"]:.2f} UI</span></div>{eye_svg(em)}</div>')
    h.append('</div></section>')
    # per-net eye table (both directions), the timing budget, and the measured nets' S-parameters/TDR
    h.append(f'<section><h2>Eye openings per net</h2><p class="lede" style="margin:0 0 14px">Every SI net at the settings chosen above: write direction (SoC PHY drive → DRAM ODT) and read direction (DRAM PDDS {DRAM_PDDS:.0f} Ω → SoC ODT), worst-case peak-distortion opening net of the {JITTER_UI:.2f} UI jitter budget, margin to the mask as the tighter of height/width.</p><div class="tablewrap"><table><thead><tr><th>Board</th><th>Net</th><th>Group</th><th>Write H × W</th><th>Read H × W</th><th>Margin</th><th>Verdict</th></tr></thead><tbody>')
    for b in boards:
        for r in (b['eyes'] or {}).get('_nets', []):
            def cell(hw):
                if not hw: return '<td class="num was">—</td>'
                ok = hw[0] >= MASK_H_V and hw[1] >= MASK_W_UI
                return f'<td class="num {"ok" if ok else "bad"}">{1000*hw[0]:.0f} mV × {hw[1]:.2f} UI</td>'
            cands = [x for x in (r['write'], r['read']) if x]
            mg = min(min(x[0] / MASK_H_V, x[1] / MASK_W_UI) for x in cands)
            h.append(f'<tr><th>{E(b["short"])}</th><td>{E(r["net"].replace("LPDDR4_", ""))}</td><td>{r["grp"]}</td>{cell(r["write"])}{cell(r["read"])}<td class="num">{mg:.2f}×</td><td><span class="chip {"pass" if mg >= 1 else "fail"}">{"PASS" if mg >= 1 else "FAIL"}</span></td></tr>')
    h.append('</tbody></table></div></section>')
    h.append(f'<section><h2>Timing budget per group</h2><p class="lede" style="margin:0 0 14px">Unit interval at {DATA_RATE_MTS:.0f} MT/s less the receiver mask, the jitter budget and the static member-to-strobe skew as laid (converted at {PS_MM["strip"]} ps/mm stripline, {PS_MM["micro"]} ps/mm microstrip); what remains is the margin the DRAM\'s training must not need. LPDDR4 trains DQS-to-DQ per lane (tDQS2DQ), so a negative static margin is absorbed within spec — the target tier is where it stays positive.</p><div class="tablewrap"><table><thead><tr><th>Board · group</th><th>UI</th><th>− mask</th><th>− jitter</th><th>− static skew</th><th>− eye closure</th><th>= margin</th></tr></thead><tbody>')
    for b in boards:
        si = b['res'].get('si') or {}
        for g in si.get('ddr_groups', []):
            ui = UI_PS; mask = MASK_W_UI * ui; jit = JITTER_UI * ui
            outer = g['home_layer'] in ('F.Cu', 'B.Cu'); skew = g['worst_skew_mm'] * (PS_MM['micro'] if outer else PS_MM['strip'])
            grp = 'CA' if 'lane' not in g['label'].lower() else 'DQ'
            ey = (b['eyes'] or {}).get(grp) or (b['eyes'] or {}).get('DQS')
            closure = (1 - (ey['width_ui'] + JITTER_UI)) * ui if ey else 0  # the eye's own closure, before the jitter budget
            margin = ui - mask - jit - skew - closure
            h.append(f'<tr><th>{E(b["short"])} · {E(g["label"])}</th><td class="num">{ui:.0f} ps</td><td class="num">{mask:.0f}</td><td class="num">{jit:.0f}</td><td class="num">{skew:.0f} ({g["worst_skew_mm"]:.1f} mm)</td><td class="num">{closure:.0f}</td><td class="num {"ok" if margin > 0 else "warn"}">{margin:.0f} ps</td></tr>')
    h.append('</tbody></table></div></section>')
    h.append('<section><h2>Measured channels</h2><p class="lede" style="margin:0 0 14px">Field-solver S-parameters of the sliced nets (0.2–4 GHz) and the impedance profile along the trace from the reflection (TDR at the port reference; the shaded band is the target ±15 %).</p><div class="eyes">')
    for b in boards:
        fw = b['fullwave'] or {}
        for net, v in fw.items():
            if not v.get('slice'): continue
            pair = v.get('kind') == 'pair'; target = (b['res'].get('si') or {}).get('z_target_pair' if pair else 'z_target_se') or (80 if pair else 40)
            h.append(f'<div class="eyebox"><div class="eyehead"><b>{E(b["short"])} · {E(net.replace("LPDDR4_", ""))}</b> <span class="was">|S| vs f</span></div>{sparam_svg(v["slice"], pair)}</div>')
            h.append(f'<div class="eyebox"><div class="eyehead"><b>{E(b["short"])} · {E(net.replace("LPDDR4_", ""))}</b> <span class="was">TDR · Z_c {v["z_ohm"]:.0f} Ω</span></div>{tdr_svg(tdr_profile(v["slice"], pair), target)}</div>')
    h.append('</div></section>')
    # conditions
    h.append('<section><h2>Conditions for sign-off</h2><div class="conds">')
    for b in boards:
        v, vt = b['verdict']
        h.append(f'<div class="cond-block"><h3>{E(b["short"])} <span class="chip {v}">{E(vt)}</span></h3>')
        if not b['conds']:
            h.append(f'<p class="now">No open conditions. Bring-up settings: {settings_line(b["judge"]).replace("<br>", "; ")}.</p>')
        else:
            h.append('<ol>' + ''.join(f'<li><span class="now">{E(c[0])}: {E(c[1])}</span> → <span class="need">{E(c[2])}</span><span class="fix">{E(c[3])}</span></li>' for c in b['conds']) + '</ol>')
        h.append('</div>')
    h.append('</div></section>')
    # methods
    stacks = ', '.join(sorted({(b['res'].get('si') or {}).get('stack', '') for b in boards} - {''}))
    h.append('<section><h2>How the numbers were produced</h2><div class="methods"><dl>'
             f'<dt>Boards</dt><dd>{E(", ".join(b["name"] for b in boards))}; stack-ups {E(stacks) or "not on file"}. DRC/ERC by kicad-cli; the router removes its own debris before measuring.</dd>'
             '<dt>Timing</dt><dd>Worst member-to-strobe skew per group against the two-tier budgets of the standard; "spec" means training absorbs it, not a target pass.</dd></dl><dl>'
             '<dt>Impedance</dt><dd>Field solver (openEMS via gerber2ems, scripts/fullwave/): one net per class sliced with its planes and GND vias, Z from the two-port ABCD matrix at 0.2–2 GHz. The router model is its stackup solve on the same copper.</dd>'
             '<dt>Legal bins</dt><dd>LPDDR4 ODT 40/48/60/80/120/240 Ω per leg (MR11), PHY drive 34–60 Ω; a pair sees 2× ODT. A group must sit in one bin; the reflection judge picks the setting.</dd>'
             '<dt>Receiver masks</dt><dd>' + '; '.join(f"{k}: {v['note']}" for k, v in RX_MASKS.items()) + f'. This page judges at {DATA_RATE_MTS:.0f} MT/s with the {"LPDDR4" if MASK_H_V == 0.14 else "selected"} mask (KLAYOUT_DATA_RATE selects the rate).</dd></dl></section>')
    h.append(f'<footer><span>build {E(label)}</span><span>scripts/signoff.py · scripts/si_report.py · scripts/fullwave/</span><span>SI reviewer: ____________________ date: __________</span><span>design owner: ____________________ date: __________</span></footer></div>')
    return '\n'.join(h)


def record(boards, label, path):
    """Append this build's per-board verdict and metrics to the history
    (docs/signoff-history.json), replacing an entry of the same label."""
    hist = json.load(open(path)) if os.path.exists(path) else []
    entry = {'label': label, 'date': time.strftime('%Y-%m-%d'), 'boards': {}}
    for b in boards:
        si = b['res'].get('si') or {}
        pairs, members = fullwave_rows(b)
        lanes = [g['worst_skew_mm'] for g in si.get('ddr_groups', []) if 'lane' in g['label'].lower()]
        pz = next((v['z_ohm'] for k, v in pairs.items() if 'DQS0' in k), None)
        pn = next((v.get('next_db') for k, v in pairs.items() if 'DQS0' in k), None)
        entry['boards'][b['short']] = {
            'verdict': b['verdict'][0], 'open': len(b['conds']),
            'pair_zdiff': pz, 'pair_next_db': pn,
            'members': {k.split('_')[-1]: v['z_ohm'] for k, v in members.items()},
            'lane_worst_mm': max(lanes) if lanes else None,
            'addr_mm': next((g['worst_skew_mm'] for g in si.get('ddr_groups', []) if 'lane' not in g['label'].lower()), None),
            'above_neck': (b['census'] or {}).get('members', {}).get('above_neck'),
            'judge': f"{b['judge']['npass']}/{b['judge']['n']}" if b['judge'] else None,
            'conditions': [c[0] + ': ' + c[1] + ' -> ' + c[2] for c in b['conds']],
            'eyes': {grp: {'h_mv': 1000 * g['height_v'], 'w_ui': g['width_ui'], 'net': g['worst_net'],
                           'svg': eye_svg_compact(g['worst']) if g.get('worst') else None,
                           'measured': {k: {'h_mv': 1000 * em['height_v'], 'w_ui': em['width_ui'], 'net': em['net'],
                                            'aggressors': em.get('aggressors', 0), 'svg': eye_svg_compact(em)}
                                        for k, em in g.get('measured', {}).items()}}
                     for grp, g in (b['eyes'] or {}).items() if not grp.startswith('_')},
        }
    hist = [h for h in hist if h['label'] != label] + [entry]
    json.dump(hist, open(path, 'w'), indent=1)


def main():
    args = sys.argv[1:]
    out = 'signoff.html'; label = 'unlabelled'; dirs = []; hist = None
    i = 0
    while i < len(args):
        if args[i] == '-o': out = args[i + 1]; i += 2
        elif args[i] == '--label': label = args[i + 1]; i += 2
        elif args[i] == '--record': hist = args[i + 1]; i += 2
        else: dirs.append(args[i]); i += 1
    if not dirs:
        raise SystemExit(__doc__)
    if label == 'unlabelled':
        try:
            label = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True,
                                   cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip() or label
        except Exception:
            pass
    boards = [read_dir(d) for d in dirs]
    page = render(boards, label)
    open(out, 'w').write(page)
    if hist:
        record(boards, label, hist)
    for b in boards:
        print(f"{b['short']:5s} {b['verdict'][1]:12s} {len(b['conds'])} condition(s)" + (f"; judge {b['judge']['npass']}/{b['judge']['n']}" if b['judge'] else ''))
    print('signoff ->', out)


if __name__ == '__main__':
    main()
