#!/usr/bin/env python3
"""Characteristic impedance from a gerber2ems result via the line's ABCD
matrix (Zc = sqrt(B/C), exact for a uniform line of any length; assumes a
symmetric, reciprocal two-port). Single-ended member from ports 0->1;
differential from the mixed-mode SDD (ports 0/2 -> 1/3) with a 100 ohm reference."""
import csv, cmath, math, sys, json, os
D=sys.argv[1].rstrip('/'); R=D+'/ems/results'
sim=json.load(open(D+'/simulation.json')); n=len(sim['ports'])
def load(p): return [[float(v) for v in row] for row in list(csv.reader(open(p)))[1:]]
def S(d,i): return cmath.rect(d[1+i], d[1+n+i])
def zc(s11,s21,z0):
    B=z0*((1+s11)**2-s21**2)/(2*s21); C=((1-s11)**2-s21**2)/(2*s21*z0)
    return cmath.sqrt(B/C)
d0=load(R+'/Port_0_data.csv'); rows=[]
d2=load(R+'/Port_2_data.csv') if n==4 and os.path.exists(R+'/Port_2_data.csv') else None
for k,a in enumerate(d0):
    f=a[0]; s00,s10=S(a,0),S(a,1); zse=zc(s00,s10,50)
    zd=None
    if d2:
        b=d2[k]; s02,s12,s22,s32=S(b,0),S(b,1),S(b,2),S(b,3); s20,s30=S(a,2),S(a,3)
        sdd11=(s00-s02-s20+s22)/2; sdd21=(s10-s12-s30+s32)/2; zd=zc(sdd11,sdd21,100)
    rows.append((f,zse,zd))
def band(lo,hi,idx):
    v=[r[idx] for r in rows if lo<=r[0]<=hi and r[idx] is not None]
    v=[x.real for x in v if abs(x.imag)<0.5*abs(x.real)]
    return (sum(v)/len(v), min(v), max(v)) if v else (float('nan'),)*3
for lo,hi in ((200,1000),(1000,2000),(2000,3000)):
    m,a,b=band(lo,hi,1); line=f"{lo:4d}-{hi:4d} MHz  Zse member {m:6.1f} ohm (range {a:.1f}..{b:.1f})"
    if d2: m2,a2,b2=band(lo,hi,2); line+=f"   Zdiff {m2:6.1f} ohm (range {a2:.1f}..{b2:.1f})"
    print(line)
