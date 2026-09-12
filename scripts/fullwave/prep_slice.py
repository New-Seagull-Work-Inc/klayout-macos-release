#!/usr/bin/env python3
"""Prepare an si-wrapper slice for gerber2ems the way the tool expects:
aux origin at the board corner, X2 gerbers, drill/pos against that origin,
simulation ports on the net's home layer at the trace ends (axis-aligned
launch), stackup.json from the board's own stackup block."""
import re, json, csv, sys, os, subprocess, math
K='/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
slice_dir=sys.argv[1].rstrip('/'); name=os.path.basename(slice_dir); os.chdir(slice_dir)
pcb=name+'.kicad_pcb'; src=open(pcb).read()
sim=json.load(open('simulation.json'))
# nets under test: from netinfo (pair: P/N) else the slice name
ni=json.load(open('netinfo.json')) if os.path.exists('netinfo.json') else {}
nets=[]
for p in sim.get('differential_pairs',[]): pass
cand=sorted({m for m in re.findall(r'\(net "([^"]+)"\)', src) if m and not m.startswith(('GND','DGND','VDD','+','/'))})
cand=[n for n in cand if name.replace('_Diff','') in n or n.startswith(name.rsplit('_',1)[0])]
if ni.get('nets') and len(ni['nets'])>1 and not (ni['nets'][0]['name'].endswith('_P') and ni['nets'][1]['name'].endswith('_N')):  # the wrapper flags any two nets as 'diff'; a real pair is _P/_N
    # victim + aggressor slice (crosstalk): every designated net gets two ports; the wrapper
    # wrote a differential_pairs entry for the two nets — they are single-ended, drop it
    nets=[n['name'] for n in ni['nets']]; sim.pop('differential_pairs', None)
elif sim.get('differential_pairs'):
    base=name.replace('_Diff','')
    nets=[base+'_P', base+'_N']
else: nets=[name]
print('nets', nets)
# copper layer order from the stackup block
blk=re.search(r'\(stackup(.*?)\n\t\t\)\n', src, re.S).group(1)
layers=[]
for lm in re.finditer(r'\(layer\s+"([^"]+)"\s*(.*?)\n\t\t\t\)', blk, re.S):
    nm, body=lm.group(1), lm.group(2)
    t=(re.search(r'\(type\s+"([^"]+)"\)', body) or [None,''])[1]
    th=re.search(r'\(thickness\s+([\d.]+)', body); er=re.search(r'\(epsilon_r\s+([\d.]+)\)', body); lt=re.search(r'\(loss_tangent\s+([\d.]+)\)', body)
    if 'copper' in t: layers.append({"name": nm, "type": "copper", "color": None, "thickness": float(th.group(1)), "material": None, "epsilon": None, "lossTangent": None})
    elif 'core' in t or 'prepreg' in t: layers.append({"name": nm, "type": "core" if 'core' in t else "prepreg", "color": None, "thickness": float(th.group(1)), "material": "FR4", "epsilon": float(er.group(1)) if er else 4.3, "lossTangent": float(lt.group(1)) if lt else 0.02})
cu=[l['name'] for l in layers if l['type']=='copper']
os.makedirs('fab', exist_ok=True)
json.dump({"layers": layers, "format_version": "1.0"}, open('fab/stackup.json','w'), indent=2)
# ground planes: layers whose zones are GND-ish
gnd=set()
for zm in re.finditer(r'\(zone\s*(?:\(net [^)]*\)\s*)?(?:\(net_name "[^"]*"\)\s*)?\(layers? ([^)]+)\)', src):
    gnd.update(x.strip('"') for x in zm.group(1).split())
# segments per net
segs={}
for m in re.finditer(r'\(segment\s*\(start ([\d.-]+) ([\d.-]+)\)\s*\(end ([\d.-]+) ([\d.-]+)\)\s*\(width ([\d.]+)\)\s*\(layer "([^"]+)"\)\s*\(net "([^"]+)"\)', src):
    x1,y1,x2,y2,w=map(float,m.groups()[:5]); L,n=m.group(6),m.group(7)
    if n in nets: segs.setdefault(n,[]).append((x1,y1,x2,y2,w,L))
