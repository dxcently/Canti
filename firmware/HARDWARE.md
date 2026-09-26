# Building the VOX node on a breadboard

This guide assumes no electronics background. It builds the circuit from the Pico 2 W, the Elegoo starter kit (breadboard, 1 push button, a blue LED, one 100 Ω resistor, jumper wires) and an INMP441 microphone module. The kit's UNO board and its breadboard power module are **not used**.

It has three parts:
- **Part A: test the button and the LED.** Solder the headers, wire the button and the LED straight to the Pico, and check them from the serial console. Start here: it needs no microphone.
- **Part B: the microphone.**
- **Part C: moving to the protoboard** for the necklace case.

> **3.3 V only.** Everything here runs from the Pico's own 3.3 V pin (physical pin 36), powered by the USB cable. **Never** connect anything to the kit's 5 V: not the UNO's 5V pin, not the breadboard power module (MB102), not the Pico's VBUS (pin 40) or VSYS (pin 39). 5 V on a Pico pin or on the microphone can destroy them. Do all wiring with the USB cable **unplugged**.

## What you need

| Part | Count | Notes |
|---|---|---|
| Raspberry Pi Pico 2 W | 1 | plus its two 20-pin header strips |
| Breadboard (830 holes) | 1 | from the kit |
| Push button (4 legs) | 1 | from the kit (the small 6 × 6 mm one) |
| Blue LED, 5 mm (2 legs) | 1 | from the kit; the longer leg is + (anode) |
| 100 Ω resistor | 1 | from the kit; colour bands brown-black-black-black-brown, or brown-black-brown-gold |
| Male-to-male jumper wires | about 12 | from the kit |
| INMP441 microphone module | 1 | Part B. 6 pins; bought separately, it usually comes with a loose header strip |
| Micro-USB **data** cable | 1 | some cables only charge; if the PC sees nothing, try another |
| Soldering iron and solder | | for the headers |

## How a breadboard works (1 minute)

- The long sides have two **rails** each, marked red (+) and blue (−). All holes along one rail line are connected.
  - On some boards the line is broken in the middle; there the two halves are **not** connected until you bridge them with a wire.
- The middle has numbered **rows** (1–63) and lettered **columns** (a–j). In one row, holes **a–e** are connected together, and holes **f–j** are connected together.
  - The groove down the middle (the **centre gap**) separates the two halves.
- A part's leg connects to whatever is in the same row-half. Two legs in the same row-half are shorted together, so never do that unless the steps say so.

## Pico pin numbers

Pins are numbered 1–40 around the board. Hold the Pico with the **USB socket at the top** and the chips facing you:
- **Left edge**, top to bottom: pins **1 to 20**.
- **Right edge**, bottom to top: pins **21 to 40**. So pin 40 is top-right, opposite pin 1.

The pin names are printed on the back of the board. The ones used here:

| Pin | Name | Used for |
|---|---|---|
| 17 | GP13 | Bluetooth LED (through the 100 Ω resistor) |
| 18 | GND | ground for the button and the LED |
| 19 | GP14 | the button |
| 24 | GP18 | mic SCK |
| 25 | GP19 | mic WS |
| 26 | GP20 | mic SD |
| 36 | 3V3(OUT) | 3.3 V supply |
| 38 | GND | ground |
| 39, 40 | VSYS, VBUS | **5 V: do not use** |

Pin 20 (GP15) is free: earlier drafts had a second button there.

# Part A: test the button and the LED

## Step 1: solder the headers, using the breadboard as a jig

The breadboard holds the pins straight while you solder.

1. Push the two 20-pin header strips, **long ends down**, into the breadboard:
   - one strip into **column c**, rows **1 to 20**;
   - the other into **column h**, rows **1 to 20**.

   They are now exactly as far apart as the Pico's two rows of holes.
