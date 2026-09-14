"""Stamp FileDescription / ProductName / icons onto a Windows PE so Settings lists Bob."""

from __future__ import annotations

import ctypes
import struct
from ctypes import wintypes
from pathlib import Path

RT_ICON = 3
RT_GROUP_ICON = 14
RT_VERSION = 16
LANG_NEUTRAL = 0
LANG_US = 1033

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ENUMRESNAMEPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
)
ENUMRESLANGPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMODULE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.WORD,
    ctypes.c_void_p,
)

kernel32.LoadLibraryExW.restype = wintypes.HMODULE
kernel32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
kernel32.FreeLibrary.argtypes = [wintypes.HMODULE]
kernel32.EnumResourceNamesW.restype = wintypes.BOOL
kernel32.EnumResourceNamesW.argtypes = [
    wintypes.HMODULE,
    ctypes.c_void_p,
    ENUMRESNAMEPROC,
    ctypes.c_void_p,
]
kernel32.EnumResourceLanguagesW.restype = wintypes.BOOL
kernel32.EnumResourceLanguagesW.argtypes = [
    wintypes.HMODULE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ENUMRESLANGPROC,
    ctypes.c_void_p,
]
kernel32.BeginUpdateResourceW.restype = wintypes.HANDLE
kernel32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
kernel32.UpdateResourceW.restype = wintypes.BOOL
kernel32.UpdateResourceW.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.WORD,
    ctypes.c_void_p,
    wintypes.DWORD,
]
kernel32.EndUpdateResourceW.restype = wintypes.BOOL
kernel32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]

LOAD_LIBRARY_AS_DATAFILE = 0x00000002


def _is_int_resource(ptr: int) -> bool:
    return ptr < 0x10000


def _name_from_ptr(lp_name: int) -> int | str:
    if _is_int_resource(lp_name):
        return lp_name
    return ctypes.wstring_at(lp_name)


def _res_id(value: int | str, keep: list) -> ctypes.c_void_p:
    if isinstance(value, int):
        return ctypes.c_void_p(value)
    buf = ctypes.create_unicode_buffer(value)
    keep.append(buf)
    return ctypes.cast(buf, ctypes.c_void_p)


def _enum_resources(exe: Path, restype: int) -> list[tuple[int | str, int]]:
    found: list[tuple[int | str, int]] = []
    module = kernel32.LoadLibraryExW(str(exe), None, LOAD_LIBRARY_AS_DATAFILE)
    if not module:
        return found
    names: list[int | str] = []

    def on_name(hmod, lp_type, lp_name, _lparam):
        names.append(_name_from_ptr(lp_name))
        return True

    kernel32.EnumResourceNamesW(module, ctypes.c_void_p(restype), ENUMRESNAMEPROC(on_name), None)
    for name in names:
        langs: list[int] = []

        def on_lang(hmod, lp_type, lp_name, lang, _lparam, _name=name, _langs=langs):
            _langs.append(int(lang))
            return True

        name_arg = ctypes.c_void_p(name) if isinstance(name, int) else ctypes.c_wchar_p(name)
        kernel32.EnumResourceLanguagesW(
            module,
            ctypes.c_void_p(restype),
            name_arg,
            ENUMRESLANGPROC(on_lang),
            None,
        )
        for lang in langs or [LANG_NEUTRAL]:
            found.append((name, lang))
    kernel32.FreeLibrary(module)
    return found


def _dword_pad(n: int) -> int:
    return (4 - (n % 4)) % 4


def _pack_node(key: str, value: bytes, w_type: int, children: bytes = b"") -> bytes:
    key_bytes = (key + "\0").encode("utf-16le")
    header_and_key = 6 + len(key_bytes)
    pad1 = _dword_pad(header_and_key)
    if w_type == 1:
        w_value_length = len(value) // 2
    else:
        w_value_length = len(value)
    before_children = header_and_key + pad1 + len(value)
    pad2 = _dword_pad(before_children) if children else 0
    w_length = before_children + pad2 + len(children)
    return (
        struct.pack("<HHH", w_length, w_value_length, w_type)
        + key_bytes
        + (b"\x00" * pad1)
        + value
        + (b"\x00" * pad2)
        + children
    )


def _utf16z(text: str) -> bytes:
    return (text + "\0").encode("utf-16le")


