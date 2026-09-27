"""Gewicht aus Apple Health ueber die eigene health-weight-bridge (Cloudflare Worker).

Ein iOS-Kurzbefehl schickt einmal taeglich automatisch das aktuelle Gewicht aus
Apple Health an den Worker. Das ersetzt den direkten Renpho-Login, der sonst die
Renpho-App auf dem Handy ausloggt (siehe renpho_source.py)."""

import os

import requests


def fetch_latest_weight() -> dict | None:
    """Liefert {"date": "YYYY-MM-DD", "weightKg": float} oder None, wenn (noch)
    kein Wert hinterlegt ist."""
    url = os.environ.get("HEALTH_BRIDGE_URL")
    token = os.environ.get("HEALTH_BRIDGE_TOKEN")
    if not url or not token:
        return None

    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    return {"date": data["date"], "weightKg": data["weightKg"]}
