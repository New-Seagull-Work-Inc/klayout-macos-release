> **Binary release** — prebuilt `klayout` and `kplace`
> executables for macOS on Apple Silicon (arm64).
> Links against the system libSystem only; no other dependencies.
> Other platforms and distributions: build from the source
> repository when authorized by Seagull Work, Inc.
> **This package contains executables, one example
> KiCad board and the fab library — no source code is
> included or implied.**
> The `klayout` and `kplace` binaries, this README, the
> `LICENSE`, the `example/` board they route and the `fab/`
> folder (the fabs' published capabilities and stackups,
> JSON) are the entire distribution: there is no source tree, no
> Makefile, and nothing here that can be compiled,
> rebuilt, or modified. The example is design input for
> the tool, not program source. The binaries are the only
> form of the program you receive.
> Nothing to build here: route the included board with
> `./klayout --input-dir example --output-dir out --resize-pcb`.
> Keep both binaries in the same directory: klayout invokes
> kplace for auto-placement and re-invokes itself for parallel
> attempts (install on PATH or run from their directory).
> kicad-cli from KiCad 10, found via PATH or KICAD_CLI,
> enables the DRC acceptance gates, zone-fill verification
> for the pour stitching, and the fab exports (gerbers,
> drill, pick-and-place, IPC-D-356).
> The `fab/` folder is the fab library the impedance model and the
> fab targeting read; it is described below.
> **Trial software, no warranty** — free to evaluate, and
> the layouts it produces are yours to use for anything,
> commercially included. Nothing it outputs is guaranteed
> or has been reviewed by an engineer: a clean DRC report
> is this program grading its own work, not an assurance
> that a board is manufacturable or safe. Verify every
> layout before you build it. Full terms in `LICENSE`.
> The build instructions carried by the source repository are
> omitted from this README: there is nothing here to compile.

# klayout — automatic placement and routing for KiCad boards

**Trial software.** This package is provided for evaluation under the
terms of the `LICENSE` file beside it. Read it before you use the
program; the layouts it produces are yours, the program is not.

## What it does

`klayout` takes a KiCad project — schematic, unrouted board, footprints —
and delivers a placed and routed board:

- **Places** the parts (`kplace`, invoked automatically) and **routes**
  every net on the layer count you ask for, through vias, with copper
  pours for the ground and power planes it reserves.
- **Signal integrity built in.** Differential pairs are detected from
  the net names and routed as coupled pairs to their standard's
  impedance and skew budget (USB, PCIe, MIPI CSI/DSI, LVDS, Ethernet).
  DDR interfaces (DDR4, LPDDR4) are detected the same way: each byte
  lane is routed as a bundle on one inner layer with its strobe pair,
  length-matched to the strobe, at the standard's single-ended and
  differential impedance on the fab's real stackup.
- **Checks its own work.** Every board goes through KiCad's own DRC
  and ERC (`kicad-cli`); the verdict is `clean` only at zero errors,
  zero warnings, zero unconnected items, zero schematic-parity findings.
- **Tries several placements in parallel** and keeps the one that
  meets every gate, printing a table of the trials so you can see why.
- **Shows you the work as it happens** — the PCB Layout Cinema, a live
  view in your browser (below).
- **Delivers the fab package**: gerbers, drill files, pick-and-place,
  IPC-D-356 netlist, unless you ask it not to.

## Quick start

```
./klayout --input-dir my-board --output-dir my-board-routed --layers 4
```

- `--input-dir` — a folder holding the KiCad project: the `.kicad_pcb`
  (parts may be unplaced; the design rules come from its `.kicad_pro`),
  the `.kicad_sch`, and the footprint / symbol libraries it uses.
- `--output-dir` — where the routed project is written. It is created.
- `--layers` — copper layers to route on (2, 4, 6, 8, 10, 12 …; `1`
  for a single-sided board with no vias).

Keep `klayout` and `kplace` in the same directory: `klayout` runs
`kplace` for placement and re-runs itself for the parallel attempts.

### What you get

In the output directory:

- `<board>.kicad_pcb` — the placed and routed board, opening directly in
  KiCad, with the copper pours filled and the fab's stackup written in.
- `<board>-klayout-result.json` — the verdict: DRC and ERC counts,
  `clean`, routing failures, every signal-integrity gate.
- `klayout.log` — everything the run printed, including the trial table
  and the impedance and skew reports.
