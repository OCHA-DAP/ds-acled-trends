"""Build the password-protected GitHub Pages download site.

Downloads the CSVs from blob, encrypts each one client-side-compatibly
(PBKDF2-SHA256 -> AES-256-GCM) using SITE_PASSWORD, and writes a static site to
docs/ where users decrypt and download in-browser with the same password. The
raw CSVs are never published — only ciphertext.
"""

import base64
import io
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from src.constants import (
    ALL_BASENAME,
    LATEST_BASENAME,
    PROCESSED_PREFIX,
)
from src.scraper import _write_container_client, list_dated_blobs

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

PBKDF2_ITERATIONS = 200_000
DOCS_DIR = Path("docs")
DATA_DIR = DOCS_DIR / "data"

# Fixed (non-secret) PBKDF2 salt. Keeping it stable across rebuilds means a
# browser's cached index.html always matches the freshly re-encrypted files —
# decryption only needs salt + password, and each file carries its own random
# IV. A per-site constant salt still defeats cross-site precomputation.
SALT = base64.b64decode("84WlFDHXSJrWqlF6BnMTRQ==")


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode("utf-8"))


def _encrypt(key: bytes, plaintext: bytes) -> bytes:
    """Return iv(12) || ciphertext+tag, matching WebCrypto AES-GCM."""
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, plaintext, None)
    return iv + ct


def _collect_csvs() -> list[dict]:
    """Download all published CSVs from blob. Returns ordered metadata dicts."""
    cc = _write_container_client()
    entries: list[dict] = []

    def _add(basename: str, label: str, category: str):
        blob_name = f"{PROCESSED_PREFIX}/{basename}"
        try:
            data = cc.get_blob_client(blob_name).download_blob().readall()
        except Exception as e:  # noqa: BLE001 - skip files not present yet
            logger.warning("Skipping %s (%s)", blob_name, e)
            return
        df = pd.read_csv(io.BytesIO(data))
        entries.append(
            {
                "basename": basename,
                "label": label,
                "category": category,
                "data": data,
                "rows": len(df),
            }
        )

    _add(ALL_BASENAME, "All periods (cumulative)", "all")
    _add(LATEST_BASENAME, "Latest measured period", "latest")
    for name in sorted(list_dated_blobs(), reverse=True):
        basename = name.rsplit("/", 1)[-1]
        period_end = basename.removesuffix(".csv").rsplit("_", 1)[-1]
        _add(basename, f"Measured period ending {period_end}", "dated")
    return entries


def _build_meta(entries: list[dict]) -> dict:
    dated = [e for e in entries if e["category"] == "dated"]
    latest_period = None
    if dated:
        latest_period = (
            dated[0]["basename"].removesuffix(".csv").rsplit("_", 1)[-1]
        )
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "latest_period": latest_period,
        "n_periods": len(dated),
    }


