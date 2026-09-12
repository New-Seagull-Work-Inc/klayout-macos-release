#!/usr/bin/env python3
"""progress.py — the sign-off progress page from docs/signoff-history.json
(one entry per build, written by scripts/signoff.py --record): a verdict
timeline per board, four metric charts across builds (open conditions,
DQS0 pair Z_diff, worst lane skew, member copper above the neck) and the
build notes (from the git subjects). Usage:
    python3 scripts/progress.py [-i docs/signoff-history.json] [-o docs/signoff-progress.html]"""
import sys, os, json, html, subprocess, time

VT = {'pass': 'Signed off', 'cond': 'Conditional', 'fail': 'Not ready'}
COLORS = ['#b5622a', '#2f6f9f', '#5b7d2a', '#8a4b8a', '#a0522d', '#4b6f8a']

CSS = """
:root{--bg:#f3f5f7;--paper:#fff;--ink:#18212b;--ink-2:#4a5561;--ink-3:#7c8792;--rule:#d7dde3;--rule-2:#e9edf0;--copper:#b5622a;--pass:#1e7f4f;--pass-bg:#e3f2e9;--cond:#9a6b07;--cond-bg:#f8efd4;--fail:#b3261e;--fail-bg:#f9e2df;--band:#e3f2e9;--grid:#e9edf0}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#0f1418;--paper:#161c22;--ink:#e6eaee;--ink-2:#aab4be;--ink-3:#7d8893;--rule:#2a333c;--rule-2:#202830;--copper:#d98c4f;--pass:#5fc48f;--pass-bg:#173225;--cond:#e0b24a;--cond-bg:#3a2f12;--fail:#f08a83;--fail-bg:#3f1f1c;--band:#173225;--grid:#202830}}
:root[data-theme="dark"]{--bg:#0f1418;--paper:#161c22;--ink:#e6eaee;--ink-2:#aab4be;--ink-3:#7d8893;--rule:#2a333c;--rule-2:#202830;--copper:#d98c4f;--pass:#5fc48f;--pass-bg:#173225;--cond:#e0b24a;--cond-bg:#3a2f12;--fail:#f08a83;--fail-bg:#3f1f1c;--band:#173225;--grid:#202830}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:15px;line-height:1.5}
.page{max-width:1120px;margin:0 auto;padding:40px 28px 72px}h1,h2,h3{font-family:"IBM Plex Sans Condensed","IBM Plex Sans",sans-serif;font-weight:600;margin:0;text-wrap:balance}
h1{font-size:34px;line-height:1.1}h2{font-size:21px;margin-bottom:6px}.sub{color:var(--ink-2);margin:0 0 14px;max-width:70ch}
.eyebrow{font-family:"IBM Plex Mono",monospace;font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3)}
header{display:flex;flex-wrap:wrap;gap:18px 40px;align-items:flex-end;justify-content:space-between;padding-bottom:22px;border-bottom:2px solid var(--copper)}
header .meta{font-family:"IBM Plex Mono",monospace;font-size:12.5px;color:var(--ink-2);display:grid;gap:3px;text-align:right}header .meta b{color:var(--ink);font-weight:500}
.lede{max-width:68ch;color:var(--ink-2);margin:18px 0 0}section{margin-top:40px}.panel{background:var(--paper);border:1px solid var(--rule);border-radius:6px;padding:18px 20px;overflow-x:auto}
.tl{display:grid;gap:6px;align-items:stretch}.tl .h{font-family:"IBM Plex Mono",monospace;font-size:11.5px;color:var(--ink-3);text-transform:uppercase;letter-spacing:.06em;padding:0 6px 6px;border-bottom:1px solid var(--rule);display:grid;gap:2px}
.tl .h b{color:var(--ink);font-weight:500;text-transform:none;letter-spacing:0;font-size:12.5px}.tl .b{font-family:"IBM Plex Sans Condensed",sans-serif;font-weight:600;font-size:18px;padding:12px 6px;display:flex;align-items:center}
.cell{border-radius:4px;padding:10px 10px 9px;display:grid;gap:3px;border:1px solid transparent;min-height:64px}.cell.changed{border-width:3px;box-shadow:0 0 0 1px var(--paper) inset}.tl .h.latest b{color:var(--copper)}.cell.pass{background:var(--pass-bg);border-color:var(--pass)}.cell.cond{background:var(--cond-bg);border-color:var(--cond)}.cell.fail{background:var(--fail-bg);border-color:var(--fail)}.cell.none{background:var(--rule-2);border-color:var(--rule)}
.cell .v{font-family:"IBM Plex Mono",monospace;font-size:11px;letter-spacing:.06em;text-transform:uppercase;font-weight:500}.cell.pass .v{color:var(--pass)}.cell.cond .v{color:var(--cond)}.cell.fail .v{color:var(--fail)}.cell.none .v{color:var(--ink-3)}.cell .d{font-size:12.5px;color:var(--ink-2);line-height:1.35}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}.chart h3{font-size:16px;margin-bottom:2px}.chart .cap{font-size:12.5px;color:var(--ink-3);margin:0 0 8px}svg{width:100%;height:auto;display:block}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;color:var(--ink-2);margin-top:8px}.legend i{display:inline-block;width:18px;height:3px;vertical-align:middle;margin-right:6px;border-radius:2px}
.events{display:grid;gap:10px;font-size:14px}.events .e{display:grid;grid-template-columns:150px 1fr;gap:12px;padding:8px 0;border-bottom:1px solid var(--rule-2)}.events .e:last-child{border-bottom:0}.events .k{font-family:"IBM Plex Mono",monospace;font-size:12.5px;color:var(--ink-2)}.events .k b{color:var(--ink);font-weight:500;display:block}
.eyes{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px}.eyebox{background:var(--paper);border:1px solid var(--rule);border-radius:6px;padding:10px 12px 8px}.eyebox.measured{border-color:var(--copper)}.eyehead{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;font-size:13px;margin-bottom:6px}.eyehead b{font-family:"IBM Plex Sans Condensed",sans-serif}.chip{display:inline-block;font-family:"IBM Plex Mono",monospace;font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;padding:3px 9px;border-radius:3px;font-weight:500}.chip.pass{background:var(--pass-bg);color:var(--pass)}.chip.cond{background:var(--cond-bg);color:var(--cond)}.chip.fail{background:var(--fail-bg);color:var(--fail)}.was{color:var(--ink-3);font-size:12px}.eye{width:100%;height:auto;display:block}
footer{margin-top:44px;padding-top:16px;border-top:1px solid var(--rule);font-family:"IBM Plex Mono",monospace;font-size:12px;color:var(--ink-3);display:flex;flex-wrap:wrap;gap:8px 28px}
"""

