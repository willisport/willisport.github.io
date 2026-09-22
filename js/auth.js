/* Basis · Login & Entschlüsselung für die gehostete (GitHub-Pages-)Version.
   Lokal ohne data/auth-config.json bleibt alles wie bisher, ohne Login. */

const AUTH_SESSION_KEY = "basisAuthSession_v2";
const GITHUB_REPO = "willisport/willisport.github.io";
const HOSTED_SYNC_WORKER_URL = "https://basis-sync-worker.willi-laurisch.workers.dev";
/* Datendateien direkt von GitHub (raw), nicht ueber die Pages-Seite - so
   sind Freischaltungen/Syncs sofort sichtbar, ohne auf einen kompletten
   Pages-Rebuild warten zu muessen (der kann mehrere Minuten dauern). */
const RAW_DATA_BASE = `https://raw.githubusercontent.com/${GITHUB_REPO}/main`;

let CURRENT_ROLE = "owner";
let CURRENT_USERNAME = "";
let IS_HOSTED = false;
let CURRENT_AUTH_CONFIG = null;
let CURRENT_DEK = null;

function b64ToBytes(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}
function bytesToB64(bytes) {
  let bin = "";
  bytes.forEach(b => { bin += String.fromCharCode(b); });
  return btoa(bin);
}

async function sha256Hex(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
}

async function deriveAesKey(password, saltB64, iterations) {
  const enc = new TextEncoder();
  const salt = b64ToBytes(saltB64);
  const keyMaterial = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
    keyMaterial, { name: "AES-GCM", length: 256 }, false, ["decrypt"]
  );
}

async function tryUnwrapDek(password, entry, iterations) {
  try {
    const key = await deriveAesKey(password, entry.salt, iterations);
    const iv = b64ToBytes(entry.iv);
    const wrapped = b64ToBytes(entry.wrappedKey);
    const dekBuf = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, wrapped);
    return new Uint8Array(dekBuf);
  } catch {
    return null;
  }
}

async function decryptDataFile(dekRawBytes, encFile) {
  const dekKey = await crypto.subtle.importKey("raw", dekRawBytes, "AES-GCM", false, ["decrypt"]);
  const iv = b64ToBytes(encFile.iv);
  const ct = b64ToBytes(encFile.ciphertext);
  const plainBuf = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, dekKey, ct);
  return JSON.parse(new TextDecoder().decode(plainBuf));
}

async function encryptJson(dekRawBytes, obj) {
  const dekKey = await crypto.subtle.importKey("raw", dekRawBytes, "AES-GCM", false, ["encrypt"]);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const plainBytes = new TextEncoder().encode(JSON.stringify(obj));
  const ctBuf = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, dekKey, plainBytes);
  return { iv: bytesToB64(iv), ciphertext: bytesToB64(new Uint8Array(ctBuf)) };
}

function saveSession(dekRawBytes, role, username, sessionVersion) {
  try {
    localStorage.setItem(AUTH_SESSION_KEY, JSON.stringify({
      dek: bytesToB64(dekRawBytes), role, username: username || "", sessionVersion: sessionVersion || 0,
    }));
  } catch { /* ignore */ }
}
function loadSession() {
  try { return JSON.parse(localStorage.getItem(AUTH_SESSION_KEY) || "null"); }
  catch { return null; }
}
function clearSession() {
  try { localStorage.removeItem(AUTH_SESSION_KEY); } catch { /* ignore */ }
}

