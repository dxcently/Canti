// VOX necklace case: parametric enclosure for the 5x7 cm protoboard + Pico 2 W.
//
// Worn as a pendant, lid against the chest (the mic hole faces the body; a small weight at the
// bottom keeps it from flipping). The lid carries the button hole, the LED hole and the mic (the
// INMP441 module clips into a pocket on the inside of the lid, sound hole over the lid's
// acoustic hole, and a 5-wire cable plugs onto a right-angle header on the protoboard, so
// the lid comes off whole), the cord goes through one loop at the top centre, and the USB
// cable to the power bank leaves at the bottom, zip-tied to a tab. The back is closed.
//
// Frame: board coordinates, looking at the component side (the lid side). x = across the
// 50 mm width, y = up the 70 mm length (y = 0 is the USB end, y = 70 the top), z = 0 is
// the outer back face. All dimensions in mm.
//
// Render one part:   openscad -D 'part="base"' -o out/base.stl vox_case.scad
// Parts: "assembly" (preview), "base", "lid", "plunger", "mic_clip" (C-ring that holds the mic),
//        "fit_test" (short base slice), "mic_test" (the lid's mic pocket on a small plate),
//        "layout" (2D, 1:1 SVG template), "clash" (base/lid overlap check: must render empty)

part = "assembly";

// --- measure these once the board is built (defaults are guesses) -------------------
board_w = 50;       // protoboard width (sold as 5x7 cm, 18x24 holes)
board_l = 70;       // protoboard length
board_t = 1.6;      // protoboard thickness
above = 10;         // tallest thing above the board top (Pico on headers, bent LED)
under_gap = 4;      // space under the board: solder tails and the wires (the mic no longer lives here;
                    // ~3 would do, but 4 is what was printed and fits, so it stays)
pico_standoff = 2.5;// Pico underside above the board top (2.5 = soldered on male headers)

// --- case ----------------------------------------------------------------------------
wall = 2.0;         // side walls
back_t = 2.0;       // back (body side) wall
lid_t = 2.0;        // front lid plate
fit = 0.5;          // gap between the board edge and the inner wall, per side
lid_fit = 0.35;     // gap between the lid skirt and the inner wall: a slip fit, the rubber bands hold it
skirt_h = 3;        // how far the lid skirt reaches down inside the walls
corner_r = 4;       // outer corner rounding
post = 3.5;         // corner posts under/over the board (board corners are free of pads)

// --- protoboard grid: holes are on 2.54 mm pitch, centred on the board -------------
pitch = 2.54;
cols = 18;
rows = 24;
grid_x0 = (board_w - (cols - 1) * pitch) / 2;
grid_y0 = (board_l - (rows - 1) * pitch) / 2;
function hx(c) = grid_x0 + c * pitch;
function hy(r) = grid_y0 + r * pitch;

// --- Pico 2 W: 51 x 21 x 1 mm, pins 17.78 apart, first pin 1.37 from the USB end -----
pico_w = 21;
pico_l = 51;
pico_col = 0;       // left pin row in hole column 0, right pin row in column 7
pico_row = 0;       // first pin in hole row 0 (USB end nearest the board's bottom edge)
pico_x = hx(pico_col) - 1.61;
pico_y = hy(pico_row) - 1.37;
usb_x = pico_x + pico_w / 2;
usb_z_board = pico_standoff + 1.0 + 1.5;   // USB centre above the board top
usb_notch_w = 12;   // wide enough for a micro-USB plug's overmould
usb_notch_below = 4;// notch reaches this far below the USB centre

// --- controls on the front, placed on grid holes ------------------------------------
button_col = 13;
b1_row = 10.5;      // legs span 3 rows (9, 12), so the centre falls between holes. The one button: 5 presses on/off, click = mode, hold 1 s off, hold 5 s pair
led_row = 16;
switch_h = 5;       // 6x6 mm tactile switch height (kit "small button")
switch_size = 6;
plunger_d = 4;
plunger_hole = 4.5;
flange_d = 7.5;
flange_t = 1.0;
plunger_out = 1.5;  // how far the plunger stands proud of the lid
led_hole = 5.3;     // 5 mm blue status LED

