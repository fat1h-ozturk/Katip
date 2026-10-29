"""Only operating-system credential stores are accepted, never plaintext backends."""

import hashlib


class SecretStore:
    def __init__(self, config_path):
        digest = hashlib.sha256(str(config_path.resolve()).encode()).hexdigest()[:24]
        self.service = f"katip:{digest}"

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
            return self._backend().get_password(self.service, reference)
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
            if backend.get_password(self.service, reference) is not None:
                backend.delete_password(self.service, reference)
            return True
        except Exception:
            return False
