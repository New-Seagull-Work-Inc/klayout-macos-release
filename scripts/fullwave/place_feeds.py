#!/usr/bin/env python3
"""After gerber2ems -g: put each simulation port's feed where the reference
planes are solid under the whole 0.4 mm port (outside via antipads and the
ball-field perforation), one common distance per pair end; rewrite the pos
file. Run gerber2ems -a afterwards (it regenerates the geometry)."""
import re, json, csv, sys, os
d=sys.argv[1].rstrip('/'); name=os.path.basename(d); os.chdir(d)
pr=json.load(open('ports_runs.json')); ox,oy=pr['origin']; ports=pr['ports']; planes=set(pr.get('planes',[]))
sim=json.load(open('simulation.json'))
x=open('ems/geometry/geometry.xml').read()
def polys(idx):
    i=x.find('Name="Gerber_%d"'%idx); seg=x[i:i+x[i:].find('</Metal>')]
    return [[(float(a)/1e4,float(b)/1e4) for a,b in re.findall(r'<Vertex X1="([-\d.e+]+)" X2="([-\d.e+]+)"', pp)] for pp in re.findall(r'<Polygon.*?</Polygon>', seg, re.S)]
def inside(pt,poly):
    c=False; n=len(poly)
    for k in range(n):
        (x1,y1),(x2,y2)=poly[k],poly[(k+1)%n]
        if (y1>pt[1])!=(y2>pt[1]) and pt[0]<(x2-x1)*(pt[1]-y1)/(y2-y1+1e-12)+x1: c=not c
    return c
cache={}
def solid(pt,li):
    for L in (li-1,li+1):
        if L<0 or (planes and L not in planes): continue
        if L not in cache: cache[L]=polys(L)
        if cache[L] and not any(inside(pt,pp) for pp in cache[L]): return False
    return True
def feed(port,dist):
    pts=[]
    for t in (0,0.2,0.4):
        dd=dist+t; pos=None
        for a,u,L,ax,li in port['runs']:
            if dd<=L+1e-9: pos=(a[0]+u[0]*dd,a[1]+u[1]*dd,tuple(u),li) if ax else None; break
            dd-=L
        if pos is None: return None
        pts.append(pos)
    if len(set(q[2] for q in pts))!=1 or len(set(q[3] for q in pts))!=1: return None
    if all(solid((q[0]-ox+dx_off,oy-q[1]+dy_off),pts[0][3]) for q in pts[:2]): return pts[0]  # feed resistor and probe plane over plane copper
    return None

dx_off=dy_off=0.0
import glob
n=len(ports); groups=[(0,2),(1,3)] if (n==4 and sim.get('differential_pairs')) else [(i,) for i in range(n)]  # a real pair: common feed distance per end; otherwise every port on its own
rows=[['Ref','Val','Package','PosX','PosY','Rot','Side']]; out=[None]*n
for grp in groups:
    for d10 in range(3,150):
        dist=d10/10; got=[feed(ports[i],dist) for i in grp]
        if all(g is not None for g in got): break
    else: got=[None]*len(grp); print('WARNING: no solid-plane feed for', [ports[i]['net'] for i in grp])
    for i,g in zip(grp,got):
        if g is None: a,u,L,ax,li=ports[i]['runs'][0]; g=(a[0]+u[0]*0.3,a[1]+u[1]*0.3,u,li)
        rot={(1,0):270,(-1,0):90,(0,1):180,(0,-1):0}[(round(g[2][0]),round(g[2][1]))]
        out[i]=(g,rot,dist); print(ports[i]['net'], 'feed at', round(g[0],3), round(g[1],3), 'rot', rot, 'layer', g[3], 'd=%.1f'%dist)

for i,(g,rot,dist) in enumerate(out): rows.append([f'SP{i+1}','Simulation_Port','Simulation_Port',round(g[0]-ox,6),round(oy-g[1],6),rot,'top'])
with open(f'fab/{name}-pos.csv','w',newline='') as fh:
    wr=csv.writer(fh,quoting=csv.QUOTE_NONNUMERIC); [wr.writerow(r) for r in rows]