// --- mic: the round INMP441 breakout, clipped into a pocket on the INSIDE of the lid ------
// Module (see README.md for the sources): a 14 mm round PCB, 6 pad holes in two rows of 3
// (2.54 mm pitch, rows 7.62 mm apart), the sound hole through the PCB at the centre on the
// side with the pin labels, and the MEMS chip on the other side. It sits LABEL SIDE (sound
// hole) TOWARDS THE LID, chip side into the case:
//   lid plate | foam ring around the hole (squeezed to mic_seat_h) | module | clip ring
// A printed seat ring at the rim sets the gap, so the pads' solder bumps never touch the
// lid; the foam ring seals the port to the lid's hole, so the mic hears the outside and
// not the case cavity; a printed C-ring (part "mic_clip") snaps into a groove in the
// pocket wall and holds the module. The 5 wires leave the chip side straight into the case.
mic_x = 36.43;      // lid position (= hole column 13, same line as the button and the LED)
mic_y = 60.4;       // clear of the y = 52 band groove, the LED and the Pico's antenna end
mic_d = 14.0;       // module PCB diameter
mic_pcb_t = 1.0;    // module PCB thickness: MEASURE; the clip groove is placed for this (+0.05)
mic_pad_r = 5.4;    // the pads and their solder reach this far from the centre
mic_seat_h = 1.2;   // lid-to-module gap = squeezed foam; solder bumps on the label side must stay under this
mic_port_d = 2.0;   // acoustic hole through the lid
mic_wall = 1.6;     // pocket wall
mic_bore = mic_d + 0.4;
mic_groove = 0.65;  // radial depth of the clip groove in the pocket wall
mic_clip_t = 1.0;   // clip ring thickness
mic_clip_id = 11.8; // clip ring inner diameter: bears on the module's rim, clear of the pads
mic_clip_gap = 4.5; // opening of the C, lets it squeeze through the bore
mic_lip = 0.9;      // pocket wall below the groove, holds the clip
// foam ring (not printed): 2 mm EVA craft foam or foam tape, 5 mm outside, 2.5 mm hole,
// squeezed from 2 mm to mic_seat_h
cloth_d = 10;       // outside recess for a fabric/foam disc against wind and rubbing noise
cloth_depth = 0.6;

// --- mic cable strain relief on the lid: a short open channel ~1 cm from the pads. Put a
// blob of hot glue over the wires in it, or a small zip tie through the two tunnels at its
// floor and around the walls and the wires, so flexing happens here and not at the pads.
relief_c = [44, 47];    // centre; the wires run along y through it
relief_len = 6;
relief_in = 4.5;        // inside width: 5 jumper wires in a bundle
relief_wall = 1.0;
relief_h = 3.5;
relief_tunnel = [3.0, 1.4];  // zip-tie tunnels through both walls at the lid face (along y, height)

// --- mic connector on the protoboard: a 5-pin RIGHT-ANGLE male header, plug pointing +x,
// so the female Dupont housing lies flat on the board (a vertical one is ~14 mm tall and
// does not fit under the lid). Pins in hole column hdr_col, rows hdr_row0 .. hdr_row0 + 4.
hdr_col = 9;        // one free column between it and the Pico's pin row (column 7)
hdr_row0 = 3;       // rows 3..7: below the button, above the USB end
hdr_pins = ["GND", "3V3", "SD", "WS", "SCK"];   // row hdr_row0 upwards; see README for the wiring
plug_reach = 16;    // from the header's pins to the back of the Dupont housing (body ~1.5 + housing 14)
plug_h = 3.0;       // housing height above the board
plug_bend = 6;      // room behind the housing for the wires to bend up

// --- necklace loop: one bail at the top centre; the cord runs side to side through it,
// parallel to the face, so the case hangs flat facing forward instead of turning sideways
bail_w = 10;        // width along x
bail_reach = 11;    // how far it sticks up past the top wall
bail_r = 5.5;       // rounding of the loop around the hole
cord_d = 4.5;       // hole for the cord or chain

