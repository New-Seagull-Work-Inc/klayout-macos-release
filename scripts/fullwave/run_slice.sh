#!/bin/bash
# prep -> geometry -> feeds over solid plane -> simulate, keeping only the copper layers that
# matter for the net's home layer (F.Cu .. one plane below the deepest home layer)
export PATH=$HOME/opt/openEMS/bin:/opt/homebrew/bin:$PATH
T=$HOME/opt/fullwave/tools; G=$HOME/opt/openEMS/venv/bin/gerber2ems; D=$1
cd "$D" && rm -rf ems && python3 $T/prep_slice.py "$D" 2>&1 | grep -E 'Trace|Error'
$G -g > g.log 2>&1; python3 $T/place_feeds.py "$D" 2>&1 | grep -E 'feed at|WARN|ports layer'
python3 - <<'PY'
import json
sim=json.load(open('simulation.json')); st=json.load(open('fab/stackup.json'))
cu=[l['name'] for l in st['layers'] if l['type']=='copper']
deep=max(max(p['layer'],p['plane']) for p in sim['ports'])
pr=json.load(open('ports_runs.json')); planes=sorted(pr.get('planes',[]))
used=max(r[4] for p in pr['ports'] for r in p['runs'])  # deepest copper layer the net runs on
below=[k for k in planes if k>=used]; deep=max(deep, below[0] if below else used)
keep=[]; ci=-1
for l in st['layers']:
    keep.append(l)
    if l['type']=='copper':
        ci+=1
        if ci==deep: break
json.dump({'layers':keep,'format_version':'1.0'},open('fab/stackup.json','w'),indent=2)
print('stack kept through', keep[-1]['name'], '| ports layer/plane', [(p['layer'],p['plane']) for p in sim['ports']])
PY
rm -rf ems; $G -g > g2.log 2>&1; python3 $T/snap_ports.py "$D" 2>&1 | grep -E "snapped|shifted|no copper|too wide"
rm -rf ems; t0=$(date +%s); $G -a > gerber2ems.log 2>&1; echo "$(basename $(dirname $(dirname $D)))/$(basename $D) rc=$? secs=$(( $(date +%s) - t0 ))"
grep Timestep gerber2ems.log | tail -1 | cut -c1-100
