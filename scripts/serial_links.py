#!/usr/bin/env python3
"""serial_links.py — eye diagrams for the board's serial links, at the rate and
electrical limits of the parts that actually sit at each end.

The LPDDR4 judge in signoff.py treats every SI net as a single-ended DQ line at
4267 MT/s with DRAM terminations. That is right for a memory bus and wrong for
a camera link. This module recognises a differential pair's interface from the
parts at its two ends (part value / footprint plus the pad the pair lands on),
takes the transmitter's and receiver's limits from their datasheets, and draws
the eye the receiver sees.

Interfaces known today (extend PROFILES for new parts):
  MIPI CSI-2 over D-PHY   sensor TX -> serializer/SoC RX, 100 ohm differential
  TI V3Link / FPD-Link    serializer forward channel on DOUT+/-, coax or STP

Channel model: each leg is the router's as-laid impedance ladder (the export's
differential Z halved = the odd-mode impedance of the leg) driven by a
Thevenin source at the TX output impedance into half the RX differential
termination to the (virtual) ground, lossless lines, reflections only
(si_report.bounce). The differential signal is P - N, so intra-pair skew and
any impedance difference between the legs show up in the eye. No loss, no
crosstalk, no package models: the eye is the routing's contribution.

Analysis (D-PHY): worst-case peak distortion over every bit pattern against the
receiver's fixed differential threshold (0 V +- VIDTH). The receiver samples
data with the forwarded clock lane, so the sampling instant is the data eye's
centre moved by the clock-to-data flight difference; the data must stay beyond
+-VIDTH for tSETUP + tHOLD around it after the transmitter's own clock-to-data
skew allowance. Worst corner of the TX output impedance, TX edge rate and RX
termination, at the minimum VOD.
"""
import os, re, glob, math, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import si_report as SR

# ---------------------------------------------------------------- the parts --
# Every number carries its source. 'match' is tested against the footprint's
# Value and library id; 'pins' maps an interface role to the pads carrying it.
PROFILES = [
    {'match': r'AR0235',
     'source': 'onsemi AR0235CS datasheet (Tables 11-12, MIPI HS transmitter; pin table 62-ball CSP)',
     'pins': {'dphy_tx': {'B6', 'B7', 'D6', 'D7', 'B8', 'B9', 'E6', 'E7', 'E8', 'E9'}},
     'dphy_tx': {'max_mbps': 850,            # "Max MIPI Data Rate 850 Mbps/lane" (Table 12 lists 900 Mb/s)
                 'vod_min': 0.140, 'vod_max': 0.270,   # VOD, V (Table 11)
                 'zos': (40.0, 62.5),         # single-ended output impedance, ohm (Table 11)
                 'tr2080_ps': (150.0, 333.0), # 20-80 % rise/fall (Table 12)
                 'dphy': '1.2'},
     'clock_pins': {'D6', 'D7'}},
    {'match': r'TSER953',
     'source': 'TI TSER953 datasheet SNLS696C (5.3 Recommended Operating Conditions; 5.5 CSI-2 HS DC/AC and V3Link driver specs; pin functions)',
     'pins': {'csi2_rx': {'1', '2', '3', '4', '5', '6', '29', '30', '31', '32'},
              'v3link_tx': {'13', '14'}},
     'csi2_rx': {'max_mbps': 832,            # "Mipi data rate (per CSI-2 lane) 80-832 Mbps"
                 'vidth': 0.070,              # VIDTH / VIDTL +-70 mV
                 'zid': (80.0, 125.0),        # differential input impedance, ohm (100 typ)
                 'tsetup_ui': 0.15, 'thold_ui': 0.15},
     'clock_pins': {'5', '6'},
     'v3link_tx': {'mbps': 4160,              # 4.16 Gbps forward channel
                   'vout_se_min': 0.520,      # single-ended output, V p-p into 50 ohm (coax mode)
                   'vod_pp_min': 1.040,       # differential output, V p-p into 100 ohm (STP mode)
                   'rt_se': 50.0,             # single-ended termination (40-60)
                   'tr2080_ps': 65.0,         # forward-channel transition time 20-80 % (typ; no max given)
                   'jitter_ui': 0.21,         # forward-channel output jitter, synchronous mode (typ)
                   'eye_ref_coax_mv': 425, 'eye_ref_stp_mv': 850}},  # EH-FC typ, at the serializer output
]
# MIPI D-PHY v1.2 (the AR0235's stated compliance), data rates up to 1 Gbps:
# the transmitter's clock-to-data skew TSKEW[TX] is +-0.15 UI. The standard,
# not either datasheet, is the source of this one figure.
DPHY_TSKEW_TX_UI = 0.15
PS_MM = {'strip': SR.PS_MM_STRIP, 'micro': SR.PS_MM_MICRO}


