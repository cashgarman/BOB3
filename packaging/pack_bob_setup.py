"""Append installer payloads to BobSetup.exe for single-file distribution."""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

MAGIC = b"BOBPAY01"
TRAILER_SIZE = 24


def payload_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(65536)
                if not chunk:
                    break
                digest.update(chunk)
    return digest.hexdigest()


def pack(stub_exe: Path, output_exe: Path, payload_files: list[Path]) -> None:
    if not stub_exe.is_file():
        raise FileNotFoundError(stub_exe)
    missing = [path for path in payload_files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing payload file(s): {', '.join(str(p) for p in missing)}")

    ordered = sorted(payload_files, key=lambda p: p.name.lower())
    stub_bytes = stub_exe.read_bytes()
    offset = len(stub_bytes)
    entries: list[dict[str, int | str]] = []
    blob = bytearray(stub_bytes)

    for path in ordered:
        data = path.read_bytes()
        entries.append({"name": path.name, "offset": offset, "length": len(data)})
        blob.extend(data)
        offset += len(data)

    manifest = {
        "version": 1,
        "hash": payload_hash(ordered),
        "files": entries,
    }
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
    manifest_offset = len(blob)
    blob.extend(manifest_bytes)
    blob.extend(struct.pack("<QQ", manifest_offset, len(manifest_bytes)))
    blob.extend(MAGIC)

    if len(blob) < TRAILER_SIZE:
        raise ValueError("Packed installer is too small.")
    output_exe.write_bytes(bytes(blob))


def read_manifest(exe_path: Path) -> dict:
    data = exe_path.read_bytes()
    if len(data) < TRAILER_SIZE:
        raise ValueError("File too small for embedded payload.")
    manifest_offset, manifest_length = struct.unpack("<QQ", data[-TRAILER_SIZE:-8])
    if data[-8:] != MAGIC:
        raise ValueError("Embedded payload magic not found.")
    manifest_bytes = data[manifest_offset : manifest_offset + manifest_length]
    return json.loads(manifest_bytes.decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if len(args) < 3:
        print(
            "Usage: pack_bob_setup.py <stub.exe> <output.exe> <payload1> [payload2 ...]",
            file=sys.stderr,
        )
        return 2
    stub = Path(args[0])
    output = Path(args[1])
    payloads = [Path(arg) for arg in args[2:]]
    pack(stub, output, payloads)
    manifest = read_manifest(output)
    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"Packed {len(manifest['files'])} file(s) into {output} ({size_mb:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