- `gerber-drill/` — gerbers, drill files, pick-and-place and IPC-D-356
  (omit with `--no-fab`).

### The PCB Layout Cinema

Every run serves a live view of the routing and opens it in your default
browser (Safari, Chrome and Firefox all work):

```
http://localhost:8765/
```

One panel per placement attempt, drawn as it routes — the copper laid
since the last frame in white — with completion bars per signal class
(differential pairs and DDR, other signals, power), the current stage,
the elapsed time, and a scrub bar to step back through the run's frames.
If the page does not open by itself, open that address (or
`http://127.0.0.1:8765/`) while the run is going. To watch a finished
run again:

```
./klayout --watch my-board-routed
```

`KLAYOUT_NO_BROWSER=1` keeps the browser closed (the server still runs),
`KLAYOUT_DASH_PORT=NNNN` picks another port, `KLAYOUT_NO_DASH=1` turns
the Cinema off.

## Other options

All options are `klayout --help`. The ones you are likely to use:

| option | meaning |
|---|---|
| `--plane NET:LAYER` | pour a copper zone for that net on that layer (`--plane GND:In2.Cu`); repeatable. Without it the tool reserves ground and power layers itself from the layer count. |
| `--stack SPEC` | the stackup by role, outermost first, e.g. `SIG-GND-SIG-GND-PWR:3V3-SIG`; sets `--layers` and the planes at once. |
| `--place-tries N` | placement attempts (default 8; four run at a time, `KLAYOUT_PARALLEL` changes that). The first attempt to meet every gate wins; `--not-first-win` keeps the lowest-numbered one instead, for reproducible output. |
| `--seed N` | base placement seed (default 1) — same command, same board, same result. |
| `--resize-pcb` | after routing, shrink the outline to the smallest DRC-legal rectangle around the design. |
| `--grid`, `--track`, `--clearance`, `--via-size`, `--via-drill`, `--edge-clearance`, `--hole-clearance` (mm) | override the design rules read from the `.kicad_pro`. |
| `--fab NAME` | the board house you will use: its floors become the minimum for every rule and its stackup is written into the board (see the fab library below). |
| `--fab-dir DIR` | where the fab library is (default: `fab/` beside the binaries; `KLAYOUT_FAB_DIR` does the same; `none` runs without it). |
| `--no-fab` | skip the gerber / drill / pick-and-place package. |
| `--si-layer-min F` | the share of a DDR lane member's copper that must stay on its home layer (default 0.90); `--si-any-layer` lifts the home-layer rule altogether. |
| `--eight-angles-routing` | 90°/45° turns only, no any-angle shortcuts. Every board is tried this way first; only a board that ends below its gates is retried any-angle, and a DDR board that is complete and DRC-clean stays octilinear. |
| `--arc-wiggles`, `--sine-wiggles` | the shape of length-matching meanders: arc accordions or sinusoids instead of rectangular bumps. |
| `--no-widen` | ignore `power.json`: route power rails at the class width instead of their IPC-2221 ampacity width. |
| `--watch DIR` | serve the PCB Layout Cinema for a finished run. |
| `--version` | print the build revision. |

Environment: `KICAD_CLI=/path/to/kicad-cli` if it is not on your PATH;
`KLAYOUT_OFFLINE=1` to keep the tool from touching the network;
`KLAYOUT_NO_SWEEP=1` to skip the fab sweep (below) when a board ends
below its gates.

## The fab library — the `fab/` folder

Four JSON files, one per board house — `jlcpcb.json`, `osh_park.json`,
`advanced_circuits.json`, `sierra_circuits.json` — holding what each
house **publishes** on its capability and impedance pages:

- the manufacturing floors: minimum track width and spacing, drill,
  via diameter and annular ring, hole-to-hole and board-edge
  clearances, layer counts, board thicknesses, copper weights,
  materials, finishes;
- where the house publishes them, its **impedance-controlled stackups**
  (`"stackups"`): for each layer count the stack from top to bottom —
  copper foils with their weight, cores and prepregs with their
  thickness, material and dielectric constant;
- `source_url` and `retrieved_utc`, so every number can be checked
  against the house's page.

klayout uses the folder three ways:

1. **Target fab** — `--fab NAME` (or a `(fab "NAME")` clause in the
   design file) raises any project rule below that house's floor and
   writes its stackup into the board.