for i,(g,rot,dist) in enumerate(out):
    li=g[3]; pls=sorted(planes) or [li+1]; pl=min(pls,key=lambda k:(abs(k-li),-k))
    sim['ports'][i]['layer']=li; sim['ports'][i]['plane']=pl
json.dump(sim,open('simulation.json','w'),indent=2)
print('ports layer/plane', [(p['layer'],p['plane']) for p in sim['ports']])

# --- truncate the trace behind each feed so the port is the end of the line ---
import subprocess
K='/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
pcb=name+'.kicad_pcb'; src=open(pcb).read()
segre=re.compile(r'\t\(segment\s*\(start ([\d.-]+) ([\d.-]+)\)\s*\(end ([\d.-]+) ([\d.-]+)\)\s*\(width ([\d.]+)\)\s*\(layer "([^"]+)"\)\s*\(net "([^"]+)"\)\s*\(uuid "[^"]+"\)\s*\)\n')
segs=[(m.group(0),tuple(float(v) for v in m.groups()[:4]),m.group(6),m.group(7)) for m in segre.finditer(src)]
arcre=re.compile(r'\t\(arc\s*\(start ([\d.-]+) ([\d.-]+)\)\s*\(mid [\d.-]+ [\d.-]+\)\s*\(end ([\d.-]+) ([\d.-]+)\)\s*\(width ([\d.]+)\)\s*\(layer "([^"]+)"\)\s*\(net "([^"]+)"\)\s*\(uuid "[^"]+"\)\s*\)\n')
segs+=[(m.group(0),tuple(float(v) for v in m.groups()[:4]),m.group(6),m.group(7)) for m in arcre.finditer(src)]
home={p['net']:None for p in ports}
for i,(g,rot,dist) in enumerate(out):
    port=ports[i]; a0=tuple(port['runs'][0][0]); L=None
    # the home layer name from the stackup index
    mine=[s for s in segs if s[3]==port['net']]
    cur=a0; walked=0.0; used=set()
    while walked<dist-1e-9:
        nxt=[s for s in mine if s[0] not in used and (abs(s[1][0]-cur[0])+abs(s[1][1]-cur[1])<1e-6 or abs(s[1][2]-cur[0])+abs(s[1][3]-cur[1])<1e-6)]
        if not nxt: break
        s=nxt[0]; used.add(s[0]); x1,y1,x2,y2=s[1]
        a=(x1,y1) if abs(x1-cur[0])+abs(y1-cur[1])<1e-6 else (x2,y2); b=(x2,y2) if a==(x1,y1) else (x1,y1)
        Ls=((b[0]-a[0])**2+(b[1]-a[1])**2)**0.5
        if walked+Ls<=dist+1e-9:
            src=src.replace(s[0],'',1)  # entirely behind the feed: drop it
        else:
            # shorten: new start at the feed point
            f=dist-walked; u=((b[0]-a[0])/Ls,(b[1]-a[1])/Ls); ns=(a[0]+u[0]*f,a[1]+u[1]*f)
            new=re.sub(r'\(start [\d.-]+ [\d.-]+\)\s*\(end [\d.-]+ [\d.-]+\)', '(start %.4f %.4f)\n\t\t(end %.4f %.4f)'%(ns[0],ns[1],b[0],b[1]), s[0], count=1)
            src=src.replace(s[0],new,1)
        walked+=Ls; cur=b
    print(port['net'], 'trace truncated %.2f mm behind the feed'%walked)
open(pcb,'w').write(src)
for f in os.listdir('fab'):
    if f.endswith('.gbr') or f.endswith('.gbrjob'): os.remove('fab/'+f)
cu_all=[l['name'] for l in json.load(open('fab/stackup.json'))['layers'] if l['type']=='copper']
subprocess.run([K,'pcb','export','gerbers','--use-drill-file-origin','--no-protel-ext','-l',','.join(cu_all+['Edge.Cuts']),'-o','fab/',pcb],capture_output=True)
print('gerbers re-exported')