def _profile(value, lib):
    for p in PROFILES:
        if re.search(p['match'], value or '', re.I) or re.search(p['match'], lib or '', re.I):
            return p
    return None


def board_parts(board_path):
    """{ref: {'value', 'lib', 'pads': {pad: net}, 'nets': {net: [pads]}}} from a .kicad_pcb."""
    t = open(board_path).read()
    parts = {}
    starts = [m.start() for m in re.finditer(r'\n\t\(footprint "', t)] + [len(t)]
    for a, b2 in zip(starts, starts[1:]):
        blk = t[a:b2]
        mref = re.search(r'\(property "Reference" "([^"]*)"', blk)
        if not mref:
            continue
        mv = re.search(r'\(property "Value" "([^"]*)"', blk)
        ml = re.search(r'\(footprint "([^"]+)"', blk)
        pads, nets = {}, {}
        for pm in re.finditer(r'\(pad "([^"]*)" ', blk):
            end = blk.find('\n\t\t(pad ', pm.end())
            seg = blk[pm.end(): end if end > 0 else len(blk)]
            mn = re.search(r'\(net (?:\d+ )?"([^"]*)"\)', seg)
            if mn:
                pads[pm.group(1)] = mn.group(1)
                nets.setdefault(mn.group(1), []).append(pm.group(1))
        mly = re.search(r'\(layer "([^"]+)"', blk)
        thru = {pm.group(1) for pm in re.finditer(r'\(pad "([^"]*)" (?:thru_hole|np_thru_hole) ', blk)}
        parts[mref.group(1)] = {'value': mv.group(1) if mv else '', 'lib': ml.group(1) if ml else '',
                                'pads': pads, 'nets': nets, 'side': mly.group(1) if mly else 'F.Cu', 'thru': thru}
    return parts


def find_board(d, res):
    """The finished board of an output directory (not a progress/stage file)."""
    name = os.path.basename(str((res or {}).get('board', '')))
    if name and os.path.exists(os.path.join(d, name)):
        return os.path.join(d, name)
    cands = [f for f in glob.glob(os.path.join(d, '*.kicad_pcb'))
             if '.progress.' not in f and not os.path.basename(f).startswith('.')]
    return cands[0] if cands else None


def _ends(parts, net):
    """[(ref, pad, profile)] for every pad on the net."""
    out = []
    for ref, p in parts.items():
        for pad in p['nets'].get(net, []):
            out.append((ref, pad, _profile(p['value'], p['lib'])))
    return out


