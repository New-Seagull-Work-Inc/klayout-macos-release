> **Binary release** — prebuilt `klayout` and `kplace`
> executables for macOS on Apple Silicon (arm64).
> Links against the system libSystem only; no other dependencies.
> Other platforms and distributions: build from the source
> repository when authorized by Seagull Work, Inc.
> **This package contains executables and one example
> KiCad board — no source code is included or implied.**
> The `klayout` and `kplace` binaries, this README, the
> `LICENSE` and the `example/` board they route are the
> entire distribution: there is no source tree, no
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
> **Trial software, no warranty** — free to evaluate, and
> the layouts it produces are yours to use for anything,
> commercially included. Nothing it outputs is guaranteed
> or has been reviewed by an engineer: a clean DRC report
> is this program grading its own work, not an assurance
> that a board is manufacturable or safe. Verify every
> layout before you build it. Full terms in `LICENSE`.
> The build instructions carried by the source repository are
> omitted from this README: there is nothing here to compile.

# klayout

A batch place-and-route tool for KiCad boards, written in portable C99 with no
dependencies beyond libm. It takes `.kicad_pcb` files — placed, or with
footprints still staged outside the outline — places them if needed,
routes the unconnected nets, and writes complete KiCad projects back
out: board, project file, and schematic. Everything in
the board file that the router doesn't understand is preserved verbatim, so
it works across KiCad versions (developed and DRC-validated against
KiCad 10).

```
boards/                          routed/
  amp.kicad_pcb        klayout      amp.kicad_pcb   (+ tracks, vias)
  amp.kicad_pro       ------->     amp.kicad_pro   (copied)
  amp.kicad_sch                    amp.kicad_sch   (copied)
```

## Status

Boards that route completely (0 DRC error violations, 0 unconnected):

- **CANNONBALL** (dense 4-layer, 58 nets): `--layers 4 --plane
  GND:In2.Cu --grid 0.05` — zero unrouted, zero DRC errors, class
  0.6/0.3 vias only, the auto-detected multi-drop USB pair routed as
  MST spans within its budgets. Also solves the ORIGINAL human-rule
  variant (0.15 mm clearance — twice as strict as the regression
  copy): 0/0 with the USB pair at 0.425 mm skew, in ~32 minutes wall
  with parallel attempts.
- **xlator** (197×132 mm, 0.076 mm rules, 7 differential pairs, MIPI
  CSI-2 + Ethernet): placed or staged-for-placement — every pair
  budget met (0.000 mm skew, matched lanes, co-layer members,
  balanced flips, solved 100-ohm geometry), zero DRC errors, zero
  unconnected. The 8-attempt hunt runs in ~36 s wall in parallel.
- **regulator** (single-sided): `--layers 1 --resize-pcb` — ground as
  flood fill, no vias, planar-routed on a re-tried placement, board
  shrunk to the minimum DRC-legal outline. With its `power.json`
  (1.25 A in, 3 A out, 100 mV drop budgets) the rails route at the
  IPC-2221 widths (0.409 / 1.367 mm), IR drop verified in budget —
  in the regression corpus with exactly those flags.

Not there yet:

- **PolarFire** (MPFS095T-FCSG325 0.5 mm BGA + DDR4 x16, 12 layers,
  Advanced Circuits floors; `test/regression-slow/polarfire`): routes
  completely (0 unrouted) with 3 DRC errors / 1 unconnected, all 17 KDS
  placement constraints met, and no SI pass — intra-pair skew
  0.49/0.71/0.66 mm against the design's 0.15 mm, byte lanes 6.4–7.0 mm
  against 2.5, addr/cmd 60 mm against 2.5 (2026-08-21, ~17 h wall). The
  diagnosis and the queued changes are in `docs/ddr-next-steps.md`.

## Automatic placement

klayout ships with a vendored simulated-annealing placer (`kplace`,
built alongside it). When an input board's footprints sit with pads
outside the board outline — the standard "parts staged for placement"
convention — klayout detects it, runs the placement stage (minimising
weighted wirelength, 90° rotations, courtyard-overlap avoidance, with
pad rotations rewritten in world frame as KiCad requires), reloads the
placed board, and routes it. A fully unplaced netlist becomes a placed,
routed, DRC-clean board in one command; boards that are already placed
skip the stage entirely.

Written boards get their silkscreen designators straightened: KiCad
text angles rotate with the part, so a customer-rotated footprint
arrives with its Reference label turned sideways and would stay that
way through placement. Every Reference angle is normalized to 0 in
the output — parts keep their rotations, labels read horizontally
(`straightened N turned designator(s)` reports it).

### Differential-pair auto-detection

With no `diffpairs.json`, pairs are detected from net names: two nets
pair when their names are the same length and differ only at
positions where one has `P`/`p`/`+` and the other `N`/`n`/`-` —
`DP`/`DN`, `D+`/`D-`, `X_P`/`X_N`, and names carrying the polarity
twice all match. Both members need routable pads; battery/voltage
terminals (`B+`/`B-`, `V+`/`V-`) are excluded; the standard is
inferred from the base name where it is unambiguous (`DP`/`DN` and
USB-ish names get USB at 90 ohm). Detections are announced, and a
`diffpairs.json` always overrides.

### Per-standard skew budgets

Each pair is judged against what ITS spec demands, not the strictest:
MIPI CSI/DSI and unknown standards 0.1 mm intra-pair, USB 1.25 mm,
Ethernet MDI 1.3 mm. The SI itemization prints each pair's own
budget with its shortfall.

### DDR interfaces

A DDR memory interface is detected from net names alone: byte lanes
(DQ by index/8 with their DM/DQM/LDM/UDM masks) assemble around their
DQS strobe pairs, and the address/command group (A*/BA/RAS/CAS/WE/
CS/CKE/ODT/ACT/PAR/RESET, token-boundary matched so CKE never reads
as CK) assembles around the CK pair. The detected spec is written to
the output as `diffpairs.json` — promote it next to the input to make
it authoritative; a hand-written file disables detection. Groups are
length-matched after pair matching (0.635 mm members-to-strobe,
2.0 mm addr/cmd-to-CK), pairs route at 100 ohm differential, and the
DDR report itemizes each group's worst skew in the SI gates.

What professionally routed DDR boards actually do — nine open-hardware
designs (BeagleV-Fire and the Antmicro PolarFire SoM among them)
measured from their design files: controller–DRAM spacing, one inner
layer and two vias per lane net, shipped skews, serpentine geometry —
is in `docs/ddr-reference-forensics/REPORT.md`; the router changes
queued from it, and the state of the PolarFire corpus board, are in
`docs/ddr-next-steps.md`.

### The SI completion map

Boards with pairs or DDR groups print a titled legend of every
matched signal, then one `Y`/`N` row per placement attempt as it
lands — which signals routed, which missed, misses named. On a
72-bit ECC DDR that is a 160-column live view of the campaign.

### Grounds by any name

Ground detection understands the common dialects: `GND`/`AGND`/`DGND`,
the CMOS `VSS`/`AVSS`/`DVSS` family, `EARTH`. All of auto-plane
selection, the "ground with no plane" note, the stackup role labels
and the power-net exclusion share one recognizer, so an `avss`-only
board gets its ground plane (or 1/2-layer flood fill) automatically.

