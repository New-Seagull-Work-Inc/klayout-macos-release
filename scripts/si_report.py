#!/usr/bin/env python3
"""si_report.py — the SI reflection report that ships beside the layout.

Reads the router's si-report/ CSV export (segments with as-laid impedance,
vias, pads), chains every SI net driver-to-receiver, runs an exact
lossless-transmission-line bounce simulation (method of characteristics —
each segment is a delay line at its own as-laid Z0; no SPICE needed for
ideal lines), and renders one PDF: a summary table plus, per net, the
impedance profile along the path and the simulated edge at the receiver,
judged against overshoot/ringback thresholds. Nets that belong to a serial
link (a camera's MIPI CSI-2 lanes, a serializer's forward channel — recognised
from the parts at the pair's ends by serial_links.py beside this script) are
not judged as DDR: they get eye pages instead, at the link's data rate and the
receiver's own window, worst corner of the transmitter and receiver limits.

Dependency-free by design (no numpy/matplotlib/ngspice): the solver is a
few hundred waves in Python lists and the PDF is written directly with
base-14 fonts and line operators, in the spirit of the C tool.

Usage:  python3 scripts/si_report.py <output-dir> [pdf-path]
        (expects <output-dir>/si-report/{segments,vias,pads}.csv)

Model + assumptions (printed on the PDF's first page):
  driver   Thevenin step, Rs = 40 ohm, 0 -> 1.1 V (VDDQ), 100 ps linear rise
  receiver ODT 60 ohm to VDDQ (POD termination; LPDDR4 range 40-80)
  velocity stripline 6.9 ps/mm, microstrip 5.9 ps/mm (the gates doc's values)
  pairs    simulated on the differential Z profile, half-amplitude per leg
  masks    overshoot <= 0.35 V above VDDQ; ringback after the first
           crossing must stay above VIH = 0.75 V (~Vref + 0.2 VDDQ)
"""
import sys, os, math, time, zlib

VDDQ, RS, RT = 1.1, 40.0, 60.0          # nominal driver / ODT (the fallback and the header)
# LPDDR4 legal bins: SoC PHY drive strength (ZQ-calibrated) and DRAM ODT per leg
# (MR11 DQ ODT for DQ/DMI/DQS, MR11 CA ODT for CA/CS/CKE/CK). A pair leg is
# terminated per leg, so a pair sees 2x ODT differentially.
PHY_DRIVE = (34.0, 40.0, 48.0, 60.0)
DRAM_ODT = (40.0, 48.0, 60.0, 80.0, 120.0, 240.0)
TRISE_PS, TSTOP_PS = 100.0, 15000.0
PS_MM_STRIP, PS_MM_MICRO = 6.9, 5.9
OVERSHOOT_MAX, VIH = 0.35, 0.75


def read_csv(path):
    rows = []
    with open(path) as f:
        head = f.readline().strip().split(',')
        for ln in f:
            ln = ln.strip()
            if ln:
                rows.append(dict(zip(head, ln.split(','))))
    return rows


def chain(net, segs, vias, pads):
    """Order a net's segments from the driver pad outward; returns a list of
    (z_ohm, delay_ps) plus the geometric length, or None when no chain."""
    if not segs:
        return None, 0.0
    # the driver: the pad on the part with the most pads (the controller BGA)
    npads = [p for p in pads if p['net'] == net]
    if not npads:
        return None, 0.0
    drv = max(npads, key=lambda p: int(p['part_pads']))
    pts = []  # (x1,y1,x2,y2,row)
    for s in segs:
        pts.append((float(s['x1']), float(s['y1']),
                    float(s['x2']), float(s['y2']), s))
    vset = [(float(v['x']), float(v['y'])) for v in vias if v['net'] == net]

    def near(ax, ay, bx, by, tol=0.06):
        if abs(ax - bx) <= tol and abs(ay - by) <= tol:
            return True
        # a via at either point joins the layers: co-located counts
        for vx, vy in vset:
            if abs(ax - vx) <= tol and abs(ay - vy) <= tol and \
               abs(bx - vx) <= tol and abs(by - vy) <= tol:
                return True
        return False

    # the net is a tree of segments; the signal path is the LONGEST simple
    # path from the driver pad (a greedy walk took spurs at serpentine
    # joins and repaired junctions and reported 5 mm of a 30 mm strobe)
    tol = 0.06  # endpoint snap, as near()
    def key(x, y):
        return (round(x / tol), round(y / tol))
    nodes = {}  # snapped point -> list of (seg index, far end index)
    for i, (x1, y1, x2, y2, _) in enumerate(pts):
        nodes.setdefault(key(x1, y1), []).append((i, 1))
        nodes.setdefault(key(x2, y2), []).append((i, 0))
    # vias join layers: every point co-located with a via shares a node
    alias = {}
    for vx, vy in vset:
        k0 = key(vx, vy)
        for k in list(nodes):
            if k != k0 and abs(k[0] - k0[0]) <= 1 and abs(k[1] - k0[1]) <= 1:
                alias[k] = k0
    def canon(k):
        return alias.get(k, k)
    adj = {}
    for k, lst in nodes.items():
        adj.setdefault(canon(k), []).extend(lst)
    # start: the endpoint nearest the driver pad
    cx, cy = float(drv['x']), float(drv['y'])
    start = min(adj, key=lambda k: math.hypot(k[0] * tol - cx, k[1] * tol - cy))
    # Dijkstra from the driver node; the receiver is the node farthest by
    # path length, the chain is the path to it (exact on a tree, and the
    # loops that repaired junctions add cannot blow it up)
    import heapq
    dist, prev = {start: 0.0}, {}
    heap = [(0.0, start)]
    while heap:
        d0, node = heapq.heappop(heap)
        if d0 > dist.get(node, 1e30):
            continue
        for i, far in adj.get(node, []):
            x1, y1, x2, y2, row = pts[i]
            nk = canon(key(x2, y2) if far == 1 else key(x1, y1))
            nd = d0 + math.hypot(x2 - x1, y2 - y1)
            if nd < dist.get(nk, 1e30):
                dist[nk] = nd; prev[nk] = (node, i); heapq.heappush(heap, (nd, nk))
    end = max(dist, key=lambda k: dist[k])
    chain_rows = []
    node = end
    while node in prev:
        node, i = prev[node]
        chain_rows.append(pts[i][4])
    chain_rows.reverse()
    best = (chain_rows, dist[end])
    order = best[0]
    if not order:
        return None, 0.0
    ladder, total = [], 0.0
    lastz = None
    # a pair leg (role 1 = P, 2 = N in the router's export): the export's Z is
    # differential. Testing role '2' alone left every P leg at the full
    # differential impedance (2x its odd-mode Z) in the bounce model.
    pairleg = any(r.get('role') in ('1', '2') for r in order)
    for row in order:
        L = float(row['len_mm'])
        z = float(row['z_ohm'])
        if pairleg and z > 0:
            z = z / 2.0  # odd-mode impedance per leg against a per-leg ODT
        inner = row['layer_name'] not in ('F.Cu', 'B.Cu')
        if z <= 0:
            z = lastz if lastz else 50.0  # model rejected: carry the neighbor
        lastz = z
        d = L * (PS_MM_STRIP if inner else PS_MM_MICRO)
        total += L
        # merge near-equal neighbors to keep the ladder small
        if ladder and abs(ladder[-1][0] - z) < 1.0:
            ladder[-1] = (ladder[-1][0], ladder[-1][1] + d, ladder[-1][2] + L)
        else:
            ladder.append((z, d, L))
    return ladder, total


