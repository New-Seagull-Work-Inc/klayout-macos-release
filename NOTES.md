# klayout v2026.09.17-1366-ge0597a55

Public release of klayout and kplace for Darwin arm64.

Contents: the executables, README.md, LICENSE, example/ (KiCad boards to route) and parts/ (the parts
and fab data those boards need).

## Changes

- Stereo boards: the row drop toward the connector is steered per placement, by the row's own
  sensor or by every image sensor, whichever closes the lanes.
- Power rails: the final widening repeats while a pass still gains width.
- The live viewer keeps the last elapsed time and title when a run ends.
- A fab stackup named by the caller is honoured.
- Router and placer fixes for fine-pitch ball grids: pad escapes, via-site clearances, a
  surface-first pass for short links.

Checksums: SHA256SUMS.

## Regression

make regression on v2026.09.17-1366-ge0597a55: 6 of 6 boards PASS (run 2026-11-20 13:10:56 rev v2026.09.17-1366-ge0597a55 kicad-cli 10.0.6 fab-library 40821de2)