# arcs: walked as one piece from start to end (never axis-aligned, so never a port site); length = chord * (theta/2)/sin(theta/2)
for m in re.finditer(r'\(arc\s*\(start ([\d.-]+) ([\d.-]+)\)\s*\(mid ([\d.-]+) ([\d.-]+)\)\s*\(end ([\d.-]+) ([\d.-]+)\)\s*\(width ([\d.]+)\)\s*\(layer "([^"]+)"\)\s*\(net "([^"]+)"\)', src):
    x1,y1,xm,ym,x2,y2,w=map(float,m.groups()[:7]); L,n=m.group(8),m.group(9)
    if n in nets: segs.setdefault(n,[]).append((x1,y1,x2,y2,w,L,'arc'))
# board corner
e=re.search(r'\(gr_rect\s*\(start ([\d.-]+) ([\d.-]+)\)\s*\(end ([\d.-]+) ([\d.-]+)\)(?:.|\n)*?\(layer "Edge.Cuts"\)', src)
ex=[float(e.group(1)),float(e.group(3))]; ey=[float(e.group(2)),float(e.group(4))]
ox,oy=min(ex)-0.05,max(ey)+0.05
s2=re.sub(r'\(aux_axis_origin [^)]*\)','',src).replace('(setup\n', f'(setup\n\t\t(aux_axis_origin {ox} {oy})\n',1)
open(pcb,'w').write(s2)
ports=[]
# vias of the nets under test: layer changes happen there
vias={}
for m in re.finditer(r'\(via\s*\(at ([\d.-]+) ([\d.-]+)\)\s*\(size [\d.]+\)\s*\(drill [\d.]+\)\s*\(layers [^)]*\)\s*(?:\([^)]*\)\s*)*?\(net "([^"]+)"\)', src):
    if m.group(3) in nets: vias.setdefault(m.group(3),[]).append((float(m.group(1)),float(m.group(2))))
def near(a,b): return abs(a[0]-b[0])+abs(a[1]-b[1])<1e-6
for n in nets:
    ss=segs[n]; vv=vias.get(n,[])
    # true route ends: vertices touched by exactly one segment and no via
    deg={}
    for s in ss:
        for p in ((s[0],s[1]),(s[2],s[3])): deg[p]=deg.get(p,0)+1
    # a via is a layer change only if segments meet it on two layers; a via touched on one layer is a terminal (pad via)
    def via_layers(v): return {s[5] for s in ss if near((s[0],s[1]),v) or near((s[2],s[3]),v)}
    ends=[p for p,c in deg.items() if c==1 and not any(near(p,v) and len(via_layers(v))>1 for v in vv)]
    ends=sorted(ends); ends=ends[:1]+ends[-1:] if len(ends)>2 else ends  # always sorted: P and N ports must pair the same ends
    for p in ends:
        cur=p; used=set(); runs=[]; w=None
        for _ in range(600):
            # continue on any layer: at a via, all layers are reachable
            here=[s for s in ss if id(s) not in used and (near((s[0],s[1]),cur) or near((s[2],s[3]),cur))]
            if not here: break
            s=here[0]; used.add(id(s)); a=(s[0],s[1]) if near((s[0],s[1]),cur) else (s[2],s[3]); b=(s[2],s[3]) if a==(s[0],s[1]) else (s[0],s[1])
            dx,dy=b[0]-a[0],b[1]-a[1]; L=math.hypot(dx,dy); w=s[4]
            if L>1e-6:
                ux,uy=dx/L,dy/L; axis=(abs(dx)<1e-6 or abs(dy)<1e-6) and len(s)==6; li=cu.index(s[5])
                if runs and runs[-1][3]==axis and runs[-1][4]==li and abs(runs[-1][1][0]-ux)+abs(runs[-1][1][1]-uy)<1e-6: runs[-1]=(runs[-1][0],runs[-1][1],runs[-1][2]+L,axis,li)
                else: runs.append((a,(ux,uy),L,axis,li))
            cur=b
        ports.append((runs,None,None,w*1000,n,None))
