/*
  BX Project - Handheld scanner body V3

  This version intentionally contains NO camera or button mock objects.
  It only models the printable handle/body, recessed flat mounting plates,
  screw passages, a hidden cable guide and shell fasteners. There are no
  camera/button mock bodies and no test coupons in V3.

  Coordinate system:
    X = left/right
    Y = front/back (front is negative Y)
    Z = bottom/top

  Export selector:
    "assembly"    complete body
    "exploded"    separated left and right shells
    "left_shell"  printable left shell
    "right_shell" printable right shell
    "dock"        separate wall-mounted/open-top head cradle
*/

$fn = 48;
// Keep the default lightweight so opening the source does not immediately
// evaluate the complete body on slower computers. Choose another part only
// when previewing or exporting it.
part = "left_shell";

// ---------- Measured component envelopes ----------
camera_panel = [37.75, 37.75];
button_panel = [29.92, 29.92];

// V3 camera pattern is opened slightly to 25 x 25 mm; button remains 24 x 24.
camera_hole_spacing = 25.0;
button_hole_spacing = 24.0;

// ---------- M3 hardware ----------
insert_outer_d = 3.9;
insert_length = 2.85;

// Starting values for FDM printing.
insert_pilot_d = 3.70;
insert_pilot_depth = 3.15;
screw_clearance_d = 3.40;

// ---------- Assembly allowances ----------
panel_edge_clearance = 1.2;
shell_wall = 2.4;
shell_seam_gap = 0.30;
front_recess_depth = 1.8;
mount_plate_thickness = 4.8;
camera_aperture_d = 13.9;

// Pads are slightly larger than the physical PCBs.
camera_pad_size = [42.0, 42.0];
button_pad_size = [35.0, 35.0];

// ---------- Body envelope ----------
head_size = [58, 38, 58];
head_center = [0, 0, 130];

grip_top_size = [44, 34, 30];
grip_top_center = [0, 5, 92];

// The grip is lengthened downward only; head width/depth and overall width stay
// unchanged.
grip_bottom_size = [40, 32, 38];
grip_bottom_center = [0, 18, 22];

camera_center_z = 130;
button_center_z = 90;

head_front_y = head_center[1] - head_size[1]/2;
button_support_front_y = head_front_y;
camera_pad_front_y = head_front_y + front_recess_depth;
button_pad_front_y = button_support_front_y + front_recess_depth;

// Left/right shell assembly fasteners, each entry is [Y, Z].
assembly_screw_positions = [
    [  8, 151],
    [  8, 111],
    [ 10,  60],
    [ 18,  14]
];
assembly_clearance_d = 3.4;
assembly_thread_relief_d = 3.3;
assembly_thread_relief_depth = 3.2;

// ---------- Internal cable guide ----------
// A 6.6 x 4.4 mm rounded channel fits a 2.8 mm cable with generous FDM
// tolerance, and can also carry two thin 2.8 mm wires side-by-side. The guide
// is attached to the rear inner wall and is split exactly between left/right
// shells, so each half prints as an open channel without trapped support.
cable_channel_inner = [6.6, 4.4, 12];
cable_channel_outer = [10.0, 7.0, 10];
cable_entry_d = 4.4;
cable_path_points = [
    [0, 14.5, 112],
    [0, 17.0,  92],
    [0, 23.0,  55],
    [0, 29.0,   4]
];

// ---------- Separate head dock ----------
// The dock grips only the rear and side portions of the square head. The front
// remains completely open, so the camera pad and raised button position do not
// interfere with placing or removing the scanner.
dock_clearance = 1.2;
dock_wall = 4.0;
dock_depth = 18.0;
dock_cradle_height = 44.0;
dock_back_thickness = 5.0;
dock_back_height = 70.0;
dock_handle_gap = 46.0;
dock_wall_hole_d = 4.5;