def detect(b):
    """Classify the board's differential pairs into serial links.
    Returns {'links': [...], 'nets': set(), 'unknown': [pair names]}."""
    res = b['res']
    pairs = []  # once each: the verdict may list a pair per routing stage
    for p in (res.get('si') or {}).get('pairs', []):
        if p['pair'] not in pairs:
            pairs.append(p['pair'])
    board = find_board(b['dir'], res)
    out = {'links': [], 'nets': set(), 'unknown': [], 'board': board}
    if not pairs or not board:
        out['unknown'] = pairs
        return out
    parts = board_parts(board)
    for pr in pairs:
        pn, nn = [x.strip() for x in pr.split('/')]
        endp = _ends(parts, pn)
        tx = rx = None; kind = None
        for ref, pad, prof in endp:
            if not prof:
                continue
            for role, pins in prof['pins'].items():
                if pad in pins:
                    if role in ('dphy_tx', 'v3link_tx'):
                        tx = (ref, pad, prof, role)
                    elif role == 'csi2_rx':
                        rx = (ref, pad, prof, role)
        if tx and tx[3] == 'dphy_tx' and rx:
            t, r = tx[2]['dphy_tx'], rx[2]['csi2_rx']
            clock = tx[1] in tx[2].get('clock_pins', set()) or rx[1] in rx[2].get('clock_pins', set())
            link = {'pair': pr, 'p': pn, 'n': nn, 'kind': 'csi2', 'tx': tx[0], 'rx': rx[0],
                    'mbps': min(t['max_mbps'], r['max_mbps']), 'txp': t, 'rxp': r, 'tx_src': tx[2]['source'], 'rx_src': rx[2]['source'], 'clock': clock,
                    'label': f"MIPI CSI-2 D-PHY {min(t['max_mbps'], r['max_mbps']):.0f} Mbps/lane",
                    'sources': [tx[2]['source'], rx[2]['source']]}
            kind = 'csi2'
        elif tx and tx[3] == 'v3link_tx':
            t = tx[2]['v3link_tx']
            # coax mode: DOUT- goes through its AC cap into a ~50 ohm resistor
            # (the datasheet's coax connection), DOUT+ through its cap to the
            # connector. STP: both caps go to the connector.
            mode = 'stp'
            for ref, pad, prof in _ends(parts, nn):
                if ref == tx[0]:
                    continue
                other = [parts[ref]['pads'][q] for q in parts[ref]['pads'] if parts[ref]['pads'][q] != nn]
                for onet in other:
                    for ref2, pad2, prof2 in _ends(parts, onet):
                        if ref2 != ref and ref2.upper().startswith('R') and \
                                re.search(r'\b(49|50|51)(\.\d)?\s*R|\b(49|50|51)(\.\d)?\s*(ohm|Ω)?\b', parts[ref2]['value'], re.I):
                            mode = 'coax'
            link = {'pair': pr, 'p': pn, 'n': nn, 'kind': 'v3link', 'tx': tx[0], 'rx': None,
                    'mbps': t['mbps'], 'txp': t, 'tx_src': tx[2]['source'], 'mode': mode, 'clock': False,
                    'label': f"TI V3Link forward channel {t['mbps']/1000:.2f} Gbps ({mode})",
                    'sources': [tx[2]['source']]}
            kind = 'v3link'
        if kind:
            out['links'].append(link); out['nets'].update((pn, nn))
        else:
            out['unknown'].append(pr)
    return out