def bounce(ladder, rs=RS, rt=RT, vsrc=None, vterm=None, trise=None, tstop=None):
    """Exact lossless-TL lattice sim of the ladder; returns (t_ps[], v_recv[],
    v_drv[]). Each line holds right/left waves in delay queues.
    Defaults are the LPDDR4 case: a 0 -> VDDQ step with a 100 ps linear edge,
    the load terminated to VDDQ (POD). vsrc: the source's open-circuit step;
    vterm: the voltage the load termination returns to (0 = ground, which is
    also the virtual ground of a differential termination in odd mode);
    trise: 0-100 % linear edge, ps; tstop: simulated time, ps."""
    from collections import deque
    vsrc = VDDQ if vsrc is None else vsrc
    vterm = VDDQ if vterm is None else vterm
    trise = TRISE_PS if trise is None else trise
    tstop = TSTOP_PS if tstop is None else tstop
    dt = max(1.0, min(d for _, d, _ in ladder) / 2.0)
    lines = []
    for z, d, _ in ladder:
        n = max(1, int(round(d / dt)))
        lines.append({'z': z, 'r': deque([0.0] * n), 'l': deque([0.0] * n)})
    steps = int(tstop / dt)
    t, vr, vd = [], [], []
    for k in range(steps):
        now = k * dt
        vs = vsrc * min(1.0, now / trise)
        z1 = lines[0]['z']
        # driver boundary: incident from the left line's returning wave
        refl_in = lines[0]['l'][0]
        gs = (rs - z1) / (rs + z1)
        a = vs * z1 / (rs + z1) + gs * refl_in  # wave launched right
        # load boundary
        zn = lines[-1]['z']
        inc = lines[-1]['r'][-1]
        gl = (rt - zn) / (rt + zn)
        # POD termination: LPDDR4 ODT pulls to VDDQ, not ground — the
        # Thevenin source at the load injects VDDQ*Zn/(RT+Zn); with a
        # ground termination the steady state was a 0.66 V divider,
        # below VIH forever, and every net failed the mask.
        bwave = gl * inc + vterm * zn / (rt + zn)  # wave launched left
        # the node voltage is BOTH waves: inc*(1+gl) drops the
        # termination source's share and read 0.5 V at DC (the sum
        # solves to VDDQ exactly)
        vrecv = inc + bwave
        vdrv = a + refl_in
        # junctions between lines i and i+1
        newr = [a] + [0.0] * (len(lines) - 1)
        newl = [0.0] * (len(lines) - 1) + [bwave]
        for i in range(len(lines) - 1):
            za, zb = lines[i]['z'], lines[i + 1]['z']
            vi = lines[i]['r'][-1]      # arriving from the left
            vj = lines[i + 1]['l'][0]   # arriving from the right
            g = (zb - za) / (zb + za)
            newl[i] = g * vi + (1.0 - g) * vj        # back into line i
            newr[i + 1] = (1.0 + g) * vi + (-g) * vj  # onward into i+1
        for i, ln in enumerate(lines):  # advance the delay queues (O(1) with deques)
            ln['r'].appendleft(newr[i]); ln['r'].pop()
            ln['l'].popleft(); ln['l'].append(newl[i])
        t.append(now)
        vr.append(vrecv)
        vd.append(vdrv)
    return t, vr, vd


def metrics(t, v):
    peak = max(v)
    over = max(0.0, peak - VDDQ)
    # ringback: after the first VIH crossing, the deepest dip below VIH
    ring, crossed = 0.0, False
    for x in v:
        if not crossed and x >= VIH:
            crossed = True
        elif crossed:
            ring = max(ring, VIH - x)
    settle = t[-1]
    for i in range(len(v) - 1, -1, -1):
        if abs(v[i] - VDDQ) > 0.05 * VDDQ:
            settle = t[i]
            break
    ok = over <= OVERSHOOT_MAX and ring <= 0.0 + 1e-9 and crossed
    return over, ring, settle, ok