// ---------- Geometry helpers ----------
module rounded_box(size, radius, center=true) {
    safe_r = min(radius, min(size[0], min(size[1], size[2]))/2 - 0.01);
    x_positions = center
        ? [-size[0]/2+safe_r, size[0]/2-safe_r]
        : [safe_r, size[0]-safe_r];
    y_positions = center
        ? [-size[1]/2+safe_r, size[1]/2-safe_r]
        : [safe_r, size[1]-safe_r];
    z_positions = center
        ? [-size[2]/2+safe_r, size[2]/2-safe_r]
        : [safe_r, size[2]-safe_r];

    // Hull-of-spheres is robust in both the CGAL and Manifold backends and
    // avoids renderer-dependent Minkowski fallback warnings.
    hull()
        for (x = x_positions)
            for (y = y_positions)
                for (z = z_positions)
                    translate([x, y, z]) sphere(r=safe_r);
}

// Cylinder axes along -Y and +Y.
module y_negative_cylinder(d, h, center=false) {
    rotate([90, 0, 0]) cylinder(d=d, h=h, center=center);
}

module y_positive_cylinder(d, h, center=false) {
    rotate([-90, 0, 0]) cylinder(d=d, h=h, center=center);
}

// Cylinder axes along -X and +X.
module x_negative_cylinder(d, h, center=false) {
    rotate([0, -90, 0]) cylinder(d=d, h=h, center=center);
}

module x_positive_cylinder(d, h, center=false) {
    rotate([0, 90, 0]) cylinder(d=d, h=h, center=center);
}

// ---------- External body ----------
module outer_body_without_pads() {
    union() {
        translate(head_center)
            rounded_box(head_size, 6);

        hull() {
            translate(grip_top_center)
                rounded_box(grip_top_size, 7);
            translate(grip_bottom_center)
                rounded_box(grip_bottom_size, 8);
        }

        // Flat support behind the externally mounted button PCB.
        translate([0,
                   button_support_front_y + 6,
                   button_center_z])
            rounded_box([44, 12, 39], 4);
    }
}

module mounting_plates() {
    // Both panels sit on a single flat, recessed plate. The plate thickness
    // carries the heat-set insert; no cylinder is placed under the insert.
    translate([0,
               camera_pad_front_y + mount_plate_thickness/2,
               camera_center_z])
        rounded_box([camera_pad_size[0],
                     mount_plate_thickness,
                     camera_pad_size[1]], 3);

    translate([0,
               button_pad_front_y + mount_plate_thickness/2,
               button_center_z])
        rounded_box([button_pad_size[0],
                     mount_plate_thickness,
                     button_pad_size[1]], 3);
}

module mounting_recesses() {
    // Remove only the front bezel depth. The plates are added after the shell
    // is hollowed, so their front faces remain exactly at the recessed plane.
    translate([0,
               head_front_y - 0.05 + (front_recess_depth + 0.05)/2,
               camera_center_z])
        rounded_box([camera_pad_size[0], front_recess_depth + 0.05,
                     camera_pad_size[1]], 3);

    translate([0,
               button_support_front_y - 0.05
                   + (front_recess_depth + 0.05)/2,
               button_center_z])
        rounded_box([button_pad_size[0], front_recess_depth + 0.05,
                     button_pad_size[1]], 3);
}

module inner_void() {
    union() {
        translate(head_center)
            rounded_box([head_size[0]-2*shell_wall,
                         head_size[1]-2*shell_wall,
                         head_size[2]-2*shell_wall], 4.5);

        hull() {
            translate(grip_top_center)
                rounded_box([grip_top_size[0]-2*shell_wall,
                             grip_top_size[1]-2*shell_wall,
                             grip_top_size[2]-2*shell_wall], 5);

            translate([grip_bottom_center[0],
                       grip_bottom_center[1],
                       grip_bottom_center[2]+shell_wall])
                rounded_box([grip_bottom_size[0]-2*shell_wall,
                             grip_bottom_size[1]-2*shell_wall,
                             grip_bottom_size[2]-2*shell_wall], 6);
        }

