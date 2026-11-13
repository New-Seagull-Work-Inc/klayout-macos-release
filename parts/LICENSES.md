# Licences and attribution

## KiCad library material
Footprints under `footprints/` whose `.source` names the KiCad library, and the
3D models they reference, come from the KiCad libraries
(https://gitlab.com/kicad/libraries/kicad-footprints,
https://gitlab.com/kicad/libraries/kicad-packages3D), licensed under
CC-BY-SA 4.0 with the following exception: "To the extent that the creation of
electronic designs that use 'Licensed Material' can be considered to be
'Adapted Material', then the copyright holder waives article 3 of the license
with respect to these designs and any generated files which use data provided
as part of the 'Licensed Material'." Where a footprint was modified (extra
stacked pad numbers), its `.source` says so; the modified file is under the
same licence.

## Footprints and models drawn by Seagull Work
Footprints whose `.source` says "Drawn by procurement" are drawn from the
maker's published land pattern and dimensions, and the box models from the
maker's published dimensions.

## Documents
Each document under `components/` has a `.source` naming the public URL it was
fetched from. The documents remain the property of their makers.

## Records
The part records (`components/*/*.json`) are Seagull Work's. Each states the
documents its figures come from.
