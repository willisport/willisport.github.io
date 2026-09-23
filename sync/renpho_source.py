"""Renpho-Waage: inoffizielle Cloud-API ueber das renpho-api Paket."""

import base64
import json
import os
from datetime import datetime
from pathlib import Path

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from renpho import RenphoClient
from renpho.client import RenphoAPIError

# Ein neuer Login macht die Renpho-App auf dem Handy ungueltig (man muss sich dort neu
# anmelden). Deshalb die Sitzung verschluesselt zwischenspeichern und nur bei Ablauf neu einloggen.
SESSION_PATH = Path(__file__).parent / ".renpho_session.enc.json"


def _dek():
    b = os.environ.get("DATA_ENCRYPTION_KEY")
    return base64.b64decode(b) if b else None


def _load_session():
    dek = _dek()
    if not dek or not SESSION_PATH.exists():
        return None
    try:
        obj = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
        plain = AESGCM(dek).decrypt(base64.b64decode(obj["iv"]), base64.b64decode(obj["ciphertext"]), None)
        s = json.loads(plain)
        return s if s.get("token") and s.get("user_id") else None
    except Exception:
        return None


def _save_session(client):
    dek = _dek()
    if not dek or not client.token:
        return
    iv = os.urandom(12)
    ct = AESGCM(dek).encrypt(iv, json.dumps({"token": client.token, "user_id": client.user_id}).encode(), None)
    SESSION_PATH.write_text(json.dumps({"iv": base64.b64encode(iv).decode(), "ciphertext": base64.b64encode(ct).decode()}), encoding="utf-8")


def _fetch_raw(client) -> list:
    raw = client.get_all_measurements() or []
    if not raw:
        # get_all_measurements() liefert bei manchen Konten nichts zurueck -
        # dann ueber die Geraeteliste direkt nachfragen (laut renpho-api README).
        device_info = client.get_device_info()
        scales = (device_info or {}).get("scale") or []
        for table in scales:
            table_name, user_id, count = table.get("tableName"), client.user_id, table.get("count")
            measurements = client.get_body_composition_measurements(table_name=table_name, user_id=user_id)
            if not measurements:
                measurements = client.get_measurements(table_name=table_name, user_id=user_id, total_count=count)
            raw.extend(measurements or [])
    return raw


def fetch_weight_history() -> list:
    """Liefert [{date, weightKg}] sortiert aufsteigend, ein Eintrag pro Tag
    (letzte Messung des Tages, meist die Morgen-Wiegung)."""
    email = os.environ.get("RENPHO_EMAIL")
    password = os.environ.get("RENPHO_PASSWORD")
    if not email or not password:
        raise RuntimeError("RENPHO_EMAIL/RENPHO_PASSWORD fehlen in sync/.env.")

    client = RenphoClient(email, password)
    raw = []
    session = _load_session()
    if session:
        client.token, client.user_id = session["token"], session["user_id"]
        try:
            raw = _fetch_raw(client)
        except (RenphoAPIError, requests.RequestException):
            raw = []
    if not raw:
        client.login()
        _save_session(client)
        raw = _fetch_raw(client)

    by_day = {}
    for m in raw:
        weight = m.get("weight")
        local_created = m.get("localCreatedAt")  # z.B. "2026-08-31 21:26:44", schon in Lokalzeit
        if weight is None:
            continue
        if local_created:
            day = str(local_created)[:10]
        else:
            ts = m.get("timeStamp")
            if ts is None:
                continue
            day = datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
        # letzte Messung des Tages gewinnt (Liste ist typischerweise neueste zuerst)
        if day not in by_day:
            by_day[day] = float(weight)

    return [{"date": d, "weightKg": round(w, 1)} for d, w in sorted(by_day.items())]