### Live-pour plane drops

An SMD pad's via drop targets only the LIVE pour: per plane layer,
the largest connected free region — under a dense BGA via field the
foreign clearance halos overlap into a moat where the zone fill
islands and is removed, and a via dropped there lands on bare
laminate. The drop search targets every plane layer the net owns
(a 6+ stack offers both its GND planes) and walks the escape out of
the moat on whatever layer is cheapest before dropping.

### Keepout rule areas

Zones with a `(keepout ...)` clause bind the router: `(tracks
not_allowed)` bars track copper on the zone's layers, `(vias
not_allowed)` bars via barrels (which span every layer, so a keepout
on any one layer kills the site). Footprint-embedded keepouts — a
sensor demanding a copper-free zone under its element, say — count
exactly like board-level ones. Every path that lays copper honors
them: the grid search, the exact-geometry validation behind
string-pulling and off-grid via sites, and the pour-stitching pass's
vias and spurs. No clearance is imposed around a keepout — the crime
is presence, not proximity — and `(copperpour not_allowed)` needs
nothing here because the pours this tool emits are filled by KiCad,
whose refill excludes keepouts itself.

### Output rules match the routed copper

When a fab sweep, `--fab`, or explicit flags resolve rules below the
project's, the OUTPUT copy of the `.kicad_pro` gets its DRC floors
(rules minimums and netclass floors, lowered only) rewritten to what
was actually routed — KiCad's DRC judges the board that exists, not
the board the project imagined.

Each floor is lowered to the rule it actually governs: the hole keys
(`min_hole_clearance`, `min_hole_to_hole`) take the resolved *hole*
clearances, never the copper one, which is usually smaller. This is
not cosmetic. DRC runs with `--refill-zones`, so a floor written here
is the floor KiCad pours against, and the saved fill is what the
gerbers carry: lowering the hole keys to the copper clearance floods
copper closer to a drilled hole than the router itself honored, and
then hides the violation behind the same edit. A rule the run never
resolved is left alone rather than treated as a floor of zero.

### Iterate on any auto-placed board

The place-route-measure loop engages for EVERY board that goes
through placement, pairs or not: an attempt whose routing cannot
complete (a single-sided board fenced in by an unlucky arrangement,
say) is re-placed with the next seed until everything routes with
zero DRC errors, up to `--place-tries`. When no attempt makes it,
the best one is still written but the failure is loud: `GATES
FAILED: no placement attempt of 8 met the completion/DRC gates`,
a `*** GATE WARNING ***` in the run summary with the count of
boards below the gates, and a nonzero exit status — a written
board is never silently passed off as a good one.

### Vias

Class vias only, by default: the human reference layouts close their
boards entirely with net-class vias, and that is the bar. The
endgame's fallback to the project's `min_via_diameter` is an explicit
opt-in (`--allow-min-vias`), and even then never goes below what the
`.kicad_pro` allows. `--exact-vias` (experimental, slow) extends
analytically validated off-grid via hunting from the endgame to the
whole search. Via-site verdicts persist across searches in a memo
tagged by net and invalidated when the copper changes, so repeated
negotiation rounds stop re-probing the same sites — this is what made
`--exact-vias` finish at all; it remains experimental because even
memoized it does not beat a well-aligned fine grid.

### Pair-driven placement

Differential-pair quality drives placement, not the other way around.
Whenever the board has pairs — from `diffpairs.json` OR auto-detected
from net names — klayout hands the list to the placer, so boards that
never shipped a pair file still place with exit corridors and facing
costs (on the camera benchmark this alone took six failing pairs down
to two). Two things happen:

- The placer's diff-pair cost terms engage: pads on pair nets get
  reserved exit corridors and lane-width fields, so parts are placed
  with room for the pairs to escape and run.
- The layout is **done and redone until every pair meets budget**.
  Boards that place here vary the placement seed per attempt
  (`--seed`, default 1; attempt *t* uses seed+*t*). Boards that
  arrive already placed iterate on the ROUTING instead — the net
  order rotates and the rip-round penalty phase shifts per attempt —
  because the placement is fixed but the negotiation is not. An
  attempt is accepted only when all connections routed, there are
  zero DRC error violations, every pair's intra-pair skew is within
  0.1 mm, every matched-standard group's inter-lane spread is within
  1.0 mm, both members of every pair have the same layer-flip count,
  and the members' per-layer copper matches within the standard's
  co-layer budget. That budget scales with the standard's timing
  tolerance: off-layer copper skews delay at the microstrip-vs-
  stripline velocity *difference* (~0.85 ps/mm), about 8x more gently
  than plain length skew, so each standard gets 8x its intra-pair
  budget with a 2.0 mm floor — CSI/unknown 2.0 mm, USB 10 mm,
  Ethernet MDI 10.4 mm. The floor stays even where timing forgives
  (Ethernet tolerates nanoseconds) because off-layer copper also
  means the members ride different impedance classes. Otherwise
  the next attempt runs, up to `--place-tries` (default 8), keeping
  the best attempt if none fully meets budget — in which case the run
  prints `PAIRS FAILED`, the summary counts the board under
  "differential pairs missing budgets", and the exit status is
  nonzero. The verdict line (`pairs meet/miss budgets: ...`) is
  printed for every attempt on every board with pairs, and the final
  SI warning ITEMIZES every shortfall of the written board — the
  measured value, the budget, and how far over: `MIPI CSI-2 group:
  inter-lane spread 3.656 mm, budget 1.0 -- 2.656 mm over (extend or
  shorten lanes to match)`. Output is unbuffered, so a long run
  streams its progress through pipes and logs in real time.

Fixed seeds also make runs reproducible: the same inputs and options
give the same board every time, on any platform. The placer draws from
an explicit deterministic generator rather than libc
`rand()`, whose algorithm is implementation-defined — glibc and macOS
walk different sequences from the same seed, which used to put the
annealer on a different placement per machine and made a recorded
baseline unreproducible anywhere else. One caveat remains: the annealer
compares against `exp()` and scales its schedule with `pow()`, and libm
transcendentals are not bit-identical across platforms, so a divergence
is improbable rather than impossible. On the xlator board the loop
rejects seed 1 (off-layer 2.8 mm) and accepts seed 2 with every
budget met: all 7 pairs at 0.000 mm intra-pair skew, CSI inter-lane
spread 0.000 mm, worst off-layer copper 0.416 mm, balanced flips,
zero DRC errors, zero unconnected — differential pairs done first,
frozen, and everything else routed around them.

## User interface

### Directory mode (primary)

```sh
./klayout --input-dir boards/ --output-dir routed/ [options]
```

Routes every `.kicad_pcb` in the input directory and writes a board with
the same name to the output directory (created if needed). For each board
the output directory also receives:

- **`<name>.kicad_pro`** — copied from the input directory; if the input
  has none, a minimal valid project file is generated so KiCad opens the
  result as a proper project.
- **`*.kicad_sch`** — every schematic in the input directory is copied
  across, so hierarchical designs keep their sub-sheets.

The exit status is 0 only if every connection on every board routed.

At the end of the run, each output board is checked with
`kicad-cli pcb drc --severity-error` and a summary is printed: the number
of DRC error violations and unconnected items in the output directory,
per board and in total. `kicad-cli` is found via `$KICAD_CLI`, PATH, or
the standard macOS install location; if it is missing the DRC report is
skipped with a notice.

### Example board

The binary package ships one board to route, in `example/`: `Doorbell_PS`,
the 2-layer revision of an 8–24 VAC doorbell-camera UPS — 48 nets, 184
pads, every one of them staged outside the outline, so the run places the
board before it routes it. Beside the board sit a `power.json` (12 rails,
up to 6 A, widened to their IPC-2221 ampacity) and a `.kicad_kds` design
file carrying 9 placement constraints, so one command exercises placement,
ampacity widening, KDS constraints and flood-fill grounds together:

```sh
./klayout --input-dir example --output-dir out --resize-pcb
```

Up to eight placement attempts are made — one fewer at a time than the
machine has cores, since the parent keeps one — and the first to meet
every gate is kept, which on this board is normally attempt 1.
`--resize-pcb` then shrinks the outline to the minimum DRC-legal rectangle
around what was placed. Around a minute and a half on a two-core x86-64
box. `out/` receives the routed
board, its project and schematic, the footprint library, and
`Doorbell_PS-klayout-result.json` with the run verdict. The expected
finish is `0 error violation(s), 0 unconnected item(s)`.

Because a `.kicad_kds` sits next to the input, the fab exports are left to
the KiChad flow — pass `--fab-outputs` to get gerbers and drill files from
this run anyway.

### Single-file mode

```sh
./klayout board.kicad_pcb -o routed.kicad_pcb [options]
```

Routes one board. No project/schematic copying is done in this mode.

### Options

| Option | Default | Meaning |
|---|---|---|
| `--layers N` | 2 | Copper layers the router may use (1–32). `--layers 1` is true single-sided: everything on F.Cu, no vias, the ground net poured as a flood fill the tracks route through (the classic single-sided technique), and placement re-tried until the remaining nets route planar. |
| *(no plane flags)* | | With only `--layers N` (4+), the tool chooses the ground plane itself: the ground net feeding the most pads goes on the inner layer adjacent to the denser SMD face (6+ layers add a second GND plane by the other face; 8+ layers add a dedicated power plane beside a ground — interplane capacitance — with the net auto-picked), reported with its reason at run start — `stackup: chose In1.Cu for ground plane "GND" (adjacent to F.Cu, the denser face: 198 vs 0 SMD pads)`. On 1/2 layers the ground is instead poured as a flood fill (both faces on 2) and never routed as tracks; if the fill fragments — live islands with no copper path back to the net — each stranded fragment is bonded to the opposite face's pour with a stitching via placed inside it, and a fine-pitch ground pin the fill cannot reach gets a via drop lapping the pad or, when no via fits, a short same-layer spur to the nearest ground copper (`stitch:` lines in the log; all of it is taken back out if DRC does not improve). `--plane`/`--stack` override. |
| `--stack SPEC` | | Stackup by role, outermost first: `SIG-GND-SIG-GND:AGND-PWR-SIG` sets 6 layers, reserves a plane for every GND/PWR layer. `GND` defaults to net "GND"; `GND:AGND` names another ground; `GND:GND+AGND` groups split grounds (joined only at their ferrite bead) on one reserved layer; bare `PWR` lets the tool pick the biggest power-looking net and print its choice. Outer layers must be SIG. Use `,` separators when net names contain dashes. |
| `--plane NETS:LAYER` | | Reserve an inner layer for one net (pours a zone; SMD pads get via drops) or a comma-separated group (routed as tracks). Repeatable. Other nets' vias still pass through. Inner layers only, so 1/2-layer boards have no reservation. |
| `--route-all-layers` | | Ignore `--plane` specs: every layer open to every net. |
| `--eight-angles-routing` | default | Octilinear copper (90/45-degree turns only) is the DEFAULT: the full campaign runs on-compass first, retries any-angle only when gates or pair budgets are missed, and restores the eight-angle result when the retry does no better. The explicit flag pins eight angles with no fallback; `KLAYOUT_ANGLES=any` skips straight to any-angle. Short pad-attach stubs may still angle as a connectivity last resort. |
| `--square-wiggles` / `--sine-wiggles` / `--arc-wiggles` | arc | Length-matching meander shape. Arc serpentines (straight risers, true KiCad arc caps) are the default; square restores the rectangular teeth, sine the chord-sampled sinusoids. Every family caps amplitude at 3 track widths (clamped 0.15–2.5 mm) — length is bought with more periods, not tall teeth — and a meander leg may never touch its own net's copper beyond its chained neighbors (a self-crossing meander is a length lie). |
| `--net NAME` | all | Route only the named net |
| `--grid MM` | 0.1 | Routing grid pitch. Over the 80M-cell budget (big outlines × many layers) the pitch auto-coarsens through the standard steps with a log line; an explicit `--grid` pins the pitch exactly — the run refuses rather than coarsen. |
| `--clearance MM` | project | Copper-to-copper clearance |
| `--track MM` | project | Track width |
| `--via-size MM` | project | Via pad diameter |
| `--via-drill MM` | project | Via drill diameter |
| `--edge-clearance MM` | project | Copper to board edge clearance |
| `--hole-clearance MM` | project | Copper to hole edge clearance |
| `--via-cost MM` | 5.0 | Detour length the router will accept to avoid one via |
| `--place-tries N` | 8 | Attempts in the iterate-until-done loop (placement seeds for staged boards, routing seeds for placed ones). Attempts run in PARALLEL, one process per attempt, defaulting to installed cores − 1; `KLAYOUT_PARALLEL=k` caps the width (12-layer grids run hundreds of MB each — oversubscribed memory page-fault-crawls), `KLAYOUT_SERIAL=1` forces one at a time. Children inherit the coordinator's RESOLVED design rules as explicit flags, so fab-floor and agent-adjusted runs behave identically in and out of the workers. |
| `--seed N` | 1 | Base seed; attempt *t* uses N+t, so every run is reproducible |
| `--resize-pcb` | | After routing, shrink the outline to the minimum DRC-legal rectangle around the design: copper, courtyards, silkscreen text, edge clearance |
| `--board NAME` | all | Directory mode: process only this board (used by the parallel workers; handy standalone) |
| `--allow-min-vias` | | Let the endgame shrink stragglers' vias to the project's `min_via_diameter`. Default is class vias only, matching the human reference layouts. |
| `--exact-vias` | | Experimental: analytically validated off-grid via hunting during the whole search, not just the endgame. Slower; the human's gridless vias prove the architecture, but a well-aligned fine grid still wins. |
| `--no-widen` | | Ignore `power.json`: route power rails at the class track width (no IPC-2221 ampacity widening). |
| `--no-fab` | | Skip gerber + drill file generation. |
| `--research` | off | On an SI miss, run the online research step (also skipped when offline or `KLAYOUT_OFFLINE=1`). |
| `--learn` | off | Enable the automatic learning loops: consultation rounds on below-gates boards, remembered tuning, code evolution (`KLAYOUT_NO_LEARN` still forces off). |
| `--agent N` | 0 | Strategy escalation: on a below-gates finish, consult a `claude` CLI for one whitelisted knob change and re-run, up to N rounds (decisions logged to `agent-log.md`). |
| `--gerber-dir DIR` | OUT/gerber-drill | Where to write the fab files. |
| `-h`, `--help` | | Usage |

Layers are indexed 0 = `F.Cu`, 1…N−2 = `In1.Cu`…, N−1 = `B.Cu`. All layer
changes use through vias, which occupy every copper layer.

### Fab outputs: gerbers + drill

Every routed board also gets manufacturing outputs by default,
written to `gerber-drill/` in the output directory (`--gerber-dir`
redirects, `--no-fab` skips): one gerber per copper, mask, silk and
paste layer plus the board outline, and Excellon drill files in mm
with decimal zeros, plated and non-plated holes in separate files.
The copper layer list is read from the written board itself, so
4/6/8-layer boards export their inner plane layers too. Generation
runs on the DRC'd output file — zone fills were saved into it by the
DRC's refill, so the gerber copper is exactly the copper DRC
validated. Like DRC, this shells out to `kicad-cli` (`$KICAD_CLI`,
`PATH`, or the standard macOS install).

### Target fab

`--fab NAME` (or a `(fab "NAME")` clause anywhere in the
`.kicad_kds` next to the input board — the design file is the
natural home for "this board is made at JLCPCB") declares the
vendor up front. Their capability JSON becomes the hard floor for
every rule: project rules below a floor are raised and called out,
no reduction (agent rounds, endgame vias, stitch copper) ever goes
under them, a `--layers` count beyond the vendor's range is
flagged, and the post-failure capability sweep below is skipped —
the fab is already chosen, so there is nothing to shop around.

### Design-file (KDS) integration

A `.kicad_kds` next to the input board changes what klayout is: not a
standalone tool but the layout stage of the KiChad flow, whose
contract is exactly two artifacts in the output directory — the
routed board and the run verdict.

- **Placement constraints.** The KDS's `(board (layout (placement
  ...)))` section — `(near A B (maximum Nmm))`, `(edge REF side
  (maximum Nmm))`, `(group name (members ...) (maximum_span Nmm))`,
  `(board (maximum_width/maximum_height))` — is parsed and enforced
  end to end: kplace carries a cost pull for every constraint (zero
  inside spec, steep past the maximum), each placement attempt is
  measured and gated on them, and every check prints measured-vs-max.
  Measurements use the footprint's authored anchor (its `(at X Y)`),
  matching KiChad's analyzer; board maxima measure the Edge.Cuts
  bounding box, strict comparison, no tolerance. Constraint clusters
  (connected `near` components — a mains supply section, an FPGA with
  its memory) are seated as units before general placement, hubs
  anchored to their edge bands, and the seated poses are final.
  `(pattern circle (members ...) (center REF) (diameter Nmm))` places
  the members evenly on the ring around the center part (an LED ring
  around its optical axis); measured as worst ring deviation with a
  1.5 mm tolerance. (Pattern syntax proposed to KiChad 2026-08-19.)
- **Routing budgets from the design file.** The KDS's `(layout
  (routing ...))` section is the authority on skew: a `(bundle NAME
  (nets ...) (maximum_skew Nmm))` overrides the DDR detector's
  default budget for the matching group, and a two-net bundle naming
  a differential pair overrides that pair's intra budget. Reference
  forensics (Antmicro's LPDDR4 test board) showed professionally
  shipped lanes at 4x the detector's default — the design file knows
  its controller's training ability, the tool does not. Per-net
  clauses klayout cannot model yet (`maximum_vias`,
  `maximum_length`, `geometry`) are announced, never silently
  dropped. DDR nets also get layer discipline: byte lanes prefer the
  top layer (the reference channels run zero-via lanes there),
  addr/cmd groups one inner stripline — a soft 2x preference that
  congestion can overrule.
- **Run verdict.** `<board>-klayout-result.json` lands next to every
  output board: DRC error/unconnected counts, routing failures, SI
  budget results, stitch bonds, `gates_met`, the fab target, the
  per-constraint measured-vs-max table, and the generated outputs (or
  `null` when fabrication belongs to KiChad). The DRC counts and the
  constraint table are stability-guaranteed — KiChad's gates consume
  them verbatim.
- **Fab outputs stay KiChad's.** With a KDS present the gerber/drill/
  pos/IPC-D-356 generation is skipped (`fab outputs: left to
  KiChad's fabricate` in the log) — their `fabricate` builds the
  package of record from the reconciled board. `--fab-outputs` forces
  klayout's own set as a cross-check; boards without a KDS always get
  the complete standalone package, which now includes pick-and-place
  (`<board>-pos.csv`) and the IPC-D-356 test netlist
  (`<board>.d356`) beside gerbers + drill.
