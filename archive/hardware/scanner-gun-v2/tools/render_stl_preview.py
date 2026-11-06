#!/usr/bin/env python3
"""Create a lightweight shaded preview from one or more ASCII STL files."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def read_ascii_stl(path: Path) -> tuple[np.ndarray, np.ndarray]:
    triangles: list[list[list[float]]] = []
    normals: list[list[float]] = []
    current: list[list[float]] = []

    with path.open("r", encoding="utf-8", errors="ignore") as stream:
        for raw_line in stream:
            words = raw_line.split()
            if not words:
                continue
            if words[0] == "facet" and len(words) >= 5:
                normals.append([float(value) for value in words[2:5]])
            elif words[0] == "vertex" and len(words) >= 4:
                current.append([float(value) for value in words[1:4]])
                if len(current) == 3:
                    triangles.append(current)
                    current = []

    if not triangles:
        raise ValueError(f"No ASCII STL triangles found in {path}")
    return np.asarray(triangles, dtype=float), np.asarray(normals, dtype=float)


def render(stl_path: Path, output_path: Path, size: int) -> None:
    triangles, normals = read_ascii_stl(stl_path)

    # Front-right three-quarter view: front is negative Y in the CAD model.
    camera = np.asarray([1.15, -1.65, 0.75], dtype=float)
    camera /= np.linalg.norm(camera)
    forward = -camera
    world_up = np.asarray([0.0, 0.0, 1.0])
    right = np.cross(forward, world_up)
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    up /= np.linalg.norm(up)

    center = (triangles.reshape(-1, 3).min(axis=0)
              + triangles.reshape(-1, 3).max(axis=0)) / 2
    triangles = triangles - center

    screen_x = triangles @ right
    screen_y = triangles @ up
    depth = triangles @ camera

    all_x = screen_x.reshape(-1)
    all_y = screen_y.reshape(-1)
    span_x = max(float(np.ptp(all_x)), 1.0)
    span_y = max(float(np.ptp(all_y)), 1.0)
    scale = 0.84 * size / max(span_x, span_y)

    px = size / 2 + screen_x * scale
    py = size / 2 - screen_y * scale

    image = Image.new("RGB", (size, size), (244, 246, 249))
    draw = ImageDraw.Draw(image)

    light = np.asarray([0.5, -0.9, 1.6], dtype=float)
    light /= np.linalg.norm(light)
    normal_lengths = np.linalg.norm(normals, axis=1)
    normal_lengths[normal_lengths == 0] = 1.0
    normals = normals / normal_lengths[:, None]
    facing = normals @ camera
    brightness = np.clip(0.36 + 0.64 * (normals @ light), 0.22, 1.0)

    # Draw far triangles first. This painter-style renderer is sufficient for
    # visual QA of these mostly convex printable parts.
    order = np.argsort(depth.mean(axis=1))
    base = np.asarray([61, 104, 158], dtype=float)
    for index in order:
        if facing[index] <= 0:
            continue
        points = [(float(px[index, i]), float(py[index, i])) for i in range(3)]
        color = tuple(np.clip(base * brightness[index], 0, 255).astype(np.uint8))
        draw.polygon(points, fill=color)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stl", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--size", type=int, default=1200)
    args = parser.parse_args()
    render(args.stl, args.output, args.size)


if __name__ == "__main__":
    main()
