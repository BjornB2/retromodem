# RetroModem enclosure — prototype

These files are the current, unfinished enclosure design:

- `RetroModem.step`: CAD exchange file.
- `Retromodem_Bottom.stl`: printable bottom.
- `RetroModem_Lid.stl`: printable lid.

**Warning: the fit is tight.** Space for the MY018 infrared board has not yet
been incorporated. This is not yet a guaranteed fit or a complete enclosure for
the preferred build. Check clearance with your own components before use.

The existing prototype has room for an 18650 holder and a USB-C charging board.
Exact models and dimensions will be added later; do not choose parts solely
on the basis of these files.

A step-up module is used between the 18650 and the Raspberry Pi. In the current
prototype it is attached to the Pi with a drop of hot glue; there is no dedicated
mount in this design. This describes the prototype, not a validated mounting or
power-supply instruction. Power wiring, insulation, cell protection and the
charging circuit still need to be documented and reviewed.

The three supplied files are included unchanged. Geometric consistency between
the STEP and STL files has not yet been checked.
