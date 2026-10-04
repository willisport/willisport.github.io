"""
AES-256-GCM Verschluesselung, kompatibel mit der Web Crypto API im Browser
(gleiche Primitive: PBKDF2-HMAC-SHA256 zur Schluesselableitung, AES-GCM mit
96-bit IV). Wird genutzt, um die synchronisierten Trainingsdaten oeffentlich
(z. B. auf GitHub Pages) ablegen zu koennen, ohne dass sie im Klartext lesbar
sind - nur wer eines der beiden Passwoerter (Owner/Viewer) kennt, kann sie im
Browser entschluesseln.
"""

import base64
import gzip
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

PBKDF2_ITERATIONS = 210_000


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(s: str) -> bytes:
    return base64.b64decode(s)


def derive_key(password: str, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(password.encode("utf-8"))


def generate_dek() -> bytes:
    return os.urandom(32)


def wrap_key(dek: bytes, password: str) -> dict:
    """Verpackt den Data Encryption Key mit einem passwortabgeleiteten Schluessel."""
    salt = os.urandom(16)
    iv = os.urandom(12)
    kek = derive_key(password, salt)
    wrapped = AESGCM(kek).encrypt(iv, dek, None)
    return {"salt": b64(salt), "iv": b64(iv), "wrappedKey": b64(wrapped)}


def encrypt_json_bytes(dek: bytes, plaintext_bytes: bytes) -> dict:
    iv = os.urandom(12)
    ciphertext = AESGCM(dek).encrypt(iv, plaintext_bytes, None)
    return {"iv": b64(iv), "ciphertext": b64(ciphertext)}


def decrypt_json(dek: bytes, enc: dict):
    """Gegenstueck zu encrypt_json_bytes; entpackt gzip-komprimierte Nutzlast
    (der Browser komprimiert groessere Overrides, um das Workflow-Limit von
    65.535 Zeichen einzuhalten)."""
    plain = AESGCM(dek).decrypt(unb64(enc["iv"]), unb64(enc["ciphertext"]), None)
    if plain[:2] == b"\x1f\x8b":
        plain = gzip.decompress(plain)
    return json.loads(plain.decode("utf-8"))
