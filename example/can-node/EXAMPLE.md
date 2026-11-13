A CAN bus node on four layers: placement from scratch, and the CAN differential pair routed to its impedance.

- Parts: MCP2515 CAN controller with 8 MHz crystal, SN65HVD230 transceiver, split termination behind a jumper, NUP2105L bus protection, screw terminal, reverse-polarity diode, NCP1117-3.3 regulator, power LED, host header. 23 parts, 27 nets.
- Board: 56 x 36 mm, 4 copper layers, JLCPCB's published 4-layer stackup.
- What the layout tool does: places every part (they start beside the board), routes it, and routes CANH / CANL as a 100 ohm pair.
- Built only from KiCad's standard symbol and footprint libraries.
- Not judged: the supply rails (this board states no rail voltages or currents).