# ------------------------------------------------------------ the channel --
def trace_path(rows, vias, src, dst, tol=0.02, debug=False):
    """The signal path of a pair leg: the SHORTEST copper path from the
    transmitter pad to the receiver pad through the exported segments
    (endpoints joined within tol on a layer, an endpoint touching another
    segment's side splits it, a via joins every layer within its radius).
    Returns [(row, length_mm)] in path order, or None.
    (si_report.chain walks from the pad with the most pads to the farthest
    node; on these pairs it lost 8-17 mm of each path at tees and meanders.)"""
    import heapq
    segs = []
    for r in rows:
        segs.append([float(r['x1']), float(r['y1']), float(r['x2']), float(r['y2']), r])
    # split every segment at the endpoints of others that land on its side
    # copper contact is overlap, as KiCad judges it: an end within half the
    # summed widths of another track's end or side touches it (router junction
    # gaps of 0.07-0.10 mm on 0.127 mm tracks broke three legs at 0.02 mm)
    pts = [(sg[0], sg[1], sg[4]['layer'], float(sg[4]['width_mm'])) for sg in segs] + \
          [(sg[2], sg[3], sg[4]['layer'], float(sg[4]['width_mm'])) for sg in segs]
    pieces = []
    for x1, y1, x2, y2, r in segs:
        dx, dy = x2 - x1, y2 - y1; L2 = dx * dx + dy * dy
        cuts = [0.0, 1.0]
        if L2 > 1e-10:
            reach = float(r['width_mm']) / 2
            for px, py, ly, pw in pts:
                if ly != r['layer']: continue
                u = ((px - x1) * dx + (py - y1) * dy) / L2
                if 1e-4 < u < 1 - 1e-4 and math.hypot(x1 + u * dx - px, y1 + u * dy - py) <= reach + pw / 2 - 1e-4:
                    cuts.append(u)
        cuts = sorted(set(cuts))
        for a2, b3 in zip(cuts, cuts[1:]):
            pieces.append((x1 + a2 * dx, y1 + a2 * dy, x1 + b3 * dx, y1 + b3 * dy, r))
    # nodes: snapped per layer
    keyof = {}
    def node(x, y, ly):
        k = (round(x / tol), round(y / tol), ly)
        for dk in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            kk = (k[0] + dk[0], k[1] + dk[1], ly)
            if kk in keyof: return keyof[kk]
        keyof[k] = len(keyof); coords.append((x, y, ly, lname[ly])); return keyof[k]
    coords, adj = [], {}
    lname = {r['layer']: r['layer_name'] for r in rows}
    for x1, y1, x2, y2, r in pieces:
        a2, b3 = node(x1, y1, r['layer']), node(x2, y2, r['layer'])
        L = math.hypot(x2 - x1, y2 - y1)
        adj.setdefault(a2, []).append((b3, L, r)); adj.setdefault(b3, []).append((a2, L, r))
    # ends in copper contact on one layer: a zero-length join
    wof = {}
    for x1, y1, x2, y2, r in pieces:
        for x, y in ((x1, y1), (x2, y2)):
            i = node(x, y, r['layer']); wof[i] = max(wof.get(i, 0.0), float(r['width_mm']))
    ids = sorted(wof)
    for a2 in range(len(ids)):
        i = ids[a2]; xi, yi, li, _ = coords[i]
        for b3 in range(a2 + 1, len(ids)):
            j = ids[b3]; xj, yj, lj, _ = coords[j]
            dd = math.hypot(xi - xj, yi - yj)
            if li == lj and dd <= (wof[i] + wof[j]) / 2 - 1e-4:  # weighted by its length: never a free hop along a curve
                adj.setdefault(i, []).append((j, dd, 'join')); adj.setdefault(j, []).append((i, dd, 'join'))
    # vias join the layers
    for v in vias:
        vx, vy, rad = float(v['x']), float(v['y']), float(v.get('size_mm') or 0.25) / 2 + tol
        near = [i for i, (x, y, _, _) in enumerate(coords) if math.hypot(x - vx, y - vy) <= rad]
        for i in near:
            for j in near:
                if i != j: adj.setdefault(i, []).append((j, 0.0, None))
    def attach(p):  # the pad: nodes within its reach on ITS copper layer (an in-pad via carries it down);
        # any layer only for a through-hole pad. On any layer, an inner meander passing
        # under a QFN pad counted as touching it and shortcut R_CLK_P by 8 mm.
        px, py = float(p['x']), float(p['y'])
        got = {i for i, (x, y, _, ln) in enumerate(coords)
               if math.hypot(x - px, y - py) <= 0.35 and (p.get('layer') in (None, '*') or ln == p['layer'])}
        for v in vias:  # a via in the pad joins it to every layer
            vx, vy = float(v['x']), float(v['y'])
            if math.hypot(vx - px, vy - py) <= 0.3:
                rad = float(v.get('size_mm') or 0.25) / 2 + tol
                got |= {i for i, (x, y, _, _) in enumerate(coords) if math.hypot(x - vx, y - vy) <= rad}
        return sorted(got)
    S, D = attach(src), set(attach(dst))
    if debug:
        print('  attach src', len(S), 'dst', len(D), 'nodes', len(coords))
    if not S or not D:
        return None
    dist, prev = {}, {}
    heap = [(0.0, i) for i in S]
    for i in S: dist[i] = 0.0
    while heap:
        d0, i = heapq.heappop(heap)
        if d0 > dist.get(i, 1e30): continue
        if i in D:
            path = []
            while i in prev:
                j, L, r = prev[i]
                if r == 'join':
                    if debug and L > 0.03: print('  join', coords[j][:2], '->', coords[i][:2], coords[i][3], round(L, 3))
                    if L > 0: path.append(('join', L))
                elif r is not None: path.append((r, L))
                i = j
            return list(reversed(path))
        for j, L, r in adj.get(i, []):
            nd = d0 + L
            if nd < dist.get(j, 1e30):
                dist[j] = nd; prev[j] = (i, L, r); heapq.heappush(heap, (nd, j))
    return None


