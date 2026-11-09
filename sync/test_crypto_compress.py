"""Komprimierte Verschluesselung: python -m unittest test_crypto_compress -v"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import crypto_utils  # noqa: E402


class CompressedEncryption(unittest.TestCase):
    def test_roundtrip_and_much_smaller(self):
        dek = crypto_utils.generate_dek()
        obj = {"weeks": {f"2026-{m:02d}-01": {"days": ["Zone-2-Lauf, ganz locker, 130-140 bpm"] * 40} for m in range(1, 13)}}
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        plain = crypto_utils.encrypt_json_bytes(dek, raw)
        packed = crypto_utils.encrypt_json_bytes(dek, raw, compress=True)
        self.assertEqual(crypto_utils.decrypt_json(dek, packed), obj)
        self.assertEqual(crypto_utils.decrypt_json(dek, plain), obj)          # alte, unkomprimierte Dateien bleiben lesbar
        self.assertLess(len(packed["ciphertext"]) * 5, len(plain["ciphertext"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
