from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))

from pack_bob_setup import MAGIC, TRAILER_SIZE, pack, payload_hash, read_manifest


def test_pack_and_read_manifest(tmp_path: Path):
    stub = tmp_path / "stub.exe"
    stub.write_bytes(b"MZ-stub-data")
    file_a = tmp_path / "Bob.msi"
    file_b = tmp_path / "helper.exe"
    file_a.write_bytes(b"msi-bytes")
    file_b.write_bytes(b"helper-bytes")
    output = tmp_path / "BobSetup.exe"

    pack(stub, output, [file_b, file_a])

    manifest = read_manifest(output)
    assert manifest["version"] == 1
    assert manifest["hash"] == payload_hash(sorted([file_a, file_b], key=lambda p: p.name.lower()))
    names = {entry["name"] for entry in manifest["files"]}
    assert names == {"Bob.msi", "helper.exe"}

    data = output.read_bytes()
    assert data.startswith(b"MZ-stub-data")
    manifest_offset, manifest_length = struct.unpack("<QQ", data[-TRAILER_SIZE:-8])
    assert data[-8:] == MAGIC
    parsed = json.loads(data[manifest_offset : manifest_offset + manifest_length].decode("utf-8"))
    assert parsed["hash"] == manifest["hash"]

    for entry in manifest["files"]:
        chunk = data[entry["offset"] : entry["offset"] + entry["length"]]
        assert chunk == (tmp_path / entry["name"]).read_bytes()
