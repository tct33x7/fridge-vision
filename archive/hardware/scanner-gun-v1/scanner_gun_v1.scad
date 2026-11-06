/*
  BX Project - Handheld receipt/list scanner, V1

  Open with OpenSCAD and change `part` below:
    "assembly"      complete concept model
    "exploded"      separated front/rear shells
    "front_shell"   printable front half
    "rear_shell"    printable rear half
    "camera_test"   small camera mounting coupon; print this first

  All dimensions are millimetres. Values marked ESTIMATED should be checked
  against the physical modules before the final print.
*/

$fn = 48;

part = "assembly";

// ---------- Known component dimensions ----------
camera_board = [37.75, 1.6, 37.75];   // X, Y(thickness), Z
camera_center_z = 126;

button_board = [29.92, 1.6, 29.92];   // X, Y(thickness), Z
button_center_z = 96;

insert_thread = 3;                    // M3
insert_outer_d = 3.9;
insert_length = 2.85;

// ---------- Fit allowances ----------
pcb_clearance = 0.65;
shell_wall = 2.4;
seam_gap = 0.30;

// Start point for a 3.9 mm heat-set insert in PETG/PLA.
// Tune this after printing camera_test.
insert_pilot_d = 3.70;
insert_pilot_depth = 3.15;

// ---------- ESTIMATED dimensions from the supplied photos ----------
camera_hole_spacing = [30.8, 30.8];   // X, Z; PCB slots absorb small error
button_hole_spacing = [24.0, 24.0];   // X, Z

// Front/rear shell assembly screws. Each entry is [X, Z]. The screw enters
// from the rear and threads into a heat-set insert in the front-shell boss.
assembly_screw_positions = [
    [-21, 126],
    [ 21, 126],
    [-13,  50],
    [ 13,  50]
];
assembly_clearance_d = 3.4;

// ---------- Overall ergonomic envelope ----------
head_size = [54, 36, 50];             // X, Y, Z
head_center = [0, 0, 126];

grip_bottom_size = [38, 31, 26];
grip_bottom_center = [0, 13, 23];
grip_top_size = [40, 33, 28];
grip_top_center = [0, 2, 94];

cable_exit_d = 10;

// Both PCB faces point forward (-Y). These values set the exterior mounting
// planes; adjust them only after checking the physical grip position.
camera_mount_surface_y = -head_size[1]/2;
button_mount_surface_y = -14.5;

// ---------- Helpers ----------
module rounded_box(size, radius, center=true) {
    safe_r = min(radius, min(size[0], min(size[1], size[2])) / 2 - 0.01);
    if (center) {
        minkowski() {
            cube([size[0]-2*safe_r, size[1]-2*safe_r, size[2]-2*safe_r], center=true);
            sphere(r=safe_r);
        }
    } else {
        translate([safe_r, safe_r, safe_r])
            minkowski() {
                cube([size[0]-2*safe_r, size[1]-2*safe_r, size[2]-2*safe_r]);
                sphere(r=safe_r);
            }
    }
}

module y_cylinder(d, h, center=false) {
    rotate([90, 0, 0]) cylinder(d=d, h=h, center=center);
}

module positive_y_cylinder(d, h, center=false) {
    rotate([-90, 0, 0]) cylinder(d=d, h=h, center=center);
}

module x_cylinder(d, h, center=false) {
    rotate([0, 90, 0]) cylinder(d=d, h=h, center=center);
}

// ---------- Main envelope ----------
module outer_body() {
    union() {
        translate(head_center) rounded_box(head_size, 6);

        hull() {
            translate(grip_bottom_center) rounded_box(grip_bottom_size, 7);
            translate(grip_top_center) rounded_box(grip_top_size, 7);
        }
    }
}

module inner_void() {
    union() {
        translate(head_center)
            rounded_box([
                head_size[0]-2*shell_wall,
                head_size[1]-2*shell_wall,
                head_size[2]-2*shell_wall
            ], 4.5);

        hull() {
            translate([grip_bottom_center[0], grip_bottom_center[1], grip_bottom_center[2]+shell_wall])
                rounded_box([
                    grip_bottom_size[0]-2*shell_wall,
                    grip_bottom_size[1]-2*shell_wall,
                    grip_bottom_size[2]-2*shell_wall
                ], 5);

            translate(grip_top_center)
                rounded_box([
                    grip_top_size[0]-2*shell_wall,
                    grip_top_size[1]-2*shell_wall,
                    grip_top_size[2]-2*shell_wall
                ], 5);
        }
    }
}

// ---------- Camera mounting ----------
module camera_bosses() {
    boss_length = 8;

    for (x = [-camera_hole_spacing[0]/2, camera_hole_spacing[0]/2])
        for (z = [camera_center_z-camera_hole_spacing[1]/2,
                  camera_center_z+camera_hole_spacing[1]/2])
            translate([x, camera_mount_surface_y, z])
                positive_y_cylinder(d=8.5, h=boss_length);
}