2. Lay the Pico on top, chips facing up, **USB socket toward row 1**. Every header pin should poke through one of its holes. Don't force it: if it doesn't fit, check the columns.
   - **Check pin 1 before soldering.** Small numbers are printed near the corner pins at the USB end: **1** on one side, **40** on the other. On the back, pin 1 is labelled GP0 and pin 40 VBUS.
   - Pin **1** must sit on the header in **c1**, and pin **40** in **h1**.
   - If it is the other way round, your breadboard is lettered in the opposite direction. That is fine: keep the Pico as it is, and in every step of this guide swap the letters **a↔j, b↔i, c↔h, d↔g, e↔f**.
3. Solder one corner pin, then the opposite corner. Check that the board lies flat, then solder the other 38.
   - Each joint: touch the iron to the pin and the pad for 1–2 s, feed a little solder until it flows around the pin into a small cone, then remove the solder and the iron.
   - Don't bridge two neighbouring pins with solder.
4. Let it cool and **leave the Pico where it is**: this is its working position.
   - Left pins (1–20) are in column c: pin *N* is in row *N*.
   - Right pins (21–40) are in column h: pin *P* is in row **41 − P** (pin 40 → row 1, pin 36 → row 5, pin 26 → row 15, pin 21 → row 20).

   Beside each pin, you can plug wires into **a** or **b** on the left, and **i** or **j** on the right. The holes under the board (d, e, f, g) are covered.

## Step 2: wire the button and the LED

Both go straight to three neighbouring Pico pins: **17** (GP13, the LED), **18** (GND) and **19** (GP14, the button). Rows 17, 18 and 19 on the left, holes **a** and **b**.

**The button.** A 4-leg button connects two pairs of legs when pressed. Which pairs is easy to get wrong, so use this rule: **wire two diagonally opposite legs**. That is always correct.

1. Place the button across the centre gap: two legs in **e30 / e32**, two legs in **f30 / f32**. Press firmly until it sits flat.
2. Wire the diagonal legs (e30 and f32):

| Wire | From | To | Meaning |
|---|---|---|---|
| W1 | **a30** | **a19** (Pico pin 19, GP14) | button signal |
| W2 | **j32** | **b18** (Pico pin 18, GND) | button to ground |

No resistor is needed for the button: the Pico has pull-ups built in.

**The LED.** One blue LED shows the Bluetooth link and whether the device is awake.

**Why 100 Ω and not the usual 220 Ω:** a blue LED needs about 2.8–3.0 V before it lights at all, and the Pico's pins give 3.3 V. Only the remaining 0.3–0.5 V pushes current through the resistor. With 220 Ω that is only about 1.5–2 mA: the LED is dim. With 100 Ω it is about 3–5 mA: clearly visible, and still safe for the LED and for the Pico pin. (Don't leave the resistor out: it is what limits the current.)

An LED only works one way round. The **longer leg is + (anode)**. The shorter leg, on the side where the rim of the LED is flat, is − (cathode).

3. Put the LED in **column g**: the long leg (+) in **g44**, the short leg (−) in **g45**.
4. Put the 100 Ω resistor **across the centre gap in row 44**: from **e44 to f44**.
5. Wire it:

| Wire | From | To | Meaning |
|---|---|---|---|
| W3 | **a44** | **a17** (Pico pin 17, GP13) | Pico pin → 100 Ω → LED long leg |
| W4 | **j45** | **a18** (Pico pin 18, GND) | LED short leg to ground |

The LED must never connect to the Pico pin without the resistor.

Check: nothing is in rows 1 and 2 on the right side (Pico pins 40 and 39, the 5 V pins), and W2 and W4 both end in row 18.

## Step 3: test the button and the LED

Plug in the USB cable and flash the firmware (`tools/build.sh --upload`, see README.md). Open the console:

```bash
stty -F /dev/ttyACM0 115200 raw -echo && cat /dev/ttyACM0 &
echo status > /dev/ttyACM0          # type any command this way
```

`status` should answer `vox_node 0.1.0 (secure build)`, and a line `power: awake`. The device starts **awake and disarmed**.