function showSignupForm(overlay) {
  const card = overlay.querySelector(".login-card");
  card.innerHTML = `
    <div class="login-title">Login erstellen</div>
    <div class="login-sub">Wird als Anfrage an den Owner geschickt. Dein Passwort verlässt nie diesen Browser im Klartext.</div>
    <input type="text" id="signup-user" class="login-input" placeholder="Benutzername (z. B. max)" autofocus />
    <input type="password" id="signup-pw" class="login-input" placeholder="Passwort (dein eigenes, merken!)" style="margin-top:10px;" />
    <button id="signup-submit" class="login-submit-btn" style="margin-top:10px;">Anfrage senden</button>
    <div class="login-error" id="signup-error"></div>
    <div class="login-sub" id="signup-back" style="margin-top:14px; cursor:pointer; text-decoration:underline;">Zurück zum Login</div>`;

  card.querySelector("#signup-back").addEventListener("click", () => showLoginOverlay(CURRENT_AUTH_CONFIG, window.__basisLoginSuccess, overlay));

  card.querySelector("#signup-submit").addEventListener("click", async () => {
    const submitBtn = card.querySelector("#signup-submit");
    const username = card.querySelector("#signup-user").value.trim().toLowerCase();
    const password = card.querySelector("#signup-pw").value;
    const errorEl = card.querySelector("#signup-error");
    errorEl.style.color = "";
    if (!/^[a-z0-9_-]{2,24}$/.test(username)) {
      errorEl.textContent = "Benutzername: 2–24 Zeichen, nur a-z, 0-9, - und _.";
      return;
    }
    if (!password || password.length < 6) {
      errorEl.textContent = "Passwort braucht mindestens 6 Zeichen.";
      return;
    }
    submitBtn.disabled = true;
    errorEl.textContent = "Anfrage wird gesendet…";
    try {
      const credentialSecret = await sha256Hex(`${username}:${password}`);
      const res = await fetch(HOSTED_SYNC_WORKER_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "request-login", username, credential: credentialSecret }),
      });
      const result = await res.json();
      if (!result.ok) throw new Error(result.error || "Unbekannter Fehler");
      errorEl.style.color = "var(--teal)";
      errorEl.textContent = "Anfrage gesendet – der Owner schaltet dich frei, kein weiterer Schritt nötig.";
    } catch (err) {
      errorEl.textContent = `Fehler: ${err.message || err}`;
    } finally {
      submitBtn.disabled = false;
    }
  });
}

function showLoginOverlay(authConfig, onSuccess, existingOverlay) {
  window.__basisLoginSuccess = onSuccess;
  const overlay = existingOverlay || document.createElement("div");
  overlay.className = "login-overlay";
  overlay.innerHTML = `
    <div class="login-card">
        <div class="login-title">Willis Dashboard</div>
      <div class="login-sub">Passwort eingeben, um dein Trainings-Dashboard zu entschlüsseln.</div>
      <input type="text" id="login-user" class="login-input" placeholder="Benutzername (nur für persönlichen Login)" />
      <input type="password" id="login-pw" class="login-input" placeholder="Passwort" style="margin-top:10px;" autofocus />
      <button id="login-submit" class="login-submit-btn" style="margin-top:10px;">Entsperren</button>
      <div class="login-error" id="login-error"></div>
      <div class="login-sub" id="login-signup-link" style="margin-top:14px; cursor:pointer; text-decoration:underline;">Noch keinen Login? Login erstellen</div>
    </div>`;
  if (!existingOverlay) document.body.appendChild(overlay);

  const userInput = overlay.querySelector("#login-user");
  const pwInput = overlay.querySelector("#login-pw");
  const btn = overlay.querySelector("#login-submit");
  const errorEl = overlay.querySelector("#login-error");

  overlay.querySelector("#login-signup-link").addEventListener("click", () => showSignupForm(overlay));

  const attempt = async () => {
    const username = userInput.value.trim().toLowerCase();
    const password = pwInput.value;
    if (!password) return;
    btn.disabled = true;
    errorEl.textContent = "";
    const iterations = authConfig.kdf.iterations;

    let dek = null, role = null, sessionVersion = 0;

    if (username) {
      const entry = (authConfig.users || {})[username];
      if (entry) {
        const credentialSecret = await sha256Hex(`${username}:${password}`);
        dek = await tryUnwrapDek(credentialSecret, entry, iterations);
        role = entry.role || "viewer";
        sessionVersion = entry.sessionVersion || 0;
      }
    } else {
      dek = await tryUnwrapDek(password, authConfig.owner, iterations);
      role = "owner";
      if (!dek) {
        dek = await tryUnwrapDek(password, authConfig.viewer, iterations);
        role = "viewer";
      }
    }

    if (!dek) {
      errorEl.textContent = "Falsches Passwort oder unbekannter Benutzername.";
      btn.disabled = false;
      pwInput.select();
      return;
    }

    saveSession(dek, role, username, sessionVersion);
    overlay.remove();
    onSuccess(dek, role, username);
  };

  btn.addEventListener("click", attempt);
  pwInput.addEventListener("keydown", (e) => { if (e.key === "Enter") attempt(); });
}