        // Hollow the raised button support as well. It joins the main grip
        // cavity and leaves only the front wall plus the four mount bosses.
        translate([0,
                   button_support_front_y + shell_wall + 6,
                   button_center_z])
            rounded_box([44-2*shell_wall,
                         12,
                         39-2*shell_wall], 3);
    }
}

// Clearance passages cross the flat mounting plates and meet the insert
// pockets opened from the inside of the shell.
module panel_screw_clearances() {
    for (x = [-camera_hole_spacing/2, camera_hole_spacing/2])
        for (z = [camera_center_z-camera_hole_spacing/2,
                  camera_center_z+camera_hole_spacing/2])
            translate([x, camera_pad_front_y-0.05, z])
                y_positive_cylinder(
                    d=screw_clearance_d,
                    h=mount_plate_thickness+0.2
                );

    for (x = [-button_hole_spacing/2, button_hole_spacing/2])
        for (z = [button_center_z-button_hole_spacing/2,
                  button_center_z+button_hole_spacing/2])
            translate([x, button_pad_front_y-0.05, z])
                y_positive_cylinder(
                    d=screw_clearance_d,
                    h=mount_plate_thickness+0.2
                );
}

// Insert pockets open toward the inside of the shell. Install the inserts from
// inside; screws enter from the external panel side.
module panel_insert_pockets() {
    camera_open_y = camera_pad_front_y + mount_plate_thickness + 0.05;
    for (x = [-camera_hole_spacing/2, camera_hole_spacing/2])
        for (z = [camera_center_z-camera_hole_spacing/2,
                  camera_center_z+camera_hole_spacing/2])
            translate([x, camera_open_y, z])
                y_negative_cylinder(d=insert_pilot_d,
                                    h=insert_pilot_depth+0.2);

    button_open_y = button_pad_front_y + mount_plate_thickness + 0.05;
    for (x = [-button_hole_spacing/2, button_hole_spacing/2])
        for (z = [button_center_z-button_hole_spacing/2,
                  button_center_z+button_hole_spacing/2])
            translate([x, button_open_y, z])
                y_negative_cylinder(d=insert_pilot_d,
                                    h=insert_pilot_depth+0.2);
}

module camera_aperture() {
    translate([0, head_front_y - 0.1, camera_center_z])
        y_positive_cylinder(
            d=camera_aperture_d,
            h=front_recess_depth + mount_plate_thickness
                + shell_wall + 0.5
        );
}

// ---------- Hidden cable entries and internal guide ----------
// Both entry holes sit underneath their respective PCB panels and disappear
// after assembly. No additional opening is visible on the finished front face.
module hidden_panel_cable_entries() {
    translate([0, camera_pad_front_y-0.05, camera_center_z-15])
        y_positive_cylinder(
            d=cable_entry_d,
            h=mount_plate_thickness+shell_wall+0.4
        );

    translate([0, button_pad_front_y-0.05, button_center_z-9])
        y_positive_cylinder(
            d=cable_entry_d,
            h=mount_plate_thickness+shell_wall+0.4
        );
}

module cable_path(size, radius) {
    for (i = [0:len(cable_path_points)-2])
        hull() {
            translate(cable_path_points[i])
                rounded_box(size, radius);
            translate(cable_path_points[i+1])
                rounded_box(size, radius);
        }
}

module cable_guide_outer() {
    // Keep every supporting wall inside the original body silhouette. The
    // inner subtraction below extends through the bottom to form the exit.
    intersection() {
        cable_path(cable_channel_outer, 2.2);
        outer_body_without_pads();
    }
}

module cable_guide_void() {
    cable_path(cable_channel_inner, 1.9);
}

// ---------- Left/right shell fasteners ----------
module assembly_bosses() {
    for (p = assembly_screw_positions)
        intersection() {
            outer_body_without_pads();
            union() {
                // Matching half-posts meet at the shell seam. This transfers
                // screw preload through the posts instead of bending a wall.
                translate([-0.05, p[0], p[1]])
                    x_negative_cylinder(d=8.5, h=45);
                translate([0.05, p[0], p[1]])
                    x_positive_cylinder(d=8.5, h=45);
            }
        }
}