def _ladder_of(path, widths=None):
    """(z_leg, delay_ps, len_mm) per run: the export's differential Z halved
    (odd mode per leg), stripline or microstrip velocity by layer. `widths`,
    when given, receives one (width_mm, inner) per run — the track width the
    conductor-loss model needs, length-weighted over merged runs."""
    lad = []
    last = None
    for r, L in path:
        if r == 'join':  # a contact hop: the copper around it
            if last is None: continue
            r = last
        last = r
        z = float(r['z_ohm']); z = z / 2.0 if z > 0 else (lad[-1][0] if lad else 50.0)
        inner = r['layer_name'] not in ('F.Cu', 'B.Cu')
        d = L * (SR.PS_MM_STRIP if inner else SR.PS_MM_MICRO)
        w = float(r.get('width_mm') or 0) or 0.1
        if lad and abs(lad[-1][0] - z) < 1.0:
            L0 = lad[-1][2]
            lad[-1] = (lad[-1][0], lad[-1][1] + d, L0 + L)
            if widths is not None:
                w0, in0 = widths[-1]
                widths[-1] = ((w0 * L0 + w * L) / (L0 + L), in0)
        else:
            lad.append((z, d, L))
            if widths is not None: widths.append((w, inner))
    return lad


def _ladders(b, det):
    parts = board_parts(det['board']) if det.get('board') else {}
    rep = os.path.join(b['dir'], 'si-report')
    segs = SR.read_csv(os.path.join(rep, 'segments.csv'))
    vias = SR.read_csv(os.path.join(rep, 'vias.csv'))
    pads = SR.read_csv(os.path.join(rep, 'pads.csv'))
    bynet = {}
    for s in segs:
        bynet.setdefault(s['net'], []).append(s)
    lad = {}
    for L in det['links']:
        for net in (L['p'], L['n']):
            np_ = [p for p in pads if p['net'] == net]
            src = next((p for p in np_ if p['ref'] == L['tx']), None)
            dst = next((p for p in np_ if p['ref'] != L['tx'] and (L['rx'] is None or p['ref'] == L['rx'])), None)
            if not src or not dst or net not in bynet: continue
            for p in (src, dst):  # the pad's copper layer: its footprint's side, every layer through-hole
                pr = parts.get(p['ref'], {})
                p = p  # (dicts are shared with the caller's list: copy)
            src, dst = dict(src), dict(dst)
            for p in (src, dst):
                pr = parts.get(p['ref'], {})
                pad = next((q for q in pr.get('nets', {}).get(net, [])), None)
                p['layer'] = '*' if pad in pr.get('thru', set()) or p.get('through') == '1' else pr.get('side')
            path = trace_path(bynet[net], [v for v in vias if v['net'] == net], src, dst)
            if path:
                widths = []  # per run, for the loss model
                lad[net] = (_ladder_of(path, widths), sum(Lm for _, Lm in path), widths)
    return lad