# ---------------- minimal PDF writer ----------------
class PDF:
    W, H = 612, 792

    def __init__(self):
        self.pages = []
        self.buf = None

    def page(self):
        self.buf = []
        self.pages.append(self.buf)

    def cmd(self, s):
        self.buf.append(s)

    def text(self, x, y, s, size=9, bold=False):
        f = '/F2' if bold else '/F1'
        # base-14 Helvetica is Latin-1: spell the symbols the parts' notes use
        s = (s.replace('Ω', 'ohm').replace('—', '-').replace('–', '-').replace('±', '+-')
              .replace('·', '.').replace('→', '->').replace('≤', '<=').replace('≥', '>=')
              .encode('latin-1', 'replace').decode('latin-1'))
        s = s.replace('\\', r'\\').replace('(', r'\(').replace(')', r'\)')
        self.cmd(f'BT {f} {size} Tf {x:.1f} {y:.1f} Td ({s}) Tj ET')

    def line(self, x1, y1, x2, y2, w=0.7, rgb=(0, 0, 0)):
        self.cmd(f'{rgb[0]} {rgb[1]} {rgb[2]} RG {w} w '
                 f'{x1:.1f} {y1:.1f} m {x2:.1f} {y2:.1f} l S')

    def poly(self, pts, w=0.9, rgb=(0, 0, 0)):
        if len(pts) < 2:
            return
        p = f'{rgb[0]} {rgb[1]} {rgb[2]} RG {w} w ' \
            f'{pts[0][0]:.1f} {pts[0][1]:.1f} m'
        for x, y in pts[1:]:
            p += f' {x:.1f} {y:.1f} l'
        self.cmd(p + ' S')

    def save(self, path):
        objs = []

        def add(body):
            objs.append(body)
            return len(objs)

        font1 = add(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
        font2 = add(b'<< /Type /Font /Subtype /Type1 '
                    b'/BaseFont /Helvetica-Bold >>')
        page_ids, content_ids = [], []
        for pg in self.pages:
            stream = zlib.compress('\n'.join(pg).encode())
            content_ids.append(add(
                b'<< /Length ' + str(len(stream)).encode() +
                b' /Filter /FlateDecode >>\nstream\n' + stream +
                b'\nendstream'))
        pages_id = len(objs) + len(self.pages) + 1
        for cid in content_ids:
            page_ids.append(add(
                f'<< /Type /Page /Parent {pages_id} 0 R /MediaBox '
                f'[0 0 {self.W} {self.H}] /Contents {cid} 0 R /Resources '
                f'<< /Font << /F1 {font1} 0 R /F2 {font2} 0 R >> >> >>'
                .encode()))
        kids = ' '.join(f'{i} 0 R' for i in page_ids)
        assert add(f'<< /Type /Pages /Kids [{kids}] /Count '
                   f'{len(page_ids)} >>'.encode()) == pages_id
        cat = add(f'<< /Type /Catalog /Pages {pages_id} 0 R >>'.encode())
        out = [b'%PDF-1.4']
        offs = [0]
        pos = len(out[0]) + 1
        for i, body in enumerate(objs, 1):
            blob = f'{i} 0 obj\n'.encode() + body + b'\nendobj'
            offs.append(pos)
            out.append(blob)
            pos += len(blob) + 1
        xref = pos
        tbl = [f'xref\n0 {len(objs)+1}\n0000000000 65535 f '.encode()]
        for o in offs[1:]:
            tbl.append(f'{o:010d} 00000 n '.encode())
        out.append(b'\n'.join(tbl))
        out.append(f'trailer\n<< /Size {len(objs)+1} /Root {cat} 0 R >>\n'
                   f'startxref\n{xref}\n%%EOF'.encode())
        with open(path, 'wb') as f:
            f.write(b'\n'.join(out))


def plot(pdf, x0, y0, w, h, xs, ys, xlab, ylab, ymin, ymax, extra=None,
         hlines=()):
    pdf.line(x0, y0, x0 + w, y0)
    pdf.line(x0, y0, x0, y0 + h)
    pdf.text(x0 + w / 2 - 20, y0 - 14, xlab, 7)
    pdf.text(x0 - 6, y0 + h + 4, ylab, 7)
    if not xs:
        return
    xmax = max(list(xs) + [a for a, _ in (extra or [])]) or 1.0  # both traces fit

    def X(v):
        return x0 + w * v / xmax

    def Y(v):
        return y0 + h * (min(max(v, ymin), ymax) - ymin) / (ymax - ymin)

    for hv, label in hlines:
        pdf.line(x0, Y(hv), x0 + w, Y(hv), 0.4, (0.7, 0.2, 0.2))
        pdf.text(x0 + w + 3, Y(hv) - 2, label, 6)
    for gy in range(5):
        v = ymin + (ymax - ymin) * gy / 4
        pdf.line(x0, Y(v), x0 + 3, Y(v))
        pdf.text(x0 - 26, Y(v) - 2, f'{v:.2f}', 6)
    if extra:
        pdf.poly([(X(a), Y(b)) for a, b in extra], 0.6, (0.55, 0.55, 0.9))
    pdf.poly([(X(a), Y(b)) for a, b in zip(xs, ys)], 0.9, (0.1, 0.1, 0.1))
    pdf.text(x0 + w - 24, y0 - 14, f'{xmax:.1f}', 6)


def lane_z(lane_lad, L, z_pair):
    """The differential impedance of a lane along its path, from the two
    legs' ladders (odd-mode per leg x 2): per leg [(mm, Zdiff)] steps for
    the drawing, and min / length-median / max plus the share of the
    copper within +-10 % of the target. None without both legs."""
    if L['p'] not in lane_lad or L['n'] not in lane_lad:
        return None
    out = {'steps': {}}
    runs = []
    for leg in ('p', 'n'):
        xs, zs, run = [], [], 0.0
        for z, _, mm in lane_lad[L[leg]][0]:
            xs += [run, run + mm]; zs += [2 * z, 2 * z]; run += mm
            runs.append((2 * z, mm))
        out['steps'][leg] = (xs, zs)
    tot = sum(mm for _, mm in runs) or 1.0
    w = sorted(runs); acc = 0.0; med = w[-1][0]
    for z, mm in w:
        acc += mm
        if acc >= tot / 2: med = z; break
    out['min'] = min(z for z, _ in runs); out['max'] = max(z for z, _ in runs); out['med'] = med
    out['within'] = sum(mm for z, mm in runs if abs(z - z_pair) <= 0.1 * z_pair) / tot
    out['len'] = tot / 2.0
    # the reflection figures an SI review states: the peak reflection
    # coefficient of the lane against its reference impedance,
    # |Gamma| = |Z - Z0| / (Z + Z0), and the return loss it implies,
    # RL = -20 log10 |Gamma| (dB); a step of +-10 % is |Gamma| 0.05, RL 26 dB
    gmax = max(abs(z - z_pair) / (z + z_pair) for z, _ in runs) if runs else 0.0
    out['gamma'] = gmax
    out['rl_db'] = -20 * math.log10(gmax) if gmax > 1e-6 else 99.0
    out['vswr'] = (1 + gmax) / (1 - gmax) if gmax < 1 else 99.0
    return out


def axes_plot(pdf, x0, y0, w, h, title, xlab, ylab, xmin, xmax, ymin, ymax,
              curves, xticks, yticks, hlines=(), vlines=()):
    """A measurement-style panel: framed axes, labelled ticks on both
    axes, a title, curves as [(xs, ys, rgb, label)], reference lines
    (hlines: (y, label, rgb); vlines: (x, label, rgb)) — the layout of a
    VNA / TDR screen a reviewer reads without a legend hunt."""
    def X(v): return x0 + (v - xmin) / (xmax - xmin) * w
    def Y(v): return y0 + (min(max(v, ymin), ymax) - ymin) / (ymax - ymin) * h
    pdf.poly([(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h), (x0, y0)], 0.6)
    pdf.text(x0, y0 + h + 4, title, 7, True)
    for t in xticks:
        if xmin <= t <= xmax:
            pdf.line(X(t), y0, X(t), y0 - 3); pdf.line(X(t), y0, X(t), y0 + h, 0.2, (0.85, 0.85, 0.85))
            pdf.text(X(t) - 6, y0 - 11, f'{t:g}', 5.5)
    for t in yticks:
        if ymin <= t <= ymax:
            pdf.line(x0 - 3, Y(t), x0, Y(t)); pdf.line(x0, Y(t), x0 + w, Y(t), 0.2, (0.85, 0.85, 0.85))
            pdf.text(x0 - 22, Y(t) - 2, f'{t:g}', 5.5)
    pdf.text(x0 + w / 2 - 12, y0 - 20, xlab, 6)
    pdf.text(x0 - 26, y0 + h + 4, ylab, 6)
    for yv, lab, rgb in hlines:
        pdf.line(x0, Y(yv), x0 + w, Y(yv), 0.5, rgb)
        if lab: pdf.text(x0 + 2, Y(yv) + 2, lab, 5.5)
    for xv, lab, rgb in vlines:
        if xmin <= xv <= xmax:
            pdf.line(X(xv), y0, X(xv), y0 + h, 0.5, rgb)
            if lab: pdf.text(X(xv) + 2, y0 + h - 8, lab, 5.5)
    ly = y0 + h - 8
    for xs, ys, rgb, lab in curves:
        pdf.poly([(X(a), Y(b)) for a, b in zip(xs, ys)], 0.8, rgb)
        if lab:
            pdf.line(x0 + w - 40, ly + 2, x0 + w - 30, ly + 2, 0.8, rgb); pdf.text(x0 + w - 28, ly, lab, 5.5); ly -= 8


def ticks(lo, hi, n=5):
    """Round tick positions covering [lo, hi] in about n steps."""
    span = hi - lo or 1.0
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10)), key=lambda v: abs(v - raw))
    t0 = math.ceil(lo / step) * step
    out = []
    while t0 <= hi + 1e-9:
        out.append(round(t0, 6)); t0 += step
    return out