- **Physical stackup.** Boards whose input carries no
  `(setup (stackup ...))` get one written into the output, matching
  the geometry the SI model assumed (35 um outer copper, FR4 er 4.3,
  the impedance model's dielectric heights; `stackup.json` next to
  the input overrides). An input stackup is the designer's and is
  left untouched.
- **Attempt gating meets reality.** Attempt children stitch their own
  pours before reporting, so selection judges what a placement can be
  bonded into; and the parent's final gate verdict is decided by the
  SHIPPED board's measurements, never by stale attempt-stage
  readings.

### Learning loops

With `--learn`, below-gates boards no longer just report — they learn
(off by default; the regression suite additionally guards via
`KLAYOUT_NO_LEARN` so references stay deterministic):

- **Consulted parameter rounds.** A board below its gates triggers up
  to three consultation rounds (a claude CLI with the banked research
  and the agent log): one whitelisted knob change per round — seed,
  place-tries, grid, track/clearance inside the legal band, plane
  spec — applied and re-run. Across rounds the BEST board wins, never
  the last: a failed experiment cannot displace an earlier better
  result. `--agent N` still sets an explicit budget.
- **Remembered tuning.** When a consulted round verifiably beats the
  baseline run, the winning knobs are persisted to
  `klayout-tuning.json` next to the input board — applied on every
  future run at the lowest precedence (project rules and the command
  line always win), with the reason recorded.