def _resample(t, v, dt, n):
    out, j = [], 0
    for i in range(n):
        x = i * dt
        while j + 1 < len(t) and t[j + 1] < x:
            j += 1
        if j + 1 >= len(t):
            out.append(v[-1]); continue
        f = (x - t[j]) / (t[j + 1] - t[j]) if t[j + 1] > t[j] else 0.0
        out.append(v[j] + f * (v[j + 1] - v[j]))
    return out


def _leg(ladder, rs, rt, tr2080, tstop):
    # a 0 -> 1 V open-circuit step, linear edge whose 20-80 % time is tr2080
    return SR.bounce(ladder, rs, rt, vsrc=1.0, vterm=0.0, trise=tr2080 / 0.6, tstop=tstop)[:2]


def _pulse_bounds(v, n_ui, vth):
    """Peak-distortion bounds at every sample: the lowest '1' and highest '0'."""
    vlo = v[0]
    p = [v[i] - (v[i - n_ui] if i >= n_ui else vlo) for i in range(len(v))]
    def bounds(i):
        hi1 = vlo + p[i]; lo0 = vlo
        for k in range(-10, 11):
            if k == 0 or not (0 <= i + k * n_ui < len(p)):
                continue
            tap = p[i + k * n_ui]
            if tap < 0: hi1 += tap
            else: lo0 += tap
        return hi1, lo0
    return p, bounds


def _flight_ps(ladder):
    return sum(d for _, d, _ in ladder)


