// VOX necklace case: parametric enclosure for the 5x7 cm protoboard + Pico 2 W.
//
// Worn as a pendant: the back (body side) carries the mic port, the front lid carries
// the button and the status LED, the cord goes through one loop at the top centre,
// and the USB cable to the power bank leaves at the bottom, zip-tied to a tab.
//
// Frame: board coordinates, looking at the component side (the front). x = across the
// 50 mm width, y = up the 70 mm length (y = 0 is the USB end, y = 70 the top), z = 0 is
// the outer back face. All dimensions in mm.
//
// Render one part:   openscad -D 'part="base"' -o out/base.stl vox_case.scad
// Parts: "assembly" (preview), "base", "lid", "plunger", "fit_test" (short base slice), "layout" (2D, 1:1 SVG template)

part = "assembly";

// --- measure these once the board is built (defaults are guesses) -------------------
board_w = 50;       // protoboard width (sold as 5x7 cm, 18x24 holes)
board_l = 70;       // protoboard length
board_t = 1.6;      // protoboard thickness
above = 10;         // tallest thing above the board top (Pico on headers, bent LED)
under_gap = 4;      // space under the board: solder tails and the mic module
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

// --- mic: module sits in a pocket on the back wall, wired to the board with short leads
mic_x = 32;         // under the board, beside the Pico's far end (no solder tails there)
mic_y = 60;         // pocket must stay clear of the top inner wall (y = 70.5)
mic_d = 14.2;       // INMP441 breakout (round); set mic_square = true for square modules
mic_square = false;
mic_ring = 1.2;     // pocket wall thickness
mic_ring_h = 2.0;   // pocket wall height
mic_port_d = 2.0;   // acoustic hole through the back wall
cloth_d = 11;       // outside recess for a fabric/foam disc against rubbing noise
cloth_depth = 0.6;

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
            // mic pocket
            translate([mic_x, mic_y, back_t - 0.01])
                linear_extrude(mic_ring_h)
                    difference() {
                        mic_shape(mic_d + 0.4 + 2 * mic_ring);
                        mic_shape(mic_d + 0.4);
                    }
        }
        usb_notch();
        band_grooves();
        translate([mic_x, mic_y, -1]) cylinder(d = mic_port_d, h = back_t + 2);
        translate([mic_x, mic_y, -1]) cylinder(d = cloth_d, h = cloth_depth + 1);
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

module mic_shape(d) {
    if (mic_square) square(d, center = true); else circle(d = d);
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
            corner_posts(board_top, base_h - board_top + 0.01);
        }
        usb_notch();
        band_grooves();
        for (b = buttons) translate([b[0], b[1], base_h - 1]) cylinder(d = plunger_hole, h = lid_t + 2);
        translate([led[0], led[1], base_h - 1]) cylinder(d = led_hole, h = lid_t + 2);
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
    // mic sits under the board (dashed-style marker: ring only)
    translate([mic_x, mic_y]) difference() { mic_shape(mic_d); mic_shape(mic_d - 0.5); }
    // labels
    translate([pico_x + 3, pico_y + 25]) text("PICO", size = 3.5);
    translate([pico_x + 2, pico_y + 2]) text("USB", size = 2.5);
    translate([buttons[0][0] + 4, buttons[0][1] - 1]) text("button", size = 2.2);
    translate([led[0] + 4, led[1] - 1]) text("LED", size = 2.2);
    translate([mic_x - 5, mic_y - 1]) text("mic (under)", size = 1.8);
    // 40 mm scale bar below the board: measure it after printing
    translate([0, -6]) square([40, 0.6]);
    translate([0, -10]) text("40 mm check", size = 2.5);
}

if (part == "base") base();
else if (part == "lid") translate([0, 0, base_h + lid_t]) rotate([180, 0, 0]) lid();
else if (part == "plunger") plunger();
else if (part == "layout") layout();
else if (part == "fit_test") intersection() {   // bottom slice of the base: checks the board fit fast
    base();
    translate([ox - 20, oy - 20, -1]) cube([out_w + 40, out_l + 40, board_top + 1.5 + 1]);
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
    color("Purple") translate([mic_x, mic_y, back_t]) linear_extrude(1.6) mic_shape(mic_d);
}
