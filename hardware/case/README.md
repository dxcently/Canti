# VOX necklace case

A 3D-printed pendant for the 5×7 cm protoboard with the Pico 2 W, one button, the status LED and an I2S mic. It is fully parametric: [`vox_case.scad`](vox_case.scad) (OpenSCAD). Measured values go in the variables at the top, and every hole moves with them.

- **Outside size:** about 55 × 75 × 20 mm, plus an 11 mm loop at the top.
- **Back (body side):** the mic port, with an outside recess for a fabric or foam disc to reduce rubbing noise. The mic module sits in a pocket on the inside of the back wall, over the port, and connects to the board with six short wires.
- **Front lid:** holes for the button plunger and the LED. It slips into the walls (a loose fit, `lid_fit`) and **two rubber bands** hold it shut. Each band wraps around the width, over the lid, down both sides and under the back, in a shallow groove that keeps it from sliding. The grooves (`band_ys`) sit clear of the button, the LED and the mic port. Use ordinary ~3 mm office bands; set `bands = false` for a plain lid.
- **Top:** one necklace loop at the centre. Its hole runs side to side, parallel to the face, so the case hangs flat facing forward.
- **Bottom:**
  - a notch for the micro-USB cable to the power bank, which stays outside the case;
  - a tab under the notch: zip-tie the plug to it, so a tug on the cable pulls on the case and not on the Pico's micro-USB socket (those tear off).
  - Set `cable_tie = false` to drop the tab.

## Parts to print

| File | Print orientation | Count |
|---|---|---|
| `out/base.stl` | back face down | 1 |
| `out/lid.stl` | already flipped; outer face down | 1 |
| `out/plunger.stl` | flange down | 1 |
| `out/fit_test.stl` | back face down | optional: the bottom 9 mm of the base, a quick check that the board drops in and the posts are the right height before the full base |

- PLA, 0.2 mm layers, no supports.
- The only bridges are the 11 mm fabric recess on the back face and the zip-tie slot; both are short enough for PLA.
- The loop and tab are flat on the back face, so they print without supports too.
- If the lid binds, raise `lid_fit` and re-export only the lid. The bands do the holding, so loose is fine.

## Build the board to match

`out/layout.svg` is a 1:1 template of the protoboard, component side up.
- Print it at 100% and check the 40 mm bar with a ruler.
- It shows where the case expects each part:
  - the Pico's pin rows in columns 0 and 7, with USB at the bottom edge;
  - the button (one; see `android/PROTOCOL.md`, *The button*, for what each press does);
  - the LED (a single blue LED on GP13; use the kit's 100 Ω resistor, since through 220 Ω a blue LED at 3.3 V is dim);
  - the area under the board that must stay clear for the mic pocket.
- The wiring itself (which GPIO each part uses) is in [`../../firmware/HARDWARE.md`](../../firmware/HARDWARE.md).

## Measure before printing

The defaults are guesses. Measure the built board and edit these:

| Variable | What to measure | Default |
|---|---|---|
| `board_w`, `board_l` | protoboard size | 50 × 70 |
| `above` | tallest part above the board top (usually the Pico on its headers, or the LED) | 10 |
| `under_gap` | solder tails under the board, and the mic module's thickness | 4 |
| `pico_standoff` | gap between the board top and the Pico's underside | 2.5 |
| `switch_h`, `switch_size` | the tactile switches | 5, 6 |
| `mic_d` / `mic_square` | the mic breakout (`mic_square = true` for square modules) | 14.2, round |

Get a mic module **without soldered pins**, or remove them: pins won't fit in the 4 mm gap under the board.

## Regenerate

```bash
cd ~/VOX/hardware/case
for p in base lid plunger; do nix run nixpkgs#openscad -- -D "part=\"$p\"" -o out/$p.stl vox_case.scad; done
nix run nixpkgs#openscad -- -D 'part="layout"' -o out/layout.svg vox_case.scad
nix run nixpkgs#openscad -- vox_case.scad        # GUI preview of the assembly
```

`out/` is not tracked; regenerate it from the `.scad` file.
