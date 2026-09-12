#!/usr/bin/env python3
"""Reduce a gerber2ems 4-port pair result (ports 0/1 = P start/stop, 2/3 = N)
to mixed-mode quantities, or a 2-port single-ended result to Zin/S21."""
import csv, cmath, math, sys, os, json
D=sys.argv[1].rstrip('/'); R=D+'/ems/results'
sim=json.load(open(D+'/simulation.json')); npor=len(sim['ports'])
def load(p): return [[float(v) for v in row] for row in list(csv.reader(open(p)))[1:]]
def S(d,i,n): return cmath.rect(d[1+i], d[1+n+i])
db=lambda v:20*math.log10(max(abs(v),1e-12))
if npor==4:
    d0=load(R+'/Port_0_data.csv'); d2=load(R+'/Port_2_data.csv'); zs=[]
    for a,b in zip(d0,d2):
        f=a[0]; s0=[S(a,i,4) for i in range(4)]; s2=[S(b,i,4) for i in range(4)]
        SDD11=(s0[0]-s2[0]-s0[2]+s2[2])/2; SDD21=(s0[1]-s2[1]-s0[3]+s2[3])/2; SCD21=(s0[1]-s2[1]+s0[3]-s2[3])/2
        SCC11=(s0[0]+s2[0]+s0[2]+s2[2])/2
        zs.append((f,100*(1+SDD11)/(1-SDD11),SDD11,SDD21,SCD21,25*(1+SCC11)/(1-SCC11)))
    lo=[z for z in zs if 200<=z[0]<=2200]
    zmin=min(abs(z[1]) for z in lo); zmax=max(abs(z[1]) for z in lo)
    print(f"Zdiff,in envelope 0.2-2.2 GHz: {zmin:.1f}..{zmax:.1f} ohm -> line Zdiff ~ {math.sqrt(zmin*zmax):.1f} ohm")
    print("  f MHz   Zdiff,in   SDD11 dB   SDD21 dB   SCD21 dB   Zcomm,in")
    for ft in (200,533,1066,1600,2133,3200,4000):
        z=min(zs,key=lambda z:abs(z[0]-ft)); print(f"{z[0]:7.0f} {abs(z[1]):9.1f} {db(z[2]):10.1f} {db(z[3]):10.2f} {db(z[4]):10.1f} {abs(z[5]):9.1f}")
else:
    d0=load(R+'/Port_0_data.csv'); zs=[]
    for a in d0:
        f=a[0]; s0=[S(a,i,npor) for i in range(npor)]
        zs.append((f,50*(1+s0[0])/(1-s0[0]),s0[0],s0[1]))
    lo=[z for z in zs if 200<=z[0]<=2200]
    zmin=min(abs(z[1]) for z in lo); zmax=max(abs(z[1]) for z in lo)
    print(f"Zin envelope 0.2-2.2 GHz: {zmin:.1f}..{zmax:.1f} ohm -> line Z0 ~ {math.sqrt(zmin*zmax):.1f} ohm")
    print("  f MHz     Zin    S11 dB    S21 dB")
    for ft in (200,533,1066,1600,2133,3200,4000):
        z=min(zs,key=lambda z:abs(z[0]-ft)); print(f"{z[0]:7.0f} {abs(z[1]):8.1f} {db(z[2]):9.1f} {db(z[3]):9.2f}")
