# klayout v2026.09.17-1368-gb0acefe9

Public release of klayout and kplace for Darwin arm64.

Contents: the executables, README.md, LICENSE, example/ (KiCad boards to route) and parts/ (the parts
and fab data those boards need).

## Changes

- Router records follow the copper: when a late pass (the retry after the prune, or the revisit
  round) reports a net closed while its copper is still in pieces, the net is counted open at
  once, so it gets the remaining passes and the final report never says routed over split copper.

Checksums: SHA256SUMS.

## Regression

make regression on v2026.09.17-1368-gb0acefe9: 6 of 6 boards PASS (run 2026-11-20 20:26:20 rev v2026.09.17-1368-gb0acefe9 kicad-cli 10.0.6 fab-library 40821de2)
