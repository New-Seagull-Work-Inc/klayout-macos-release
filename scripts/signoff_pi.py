#!/usr/bin/env python3
"""signoff_pi.py — the power-integrity sign-off page for one or more boards.

Reads <board>-klayout-result.json per output directory: the "pi" block
(one row per rail: declared load, IPC-2221 ampacity width vs the width
laid, worst IR drop vs budget, the worst load, plane-fed / unmodeled
status) and the plane facts (stitch bonds), plus DRC/ERC. Writes
signoff-pi.html in the sign-off page design. Conditions are derived:
a rail over its drop budget, a rail laid narrower than its ampacity width,
a rail with no supply/load pads to model, no rails declared at all.
Usage: python3 scripts/signoff_pi.py OUT_DIR [OUT_DIR ...] [-o signoff-pi.html] [--label BUILD]"""
import sys, os, json, html, time, subprocess

REMEDY = {
    'over':      'IR drop over budget: widen the rail (ampacity pass), add a plane (--plane NET:LAYER), or move the supply.',
    'narrow':    'Rail laid below its ampacity width: room on the rail\'s layer — the field-box / halo work, or a plane.',
    'unmodeled': 'IR drop not modeled: declare the supply pad and load pads with currents in power.json.',
    'norails':   'No rails declared: write power.json (rail, supply pad, loads with mA, drop budget) or add a rated fuse for the inference.',
    'drc':       'DRC/ERC must be zero.',
}


def read_dir(d):
    res = None
    for f in os.listdir(d):
        if f.endswith('-klayout-result.json'):
            res = json.load(open(os.path.join(d, f)))
    if not res:
        raise SystemExit(f'{d}: no *-klayout-result.json')
    si = res.get('si') or {}
    layers = si.get('copper_layers') or 0
    return {'dir': d, 'name': os.path.basename(os.path.abspath(d)), 'res': res,
            'short': f'{layers}L' if layers else os.path.basename(os.path.abspath(d)), 'layers': layers}


def conditions(b):
    res = b['res']; conds = []
    drc = res.get('drc', {}); erc = res.get('erc') or {}
    if drc.get('error_violations') or drc.get('warnings') or drc.get('unconnected_items') or erc.get('errors') or erc.get('warnings'):
        conds.append(('DRC/ERC', f"{drc.get('error_violations',0)} / {drc.get('warnings',0)} / {drc.get('unconnected_items',0)}", 'all zero', REMEDY['drc']))
    pi = res.get('pi')
    if not pi or not pi.get('rails'):
        conds.append(('Rails', 'none declared', 'every supply rail with its loads and budget', REMEDY['norails']))
        return conds
    for r in pi['rails']:
        if r['status'] == 'over':
            conds.append((f"{r['net']} IR drop", f"{r['ir_drop_mv']:.1f} mV at {r['worst_load']}", f"<= {r['budget_mv']:.0f} mV", REMEDY['over']))
        if r['ampacity_width_mm'] > r['laid_width_mm'] + 1e-6 and r['status'] != 'plane':
            conds.append((f"{r['net']} width", f"{r['laid_width_mm']:.3f} mm laid", f">= {r['ampacity_width_mm']:.3f} mm for {r['load_mA']:.0f} mA", REMEDY['narrow']))
        if r['status'] == 'unmodeled' and r['load_mA'] > 0:
            conds.append((f"{r['net']} IR drop", 'not modeled', 'measured against a budget', REMEDY['unmodeled']))
    return conds


def verdict(conds):
    if not conds:
        return 'pass', 'Signed off'
    hard = any(c[0] == 'DRC/ERC' or 'IR drop' in c[0] and 'mV' in c[1] for c in conds)
    return ('fail', 'Not ready') if hard else ('cond', 'Conditional')


CSS = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'signoff.py')).read()
CSS = CSS[CSS.index('CSS = """') + 9:CSS.index('"""', CSS.index('CSS = """') + 9)]