ports_runs=sorted(ports,key=lambda t:nets.index(t[4]))
# provisional ports (place_feeds.py sets the real positions/layers after the geometry is rendered)
ports=[]
for runs,_,_,w,n,_ in ports_runs:
    a,u,L,ax,li=runs[0]; pls=[i for i,l in enumerate(cu) if l in gnd] or [li+1 if li+1<len(cu) else li-1]; pl=min(pls,key=lambda i:(abs(i-li), -i))
    rot={(1,0):270,(-1,0):90,(0,1):180,(0,-1):0}.get((round(u[0]),round(u[1])),0)
    ports.append(((a[0]+u[0]*0.3,a[1]+u[1]*0.3),rot,li,pl,w,n,cu[li],0.3))
json.dump({'origin':[ox,oy],'nets':nets,'planes':[i for i,l in enumerate(cu) if l in gnd],'ports':[{'runs':[[list(a),list(u),L,ax,li] for a,u,L,ax,li in ports_runs[i][0]],'layer':ports_runs[i][0][0][4],'plane':None,'width':ports_runs[i][3],'net':ports_runs[i][4]} for i in range(len(ports_runs))]},open('ports_runs.json','w'),indent=1)
# export fab against the aux origin, X2 attributes kept (the mesher refines around the nets under test)
for f in os.listdir('fab'):
    if f!='stackup.json': os.remove('fab/'+f)
subprocess.run([K,'pcb','export','gerbers','--use-drill-file-origin','--no-protel-ext','-l',','.join(cu+['Edge.Cuts']),'-o','fab/',pcb],capture_output=True)
subprocess.run([K,'pcb','export','drill','--drill-origin','plot','--excellon-separate-th','--format','excellon','-o','fab/',pcb],capture_output=True)
# the board's own GND vias inside the slice: they tie the reference planes (the wrapper strips them)
import glob
srcb=glob.glob(os.path.join(os.path.dirname(os.path.dirname(slice_dir)),'*.kicad_pcb'))
if srcb:
    bsrc=open(srcb[0]).read()
    vias=[(float(a),float(b),float(dr),nn) for a,b,sz,dr,nn in re.findall(r'\(via\s*\(at ([\d.-]+) ([\d.-]+)\)\s*\(size ([\d.]+)\)\s*\(drill ([\d.]+)\)\s*\(layers [^)]*\)\s*\(net "([^"]*)"\)', bsrc)]
    ins=[v for v in vias if 'GND' in v[3].upper() and min(ex)<=v[0]<=max(ex) and min(ey)<=v[1]<=max(ey)]
    drl=glob.glob('fab/*-PTH.drl')
    if drl and ins:
        t=open(drl[0]).read()
        tool=re.search(r'^(T\d+)C([\d.]+)', t, re.M)
        lines=[f"X{v[0]-ox:.3f}Y{oy-v[1]:.3f}" for v in ins]
        if tool and 'M30' in t:
            t=t.replace('M30', '\n'.join(lines)+'\nM30',1); open(drl[0],'w').write(t)
            print(len(ins),'GND vias from the board added to the slice drill (tool',tool.group(1),tool.group(2),'mm)')

with open(f'fab/{name}-pos.csv','w',newline='') as fh:
    wr=csv.writer(fh,quoting=csv.QUOTE_NONNUMERIC); wr.writerow(['Ref','Val','Package','PosX','PosY','Rot','Side'])
    for i,(p,r,li,pl,w,n,h,d) in enumerate(ports): wr.writerow([f'SP{i+1}','Simulation_Port','Simulation_Port',round(p[0]-ox,6),round(oy-p[1],6),r,'top'])
# simulation.json ports; pairs: P ports then N ports, order start/stop
sim['ports']=[]
xt = (not sim.get('differential_pairs')) and len(nets)>1  # crosstalk slice
for i,(p,r,li,pl,w,n,h,d) in enumerate(ports):
    sim['ports'].append({'number':i+1,'width':round(w,1),'length':400.0,'impedance':50.0,'layer':li,'plane':pl,'excite': True if xt else i%2==0})
if xt: sim['crosstalk']={'victim':nets[0],'aggressors':nets[1:]}
if sim.get('differential_pairs'):
    sim['differential_pairs'][0].update({'start_p':0,'stop_p':1,'start_n':2,'stop_n':3})
json.dump(sim,open('simulation.json','w'),indent=2)
print('layers', cu, 'gnd', sorted(gnd)); print(open(f'fab/{name}-pos.csv').read()); print([ (p['layer'],p['plane'],p['width'],p['excite']) for p in sim['ports']])