JS = r"""
const VT = {pass:'Signed off', cond:'Conditional', fail:'Not ready'};
const tl = document.getElementById('tl');
tl.style.gridTemplateColumns = '110px repeat(' + builds.length + ',1fr)';
tl.insertAdjacentHTML('beforeend', '<div class="h"></div>' + builds.map((b,i)=>`<div class="h${i===builds.length-1?' latest':''}">${b.date}<b>${b.label}</b></div>`).join(''));
for (const [name, bd] of Object.entries(boards)) {
  tl.insertAdjacentHTML('beforeend', `<div class="b">${name}</div>` + bd.rows.map((r, i) => {
    if (!r) return '<div class="cell none"><span class="v">not in this build</span></div>';
    const d = [];
    if (r.pair_zdiff != null) d.push(`pair ${Math.round(r.pair_zdiff)} Ω`);
    if (r.lane_worst_mm != null) d.push(`lane ${r.lane_worst_mm.toFixed(2)} mm`);
    d.push(`${r.open} open`);
    // changed vs the previous build: verdict, open count, or any charted metric
    const q = i > 0 ? bd.rows[i-1] : null;
    const key = x => x ? [x.verdict, x.open, Math.round(x.pair_zdiff||0), (x.lane_worst_mm||0).toFixed(2), Math.round(100*(x.above_neck||0))].join('|') : '';
    const changed = q && key(q) !== key(r);
    const what = changed ? ' title="changed since the previous build"' : '';
    return `<div class="cell ${r.verdict}${changed ? ' changed' : ''}"${what}><span class="v">${VT[r.verdict]}${changed ? ' ▲' : ''}</span><span class="d">${d.join(' · ')}</span></div>`;
  }).join(''));
}
function chart(id, get, opts) {
  const svg = document.getElementById(id); const W=520, H=240, L=44, R=14, T=14, B=34;
  const n = builds.length, xs = builds.map((_,i)=> n>1 ? L + i*(W-L-R)/(n-1) : (L+W-R)/2);
  const ymin = opts.min, ymax = opts.max, log = !!opts.log;
  const y = v => { const t = log ? (Math.log(v)-Math.log(ymin))/(Math.log(ymax)-Math.log(ymin)) : (v-ymin)/(ymax-ymin); return T + (H-T-B)*(1-Math.max(0,Math.min(1,t))); };
  let s = '';
  if (opts.band) s += `<rect x="${L}" y="${y(opts.band[1])}" width="${W-L-R}" height="${y(opts.band[0])-y(opts.band[1])}" fill="var(--band)"/>`;
  (opts.ticks||[]).forEach(t => { s += `<line x1="${L}" x2="${W-R}" y1="${y(t)}" y2="${y(t)}" stroke="var(--grid)"/><text x="${L-6}" y="${y(t)+4}" text-anchor="end" font-size="10" fill="var(--ink-3)" font-family="IBM Plex Mono,monospace">${t}</text>`; });
  (opts.lines||[]).forEach(t => { s += `<line x1="${L}" x2="${W-R}" y1="${y(t.v)}" y2="${y(t.v)}" stroke="var(--copper)" stroke-dasharray="4 3"/><text x="${W-R}" y="${y(t.v)-4}" text-anchor="end" font-size="10" fill="var(--copper)" font-family="IBM Plex Mono,monospace">${t.l}</text>`; });
  builds.forEach((b,i)=> s += `<text x="${xs[i]}" y="${H-12}" text-anchor="middle" font-size="10" fill="var(--ink-3)" font-family="IBM Plex Mono,monospace">${b.label.slice(0,7)}</text>`);
  for (const [name, bd] of Object.entries(boards)) {
    const pts = bd.rows.map((r,i)=> { const v = r ? get(r) : null; return v==null ? null : [xs[i], y(log ? Math.max(v, ymin) : v)]; });
    let path = '', prev = null;
    pts.forEach(p=>{ if(!p){prev=null;return;} path += (prev? ' L':' M') + p[0]+' '+p[1]; prev=p; });
    s += `<path d="${path}" fill="none" stroke="${bd.color}" stroke-width="2.2" stroke-linejoin="round"/>`;
    pts.forEach((p,i)=>{ if(!p) return; const prev = i>0 && pts[i-1] ? pts[i-1][1] : null; const ch = prev!==null && Math.abs(prev-p[1])>0.5; s += ch ? `<circle cx="${p[0]}" cy="${p[1]}" r="6" fill="none" stroke="${bd.color}" stroke-width="2"/><circle cx="${p[0]}" cy="${p[1]}" r="3" fill="${bd.color}"/>` : `<circle cx="${p[0]}" cy="${p[1]}" r="3.6" fill="${bd.color}"/>`; });
    const last = pts.filter(Boolean).slice(-1)[0]; if (last) s += `<text x="${last[0]+7}" y="${last[1]+4}" font-size="11" font-weight="600" fill="${bd.color}" font-family="IBM Plex Sans Condensed,sans-serif">${name}</text>`;
    if (opts.second) {  // a second series per board, dashed (the measured counterpart)
      const p2 = bd.rows.map((r,i)=> { const v = r ? opts.second(r) : null; return v==null ? null : [xs[i], y(log ? Math.max(v, ymin) : v)]; });
      let d2 = '', pv = null; p2.forEach(p=>{ if(!p){pv=null;return;} d2 += (pv? ' L':' M') + p[0]+' '+p[1]; pv=p; });
      s += `<path d="${d2}" fill="none" stroke="${bd.color}" stroke-width="2" stroke-dasharray="5 4"/>`;
      p2.forEach(p=>{ if(p) s += `<rect x="${p[0]-3.5}" y="${p[1]-3.5}" width="7" height="7" fill="var(--paper)" stroke="${bd.color}" stroke-width="2"/>`; });
    }
  }
  svg.innerHTML = s;
}
chart('c1', r=>r.open, {min:0,max:7,ticks:[0,2,4,6],band:[0,0.001]});
chart('c2', r=>r.pair_zdiff, {min:60,max:200,ticks:[80,100,120,140,160,180],band:[80,140],lines:[{v:80,l:'target 80'}]});
chart('c3', r=>r.lane_worst_mm, {min:0.1,max:20,log:true,ticks:[0.1,1,4,12],band:[0.1,4],lines:[{v:12,l:'spec 12'},{v:4,l:'target 4'}]});
chart('c4', r=>r.above_neck==null?null:100*r.above_neck, {min:0,max:100,ticks:[0,25,50,75,100],band:[60,100]});
const eyeH = r => (r.eyes && r.eyes.DQ) ? r.eyes.DQ.h_mv : null;
const eyeW = r => (r.eyes && r.eyes.DQ) ? r.eyes.DQ.w_ui : null;
const measH = r => { const m = r.eyes && r.eyes.DQ && r.eyes.DQ.measured; if (!m) return null; const v = Object.values(m); return v.length ? Math.min(...v.map(x=>x.h_mv)) : null; };
const measW = r => { const m = r.eyes && r.eyes.DQ && r.eyes.DQ.measured; if (!m) return null; const v = Object.values(m); return v.length ? Math.min(...v.map(x=>x.w_ui)) : null; };
chart('c5', eyeH, {min:0,max:800,ticks:[0,200,400,600,800],band:[140,800],lines:[{v:140,l:'mask 140 mV'}], second: measH});
chart('c6', eyeW, {min:0,max:1,ticks:[0,0.25,0.5,0.75,1],band:[0.22,1],lines:[{v:0.22,l:'mask 0.22 UI'}], second: measW});
// eyes over builds: rows = boards, columns = builds; the measured DQ eye when present, else the bounce eye
const grid = document.getElementById('eyegrid');
grid.style.gridTemplateColumns = '110px repeat(' + builds.length + ',1fr)';
grid.insertAdjacentHTML('beforeend', '<div class="h"></div>' + builds.map((b,i)=>`<div class="h${i===builds.length-1?' latest':''}">${b.date}<b>${b.label}</b></div>`).join(''));
for (const [name, bd] of Object.entries(boards)) {
  let cells = '';
  let prevKey = null;
  bd.rows.forEach(r => {
    const g = r && r.eyes && r.eyes.DQ;
    if (!g) { cells += '<div class="cell none"><span class="v">no eye</span></div>'; prevKey = null; return; }
    const m = Object.values(g.measured||{}).sort((a,b)=>a.h_mv-b.h_mv)[0];
    const use = m && m.svg ? m : g;
    const key = `${Math.round(use.h_mv)}|${use.w_ui.toFixed(2)}|${use.net}`;
    const changed = prevKey !== null && key !== prevKey; prevKey = key;
    const ok = use.h_mv >= 140 && use.w_ui >= 0.22;
    cells += `<div class="cell ${ok?'pass':'fail'}${changed?' changed':''}" style="padding:6px"><span class="v">${ok?'PASS':'FAIL'} · ${m && m.svg ? 'measured' : 'bounce'} · ${use.net.replace('LPDDR4_','')}</span>${use.svg||''}<span class="d">${Math.round(use.h_mv)} mV × ${use.w_ui.toFixed(2)} UI vs mask 140 mV × 0.22 UI</span></div>`;
  });
  grid.insertAdjacentHTML('beforeend', `<div class="b">${name}</div>` + cells);
}
// the latest build's eyes
const last = builds.length - 1; const eg = document.getElementById('eyes'); let eh = '';
for (const [name, bd] of Object.entries(boards)) {
  const r = bd.rows[last]; if (!r || !r.eyes) continue;
  for (const [grp, g] of Object.entries(r.eyes)) {
    if (g.svg) eh += `<div class="eyebox"><div class="eyehead"><b>${name} · ${grp}</b> <span class="was">bounce · ${g.net}</span> <span class="chip ${g.h_mv>=140&&g.w_ui>=0.22?'pass':'fail'}">${g.h_mv>=140&&g.w_ui>=0.22?'PASS':'FAIL'} · ${Math.round(g.h_mv)} mV × ${g.w_ui.toFixed(2)} UI</span></div>${g.svg}</div>`;
    for (const [k, m] of Object.entries(g.measured||{})) if (m.svg) eh += `<div class="eyebox measured"><div class="eyehead"><b>${name} · ${grp}</b> <span class="was">field solver${m.aggressors?` + ${m.aggressors} aggressor(s)`:', no crosstalk'} · ${m.net}</span> <span class="chip ${m.h_mv>=140&&m.w_ui>=0.22?'pass':'fail'}">${m.h_mv>=140&&m.w_ui>=0.22?'PASS':'FAIL'} · ${Math.round(m.h_mv)} mV × ${m.w_ui.toFixed(2)} UI</span></div>${m.svg}</div>`;
  }
}
eg.innerHTML = eh || '<p class="sub">no eyes recorded for the latest build</p>';
document.getElementById('lg').innerHTML = Object.entries(boards).map(([n,b])=>`<span><i style="background:${b.color}"></i>${n}</span>`).join('') + '<span><i style="background:var(--band)"></i>rule satisfied</span><span>▲ / thick border / ringed point = changed since the previous build</span><span>dashed line, square points = measured (field solver)</span>';
document.getElementById('ev').innerHTML = builds.map(b=>`<div class="e"><div class="k">${b.date}<b>${b.label}</b></div><div>${b.note}</div></div>`).join('');
"""