// --- cable tie tab under the USB notch: a zip tie holds the plug to the case, so a tug
// on the power bank cable does not land on the Pico's micro-USB socket
cable_tie = true;
tie_w = 12;
tie_reach = 7;      // how far it sticks out past the bottom wall
tie_h = 8;
tie_slot = [4, 2];  // slot for the zip tie (y, z), running along x

// --- rubber bands hold the lid on: each band wraps around the width (over the lid, down
// both sides, under the back) and sits in a shallow groove so it cannot slide off.
// Keep the bands clear of the button, the LED and the mic port (see the layout).
bands = true;
band_ys = [12, 52];  // groove centres along y
band_w = 4;          // groove width (fits a ~3 mm office rubber band)
band_depth = 0.8;    // groove depth into the lid, the side walls and the back

$fn = 48;

// --- derived --------------------------------------------------------------------------
in_w = board_w + 2 * fit;
in_l = board_l + 2 * fit;
out_w = in_w + 2 * wall;
out_l = in_l + 2 * wall;
board_z = back_t + under_gap;               // board underside
board_top = board_z + board_t;
base_h = board_top + above;                 // wall height; the lid plate sits on top
ox = -fit - wall;                           // outer corner in board coordinates
oy = -fit - wall;
buttons = [[hx(button_col), hy(b1_row)]];
led = [hx(button_col), hy(led_row)];
mic_groove_d0 = mic_seat_h + mic_pcb_t + 0.05;              // depths below the lid's inner face
mic_groove_d1 = mic_groove_d0 + mic_clip_t + 0.2;
mic_pocket_d = mic_groove_d1 + mic_lip;                     // pocket wall depth
mic_pocket_od = mic_bore + 2 * mic_wall;
mic_clip_od = mic_bore + 2 * mic_groove - 0.3;
hdr_x = hx(hdr_col);
hdr_y0 = hy(hdr_row0);
hdr_y1 = hy(hdr_row0 + len(hdr_pins) - 1);

// sanity checks: fail the render instead of printing a bad part
for (y = band_ys) assert(abs(mic_y - y) >= band_w / 2 + cloth_d / 2 + 0.5, "mic hole/recess crosses a rubber-band groove");
assert(mic_x + mic_pocket_od / 2 <= board_w - post - 0.5, "mic pocket hits a lid corner post");
assert(mic_y + mic_pocket_od / 2 <= board_l + fit - lid_fit, "mic pocket sticks out of the lid skirt");
assert(mic_y - mic_pocket_od / 2 >= led[1] + led_hole / 2 + 1, "mic pocket hits the LED");
assert(mic_clip_id / 2 >= mic_pad_r + 0.3, "mic clip ring would press on the pads");
assert(relief_c[0] - relief_in / 2 - relief_wall >= led[0] + led_hole / 2 + 1.5, "strain relief too close to the LED hole");
assert(relief_c[0] + relief_in / 2 + relief_wall <= board_w + fit - lid_fit - 1.2 - 1.2, "no room for a zip tie between the strain relief and the skirt");
assert(hdr_x - 1.3 > pico_x + pico_w, "mic header under the Pico");
assert(hdr_x + plug_reach + plug_bend <= board_w + fit, "no room behind the mic plug for the wires to bend");
assert(hdr_y1 + 1.5 < buttons[0][1] - switch_size / 2, "mic plug hits the button");

module rrect(x, y, w, l, r) {
    translate([x, y]) offset(r) offset(-r) square([w, l]);
}

module outer2d() { rrect(ox, oy, out_w, out_l, corner_r); }
module inner2d(extra = 0) {
    rrect(-fit + extra, -fit + extra, in_w - 2 * extra, in_l - 2 * extra, max(0.5, corner_r - wall));
}

module corner_posts(z0, h) {
    for (c = [[0, 0], [board_w - post, 0], [0, board_l - post], [board_w - post, board_l - post]])
        // overlap into the wall (coincident faces make the union non-manifold)
        translate([c[0] == 0 ? -fit - 0.6 : c[0], c[1] == 0 ? -fit - 0.6 : c[1], z0])
            cube([post + fit + 0.6, post + fit + 0.6, h]);
}

module usb_notch() {
    translate([usb_x - usb_notch_w / 2, oy - 1, board_top + usb_z_board - usb_notch_below])
        cube([usb_notch_w, wall + fit + 1.5, 50]);
}

