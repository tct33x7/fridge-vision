"""Parametric B-Rep rebuild of Scanner Gun V3 for Fusion 360 / STEP."""

from __future__ import annotations

from pathlib import Path

import cadquery as cq


OUTPUT_DIR = Path(
    globals().get(
        "__file__",
        "/private/var/hiddenadmin/Desktop/BX Project/hardware/scanner-gun-v3/fusion360/scanner_gun_v3_cadquery.py",
    )
).resolve().parent
PRINT_DIR = OUTPUT_DIR.parent / "exports"

# ---------- Exact measured and agreed dimensions (mm) ----------
CAMERA_PANEL = (37.75, 37.75)
BUTTON_PANEL = (29.92, 29.92)
CAMERA_HOLE_SPACING = 25.0
BUTTON_HOLE_SPACING = 24.0

INSERT_OUTER_D = 3.9
INSERT_LENGTH = 2.85
INSERT_PILOT_D = 3.70
INSERT_PILOT_DEPTH = 3.15
SCREW_CLEARANCE_D = 3.40

SHELL_WALL = 2.4
SHELL_SEAM_GAP = 0.30

# V3 mounts both panels on a recessed, flat lower plane.  The plate is thick
# enough for the 2.85 mm heat-set insert while remaining flush under the PCB;
# no cylindrical boss is placed underneath the insert.
FRONT_RECESS_DEPTH = 1.8
MOUNT_PLATE_THICKNESS = 4.8
CAMERA_APERTURE_D = 13.9

CAMERA_PAD_SIZE = (42.0, 42.0)
BUTTON_PAD_SIZE = (35.0, 35.0)

HEAD_SIZE = (58.0, 38.0, 58.0)
HEAD_CENTER = (0.0, 0.0, 130.0)

GRIP_TOP_SIZE = (44.0, 34.0, 30.0)
GRIP_TOP_CENTER = (0.0, 5.0, 92.0)
GRIP_BOTTOM_SIZE = (40.0, 32.0, 38.0)
GRIP_BOTTOM_CENTER = (0.0, 18.0, 22.0)

CAMERA_CENTER_Z = 130.0
BUTTON_CENTER_Z = 90.0

HEAD_FRONT_Y = HEAD_CENTER[1] - HEAD_SIZE[1] / 2
BUTTON_SUPPORT_FRONT_Y = HEAD_FRONT_Y
CAMERA_PAD_FRONT_Y = HEAD_FRONT_Y + FRONT_RECESS_DEPTH
BUTTON_PAD_FRONT_Y = BUTTON_SUPPORT_FRONT_Y + FRONT_RECESS_DEPTH

ASSEMBLY_SCREW_POSITIONS = (
    (8.0, 151.0),
    (8.0, 111.0),
    (10.0, 60.0),
    (18.0, 14.0),
)
ASSEMBLY_CLEARANCE_D = 3.4
ASSEMBLY_THREAD_RELIEF_D = 3.3
ASSEMBLY_THREAD_RELIEF_DEPTH = 3.2

CABLE_CHANNEL_INNER = (6.6, 4.4)
CABLE_CHANNEL_OUTER = (10.0, 7.0)
CABLE_ENTRY_D = 4.4

DOCK_CLEARANCE = 1.2
DOCK_WALL = 4.0
DOCK_DEPTH = 18.0
DOCK_CRADLE_HEIGHT = 44.0
DOCK_BACK_THICKNESS = 5.0
DOCK_BACK_HEIGHT = 70.0
DOCK_HANDLE_GAP = 46.0
DOCK_WALL_HOLE_D = 4.5


def rounded_box(size, radius, center=(0.0, 0.0, 0.0)):
    safe_radius = min(radius, min(size) / 2 - 0.01)
    result = cq.Workplane("XY").box(*size, centered=(True, True, True))
    if safe_radius > 0:
        result = result.edges().fillet(safe_radius)
    return result.val().translate(center)