def git_subject(label):
    try:
        return subprocess.run(['git', 'log', '-1', '--format=%s', label.split()[0]], capture_output=True, text=True,
                              cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
    except Exception:
        return ''


def main():
    args = sys.argv[1:]
    inp = 'docs/signoff-history.json'; out = 'docs/signoff-progress.html'
    i = 0
    while i < len(args):
        if args[i] == '-i': inp = args[i + 1]; i += 2
        elif args[i] == '-o': out = args[i + 1]; i += 2
        else: i += 1
    hist = json.load(open(inp))
    names = []
    for h in hist:
        for n in h['boards']:
            if n not in names: names.append(n)
    names.sort(key=lambda n: -int(n[:-1]) if n[:-1].isdigit() else 0)
    builds = [{'label': h['label'], 'date': h['date'][5:], 'note': html.escape(h.get('note') or git_subject(h['label']) or '')} for h in hist]
    boards = {n: {'color': COLORS[k % len(COLORS)], 'rows': [h['boards'].get(n) for h in hist]} for k, n in enumerate(names)}
    latest = hist[-1] if hist else {'label': '-', 'date': '-'}
    E = html.escape
    page = f"""<meta charset="utf-8"><title>Sign-off Progress</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>{CSS}</style>
<div class="page">
<header><div><div class="eyebrow">Router campaign · progress</div><h1 style="margin-top:8px">Sign-off Progress</h1>
<p class="lede">The boards against the sign-off bar, build by build, from the sign-off pages recorded by make signoff. Verdicts and conditions are derived from the gates; impedance is the field solver where measured.</p></div>
<div class="meta"><div><span>latest</span> <b>{E(latest['label'])} · {E(latest['date'])}</b></div><div><span>boards</span> <b>{E(' · '.join(names))}</b></div></div></header>
<section><h2>Verdicts over builds</h2><p class="sub">Signed off = no open condition. Conditional = every gate in spec and a legal ODT bin for every group. Not ready = a hard miss: DRC/ERC, a spec miss, or a member outside every legal bin.</p><div class="panel"><div class="tl" id="tl"></div></div></section>
<section><h2>How the numbers moved</h2><p class="sub">One metric per chart across builds, one line per board; the shaded band is where the sign-off rule is satisfied.</p>
<div class="charts">
<div class="panel chart"><h3>Open SI conditions</h3><p class="cap">count per board — zero is signed off</p><svg id="c1" viewBox="0 0 520 240"></svg></div>
<div class="panel chart"><h3>DQS0 pair Z<sub>diff</sub> (field solver)</h3><p class="cap">Ω — band: within 15 % of a legal 2×ODT bin (80–140 Ω)</p><svg id="c2" viewBox="0 0 520 240"></svg></div>
<div class="panel chart"><h3>Worst lane skew</h3><p class="cap">mm — target 4, spec 12 (log scale)</p><svg id="c3" viewBox="0 0 520 240"></svg></div>
<div class="panel chart"><h3>Member copper above the class neck</h3><p class="cap">% of DDR member length wider than the neck</p><svg id="c4" viewBox="0 0 520 240"></svg></div>
<div class="panel chart"><h3>Worst eye height (DQ, bounce · measured)</h3><p class="cap">mV, peak-distortion opening — mask 140 mV (LPDDR4)</p><svg id="c5" viewBox="0 0 520 240"></svg></div>
<div class="panel chart"><h3>Worst eye width (DQ, bounce · measured)</h3><p class="cap">UI — mask 0.22 UI</p><svg id="c6" viewBox="0 0 520 240"></svg></div>
</div><div class="legend" id="lg"></div></section>
<section><h2>Eyes over builds</h2><p class="sub">One row per board, one column per build: the worst DQ eye of that build — the measured (field-solver) eye where a slice existed, the bounce eye otherwise. Amber box: the receiver mask at V<sub>ref</sub>. A thick border marks a change from the previous build.</p><div class="panel"><div class="tl" id="eyegrid"></div></div></section>
<section><h2>All groups at the latest build</h2><p class="sub">Worst net per group (DQ, DQS, CA) and board, bounce and measured.</p><div class="eyes" id="eyes"></div></section>
<section><h2>What each build changed</h2><div class="panel events" id="ev"></div></section>
<footer><span>latest {E(latest['label'])}</span><span>scripts/progress.py · docs/signoff-history.json</span></footer>
</div>
<script>
const builds = {json.dumps(builds)};
const boards = {json.dumps(boards)};
{JS}
</script>
"""
    open(out, 'w').write(page)
    print('progress ->', out, f'({len(hist)} build(s), {len(names)} board(s))')


if __name__ == '__main__':
    main()