// Profiles below are drawn in the (y, z) plane and extruded along x:
// rotate([90, 0, 90]) maps 2D (u, v) and extrusion w to (x, y, z) = (w, u, v).
// Both are flat on the back face so the base prints without supports.
module bail() {
    y0 = oy + out_l;
    cy = y0 + bail_reach - bail_r;
    cz = base_h / 2;
    translate([board_w / 2 - bail_w / 2, 0, 0]) rotate([90, 0, 90])
        linear_extrude(bail_w)
            difference() {
                hull() {
                    translate([y0 - wall / 2, 0]) square([wall / 2, base_h]);   // starts inside the wall only
                    translate([y0, 0]) square([bail_reach, 1]);
                    translate([cy, cz]) circle(r = bail_r);
                }
                translate([cy, cz]) circle(d = cord_d);
            }
}

module tie_tab() {
    translate([usb_x - tie_w / 2, 0, 0]) rotate([90, 0, 90])
        linear_extrude(tie_w)
            difference() {
                translate([oy - tie_reach, 0]) square([tie_reach + wall / 2, tie_h]);
                translate([oy - tie_reach + 1.5, tie_h - 2 - tie_slot[1]]) square(tie_slot);
            }
}

module base() {
    difference() {
        union() {
            difference() {
                linear_extrude(base_h) outer2d();
                translate([0, 0, back_t]) linear_extrude(base_h) inner2d();
            }
            corner_posts(back_t - 0.01, under_gap + 0.01);
            bail();
            if (cable_tie) tie_tab();
        }
        usb_notch();
        band_grooves();
    }
}

// The groove is the skin of the case, band_depth thick, in a band_w wide slice at each y.
module band_grooves() {
    total = base_h + lid_t;
    if (bands) for (y = band_ys)
        translate([0, y - band_w / 2, 0])
            difference() {
                translate([ox - 1, 0, -1]) cube([out_w + 2, band_w, total + 2]);
                translate([ox + band_depth, -1, band_depth])
                    cube([out_w - 2 * band_depth, band_w + 2, total - 2 * band_depth]);
            }
}

// The mic pocket on the inside of the lid: wall with the clip groove, and the seat ring.
module mic_pocket() {
    translate([mic_x, mic_y, base_h - mic_pocket_d]) difference() {
        cylinder(d = mic_pocket_od, h = mic_pocket_d + 0.01);
        translate([0, 0, -1]) cylinder(d = mic_bore, h = mic_pocket_d + 2);
        // clip groove
        translate([0, 0, mic_pocket_d - mic_groove_d1]) cylinder(d = mic_bore + 2 * mic_groove, h = mic_groove_d1 - mic_groove_d0);
        // lead-in chamfer at the mouth, for pushing the clip in
        translate([0, 0, -0.01]) cylinder(d1 = mic_bore + 1.0, d2 = mic_bore, h = 0.5);
    }
    // seat ring: the module's rim rests here, mic_seat_h below the lid
    translate([mic_x, mic_y, base_h - mic_seat_h]) difference() {
        cylinder(d = mic_bore + 0.2, h = mic_seat_h + 0.01);
        translate([0, 0, -1]) cylinder(r = mic_pad_r + 0.4, h = mic_seat_h + 2);
    }
}

// Acoustic hole through the lid, and the outside recess for the fabric disc.
module mic_holes() {
    translate([mic_x, mic_y, base_h - 1]) cylinder(d = mic_port_d, h = lid_t + 2, $fn = 24);
    translate([mic_x, mic_y, base_h + lid_t - cloth_depth]) cylinder(d = cloth_d, h = cloth_depth + 1);
}

// Strain relief: two short walls with zip-tie tunnels at the lid face.
module strain_relief() {
    difference() {
        for (s = [-1, 1])
            translate([relief_c[0] + s * (relief_in + relief_wall) / 2 - relief_wall / 2,
                       relief_c[1] - relief_len / 2, base_h - relief_h])
                cube([relief_wall, relief_len, relief_h + 0.01]);
        translate([relief_c[0] - relief_in, relief_c[1] - relief_tunnel[0] / 2, base_h - relief_tunnel[1]])
            cube([2 * relief_in, relief_tunnel[0], relief_tunnel[1] + 0.5]);
    }
}

