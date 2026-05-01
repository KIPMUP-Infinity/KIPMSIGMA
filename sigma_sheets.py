# ═══════════════════════════════════════════════════════════════════════
# SIGMA SHEETS v2 — Google Sheets Persistent Storage
# by MnM Strategy+ / KIPM-UP
#
# Storage: Google Sheets (primary) + JSON lokal fallback (./sigma_data/)
#
# Sheet yang digunakan (semua bisa 1 spreadsheet atau terpisah):
#   BrokerHistory  — history hasil scan broker
#   RekoHistory    — history rekomendasi AI (Daily/Weekly/BSJP)
#   Journal        — trading journal
#   BackupLog      — log backup/deploy
#   sigma_modules  — storage internal sigma_modules
#
# Import yang dipakai app.py:
#   sheets_available, save_broker_scan, load_broker_history,
#   save_reko, load_reko_history, save_journal_entry, load_journal,
#   update_journal_status, render_sheets_status, render_backup_button,
#   render_history_table, log_backup
# ═══════════════════════════════════════════════════════════════════════

import json
import os
import time
import hashlib
from datetime import datetime, timezone

# ── Local fallback storage ──────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sigma_data")
os.makedirs(DATA_DIR, exist_ok=True)

# ── In-process cache ────────────────────────────────────────────────
_ws_cache    = {}   # {sheet_name: worksheet_object}
_row_index   = {}   # {sheet_name: {key: row_number}}   — untuk _write internal
_data_cache  = {}   # {sheet_name: {key: value}}
_cache_ts    = {}   # {sheet_name: float}
_CACHE_TTL   = 60   # detik

# ── Google Sheets column headers ────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = {
    "BrokerHistory": [
        "timestamp", "ticker", "date_data", "verdict",
        "akumulasi_score", "distribusi_score", "net_flow",
        "top_buyers", "top_sellers", "foreign_net",
        "catatan", "user", "session_id",
    ],
    "RekoHistory": [
        "timestamp", "mode", "ticker", "bias",
        "entry_low", "entry_high", "stoploss",
        "tp1", "tp2", "sigma_score", "grade",
        "summary_ai", "user", "session_id",
    ],
    "Journal": [
        "timestamp", "ticker", "status", "bias",
        "entry_price", "stoploss", "tp1", "tp2",
        "lot_size", "modal", "pnl_rp", "pnl_pct",
        "tanggal_entry", "tanggal_exit",
        "catatan", "setup", "user",
    ],
    "BackupLog": [
        "timestamp", "success", "note",
    ],
    # sheet key-value untuk sigma_modules
    "sigma_modules": ["key", "value", "updated_at", "meta"],
}


# ═══════════════════════════════════════════════════════════════════════
# INTERNAL — Streamlit secrets helper (safe tanpa crash)
# ═══════════════════════════════════════════════════════════════════════

def _get_secret(*keys, default=None):
    """Baca nested secret dengan aman. Return default jika tidak ada."""
    try:
        import streamlit as st
        val = st.secrets
        for k in keys:
            val = val[k]
        return val
    except Exception:
        return default


def _log_error(context: str, e: Exception):
    """Simpan error ke session state untuk ditampilkan di UI."""
    msg = f"[SigmaSheets/{context}] {type(e).__name__}: {str(e)[:300]}"
    try:
        import streamlit as st
        if "sheets_errors" not in st.session_state:
            st.session_state["sheets_errors"] = []
        st.session_state["sheets_errors"].append(msg)
        st.session_state["sheets_errors"] = st.session_state["sheets_errors"][-10:]
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# INTERNAL — Google Sheets client & worksheet helpers
# ═══════════════════════════════════════════════════════════════════════

