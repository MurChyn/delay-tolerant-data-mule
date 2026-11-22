// Enclosure for the ESP32 mobile data mule node.
// Units: mm. Render with OpenSCAD (https://openscad.org).
//
// Print settings: PLA/PETG, 0.2 mm layer height, 20% infill.
// The lid is a separate part so the SD card and USB port remain accessible.

/* [Dimensions] */
outer_x      = 90;
outer_y      = 65;
outer_z      = 32;
wall         = 2.4;
floor_thick  = 2.4;
lid_thick    = 2.4;

/* [Mounting] */
boss_d       = 7;
boss_h       = 6;
screw_d      = 2.6;
board_hole_x = 24;   // half-pitch of DevKit mounting holes
board_hole_y = 13;

/* [Render switches] */
show_base = true;
show_lid  = true;

module rounded_box(sx, sy, sz, r) {
    hull() {
        for (x = [r, sx - r], y = [r, sy - r])
            translate([x, y, 0]) cylinder(r = r, h = sz, $fn = 32);
    }
}

module base() {
    difference() {
        rounded_box(outer_x, outer_y, outer_z, 5);
        // hollow interior
        translate([wall, wall, floor_thick])
            rounded_box(outer_x - 2 * wall, outer_y - 2 * wall,
                        outer_z, 3);
        // PCB mounting bosses are added back below
        // cable gland holes on the long wall
        for (y = [outer_y * 0.3, outer_y * 0.7])
            translate([outer_x, y, outer_z * 0.45])
                rotate([0, 90, 0])
                    cylinder(r = 5, h = wall + 2, $fn = 24);
    }

    // mounting bosses for the ESP32 DevKit
    for (dx = [-board_hole_x, board_hole_x],
         dy = [-board_hole_y, board_hole_y])
        translate([outer_x / 2 + dx, outer_y / 2 + dy, floor_thick])
            difference() {
                cylinder(r = boss_d / 2, h = boss_h, $fn = 24);
                cylinder(r = screw_d / 2, h = boss_h + 1, $fn = 16);
            }
}

module lid() {
    difference() {
        translate([0, 0, outer_z])
            rounded_box(outer_x, outer_y, lid_thick, 5);
        // lightening cut-out for status LED / OLED window
        translate([outer_x - 22, outer_y / 2, outer_z - 1])
            cylinder(r = 6, h = lid_thick + 2, $fn = 32);
        // corner screw holes
        for (x = [6, outer_x - 6], y = [6, outer_y - 6])
            translate([x, y, outer_z - 1])
                cylinder(r = screw_d / 2, h = lid_thick + 2, $fn = 16);
    }
}

if (show_base) base();
if (show_lid)  lid();