module lid() {
    difference() {
        union() {
            translate([0, 0, base_h]) linear_extrude(lid_t) outer2d();
            translate([0, 0, base_h - skirt_h])
                linear_extrude(skirt_h + 0.01)
                    difference() {
                        inner2d(lid_fit);
                        inner2d(lid_fit + 1.2);
                    }
            // the posts reach into the wall (for the base's union), so trim them to the skirt's outline:
            // same lid_fit gap and rounded corners as the skirt, or they bind in the walls' corners
            intersection() {
                corner_posts(board_top, base_h - board_top + 0.01);
                translate([0, 0, board_top - 1]) linear_extrude(base_h - board_top + 2) inner2d(lid_fit);
            }
            mic_pocket();
            strain_relief();
        }
        usb_notch();
        band_grooves();
        for (b = buttons) translate([b[0], b[1], base_h - 1]) cylinder(d = plunger_hole, h = lid_t + 2);
        translate([led[0], led[1], base_h - 1]) cylinder(d = led_hole, h = lid_t + 2);
        mic_holes();
    }
}

// C-shaped clip ring: squeeze it, push it into the pocket over the module until it snaps
// into the groove. Prints flat.
module mic_clip() {
    linear_extrude(mic_clip_t) difference() {
        circle(d = mic_clip_od);
        circle(d = mic_clip_id);
        translate([0, -mic_clip_gap / 2]) square([mic_clip_od, mic_clip_gap]);
    }
}

// Print-in-minutes check of the mic pocket: the pocket, the hole and the recess on a small
// plate. Fit the foam ring, the module and the clip into it before printing the whole lid.
module mic_test() {
    s = mic_pocket_od + 4;
    difference() {
        union() {
            translate([mic_x - s / 2, mic_y - s / 2, base_h]) cube([s, s, lid_t]);
            mic_pocket();
        }
        mic_holes();
    }
}

plunger_len = (above - switch_h) + lid_t + plunger_out;
module plunger() {
    cylinder(d = flange_d, h = flange_t);
    cylinder(d = plunger_d, h = plunger_len);
}

// 1:1 placement template for the protoboard, component side up (print at 100% scale).
module layout() {
    difference() {
        square([board_w, board_l]);
        translate([0.3, 0.3]) square([board_w - 0.6, board_l - 0.6]);
    }
    for (c = [0 : cols - 1], r = [0 : rows - 1]) translate([hx(c), hy(r)]) circle(d = 0.6, $fn = 8);
    // Pico outline and USB end
    translate([pico_x, pico_y]) difference() {
        square([pico_w, pico_l]);
        translate([0.4, 0.4]) square([pico_w - 0.8, pico_l - 0.8]);
    }
    translate([usb_x - 4, pico_y - 1.3]) square([8, 1.3]);
    for (b = buttons) translate(b) difference() {
        square(switch_size, center = true);
        square(switch_size - 0.8, center = true);
    }
    translate(led) difference() { circle(d = 5); circle(d = 4.2); }
    // mic header: 5 pins (filled rings) in column hdr_col, and where its plug lies
    for (i = [0 : len(hdr_pins) - 1]) translate([hdr_x, hy(hdr_row0 + i)]) {
        difference() { circle(d = 1.9, $fn = 16); circle(d = 0.9, $fn = 16); }
        translate([-1.6, -0.55]) text(hdr_pins[i], size = 1.3, halign = "right");
    }
    translate([hdr_x + 1.3, hdr_y0 - 1.5]) difference() {
        square([plug_reach - 1.3, hdr_y1 - hdr_y0 + 3]);
        translate([0.3, 0.3]) square([plug_reach - 1.9, hdr_y1 - hdr_y0 + 2.4]);
    }
    translate([hdr_x + 3, (hdr_y0 + hdr_y1) / 2 + 0.3]) text("mic plug, flat", size = 1.5);
    translate([hdr_x + 3, (hdr_y0 + hdr_y1) / 2 - 1.8]) text("(right-angle header)", size = 1.05);
    // where the mic hangs from the lid: keep the board under it lower than 4 mm
    translate([mic_x, mic_y]) difference() { circle(d = mic_pocket_od); circle(d = mic_pocket_od - 0.4); }
    translate([mic_x, mic_y + 1]) text("mic is in the lid", size = 1.4, halign = "center");
    translate([mic_x, mic_y - 1.2]) text("above this circle:", size = 1.2, halign = "center");
    translate([mic_x, mic_y - 3]) text("nothing over 4 mm", size = 1.2, halign = "center");
    // labels
    translate([pico_x + 3, pico_y + 25]) text("PICO", size = 3.5);
    translate([pico_x + 2, pico_y + 2]) text("USB", size = 2.5);
    translate([buttons[0][0] + 4, buttons[0][1] - 1]) text("button", size = 2.2);
    translate([led[0] + 4, led[1] - 1]) text("LED", size = 2.2);
    // 40 mm scale bar below the board: measure it after printing
    translate([0, -6]) square([40, 0.6]);
    translate([0, -10]) text("40 mm check", size = 2.5);
}

