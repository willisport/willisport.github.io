"""Sofort-Alarm per Telegram bei neuer wichtiger Mail (kein Newsletter).

Merkt sich per verschluesseltem State (data/mail-alert-state.enc.json), welche
UIDs schon gemeldet wurden, damit nichts doppelt kommt. Laeuft alle 15 Min in
GitHub Actions.
"""

import base64
import json
import os
from pathlib import Path

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import mail_check

ROOT = Path(__file__).parent.parent
STATE_PATH = ROOT / "data" / "mail-alert-state.enc.json"
MAX_KEEP = 500  # verhindert unbegrenztes Wachstum


def _dek():
    b = os.environ.get("DATA_ENCRYPTION_KEY")
    return base64.b64decode(b) if b else None


def load_notified():
    dek = _dek()
    if not dek or not STATE_PATH.exists():
        return set()
    try:
        obj = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        plain = AESGCM(dek).decrypt(base64.b64decode(obj["iv"]), base64.b64decode(obj["ciphertext"]), None)
        return set(json.loads(plain))
    except Exception:
        return set()


def save_notified(notified):
    dek = _dek()
    if not dek:
        return
    keys = list(notified)[-MAX_KEEP:]
    iv = os.urandom(12)
    ct = AESGCM(dek).encrypt(iv, json.dumps(keys).encode("utf-8"), None)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"iv": base64.b64encode(iv).decode(), "ciphertext": base64.b64encode(ct).decode()}),
        encoding="utf-8",
    )


def send_telegram(text):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text},
        timeout=15,
    )
    resp.raise_for_status()


def main():
    notified = load_notified()
    new_count = 0
    for account, label in (("gmx", "GMX"), ("icloud", "iCloud")):
        try:
            rows = mail_check.scan_unread_important(account)
        except Exception as e:
            print(f"[warn] {account} nicht erreichbar: {e}")
            continue
        if rows is None:
            print(f"[info] keine Zugangsdaten fuer {account} - ausgelassen")
            continue
        for r in rows:
            key = f"{account}:{r['uid']}"
            if key in notified:
                continue
            send_telegram(f"📬 Neue wichtige Mail ({label})\nVon: {r['addr']}\nBetreff: {r['subject']}")
            notified.add(key)
            new_count += 1

    if new_count:
        save_notified(notified)
    print(f"fertig: {new_count} neue Alarme gesendet")


if __name__ == "__main__":
    main()
