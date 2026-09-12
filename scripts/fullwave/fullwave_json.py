#!/usr/bin/env python3
"""Collect a workspace's slice results into <board out dir>/si-report/fullwave.json
for scripts/signoff.py:  {net: {kind: pair|member, z_ohm, next_db, s11_db, method, date}}.
Usage: fullwave_json.py WORKSPACE OUT_DIR"""
import sys, os, json, csv, cmath, math, time, glob, subprocess
W, OUT = sys.argv[1], sys.argv[2]
rd = os.path.expanduser('~/opt/fullwave/tools/readout.py')
res = {}
for d in sorted(glob.glob(os.path.join(W, 'slices', '*'))):
    if not os.path.exists(os.path.join(d, 'ems/results/Port_0_data.csv')): continue
    line = subprocess.run(['python3', rd, d], capture_output=True, text=True).stdout.strip()
    if 'SUSPECT' in line or not line: continue
    name = os.path.basename(d)
    import re
    simj = json.load(open(os.path.join(d, 'simulation.json'))) if os.path.exists(os.path.join(d, 'simulation.json')) else {}
    if simj.get('crosstalk'):  # victim + aggressor: the victim's channel is ports 0->1; aggressor ends are ports 2,3
        m = re.search(r'Zse\s+([\d.]+) ohm.*S11\s+([-\d.]+)', line)
        vic = simj['crosstalk']['victim']
        e = res.setdefault(vic, {'kind': 'member', 'method': 'openEMS ABCD 0.2-2 GHz', 'date': time.strftime('%Y-%m-%d')})
        e['slice'] = os.path.abspath(d)
        if m: e['z_ohm'] = float(m.group(1)); e['s11_db'] = float(m.group(2))
        e['aggressors'] = [{'net': simj['crosstalk']['aggressors'][0], 'slice': os.path.abspath(d), 'ports': [2, 1], 'kind': 'FEXT'},
                           {'net': simj['crosstalk']['aggressors'][0], 'slice': os.path.abspath(d), 'ports': [3, 1], 'kind': 'NEXT'}]
        continue
    if name.endswith('_Diff'):
        m = re.search(r'Zdiff\s+([\d.]+) ohm.*NEXT\s+([-\d.]+)', line)
        if m: res[name[:-5]] = {'kind': 'pair', 'slice': os.path.abspath(d), 'z_ohm': float(m.group(1)), 'next_db': float(m.group(2)), 'method': 'openEMS ABCD 0.2-2 GHz', 'date': time.strftime('%Y-%m-%d')}
    else:
        m = re.search(r'Zse\s+([\d.]+) ohm.*S11\s+([-\d.]+)', line)
        if m: res[name] = {'kind': 'member', 'slice': os.path.abspath(d), 'z_ohm': float(m.group(1)), 's11_db': float(m.group(2)), 'method': 'openEMS ABCD 0.2-2 GHz', 'date': time.strftime('%Y-%m-%d')}
os.makedirs(os.path.join(OUT, 'si-report'), exist_ok=True)
json.dump(res, open(os.path.join(OUT, 'si-report', 'fullwave.json'), 'w'), indent=1)
print(OUT, '->', {k: v['z_ohm'] for k, v in res.items()})
