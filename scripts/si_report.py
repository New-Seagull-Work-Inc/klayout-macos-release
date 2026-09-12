#!/usr/bin/env python3
"""si_report.py — the SI reflection report that ships beside the layout.

Reads the router's si-report/ CSV export (segments with as-laid impedance,
vias, pads), chains every SI net driver-to-receiver, runs an exact
lossless-transmission-line bounce simulation (method of characteristics —
each segment is a delay line at its own as-laid Z0; no SPICE needed for
ideal lines), and renders one PDF: a summary table plus, per net, the
impedance profile along the path and the simulated edge at the receiver,
judged against overshoot/ringback thresholds.

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
    pairleg = any(r.get('role') == '2' for r in order)  # a pair leg: the export's Z is differential
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


def bounce(ladder, rs=RS, rt=RT):
    """Exact lossless-TL lattice sim of the ladder; returns (t_ps[], v_recv[],
    v_drv[]). Each line holds right/left waves in delay queues."""
    from collections import deque
    dt = max(1.0, min(d for _, d, _ in ladder) / 2.0)
    lines = []
    for z, d, _ in ladder:
        n = max(1, int(round(d / dt)))
        lines.append({'z': z, 'r': deque([0.0] * n), 'l': deque([0.0] * n)})
    steps = int(TSTOP_PS / dt)
    t, vr, vd = [], [], []
    for k in range(steps):
        now = k * dt
        vs = VDDQ * min(1.0, now / TRISE_PS)
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
        bwave = gl * inc + VDDQ * zn / (rt + zn)  # wave launched left
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
    xmax = max(xs) or 1.0

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
        nets = [n for n in ladders if group_of(n) == grp]
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
    pdf.text(50, 716, f'step 0-{VDDQ} V, {TRISE_PS:.0f} ps rise; ODT to VDDQ (POD); '
             f'lossless TL bounce model; pair legs at odd-mode Z; settings chosen '
             f'from the LPDDR4 legal bins per group:', 8)
    yy = 716
    for grp, (rs, rt, np_, nn, zmed) in settings.items():
        yy -= 12
        pdf.text(60, yy, f'{grp}: PHY drive {rs:.0f} ohm, DRAM ODT {rt:.0f} ohm per leg '
                 f'(MR11 {"DQ" if grp == "DQ" else "CA"} ODT'
                 f'{"; pairs 2x = %.0f ohm diff" % (2 * rt) if grp == "DQ" or grp == "CA" else ""}) '
                 f'-- {np_}/{nn} nets pass, group median line Z {zmed:.0f} ohm', 8)
    setting_line = '  '.join(f'{g}: drive {rs:.0f}/ODT {rt:.0f} ({np_}/{nn})' for g, (rs, rt, np_, nn, _) in settings.items())
    pdf.text(50, yy - 12, f'masks: overshoot <= {OVERSHOOT_MAX} V, ringback '
             f'must hold above VIH {VIH} V after the first crossing', 8)
    y = yy - 40
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
    print(f'si-report: {len(results)} net(s), {npass} PASS, ' + (f'[{setting_line}] ' if settings else '') +
          f'{len(results)-npass} FAIL -> {pdfp}')


if __name__ == '__main__':
    main()
