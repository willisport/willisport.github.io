"""Schickt eine verschluesselte Datei aus data/outbox per Telegram (sendDocument).

Aufruf: python send_file.py <pfad zu *.enc.json> [Beschriftung]
Die Datei ist JSON {name, iv, ciphertext}; Klartext = JSON {name, b64}.
"""
import base64, json, os, sys
import requests
import crypto_utils


def main():
    path = sys.argv[1]
    caption = sys.argv[2] if len(sys.argv) > 2 else ""
    key = crypto_utils.unb64(os.environ["DATA_ENCRYPTION_KEY"])
    with open(path, encoding="utf-8") as f:
        enc = json.load(f)
    payload = crypto_utils.decrypt_json(key, enc)
    data = base64.b64decode(payload["b64"])
    r = requests.post(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendDocument",
        data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "caption": caption},
        files={"document": (payload["name"], data, "application/pdf")},
        timeout=120,
    )
    print("Telegram:", r.status_code, r.text[:200])
    r.raise_for_status()


if __name__ == "__main__":
    main()