def build_version_info(
    *,
    file_description: str,
    product_name: str,
    company: str,
    original_filename: str,
    version: str,
    copyright_text: str = "",
) -> bytes:
    parts = [int(p) for p in (version.split(".") + ["0", "0", "0", "0"])[:4]]
    ms = (parts[0] << 16) | parts[1]
    ls = (parts[2] << 16) | parts[3]
    fixed = struct.pack(
        "<13I",
        0xFEEF04BD,  # dwSignature
        0x00010000,  # dwStrucVersion
        ms,  # dwFileVersionMS
        ls,  # dwFileVersionLS
        ms,  # dwProductVersionMS
        ls,  # dwProductVersionLS
        0x3F,  # dwFileFlagsMask
        0,  # dwFileFlags
        0x00040004,  # dwFileOS VOS_NT_WINDOWS32
        1,  # dwFileType VFT_APP
        0,  # dwFileSubtype
        0,  # dwFileDateMS
        0,  # dwFileDateLS
    )
    version_display = ".".join(str(p) for p in parts)
    strings = [
        ("CompanyName", company),
        ("FileDescription", file_description),
        ("FileVersion", version_display),
        ("InternalName", product_name),
        ("LegalCopyright", copyright_text or f"© {company}"),
        ("OriginalFilename", original_filename),
        ("ProductName", product_name),
        ("ProductVersion", version_display),
    ]
    string_nodes = b"".join(
        _pack_node(key, _utf16z(val), 1) for key, val in strings if val is not None
    )
    string_table = _pack_node("040904B0", b"", 1, string_nodes)
    string_file_info = _pack_node("StringFileInfo", b"", 1, string_table)
    translation = struct.pack("<HH", 0x0409, 0x04B0)
    var = _pack_node("Translation", translation, 0)
    var_file_info = _pack_node("VarFileInfo", b"", 1, var)
    return _pack_node("VS_VERSION_INFO", fixed, 0, string_file_info + var_file_info)


def parse_ico(path: Path) -> tuple[bytes, list[bytes]]:
    data = path.read_bytes()
    reserved, ico_type, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or ico_type != 1 or count < 1:
        raise ValueError(f"Not a valid ICO: {path}")
    images: list[bytes] = []
    group = struct.pack("<HHH", 0, 1, count)
    offset = 6
    for index in range(count):
        width, height, colors, _res, planes, bitcount, size, img_offset = struct.unpack_from(
            "<BBBBHHII", data, offset
        )
        offset += 16
        images.append(data[img_offset : img_offset + size])
        group += struct.pack(
            "<BBBBHHIH",
            width,
            height,
            colors,
            0,
            planes or 1,
            bitcount or 32,
            size,
            index + 1,
        )
    return group, images


def stamp_exe(
    exe: Path,
    ico: Path,
    *,
    file_description: str,
    product_name: str,
    company: str,
    original_filename: str,
    version: str,
) -> None:
    existing: list[tuple[int, int | str, int]] = []
    for restype in (RT_ICON, RT_GROUP_ICON, RT_VERSION):
        for name, lang in _enum_resources(exe, restype):
            existing.append((restype, name, lang))

    handle = kernel32.BeginUpdateResourceW(str(exe), False)
    if not handle:
        raise OSError(f"BeginUpdateResource failed for {exe}")
    keep: list = []
    try:
        for restype, name, lang in existing:
            ok = kernel32.UpdateResourceW(
                handle,
                ctypes.c_void_p(restype),
                _res_id(name, keep),
                lang,
                None,
                0,
            )
            if not ok:
                raise ctypes.WinError(ctypes.get_last_error())

        version_blob = build_version_info(
            file_description=file_description,
            product_name=product_name,
            company=company,
            original_filename=original_filename,
            version=version,
        )
        version_buf = ctypes.create_string_buffer(version_blob, len(version_blob))
        keep.append(version_buf)
        if not kernel32.UpdateResourceW(
            handle,
            ctypes.c_void_p(RT_VERSION),
            ctypes.c_void_p(1),
            LANG_US,
            version_buf,
            len(version_blob),
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        group, images = parse_ico(ico)
        for index, image in enumerate(images, start=1):
            buf = ctypes.create_string_buffer(image, len(image))
            keep.append(buf)
            if not kernel32.UpdateResourceW(
                handle,
                ctypes.c_void_p(RT_ICON),
                ctypes.c_void_p(index),
                LANG_US,
                buf,
                len(image),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
        group_buf = ctypes.create_string_buffer(group, len(group))
        keep.append(group_buf)
        if not kernel32.UpdateResourceW(
            handle,
            ctypes.c_void_p(RT_GROUP_ICON),
            ctypes.c_void_p(1),
            LANG_US,
            group_buf,
            len(group),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel32.EndUpdateResourceW(handle, False):
            raise ctypes.WinError(ctypes.get_last_error())
        handle = None
    finally:
        if handle:
            kernel32.EndUpdateResourceW(handle, True)
        keep.clear()