- **Code evolution.** When no parameter fixes a board, the
  consultation may propose an actual code change: a unified diff
  restricted to the router's algorithm files (never the gates, DRC
  calls, Makefile or test suite), applied in a git worktree, built,
  and judged twice — the triggering board must meet its gates AND
  the full regression suite must pass — before being adopted as its
  own commit with provenance. Failures feed their evidence back for
  a revised patch, three attempts per run, transcripts kept in
  `.evolve/`. Evolution refuses to run on a dirty tree: it builds on
  committed ground only.

### Choosing between `--research` and `--learn`

Both flags hand a below-gates board to a claude CLI; they differ in
whether the run ACTS on the answer.

- `--research` is **advisory and read-only**: the layout-practice
  findings for the board's exact parts are banked once in
  `OUT/research-notes.md` and nothing about the run changes. Use it
  alone when you want the analysis without the tool touching
  anything.
- `--learn` is **the acting side**: consultation rounds that apply
  one whitelisted knob change per round, remembered tuning, and (as
  the last resort) code evolution. A consultation is itself a full
  claude call, so it can research ad hoc — but without the notes
  file, whatever it learns is transient to that round.
- **Together they are the intended pairing for a hard board**: the
  research runs once, the notes are banked, and every consultation
  round starts from them instead of re-deriving or re-researching —
  cheaper rounds, better-informed proposals, and the notes remain as
  a readable artifact. (`--research --agent N` is the bounded-budget
  variant.)