def rounded_loft(profiles):
    sketches = []
    for width, depth, radius, center_y, z in profiles:
        sketch = (
            cq.Sketch()
            .rect(width, depth)
            .vertices()
            .fillet(radius)
            .moved(y=center_y, z=z)
        )
        sketches.append(sketch)
    return cq.Workplane("XY").placeSketch(*sketches).loft().val()


def cylinder(radius, length, start, direction):
    return cq.Solid.makeCylinder(
        radius,
        length,
        cq.Vector(*start),
        cq.Vector(*direction),
    )


def fuse_all(shapes):
    iterator = iter(shapes)
    result = next(iterator)
    for shape in iterator:
        result = result.fuse(shape)
    return result.clean()


def cut_all(shape, cutters):
    result = shape
    for cutter in cutters:
        result = result.cut(cutter)
    return result.clean()


def build_scanner_body():
    head = rounded_box(HEAD_SIZE, 6.0, HEAD_CENTER)

    # Clean analytic loft replaces the OpenSCAD 3-D hull while preserving the
    # exact top/bottom envelopes and centre offsets.
    grip = rounded_loft(
        (
            (
                GRIP_BOTTOM_SIZE[0],
                GRIP_BOTTOM_SIZE[1],
                8.0,
                GRIP_BOTTOM_CENTER[1],
                GRIP_BOTTOM_CENTER[2] - GRIP_BOTTOM_SIZE[2] / 2,
            ),
            (
                GRIP_BOTTOM_SIZE[0],
                GRIP_BOTTOM_SIZE[1],
                8.0,
                GRIP_BOTTOM_CENTER[1],
                GRIP_BOTTOM_CENTER[2] + GRIP_BOTTOM_SIZE[2] / 2,
            ),
            (
                GRIP_TOP_SIZE[0],
                GRIP_TOP_SIZE[1],
                7.0,
                GRIP_TOP_CENTER[1],
                GRIP_TOP_CENTER[2] - GRIP_TOP_SIZE[2] / 2,
            ),
            (
                GRIP_TOP_SIZE[0],
                GRIP_TOP_SIZE[1],
                7.0,
                GRIP_TOP_CENTER[1],
                GRIP_TOP_CENTER[2] + GRIP_TOP_SIZE[2] / 2,
            ),
        )
    )

    button_support = rounded_box(
        (44.0, 12.0, 39.0),
        4.0,
        (0.0, BUTTON_SUPPORT_FRONT_Y + 6.0, BUTTON_CENTER_Z),
    )
    outer_without_pads = fuse_all((head, grip, button_support))

    camera_pad = rounded_box(
        (CAMERA_PAD_SIZE[0], MOUNT_PLATE_THICKNESS, CAMERA_PAD_SIZE[1]),
        3.0,
        (
            0.0,
            CAMERA_PAD_FRONT_Y + MOUNT_PLATE_THICKNESS / 2,
            CAMERA_CENTER_Z,
        ),
    )
    button_pad = rounded_box(
        (BUTTON_PAD_SIZE[0], MOUNT_PLATE_THICKNESS, BUTTON_PAD_SIZE[1]),
        3.0,
        (
            0.0,
            BUTTON_PAD_FRONT_Y + MOUNT_PLATE_THICKNESS / 2,
            BUTTON_CENTER_Z,
        ),
    )

    inner_head = rounded_box(
        tuple(value - 2 * SHELL_WALL for value in HEAD_SIZE),
        4.5,
        HEAD_CENTER,
    )
    inner_grip = rounded_loft(
        (
            (
                GRIP_BOTTOM_SIZE[0] - 2 * SHELL_WALL,
                GRIP_BOTTOM_SIZE[1] - 2 * SHELL_WALL,
                6.0,
                GRIP_BOTTOM_CENTER[1],
                GRIP_BOTTOM_CENTER[2] - GRIP_BOTTOM_SIZE[2] / 2
                + 2 * SHELL_WALL,
            ),
            (
                GRIP_BOTTOM_SIZE[0] - 2 * SHELL_WALL,
                GRIP_BOTTOM_SIZE[1] - 2 * SHELL_WALL,
                6.0,
                GRIP_BOTTOM_CENTER[1],
                GRIP_BOTTOM_CENTER[2] + GRIP_BOTTOM_SIZE[2] / 2
                - SHELL_WALL,
            ),
            (
                GRIP_TOP_SIZE[0] - 2 * SHELL_WALL,
                GRIP_TOP_SIZE[1] - 2 * SHELL_WALL,
                5.0,
                GRIP_TOP_CENTER[1],
                GRIP_TOP_CENTER[2] - GRIP_TOP_SIZE[2] / 2
                + SHELL_WALL,
            ),
            (
                GRIP_TOP_SIZE[0] - 2 * SHELL_WALL,
                GRIP_TOP_SIZE[1] - 2 * SHELL_WALL,
                5.0,
                GRIP_TOP_CENTER[1],
                GRIP_TOP_CENTER[2] + GRIP_TOP_SIZE[2] / 2
                - SHELL_WALL,
            ),
        )
    )
    inner_button_support = rounded_box(
        (44.0 - 2 * SHELL_WALL, 12.0, 39.0 - 2 * SHELL_WALL),
        3.0,
        (
            0.0,
            BUTTON_SUPPORT_FRONT_Y + SHELL_WALL + 6.0,
            BUTTON_CENTER_Z,
        ),
    )
    inner_void = fuse_all((inner_head, inner_grip, inner_button_support))
    # Hollow the shell first, then add the two thick, flat recessed mounting
    # plates. This leaves a clean panel contact face and removes the V2
    # cylindrical structures below the heat-set inserts.
    body = outer_without_pads.cut(inner_void)
    body = fuse_all((body, camera_pad, button_pad))

    recess_cutters = [
        rounded_box(
            (
                CAMERA_PAD_SIZE[0],
                FRONT_RECESS_DEPTH + 0.05,
                CAMERA_PAD_SIZE[1],
            ),
            3.0,
            (
                0.0,
                HEAD_FRONT_Y - 0.05 + (FRONT_RECESS_DEPTH + 0.05) / 2,
                CAMERA_CENTER_Z,
            ),
        ),
        rounded_box(
            (
                BUTTON_PAD_SIZE[0],
                FRONT_RECESS_DEPTH + 0.05,
                BUTTON_PAD_SIZE[1],
            ),
            3.0,
            (
                0.0,
                BUTTON_SUPPORT_FRONT_Y - 0.05
                + (FRONT_RECESS_DEPTH + 0.05) / 2,
                BUTTON_CENTER_Z,
            ),
        ),
    ]
    body = cut_all(body, recess_cutters)

    assembly_bosses = []
    for y, z in ASSEMBLY_SCREW_POSITIONS:
        cross_post = cylinder(8.5 / 2, 90.0, (-45.0, y, z), (1.0, 0.0, 0.0))
        assembly_bosses.append(cross_post.intersect(outer_without_pads))

    cable_outer = rounded_loft(
        (
            (CABLE_CHANNEL_OUTER[0], CABLE_CHANNEL_OUTER[1], 2.2, 29.0, -1.0),
            (CABLE_CHANNEL_OUTER[0], CABLE_CHANNEL_OUTER[1], 2.2, 23.0, 55.0),
            (CABLE_CHANNEL_OUTER[0], CABLE_CHANNEL_OUTER[1], 2.2, 17.0, 92.0),
            (CABLE_CHANNEL_OUTER[0], CABLE_CHANNEL_OUTER[1], 2.2, 14.5, 117.0),
        )
    ).intersect(outer_without_pads)

    body = fuse_all((body, *assembly_bosses, cable_outer))

    cutters = [
        # The camera lens passes through the front bezel and the mounting
        # plate. The aperture is deliberately only 13.9 mm, leaving a broad
        # flat rim for the panel and keeping the front symmetric.
        cylinder(
            CAMERA_APERTURE_D / 2,
            FRONT_RECESS_DEPTH + MOUNT_PLATE_THICKNESS + SHELL_WALL + 0.5,
            (0.0, HEAD_FRONT_Y - 0.1, CAMERA_CENTER_Z),
            (0.0, 1.0, 0.0),
        )
    ]
    for spacing, center_z, pad_front_y in (
        (CAMERA_HOLE_SPACING, CAMERA_CENTER_Z, CAMERA_PAD_FRONT_Y),
        (BUTTON_HOLE_SPACING, BUTTON_CENTER_Z, BUTTON_PAD_FRONT_Y),
    ):
        plate_back_y = pad_front_y + MOUNT_PLATE_THICKNESS
        for x in (-spacing / 2, spacing / 2):
            for z in (center_z - spacing / 2, center_z + spacing / 2):
                cutters.append(
                    cylinder(
                        SCREW_CLEARANCE_D / 2,
                        MOUNT_PLATE_THICKNESS + 0.2,
                        (x, pad_front_y - 0.05, z),
                        (0.0, 1.0, 0.0),
                    )
                )
                cutters.append(
                    cylinder(
                        INSERT_PILOT_D / 2,
                        INSERT_PILOT_DEPTH + 0.2,
                        (x, plate_back_y + 0.05, z),
                        (0.0, -1.0, 0.0),
                    )
                )

    cutters.extend(
        (
            cylinder(
                CABLE_ENTRY_D / 2,
                MOUNT_PLATE_THICKNESS + SHELL_WALL + 0.4,
                (0.0, CAMERA_PAD_FRONT_Y - 0.05, CAMERA_CENTER_Z - 15.0),
                (0.0, 1.0, 0.0),
            ),
            cylinder(
                CABLE_ENTRY_D / 2,
                MOUNT_PLATE_THICKNESS + SHELL_WALL + 0.4,
                (0.0, BUTTON_PAD_FRONT_Y - 0.05, BUTTON_CENTER_Z - 9.0),
                (0.0, 1.0, 0.0),
            ),
        )
    )

    cable_inner = rounded_loft(
        (
            (CABLE_CHANNEL_INNER[0], CABLE_CHANNEL_INNER[1], 1.9, 29.0, -2.0),
            (CABLE_CHANNEL_INNER[0], CABLE_CHANNEL_INNER[1], 1.9, 23.0, 55.0),
            (CABLE_CHANNEL_INNER[0], CABLE_CHANNEL_INNER[1], 1.9, 17.0, 92.0),
            (CABLE_CHANNEL_INNER[0], CABLE_CHANNEL_INNER[1], 1.9, 14.5, 118.0),
        )
    )
    cutters.append(cable_inner)

    for y, z in ASSEMBLY_SCREW_POSITIONS:
        cutters.append(
            cylinder(
                INSERT_PILOT_D / 2,
                INSERT_PILOT_DEPTH + 0.2,
                (-0.05, y, z),
                (-1.0, 0.0, 0.0),
            )
        )
        cutters.append(
            cylinder(
                ASSEMBLY_CLEARANCE_D / 2,
                45.0,
                (45.0, y, z),
                (-1.0, 0.0, 0.0),
            )
        )
        cutters.append(
            cylinder(
                ASSEMBLY_THREAD_RELIEF_D / 2,
                ASSEMBLY_THREAD_RELIEF_DEPTH,
                (-INSERT_PILOT_DEPTH + 0.10, y, z),
                (-1.0, 0.0, 0.0),
            )
        )

    return cut_all(body, cutters)