function showSyncStatus(syncedAtIso) {
  const el = document.getElementById("sync-status");
  if (!el) return;
  let label = "Automatisch synchronisiert (alle 10 Min)";
  if (syncedAtIso) {
    const d = new Date(syncedAtIso);
    if (!Number.isNaN(d.getTime())) {
      const time = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
      const ageMin = Math.round((Date.now() - d.getTime()) / 60000);
      const ageTxt = ageMin < 1 ? "gerade eben" : ageMin < 60 ? `vor ${ageMin} min` : `vor ${Math.round(ageMin / 60)} h`;
      label = `⟳ Zuletzt synchronisiert ${time} Uhr (${ageTxt})`;
    }
  }
  el.textContent = label;
  el.hidden = false;
}

function setupLogoutControl() {
  const el = document.getElementById("role-chip");
  if (!el) return;
  el.hidden = false;
  const label = CURRENT_ROLE === "owner" ? "Owner" : (CURRENT_USERNAME || "Viewer");
  el.textContent = `${label} · abmelden`;
  el.addEventListener("click", () => {
    clearSession();
    location.reload();
  });
}

function setupHostedSyncButton(onData) {
  const btn = document.getElementById("hosted-sync-btn");
  const panel = document.getElementById("sync-panel");
  if (!btn) return;
  btn.hidden = false;

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.classList.add("is-syncing");
    if (panel) {
      panel.innerHTML = `<div class="title">Sync wird gestartet…</div>`;
      panel.hidden = false;
    }

    try {
      const res = await fetch(HOSTED_SYNC_WORKER_URL, { method: "POST" });
      const result = await res.json();
      if (!result.ok) throw new Error(result.error || "Unbekannter Fehler");

      if (panel) panel.innerHTML = `<div class="title">Sync gestartet</div><div>Läuft im Hintergrund, dauert ca. 1–2 Minuten…</div>`;

      const prevSyncedAt = (typeof APP_DATA !== "undefined" && APP_DATA) ? APP_DATA.syncedAt : undefined;
      const gotFreshData = await pollForFreshSync(prevSyncedAt);

      if (gotFreshData) {
        if (panel) panel.innerHTML = `<div class="title">Sync erfolgreich</div><div>Daten sind aktuell.</div>`;
        onData(gotFreshData);
        showSyncStatus(gotFreshData.syncedAt);
      } else if (panel) {
        panel.innerHTML = `<div class="title">Sync läuft noch</div><div>Dauert diesmal ungewöhnlich lang – lad die Seite in ein paar Minuten neu.</div>`;
      }
    } catch (err) {
      if (panel) {
        panel.innerHTML = `<div class="title">Fehler beim Sync</div><div>${escapeHtml(String(err.message || err))}</div>`;
        panel.hidden = false;
      }
    } finally {
      btn.disabled = false;
      btn.classList.remove("is-syncing");
      setTimeout(() => { if (panel) panel.hidden = true; }, 12000);
    }
  });
}