if (part == "base") base();
else if (part == "lid") translate([0, 0, base_h + lid_t]) rotate([180, 0, 0]) lid();
else if (part == "plunger") plunger();
else if (part == "layout") layout();
else if (part == "mic_clip") mic_clip();
else if (part == "mic_test") translate([0, 0, base_h + lid_t]) rotate([180, 0, 0]) mic_test();   // outer face down, like the lid
else if (part == "fit_test") intersection() {   // bottom slice of the base: checks the board fit fast
    base();
    translate([ox - 20, oy - 20, -1]) cube([out_w + 40, out_l + 40, board_top + 1.5 + 1]);
}
else if (part == "clash") intersection() {   // base and lid overlap below the wall top: must render EMPTY
    base();
    intersection() { lid(); translate([ox - 1, oy - 1, -1]) cube([out_w + 2, out_l + 2, base_h - 0.01 + 1]); }
}
else if (part == "none") { }
else {
    color("SlateGray") base();
    color("LightSteelBlue", 0.6) translate([0, 0, 25]) lid();   // lifted to show inside
    color("DarkGreen") translate([0, 0, board_z]) cube([board_w, board_l, board_t]);
    color("Teal") translate([pico_x, pico_y, board_top + pico_standoff]) cube([pico_w, pico_l, 1]);
    color("Silver") translate([usb_x - 4, pico_y - 1.3, board_top + pico_standoff + 1]) cube([8, 5.5, 3]);
    for (b = buttons) color("Black") translate([b[0] - 3, b[1] - 3, board_top]) cube([6, 6, switch_h]);
    for (b = buttons) color("Orange") translate([b[0], b[1], board_top + switch_h + 25]) plunger();
    color("White") translate([led[0], led[1], board_top]) cylinder(d = 5, h = 8.6);
    // mic connector: right-angle header body and the Dupont plug lying flat on the board
    color("Black") translate([hdr_x - 1, hdr_y0 - 1.27, board_top]) cube([2.5, hdr_y1 - hdr_y0 + 2.54, 2.54]);
    color("DimGray") translate([hdr_x + 1.5, hdr_y0 - 1.27, board_top + 0.1]) cube([plug_reach - 1.5, hdr_y1 - hdr_y0 + 2.54, plug_h - 0.1]);
    // mic in the lid (lifted with it): foam ring, module (label side up against the lid), clip
    translate([0, 0, 25]) {
        color("DimGray") translate([mic_x, mic_y, base_h - mic_seat_h]) difference() {
            cylinder(d = 5, h = mic_seat_h);
            translate([0, 0, -1]) cylinder(d = 2.5, h = mic_seat_h + 2);
        }
        color("Purple") translate([mic_x, mic_y, base_h - mic_seat_h - mic_pcb_t]) difference() {
            cylinder(d = mic_d, h = mic_pcb_t);
            translate([0, 0, -1]) cylinder(d = 1, h = mic_pcb_t + 2);
        }
        color("Orange") translate([mic_x, mic_y, base_h - mic_groove_d1 + 0.1]) mic_clip();
    }
}
