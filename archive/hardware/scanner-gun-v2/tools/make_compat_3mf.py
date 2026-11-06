#!/usr/bin/env python3
"""Convert a binary STL into a minimal core-only 3MF package."""

from __future__ import annotations

import argparse
import io
import struct
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"


def read_binary_stl(path: Path):
    data = path.read_bytes()
    if len(data) < 84:
        raise ValueError(f"Binary STL is too short: {path}")
    triangle_count = struct.unpack_from("<I", data, 80)[0]
    expected_size = 84 + triangle_count * 50
    if len(data) != expected_size:
        raise ValueError(
            f"Binary STL size mismatch: expected {expected_size}, got {len(data)}"
        )

    vertices: list[tuple[float, float, float]] = []
    vertex_ids: dict[tuple[float, float, float], int] = {}
    triangles: list[tuple[int, int, int]] = []

    offset = 84
    for _ in range(triangle_count):
        face: list[int] = []
        for vertex_offset in (12, 24, 36):
            vertex = struct.unpack_from("<fff", data, offset + vertex_offset)
            vertex_id = vertex_ids.get(vertex)
            if vertex_id is None:
                vertex_id = len(vertices)
                vertex_ids[vertex] = vertex_id
                vertices.append(vertex)
            face.append(vertex_id)
        triangles.append((face[0], face[1], face[2]))
        offset += 50

    return vertices, triangles


def model_xml(name: str, vertices, triangles) -> bytes:
    stream = io.StringIO()
    stream.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    stream.write(f'<model unit="millimeter" xml:lang="en-US" xmlns="{CORE}">\n')
    stream.write(f'  <metadata name="Title">{escape(name)}</metadata>\n')
    stream.write("  <resources>\n")
    stream.write('    <object id="1" type="model">\n')
    stream.write("      <mesh>\n")
    stream.write("        <vertices>\n")
    for x, y, z in vertices:
        stream.write(
            f'          <vertex x="{x:.9g}" y="{y:.9g}" z="{z:.9g}"/>\n'
        )
    stream.write("        </vertices>\n")
    stream.write("        <triangles>\n")
    for v1, v2, v3 in triangles:
        stream.write(f'          <triangle v1="{v1}" v2="{v2}" v3="{v3}"/>\n')
    stream.write("        </triangles>\n")
    stream.write("      </mesh>\n")
    stream.write("    </object>\n")
    stream.write("  </resources>\n")
    stream.write("  <build>\n")
    stream.write('    <item objectid="1"/>\n')
    stream.write("  </build>\n")
    stream.write("</model>\n")
    return stream.getvalue().encode("utf-8")


def write_3mf(stl_path: Path, output_path: Path) -> None:
    vertices, triangles = read_binary_stl(stl_path)
    content_types = f'''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="{CONTENT_TYPES}">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>
'''.encode("utf-8")
    relationships = f'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="{REL}">
  <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
'''.encode("utf-8")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        allowZip64=False,
    ) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr(
            "3D/3dmodel.model",
            model_xml(stl_path.stem, vertices, triangles),
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stl", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    write_3mf(args.stl, args.output)


if __name__ == "__main__":
    main()