**1. The LED wiring**
- [ ] `led on`: the blue LED lights. `led off`: it goes dark.
- [ ] If it never lights, the LED is probably in backwards (swap its two legs), or W3/W4 is in the wrong row.
- [ ] `led auto` returns to the automatic pattern. With no phone connected, that is a short blink once a second.

**2. The button wiring**
- [ ] `buttons` says `button (GP14) released`. Hold the button down and run `buttons` again: `button (GP14) PRESSED`.
- [ ] If it always says PRESSED, the button is turned 90°: use the diagonal rule from step 2. If it never says PRESSED, check W1 and W2.

**3. What the presses do** (the console prints each result; the phone shows it too, the LED does not)

| You do | Console | LED |
|---|---|---|
| 1 click | about 0.4 s later: `state: paused, cursor mode (button click)`; click again for gesture | unchanged |
| 2, 3 or 4 quick presses | `button: 3 presses do nothing` | unchanged |
| 5 quick presses (disarmed) | `state: armed, gesture mode (5 presses)` | unchanged |
| 5 quick presses (armed) | `going to sleep (5 presses while armed)`, then `asleep: radio and mic off` | off |
| hold 1 s | at 1 s, still held: `state: stopped`; on release: `going to sleep (button hold released)` | off once asleep |
| asleep: 5 quick presses | `waking up (5 presses)`, `awake after ... ms`, `waiting up to 60 s for a bonded phone` | slow blink again |
| asleep, no phone within 60 s | `going to sleep (no bonded phone subscribed within 60 s of waking)` | off |
| hold 5 s (awake or asleep) | `pairing window OPEN for 60 s` | fast blink for up to 60 s |
| hold the button while plugging in | `button held at power-on: test-sound trigger ON`; then 2 presses send the next canned sound (when armed) | |

"Asleep" turns the Bluetooth chip and the mic off. The small on-board LED is wired to the Bluetooth chip, so its once-a-second heartbeat stops too; that is normal. The USB console keeps working while asleep (`status` says `power: asleep`); `wake` wakes the device from the console.

No button wired yet? `btn click`, `btn clicks 5`, `btn hold 1200` and `btn hold 5500` press it for you, through exactly the same logic as the real button.

**4. The blue LED**

| LED | Meaning |
|---|---|
| short blink once a second | awake, no phone connected: advertising |
| fast blink, 5 times a second | the pairing window is open (up to 60 s after holding the button 5 s), or a phone is connecting, pairing or subscribing |
| off | a phone is connected and subscribed, whatever the armed state and mode |
| off | asleep |
| steady on / off | `led on` / `led off` (wiring test); `led auto` goes back |

With the phone app (or `tools/ble_check.py`):
- [ ] First pairing: hold the button 5 s (fast blink), then connect from the phone. Once it is paired and subscribed, the LED goes off and the window closes.
- [ ] Turn off the phone's Bluetooth: back to the slow blink, and the device is disarmed.
- [ ] Outside the pairing window a phone that is not bonded cannot pair: the console says `pairing: Just Works request REJECTED: pairing window closed`.
- [ ] Every re-flash erases the bonds. The phone still has the old bond, so encryption fails. Remove VOX-XXXX from the phone's Bluetooth list, hold the button 5 s, and pair again.

# Part B: the microphone

## Step 4: power rails

Use the rails on the **right** side of the breadboard (the side nearest column j).

| Wire | From | To |
|---|---|---|
| W5 | **j5** (Pico pin 36, 3V3 OUT) | right **red (+)** rail |
| W6 | **j3** (Pico pin 38, GND) | right **blue (−)** rail |

Now the + rail is 3.3 V and the − rail is ground. If your rails have a break in the middle, add a short wire across each break.

## Step 5: INMP441 microphone

