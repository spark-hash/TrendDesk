"""Protect the local API credential with Windows DPAPI under the current user."""
import base64
import ctypes
from ctypes import wintypes


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.c_void_p)]


def _transform(value: bytes, encrypt: bool) -> bytes:
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    free = kernel.LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    transform = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    description = wintypes.LPCWSTR if encrypt else ctypes.POINTER(wintypes.LPWSTR)
    transform.argtypes = [ctypes.POINTER(Blob), description, ctypes.POINTER(Blob),
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    transform.restype = wintypes.BOOL
    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.addressof(buffer))
    result = Blob()
    try:
        # CRYPTPROTECT_UI_FORBIDDEN only. Machine-wide decryption is not enabled.
        if not transform(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
            raise OSError('Windows DPAPI 操作失败')
        return ctypes.string_at(result.data, result.size)
    finally:
        ctypes.memset(ctypes.addressof(buffer), 0, len(buffer))
        if result.data:
            ctypes.memset(result.data, 0, result.size)
            free(result.data)


def protect(key: str) -> str:
    return base64.b64encode(_transform(key.encode('ascii'), True)).decode('ascii')


def unprotect(encoded: str) -> str:
    return _transform(base64.b64decode(encoded, validate=True), False).decode('ascii')
