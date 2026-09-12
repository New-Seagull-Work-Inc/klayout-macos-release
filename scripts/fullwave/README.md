# Full-wave impedance validation (openEMS via Antmicro's gerber2ems)

A field-solver check of what the router actually laid: one net (or one
pair) is sliced out of a finished board with its reference planes, meshed
and solved in openEMS, and its characteristic impedance is extracted
from the S-parameters. It is a *validation* tool — ~10 minutes per net —
not part of the routing loop. Its first use (2026-09-10) showed the
router's stripline model reading 4–10 ohm low on inner layers, pairs
running 92–112 ohm where the census said 80–89, and the 6-layer board's
pairs at ~200 ohm; those numbers drove the ODT judge in si_report.py
and the passives decision (see docs/ddr-lane-matching.md).

## Chain
- **openEMS** (FDTD, C++) + CSXCAD, built from source with the Python
  bindings into `~/opt/openEMS` (venv `~/opt/openEMS/venv`, python3.14).
- **gerber2ems** (Antmicro) in that venv: gerbers → geometry → openEMS
  runs → S-parameters. One patch: `simulation.py` normalises S to the
  declared 50 ohm port impedance (`CalcPort(..., ref_impedance=...)`) —
  the probe-derived line impedance is unreliable on 0.4 mm ports over
  0.1–0.3 mm traces.
- **si-wrapper** (Antmicro kicad-si-simulation-wrapper) on KiCad's own
  Python 3.9 (`~/Library/Python/3.9/bin/si-wrapper`): the slicer only.
  Patched for KiCad 10 / Python 3.9, and its entry point ends with
  `os._exit()` — pcbnew's SWIG objects crash in interpreter finalisation
  on macOS (1 in 3 runs) once the slice is already written.
- `gerbv` (Homebrew) renders the gerbers for the mesher.

## Recipe (what the scripts do, and why each step exists)
`sweep.sh` runs everything below for every board and net; `run_slice.sh`
is one slice.
1. Workspace `~/opt/fullwave/<board>/` holds the board (`.kicad_pcb`,
   `.kicad_pro` with the `80Ohm-ddr-diff` / `50Ohm-ddr-se` netclasses the
   wrapper needs, `init.json`, `net_configs/<net>.json`). The slicer runs
   once per net into `pristine/`; every attempt works on a copy in `slices/`.
2. `prep_slice.py <slice>`: sets the aux origin at the board's lower-left
   corner and exports gerbers (X2 net attributes on — the mesher refines
   around the nets of interest), drill and pos **against that origin**
   (gerber2ems places copper relative to the corner but takes port and
   drill coordinates raw); writes `fab/stackup.json` from the board's own
   stackup block; finds the net's true ends (degree-1 vertices, a via
   touched on one layer is a terminal), walks the route across layers,
   vias and arcs; appends the board's GND vias inside the slice to the
   drill so the reference planes are tied (the slicer strips them — an
   untied plane pair traps the common mode); writes `ports_runs.json`.
3. `gerber2ems -g` renders the geometry.
4. `place_feeds.py <slice>`: puts each port's feed where the reference
   plane is solid under the feed resistor and the probe plane — the via
   antipads and the ball-field perforation are holes, and a feed over a
   hole is an open port (the first three runs); one common distance per
   pair end; snaps the port across-axis onto the rendered copper centre
   line (the edge-stroke crop shifts the frame ~0.05 mm — fatal on a
   75 um trace) and shifts the drill the same way; sets each port's
   layer/plane from where the feed landed; truncates the trace behind the
   feed (a port mid-route leaves an open stub); re-exports gerbers.
5. The stack is trimmed to F.Cu … one plane below the deepest layer the
   net runs on (physically complete for a stripline, 3× fewer cells).
6. `gerber2ems -a` simulates (one run per excited port) and post-processes.
7. `readout.py` / `line_z.py` / `mixed_mode.py`: characteristic impedance
   from the two-port ABCD matrix (Zc = sqrt(B/C), length-independent;
   symmetric-line assumption — use 0.2–2 GHz), mixed-mode SDD/SCC terms,
   and a SUSPECT flag when a port did not couple (no transmission or
   |S11| ≈ 0 dB). `recalc_s.py` re-derives S from stored probe data
   without re-simulating (after a normalisation change).

## Reading the numbers
- A converged run decays to ≤ −40 dB; a plateau at −15…−20 dB means a
  port is not connected or a plane is floating.
- Mesh: default (`inter_layers 4`, 50 um at copper) vs refined
  (8 / 25 um, 5× cells) agreed within 2 ohm on the 12L DQS0 pair; the
  refined run is passive (S21 < 0 dB), the default shows +1 dB.
- Pair legs terminate per leg, so Z_diff ≈ 2·Z_se when the pair is not
  coupled; NEXT ≈ −15 dB is tight coupling, −25…−35 dB loose/none.
- Exact zero-thickness symmetric stripline (Cohn, K(k)/K(k')) is a good
  third opinion: 0.1424 mm → 48 ohm, 0.1637 → 44.7 on the 12L In2 stack.
