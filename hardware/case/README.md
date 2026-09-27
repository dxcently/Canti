# VOX necklace case

A 3D-printed pendant for the 5×7 cm protoboard with the Pico 2 W, one button, the status LED and an I2S mic. It is fully parametric: [`vox_case.scad`](vox_case.scad) (OpenSCAD). Measured values go in the variables at the top, and every hole moves with them.

- **Outside size:** about 55 × 75 × 20 mm, plus an 11 mm loop at the top.
- **Lid (worn against the chest):**
  - holes for the button plunger and the LED;
  - **the microphone.** The round INMP441 module clips into a pocket on the inside of the lid, with its sound hole over a 2 mm hole in the lid. A 5-wire cable plugs onto a small right-angle header on the protoboard, so the whole lid (mic included) can be unplugged and set aside. See [The microphone](#the-microphone).
  - The lid slips into the walls (a loose fit, `lid_fit`) and **two rubber bands** hold it shut. Each band wraps around the width, over the lid, down both sides and under the back, in a shallow groove that keeps it from sliding. The grooves (`band_ys`) sit clear of the button, the LED and the mic hole. Use ordinary ~3 mm office bands; set `bands = false` for a plain lid.
- **Back (worn facing out):** closed. (Earlier versions had the mic port here; it is gone.)
- **Top:** one necklace loop at the centre. Its hole runs side to side, parallel to the face, so the case hangs flat. **Wear it lid-in**: the lid, and with it the mic hole, faces your chest. Add a small weight at the bottom or side if it tends to flip. The button and LED end up against your chest too; that is intended.
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
| `out/mic_clip.stl` | flat | 1 (print 2–3: they are tiny and easy to lose) |
| `out/fit_test.stl` | back face down | optional: the bottom 9 mm of the base, a quick check that the board drops in and the posts are the right height |
| `out/mic_test.stl` | outer face down | optional: the lid's mic pocket on a 21 mm plate (about 10 minutes). Check that your module, the foam ring and the clip fit before printing the whole lid |

- PLA, 0.2 mm layers, no supports.
- The only bridges are the 10 mm fabric recess on the lid's outer face (it is on the bed side), the two zip-tie tunnels in the lid's strain relief, and the zip-tie slot on the base tab; all are short enough for PLA.
- If the 2 mm mic hole prints undersized, open it with a 2 mm drill bit turned by hand.
- If the lid binds, raise `lid_fit` and re-export only the lid. The bands do the holding, so loose is fine.

**What changed with the lid-mounted mic, and what to reprint:** only the lid (plus the new clip) is new. The base only lost the old mic pocket and back port, so **a base you already printed still works**: stick a piece of tape over its old 2 mm back hole. The pocket ring left on its floor sits under the board, clear of the new wiring. The plunger is unchanged. No fitted dimension moved: board, Pico, USB notch, button, LED, bands and loop are all as before.

## The microphone

### What to buy

| Part | Count | Notes |
|---|---|---|
| **INMP441 I2S microphone module, the round one** (about 14 mm across, 6 pins) | 1 | sold as "INMP441 omnidirectional microphone module I2S". Get one **without the header soldered on** ("unwelded"). The loose header strip it usually comes with is not needed |
| Female Dupont jumper wires, about 20 cm (female–female or female–male) | 5 | you cut them in half. Get the kind with removable single housings if you want to combine them (below) |
| **5-pin right-angle male header**, 2.54 mm pitch | 1 | break it off a 40-pin right-angle strip ("90 degree pin header") |
| 1×5 Dupont housing, 2.54 mm (optional) | 1 | puts the 5 wires in one connector, so it only goes on one way round |
| 2 mm EVA craft foam, or 2 mm self-adhesive foam tape | a scrap | for the foam ring. Thicker foam works too: raise `mic_seat_h` (see *Measure before printing*) |
| thin fabric (old T-shirt) or thin foam | a scrap | 10 mm disc for the outside of the mic hole, against wind and rubbing |
| hot glue, or a small zip tie (2.5 mm wide) | | strain relief on the lid |

### How it sits

The module has 6 pad holes in **two rows of 3**, the rows 7.62 mm apart, and its sound hole goes **through the module's circuit board, at the centre**, on the side where the pin names are printed. The MEMS chip (the small metal box) is on the other side. The INMP441 is a "bottom port" part: it hears through the board it is soldered to.

So the module goes in **label side (sound hole) towards the lid**, chip side into the case:

```
 outside      fabric disc (in the 10 mm recess)
 ==========   lid, 2 mm hole
   [ foam ]   foam ring around the hole, squeezed to 1.2 mm
 ---------    module: labels + sound hole up (towards the lid), chip down
   ( clip )   printed C-ring in the pocket's groove
    | | |     5 wires, straight out of the chip side
```

- A printed seat ring at the pocket's rim holds the module 1.2 mm off the lid (`mic_seat_h`), so the solder on the pads can never touch the lid or tilt the module.
- The foam ring (5 mm outside, 2.5 mm hole) is squeezed between the lid and the module around the sound hole. The mic then hears through the lid's hole and not the air inside the case, and the foam also keeps button clicks in the lid from reaching the module.
- The C-shaped clip snaps into a groove in the pocket wall and holds the module against the seat. It only touches the module's outer rim, clear of the pads.
- The mic hole sits in the top-right of the lid, 28 mm from the button (fewer clicks picked up), clear of the rubber-band groove, and about 7 mm to the side of the Pico's antenna end (not over it).

### The cable

- Five wires, soldered straight into the module's pad holes: **VDD, GND, SD, WS, SCK**. **L/R is bridged to GND on the module**, so it needs no wire of its own (the firmware reads the left channel).
- The other end is the wires' female Dupont ends, pushed onto a **5-pin right-angle header** soldered on the protoboard. A right-angle header lets the plug lie flat on the board: a vertical header plus plug would stand about 14 mm tall, and there are only 10 mm under the lid.
- **Length: 8–9 cm** from the module's pads to the back of the Dupont housing. That is enough to set the lid down beside the case while it stays plugged in, and still short enough to fold in the case when it is closed (it needs about 5.5 cm; the rest folds in the space between the button and the right-hand wall).
- **Strain relief:** about 1 cm from the pads the cable runs through a short channel on the lid (two small walls next to the LED hole). Fix it there with a blob of hot glue, or a small zip tie through the two tunnels at the channel's floor and around the walls and the wires. Then all the bending happens there, not at the solder joints.

### The header on the protoboard

The layout shows it: **5 pins in column 9, rows 3 to 7**, the plug pointing right (towards the right-hand wall), below the button. It is clear of the Pico (one free column between them), the button, the LED and the plunger, and the plug's wires have 6 mm behind it to bend up.

| Header pin (column 9) | Signal | Protoboard wire (under the board) to | Pico pin |
|---|---|---|---|
| row 3 | GND | column 7, row 2 | pin 3 (GND) |
| row 4 | 3V3 | column 0, row 4 | pin 36 (3V3 OUT). **Not** pin 39 or 40 (rows 1 and 0 of column 0) |
| row 5 | SD | column 0, row 14 | pin 26 (GP20) |
| row 6 | WS | column 0, row 15 | pin 25 (GP19) |
| row 7 | SCK | column 0, row 16 | pin 24 (GP18) |

The row numbers of the Pico's pins are the ones in [`../../firmware/HARDWARE.md`](../../firmware/HARDWARE.md), Part C (the Pico chips up, USB at the bottom edge).

### Mic wiring, pad by pad

| Mic pad (as printed on the module) | Goes to | Header pin (column 9) |
|---|---|---|
| **GND** | wire → | row 3 |
| **L/R** | a short bridge wire to the module's own **GND** pad (no cable wire) | |
| **VDD** | wire → | row 4 (3V3) |
| **SD** | wire → | row 5 |
| **WS** | wire → | row 6 |
| **SCK** | wire → | row 7 |

On the module, **GND, VDD, SD** are one row of 3 and **L/R, WS, SCK** the other, with GND facing L/R across the sound hole. Always go by the printed names on your module: if they differ, they win. Other names for the same pins: SCLK/BCLK = SCK, LRCL/LRCLK = WS, DOUT/DATA = SD.

### Assembly, step by step

Do it with the USB cable unplugged.

1. **Print the test piece first** (`mic_test.stl` and `mic_clip.stl`, ~15 minutes). The rest of the steps can be tried on it.
2. **Cut the foam ring.** From 2 mm foam, cut a disc about 5 mm across. Make a hole in the middle, about 2.5 mm: push a hot soldering iron tip through (outdoors or near a window), or cut it with a craft knife. Stick it on the inside of the lid, centred on the 2 mm hole: self-adhesive foam sticks by itself; otherwise a tiny dot of glue at its edge, **never over the hole**.
3. **Prepare 5 wires.** Cut 5 female Dupont jumpers so each piece keeps its female end and is about 10 cm long. Strip 2 mm at the cut end and twist the strands. Tin the end: heat it with the iron and touch solder to it until it is shiny.
4. **Solder the wires to the module.**
   - Lay the module **label side down** on the table, chip side up. The labels are now underneath, so note which hole is which first (take a photo of the label side).
   - Push each wire **from the chip side** into its pad hole until the insulation touches the board. Heat the pad and the wire together for 1–2 s and add a little solder. At most 3 s per pad, so the tiny mic is not cooked.
   - **Keep solder and flux away from the sound hole** in the middle. A bit of masking tape over the hole on the label side while you solder helps; remove it afterwards.
   - Wires: GND, VDD, SD, WS, SCK. Nothing into L/R yet.
5. **Bridge L/R to GND.** Take a short piece of thin insulated wire (or a cut-off resistor leg with a bit of insulation on it), about 1.5 cm. Solder one end into the **L/R** hole from the chip side, bend it round the outside of the chip, and solder the other end onto the GND wire's joint. It must not touch the chip or any other pad.
6. **Check the label side.** Turn the module over. If a wire tip sticks out of a pad, snip it flush. Nothing on this side may stand higher than about 1 mm, and the sound hole must be clear: hold it up to the light.
7. **Test the mic before closing anything.** Plug the 5 female ends straight onto the breadboard setup or the protoboard header (below) and run the *Microphone checklist* in `firmware/HARDWARE.md` (`mic level`).
8. **Make the plug.** Optional but recommended: pull the single plastic housings off the 5 female ends (lift the little latch with a pin) and push the metal crimps into one 1×5 housing, in the order **GND, 3V3(VDD), SD, WS, SCK**. Mark the GND end of the housing and the GND pin (row 3) on the board with a dot of paint or marker. Without a combined housing, label the 5 wires with tape flags instead.
9. **Solder the right-angle header** on the protoboard: short legs through **column 9, rows 3–7**, from the component side, horizontal pins pointing right. Solder under the board, trim the tails to under 2 mm, and wire it as in the header table. Use insulated wire wherever a wire crosses other pads. The underside is a **mirror image**: seen from below, column 0 is on the right.
10. **Clip the module into the lid.** Lay the lid outer face down. Put the module into the pocket, **label side down** (towards the foam ring and the lid), wires pointing up at you. Squeeze the C-clip a little and push it into the pocket over the module until it snaps into the groove; tweezers help. The module should sit flat on the seat and not rattle. If the clip does not go in, your module is thicker than 1.0 mm: measure it and set `mic_pcb_t` (see below). If the module still rattles, one dot of hot glue on the clip fixes it.
11. **Strain relief.** Gather the 5 wires into a bundle, lay them through the little channel next to the LED hole (about 1 cm from the pads) and fix them with a blob of hot glue, or a small zip tie through the two tunnels at the channel floor and around the walls and the wires.
12. **The fabric disc.** Cut a 10 mm disc of thin fabric and glue it into the recess on the outside of the lid **by its rim only**, so the glue does not close the hole.
13. **Close the case.** Plug the cable onto the header (GND mark to GND mark). Fold the spare cable into the space between the button and the right-hand wall, away from the plunger. Put the lid on (it only goes one way: the LED through its hole) and put the two rubber bands in their grooves. The lid rests on the walls and the corner posts, so closing it cannot crush anything; the foam ring is squeezed from 2 mm to 1.2 mm.
14. Run `mic level` once more with the case closed and check the button still clicks freely.

## Build the board to match

`out/layout.svg` is a 1:1 template of the protoboard, component side up.
- Print it at 100% and check the 40 mm bar with a ruler.
- It shows where the case expects each part:
  - the Pico's pin rows in columns 0 and 7, with USB at the bottom edge;
  - the button (one; see `android/PROTOCOL.md`, *The button*, for what each press does);
  - the LED (a single blue LED on GP13; use the kit's 100 Ω resistor, since through 220 Ω a blue LED at 3.3 V is dim);
  - the mic header (column 9, rows 3–7, with its signal names) and the area its plug lies on;
  - the circle under the lid's mic pocket: the mic and its wires hang about 5 mm down from the lid there, so keep everything on the board under that circle **lower than 4 mm**.
- The wiring itself (which GPIO each part uses) is in [`../../firmware/HARDWARE.md`](../../firmware/HARDWARE.md).

## Measure before printing

The defaults are guesses. Measure the built board and edit these:

| Variable | What to measure | Default |
|---|---|---|
| `board_w`, `board_l` | protoboard size | 50 × 70 |
| `above` | tallest part above the board top (usually the Pico on its headers, or the LED) | 10 |
| `under_gap` | solder tails and wires under the board | 4 |
| `pico_standoff` | gap between the board top and the Pico's underside | 2.5 |
| `switch_h`, `switch_size` | the tactile switches | 5, 6 |
| `mic_d` | the mic module's diameter | 14.0 |
| `mic_pcb_t` | the mic module's board thickness (calipers on the rim). The clip groove is placed for it, so this one matters | 1.0 |
| `mic_seat_h` | lid-to-module gap = the squeezed foam. Raise it for thicker foam (squeezed to about 60 %) or if your solder bumps are taller than 1 mm | 1.2 |

`under_gap` could now be about 3 mm, since the mic no longer lives under the board, but 4 is what you printed and it fits, so it stays.

## Where the mic's dimensions come from

Not yet measured on a real module; these are from the sources below. Measure yours and change the variables if they differ.

- **Board 14 mm across:** TinyTronics lists "PCB dimensions: 14 × 14 mm" and a male header set in the box ([TinyTronics INMP441](https://www.tinytronics.nl/en/sensors/sound/inmp441-mems-microphone-i2s)); the KiCad footprint below draws the board as a 14 mm circle.
- **Pins: two rows of 3, 2.54 mm pitch, rows 7.62 mm apart, sound hole at the centre:** the footprint in [barafael/inmp441-breakout-kicad](https://github.com/barafael/inmp441-breakout-kicad) (`inmp441.pretty/inmp441.kicad_mod`: pads at x = −2.54 / 0 / +2.54, y = ±3.81, a hole at 0,0; its author notes "the physical dimensions work"). Components101 also says "six pins, three on each side" ([components101](https://components101.com/modules/inmp441-mems-omnidirectional-microphone)).
- **Sound hole on the label side, chip on the other side; pin names GND/VDD/SD and L/R/WS/SCK in the two rows:** photos of both sides in the Arduino forum thread [How to soldering INMP441](https://forum.arduino.cc/t/how-to-soldering-inmp441/1430378), where the replies favour mounting with the hole facing the sound. Random Nerd Tutorials likewise says the small hole should face you ([RNT ESP32 + INMP441](https://randomnerdtutorials.com/esp32-inmp441-i2s-microphone-arduino/)).
- **Bottom port, 4.72 × 3.76 × 1.00 mm chip, hole in the PCB under it (0.5–1 mm recommended, at least 0.25 mm):** InvenSense datasheet ([INMP441 datasheet](https://www.mouser.com/datasheet/2/400/INMP441-1112508.pdf), also [on DigiKey](https://www.digikey.com/htmldatasheets/production/1431884/0/0/1/inmp441-datasheet.html)).
- **Assumed, not found in any source:** the module's board thickness (1.0 mm; the photos look thin) and the exact order of the pads within each row. Both are covered above: `mic_pcb_t`, and "go by the printed names".

Acoustics: the 2 mm lid hole plus the small space inside the foam ring resonate at roughly 12 kHz, above what the firmware records at 16 kHz sampling (up to 8 kHz), so the hum band is not coloured.

## Regenerate

```bash
cd ~/VOX/hardware/case
for p in base lid plunger mic_clip fit_test mic_test; do nix run nixpkgs#openscad -- -D "part=\"$p\"" -o out/$p.stl vox_case.scad; done
nix run nixpkgs#openscad -- -D 'part="layout"' -o out/layout.svg vox_case.scad
sed -i 's/stroke-width="0.5"/stroke-width="0.1"/' out/layout.svg   # thin outlines, so the small labels stay readable
nix run nixpkgs#openscad -- vox_case.scad        # GUI preview of the assembly
nix run nixpkgs#openscad -- -D 'part="clash"' -o /tmp/clash.stl vox_case.scad   # must fail with "top level object is empty"
```

After any change to the lid or the walls, run the clash check: it renders where the lid overlaps the base below the
wall top, and anything there means the lid won't seat.

Each STL export should report `Simple: yes`. The `.scad` file also checks the mic, strain relief and header positions against the grooves, LED, button, Pico and walls, and stops with a message if a change breaks one of them. Regenerate `out/` from the `.scad` file after any change.