def render(boards, label):
    E = html.escape
    boards = sorted(boards, key=lambda b: -b['layers'])
    for b in boards:
        b['conds'] = conditions(b); b['verdict'] = verdict(b['conds'])
    counts = {'pass': 0, 'cond': 0, 'fail': 0}
    for b in boards: counts[b['verdict'][0]] += 1
    summary = ', '.join(f"{v} {k}" for k, v in (('signed off', counts['pass']), ('conditional', counts['cond']), ('not ready', counts['fail'])) if v)
    h = ['<meta charset="utf-8">', '<title>PI Sign-off</title>',
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">',
         f'<style>{CSS}</style><div class="page">',
         f'<header><div><div class="eyebrow">Router sign-off · power integrity · {E(", ".join(b["short"] for b in boards))}</div><h1 style="margin-top:8px">PI Sign-off</h1>'
         f'<p class="lede">{E(summary)}. Each rail is judged on what the router laid: IPC-2221 ampacity width against the width achieved, and the nodal IR-drop solve over the routed copper against the rail\'s budget. A rail poured as a plane is not modeled (plane spreading dwarfs trace resistance); a rail without supply and load pads cannot be.</p></div>'
         f'<div class="meta"><div><span>build</span> <b>{E(label)}</b></div><div><span>date</span> <b>{time.strftime("%Y-%m-%d")}</b></div></div></header>']
    h.append('<div class="verdicts">')
    for b in boards:
        v, vt = b['verdict']; pi = b['res'].get('pi') or {}
        rails = pi.get('rails', [])
        first = b['conds'][0] if b['conds'] else None
        blurb = 'No open conditions.' if not first else f"{len(b['conds'])} open: {first[0]} {first[1]} → {first[2]}" + (' …' if len(b['conds']) > 1 else '')
        stat = f"{len(rails)} rail(s): " + ', '.join(f"{r['net']} {r['status']}" for r in rails) if rails else 'no rails declared'
        h.append(f'<div class="card"><div class="board"><h3>{E(b["short"])}</h3><span class="chip {v}">{E(vt)}</span></div><p>{E(blurb)}</p><div class="settings">{E(stat)}<br>plane bonds {pi.get("stitch_bonds", b["res"].get("stitch_bonds", 0))}</div></div>')
    h.append('</div>')
    # rails table: one row per (board, rail)
    h.append('<section><h2>Rails against the gates</h2><div class="tablewrap"><table><thead><tr><th>Board · rail</th><th>Load</th><th>Ampacity width → laid</th><th>IR drop → budget</th><th>Worst load</th><th>Status</th></tr></thead><tbody>')
    for b in boards:
        pi = b['res'].get('pi') or {}
        rails = pi.get('rails', [])
        if not rails:
            h.append(f'<tr><th>{E(b["short"])}</th><td colspan="5" class="was">no rails declared (power.json) — IR drop and ampacity not judged</td></tr>')
            continue
        for r in rails:
            st = r['status']
            wcls = 'ok' if r['laid_width_mm'] + 1e-6 >= r['ampacity_width_mm'] or st == 'plane' else 'warn'
            dcls = {'ok': 'ok', 'over': 'bad', 'report': 'warn', 'plane': 'ok', 'unmodeled': 'warn'}[st]
            drop = f"{r['ir_drop_mv']:.1f} mV → {r['budget_mv']:.0f} mV" if st in ('ok', 'over') else (f"{r['ir_drop_mv']:.1f} mV, no budget" if st == 'report' else ('plane-fed' if st == 'plane' else 'not modeled'))
            h.append(f'<tr><th>{E(b["short"])} · {E(r["net"])}</th><td class="num">{r["load_mA"]:.0f} mA · {r["loads"]} load(s)</td>'
                     f'<td class="num {wcls}">{r["ampacity_width_mm"]:.3f} → {r["laid_width_mm"]:.3f} mm</td><td class="num {dcls}">{E(drop)}</td>'
                     f'<td>{E(r["worst_load"] or "—")}</td><td><span class="chip {"pass" if st in ("ok","plane") else ("fail" if st == "over" else "cond")}">{E(st)}</span></td></tr>')
    h.append('</tbody></table></div></section>')
    h.append('<section><h2>Conditions for sign-off</h2><div class="conds">')
    for b in boards:
        v, vt = b['verdict']
        h.append(f'<div class="cond-block"><h3>{E(b["short"])} <span class="chip {v}">{E(vt)}</span></h3>')
        h.append('<p class="now">No open conditions.</p>' if not b['conds'] else '<ol>' + ''.join(f'<li><span class="now">{E(c[0])}: {E(c[1])}</span> → <span class="need">{E(c[2])}</span><span class="fix">{E(c[3])}</span></li>' for c in b['conds']) + '</ol>')
        h.append('</div>')
    h.append('</div></section>')
    h.append('<section><h2>How the numbers were produced</h2><div class="methods"><dl>'
             '<dt>Rails</dt><dd>power.json declares each rail, its supply pad, its load pads with currents and an IR-drop budget; without it the router infers currents from a rated fuse and connector ratings, and reports only.</dd>'
             '<dt>Ampacity</dt><dd>IPC-2221 external-layer width for the declared current at the stack\'s copper thickness and a 10 °C rise; the router widens rails to it where the copper allows and records the width it achieved.</dd></dl><dl>'
             '<dt>IR drop</dt><dd>Nodal solve over the routed segments and vias from the supply pad to each load; the worst drop is gated against the budget and the rail is widened and re-routed while over it (four rounds).</dd>'
             '<dt>Not yet judged</dt><dd>PDN impedance vs frequency (decoupling) and plane current density — the next measurements for this page.</dd></dl></section>')
    h.append(f'<footer><span>build {E(label)}</span><span>scripts/signoff_pi.py</span></footer></div>')
    return '\n'.join(h)


def main():
    args = sys.argv[1:]; out = 'signoff-pi.html'; label = None; dirs = []
    i = 0
    while i < len(args):
        if args[i] == '-o': out = args[i + 1]; i += 2
        elif args[i] == '--label': label = args[i + 1]; i += 2
        else: dirs.append(args[i]); i += 1
    if not dirs:
        raise SystemExit(__doc__)
    if not label:
        try:
            label = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip() or 'unlabelled'
        except Exception:
            label = 'unlabelled'
    boards = [read_dir(d) for d in dirs]
    open(out, 'w').write(render(boards, label))
    for b in boards:
        print(f"{b['short']:5s} {b['verdict'][1]:12s} {len(b['conds'])} condition(s)")
    print('signoff-pi ->', out)


if __name__ == '__main__':
    main()
