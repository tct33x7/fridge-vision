// Re-import check for the smallest compatibility exports.
source_format = "stl";

if (source_format == "stl") {
    import("../compatibility/scanner_mount_test_v2_compat.stl");
} else if (source_format == "3mf") {
    import("../compatibility/scanner_mount_test_v2_compat.3mf");
} else {
    assert(false, str("Unknown source format: ", source_format));
}