1. Solder the INMP441's header the same way as the Pico's: push the strip into the breadboard, lay the module on it, and solder.
2. Push the module's 6 pins into **column h**, rows **52 to 57**, with the microphone hole facing up and away from the other parts.
   - If your module has its pins in **two rows of 3**, place it across the centre gap instead: one row in e52–e54, the other in f52–f54.
   - Then wire each pin from the free holes of its own row-half: a/b for the pins in column e, i/j for the pins in column f.
3. Read the labels printed next to its pins. They are usually **SCK, WS, L/R, SD, VDD, GND**, in some order.
4. Write down which label ended up in which row. Then connect each row from column **j** (or a/b, see above) as follows:

| Mic pin | Wire from its row (column j) to | Meaning |
|---|---|---|
| **VDD** | right **red (+)** rail | 3.3 V. **Not 5 V** |
| **GND** | right blue (−) rail | ground |
| **L/R** | right blue (−) rail | selects the left channel, which the firmware reads |
| **SCK** | **j17** (Pico pin 24, GP18) | bit clock |
| **WS** | **j16** (Pico pin 25, GP19) | word select |
| **SD** | **j15** (Pico pin 26, GP20) | data |

If a mic label is SCLK or BCLK, that is SCK. LRCL or LRCLK means WS, and DOUT or DATA means SD.

## Step 6: check before plugging in

- No wire goes to Pico pins 39 or 40 (rows 2 and 1, right side), or to anything from the kit's 5 V.
- The red (+) rail's only sources are W5 (Pico pin 36) and the mic's VDD. Nothing connects + directly to −.
- The LED goes through the 100 Ω resistor (row 44, across the gap).
- Then plug the USB cable into the PC. The Pico's small on-board LED blinks once a second (the heartbeat).

## Microphone checklist

**1. Microphone level: `mic level`** (prints about 10 lines a second; `mic off` stops it; the device must be awake)
- [ ] `ALL ZEROS` means no data from the mic. Check VDD (3.3 V), GND, SD → pin 26, SCK → pin 24, WS → pin 25. With no mic plugged in at all, this is what you see, and INFO says `"mic":"none"`.
- [ ] `left slot is zero but the RIGHT slot has data` means L/R is not on ground.
- [ ] `CONSTANT` means SD is stuck. Check its wire.
- [ ] Expected numbers are rough: the INMP441 gives −26 dBFS at 94 dB SPL, and they depend on distance.

  | Situation | rms (dBFS) |
  |---|---|
  | Quiet room | about −75 to −85 |
  | Normal talking at arm's length | about −55 to −65 |
  | Humming 10 cm from the mic | about −35 to −50 |

  - A clap or a lip pop close by: the peak jumps to −20 or higher.
  - If the numbers never move when you make noise, the mic is not being read.
  - `CLIPPING` means the sound was too loud for the mic.

**2. Record and run the extractor**
- [ ] `mic off`, then record 5 s while you hum a rising note, a pop and a hiss:
  ```bash
  cd ~/VOX/firmware
  nix shell --impure --expr 'with import <nixpkgs> {}; python313.withPackages (p: [p.bleak p.pyserial])' \
      -c python tools/pico_stream.py -s 5 -o /tmp/vox_mic.wav
  ```
  It reports:
  - lost frames and CRC errors, which should both be 0;
  - the level;
  - `ALL ZEROS` if no mic data came.

  If your voice is very quiet in the file, add `--gain 18`; if it says `CLIPPING`, use `--gain 6`.
- [ ] Listen to `/tmp/vox_mic.wav`. It should sound like you, not like a buzz or static.
  - Static that follows your voice's loudness means the bit alignment is wrong. Report it: the firmware assumes 24-bit data in 32-bit slots.
- [ ] Run the extractor on it: `cd ~/VOX/extractor && ./run python record.py --wav /tmp/vox_mic.wav`. It should print one VOX line per sound (rise, pop, hiss).

# Part C: moving to the protoboard

