#!/usr/bin/env python3
"""One-line readout of a slice: Zc (ABCD, 0.2-2 GHz), match, transmission, convergence, sanity."""
import csv, cmath, math, sys, json, os, re
D=sys.argv[1].rstrip('/'); R=D+'/ems/results'
sim=json.load(open(D+'/simulation.json')); n=len(sim['ports']); xt=bool(sim.get('crosstalk'))
def load(p): return [[float(v) for v in row] for row in list(csv.reader(open(p)))[1:]]
def S(d,i): return cmath.rect(d[1+i], d[1+n+i])
def zc(s11,s21,z0):
    B=z0*((1+s11)**2-s21**2)/(2*s21); C=((1-s11)**2-s21**2)/(2*s21*z0); return cmath.sqrt(B/C)
db=lambda v:20*math.log10(max(abs(v),1e-12))
d0=load(R+'/Port_0_data.csv'); d2=load(R+'/Port_2_data.csv') if (n==4 and not xt) else None
zse=[]; zd=[]; s11=[]; s21=[]; sdd11=[]; sdd21=[]; next_=[]
for k,a in enumerate(d0):
    f=a[0]
    if not (200<=f<=2000): continue
    z=zc(S(a,0),S(a,1),50); 
    if abs(z.imag)<0.5*abs(z.real): zse.append(z.real)
    s11.append(db(S(a,0))); s21.append(db(S(a,1)))
    if d2:
        b=d2[k]; sa=[S(a,i) for i in range(4)]; sb=[S(b,i) for i in range(4)]
        D11=(sa[0]-sb[0]-sa[2]+sb[2])/2; D21=(sa[1]-sb[1]-sa[3]+sb[3])/2
        z=zc(D11,D21,100)
        if abs(z.imag)<0.5*abs(z.real): zd.append(z.real)
        sdd11.append(db(D11)); sdd21.append(db(D21)); next_.append(db(sa[2]))
med=lambda v: sorted(v)[len(v)//2] if v else float('nan')
log=open(D+'/gerber2ems.log').read(); e=re.findall(r'Energy: ~[\d.e+-]+ \(([-\d.]+)dB\)', log); conv=e[-1] if e else '?'
ok = (s21 and med(s21)>-4) or (sdd21 and med(sdd21)>-4)
tag=os.path.basename(os.path.dirname(os.path.dirname(D)))+'/'+os.path.basename(D)
if d2: print(f"{tag:32s} Zdiff {med(zd):6.1f} ohm  member {med(zse):6.1f}  | SDD11 {med(sdd11):6.1f} dB SDD21 {med(sdd21):6.2f} NEXT {med(next_):6.1f} | energy {conv} dB {'' if ok else 'SUSPECT'}")
else:  print(f"{tag:32s} Zse   {med(zse):6.1f} ohm               | S11 {med(s11):6.1f} dB S21 {med(s21):6.2f}               | energy {conv} dB {'' if ok else 'SUSPECT'}")
