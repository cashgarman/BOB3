"""Windows 10/11 toast notifications via WinRT (not tray balloon tips).

pystray's Shell_NotifyIcon balloons are ignored on current Windows 11, so
loading progress never appeared. This talks to ToastNotificationManager with
Bob's AppUserModelID and, if needed, writes the Start Menu shortcut Windows
requires before it will show a desktop toast.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import wintypes
from xml.sax.saxutils import escape

log = logging.getLogger(__name__)

_inited = False
_ok = False


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __init__(self, d1: int, d2: int, d3: int, d4: tuple[int, ...]) -> None:
        super().__init__(d1, d2, d3, (ctypes.c_ubyte * 8)(*d4))


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_uint32)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("wReserved1", ctypes.c_ushort),
        ("wReserved2", ctypes.c_ushort),
        ("wReserved3", ctypes.c_ushort),
        ("pwszVal", ctypes.c_void_p),
        ("_pad", ctypes.c_byte * 8),
    ]


HSTRING = ctypes.c_void_p
HRESULT = ctypes.HRESULT
PPVOID = ctypes.POINTER(ctypes.c_void_p)

IID_IToastNotificationManagerStatics = _GUID(0x50AC103F, 0xD235, 0x4598, (0xBB, 0xEF, 0x98, 0xFE, 0x4D, 0x1A, 0x3A, 0xD4))
IID_IToastNotificationFactory = _GUID(0x04124B20, 0x82C6, 0x4229, (0xB1, 0x09, 0xFD, 0x9E, 0xD4, 0x66, 0x2B, 0x53))
IID_IXmlDocument = _GUID(0xF7F3A506, 0x1E87, 0x42D6, (0xBC, 0xFB, 0xB8, 0xC8, 0x09, 0xFA, 0x54, 0x94))
IID_IXmlDocumentIO = _GUID(0x6CD0E74E, 0xEE65, 0x4489, (0x9E, 0xBF, 0xCA, 0x43, 0xE8, 0x7B, 0xA6, 0x37))
IID_IToastNotification2 = _GUID(0x9DFB9FD1, 0x143A, 0x490E, (0x90, 0xBF, 0xB9, 0xFB, 0xA7, 0x13, 0x2D, 0xE7))
IID_IShellLinkW = _GUID(0x000214F9, 0x0000, 0x0000, (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46))
IID_IPersistFile = _GUID(0x0000010B, 0x0000, 0x0000, (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46))
IID_IPropertyStore = _GUID(0x886D8EEB, 0x8CF2, 0x4446, (0x8D, 0x02, 0xCD, 0xBA, 0x1D, 0xBD, 0xCF, 0x99))
CLSID_ShellLink = _GUID(0x00021401, 0x0000, 0x0000, (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46))
PKEY_AppUserModel_ID = _PROPERTYKEY(
    _GUID(0x9F4C2855, 0x9F79, 0x4B39, (0xA8, 0xD0, 0xE1, 0xD4, 0x2D, 0xE1, 0xD5, 0xF3)),
    5,
)
VT_LPWSTR = 31
COINIT_MULTITHREADED = 0x0
CLSCTX_INPROC_SERVER = 0x1
STGM_READWRITE = 0x00000002
RO_INIT_MULTITHREADED = 1

RC_MANAGER = "Windows.UI.Notifications.ToastNotificationManager"
RC_TOAST = "Windows.UI.Notifications.ToastNotification"
RC_XML = "Windows.Data.Xml.Dom.XmlDocument"


def _combase():
    lib = ctypes.WinDLL("combase")
    lib.WindowsCreateString.argtypes = [wintypes.LPCWSTR, wintypes.UINT, ctypes.POINTER(HSTRING)]
    lib.WindowsCreateString.restype = HRESULT
    lib.WindowsDeleteString.argtypes = [HSTRING]
    lib.WindowsDeleteString.restype = HRESULT
    lib.RoInitialize.argtypes = [ctypes.c_uint]
    lib.RoInitialize.restype = HRESULT
    lib.RoGetActivationFactory.argtypes = [HSTRING, ctypes.POINTER(_GUID), PPVOID]
    lib.RoGetActivationFactory.restype = HRESULT
    lib.RoActivateInstance.argtypes = [HSTRING, PPVOID]
    lib.RoActivateInstance.restype = HRESULT
    return lib


def _hstring(text: str, combase) -> HSTRING:
    hs = HSTRING()
    hr = combase.WindowsCreateString(text, len(text), ctypes.byref(hs))
    if hr < 0:
        raise OSError(hr, f"WindowsCreateString 0x{hr & 0xFFFFFFFF:08X}")
    return hs


def _vtbl(obj: int) -> ctypes.POINTER(ctypes.c_void_p):
    ptr = ctypes.c_void_p(obj)
    vtbl_ptr = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p)).contents
    return ctypes.cast(vtbl_ptr, ctypes.POINTER(ctypes.c_void_p))


def _call(obj: int, index: int, restype, argtypes, *args):
    fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(_vtbl(obj)[index])
    return fn(obj, *args)


def _release(obj: int | None) -> None:
    if not obj:
        return
    _call(obj, 2, ctypes.c_ulong, [])


def _qi(obj: int, iid: _GUID) -> int:
    out = ctypes.c_void_p()
    hr = _call(obj, 0, HRESULT, [ctypes.POINTER(_GUID), PPVOID], ctypes.byref(iid), ctypes.byref(out))
    if hr < 0 or not out.value:
        raise OSError(hr, f"QueryInterface 0x{hr & 0xFFFFFFFF:08X}")
    return int(out.value)


def _ensure_runtime() -> None:
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    ole32.CoInitializeEx.restype = HRESULT
    hr = ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
    if hr < 0 and (hr & 0xFFFFFFFF) not in {0x80010106}:  # RPC_E_CHANGED_MODE
        # Already initialized with a different model is still usable.
        pass
    combase = _combase()
    hr = combase.RoInitialize(RO_INIT_MULTITHREADED)
    if hr < 0 and (hr & 0xFFFFFFFF) not in {0x80010106, 0x80000017}:  # changed mode / already init
        raise OSError(hr, f"RoInitialize 0x{hr & 0xFFFFFFFF:08X}")


def _register_aumid() -> None:
    from bob.win32_app import APP_ID, APP_NAME, branded_exe, icon_path

    try:
        import winreg
    except ImportError:
        return
    ico = icon_path()
    exe = branded_exe()
    icon_uri = ico.resolve().as_uri() if ico.is_file() else ""
    icon_res = f"{exe},0" if exe.is_file() else icon_uri
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\AppUserModelId\{APP_ID}")
    try:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        if icon_uri:
            winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, icon_uri)
        if icon_res:
            winreg.SetValueEx(key, "IconResource", 0, winreg.REG_SZ, icon_res)
    finally:
        winreg.CloseKey(key)


def _start_menu_lnk() -> str:
    appdata = os.environ.get("APPDATA") or ""
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Bob.lnk")


def _ensure_shortcut() -> None:
    """Desktop toasts need a Start Menu shortcut stamped with the AUMID."""
    from bob.win32_app import APP_ID, branded_exe, icon_path, project_root

    lnk = _start_menu_lnk()
    if os.path.isfile(lnk):
        return
    target = branded_exe()
    args = ""
    if not target.is_file():
        target = project_root() / ".venv" / "Scripts" / "pythonw.exe"
        args = "-m bob"
    if not target.is_file():
        return
    ico = icon_path()
    ole32 = ctypes.windll.ole32
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.POINTER(_GUID),
        PPVOID,
    ]
    ole32.CoCreateInstance.restype = HRESULT
    shell = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(
        ctypes.byref(CLSID_ShellLink),
        None,
        CLSCTX_INPROC_SERVER,
        ctypes.byref(IID_IShellLinkW),
        ctypes.byref(shell),
    )
    if hr < 0 or not shell.value:
        raise OSError(hr, f"CoCreateInstance ShellLink 0x{hr & 0xFFFFFFFF:08X}")
    obj = int(shell.value)
    try:
        _call(obj, 20, HRESULT, [wintypes.LPCWSTR], str(target))  # SetPath
        _call(obj, 9, HRESULT, [wintypes.LPCWSTR], str(project_root()))  # SetWorkingDirectory
        if args:
            _call(obj, 11, HRESULT, [wintypes.LPCWSTR], args)  # SetArguments
        if ico.is_file():
            _call(obj, 17, HRESULT, [wintypes.LPCWSTR, ctypes.c_int], str(ico), 0)  # SetIconLocation
        props = _qi(obj, IID_IPropertyStore)
        try:
            buf = ctypes.create_unicode_buffer(APP_ID)
            pv = _PROPVARIANT()
            pv.vt = VT_LPWSTR
            pv.pwszVal = ctypes.cast(buf, ctypes.c_void_p).value
            hr = _call(
                props,
                6,
                HRESULT,
                [ctypes.POINTER(_PROPERTYKEY), ctypes.POINTER(_PROPVARIANT)],
                ctypes.byref(PKEY_AppUserModel_ID),
                ctypes.byref(pv),
            )
            if hr < 0:
                raise OSError(hr, f"IPropertyStore.SetValue 0x{hr & 0xFFFFFFFF:08X}")
            hr = _call(props, 7, HRESULT, [])  # Commit
            if hr < 0:
                raise OSError(hr, f"IPropertyStore.Commit 0x{hr & 0xFFFFFFFF:08X}")
        finally:
            _release(props)
        persist = _qi(obj, IID_IPersistFile)
        try:
            os.makedirs(os.path.dirname(lnk), exist_ok=True)
            hr = _call(persist, 6, HRESULT, [wintypes.LPCWSTR, ctypes.c_int], lnk, True)  # Save
            if hr < 0:
                raise OSError(hr, f"IPersistFile.Save 0x{hr & 0xFFFFFFFF:08X}")
        finally:
            _release(persist)
    finally:
        _release(obj)


def _message_text_nodes(message: str) -> str:
    lines = [ln.strip() for ln in message.splitlines() if ln.strip()]
    if not lines:
        lines = [message.strip()]
    return "".join(f"<text>{escape(ln)}</text>" for ln in lines if ln)


def prefetch() -> None:
    """Create shortcut/AUMID early so the first toast can pop immediately."""
    if sys.platform != "win32":
        return
    try:
        _ensure_runtime()
        _register_aumid()
        _ensure_shortcut()
    except Exception:
        log.exception("Toast prefetch failed")


def _show_winrt(
    title: str,
    message: str,
    *,
    replace: bool,
    silent: bool = False,
    tag: str | None = None,
) -> None:
    from bob.win32_app import APP_ID, apply_process_app_id

    apply_process_app_id()
    _ensure_runtime()
    _register_aumid()
    try:
        _ensure_shortcut()
    except Exception:
        log.exception("Could not create Start Menu shortcut for toasts")

    combase = _combase()
    xml_text = (
        '<toast duration="long">'
        + ('<audio silent="true"/>' if silent else "")
        + "<visual><binding template=\"ToastGeneric\">"
        f"<text>{escape(title)}</text>"
        f"{_message_text_nodes(message)}"
        "</binding></visual></toast>"
    )

    hs_manager = hs_app = hs_toast = hs_xml_name = hs_xml = None
    manager = notifier = factory = inspectable = xml_doc = xml_io = toast = toast2 = None
    try:
        hs_manager = _hstring(RC_MANAGER, combase)
        factory_ptr = ctypes.c_void_p()
        hr = combase.RoGetActivationFactory(
            hs_manager, ctypes.byref(IID_IToastNotificationManagerStatics), ctypes.byref(factory_ptr)
        )
        if hr < 0 or not factory_ptr.value:
            raise OSError(hr, f"RoGetActivationFactory manager 0x{hr & 0xFFFFFFFF:08X}")
        manager = int(factory_ptr.value)

        hs_app = _hstring(APP_ID, combase)
        notifier_ptr = ctypes.c_void_p()
        hr = _call(
            manager,
            7,
            HRESULT,
            [HSTRING, PPVOID],
            hs_app,
            ctypes.byref(notifier_ptr),
        )
        if hr < 0 or not notifier_ptr.value:
            raise OSError(hr, f"CreateToastNotifierWithId 0x{hr & 0xFFFFFFFF:08X}")
        notifier = int(notifier_ptr.value)

        hs_toast = _hstring(RC_TOAST, combase)
        factory_ptr = ctypes.c_void_p()
        hr = combase.RoGetActivationFactory(
            hs_toast, ctypes.byref(IID_IToastNotificationFactory), ctypes.byref(factory_ptr)
        )
        if hr < 0 or not factory_ptr.value:
            raise OSError(hr, f"RoGetActivationFactory toast 0x{hr & 0xFFFFFFFF:08X}")
        factory = int(factory_ptr.value)

        hs_xml_name = _hstring(RC_XML, combase)
        inspectable_ptr = ctypes.c_void_p()
        hr = combase.RoActivateInstance(hs_xml_name, ctypes.byref(inspectable_ptr))
        if hr < 0 or not inspectable_ptr.value:
            raise OSError(hr, f"RoActivateInstance XmlDocument 0x{hr & 0xFFFFFFFF:08X}")
        inspectable = int(inspectable_ptr.value)
        xml_doc = _qi(inspectable, IID_IXmlDocument)
        xml_io = _qi(xml_doc, IID_IXmlDocumentIO)
        hs_xml = _hstring(xml_text, combase)
        hr = _call(xml_io, 6, HRESULT, [HSTRING], hs_xml)  # LoadXml
        if hr < 0:
            raise OSError(hr, f"LoadXml 0x{hr & 0xFFFFFFFF:08X}")

        toast_ptr = ctypes.c_void_p()
        hr = _call(factory, 6, HRESULT, [ctypes.c_void_p, PPVOID], xml_doc, ctypes.byref(toast_ptr))
        if hr < 0 or not toast_ptr.value:
            raise OSError(hr, f"CreateToastNotification 0x{hr & 0xFFFFFFFF:08X}")
        toast = int(toast_ptr.value)

        toast_tag = tag or ("bob-load" if replace else None)
        if toast_tag:
            try:
                toast2 = _qi(toast, IID_IToastNotification2)
                hs_tag = _hstring(toast_tag, combase)
                hs_group = _hstring("bob", combase)
                try:
                    _call(toast2, 6, HRESULT, [HSTRING], hs_tag)  # put_Tag
                    _call(toast2, 8, HRESULT, [HSTRING], hs_group)  # put_Group
                finally:
                    combase.WindowsDeleteString(hs_tag)
                    combase.WindowsDeleteString(hs_group)
            except OSError:
                log.debug("IToastNotification2 not available", exc_info=True)

        hr = _call(notifier, 6, HRESULT, [ctypes.c_void_p], toast)  # Show
        if hr < 0:
            raise OSError(hr, f"ToastNotifier.Show 0x{hr & 0xFFFFFFFF:08X}")
    finally:
        for obj in (toast2, toast, xml_io, xml_doc, inspectable, factory, notifier, manager):
            _release(obj)
        for hs in (hs_xml, hs_xml_name, hs_toast, hs_app, hs_manager):
            if hs:
                combase.WindowsDeleteString(hs)


def show(
    message: str,
    title: str = "BOB",
    *,
    replace: bool = True,
    silent: bool = False,
    tag: str | None = None,
) -> bool:
    """Show a Windows toast. Safe to call from any thread; never raises."""
    global _inited, _ok
    if sys.platform != "win32":
        return False
    text = (message or "").strip()
    if not text:
        return False
    heading = (title or "BOB").strip() or "BOB"
    try:
        _show_winrt(heading, text, replace=replace, silent=silent, tag=tag)
        _ok = True
        if not _inited:
            _inited = True
        log.info("toast: %s — %s", heading, text)
        return True
    except Exception:
        log.exception("Windows toast failed (%s: %s)", heading, text)
        _inited = True
        _ok = False
        return False