def _get_client():
    """
    Return authorized gspread client.
    Tangani private_key newline issue dari Streamlit secrets.
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        raw = _get_secret("gsheets_credentials")
        if raw is None:
            return None
        creds_dict = dict(raw)

        # Fix private_key newlines (sering jadi masalah di Streamlit Cloud)
        if "private_key" in creds_dict:
            pk = str(creds_dict["private_key"])
            if "\\n" in pk:
                pk = pk.replace("\\n", "\n")
            creds_dict["private_key"] = pk

        creds  = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        client = gspread.authorize(creds)

        # Hapus error lama kalau berhasil
        try:
            import streamlit as st
            st.session_state.pop("_sheets_last_error", None)
        except Exception:
            pass

        return client

    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        try:
            import streamlit as st
            st.session_state["_sheets_last_error"] = err_msg
        except Exception:
            pass
        return None


def _get_spreadsheet_id(sheet_type: str) -> str:
    """
    Resolve spreadsheet ID berdasarkan tipe sheet.
    Mendukung 1 spreadsheet atau spreadsheet terpisah per tipe.
    Prioritas: spreadsheet_<type> → spreadsheet_database → spreadsheet_broker (fallback umum)
    """
    specific = _get_secret("gsheets", f"spreadsheet_{sheet_type}")
    if specific:
        return specific
    database = _get_secret("gsheets", "spreadsheet_database")
    if database:
        return database
    return _get_secret("gsheets", "spreadsheet_broker", default="")


def _get_sheet_ws(sheet_name: str):
    """
    Return worksheet object. Buat worksheet baru jika belum ada.
    Cache per proses untuk efisiensi.
    """
    if sheet_name in _ws_cache:
        return _ws_cache[sheet_name]

    gc = _get_client()
    if gc is None:
        return None

    try:
        import gspread

        # Tentukan spreadsheet ID berdasarkan nama sheet
        type_map = {
            "BrokerHistory": "broker",
            "RekoHistory":   "reko",
            "Journal":       "journal",
            "BackupLog":     "broker",       # simpan bersama broker
            "sigma_modules": "database",
        }
        ss_id = _get_spreadsheet_id(type_map.get(sheet_name, "broker"))
        if not ss_id:
            return None

        wb = gc.open_by_key(ss_id)

        try:
            ws = wb.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            headers = HEADERS.get(sheet_name, ["key", "value", "updated_at"])
            ws = wb.add_worksheet(title=sheet_name, rows=5000, cols=len(headers))
            ws.append_row(headers, value_input_option="RAW")

        # Pastikan header ada (sheet mungkin kosong)
        existing = ws.row_values(1)
        if not existing and sheet_name in HEADERS:
            ws.append_row(HEADERS[sheet_name], value_input_option="RAW")

        _ws_cache[sheet_name] = ws
        return ws

    except Exception as e:
        _log_error(f"_get_sheet_ws({sheet_name})", e)
        return None


# ═══════════════════════════════════════════════════════════════════════
# INTERNAL — Key-Value API (dipakai sigma_modules)
# ═══════════════════════════════════════════════════════════════════════

def _load_sheet(sheet_name: str) -> dict:
    """Fetch seluruh sheet key-value → dict. Dengan TTL cache."""
    now = time.time()
    if sheet_name in _data_cache and (now - _cache_ts.get(sheet_name, 0)) < _CACHE_TTL:
        return _data_cache[sheet_name]

    ws = _get_sheet_ws(sheet_name)
    if ws is None:
        return _data_cache.get(sheet_name, {})

    try:
        all_vals = ws.get_all_values()
        result, ridx = {}, {}
        for i, row in enumerate(all_vals):
            if i == 0:
                continue
            if not row or not row[0].strip():
                continue
            k = row[0].strip()
            v = row[1].strip() if len(row) > 1 else ""
            try:
                result[k] = json.loads(v)
            except Exception:
                result[k] = v
            ridx[k] = i + 1   # 1-indexed
        _data_cache[sheet_name] = result
        _row_index[sheet_name]  = ridx
        _cache_ts[sheet_name]   = now
        return result
    except Exception as e:
        _log_error(f"_load_sheet({sheet_name})", e)
        return _data_cache.get(sheet_name, {})


def _write(sheet_name: str, key: str, value) -> bool:
    """
    Upsert satu baris key-value ke worksheet.
    Fallback ke file lokal jika Sheets tidak tersedia.
    """
    ws = _get_sheet_ws(sheet_name)
    if ws is None:
        return _local_write(sheet_name, key, value)

    try:
        val_str = json.dumps(value, ensure_ascii=False)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _load_sheet(sheet_name)   # pastikan row_index ter-load
        ridx = _row_index.get(sheet_name, {}).get(key)

        if ridx:
            ws.update(f"B{ridx}:C{ridx}", [[val_str, now_str]])
        else:
            ws.append_row([key, val_str, now_str, ""], value_input_option="RAW")
            _cache_ts[sheet_name] = 0   # invalidate cache

        # Update in-memory cache
        if sheet_name not in _data_cache:
            _data_cache[sheet_name] = {}
        _data_cache[sheet_name][key] = value

        _local_write(sheet_name, key, value)   # double-safety ke lokal
        return True

    except Exception as e:
        _log_error(f"_write({sheet_name}/{key})", e)
        return _local_write(sheet_name, key, value)


def _local_write(sheet_name: str, key: str, value) -> bool:
    """Fallback: simpan ke file lokal."""
    try:
        fname = f"sh_{sheet_name}_{hashlib.md5(key.encode()).hexdigest()[:8]}.json"
        with open(os.path.join(DATA_DIR, fname), "w", encoding="utf-8") as f:
            json.dump({"key": key, "value": value}, f, ensure_ascii=False)
        return True
    except Exception:
        return False


def _local_read(sheet_name: str, key: str):
    """Baca dari file lokal fallback."""
    try:
        fname = f"sh_{sheet_name}_{hashlib.md5(key.encode()).hexdigest()[:8]}.json"
        p = os.path.join(DATA_DIR, fname)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f).get("value")
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API — sheets_available
# ═══════════════════════════════════════════════════════════════════════

def sheets_available() -> bool:
    """Return True jika Google Sheets terkonfigurasi dengan benar."""
    creds = _get_secret("gsheets_credentials")
    # Minimal perlu 1 spreadsheet ID tersedia
    ss_id = (
        _get_secret("gsheets", "spreadsheet_broker") or
        _get_secret("gsheets", "spreadsheet_database") or
        _get_secret("gsheets", "spreadsheet_reko")
    )
    return bool(creds and ss_id)


def _now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _session_id() -> str:
    try:
        import streamlit as st
        return st.session_state.get("sigma_session_id", "sigma")
    except Exception:
        return "sigma"


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API — Broker Summary
# ═══════════════════════════════════════════════════════════════════════

def save_broker_scan(
    ticker: str,
    date_data: str,
    verdict: str = "NEUTRAL",
    akumulasi_score: float = 0,
    distribusi_score: float = 0,
    net_flow: float = 0,
    top_buyers: list = None,
    top_sellers: list = None,
    foreign_net: float = 0.0,
    catatan: str = "",
    user: str = "SIGMA",
) -> bool:
    """
    Simpan hasil scan broker ke Google Sheets.
    verdict: "AKUMULASI" / "DISTRIBUSI" / "MIXED" / "NEUTRAL"
    """
    if not sheets_available():
        return False
    try:
        ws = _get_sheet_ws("BrokerHistory")
        if ws is None:
            return False
        row = [
            _now_utc_str(),
            ticker.upper(),
            date_data,
            verdict,
            round(akumulasi_score, 2),
            round(distribusi_score, 2),
            round(net_flow, 0),
            json.dumps((top_buyers or [])[:5]),
            json.dumps((top_sellers or [])[:5]),
            round(foreign_net, 0),
            catatan,
            user,
            _session_id(),
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        _log_error("save_broker_scan", e)
        return False


def load_broker_history(ticker: str = None, limit: int = 100) -> list:
    """
    Load history broker scan. Urutan terbaru dulu.
    ticker=None → semua ticker.
    """
    if not sheets_available():
        return []
    try:
        ws = _get_sheet_ws("BrokerHistory")
        if ws is None:
            return []
        rows = ws.get_all_records()
        if ticker:
            rows = [r for r in rows if r.get("ticker", "").upper() == ticker.upper()]
        return list(reversed(rows))[:limit]
    except Exception as e:
        _log_error("load_broker_history", e)
        return []


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API — Rekomendasi AI
# ═══════════════════════════════════════════════════════════════════════

def save_reko(
    mode: str,
    ticker: str,
    bias: str = "NEUTRAL",
    entry_low: float = 0,
    entry_high: float = 0,
    stoploss: float = 0,
    tp1: float = 0,
    tp2: float = 0,
    sigma_score: int = 0,
    grade: str = "",
    summary_ai: str = "",
    user: str = "SIGMA",
) -> bool:
    """
    Simpan output rekomendasi AI (Daily/Weekly/BSJP) ke Google Sheets.
    mode: "DAILY" / "WEEKLY" / "BSJP"
    """
    if not sheets_available():
        return False
    try:
        ws = _get_sheet_ws("RekoHistory")
        if ws is None:
            return False
        row = [
            _now_utc_str(),
            mode.upper(), ticker.upper(), bias.upper(),
            entry_low, entry_high, stoploss,
            tp1, tp2, sigma_score, grade,
            str(summary_ai)[:500],
            user, _session_id(),
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        _log_error("save_reko", e)
        return False


def load_reko_history(mode: str = None, ticker: str = None, limit: int = 50) -> list:
    """
    Load history rekomendasi. Urutan terbaru dulu.
    mode=None → semua. ticker=None → semua.
    """
    if not sheets_available():
        return []
    try:
        ws = _get_sheet_ws("RekoHistory")
        if ws is None:
            return []
        rows = ws.get_all_records()
        if mode:
            rows = [r for r in rows if r.get("mode", "").upper() == mode.upper()]
        if ticker:
            rows = [r for r in rows if r.get("ticker", "").upper() == ticker.upper()]
        return list(reversed(rows))[:limit]
    except Exception as e:
        _log_error("load_reko_history", e)
        return []


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API — Trading Journal
# ═══════════════════════════════════════════════════════════════════════

def save_journal_entry(
    ticker: str,
    status: str = "ON WATCH",
    bias: str = "BUY",
    entry_price: float = 0,
    stoploss: float = 0,
    tp1: float = 0,
    tp2: float = 0,
    lot_size: int = 0,
    modal: float = 0.0,
    pnl_rp: float = 0.0,
    pnl_pct: float = 0.0,
    tanggal_entry: str = "",
    tanggal_exit: str = "",
    catatan: str = "",
    setup: str = "",
    user: str = "SIGMA",
) -> bool:
    """
    Simpan entry trading journal ke Google Sheets.
    status: "ON WATCH" / "MATCH BUY 1" / "MATCH BUY 2" /
            "HIT TARGET 1" / "HIT TARGET 2" / "HIT STOPLOSS" / "CLOSED"
    """
    if not sheets_available():
        return False
    try:
        ws = _get_sheet_ws("Journal")
        if ws is None:
            return False
        row = [
            _now_utc_str(),
            ticker.upper(), status, bias.upper(),
            entry_price, stoploss, tp1, tp2,
            lot_size, modal, pnl_rp, round(pnl_pct, 2),
            tanggal_entry or datetime.now().strftime("%Y-%m-%d"),
            tanggal_exit,
            catatan, setup, user,
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        _log_error("save_journal_entry", e)
        return False


def load_journal(ticker: str = None, status: str = None, limit: int = 200) -> list:
    """
    Load trading journal. Urutan terbaru dulu.
    ticker=None → semua. status=None → semua.
    """
    if not sheets_available():
        return []
    try:
        ws = _get_sheet_ws("Journal")
        if ws is None:
            return []
        rows = ws.get_all_records()
        if ticker:
            rows = [r for r in rows if r.get("ticker", "").upper() == ticker.upper()]
        if status:
            rows = [r for r in rows if status.upper() in r.get("status", "").upper()]
        # Simpan key internal (_row_num) untuk keperluan update
        for i, r in enumerate(rows):
            r["_row_num"] = i + 2   # +2 karena header di row 1
        return list(reversed(rows))[:limit]
    except Exception as e:
        _log_error("load_journal", e)
        return []


def update_journal_status(
    ticker: str,
    old_status: str,
    new_status: str,
    pnl_rp: float = None,
    pnl_pct: float = None,
    tanggal_exit: str = None,
    hasil: str = "",
    catatan: str = "",
) -> bool:
    """
    Update status entry journal yang ada (ON WATCH → HIT TARGET 1, dll).
    Update row pertama yang match ticker + old_status.
    Mendukung signature lama (key, status, hasil, catatan) dan baru.
    """
    if not sheets_available():
        return False
    try:
        ws = _get_sheet_ws("Journal")
        if ws is None:
            return False

        rows     = ws.get_all_values()
        headers  = rows[0] if rows else []
        if not headers:
            return False
        col_idx  = {h: i + 1 for i, h in enumerate(headers)}

        for i, row in enumerate(rows[1:], start=2):
            row_dict = dict(zip(headers, row))
            if (row_dict.get("ticker", "").upper() == ticker.upper() and
                    old_status.upper() in row_dict.get("status", "").upper()):
                ws.update_cell(i, col_idx["status"], new_status)
                if pnl_rp is not None and "pnl_rp" in col_idx:
                    ws.update_cell(i, col_idx["pnl_rp"], pnl_rp)
                if pnl_pct is not None and "pnl_pct" in col_idx:
                    ws.update_cell(i, col_idx["pnl_pct"], round(pnl_pct, 2))
                if tanggal_exit and "tanggal_exit" in col_idx:
                    ws.update_cell(i, col_idx["tanggal_exit"], tanggal_exit)
                if catatan and "catatan" in col_idx:
                    ws.update_cell(i, col_idx["catatan"], catatan)
                return True
        return False

    except Exception as e:
        _log_error("update_journal_status", e)
        return False


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API — Backup Log
# ═══════════════════════════════════════════════════════════════════════

def log_backup(success: bool = True, note: str = "", version: str = "",
               filename: str = "", size_kb: float = 0, commit_hash: str = "") -> bool:
    """
    Catat log backup/deploy ke Google Sheets (sheet BackupLog).
    Mendukung signature lama (success, note) dan baru (version, filename, ...).
    """
    if not sheets_available():
        return False
    try:
        ws = _get_sheet_ws("BackupLog")
        if ws is None:
            return False
        # Format fleksibel — gabung semua info ke note jika ada
        full_note = note
        if version or filename:
            full_note = f"{version} | {filename} | {full_note}".strip(" |")
        row = [_now_utc_str(), str(success), full_note[:500]]
        ws.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        _log_error("log_backup", e)
        return False


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API — Export semua data
# ═══════════════════════════════════════════════════════════════════════

def export_all_to_json() -> dict:
    """Export semua data dari Sheets untuk download backup."""
    return {
        "exported_at":    datetime.now(timezone.utc).isoformat(),
        "sigma_version":  "SIGMA KIPM-UP v2",
        "broker_history": load_broker_history(limit=1000),
        "reko_history":   load_reko_history(limit=500),
        "journal":        load_journal(limit=500),
    }


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API — Streamlit UI Helpers
# ═══════════════════════════════════════════════════════════════════════

def render_sheets_status():
    """Render status koneksi Google Sheets + link ke tiap sheet + tombol test."""
    try:
        import streamlit as st

        ok = sheets_available()
        status_color = "#26a69a" if ok else "#f23645"
        status_label = "✅ Terhubung" if ok else "❌ Tidak Terhubung"

        st.markdown(
            f"<div style='color:{status_color};font-size:0.85rem;padding:4px 0'>"
            f"📊 Google Sheets: <b>{status_label}</b></div>",
            unsafe_allow_html=True)

        if ok:
            # Tampilkan link ke setiap spreadsheet
            base = "https://docs.google.com/spreadsheets/d"
            links = []
            for key, label in [("spreadsheet_broker",   "📋 Broker History"),
                                ("spreadsheet_reko",     "🤖 Reko History"),
                                ("spreadsheet_journal",  "📓 Journal"),
                                ("spreadsheet_database", "🗄 Database")]:
                sid = _get_secret("gsheets", key)
                if sid:
                    links.append(f"<a href='{base}/{sid}' target='_blank' "
                                 f"style='color:#90caf9;font-size:0.8rem'>{label}</a>")
            if links:
                st.markdown(" &nbsp; ".join(links), unsafe_allow_html=True)

        # Tombol test koneksi
        if st.button("🔌 Test Sheets", key="btn_test_sheets", use_container_width=True):
            with st.spinner("Testing koneksi Google Sheets..."):
                if not ok:
                    st.error("❌ Credentials tidak ditemukan di Streamlit secrets.\n\n"
                             "Pastikan [gsheets_credentials] dan [gsheets] sudah diisi.")
                else:
                    client = _get_client()
                    if client:
                        st.success("✅ Koneksi Google Sheets OK!")
                    else:
                        real_err = st.session_state.get("_sheets_last_error", "Unknown")
                        st.error(f"❌ Gagal connect.\n\n**Detail:**\n```\n{real_err}\n```")

        # Error log
        errors = st.session_state.get("sheets_errors", [])
        if errors:
            with st.expander(f"⚠️ {len(errors)} Sheets Error (klik untuk lihat)", expanded=False):
                for e in reversed(errors[-5:]):
                    st.caption(e)
                if st.button("🗑 Clear Errors", key="btn_clear_sheets_err"):
                    st.session_state["sheets_errors"] = []
                    st.rerun()

    except Exception as e:
        try:
            import streamlit as st
            st.error(f"Error render sheets status: {e}")
        except Exception:
            pass


def render_backup_button():
    """Render tombol Download Backup JSON semua data."""
    try:
        import streamlit as st

        if not sheets_available():
            st.info("⚠️ Google Sheets tidak terhubung — backup tidak tersedia.")
            return

        if st.button("💾 Download Backup Semua Data", key="btn_download_backup",
                     use_container_width=True):
            with st.spinner("Mengambil semua data dari Google Sheets..."):
                data     = export_all_to_json()
                json_str = json.dumps(data, indent=2, ensure_ascii=False)
                fname    = f"SIGMA_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
                st.download_button(
                    label=f"⬇️ {fname}",
                    data=json_str.encode("utf-8"),
                    file_name=fname,
                    mime="application/json",
                    key="btn_dl_json",
                )
                st.success(
                    f"✅ Data siap download: "
                    f"{len(data['broker_history'])} broker scan · "
                    f"{len(data['reko_history'])} reko · "
                    f"{len(data['journal'])} journal entry.")

    except Exception as e:
        try:
            import streamlit as st
            st.error(f"Error backup: {e}")
        except Exception:
            pass


def render_history_table(history_type: str = "broker", limit: int = 30,
                         ticker: str = None):
    """
    Render tabel history dari Google Sheets.
    history_type: 'broker' | 'reko' | 'journal'
    Mendukung parameter lama (history_type) dan alias data_type.
    """
    try:
        import streamlit as st
        import pandas as pd

        loaders = {
            "broker":  lambda: load_broker_history(ticker=ticker, limit=limit),
            "reko":    lambda: load_reko_history(ticker=ticker, limit=limit),
            "journal": lambda: load_journal(ticker=ticker, limit=limit),
        }

        if history_type not in loaders:
            st.error(f"history_type tidak valid: {history_type}")
            return

        with st.spinner(f"Memuat {history_type} history dari Google Sheets..."):
            rows = loaders[history_type]()

        if not rows:
            st.info(f"Belum ada data {history_type} history"
                    + (f" untuk {ticker}" if ticker else "") + ".")
            return

        df = pd.DataFrame(rows)
        # Hapus kolom internal
        df = df.drop(columns=[c for c in ["session_id", "_row_num", "_key"]
                               if c in df.columns], errors="ignore")

        # Styling tabel berdasarkan tipe
        if history_type == "broker":
            verdict_colors = {"AKUMULASI": "✅", "DISTRIBUSI": "❌", "NEUTRAL": "⚪", "MIXED": "🟡"}
            if "verdict" in df.columns:
                df["verdict"] = df["verdict"].apply(
                    lambda v: f"{verdict_colors.get(str(v).upper(), '')} {v}")

        elif history_type == "journal":
            status_colors = {
                "HIT TARGET": "✅", "HIT STOPLOSS": "❌",
                "ON WATCH": "👁", "MATCH BUY": "🟢", "CLOSED": "⚫"
            }
            if "status" in df.columns:
                def _color_status(s):
                    for k, icon in status_colors.items():
                        if k in str(s).upper():
                            return f"{icon} {s}"
                    return s
                df["status"] = df["status"].apply(_color_status)

        st.dataframe(df, use_container_width=True, height=400, hide_index=True)
        st.caption(f"📌 {len(df)} records ditampilkan"
                   + (" · Google Sheets" if sheets_available() else " · Data lokal"))

    except Exception as e:
        try:
            import streamlit as st
            st.warning(f"Tidak bisa render history: {e}")
        except Exception:
            pass
