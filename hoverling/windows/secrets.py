"""Store provider credentials protected by the current Windows user's DPAPI key."""
import base64
import ctypes as c
from ctypes import wintypes as w

from ..translate import Settings

SECRET_KEYS = ("api_key", "youdao_app_secret", "deepl_api_key", "google_cloud_key")
PREFIX = "dpapi:"


class Blob(c.Structure):
    _fields_ = [("size", w.DWORD), ("data", c.c_void_p)]


crypt = c.WinDLL("crypt32", use_last_error=True)
for func in (crypt.CryptProtectData, crypt.CryptUnprotectData):
    func.argtypes = [c.POINTER(Blob), c.c_void_p, c.POINTER(Blob), c.c_void_p, c.c_void_p, w.DWORD, c.POINTER(Blob)]
    func.restype = w.BOOL
local_free = c.windll.kernel32.LocalFree
local_free.argtypes = [c.c_void_p]
local_free.restype = c.c_void_p


def transform(data, encrypt):
    buf = c.create_string_buffer(data)
    source = Blob(len(data), c.cast(buf, c.c_void_p))
    out = Blob()
    func = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    if not func(c.byref(source), None, None, None, None, 1, c.byref(out)):
        raise c.WinError(c.get_last_error())
    try:
        return c.string_at(out.data, out.size)
    finally:
        local_free(out.data)


class WindowsSettings(Settings):
    def __init__(self, path):
        super().__init__(path)
        for key in SECRET_KEYS:
            value = self.values[key]
            if value.startswith(PREFIX):
                try:
                    self.values[key] = transform(base64.b64decode(value[len(PREFIX):], validate=True), False).decode()
                except (ValueError, OSError):
                    self.values[key] = ""

    def save(self, values):
        plain = {**self.values, **values}
        protected = dict(values)
        for key in SECRET_KEYS:
            value = plain[key]
            protected[key] = PREFIX + base64.b64encode(transform(value.encode(), True)).decode() if value else ""
        super().save(protected)
        self.values.update({key: plain[key] for key in SECRET_KEYS})