async function fetchFileViaGithubApi(path) {
  const res = await fetch(`https://api.github.com/repos/${GITHUB_REPO}/contents/${path}`, {
    headers: { Accept: "application/vnd.github.raw+json" },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`GitHub API antwortete mit ${res.status}`);
  return res.json();
}

async function pollForFreshSync(prevSyncedAt, maxWaitMs = 150000, intervalMs = 6000) {
  const start = Date.now();
  while (Date.now() - start < maxWaitMs) {
    await new Promise(r => setTimeout(r, intervalMs));
    try {
      const encFile = await fetchFileViaGithubApi("data/training-data.enc.json");
      const data = await decryptDataFile(CURRENT_DEK, encFile);
      if (data.syncedAt && data.syncedAt !== prevSyncedAt) return data;
    } catch { /* naechster Versuch */ }
  }
  return null;
}

function setupLoginsNavItem() {
  document.querySelectorAll('[data-tab="logins"]').forEach(el => { el.hidden = CURRENT_ROLE !== "owner"; });
  document.querySelectorAll('[data-tab="airis"]').forEach(el => { el.hidden = CURRENT_ROLE !== "owner"; });
}

/* Airis: separater, nur fuer den Owner sichtbarer Bereich (Mail-/Kalenderuebersicht).
   Eigene verschluesselte Datei statt in training-data.enc.json, damit ein Viewer-Zugriff
   (auch versehentlich) diese Datei nie anfragt, geschweige denn entschluesseln koennte -
   Verteidigung in der Tiefe zusaetzlich zum reinen UI-Ausblenden oben. */
async function loadAirisStatus() {
  if (CURRENT_ROLE !== "owner" || !CURRENT_DEK) return;
  try {
    const encFile = await fetch(`${RAW_DATA_BASE}/data/airis-status.enc.json`, { cache: "no-store" }).then(r => r.json());
    const data = await decryptDataFile(CURRENT_DEK, encFile);
    if (typeof renderAiris === "function") renderAiris(data);
  } catch {
    // Datei existiert evtl. noch nicht (erster Sync steht noch aus) oder Abruf fehlgeschlagen -
    // Tab zeigt dann seinen eigenen "noch keine Daten"-Zustand.
  }
}

/**
 * Boot-Einstiegspunkt: prueft, ob eine verschluesselte gehostete Version
 * vorliegt (data/auth-config.json vorhanden). Falls nein: normales lokales
 * Verhalten wie bisher (training-data.json direkt laden, kein Login).
 * Falls ja: Login-Screen bzw. gespeicherte Session, dann training-data.enc.json
 * entschluesseln.
 */
async function bootWithAuth(onData) {
  let authConfig = null;
  try {
    const probe = await fetch("data/auth-config.json", { cache: "no-store" });
    if (probe.ok) {
      try {
        const fresh = await fetch(`${RAW_DATA_BASE}/data/auth-config.json`, { cache: "no-store" });
        authConfig = fresh.ok ? await fresh.json() : await probe.json();
      } catch {
        authConfig = await probe.json();
      }
    }
  } catch { /* kein Hosted-Modus */ }

  if (!authConfig) {
    IS_HOSTED = false;
    CURRENT_ROLE = "owner";
    fetch("data/training-data.json")
      .then(r => r.json())
      .then(data => { onData(data); setupLoginsNavItem(); })
      .catch(err => {
        document.getElementById("tab-heute").innerHTML =
          `<div class="card accent-amber"><b>Konnte Trainingsdaten nicht laden.</b><br>${err}<br><br>Läuft die Seite über einen lokalen Server (nicht direkt als Datei geöffnet)?</div>`;
      });
    return;
  }

  IS_HOSTED = true;
  CURRENT_AUTH_CONFIG = authConfig;
  document.body.classList.add("is-hosted");

  const loadEncryptedAndRender = async (dekRawBytes, role, username) => {
    // Bittet den Browser, die gespeicherte Anmeldung nicht bei Speicherknappheit/Inaktivitaet zu loeschen.
    try { if (navigator.storage && navigator.storage.persist) navigator.storage.persist(); } catch { /* ignore */ }
    CURRENT_ROLE = role;
    CURRENT_USERNAME = username || "";
    CURRENT_DEK = dekRawBytes;
    document.body.classList.toggle("is-viewer", role === "viewer");
    try {
      const encFile = await fetch(`${RAW_DATA_BASE}/data/training-data.enc.json`, { cache: "no-store" }).then(r => r.json());
      const data = await decryptDataFile(dekRawBytes, encFile);
      await initOverridesFromServer();
      onData(data);
      setupLogoutControl();
      setupHostedSyncButton(onData);
      setupLoginsNavItem();
      loadAirisStatus();
      showSyncStatus(data.syncedAt);
    } catch (err) {
      document.getElementById("tab-heute").innerHTML =
        `<div class="card accent-amber"><b>Konnte Daten nicht entschlüsseln.</b><br>${err}</div>`;
    }
  };

  const session = loadSession();
  if (session && session.dek) {
    if (session.username) {
      const entry = (authConfig.users || {})[session.username];
      const stillValid = entry && (entry.sessionVersion || 0) === (session.sessionVersion || 0);
      if (!stillValid) clearSession();
    }
  }
  const validSession = loadSession();
  if (validSession && validSession.dek) {
    await loadEncryptedAndRender(b64ToBytes(validSession.dek), validSession.role, validSession.username);
    return;
  }

  showLoginOverlay(authConfig, loadEncryptedAndRender);
}
