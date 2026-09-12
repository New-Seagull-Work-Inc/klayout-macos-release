#!/usr/bin/env python3
"""Recompute gerber2ems S-parameters from the stored port probe data,
normalized to each port's declared impedance, then postprocess (no re-run)."""
import sys, os, numpy as np
os.chdir(sys.argv[1]); sys.argv=['gerber2ems','-p']
import gerber2ems.main as M
from gerber2ems.config import Config
from gerber2ems.postprocess import Postprocesor
from gerber2ems.simulation import Simulation
from gerber2ems import importer
args=M.parse_arguments(); Config.load(args); M.setup_logging(args); cfg=M.cfg
importer.import_stackup(); importer.import_port_positions()
frequencies=np.linspace(cfg.frequency.start, cfg.frequency.stop, 1001)
post=Postprocesor(frequencies, len(cfg.ports))
for index, port in enumerate(cfg.ports):
    if port.excite:
        sim=Simulation(); sim.load_geometry(); sim.add_virtual_ports()
        reflected, incident = sim.get_port_parameters(index, frequencies)
        for i,_ in enumerate(cfg.ports): post.add_port_data(i, index, incident[i], reflected[i])
post.calculate_sparams(); post.sparam_to_file()
M.create_dir(M.RESULTS_DIR, cleanup=True); M.postprocess(); print('recalculated')