module camera_insert_holes() {
    for (x = [-camera_hole_spacing[0]/2, camera_hole_spacing[0]/2])
        for (z = [camera_center_z-camera_hole_spacing[1]/2,
                  camera_center_z+camera_hole_spacing[1]/2])
            translate([x, camera_mount_surface_y-0.05, z])
                positive_y_cylinder(d=insert_pilot_d, h=insert_pilot_depth+0.2);
}

// Small entry slot for the camera's side cable to pass into the hollow body.
module camera_cable_slot() {
    translate([-21, camera_mount_surface_y-2, 104])
        rounded_box([8, 12, 6], 2);
}

module button_cable_slot() {
    translate([-16, button_mount_surface_y-2, 74])
        rounded_box([7, 12, 5], 1.8);
}

// ---------- Button PCB mounting ----------
// The entire button PCB is externally mounted on the front of the grip. Its
// component face points forward and the micro-switch lever points downward,
// giving the user a direct, pistol-trigger-like press point.
module button_bosses() {
    boss_length = 8;

    for (x = [-button_hole_spacing[0]/2, button_hole_spacing[0]/2])
        for (z = [button_center_z-button_hole_spacing[1]/2,
                  button_center_z+button_hole_spacing[1]/2])
            translate([x, button_mount_surface_y, z])
                positive_y_cylinder(d=8.5, h=boss_length);
}

module button_insert_holes() {
    for (x = [-button_hole_spacing[0]/2, button_hole_spacing[0]/2])
        for (z = [button_center_z-button_hole_spacing[1]/2,
                  button_center_z+button_hole_spacing[1]/2])
            translate([x, button_mount_surface_y-0.05, z])
                positive_y_cylinder(d=insert_pilot_d, h=insert_pilot_depth+0.2);
}

// ---------- Cable handling ----------
module cable_exit_cutout() {
    translate([0, grip_bottom_center[1], 0])
        cylinder(d=cable_exit_d, h=24);
}

// Two transverse slots accept a small zip tie as elementary strain relief.
module strain_relief_slots() {
    for (z = [14, 21])
        translate([0, grip_bottom_center[1]+grip_bottom_size[1]/2-1.5, z])
            cube([13, 5, 2.8], center=true);
}

// ---------- Front/rear shell fasteners ----------
module assembly_bosses() {
    for (p = assembly_screw_positions)
        intersection() {
            outer_body();
            translate([p[0], -0.05, p[1]])
                y_cylinder(d=8.5, h=40);
        }
}

module assembly_insert_holes() {
    for (p = assembly_screw_positions)
        translate([p[0], -0.05, p[1]])
            y_cylinder(d=insert_pilot_d, h=insert_pilot_depth+0.2);
}

module assembly_screw_clearance() {
    for (p = assembly_screw_positions)
        translate([p[0], 40, p[1]])
            y_cylinder(d=assembly_clearance_d, h=40);
}

// ---------- Complete hollow body ----------
module body_with_mounts() {
    difference() {
        union() {
            difference() {
                outer_body();
                inner_void();
            }
            camera_bosses();
            button_bosses();
            assembly_bosses();
        }

        camera_insert_holes();
        button_insert_holes();
        camera_cable_slot();
        button_cable_slot();
        cable_exit_cutout();
        strain_relief_slots();
        assembly_insert_holes();
        assembly_screw_clearance();
    }
}

// ---------- Shell halves ----------
module front_shell() {
    intersection() {
        body_with_mounts();
        translate([-100, -100, -10])
            cube([200, 100-seam_gap/2, 220]);
    }
}

module rear_shell() {
    intersection() {
        body_with_mounts();
        translate([-100, seam_gap/2, -10])
            cube([200, 100, 220]);
    }
}

// ---------- Fit-test coupon ----------
module camera_test_coupon() {
    plate_size = [48, 5, 48];
    difference() {
        union() {
            translate([0, 0, camera_center_z])
                rounded_box(plate_size, 3);

            for (x = [-camera_hole_spacing[0]/2, camera_hole_spacing[0]/2])
                for (z = [camera_center_z-camera_hole_spacing[1]/2,
                          camera_center_z+camera_hole_spacing[1]/2])
                    translate([x, -2.5, z])
                        positive_y_cylinder(d=8.5, h=6);
        }

        for (x = [-camera_hole_spacing[0]/2, camera_hole_spacing[0]/2])
            for (z = [camera_center_z-camera_hole_spacing[1]/2,
                      camera_center_z+camera_hole_spacing[1]/2])
                translate([x, -2.55, z])
                    positive_y_cylinder(d=insert_pilot_d, h=insert_pilot_depth+0.2);
    }
}

// ---------- Output selector ----------
if (part == "assembly") {
    color([0.16, 0.20, 0.24]) body_with_mounts();
} else if (part == "exploded") {
    color([0.15, 0.38, 0.72]) translate([0, -24, 0]) front_shell();
    color([0.22, 0.25, 0.30]) translate([0, 24, 0]) rear_shell();
} else if (part == "front_shell") {
    front_shell();
} else if (part == "rear_shell") {
    rear_shell();
} else if (part == "camera_test") {
    translate([0, 0, -camera_center_z]) camera_test_coupon();
} else {
    assert(false, str("Unknown part: ", part));
}