# Loss model for the S-parameters (first order, the textbook forms —
# Johnson & Graham, High-Speed Digital Design; IPC-2141 for the
# dielectric): stated on the report's first page.
TAN_D = 0.02          # FR-4 class loss tangent at ~1 GHz (the stackup's, when the fab publishes it, belongs here)
SIGMA_CU = 5.8e7      # copper conductivity, S/m
ROUGH = 1.5           # conductor-loss multiplier for standard (non-VLP) foil roughness
C_MM_PS = 0.299792458  # c, mm/ps


def seg_loss_db_per_mm(f_ghz, z_leg, width_mm, inner, ps_per_mm):
    """Dielectric + conductor attenuation of one run at f, dB/mm.
    Dielectric: alpha_d = 8.686 * pi * f * sqrt(er_eff) * tan_d / c, with
    er_eff from the run's own propagation velocity. Conductor (skin
    effect, wide-strip form): alpha_c = 8.686 * Rs / (Z * w) * ROUGH,
    Rs = sqrt(pi f mu0 / sigma); a stripline carries current on both
    faces, so half of that."""
    if f_ghz <= 0: return 0.0
    f = f_ghz * 1e9
    er_eff = (ps_per_mm * C_MM_PS) ** 2
    alpha_d = 8.686 * math.pi * f * math.sqrt(er_eff) * TAN_D / 2.99792458e11  # dB/mm
    rs = math.sqrt(math.pi * f * 4e-7 * math.pi / SIGMA_CU)
    alpha_c = 8.686 * rs / (z_leg * max(width_mm, 0.02) * 1e-3) * ROUGH / 1000.0  # dB/mm
    if inner: alpha_c *= 0.5
    return alpha_d + alpha_c


def lane_sparams(lane_lad, L, z_pair, fmax_ghz, n=120):
    """SDD11 / SDD21 of the lane against Z0 = its differential target, from
    the as-laid ladder: each run a lossy line (Z = 2 x odd-mode leg Z,
    delay from the router's velocity, attenuation from seg_loss_db_per_mm)
    as an ABCD matrix, cascaded; the legs are averaged. Returns
    {'f': GHz[], 's11': dB[], 's21': dB[], 'il_dc': dB[]} or None, il_dc
    being the plain attenuation sum (no reflections) for the caption."""
    if L['p'] not in lane_lad or L['n'] not in lane_lad:
        return None
    import cmath
    legs = [lane_lad[L[k]] for k in ('p', 'n')]
    fs = [fmax_ghz * (i + 1) / n for i in range(n)]
    s11, s21, il = [], [], []
    for f in fs:
        acc11 = acc21 = att = 0.0
        for entry in legs:
            lad = entry[0]; widths = entry[2] if len(entry) > 2 else [(0.1, False)] * len(lad)
            A, B, C, D = 1 + 0j, 0j, 0j, 1 + 0j
            for (z, d_ps, mm), (wmm, inner) in zip(lad, widths):
                Z = 2 * z; th = 2 * math.pi * f * d_ps / 1000.0  # GHz x ps
                a_db = seg_loss_db_per_mm(f, z, wmm, inner, d_ps / mm if mm > 0 else PS_MM_MICRO) * mm
                att += a_db / 2
                g = a_db / 8.686 + 1j * th  # gamma * length
                a, b, c, d = cmath.cosh(g), Z * cmath.sinh(g), cmath.sinh(g) / Z, cmath.cosh(g)
                A, B, C, D = A * a + B * c, A * b + B * d, C * a + D * c, C * b + D * d
            den = A + B / z_pair + C * z_pair + D
            acc11 += abs((A + B / z_pair - C * z_pair - D) / den) / 2
            acc21 += abs(2 / den) / 2
        s11.append(20 * math.log10(max(acc11, 1e-6))); s21.append(20 * math.log10(max(acc21, 1e-6)))
        il.append(-att)
    return {'f': fs, 's11': s11, 's21': s21, 'il_dc': il}