2. **Impedance** — every differential pair and every DDR lane member is
   solved on the declared house's stackup for the board's layer count
   (with none declared, the first house that publishes one; the log
   names it): the microstrip model on the outer layers, the stripline
   model between the planes on the inner ones. The report then measures
   the copper **as laid** — `impedance: target 80 ohm, as laid ~82 ohm,
   91% of the copper within 10%` — rather than restating the solve.
3. **Fab sweep** — when a board ends below its gates, it is re-routed
   under each house's floors and the report names the houses that could
   build it.

Without the folder the tool still routes, but the impedance model falls
back to an assumed stackup and DDR lanes keep the class width; the log
says so. To add a house, drop a JSON file in the same shape as the
others, with the numbers from its public pages and the `source_url`
kept.

## Reading the result

The log ends with the verdict. For a board with differential pairs or
DDR, the **trial table** comes first — one row per placement attempt,
a check or a cross in every gate cell:

```
┌───────┬──────┬────────┬──────────┬───────────┬────────────────┬──────────────────┬──────────────────┬─────────────────┬─────────────────────┬─────────────────────┬────────────────────┐
│ trial │ time │ gates  │ unrouted │ DRC e/w/u │ pair skew mm   │ DQS0 lane skew   │ DQS1 lane skew   │ ADDR/CK skew    │ home layer          │ pairs Z as laid     │ DQS0 lane Z        │
├───────┼──────┼────────┼──────────┼───────────┼────────────────┼──────────────────┼──────────────────┼─────────────────┼─────────────────────┼─────────────────────┼────────────────────┤
│ 1     │ 8:48 │ met ✓  │ 0 ✓      │ 0/0/0 ✓   │ 0.007 / 2.55 ✓ │ 0.174 / 2.05 ✓   │ 0.052 / 2.05 ✓   │ 3.091 / 16.00 ✓ │ 0 miss, worst 93% ✓ │ 81-84 ohm, 91% in ✓ │ 44.1 ohm, 72% in ✗ │
└───────┴──────┴────────┴──────────┴───────────┴────────────────┴──────────────────┴──────────────────┴─────────────────┴─────────────────────┴─────────────────────┴────────────────────┘
```

Skew cells show the worst member against its budget; "home layer" the
lane members below the required share and the worst one's share;
impedance cells the length-weighted impedance of the copper as laid and
how much of it is within 10 % of the target (the check when the mean is
within 10 %). Then:

- `clean: true` in the result file — DRC 0 errors / 0 warnings / 0
  unconnected, schematic parity 0, ERC 0/0, no routing failures. A board
  that routes but is not clean is still written, with `*** NOT CLEAN`
  and the counts in the log.
- **Violations that were already on the input board** are named as such:
  the tool runs the same DRC on the input (read-only) and the final
  message says how many of the reported errors and warnings were there
  before routing and how many the router introduced — and, when nothing
  beyond the input's own findings remains, says so. The result file
  carries `input_drc`, `introduced` and `clean_beyond_input`. A pad
  overlapping its own footprint's hole, a library footprint mismatch,
  an unplaced part's courtyard: those are the board's to fix, not the
  router's.
- The per-pair and per-lane reports above the table: skew, home-layer
  share, impedance as laid, via counts.

KiCad's own DRC is the ground truth; open the board in KiCad or run
`kicad-cli pcb drc` on it yourself to confirm.

## Requirements

- The platform named at the top of this file.
- **KiCad 10** with `kicad-cli` on your PATH (or `KICAD_CLI` set). Without
  it the board still routes, but the DRC / ERC gates, the pour
  verification and the fab package are skipped, and the verdict says so.
- Both binaries in the same directory.

## Limitations

- Through vias only — no blind, buried or micro vias.
- Copper already in the input board is left as it is: a pre-routed pair
  is frozen and reported, not completed.
- One track width and clearance for ordinary nets; pairs, DDR lane
  members and power rails get their own solved widths.
- Trapezoid and custom pad shapes are treated as their bounding circle.
- A differential pair needs equal P and N pad counts (2–8 per member).
- Zones present in the input board are not treated as obstacles; the
  pours klayout emits are.

## License

See `LICENSE`. This is a trial: free to evaluate, no warranty, and
nothing the program outputs has been reviewed by an engineer — a clean
DRC report is the program grading its own work. Verify every layout
before you build it.
