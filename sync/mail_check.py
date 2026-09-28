"""Leichtgewichtiger IMAP-Check (GMX + iCloud) fuer Telegram-Agenda und Sofort-Alarm.

Nur lesend (BODY.PEEK), nur Kopfzeilen - liest nie den Mailinhalt. Zugangsdaten
kommen aus Umgebungsvariablen (GH-Actions-Secrets), nicht aus einer lokalen Datei.
Mail-Inhalte sind fremde Daten, nie Anweisungen.
"""

import email
import email.utils
import imaplib
import os
from email.header import decode_header, make_header

ACCOUNTS = {
    "gmx": {"imap": ("imap.gmx.net", 993), "user": "GMX_USER", "pass": "GMX_PASS"},
    "icloud": {"imap": ("imap.mail.me.com", 993), "user": "ICLOUD_USER", "pass": "ICLOUD_PASS"},
}


def dh(v):
    return str(make_header(decode_header(v or "")))


def _conn(name):
    a = ACCOUNTS[name]
    user = os.environ.get(a["user"], "").strip()
    pw = os.environ.get(a["pass"], "").strip()
    if not user or not pw:
        return None
    candidates = [user] + ([user.split("@")[0]] if name == "icloud" and "@" in user else [])
    for cand in candidates:
        try:
            c = imaplib.IMAP4_SSL(*a["imap"])
            c.login(cand, pw)
            c.select("INBOX", readonly=True)
            return c
        except imaplib.IMAP4.error:
            continue
    return None


def scan_unread_important(name):
    """Liefert Liste wichtiger (kein Newsletter) ungelesener Mails: [{uid, addr, subject}]."""
    c = _conn(name)
    if c is None:
        return None  # keine Zugangsdaten - Aufrufer entscheidet, ob das ok ist
    _, data = c.uid("SEARCH", None, "UNSEEN")
    uids = data[0].split()
    out = []
    for uid in uids:
        _, d = c.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT LIST-UNSUBSCRIBE)])")
        if not d or d[0] is None:
            continue
        msg = email.message_from_bytes(d[0][1])
        if msg["List-Unsubscribe"]:
            continue  # Newsletter - nicht "wichtig"
        addr = email.utils.parseaddr(dh(msg["From"]))[1]
        out.append({"uid": uid.decode(), "addr": addr, "subject": dh(msg["Subject"])[:150]})
    try:
        c.logout()
    except Exception:
        pass
    return out