The necklace case (`hardware/case/`) holds a 5 × 7 cm protoboard (18 × 24 holes). `hardware/case/out/layout.svg` is a 1:1 template of it: print it at 100 % and check its 40 mm bar with a ruler. Regenerate it first if `out/` is missing (see `hardware/case/README.md`).

**Reading the template.** It shows the board from the **component side** (the side the Pico, the button and the LED sit on): the labels read normally, so it is not mirrored. Number the holes as the case file does:
- **columns 0–17**, left to right;
- **rows 0–23**, from the bottom edge (the USB end) up.

**The Pico** sits with its chips facing up, away from the board, soldered on its male headers (as on the breadboard), **USB socket at the bottom edge**. Its pin rows go into **column 0** and **column 7**, starting in row 0.

Which pin lands where (checked against the official Pico 2 W pinout, which is drawn from the chip side with the USB socket at the top and pin 1 top-left; turning it so the USB is at the bottom puts pin 1 bottom-right):
- **Column 7 (right row): pins 1–20, going up from the USB end. Pin *N* is in row *N* − 1.** So pin 17 (GP13) = row 16, pin 18 (GND) = row 17, pin 19 (GP14) = row 18.
- **Column 0 (left row): pins 40–21, going up from the USB end. Pin *P* is in row 40 − *P*.** So pin 40 (VBUS) = row 0, pin 39 (VSYS) = row 1, pin 38 (GND) = row 2, pin 36 (3V3) = row 4, pin 26 = row 14, pin 25 = row 15, pin 24 = row 16, pin 23 (GND) = row 17.
- Before soldering, turn the Pico over and check: **GP0 (pin 1) must be at the bottom of column 7**, next to the USB socket, and **VBUS (pin 40) at the bottom of column 0**. This only holds with the chips facing up. A Pico mounted chips-down is mirrored: pins 1–20 would then be in column 0, and everything below would be wrong.

**The parts** (the template marks their centres):

| Part | Centre | Legs | Notes |
|---|---|---|---|
| LED | col 13, row 16 | long leg (+) in **col 12, row 16**, short leg (−) in **col 14, row 16** | spread the legs one hole apart each side so the LED sits exactly under the lid's LED hole |
| 100 Ω resistor | | **col 8, row 16** and **col 11, row 16**, lying flat | bend the leads right at the body; it fits 3 hole spacings |
| Button | col 13, row 10 | **cols 12 and 14, rows 9 and 12** | the kit button needs 2 hole spacings one way and 3 the other (as on the breadboard: rows 30/32, across the gap), so its centre is half a hole (1.3 mm) above row 10; the plunger's 7.5 mm flange still covers the switch |

**Wiring** (under the board; use insulated wire wherever a wire crosses other pads):

| From | To | Meaning |
|---|---|---|
| Pico pin 17 (col 7, row 16) | resistor lead (col 8, row 16): bend the lead onto the pin's pad and solder | GP13 → 100 Ω |
| resistor lead (col 11, row 16) | LED long leg (col 12, row 16): bend and solder | 100 Ω → LED + |
| LED short leg (col 14, row 16) | Pico pin 18 (col 7, row 17) | LED − to GND |
| button leg col 12, row 12 | Pico pin 19 (col 7, row 18) | button signal (GP14) |
| button leg col 14, row 9 (the **diagonal** one) | Pico pin 18 (col 7, row 17) | button to GND |
| mic SCK / WS / SD | Pico pin 24 (col 0, row 16) / 25 (row 15) / 26 (row 14) | six short wires to the mic module in the case's pocket |
| mic VDD | Pico pin 36 (col 0, row 4) | 3.3 V, **not** pin 39 or 40 (rows 1 and 0) |
| mic GND and L/R | Pico pin 38 (col 0, row 2) | ground |

Before you plug in, test with a multimeter (continuity): button leg col 12/row 12 to pin 19 only; pin 18 to both the LED's short leg and the button's diagonal leg; nothing touches rows 0 and 1 of column 0. Then run Step 3's checks again.
