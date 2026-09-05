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

- **Places** the parts (`kplace`, invoked automatically) the way an
  experienced layout engineer would, from the board alone: every chip
  gets its decoupling and its two-pad satellites in rows along the
  edge that carries their pins; chips cluster into functional blocks
  (a regulator and its parts, a charger and its parts) ordered from
  the input connector; a connector's circuit sits at the connector,
  with the USB pair short and straight from the jack. Boards of four
  copper layers and up are placed on both faces from the first
  attempt; two-layer boards start single-sided and go to both faces
  only when no single-sided attempt routes every net.
  `--group-labeling` frames and names each block on the silkscreen
  (`Battery charger (U3)`, `Boost converter (U10)`).
- **Routes** every net on the layer count you ask for, through vias,
  with copper pours for the ground and power planes it reserves, and
  power rails at their IPC-2221 ampacity width.
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
- **Builds to your fab's floors.** `--fab NAME` raises every design
  rule below the house's published minimums for the board's layer
  count, writes its stackup into the board, and judges the input at
  those floors too, so a footprint the house cannot etch is named as
  the input's problem, not the router's.
- **Delivers the fabrication package**: gerbers, drill files and maps,
  IPC-D-356 netlist, a sourced BOM, pick-and-place, fab drawings, a
  board render, the schematic as PDF, a copy of the design and a
  SHA-256 manifest, unless you ask it not to.
- **Keeps the console quiet.** A run prints one status line per
  attempt (placing, routing pass, rip-up round, DRC, done) and the
  verdict; everything else goes to `klayout.log`.

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

Everything a run produces lives in the output directory:

```
my-board-routed/
  <board>.kicad_pcb            the placed and routed board: opens in KiCad,
                               pours filled, the fab's stackup written in,
                               designators straightened and kept off silk
  <board>.kicad_pro, .kicad_prl, .kicad_sch, fp-lib-table, sym-lib-table,
  <libs>.pretty/, <libs>.kicad_sym
                               the rest of the project, copied beside the
                               board so it opens as a whole; the project's
                               DRC minimums raised to the fab's floors
  <board>-klayout-result.json  the verdict (below)
  klayout.log                  everything the run did: the trial table,
                               placement and routing passes, the impedance,
                               skew and reflection reports, DRC and ERC
  placement-report.txt         boards that were placed: wirelength before
                               and after, the pin pulls, each part's move
                               (beside the board, or in the kept attempt's
                               folder when that attempt placed it)
  si-report/                   boards built on a fab's stackup: the copper
                               as laid, per net — segments.csv, vias.csv,
                               pads.csv — the reflection data an SI review
                               starts from
  fabrication/                 the manufacturing package (below);
                               --gerber-dir moves it, --no-fab skips it
  .input/                      a read-only copy of the input, judged by the
                               same DRC at the fab's floors, so the verdict
                               can separate the board's own violations from
                               anything the router introduced
  .att0/ … .att7/, .att0.log … the placement attempts, each a full project
                               with that attempt's board and log (hidden
                               dot-files; `ls -a`)
  <board>.progress.json        the frame the PCB Layout Cinema is drawing
```

The fabrication package, in the layout a board house and an assembler
both expect:

```
fabrication/
  gerbers/            <board>-<Layer>.gbr for every copper, mask, silk and
                      paste layer plus the outline, and <board>-job.gbrjob
    drill/            <board>-PTH.drl, <board>-NPTH.drl (Excellon, mm), a
                      PDF drill map per file, drill-report.rpt
  electrical-test/    <board>.d356 — the IPC-D-356 netlist for bare-board test
  assembly/           <board>-bom.csv — one row per reference: Reference,
                      Value, Footprint, Quantity, Manufacturer, MPN,
                      Datasheet, Lifecycle, Supplier, SKU, Product URL,
                      Available, Verified On, Unit Price, DNP
                      <board>-positions.csv — pick-and-place, both sides,
                      mm, populated parts only
                      drawings-svg/ — front and back fab drawings
  documentation/      <board>-board-render.png (top view) and
                      schematic/<board>.pdf
  design/             the board, project, schematic, tables and libraries
                      as sent to manufacture
  manifest.json       every file with its size and SHA-256, the source
                      board's hash, the kicad-cli version, the run's DRC counts
```

The BOM's sourcing columns come from the footprint's own fields
(Manufacturer, MPN, Datasheet) when the schematic carries them, and
otherwise from the parts library beside the fab library
(`--parts-dir`): manufacturer, part number, lifecycle status, stock, the
first authorized supplier with its SKU, the lowest-volume price and the
date the record was verified. A part with no record keeps its row with
those columns empty, so the BOM always lists every part on the board.

### The PCB Layout Cinema

Every run serves a live view of the routing and opens it in your default
browser (Safari, Chrome and Firefox all work):

```
http://localhost:8765/
```

One panel per placement attempt, drawn as it routes — the copper laid
since the last frame in white — with completion bars per signal class
(differential pairs and DDR, other signals, power), the current stage,
the elapsed time, and a scrub bar over the run's frames. **Step frame by
frame** with the ‹ › buttons beside the bar, or click a panel and use
the ← → keys (space returns to live); the counter shows which frame you
are on. The run ends on two frames: what the last pass laid, highlighted
white, then the finished board in its layer colours.
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
| `--parts-dir DIR` | the parts library the BOM is sourced from (default: `components/` beside the fab library). |
| `--group-labeling` | frame and name the functional blocks on the front silkscreen; off, the blocks pack as tightly as the rows allow and nothing is drawn. |
| `--no-fab` | skip the fabrication package. |
| `--gerber-dir DIR` | write the fabrication package somewhere else. |
| `--split-ps` | split a board larger than a power supply into `<base>-PS` (the mains sheet) and `<base>-MB` (everything else) and route the two separately. |
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
  and the counts in the log. The result file also carries `fab_target`
  (the house whose floors the board was built to), `gates_met`,
  `si_pairs_missed`, `stitch_bonds`, the `placement_constraints` read
  from the design file and any violations, and `outputs` — the path of
  the fabrication package and of each of its parts.
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