Two caveats before reaching for the pair. A `--learn` run is
inherently **non-reproducible** — consultation replies vary — which
is why the regression suite pins `KLAYOUT_NO_LEARN`; use it to
explore a stuck board, not to produce a board you need to re-derive
bit-identically. And each consultation round is a **full re-run** of
the board (evolution adds rebuild-plus-regression cycles on top), so
on a large board that is hours per round. The working pattern: plain
run first; if it finishes below gates and the failure is not already
understood, re-run with `--research --learn`. The mechanical SI
retry (one deterministic re-place with the failing pairs' parts
pulled closer) always runs — it needs no network and costs one pass,
so it is not gated behind either flag.

### Fab capability sweep

Bare-PCB fab capability files (one JSON per vendor — min trace width
and spacing, via drill/diameter, edge clearance, layer counts) plug
in via `--fab-dir DIR`, `KLAYOUT_FAB_DIR`, or the house default
`../designer-parts/fab` when present. When a board finishes below
ANY gate under the project's own rules — incomplete, DRC, or SI
budgets — each fab's envelope gets its own attempt with the rules
opened to that fab's minimums, and the run ends with a verdict per
vendor (completes / completes and meets SI / still incomplete) plus
a recommendation preferring the first fab that meets SI outright:

```
fab sweep: JLCPCB (trace 0.127, space 0.127, via 0.25/0.15)... COMPLETES the board, SI budgets MET
*** FAB RECOMMENDATION *** the board completes AND meets every SI budget
    within JLCPCB's capabilities. To adopt: rerun with --track 0.127
    --clearance 0.127 --via-size 0.25 --via-drill 0.15 ... then order at JLCPCB.
```

Sweep boards are judged by the router's exact geometry model, not
the KiCad DRC gate — copper below the project's own netclass values
SHOULD flag under the old rules, so adopting a sweep result means
updating the project rules to the reported numbers. Sweep outputs
stay in `OUT/.fab-<vendor>/`; the main output is never displaced.

### Agent mode: research and strategy escalation

The inner loop (placement seeds, routing attempts, honest gates) has
a fixed strategy. Agent mode adds the outer brain for boards that
finish below their gates:

1. **Problem write-up** — the failing pairs with their numbers plus a
   parts inventory (footprint library ids, tagged with the pairs they
   carry) goes to `OUT/research-request.txt`. Reference layouts for
   the EXACT parts on the board are what a human would search for,
   so that is what the request asks for.
2. **Research** — with `--research`, when the internet is reachable
   (one ~0.7 s TCP probe; `KLAYOUT_OFFLINE=1` skips) and a
   `claude` CLI is on PATH, the request is handed to it and the
   findings land in `OUT/research-notes.md`. Advisory only.
3. **Escalation** (`--agent N`) — the consultation must answer with
   ONE next action as strict JSON from a whitelisted vocabulary —
   new `seed`, `place_tries`, `grid`, `plane`, `route_all_layers`,
   `track`/`clearance` (reductions allowed only inside the legal band
   between the project's HARD minimums and the current values; pair
   geometry is impedance-solved and untouchable; and the DRC gate
   remains the judge either way), or `stop` — which is validated,
   clamped to legal ranges, logged
   with its reasoning to `OUT/agent-log.md`, applied, and the board
   re-run, up to N rounds. The model picks among the tool's own
   legal knobs; it can never emit shell, paths, or file edits.

Agent mode is inherently nondeterministic and is never used by the
regression suite; every decision is on the record in the log.

### Where design rules come from

KiCad stores design rules in the `.kicad_pro` project file, not in the
board file. For each board, values are resolved in this order:

1. **Command line** — `--clearance`, `--track`, `--via-size`, `--via-drill`
   always win.
2. **Project file** next to the input board: the Default net class value,
   floored by the board's `min_*` rule (`min_clearance`,
   `min_track_width`, `min_via_diameter`, `min_through_hole_diameter`) —
   whichever is larger wins. Edge clearance comes from
   `min_copper_edge_clearance`.
3. **Built-in defaults** — 0.2 mm clearance, 0.25 mm track, 0.6/0.3 mm via.

A `.kicad_dru` custom-rules file next to the board is honored too:
its UNCONDITIONAL constraints (clearance, track_width, hole_to_hole,
edge/hole clearance, via_diameter, hole_size, annular_width — the
last checked against the router's own via ring) override the project
values in whichever direction the customer chose, and the file is
copied to the output so DRC judges the result under the same law.
Conditional rules carry KiCad's full expression language and are
announced by name as "not modeled in routing" — the DRC gate still
enforces them on the output. Command-line pins beat everything.

The resolved rules are printed per board before routing.

## Status and benchmark results

Quality bar: `kicad-cli pcb drc` on every output — **zero error violations
introduced** is non-negotiable; completion is the metric being pushed.

CANNONBALL (dense 4-layer board, 58 nets / 179 connections; a human
layout of the same design routes it fully) — progression of unrouted
connections, all at 0 introduced DRC violations:

| Router state | Failed connections |
|---|---|
| 2 layers, bounding-circle obstacles | 71 |
| `--layers 4` | 52 |
| `--layers 4` + exact pad-shape obstacles | 25 |
| + rip-up-and-retry with history cost | 7 |
| + EP anchor-pad adoption, `--via-size 0.5` | **0** |

Recommended invocation for dense boards:

```sh
./klayout --input-dir boards/ --output-dir routed/ --layers 4 \
    --via-size 0.5 --via-drill 0.3   # if min_via_diameter allows
```

Via size is the scarce resource on dense 4-layer boards — a through
via's keep-out spans every layer — so if the board's `min_via_diameter`
permits a smaller via than the Default net class uses, passing it can be
the difference between a few stubborn nets and full completion.

Simpler boards (the two in `test/regression/`) route completely.

The router now negotiates congestion: a greedy first pass, a
hard-nets-first reroute, then rip-up rounds in which a failed connection
finds the cheapest path across other nets' copper (exact static
obstacles stay hard), rips the owning nets, and requeues them — with a
PathFinder-style history cost that makes repeatedly contested cells more
expensive for everyone, so oscillating fights settle. Fine-pitch parts
(0.35 mm LGA) attach through zero-margin escape stubs validated against
exact geometry rather than the (slack-carrying) raster. The best state
seen across all rounds is kept and restored.

With those flags CANNONBALL's kept attempt routes every connection it
is given (`routed 178 connection(s), 0 failed`) and introduces 0 DRC
error violations. kicad-cli still reports 1 unconnected item against
that board, so the router's own completion count and KiCad's
connectivity check do not agree here; the gap is not yet explained.

