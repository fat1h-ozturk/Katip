"""Only operating-system credential stores are accepted, never plaintext backends."""

import hashlib

from ..runtime import app_id


class SecretStore:
    def __init__(self, config_path):
        # References are random UUIDs, so one stable service per profile cannot collide and
        # survives a relocated/symlinked home or redirected APPDATA.
        self.service = f"katip:{app_id()}"
        digest = hashlib.sha256(str(config_path.resolve()).encode()).hexdigest()[:24]
        # Candidate builds stored entries under a path-derived name; read and purge them too.
        self.legacy_service = f"katip:{digest}"

    def _backend(self):
        import keyring
        backend = keyring.get_keyring()
        allowed = ("keyring.backends.SecretService", "keyring.backends.Windows", "keyring.backends.macOS")
        candidates = getattr(backend, "backends", [backend])
        for candidate in candidates:
            if type(candidate).__module__ in allowed:
                return candidate
        raise RuntimeError("İşletim sistemi anahtar kasası kullanılamıyor; önceki anahtar korundu.")

    def get(self, reference):
        try:
            backend = self._backend()
            value = backend.get_password(self.service, reference)
            if value is None:
                value = backend.get_password(self.legacy_service, reference)
            return value
        except Exception:
            raise RuntimeError("Anahtar kasası okunamadı; önceki anahtar kaydı korundu.") from None

    def put(self, reference, value):
        try:
            backend = self._backend()
            backend.set_password(self.service, reference, value)
            if backend.get_password(self.service, reference) != value:
                raise ValueError("Credential verification failed")
        except Exception:
            raise RuntimeError("Anahtar kasasına kaydedilemedi; önceki ayarlar korundu.") from None

    def delete(self, reference):
        try:
            backend = self._backend()
            for service in (self.service, self.legacy_service):
                if backend.get_password(service, reference) is not None:
                    backend.delete_password(service, reference)
            return True
        except Exception:
            return False