module assembly_insert_pockets() {
    for (p = assembly_screw_positions)
        translate([-0.05, p[0], p[1]])
            x_negative_cylinder(d=insert_pilot_d,
                                h=insert_pilot_depth+0.2);
}

module assembly_screw_clearances() {
    for (p = assembly_screw_positions)
        translate([45, p[0], p[1]])
            x_negative_cylinder(d=assembly_clearance_d, h=45);
}

module assembly_thread_reliefs() {
    for (p = assembly_screw_positions)
        translate([-insert_pilot_depth+0.10, p[0], p[1]])
            x_negative_cylinder(d=assembly_thread_relief_d,
                                h=assembly_thread_relief_depth);
}

// ---------- Final printable body ----------
module scanner_body() {
    difference() {
        union() {
            difference() {
                outer_body_without_pads();
                inner_void();
                mounting_recesses();
            }
            mounting_plates();
            assembly_bosses();
            cable_guide_outer();
        }

        camera_aperture();
        panel_screw_clearances();
        panel_insert_pockets();
        hidden_panel_cable_entries();
        cable_guide_void();
        assembly_insert_pockets();
        assembly_screw_clearances();
        assembly_thread_reliefs();
    }
}

module left_shell() {
    intersection() {
        scanner_body();
        translate([-120, -120, -10])
            cube([120-shell_seam_gap/2, 240, 220]);
    }
}

module right_shell() {
    intersection() {
        scanner_body();
        translate([shell_seam_gap/2, -120, -10])
            cube([120, 240, 220]);
    }
}

// ---------- Minimal open-top dock ----------
// The square head slides down from above. Two short, symmetric lower shelves
// support its side edges while the handle hangs freely through the centre gap.
module head_dock() {
    inner_width = head_size[0] + 2*dock_clearance;
    outer_width = inner_width + 2*dock_wall;
    shelf_width = (inner_width-dock_handle_gap)/2;
    back_y = dock_depth + dock_back_thickness/2;
    side_x = inner_width/2 + dock_wall/2;
    shelf_x = dock_handle_gap/2 + shelf_width/2;
    shelf_z = -dock_cradle_height/2 + dock_wall/2;

    difference() {
        union() {
            // Rear wall plate.
            translate([0, back_y, 0])
                rounded_box([outer_width+10,
                             dock_back_thickness,
                             dock_back_height], 4);

            // Symmetric side guides; top and front remain open.
            for (x = [-side_x, side_x])
                translate([x, dock_depth/2, 0])
                    rounded_box([dock_wall,
                                 dock_depth,
                                 dock_cradle_height], 2);

            // Two small lower shelves leave the centre open for the handle.
            for (x = [-shelf_x, shelf_x])
                translate([x, dock_depth/2, shelf_z])
                    rounded_box([shelf_width,
                                 dock_depth,
                                 dock_wall], 1.5);
        }

        // Four symmetric wall-mounting holes through the rear plate.
        for (x = [-24, 24])
            for (z = [-24, 24])
                translate([x, dock_depth-0.2, z])
                    y_positive_cylinder(d=dock_wall_hole_d,
                                        h=dock_back_thickness+0.4);
    }
}

// ---------- Output ----------
if (part == "assembly") {
    color([0.16, 0.20, 0.24]) scanner_body();
} else if (part == "exploded") {
    color([0.15, 0.38, 0.72])
        translate([-24, 0, 0]) left_shell();
    color([0.22, 0.25, 0.30])
        translate([24, 0, 0]) right_shell();
} else if (part == "left_shell") {
    left_shell();
} else if (part == "right_shell") {
    right_shell();
} else if (part == "dock") {
    head_dock();
} else {
    assert(false, str("Unknown part: ", part));
}
