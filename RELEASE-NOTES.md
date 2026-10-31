# klayout v2026.09.17-696-gcaf3314 - macOS arm64

Built from source `caf3314` for Apple Silicon, macOS 14 or newer.

- Revalidate retained copper and component courtyards against destination mounting holes and rule areas.
- Keep SI pin landings routable and search distinct legal placements without counting duplicate poses as failed routes.
- Trim retained dangling ends onto actual same-net custom-pad copper; accept only when DRC improves without opening connections.
- Publish final DRC/ERC counts and corrected cinema metadata, including the selected board's post-cleanup warning count.

Validation: cinema-check, keepout-check, si-terminal-check, stack-room-check and hole-clearance-check pass. Reference camera run 111 has zero DRC/ERC violations on both boards.

Download `klayout-release.tar.gz` and extract it into `klayout/` beside Architect and the `designer-parts/` release. The package contains executables, a runnable example, board-house rules and documentation.