def main() -> None:
    password = os.environ.get("SITE_PASSWORD")
    if not password:
        raise SystemExit("SITE_PASSWORD is not set — refusing to build site.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    salt = SALT
    key = _derive_key(password, salt)

    entries = _collect_csvs()
    if not entries:
        raise SystemExit("No CSVs found in blob — nothing to publish.")

    files_manifest = []
    for e in entries:
        enc = _encrypt(key, e["data"])
        enc_name = f"{e['basename']}.enc"
        (DATA_DIR / enc_name).write_bytes(enc)
        files_manifest.append(
            {
                "name": e["basename"],
                "enc": f"data/{enc_name}",
                "label": e["label"],
                "category": e["category"],
                "bytes": len(e["data"]),
                "rows": e["rows"],
            }
        )
        logger.info("Encrypted %s (%d bytes -> %d)", e["basename"], len(e["data"]), len(enc))

    meta = _build_meta(entries)
    config = {
        "salt": base64.b64encode(salt).decode(),
        "iterations": PBKDF2_ITERATIONS,
        "files": files_manifest,
        "meta": meta,
    }

    html = _render_html(config)
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")
    (DOCS_DIR / ".nojekyll").write_text("")
    logger.info("Wrote site to %s (%d files)", DOCS_DIR, len(files_manifest))


def _render_html(config: dict) -> str:
    config_json = json.dumps(config)
    return _HTML_TEMPLATE.replace("__CONFIG_JSON__", config_json)


_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex, nofollow" />
<title>ACLED Trends — Data Downloads</title>
<style>
  :root {
    --navy: #1b2a4a; --navy-soft: #2a3f63; --amber: #f4a81d;
    --ink: #1d2430; --muted: #6b7585; --line: #e4e8ef; --bg: #f5f7fa;
    --ok: #1f8a4c; --err: #c0392b;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: var(--ink); background: var(--bg); line-height: 1.5;
  }
  header {
    background: var(--navy); color: #fff; padding: 28px 24px;
  }
  .wrap { max-width: 860px; margin: 0 auto; padding: 0 20px; }
  header .wrap { padding: 0; }
  h1 { margin: 0 0 6px; font-size: 1.5rem; letter-spacing: .2px; }
  header p { margin: 0; color: #c7d0e0; font-size: .95rem; }
  main { padding: 32px 0 64px; }
  .card {
    background: #fff; border: 1px solid var(--line); border-radius: 12px;
    padding: 22px; margin: 0 auto 22px;
  }
  .lock h2 { margin: 0 0 4px; font-size: 1.1rem; }
  .lock p { margin: 0 0 16px; color: var(--muted); font-size: .9rem; }
  .row { display: flex; gap: 10px; flex-wrap: wrap; }
  input[type=password] {
    flex: 1 1 220px; min-width: 0; padding: 11px 13px; font-size: 1rem;
    border: 1px solid var(--line); border-radius: 8px;
  }
  input[type=password]:focus { outline: 2px solid var(--amber); border-color: var(--amber); }
  button {
    cursor: pointer; border: none; border-radius: 8px; font-size: .95rem;
    font-weight: 600; padding: 11px 18px; background: var(--navy); color: #fff;
  }
  button:hover { background: var(--navy-soft); }
  button.ghost {
    background: #fff; color: var(--navy); border: 1px solid var(--line);
    padding: 8px 14px; font-size: .85rem;
  }
  button.ghost:hover { border-color: var(--navy); background: #f8fafc; }
  button:disabled { opacity: .5; cursor: not-allowed; }
  .msg { margin-top: 12px; font-size: .9rem; min-height: 1.2em; }
  .msg.err { color: var(--err); }
  .msg.ok { color: var(--ok); }
  #files { display: none; }
  .meta { color: var(--muted); font-size: .85rem; margin: 0 0 18px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 11px 8px; border-bottom: 1px solid var(--line); font-size: .92rem; }
  th { color: var(--muted); font-weight: 600; font-size: .78rem; text-transform: uppercase; letter-spacing: .04em; }
  td.num { text-align: right; color: var(--muted); white-space: nowrap; }
  tr.group-all td, tr.group-latest td { font-weight: 600; }
  .pill { display: inline-block; font-size: .68rem; text-transform: uppercase; letter-spacing: .04em;
    padding: 2px 7px; border-radius: 999px; background: #eef1f6; color: var(--muted); margin-left: 8px; }
  .pill.amber { background: #fdf0d5; color: #9a6b00; }
  footer { color: var(--muted); font-size: .8rem; text-align: center; padding: 0 0 40px; }
  footer a { color: var(--muted); }
  code { background: #eef1f6; padding: 1px 5px; border-radius: 4px; font-size: .85em; }
</style>
</head>
<body>
<header>
  <div class="wrap">
    <h1>ACLED Trends — Organized Violence</h1>
    <p>Per-country event counts for each measured 4-week period. Password-protected downloads.</p>
  </div>
</header>
<main class="wrap">
  <div class="card lock" id="lock">
    <h2>Enter password to unlock downloads</h2>
    <p>Files are end-to-end encrypted; the password decrypts them in your browser. Ask the data owner for access.</p>
    <form class="row" id="form" autocomplete="off">
      <input type="password" id="pw" placeholder="Password" aria-label="Password" autofocus />
      <button type="submit" id="unlock">Unlock</button>
    </form>
    <div class="msg" id="msg" role="status"></div>
  </div>

  <div class="card" id="files">
    <p class="meta" id="meta"></p>
    <table>
      <thead><tr><th>File</th><th class="num">Rows</th><th class="num">Size</th><th class="num"></th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </div>

  <footer>
    Maintained by the OCHA Centre for Humanitarian Data (CHD) &middot;
    <a href="https://github.com/OCHA-DAP/ds-acled-trends" rel="noopener">source on GitHub</a><br>
    Data &copy; <a href="https://acleddata.com" rel="noopener">ACLED</a>, sourced from the
    <a href="https://acleddata.com/platform/trends" rel="noopener">Trends platform</a>.
    Subject to ACLED's terms of use and attribution policy.
  </footer>
</main>

<script>
const CONFIG = __CONFIG_JSON__;
const b64ToBytes = (b64) => Uint8Array.from(atob(b64), c => c.charCodeAt(0));
const fmtBytes = (n) => n < 1024 ? n + " B" : n < 1048576 ? (n/1024).toFixed(1) + " KB" : (n/1048576).toFixed(1) + " MB";

let KEY = null;

async function deriveKey(password) {
  const salt = b64ToBytes(CONFIG.salt);
  const baseKey = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations: CONFIG.iterations, hash: "SHA-256" },
    baseKey, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
}

async function decryptFile(key, encPath) {
  const buf = new Uint8Array(await (await fetch(encPath)).arrayBuffer());
  const iv = buf.slice(0, 12), ct = buf.slice(12);
  return new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, ct));
}

function triggerDownload(bytes, filename) {
  const url = URL.createObjectURL(new Blob([bytes], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url; a.download = filename; document.body.appendChild(a); a.click();
  a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1500);
}

function renderFiles() {
  const m = CONFIG.meta;
  document.getElementById("meta").innerHTML =
    `${CONFIG.files.length} file(s) &middot; ` +
    (m.latest_period ? `latest period ending <strong>${m.latest_period}</strong> &middot; ` : "") +
    `${m.n_periods} period(s) &middot; generated ${m.generated_at}`;
  const tbody = document.getElementById("rows");
  tbody.innerHTML = "";
  for (const f of CONFIG.files) {
    const tr = document.createElement("tr");
    tr.className = "group-" + f.category;
    const pill = f.category === "all" ? '<span class="pill amber">all</span>'
      : f.category === "latest" ? '<span class="pill amber">latest</span>' : "";
    tr.innerHTML =
      `<td>${f.label}${pill}<br><code>${f.name}</code></td>` +
      `<td class="num">${f.rows.toLocaleString()}</td>` +
      `<td class="num">${fmtBytes(f.bytes)}</td>` +
      `<td class="num"></td>`;
    const btn = document.createElement("button");
    btn.className = "ghost"; btn.textContent = "Download";
    btn.onclick = async () => {
      btn.disabled = true; btn.textContent = "Decrypting…";
      try {
        triggerDownload(await decryptFile(KEY, f.enc), f.name);
        btn.textContent = "Download";
      } catch (e) {
        btn.textContent = "Failed";
      } finally { btn.disabled = false; }
    };
    tr.lastElementChild.appendChild(btn);
    tbody.appendChild(tr);
  }
}

document.getElementById("form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const msg = document.getElementById("msg");
  const pw = document.getElementById("pw").value;
  if (!pw) return;
  msg.className = "msg"; msg.textContent = "Checking…";
  document.getElementById("unlock").disabled = true;
  try {
    const key = await deriveKey(pw);
    // Validate by decrypting the first (smallest is fine) file.
    await decryptFile(key, CONFIG.files[0].enc);
    KEY = key;
    document.getElementById("lock").style.display = "none";
    document.getElementById("files").style.display = "block";
    renderFiles();
  } catch (e) {
    msg.className = "msg err"; msg.textContent = "Incorrect password.";
    document.getElementById("unlock").disabled = false;
  }
});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
