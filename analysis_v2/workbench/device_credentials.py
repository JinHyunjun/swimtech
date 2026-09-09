"""Only this application's approved device grant; never browser credentials.

Windows DPAPI (current user, not LOCAL_MACHINE). No plaintext fallback.
https://learn.microsoft.com/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata
"""
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile


def crypt(data, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('Secure saved connections currently require Windows; use --memory-only elsewhere.')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    dll = ctypes.WinDLL('crypt32', use_last_error=True)
    function = dll.CryptUnprotectData if decrypt else dll.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError(ctypes.get_last_error())
    free = ctypes.WinDLL('kernel32', use_last_error=True).LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    try: return ctypes.string_at(output.data, output.size)
    finally: free(output.data)


class DeviceCredentials:
    def __init__(self, base, root=None):
        self.base = base
        self.root = Path(root or Path(os.getenv('LOCALAPPDATA', Path.home()))/'SwimMate'/'video-worker')
        self.path = self.root/(hashlib.sha256(base.encode()).hexdigest()[:20]+'.dpapi')

    def load(self):
        if not self.path.exists(): return None
        try:
            value = json.loads(crypt(self.path.read_bytes(), decrypt=True))
            if value['base'] != self.base: raise ValueError('origin')
            return value['device']
        except Exception as exc:
            raise RuntimeError('Saved PC connection cannot be opened. Use --forget-device and approve again.') from exc

    def save(self, device):
        encrypted = crypt(json.dumps({'base':self.base,'device':device}).encode())
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=self.root, suffix='.encrypted')
        try:
            with os.fdopen(fd, 'wb') as out: out.write(encrypted)
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp): os.unlink(temp)

    def forget(self):
        self.path.unlink(missing_ok=True)

    @contextmanager
    def single_instance(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix('.lock').open('a+b') as lock:
            lock.seek(0, 2)
            if lock.tell() == 0: lock.write(b'0'); lock.flush()
            lock.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError('The processor is already running for this service.') from exc
            try: yield
            finally:
                lock.seek(0)
                if os.name == 'nt': msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else: fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