def split_shells(body):
    left_width = 120.0 - SHELL_SEAM_GAP / 2
    left_clip = rounded_box(
        (left_width, 240.0, 220.0),
        0.0,
        (-120.0 + left_width / 2, 0.0, 100.0),
    )
    right_width = 120.0 - SHELL_SEAM_GAP / 2
    right_clip = rounded_box(
        (right_width, 240.0, 220.0),
        0.0,
        (SHELL_SEAM_GAP / 2 + right_width / 2, 0.0, 100.0),
    )
    return body.intersect(left_clip).clean(), body.intersect(right_clip).clean()


def build_dock():
    inner_width = HEAD_SIZE[0] + 2 * DOCK_CLEARANCE
    outer_width = inner_width + 2 * DOCK_WALL
    shelf_width = (inner_width - DOCK_HANDLE_GAP) / 2
    back_y = DOCK_DEPTH + DOCK_BACK_THICKNESS / 2
    side_x = inner_width / 2 + DOCK_WALL / 2
    shelf_x = DOCK_HANDLE_GAP / 2 + shelf_width / 2
    shelf_z = -DOCK_CRADLE_HEIGHT / 2 + DOCK_WALL / 2

    pieces = [
        rounded_box(
            (outer_width + 10.0, DOCK_BACK_THICKNESS, DOCK_BACK_HEIGHT),
            4.0,
            (0.0, back_y, 0.0),
        )
    ]
    for x in (-side_x, side_x):
        pieces.append(
            rounded_box(
                (DOCK_WALL, DOCK_DEPTH, DOCK_CRADLE_HEIGHT),
                2.0,
                (x, DOCK_DEPTH / 2, 0.0),
            )
        )
    for x in (-shelf_x, shelf_x):
        pieces.append(
            rounded_box(
                (shelf_width, DOCK_DEPTH, DOCK_WALL),
                1.5,
                (x, DOCK_DEPTH / 2, shelf_z),
            )
        )

    dock = fuse_all(pieces)
    holes = []
    for x in (-24.0, 24.0):
        for z in (-24.0, 24.0):
            holes.append(
                cylinder(
                    DOCK_WALL_HOLE_D / 2,
                    DOCK_BACK_THICKNESS + 0.4,
                    (x, DOCK_DEPTH - 0.2, z),
                    (0.0, 1.0, 0.0),
                )
            )
    return cut_all(dock, holes)


