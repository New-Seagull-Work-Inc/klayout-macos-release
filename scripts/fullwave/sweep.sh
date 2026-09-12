#!/bin/bash
# fresh copies of pristine slices (sliced once with the KiCad-python wrapper, which crashes on exit) + the full pipeline
for L in 6 8 10 12; do W=$HOME/opt/fullwave/${L}L-cur; cd $W; mkdir -p pristine
  for n in LPDDR4_DQS0 LPDDR4_DQ0 LPDDR4_DQ2; do
    [ "$n" = LPDDR4_DQS0 ] && d=LPDDR4_DQS0_Diff || d=$n
    if [ ! -f pristine/$d/$d.kicad_pcb ]; then
      rm -rf slices/$d; for try in 1 2 3; do $HOME/Library/Python/3.9/bin/si-wrapper slice --file net_configs/$n.json >/dev/null 2>&1; [ -f slices/$d/$d.kicad_pcb ] && break; done
      [ -f slices/$d/$d.kicad_pcb ] && { rm -rf pristine/$d; cp -r slices/$d pristine/$d; } || { echo "${L}L/$d SLICE FAILED"; continue; }
    fi
    rm -rf slices/$d; cp -r pristine/$d slices/$d
    $HOME/opt/fullwave/tools/run_slice.sh $W/slices/$d 2>&1 | grep -E 'rc=|WARN|Trace|Error'
    python3 $HOME/opt/fullwave/tools/readout.py $W/slices/$d
  done
done
echo SWEEP DONE