The four hole-clearance errors the gate reports are the USB-C connector
footprint's own pads against its own mounting holes. They are present
in the unrouted input, they appear identically in the human reference
layout, and no placement or routing can move a pad relative to its own
footprint's holes. The hand-routed reference introduces two more of its
own, plus 19 other errors, at 73 unconnected.

All of the above is measured under kicad-cli 10.0.5. An earlier
revision of this section recorded 192/192 connections with 0 DRC errors
and 0 unconnected items under KiCad 10.0.4, whose zone filler and DRC
scored the attempts differently and selected a different winning
attempt. That baseline moved with the toolchain, not with the router.

### Copper pours

`--plane NET:LAYER` pours a real zone: klayout emits the KiCad zone
(solid pad connections, island removal), gives every SMD pad of the net
a via drop to the plane, lets thru-hole pads connect through the fill,
and reserves the layer against other nets' tracks (their vias still pass
through — the fill pours around them). The DRC step runs with
`--refill-zones --save-board`, so the output board is verified *and*
saved with its fill computed. Measured configurations on CANNONBALL,
all at 0 DRC error violations:

| Configuration | Unrouted |
|---|---|
| no pour, netclass 0.6 vias | 5 |
| `--plane GND:In2.Cu`, 0.6 vias | 3 |
| `--plane GND:In2.Cu --via-size 0.5` | 2 |
| no pour, `--via-size 0.5 --via-drill 0.3` | **0** |
| GND pour + power group on In1, 0.6 vias | 14 |

**The complete-board recipe** — zero unrouted, zero DRC error
violations, netclass 0.6/0.3 vias, a real verified GND plane, copper
reuse and manufacturing-correct same-net via spacing:

```sh
klayout --input-dir boards/ --output-dir routed/ \
       --layers 4 --plane GND:In2.Cu --grid 0.05
```

The 0.05 grid matters: this board's footprints sit on mixed mil/metric
coordinates (origins largely on a 1-mil grid, pad offsets metric), and
0.05 mm resolves enough of the legal track corridors and via gaps that
the router closes every connection — 0.1 mm leaves ~5 unrouted and
0.04 mm (finer but worse aligned) does not help. The endgame can also
place analytically validated off-grid vias and, when the rules allow,
minimum-size vias for stragglers. Grouping
the voltage nets onto In1 starves the signals of that layer (14), the
same lesson as two pours. Pour zones flood every copper layer like hand
layouts do; the reserved layer is the guaranteed plane and the other
fills are additive.

Two pours (GND + 3V3) starve the signal layers and do worse — one
ground plane is the sweet spot on a 4-layer board this dense.

Pour layers are not walled off: signal nets may route through them as a
last resort (a 4x cost multiplier keeps traffic away). Fill integrity is
preserved by construction — on a pour layer a foreign track must keep a
plane rib (two zone clearances plus the zone minimum thickness, 0.85 mm)
between itself and any static copper, the board edge, or another net's
incursion, so every incursion stays an isolated slot that cannot cut the
plane edge-to-edge. Vias passing through the plane need no such guard (a
via barrel is a small closed slot) and are unrestricted beyond normal
clearance. KiCad's refill + DRC in the verification step remains the
ground truth that no fill island is ever orphaned. When
connections remain after the rip-up rounds and the board's
`min_via_diameter` allows a smaller via than the net class, an endgame
pass automatically retries the stragglers with minimum-size vias
(snapshot-protected, so it can only improve the result).

Future quality work: per-netclass track widths/clearances.

Debugging aid: set `KLAYOUT_DEBUG=1` to print, for each failed
connection, the seed/target cell counts of both pads — `seeds=0` means
the pad's copper is entirely blanketed by obstacles (a modeling
problem), while nonzero counts mean the maze search genuinely found no
corridor (a congestion problem).

## Current limitations

- Only through vias; no blind/buried vias or microvias.
- Nets that already have some copper in the input are skipped, not
  completed.
- Trapezoid and custom-shape pads are still bounding circles (their true
  outline is not parsed), so channels next to them may be refused.
- The outline is enforced as "stay clear of the edge geometry"; a track
  cannot cross Edge.Cuts, but exotic outlines with interior cutouts rely
  on that blocking alone.
- Zones/pours present in the *input* board are not treated as obstacles
  (pours *emitted by klayout* are fully modeled).
- One clearance/track width for ordinary nets; differential pairs get
  their own impedance-solved width and gap, and power rails from
  `power.json` get IPC-2221 ampacity widths, but there are no general
  per-net-class rules.
- Ampacity widening sizes tracks only; via *thermal* capacity is not
  checked (the IR-drop pass does model via barrel resistance, so a
  starved single-via neck shows up as excess drop, but a via running
  hot within the drop budget does not).
- Differential pairs need equal P/N pad counts (2–8 per member);
  unequal or larger fan-outs route as ordinary nets with a note.

## Power rails: ampacity trace widening

If a `power.json` sits next to the input board — written by hand or
generated by the schematic tool — its power rails are routed at the
width their current demands. The format is the layout tool's
power-delivery model; klayout reads the subset it needs:

```json
{
  "gnd_nets": ["GND"],
  "nets": {
    "VBUS": {
      "voltage": 5,
      "supply": "J1.1",
      "loads": [{ "pad": "U2.3", "current_mA": 1500 },
                { "pad": "U4.8", "current_mA": 500 }]
    },
    "3V3": { "current_mA": 800 }
  }
}
```

Each rail's draw is the sum of its declared load currents (the
net-level `current_mA`/`current_A` shorthand works when no loads are
listed; rated *supply* currents are capacity, not consumption, and are
ignored). The minimum track width for that draw comes from the
IPC-2221 external-layer ampacity formula — `I = 0.048 · ΔT^0.44 ·
A^0.725`, ΔT = 10 °C, copper thickness from `stackup.json` (default
35 µm) — and the rail routes at `max(class track, IPC width)`:
widening only, never narrower than the class. The substitution happens
at the router's single choke point, so search halos, stub validation
and emission all see the wide track; DRC clearances are honored at the
new width automatically.

Every decision is printed at run start:

```
power: VBUS draws 2000 mA -> track 0.781 mm (IPC-2221, 35 um copper, dT 10 C; class 0.254 mm)
```

A rail asking for more than 2 mm of copper gets a note suggesting
`--plane NET:LAYER` instead — a maze-routed trace that wide rarely
fits. `--no-widen` turns the whole pass off for routability
comparisons. Nets named in `power.json` but absent from the board are
reported, not silently ignored.

### Auto-power: inferred maximum currents

A power-supply board with no `power.json` still declares its own
maximum currents if you read the copper's paperwork, and klayout
does: the fuse's rating (from its Value, e.g. "1.1A HOLD") bounds
the input; the series chain — fuse, protection diode, regulator,
inductor, output — says which nets carry it (walked through two-pin
F/D/L parts and bridged through small converter ICs, never into a
ground net, so catch-diode and TVS shunt legs stay out); and a buck
MULTIPLIES current downstream: with the input voltage from a
connector Value ("12V INPUT") and rail voltages from net names
("+5V_OUT"), I_out = I_in x Vin/Vout at eta = 1 — conservative for
sizing. Every inference prints its reasoning, the rails feed the
same IPC-2221 machinery, and the model is written to
`OUT/auto-power.json` in the real power.json format — review it and
copy it next to the input board to make it authoritative. A real
`power.json` disables all inference; `--no-widen` disables this too.