def validate_shape(name, shape):
    box = shape.BoundingBox()
    if not shape.isValid():
        raise RuntimeError(f"{name} is not a valid B-Rep")
    if shape.Volume() <= 0:
        raise RuntimeError(f"{name} has no solid volume")
    print(
        f"{name}: valid, volume={shape.Volume():.2f} mm^3, "
        f"bbox=({box.xlen:.2f}, {box.ylen:.2f}, {box.zlen:.2f}) mm"
    )


def main():
    print("Building clean V3 B-Rep geometry...")
    body = build_scanner_body()
    left_shell, right_shell = split_shells(body)
    dock = build_dock()

    parts = {
        "scanner_left_shell_v3": left_shell,
        "scanner_right_shell_v3": right_shell,
        "scanner_dock_v3": dock,
    }
    for name, shape in parts.items():
        validate_shape(name, shape)
        cq.exporters.export(shape, str(OUTPUT_DIR / f"{name}.step"))
        if name != "scanner_dock_v3":
            PRINT_DIR.mkdir(parents=True, exist_ok=True)
        cq.exporters.export(shape, str(PRINT_DIR / f"{name}.stl"))

    assembly = cq.Assembly(name="Scanner Gun V3 Editable")
    assembly.add(left_shell, name="01 Left Shell", color=cq.Color(0.20, 0.42, 0.72))
    assembly.add(right_shell, name="02 Right Shell", color=cq.Color(0.30, 0.33, 0.38))
    assembly.add(
        dock,
        name="03 Head Dock",
        color=cq.Color(0.25, 0.50, 0.35),
        loc=cq.Location(cq.Vector(105.0, 0.0, 100.0)),
    )
    assembly.export(str(OUTPUT_DIR / "scanner_gun_v3_editable.step"))
    print("STEP export complete")


if __name__ == "__main__":
    main()
