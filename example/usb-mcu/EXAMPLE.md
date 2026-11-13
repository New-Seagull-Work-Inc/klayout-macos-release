A USB full-speed microcontroller board on four layers: placement from scratch, and a USB 2.0 differential pair routed to its impedance and skew budget.

- Parts: USB-C receptacle, USBLC6-2SC6 ESD protection, STM32F042K6T6 microcontroller, AP2112K-3.3 regulator, 8 MHz crystal, reset and boot buttons, SWD header, two LEDs, two GPIO headers. 28 parts, 38 nets.
- Board: 60 x 40 mm, 4 copper layers, JLCPCB's published 4-layer stackup.
- What the layout tool does: places every part (they start beside the board), routes it, and routes USB D+ / D- as a pair through the ESD part to the microcontroller, held to 90 ohm +-15 % and a 1.27 mm length match.
- Built only from KiCad's standard symbol and footprint libraries.
- Not judged: the supply rails (this board states no rail voltages or currents).