### IR drop

Ampacity says the trace won't overheat; the IR-drop check says the
load still sees its voltage. When a rail declares a supply pad and
per-load draws, the routed copper is measured after routing: DC nodal
analysis of the rail's own network — every segment contributes
`R = ρ·L/(w·t)`, vias and thru-pads join layers as plated barrels,
the supply pad anchors 0 V, each load draws its declared current. No
SPICE involved: the network is a few dozen resistors and klayout
solves it directly.

The worst load's drop is judged against `max_drop_mv` (per net, or
file-level for all rails; absent = report only):

```
power: V5 IR drop 37.8 mV worst, at J2.1 (2000 mA), budget 20 mV — OVER
power: V5 widening 0.781 -> 1.552 mm for the drop budget, re-routing
power: V5 IR drop 19.0 mV worst, at J2.1 (2000 mA), budget 20 mV — OK
```

A miss widens the rail (drop scales with 1/width) and re-routes it
with the full machinery — frozen differential pairs respected, up to
three rounds, capped at 3 mm. If the wider trace no longer fits, the
previous copper is restored and the shortfall is reported as a
`*** POWER WARNING ***` with the `--plane` suggestion — never hidden.
Rails poured as planes, fed through unmodeled copper, or hand-routed
in the input are reported as such and left alone.

## Differential pairs

If `diffpairs.json` sits next to the input board (`{"pairs": [{"p":
"NETP", "n": "NETN", ...}]}`), klayout length-matches each pair after
routing using full wiggles — single-sided serpentine meanders (arc
caps by default; `--square-wiggles`/`--sine-wiggles` restore the
older shapes) inserted along the shorter member's longest straight
segments (falling through to shorter segments when a run is
corridor-locked beside its partner), every leg validated against the
exact geometry, amplitude capped at 3 track widths, self-crossings
banned — and reports aligned columns of P/N routed lengths and
intra-pair skew.

Pairs are first attempted **coupled**: one centerline search per pair
(partner nets merged so neither blocks, virtual track wide enough for
both members plus the intra-pair gap, single layer), with P and N
emitted as mitered parallel offsets — exact-validated segment by
segment — and the ends trimmed clear of the pin fields so each pad
joins by an independent breakout stub. Through-hole endpoints
(Ethernet magnetics, jacks) couple too: they exist on every copper
layer, so the working layer comes from the SMD side. Pairs that
don't fit fall to the flip-symmetric machinery below, and the wiggle
matcher covers the lengths either way. On xlator this puts all three
MIPI lanes at identical 39.489 mm — 0.000 intra-pair skew and 0.000
inter-lane spread.

When BOTH the coupled attempt and every flip-symmetric escalation
fail, a **rescue coupling** gets one last shot with three extra
freedoms — it runs strictly last, so it can never take a working
pair away. (1) Gather rings: a double-width corridor cannot exist
inside a fine-pitch pin field, so the centerline may start and end
at candidate gather points ringing each end 1.8–3 mm out, the way a
human gathers a pair outside the breakout zone. (2) Symmetric layer
flips: the centerline may via (doubled cost — one flip is two
barrels); at each flip the P via sits on its polyline, the N via
staggers ~0.9 mm along its own, both jog outward when the barrel
outgrows the pair pitch, and every site passes the exact analytic
via check before any copper is emitted. (3) Routed breakouts: each
member reaches its gather point as a normal validated route; the
second member's via count is pinned to the first's (the counted-via
search), so flip symmetry survives the pin field. Twisted results
and unreachable gathers retry with the offending endpoints removed;
whatever still fails falls back to ordinary routing, honestly
reported.

Pairs that cannot couple fall back to **flip-symmetric, co-layer
routing**: one member routes freely, and its partner is routed with a
constrained search — the A* state carries a via counter, the goal is
accepted only at the member's exact flip count, via hops may land only
on the member's layer sequence, and cells more than ~2 mm from the
member's path carry a shadow-corridor penalty so the partner flies
beside it and flips at nearby spots. If the partner cannot follow, the
roles swap and the search runs the other way round. The point of all
of this is DELAY matching, not just length matching: stripline and
microstrip layers propagate at different speeds, so a pair is only
truly matched when both members put the same length on the same
layers. The report measures that directly as `off-layer` mm (half the
summed per-layer length difference between the members; 0 = co-layer),
and the placement loop budgets it at 2.0 mm.

The skew wiggles are layer-aware for the same reason: intra-pair bumps
go on the layer where the short member lacks copper relative to its
partner, and inter-lane extensions go on the layer both members share,
so length matching does not un-balance the layers.

**Once a pair is routed, it is frozen.** Raul: the differential pairs
are the most important copper on the board — iterate until they are
done, then don't touch them. Routed pair copper is static for every
other net: included in the rip-search's obstacle maps, never
soft-annotated as rippable, never ignorable in the analytic checks.
Everything else routes around the pairs, never through them.

The symmetric search shadows **per stretch**: while the partner is
between its i-th and i+1-th vias, only cells within ~2 mm of the
member's i-th stretch are penalty-free, so the flips land at nearby
spots and both members split their length over the layers the same
way (an xy-only corridor let the partner flip anywhere along it).
Both role orders (P-first and N-first) are tried, and a success that
is lopsided — partner much longer than its member, or split across
the propagation classes differently — loses to the better order.
When the natural flip count strands the partner entirely (a member's
0-via path can foreclose the only same-layer route back for its
partner), the search ESCALATES: the member is re-routed forcing 2,
then 4 flips, each opening a fresh layer for the partner to shadow.
Off-layer copper itself is measured per propagation CLASS, not per
layer: one member on F.Cu while the other runs on B.Cu is electrically
symmetric (same microstrip height over the same plane) and does not
count; microstrip-vs-stripline copper does. Pair order rotates with
the routing seed — the first pair laid gets first pick of the
corridors, so each attempt gives a different pair the advantage.

After the rip-up rounds settle, a **pair repair pass** re-checks every
pair: any that ended off-layer or flip-unbalanced (rounds re-route
ripped members with no layer discipline) is ripped and routed again as
a pair in the settled board, one pair at a time, each under its own
snapshot — kept only if it strictly improves and never at the cost of
a routed connection. The hard-nets-first reorder pass also exempts
intact pair nets from its wholesale rip. Known limit: pair members
ripped as blockers during the rounds can still end off-layer when the
repair search finds no constrained path in the settled board — rip
protection for pair copper is the open work item (see the
`pair-protection-wip` branch).

### Multi-drop pairs

A differential pair is not always two pads a side: CANNONBALL's USB
pair fans from the connector's mirrored pads to the MCU — four pads
per member — and used to be silently skipped by the pair machinery.
Members with equal pad counts (up to 8) are decomposed into PORTS
(each P pad grouped with its nearest N pad), the ports spanned by a
minimum spanning tree, and every span routed through the coupled and
symmetric machinery with the full budget treatment. A span's fallback
may only rip copper that span itself added, and the connection
records the router trusts are written per span and die with their
copper — the audit trail behind both rules is a false-complete bug
where the router declared victory over missing copper. The DRC gate
now also requires ZERO UNCONNECTED items per attempt, so that class
of lie cannot reach an accepted board.