def eye_plot(pdf, x0, y0, w, h, e):
    """The eye over two UI: PRBS traces (grey), the zero line, and for a
    thresholded receiver the +-VIDTH window at the sampling instant — the
    inner box is setup+hold, the outer one adds the transmitter's skew
    allowance (serial_links._analyse)."""
    span = max(abs(e['vlo']), abs(e['vhi'])) * 1.25 or 0.1
    def X(u): return x0 + u / 2.0 * w
    def Y(v): return y0 + (v + span) / (2 * span) * h
    pdf.line(x0, y0, x0 + w, y0); pdf.line(x0, y0, x0, y0 + h)
    for u in (0, 0.5, 1, 1.5, 2):
        pdf.line(X(u), y0, X(u), y0 - 3); pdf.text(X(u) - 4, y0 - 12, f'{u:g}', 6)
    pdf.text(x0 + w / 2 - 30, y0 - 24, 'UI (2 shown)', 7)
    for mv in (-span, -span / 2, 0, span / 2, span):
        pdf.line(x0 - 3, Y(mv), x0, Y(mv)); pdf.text(x0 - 30, Y(mv) - 2, f'{1000*mv:.0f}', 6)
    pdf.text(x0 - 6, y0 + h + 6, 'mV differential at the receiver', 7)
    pdf.line(x0, Y(0), x0 + w, Y(0), 0.3, (0.6, 0.6, 0.6))
    for seg in e['traces']:
        pdf.poly([(X(u), Y(v)) for u, v in seg], 0.5, (0.45, 0.45, 0.45))
    if e['vth'] > 0:
        c = e['samp_ui']
        for (a, b2, wd, rgb) in ((c - e['setup_ui'], c + e['hold_ui'], 0.6, (0.8, 0.4, 0.4)),
                                  (c - e['box_ui'] / 2, c + e['box_ui'] / 2, 1.0, (0.75, 0.1, 0.1))):
            pts = [(X(a), Y(e['vth'])), (X(b2), Y(e['vth'])), (X(b2), Y(-e['vth'])),
                   (X(a), Y(-e['vth'])), (X(a), Y(e['vth']))]
            pdf.poly(pts, wd, rgb)
        pdf.text(X(c) - 40, Y(e['vth']) + 4, f"receiver window +-{1000*e['vth']:.0f} mV", 6)


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else '.'
    rep = os.path.join(outdir, 'si-report')
    pdfp = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        rep, 'si-report.pdf')
    # The router writes si-report/ only for boards with SI groups (pairs,
    # DDR buses); a board without them has nothing to report — say so
    # instead of tracing back on the missing CSV.
    if not os.path.exists(os.path.join(rep, 'segments.csv')):
        raise SystemExit(f'{outdir}: no si-report/ — the board has no SI groups (pairs or DDR buses) to report on')
    segs = read_csv(os.path.join(rep, 'segments.csv'))
    vias = read_csv(os.path.join(rep, 'vias.csv'))
    pads = read_csv(os.path.join(rep, 'pads.csv'))
    bynet = {}
    for s in segs:
        bynet.setdefault(s['net'], []).append(s)
    ladders = {}
    for net in sorted(bynet):
        ladder, length = chain(net, bynet[net], vias, pads)
        if ladder:
            ladders[net] = (ladder, length)
    # Serial links: the pairs whose ends are a known transmitter and
    # receiver (serial_links.PROFILES) are judged by their own standard
    # (eye at the receiver) and kept out of the DDR ODT judge below. Needs
    # the router's verdict JSON for the pair list; without it (or without
    # the module) the report is the DDR one for every net.
    links, lane_nets, link_note, lane_lad, z_pair = None, set(), '', {}, 100.0
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import json
        import serial_links as SL
        resj = next((os.path.join(outdir, f) for f in sorted(os.listdir(outdir))
                     if f.endswith('-klayout-result.json')), None)
        if resj:
            b = {'dir': outdir, 'res': json.load(open(resj)), 'has_report': True}
            det = SL.detect(b)
            lane_nets = set(det['nets'])
            links = SL.link_eyes(b, det) if det['links'] else None
            lane_lad = SL._ladders(b, det) if det['links'] else {}  # per leg: (z_leg, ps, mm) runs
            z_pair = float(((b['res'].get('si') or {}).get('z_target_pair')) or 100.0)
        else:
            link_note = 'no verdict JSON: serial links not recognised'
    except Exception as ex:
        link_note = f'serial links not judged ({ex})'
    # ODT judge: one legal (PHY drive, DRAM ODT) setting per group; a group
    # passes with the setting that clears the most nets, then the least
    # overshoot, then the strongest termination. Candidates: the ODT bins
    # bracketing the group's median line impedance plus the nominal.
    def group_of(net):
        n = net.upper()
        return 'CA' if any(k in n for k in ('_CA', '_CS', '_CKE', '_CK_', '_CK')) else 'DQ'
    def median_z(ladder):
        w = sorted((z, L) for z, _, L in ladder)
        half, acc = sum(L for _, L in w) / 2, 0
        for z, L in w:
            acc += L
            if acc >= half:
                return z
        return w[-1][0]
    settings, results = {}, []
    for grp in ('DQ', 'CA'):
        nets = [n for n in ladders if group_of(n) == grp and n not in lane_nets]
        if not nets:
            continue
        zmed = sorted(median_z(ladders[n][0]) for n in nets)[len(nets) // 2]
        below = [o for o in DRAM_ODT if o <= zmed]; above = [o for o in DRAM_ODT if o >= zmed]
        odts = sorted({(below[-1] if below else DRAM_ODT[0]), (above[0] if above else DRAM_ODT[-1]), RT})
        cands = [(rs, rt) for rt in odts for rs in (40.0, 48.0)] + [(RS, RT)]
        best = None
        for rs, rt in cands:
            runs = {}
            for n in nets:
                t, vr, _ = bounce(ladders[n][0], rs, rt)
                runs[n] = (t, vr) + metrics(t, vr)
            npass = sum(1 for r in runs.values() if r[5]); worst = max(r[2] for r in runs.values())
            key = (npass, -worst, -rt)
            if best is None or key > best[0]:
                best = (key, rs, rt, runs)
        _, rs, rt, runs = best
        settings[grp] = (rs, rt, sum(1 for r in runs.values() if r[5]), len(nets), zmed)
        for n in nets:
            t, vr, over, ring, settle, ok = runs[n]
            results.append((n, ladders[n][0], ladders[n][1], t, vr, over, ring, settle, ok))
    results.sort(key=lambda r: r[0])
    pdf = PDF()
    pdf.page()
    pdf.text(50, 750, 'SI reflection report', 16, True)
    pdf.text(50, 734, time.strftime('%Y-%m-%d %H:%M') + '   ' +
             os.path.abspath(outdir), 8)
    yy = 716
    if settings:
        pdf.text(50, yy, f'DDR nets: step 0-{VDDQ} V, {TRISE_PS:.0f} ps rise; ODT to VDDQ (POD); '
                 f'lossless TL bounce model; pair legs at odd-mode Z; settings chosen '
                 f'from the LPDDR4 legal bins per group:', 8)
    else:
        pdf.text(50, yy, 'no DDR nets: every SI net on this board belongs to a serial link '
                 '(eyes below)' + (f' — {link_note}' if link_note else ''), 8)
    for grp, (rs, rt, np_, nn, zmed) in settings.items():
        yy -= 12
        pdf.text(60, yy, f'{grp}: PHY drive {rs:.0f} ohm, DRAM ODT {rt:.0f} ohm per leg '
                 f'(MR11 {"DQ" if grp == "DQ" else "CA"} ODT'
                 f'{"; pairs 2x = %.0f ohm diff" % (2 * rt) if grp == "DQ" or grp == "CA" else ""}) '
                 f'-- {np_}/{nn} nets pass, group median line Z {zmed:.0f} ohm', 8)
    setting_line = '  '.join(f'{g}: drive {rs:.0f}/ODT {rt:.0f} ({np_}/{nn})' for g, (rs, rt, np_, nn, _) in settings.items())
    if settings:
        pdf.text(50, yy - 12, f'masks: overshoot <= {OVERSHOOT_MAX} V, ringback '
                 f'must hold above VIH {VIH} V after the first crossing', 8)
        yy -= 12
    # Model, standards and parameters — every number the verdicts rest on,
    # with its source, so a reviewer can check the report against the
    # standard and the datasheets rather than trust it.
    yy -= 22
    pdf.text(50, yy, 'Model, standards and parameters', 9, True)
    lines = [
        'Channel: each segment a lossless transmission line at the router\'s as-laid impedance (its stackup model on the finished copper);',
        f'  method of characteristics, exact for ideal lines; propagation {PS_MM_MICRO} ps/mm microstrip, {PS_MM_STRIP} ps/mm stripline;',
        '  no dielectric or copper loss, no crosstalk, no package or connector models: the report is the routing\'s contribution alone.',
        'Impedance: the industry tolerance for controlled impedance is +-10 % of the target (IPC-2221/IPC-6012 impedance-control class);',
        '  reflection coefficient |Gamma| = |Z - Z0| / (Z + Z0) against the lane\'s reference Z0, return loss RL = -20 log10 |Gamma| dB',
        '  (a +-10 % step is |Gamma| 0.05, RL 26 dB; the peak over the lane is reported).',
        'S-parameters: SDD11 (return loss) and SDD21 (insertion loss) vs frequency from the same ladder as an ABCD cascade of lossy lines',
        '  (both legs averaged) against the lane\'s Z0, to the 5th harmonic of the link\'s fundamental; the table gives the worst SDD11 up to',
        '  Nyquist and SDD21 at Nyquist. Loss, first order (Johnson & Graham; IPC-2141): dielectric alpha_d = 8.686 pi f sqrt(er_eff) tan_d / c',
        f'  with tan_d {TAN_D} (FR-4 class) and er_eff from each run\'s velocity; conductor alpha_c = 8.686 Rs / (Z w) x {ROUGH} (foil roughness),',
        f'  Rs = sqrt(pi f mu0 / sigma), sigma {SIGMA_CU:.1e} S/m, w = the run\'s track width, halved on striplines (current on both faces).',
    ]
    if settings:
        lines += [
            f'DDR (JEDEC JESD209-4, LPDDR4): VDDQ {VDDQ} V, pseudo-open-drain driver, {TRISE_PS:.0f} ps edge; PHY drive strength',
            f'  {"/".join(f"{x:.0f}" for x in PHY_DRIVE)} ohm (ZQ-calibrated) and DRAM ODT {"/".join(f"{x:.0f}" for x in DRAM_ODT)} ohm per leg (MR11 DQ/CA ODT);',
            f'  masks: overshoot <= {OVERSHOOT_MAX} V above VDDQ (JESD209-4 overshoot amplitude limit), ringback above VIH {VIH} V = Vref + 0.2 VDDQ.',
        ]
    if links:
        seen = set()
        for L in links:
            if 'error' in L: continue
            if L['kind'] == 'csi2':
                t, r = L['txp'], L['rxp']
                key = (L['tx'], L['rx'])
                if key in seen: continue
                seen.add(key)
                lines += [
                    f"MIPI CSI-2 D-PHY v{t.get('dphy', '1.2')} (MIPI Alliance): HS transmitter clock-to-data skew +-{SL.DPHY_TSKEW_TX_UI:g} UI; the lane is judged at",
                    f"  {L['mbps']:.0f} Mbps (the slower of the two parts), receiver window +-{1000*r['vidth']:.0f} mV over tSETUP {r['tsetup_ui']:g} + tHOLD {r['thold_ui']:g} UI.",
                    f"  TX {L['tx']}: VOD {1000*t['vod_min']:.0f}-{1000*t.get('vod_max', t['vod_min']):.0f} mV, ZOS {'/'.join(f'{z:g}' for z in t['zos'])} ohm, tr/tf 20-80 % {'/'.join(f'{x:g}' for x in t['tr2080_ps'])} ps",
                    f"    - {L.get('tx_src', '')}",
                    f"  RX {L['rx']}: ZID {'/'.join(f'{z:g}' for z in r['zid'])} ohm (100 typ), VIDTH/VIDTL +-{1000*r['vidth']:.0f} mV, up to {r['max_mbps']:.0f} Mbps",
                    f"    - {L.get('rx_src', '')}",
                    '  Worst corner = every combination of ZOS, ZID and edge rate at minimum VOD; the eye must clear the window at the',
                    '  clock-defined sampling instant with the transmitter skew allowance on both sides.',
                ]
            else:
                t = L['txp']
                if L['tx'] in seen: continue
                seen.add(L['tx'])
                lines += [
                    f"TI V3Link forward channel ({L['mode']}): {t['mbps']/1000:.2f} Gbps, output {1000*(t['vout_se_min'] if L['mode']=='coax' else t['vod_pp_min']):.0f} mV p-p min, "
                    f"termination {t['rt_se']:g} ohm, tr/tf 20-80 % {t['tr2080_ps']:g} ps, jitter {t['jitter_ui']:g} UI - {L.get('tx_src', '')}",
                ]
    for ln in lines:
        yy -= 10
        pdf.text(50, yy, ln[:150], 6.5)
    y = yy - 28
    if results:
        pdf.text(50, y, 'net', 8, True)
        pdf.text(230, y, 'len mm', 8, True)
        pdf.text(280, y, 'Z min-max', 8, True)
        pdf.text(360, y, 'overshoot V', 8, True)
        pdf.text(430, y, 'ringback V', 8, True)
        pdf.text(495, y, 'verdict', 8, True)
        y -= 4
        pdf.line(50, y, 560, y, 0.4)
    for net, ladder, length, *_r in results:
        over, ring, settle, ok = _r[2], _r[3], _r[4], _r[5]
        y -= 12
        if y < 60:
            pdf.page()
            y = 740
        zs = [z for z, _, _ in ladder]
        pdf.text(50, y, net[:34], 8)
        pdf.text(230, y, f'{length:.1f}', 8)
        pdf.text(280, y, f'{min(zs):.0f}-{max(zs):.0f}', 8)
        pdf.text(360, y, f'{over:.3f}', 8)
        pdf.text(430, y, f'{ring:.3f}', 8)
        pdf.text(495, y, 'PASS' if ok else 'FAIL', 8, True)
    nlink_ok = nlink = 0
    if links:
        # summary table: one row per lane, the link's own verdict
        if y < 140:
            pdf.page(); y = 740
        y -= 24
        pdf.text(50, y, "Serial links — eye at the receiver, worst corner of the parts' limits", 9, True)
        y -= 14
        pdf.text(50, y, link_note if link_note else
                 'differential P-N from the as-laid impedance of both legs (skew and leg mismatch '
                 'included); lossless, reflections only; PRBS-7 drawn, worst-case pattern judged', 8)
        y -= 12
        pdf.text(50, y, f'Zdiff: the router\'s stackup model on the laid copper, differential, target {z_pair:.0f} ohm; '
                 f'"in 10%" = share of the lane\'s length within +-10 % of it;', 8)
        y -= 11
        pdf.text(50, y, 'RL/VSWR at the lane\'s worst step; SDD11 = worst return loss up to Nyquist, SDD21 = insertion loss at Nyquist (both dB)', 8)
        y -= 16
        for x, h_ in ((50, 'pair'), (185, 'link'), (270, 'Zdiff min/med/max'), (342, 'in 10%'),
                      (370, 'RL dB/VSWR'), (415, 'SDD11 / SDD21'), (468, 'eye mV'), (497, 'width'), (525, 'margin'), (558, 'verdict')):
            pdf.text(x, y, h_, 6.5, True)
        y -= 4
        pdf.line(50, y, 590, y, 0.4)
        for L in links:
            y -= 12
            if y < 60:
                pdf.page(); y = 740
            pdf.text(50, y, L['pair'][:36], 6)
            pdf.text(185, y, L['label'][:22], 6)
            if 'error' in L:
                pdf.text(275, y, L['error'][:40], 7); continue
            zz = lane_z(lane_lad, L, z_pair)
            if zz:
                pdf.text(270, y, f"{zz['min']:.0f} / {zz['med']:.0f} / {zz['max']:.0f}", 6.5)
                pdf.text(342, y, f"{100*zz['within']:.0f}%", 6.5)
                pdf.text(370, y, f"{zz['rl_db']:.0f} / {zz['vswr']:.2f}", 6.5)
                fnyq = L['mbps'] / 2000.0  # GHz
                sp = lane_sparams(lane_lad, L, z_pair, 5 * fnyq)
                if sp:
                    inb = [v for f_, v in zip(sp['f'], sp['s11']) if f_ <= fnyq + 1e-9]
                    il = sp['s21'][min(range(len(sp['f'])), key=lambda i: abs(sp['f'][i] - fnyq))]
                    pdf.text(415, y, f"{max(inb):.0f} / {il:.2f} dB", 6.5)
            e = L['eye']; nlink += 1
            pdf.text(470, y, f"{1000*e['height_v']:.0f}", 6.5)
            pdf.text(498, y, f"{e['width_ui']:.2f}", 6.5)
            pdf.text(525, y, f"{e['margin_ui']:+.2f}" if e['vth'] > 0 else '-', 6.5)
            v = 'PASS' if L['ok'] else ('FAIL' if L['ok'] is not None else 'info')
            nlink_ok += 1 if L['ok'] else 0
            pdf.text(558, y, v, 6.5, True)
        # eye pages, two lanes per page
        slot = 2
        for L in links:
            if 'error' in L:
                continue
            if slot == 2:
                pdf.page(); slot = 0
            top = 750 - slot * 370
            slot += 1
            e = L['eye']
            pdf.text(50, top, L['pair'], 11, True)
            pdf.text(50, top - 14, f"{L['label']}: {L['tx']} -> {L['rx'] or 'connector'}; "
                     f"UI {L['ui_ps']:.0f} ps; flight {L['flight_ps']:.0f} ps, P-N skew {L['skew_ps']:.0f} ps"
                     + (f"; clock-to-data {L['shift_ps']:+.0f} ps" if L.get('shift_ps') else ''), 8)
            verdict = 'PASS' if L['ok'] else ('FAIL' if L['ok'] is not None else 'informative')
            pdf.text(50, top - 26, f"worst corner: {e['corner']}", 8)
            pdf.text(50, top - 38, f"eye height {1000*e['height_v']:.0f} mV, width {e['width_ui']:.2f} UI" +
                     (f", margin {e['margin_ui']:+.2f} UI at the receiver's window "
                      f"(+-{1000*e['vth']:.0f} mV over {e['box_ui']:.2f} UI)" if e['vth'] > 0 else
                      f" (reference {L.get('ref_mv', 0):.0f} mV at the serializer output)") +
                     f" - {verdict}", 8, True)
            zz = lane_z(lane_lad, L, z_pair)
            if zz:
                pdf.text(50, top - 50, f"Zdiff along the lane: {zz['min']:.0f}-{zz['max']:.0f} ohm, median {zz['med']:.0f}, "
                         f"{100*zz['within']:.0f}% of {zz['len']:.1f} mm within +-10% of {z_pair:.0f} ohm; "
                         f"peak |Gamma| {zz['gamma']:.2f}, RL {zz['rl_db']:.0f} dB, VSWR {zz['vswr']:.2f}; "
                         f"S-parameters to the 5th harmonic", 8)
                xp, zp = zz['steps']['p']; xn, zn = zz['steps']['n']
                xmax = max(xp[-1], xn[-1])
                red, blue, grey = (0.75, 0.1, 0.1), (0.2, 0.3, 0.8), (0.55, 0.55, 0.55)
                py = top - 150  # panel row: TDR view, |SDD11|, |SDD21|
                axes_plot(pdf, 95, py, 125, 70, 'Zdiff along the lane (TDR view)', 'mm', 'ohm',
                          0, xmax, z_pair * 0.5, z_pair * 1.5,
                          [(xp, zp, (0.1, 0.1, 0.1), 'P'), (xn, zn, blue, 'N')],
                          ticks(0, xmax, 4), ticks(z_pair * 0.5, z_pair * 1.5, 4),
                          hlines=((z_pair * 1.1, '+10%', grey), (z_pair * 0.9, '-10%', grey)))
                fnyq = L['mbps'] / 2000.0; fbit = 2 * fnyq; fmax = 5 * fnyq
                sp = lane_sparams(lane_lad, L, z_pair, fmax)
                if sp:
                    vl = ((fnyq, 'Nyquist', grey), (fbit, f'{fbit:g} GHz', grey))
                    axes_plot(pdf, 255, py, 125, 70, '|SDD11| return loss', 'GHz', 'dB',
                              0, fmax, -50, 0, [(sp['f'], sp['s11'], (0.1, 0.1, 0.1), '')],
                              ticks(0, fmax, 4), (-50, -40, -30, -20, -10, 0),
                              hlines=((-10, 'RL 10 dB reference', red),), vlines=vl)
                    il_floor = -max(0.5, math.ceil(-min(sp['s21']) * 4) / 4)
                    axes_plot(pdf, 415, py, 125, 70, '|SDD21| insertion loss', 'GHz', 'dB',
                              0, fmax, il_floor, 0, [(sp['f'], sp['s21'], (0.1, 0.1, 0.1), 'SDD21'),
                                                     (sp['f'], sp['il_dc'], blue, 'attenuation')],
                              ticks(0, fmax, 4), ticks(il_floor, 0, 4), vlines=vl)
                eye_plot(pdf, 90, top - 328, 430, 140, e)
            else:
                eye_plot(pdf, 90, top - 330, 430, 255, e)
    for net, ladder, length, t, vr, over, ring, settle, ok in results:
        pdf.page()
        pdf.text(50, 750, net, 13, True)
        pdf.text(50, 736, f'{length:.1f} mm, {len(ladder)} impedance '
                 f'section(s); overshoot {over:.3f} V, ringback {ring:.3f} V,'
                 f' settle {settle/1000:.1f} ns — '
                 + ('PASS' if ok else 'FAIL'), 8)
        xs, zs, run = [], [], 0.0
        for z, _, L in ladder:
            xs += [run, run + L]
            zs += [z, z]
            run += L
        plot(pdf, 70, 470, 460, 200, xs, zs, 'mm along path',
             'Z ohm', 30, 140,
             hlines=((80, 'target'),))
        plot(pdf, 70, 120, 460, 260,
             [x / 1000 for x in t], vr, 'ns', 'V at receiver',
             -0.2, 1.6,
             hlines=((VDDQ, 'VDDQ'), (VIH, 'VIH'),
                     (VDDQ + OVERSHOOT_MAX, 'overshoot max')))
    pdf.save(pdfp)
    npass = sum(1 for r in results if r[8])
    print(f'si-report: {len(results)} DDR net(s), {npass} PASS, ' + (f'[{setting_line}] ' if settings else '') +
          f'{len(results)-npass} FAIL; {nlink} serial lane(s), {nlink_ok} PASS -> {pdfp}')


if __name__ == '__main__':
    main()