def _analyse(v, dt, ui_ps, vth, shift_ui, tx_skew_ui, setup_ui, hold_ui):
    """Worst-case eye of the differential waveform v (step response, -D -> +D)
    against a fixed 0 V threshold +- vth. Returns the metrics and the drawing."""
    n_ui = max(4, int(round(ui_ps / dt)))
    p, bounds = _pulse_bounds(v, n_ui, vth)
    ic = max(range(len(p)), key=lambda i: p[i])
    def opening(i):  # how far the worst 1 and worst 0 stay beyond the thresholds
        if i < 0 or i >= len(p): return -1.0
        hi1, lo0 = bounds(i)
        return min(hi1, -lo0)
    best, c = -1e9, ic
    for i in range(max(0, ic - n_ui), min(len(p), ic + n_ui + 1), max(1, n_ui // 64)):
        o = opening(i)
        if o > best: best, c = o, i
    height = max(0.0, 2 * best)
    lo = c
    while lo > 0 and opening(lo - 1) >= vth: lo -= 1
    hi = c
    while hi < len(p) - 1 and opening(hi + 1) >= vth: hi += 1
    width_ui = (hi - lo + 1) / n_ui if best >= vth else 0.0
    centre = (lo + hi) / 2.0
    samp = centre + shift_ui * n_ui                  # where the forwarded clock samples
    need_lo = samp - (setup_ui + tx_skew_ui) * n_ui  # data valid from here ...
    need_hi = samp + (hold_ui + tx_skew_ui) * n_ui   # ... to here
    margin_ui = min(need_lo - lo, hi - need_hi) / n_ui if best >= vth else -1.0
    # drawing: PRBS-7 superposition, two UI around the eye centre
    bits = _prbs7(); traces = []
    ic_draw = int(round(centre)); vlo = v[0]
    for k in range(2, len(bits)):
        seg = []
        for j in range(0, 2 * n_ui, max(1, n_ui // 48)):
            i = ic_draw + j - n_ui; val = vlo
            for m in range(0, 14):
                if k - m < 0: break
                if bits[k - m]:
                    idx = i + m * n_ui
                    if 0 <= idx < len(p): val += p[idx]
                    elif idx >= len(p): val += p[-1]
            seg.append((j / n_ui, val))
        traces.append(seg)
    return {'height_v': height, 'width_ui': width_ui, 'margin_ui': margin_ui,
            'samp_ui': 1 + (samp - centre) / n_ui, 'traces': traces,
            'vlo': v[0], 'vhi': v[-1], 'vth': vth, 'setup_ui': setup_ui + tx_skew_ui,
            'hold_ui': hold_ui + tx_skew_ui, 'box_ui': setup_ui + hold_ui}


def _prbs7():
    reg, out = 0x7f, []
    for _ in range(127):
        bit = ((reg >> 6) ^ (reg >> 5)) & 1
        out.append(reg & 1); reg = ((reg << 1) | bit) & 0x7f
    return out


def _diff_wave(lp, ln, rs, rt_leg, tr, amp_leg, tstop):
    """P - N at the receiver for complementary legs, from -D to +D."""
    tp, vp = _leg(lp, rs, rt_leg, tr, tstop)
    tn, vn = _leg(ln, rs, rt_leg, tr, tstop)
    dt = min(tp[1] - tp[0], tn[1] - tn[0], 2.0)
    n = int(tstop / dt)
    vp, vn = _resample(tp, vp, dt, n), _resample(tn, vn, dt, n)
    s = [amp_leg * (a + b2) for a, b2 in zip(vp, vn)]
    d = s[-1] / 2.0
    return [x - d for x in s], dt


def link_eyes(b, det):
    """Per link: the worst-corner eye, its corner, the clock-to-data offset."""
    if not det['links']:
        return None
    lad = _ladders(b, det)
    # clock flight per receiver (the forwarded clock lane of each CSI-2 bus)
    clk = {}
    for L in det['links']:
        if L['kind'] == 'csi2' and L['clock'] and L['p'] in lad and L['n'] in lad:
            clk[L['rx']] = (_flight_ps(lad[L['p']][0]) + _flight_ps(lad[L['n']][0])) / 2
    out = []
    for L in det['links']:
        if L['p'] not in lad or L['n'] not in lad:
            out.append(dict(L, error='no traced path in the SI export')); continue
        lp, ln = lad[L['p']][0], lad[L['n']][0]
        ui_ps = 1e6 / L['mbps']
        fl = (_flight_ps(lp) + _flight_ps(ln)) / 2
        if L['kind'] == 'csi2':
            t, r = L['txp'], L['rxp']
            vod = t['vod_min']
            shift_ps = 0.0 if L['clock'] or L['rx'] not in clk else clk[L['rx']] - fl
            tx_skew = 0.0 if L['clock'] else DPHY_TSKEW_TX_UI
            tstop = 16 * ui_ps + 2 * fl
            worst = None
            for zos in t['zos']:
                for zid in r['zid']:
                    for tr in t['tr2080_ps']:
                        # the source is defined by VOD into the nominal 100 ohm:
                        # open-circuit leg step = VOD * (ZOS + 50) / 50
                        amp = vod * (zos + 50.0) / 50.0
                        v, dt = _diff_wave(lp, ln, zos, zid / 2.0, tr, amp, tstop)
                        e = _analyse(v, dt, ui_ps, r['vidth'], shift_ps / ui_ps, tx_skew, r['tsetup_ui'], r['thold_ui'])
                        e['corner'] = f"ZOS {zos:g} Ω, ZID {zid:g} Ω, tr {tr:g} ps, VOD {1000*vod:.0f} mV"
                        key = (e['margin_ui'] < 0 or e['height_v'] < 2 * r['vidth'], -e['margin_ui'])
                        if worst is None or key > worst[0]:
                            worst = (key, e)
            e = worst[1]
            ok = e['height_v'] >= 2 * r['vidth'] and e['margin_ui'] >= 0
            out.append(dict(L, eye=e, ok=ok, ui_ps=ui_ps, shift_ps=shift_ps, flight_ps=fl,
                            skew_ps=abs(_flight_ps(lp) - _flight_ps(ln))))
        else:  # V3Link forward channel, board section only
            t = L['txp']
            tstop = 30 * ui_ps + 2 * fl
            rs = t['rt_se']
            if L['mode'] == 'coax':
                amp = t['vout_se_min'] * (rs + 50.0) / 50.0    # per leg, open circuit
                tp, vp = _leg(lp, rs, 50.0, t['tr2080_ps'], tstop)
                dt = min(tp[1] - tp[0], 2.0); n = int(tstop / dt)
                v = [amp * x for x in _resample(tp, vp, dt, n)]
                d = v[-1] / 2.0; v = [x - d for x in v]
                ideal = t['vout_se_min']; ref_mv = t['eye_ref_coax_mv']
                what = 'DOUT+ at the connector side of its AC cap, single-ended into the 50 Ω coax'
            else:
                amp = t['vod_pp_min'] / 2 * (rs + 50.0) / 50.0
                v, dt = _diff_wave(lp, ln, rs, 50.0, t['tr2080_ps'], amp, tstop)
                ideal = t['vod_pp_min']; ref_mv = t['eye_ref_stp_mv']
                what = 'DOUT+ - DOUT- at the AC caps, into the 100 Ω STP'
            e = _analyse(v, dt, ui_ps, 0.0, 0.0, 0.0, 0.0, 0.0)
            e['width_ui'] = max(0.0, e['width_ui'] - t['jitter_ui'])
            e['corner'] = f"RT {rs:g} Ω, tr {t['tr2080_ps']:g} ps, minimum swing"
            out.append(dict(L, eye=e, ok=None, ui_ps=ui_ps, ideal_v=ideal, ref_mv=ref_mv, what=what,
                            flight_ps=fl, skew_ps=abs(_flight_ps(lp) - _flight_ps(ln))))
    return out


# ---------------------------------------------------------------- drawing --
def eye_svg(e, w=260, h=160):
    """The eye with its receiver window: +-VIDTH over setup+hold (inner box)
    and the transmitter skew allowance around it (outer box), at the
    clock-defined sampling instant."""
    span = max(abs(e['vlo']), abs(e['vhi'])) * 1.25 or 0.1
    def X(u): return 30 + u / 2 * (w - 38)
    def Y(v): return 8 + (span - v) / (2 * span) * (h - 22)
    s = [f'<svg viewBox="0 0 {w} {h}" class="eye">']
    for mv in (-span, 0, span):
        s.append(f'<text x="26" y="{Y(mv)+3:.1f}" text-anchor="end" font-size="8" fill="var(--ink-3)" font-family="IBM Plex Mono,monospace">{1000*mv:.0f}</text>')
    s.append(f'<line x1="30" x2="{w-8}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="var(--rule)" stroke-dasharray="3 3"/>')
    if e['vth'] > 0:
        c = e['samp_ui']
        s.append(f'<rect x="{X(c - e["setup_ui"]):.1f}" y="{Y(e["vth"]):.1f}" width="{X(c + e["hold_ui"]) - X(c - e["setup_ui"]):.1f}" height="{Y(-e["vth"]) - Y(e["vth"]):.1f}" fill="none" stroke="var(--cond)" stroke-width="0.8" stroke-dasharray="3 2"/>')
        s.append(f'<rect x="{X(c - e["box_ui"]/2):.1f}" y="{Y(e["vth"]):.1f}" width="{X(c + e["box_ui"]/2) - X(c - e["box_ui"]/2):.1f}" height="{Y(-e["vth"]) - Y(e["vth"]):.1f}" fill="var(--cond-bg)" stroke="var(--cond)" stroke-width="0.9"/>')
    for seg in e['traces']:
        d = ' '.join(f'{"M" if i == 0 else "L"}{X(u):.1f} {Y(v):.1f}' for i, (u, v) in enumerate(seg))
        s.append(f'<path d="{d}" fill="none" stroke="var(--copper)" stroke-opacity="0.35" stroke-width="0.9"/>')
    s.append(f'<text x="{w-8}" y="{h-3}" text-anchor="end" font-size="8" fill="var(--ink-3)" font-family="IBM Plex Mono,monospace">2 UI · mV differential</text></svg>')
    return ''.join(s)