### Parallel attempts

The iterate-until-done attempts are independent, so they run as
concurrent child processes (one per attempt, waves sized to the CPU
count) with the winner selected exactly as the serial loop would:
the lowest attempt that meets every gate, else the best score —
deterministic, byte-identical winners at the wall time of the
slowest single attempt instead of the sum. xlator's 8-attempt hunt:
36 seconds instead of ~6 minutes; CANNONBALL's: ~32 minutes instead
of an hour or more. `--board NAME` restricts a directory run to one
board (used by the workers; handy standalone too). KLAYOUT_SERIAL=1
forces the serial loop.

### Pre-routed pairs

Copper already in the input file is the user's: any net with existing
tracks is left untouched by routing ("already has tracks, skipping"),
and its copper is static — nothing may rip it. A hand-routed
differential pair is therefore a hard corridor the rest of the board
routes around. It is still MEASURED and held to the same budgets as
router-laid pairs — lengths, skew, via counts and off-layer copper
all include input copper — so hand-laid skew cannot evade the SI
verdict by reporting as zero.

One modification IS sanctioned, because it is the point of laying the
pair by hand: **pre-routed pairs are length-matched FIRST**, before
anything else routes. The skew matcher may split the user's own
straight runs to insert meanders on the short member (`pre-routed
pair P / N: length-matched N, skew 2.001 -> 0.000 mm`), and the
matched pair is then frozen with the whole board routing around it.
A hand route carrying a LONG DETOUR — lane length beyond ~1.35x the
direct pad-to-pad run — is re-laid instead (`pre-routed pair P / N:
54.956 mm is a long detour over the 34.377 mm direct run; re-laying
the pair`): matching it would force the whole detour into every
lane-mate's meanders, so the tool rips the hand copper and routes the
pair to length with everything else. Group-level budgets still apply
to what remains: a long-but-legal hand route fails inter-lane spread
honestly rather than burying tens of millimetres in meanders. Feeding a routed board back in also does
not stack a second pour: an existing zone for the plane net is
detected and reused.

### Impedance-matched pair geometry

Pair copper is not routed at the net-class track width: each pair's
width and gap are solved from its standard's differential impedance —
100 ohms for MIPI CSI/DSI, LVDS and Ethernet MDI, 90 for USB, 85 for
PCIe — using Hammerstad-Jensen microstrip and IPC-2141 edge-coupled
corrections on the stackup. A `stackup.json` next to the board
supplies the fab's real numbers — `{ "er": 4.2, "copper_um": 35,
"microstrip_h_mm": 0.2104, "stripline_b_mm": 1.1 }` — and is
reported when loaded; without one the assumptions are 35 um copper,
er 4.3, 0.21 mm microstrip height, 1.0 mm stripline spacing (printed
with every
solution so a wrong assumption is visible, e.g. `impedance (MIPI
CSI-2): 100 ohm differential -> track 0.172 mm, gap 0.101 mm`). The
pair report then shows every pair's modeled impedance weighted by
where its copper actually runs — `impedance: target 100 ohm, ~100.0
ohm length-weighted (100% microstrip @ 100.0, 0% stripline @ 102.9)`
— and a hand-routed pair honestly reports "geometry as laid, not
modeled" rather than claiming numbers for copper the solver did not
shape. The
gap floor is the board clearance plus margin, so the solved geometry
is always DRC-legal. Coupled sections, symmetric routes, breakout
stubs and skew wiggles all use the pair's solved width.

### Honest length matching

The wiggle length-matcher refuses to fake it: bump copper is marked
and never used as the base for further bumps (compounding bumps
produced self-crossing copper lattices), and asks beyond a sane bound
(25% of lane length inter-lane, 5 mm intra-pair) are declined with a
message — a member that long relative to its partner is a routing
problem, and hiding it in wiggles would only make the copper worse
while the skew number lied.

### DRC-gated acceptance

Each placement attempt's board is checked with `kicad-cli pcb drc`
inside the loop: zero error-severity violations is part of the
acceptance bar, so pair metrics can never select a board with shorts
as "best".

Pairs whose `"standard"` requires it (MIPI/CSI/DSI, LVDS, PCIe, USB3)
are also **inter-lane matched**: every lane in the group is extended
toward the longest lane, tighter member first with the partner matched
to what it actually achieved — so intra-pair skew (the strict budget)
always wins over inter-lane spread when a corridor-locked lane cannot
take the full extension. A group summary line reports the longest lane
and the residual spread. Ethernet MDI pairs are intra-matched only
(pair-to-pair skew is a non-issue at board scale for the PHY). On the xlator board, 6 of 7
pairs match to 0.000 mm (the seventh is limited by available straight
runs at 0.783 mm).

Routed paths are also straightened by string-pulling: within each
same-layer stretch the emitter pulls the longest exactly-legal straight
segments through the grid path's corners, eliminating the staircase
wobble grid searches produce (6× fewer segments on large boards).

## Verifying results

KiCad's command-line DRC is the ground truth. The regression suite in the source repository
closes the loop automatically: after checking each routed board against
its baseline, it runs `kicad-cli pcb drc --severity-error` on both the
input and the output, and fails unless the routed board has **0
unconnected items** and **no violations beyond those already present in
the input** (pre-existing footprint defects are not the router's fault,
but anything the router adds is). `kicad-cli` is found on PATH or at the
standard macOS location; override with the `KICAD_CLI` environment variable.

**Baselines require kicad-cli, and are only comparable against runs that
had it.** Without kicad-cli the suite still runs and still compares
baselines — the DRC and SI steps are skipped with a notice — but DRC is
also part of the *acceptance gate* that picks which attempt gets kept
(zero error violations and zero unconnected, see **DRC-gated
acceptance**). With no DRC to fail, the gate collapses to the router's
own metrics and the first attempt is accepted immediately. The board that
comes out is therefore a different board, and baselines recorded with
kicad-cli will not match a run without it, in either direction. Record
and check baselines on a machine that has it. For the same reason,
baselines are pinned to a KiCad *version*: an upgrade that reports one
more violation can change which attempt wins.

To check a board manually:

```sh
kicad-cli pcb drc --severity-error -o report.txt routed/board.kicad_pcb
```

## License

Trial software, free to evaluate. `LICENSE` carries the terms; the two
that matter most in practice:

- **What it produces is yours.** Routed boards, gerbers, drill files,
  pick-and-place, verdict JSON — use them for anything, personal or
  commercial, no royalty and no attribution. Your input designs stay
  yours too. The included example board is free to use and modify as
  well.
- **Nothing is guaranteed.** The software comes with no warranty, and a
  run that reports zero DRC violations and every gate met is this
  program grading its own work — not an assurance that a board is
  correct, manufacturable, or safe. Placement, routing, ampacity
  widening and impedance geometry are heuristics and can be confidently
  wrong. Verify every layout independently before fabricating,
  energizing, or selling it.

Copyright (c) 2026 Seagull Work, Inc. Redistributing the executables,
and use beyond evaluation, need separate terms — ask.
