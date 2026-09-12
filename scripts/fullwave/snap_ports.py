#!/usr/bin/env python3
"""Snap each simulation port across-axis onto the rendered copper centreline of
its own trace, and shift the drill by the mean offset. Run after the FINAL
geometry render (gerber2ems -g on the truncated slice): gerber2ems' crop of
the edge stroke can move the frame by a pixel row between renders."""
import re, json, csv, sys, os, glob
d=sys.argv[1].rstrip('/'); name=os.path.basename(d); os.chdir(d)
pr=json.load(open('ports_runs.json')); sim=json.load(open('simulation.json'))
x=open('ems/geometry/geometry.xml').read()
def polys(idx):
    i=x.find('Name="Gerber_%d"'%idx); seg=x[i:i+x[i:].find('</Metal>')]
    return [[(float(a)/1e4,float(b)/1e4) for a,b in re.findall(r'<Vertex X1="([-\d.e+]+)" X2="([-\d.e+]+)"', pp)] for pp in re.findall(r'<Polygon.*?</Polygon>', seg, re.S)]
f=f'fab/{name}-pos.csv'; rows=list(csv.reader(open(f))); cache={}; shifts=[]
for r in rows[1:]:
    if not r[0].startswith('SP'): continue
    i=int(r[0][2:])-1; px,py,rot=float(r[3]),float(r[4]),int(float(r[5]))
    li=sim['ports'][i]['layer']; wmm=sim['ports'][i]['width']/1000.0; win=wmm+0.08
    if li not in cache: cache[li]=polys(li)
    along_x = rot in (90,270); L=0.4; sx=-1 if rot==90 else 1; sy=-1 if rot==0 else 1
    vals=[]
    for pp in cache[li]:
        for (vx,vy) in pp:
            if along_x:
                if min(px,px+sx*L)-0.02<=vx<=max(px,px+sx*L)+0.02 and abs(vy-py)<win: vals.append(vy)
            else:
                if min(py,py+sy*L)-0.02<=vy<=max(py,py+sy*L)+0.02 and abs(vx-px)<win: vals.append(vx)
    def band(win):
        vv=[]
        for pp in cache[li]:
            for (vx,vy) in pp:
                if along_x:
                    if min(px,px+sx*L)-0.02<=vx<=max(px,px+sx*L)+0.02 and abs(vy-py)<win: vv.append(vy)
                else:
                    if min(py,py+sy*L)-0.02<=vy<=max(py,py+sy*L)+0.02 and abs(vx-px)<win: vv.append(vx)
        return vv
    vals=band(win)
    if vals and max(vals)-min(vals) < 0.5*wmm: vals=band(2*win)  # one edge only: look further out
    if not vals: print(r[0],'no copper under the port!'); continue
    c=(min(vals)+max(vals))/2; width=max(vals)-min(vals); dd=c-(py if along_x else px)
    if width<1.4*wmm+0.03 or (width<0.6 and width>wmm):  # a single trace, possibly wider than the walk's last segment
        if along_x: r[4]='%f'%(py+dd)
        else: r[3]='%f'%(px+dd)
        shifts.append(dd)
        if width>1.4*wmm+0.03:  # the port takes the copper's width (widened trace, necked end)
            sim['ports'][i]['width']=round(width*1000,1); print(r[0],'port width set to the copper: %.3f mm'%width)
        print(r[0],'snapped %.3f mm (trace width %.3f)'%(dd,width))
    else: print(r[0],'copper band %.3f too wide, not snapped'%width)
json.dump(sim,open('simulation.json','w'),indent=2)
with open(f,'w',newline='') as fh:
    wr=csv.writer(fh,quoting=csv.QUOTE_NONNUMERIC); [wr.writerow(rr) for rr in rows]
if shifts:
    m=sum(shifts)/len(shifts); drl=glob.glob('fab/*-PTH.drl')
    if drl and abs(m)>0.01:
        t=open(drl[0]).read()
        t=re.sub(r'^X([\d.]+)Y([\d.]+)$', lambda mm: 'X%.3fY%.3f'%(float(mm.group(1))+m,float(mm.group(2))+m), t, flags=re.M)
        open(drl[0],'w').write(t); print('drill shifted by %.3f mm'%m)
