# ═══════════════════════════════════════════════════════════════════════════════
# SIGMA SHEETS — Google Sheets Persistent Storage
# by MnM Strategy+ / KIPM-UP
#
# Fungsi:
#   - Simpan & load history Broker Summary scan
#   - Simpan & load history Rekomendasi AI (Daily/Weekly/BSJP)
#   - Simpan & load Trading Journal MnM Strategy+
#   - Backup otomatis setiap kali ada data baru
#   - Semua data publik & bisa diakses langsung via Google Sheets link
#
# Setup:
#   1. Tambahkan credentials di Streamlit secrets (lihat README)
#   2. Tambahkan gspread + google-auth di requirements.txt
#   3. Import modul ini di app.py
# ═══════════════════════════════════════════════════════════════════════════════

import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone
import json
import time
import traceback
from typing import Optional

# ─────────────────────────────────────────────
# KONFIGURASI
# ─────────────────────────────────────────────

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Header kolom untuk setiap sheet
HEADERS = {
    "broker": [
        "timestamp", "ticker", "date_data", "verdict",
        "akumulasi_score", "distribusi_score", "net_flow",
        "top_buyers", "top_sellers", "foreign_net",
        "catatan", "user", "session_id"
    ],
    "reko": [
        "timestamp", "mode", "ticker", "bias",
        "entry_low", "entry_high", "stoploss",
        "tp1", "tp2", "sigma_score", "grade",
        "summary_ai", "user", "session_id"
    ],
    "journal": [
        "timestamp", "ticker", "status", "bias",
        "entry_price", "stoploss", "tp1", "tp2",
        "lot_size", "modal", "pnl_rp", "pnl_pct",
        "tanggal_entry", "tanggal_exit",
        "catatan", "setup", "user"
    ],
    "backup": [
        "timestamp", "version", "filename",
        "size_kb", "commit_hash", "catatan"
    ]
}


# ─────────────────────────────────────────────
# KONEKSI & AUTH
# ─────────────────────────────────────────────

@st.cache_resource(ttl=3600)
def _get_gspread_client():
    """
    Inisialisasi gspread client dari Streamlit secrets.
    Di-cache 1 jam supaya tidak reconnect setiap request.
    """
    try:
        creds_dict = dict(st.secrets["gsheets_credentials"])
        # Streamlit secrets kadang escape newline — fix private_key
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        return None


def _get_sheet(spreadsheet_id: str, worksheet_name: str, headers: list):
    """
    Buka worksheet. Jika belum ada, buat otomatis + isi header.
    Return: worksheet object atau None jika gagal.
    """
    try:
        client = _get_gspread_client()
        if not client:
            return None
        ss = client.open_by_key(spreadsheet_id)
        try:
            ws = ss.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            # Buat worksheet baru
            ws = ss.add_worksheet(title=worksheet_name, rows=1000, cols=len(headers))
            ws.append_row(headers, value_input_option="RAW")
        # Cek apakah header sudah ada
        existing = ws.row_values(1)
        if not existing:
            ws.append_row(headers, value_input_option="RAW")
        return ws
    except Exception as e:
        _log_error("_get_sheet", e)
        return None


def _log_error(context: str, e: Exception):
    """Simpan error ke session state untuk ditampilkan di UI."""
    msg = f"[SigmaSheets/{context}] {type(e).__name__}: {str(e)[:200]}"
    try:
        if "sheets_errors" not in st.session_state:
            st.session_state["sheets_errors"] = []
        st.session_state["sheets_errors"].append(msg)
        # Keep max 10 errors
        st.session_state["sheets_errors"] = st.session_state["sheets_errors"][-10:]
    except Exception:
        pass


def sheets_available() -> bool:
    """Cek apakah Google Sheets tersedia (credentials ada + koneksi OK)."""
    try:
        has_creds = bool(st.secrets.get("gsheets_credentials"))
        has_ids   = bool(st.secrets.get("gsheets", {}).get("spreadsheet_broker"))
        return has_creds and has_ids
    except Exception:
        return False


# ─────────────────────────────────────────────
# BROKER SUMMARY — SAVE & LOAD
# ─────────────────────────────────────────────

def save_broker_scan(
    ticker: str,
    date_data: str,
    verdict: str,
    akumulasi_score: float,
    distribusi_score: float,
    net_flow: float,
    top_buyers: list,
    top_sellers: list,
    foreign_net: float = 0.0,
    catatan: str = "",
    user: str = "SIGMA",
) -> bool:
    """
    Simpan hasil scan broker summary ke Google Sheets.

    Args:
        ticker          : Kode saham (misal: "BBCA")
        date_data       : Tanggal data broker (YYYY-MM-DD)
        verdict         : "AKUMULASI" / "DISTRIBUSI" / "MIXED" / "NEUTRAL"
        akumulasi_score : Score akumulasi (0–100)
        distribusi_score: Score distribusi (0–100)
        net_flow        : Net lot flow (positif = akumulasi)
        top_buyers      : List dict [{"broker": "RX", "lot": 1000}, ...]
        top_sellers     : List dict [{"broker": "BK", "lot": 800}, ...]
        foreign_net     : Net flow asing (lot)
        catatan         : Catatan tambahan
        user            : Username / identifier

    Returns:
        True jika berhasil, False jika gagal
    """
    if not sheets_available():
        return False
    try:
        ss_id = st.secrets["gsheets"]["spreadsheet_broker"]
        ws = _get_sheet(ss_id, "BrokerHistory", HEADERS["broker"])
        if not ws:
            return False

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        session_id = st.session_state.get("sigma_session_id", "unknown")

        row = [
            now,
            ticker.upper(),
            date_data,
            verdict,
            round(akumulasi_score, 2),
            round(distribusi_score, 2),
            round(net_flow, 0),
            json.dumps(top_buyers[:5]),   # max 5 broker
            json.dumps(top_sellers[:5]),
            round(foreign_net, 0),
            catatan,
            user,
            session_id,
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        _log_error("save_broker_scan", e)
        return False


def load_broker_history(ticker: str = None, limit: int = 100) -> list:
    """
    Load history broker scan dari Google Sheets.

    Args:
        ticker : Filter by ticker. None = semua ticker.
        limit  : Maksimal rows yang diambil (terbaru dulu).

    Returns:
        List of dict, urutan terbaru ke terlama.
    """
    if not sheets_available():
        return []
    try:
        ss_id = st.secrets["gsheets"]["spreadsheet_broker"]
        ws = _get_sheet(ss_id, "BrokerHistory", HEADERS["broker"])
        if not ws:
            return []

        all_rows = ws.get_all_records()
        if ticker:
            all_rows = [r for r in all_rows if r.get("ticker", "").upper() == ticker.upper()]

        # Urutan terbaru dulu
        all_rows = list(reversed(all_rows))
        return all_rows[:limit]
    except Exception as e:
        _log_error("load_broker_history", e)
        return []


# ─────────────────────────────────────────────
# REKOMENDASI AI — SAVE & LOAD
# ─────────────────────────────────────────────

def save_reko(
    mode: str,
    ticker: str,
    bias: str,
    entry_low: float,
    entry_high: float,
    stoploss: float,
    tp1: float,
    tp2: float,
    sigma_score: int = 0,
    grade: str = "",
    summary_ai: str = "",
    user: str = "SIGMA",
) -> bool:
    """
    Simpan output rekomendasi AI ke Google Sheets.

    Args:
        mode     : "DAILY" / "WEEKLY" / "BSJP"
        ticker   : Kode saham
        bias     : "BULLISH" / "BEARISH" / "NEUTRAL"
        entry_low/high: Range entry (Rp)
        stoploss : Level SL (Rp)
        tp1/tp2  : Target profit (Rp)
        sigma_score: Score SIGMA (0–100)
        grade    : "STRONG BUY" / "BUY" / "WATCH" / dll
        summary_ai: Ringkasan analisa AI
        user     : Username

    Returns:
        True jika berhasil
    """
    if not sheets_available():
        return False
    try:
        ss_id = st.session_state.get("_sheets_reko_id") or st.secrets["gsheets"]["spreadsheet_reko"]
        ws = _get_sheet(ss_id, "RekoHistory", HEADERS["reko"])
        if not ws:
            return False

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        session_id = st.session_state.get("sigma_session_id", "unknown")

        row = [
            now, mode.upper(), ticker.upper(), bias.upper(),
            entry_low, entry_high, stoploss,
            tp1, tp2,
            sigma_score, grade,
            summary_ai[:500],  # trim panjang
            user, session_id,
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        _log_error("save_reko", e)
        return False


def load_reko_history(mode: str = None, ticker: str = None, limit: int = 50) -> list:
    """
    Load history rekomendasi dari Google Sheets.

    Args:
        mode   : Filter by mode ("DAILY"/"WEEKLY"/"BSJP"). None = semua.
        ticker : Filter by ticker. None = semua.
        limit  : Maks rows.

    Returns:
        List of dict, terbaru dulu.
    """
    if not sheets_available():
        return []
    try:
        ss_id = st.secrets["gsheets"]["spreadsheet_reko"]
        ws = _get_sheet(ss_id, "RekoHistory", HEADERS["reko"])
        if not ws:
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


# ─────────────────────────────────────────────
# TRADING JOURNAL — SAVE & LOAD
# ─────────────────────────────────────────────

def save_journal_entry(
    ticker: str,
    status: str,
    bias: str,
    entry_price: float,
    stoploss: float,
    tp1: float,
    tp2: float,
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

    Status: "ON WATCH" / "MATCH BUY 1" / "MATCH BUY 2" /
            "HIT TARGET 1" / "HIT TARGET 2" / "HIT STOPLOSS"
    """
    if not sheets_available():
        return False
    try:
        ss_id = st.secrets["gsheets"]["spreadsheet_journal"]
        ws = _get_sheet(ss_id, "Journal", HEADERS["journal"])
        if not ws:
            return False

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        row = [
            now, ticker.upper(), status, bias.upper(),
            entry_price, stoploss, tp1, tp2,
            lot_size, modal, pnl_rp, round(pnl_pct, 2),
            tanggal_entry, tanggal_exit,
            catatan, setup, user,
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        _log_error("save_journal_entry", e)
        return False


def load_journal(ticker: str = None, status: str = None, limit: int = 200) -> list:
    """
    Load trading journal dari Google Sheets.

    Args:
        ticker : Filter by ticker. None = semua.
        status : Filter by status. None = semua.
        limit  : Maks rows.

    Returns:
        List of dict, terbaru dulu.
    """
    if not sheets_available():
        return []
    try:
        ss_id = st.secrets["gsheets"]["spreadsheet_journal"]
        ws = _get_sheet(ss_id, "Journal", HEADERS["journal"])
        if not ws:
            return []

        rows = ws.get_all_records()
        if ticker:
            rows = [r for r in rows if r.get("ticker", "").upper() == ticker.upper()]
        if status:
            rows = [r for r in rows if status.upper() in r.get("status", "").upper()]

        return list(reversed(rows))[:limit]
    except Exception as e:
        _log_error("load_journal", e)
        return []


def update_journal_status(ticker: str, old_status: str, new_status: str,
                           pnl_rp: float = None, pnl_pct: float = None,
                           tanggal_exit: str = None) -> bool:
    """
    Update status entry journal yang sudah ada (misal ON WATCH → HIT TARGET 1).
    Update row pertama yang match ticker + old_status.
    """
    if not sheets_available():
        return False
    try:
        ss_id = st.secrets["gsheets"]["spreadsheet_journal"]
        ws = _get_sheet(ss_id, "Journal", HEADERS["journal"])
        if not ws:
            return False

        rows = ws.get_all_values()
        headers = rows[0] if rows else []
        if not headers:
            return False

        col_idx = {h: i+1 for i, h in enumerate(headers)}
        for i, row in enumerate(rows[1:], start=2):
            row_dict = dict(zip(headers, row))
            if (row_dict.get("ticker", "").upper() == ticker.upper() and
                    old_status.upper() in row_dict.get("status", "").upper()):
                # Update status
                ws.update_cell(i, col_idx["status"], new_status)
                if pnl_rp is not None and "pnl_rp" in col_idx:
                    ws.update_cell(i, col_idx["pnl_rp"], pnl_rp)
                if pnl_pct is not None and "pnl_pct" in col_idx:
                    ws.update_cell(i, col_idx["pnl_pct"], round(pnl_pct, 2))
                if tanggal_exit and "tanggal_exit" in col_idx:
                    ws.update_cell(i, col_idx["tanggal_exit"], tanggal_exit)
                return True
        return False
    except Exception as e:
        _log_error("update_journal_status", e)
        return False


# ─────────────────────────────────────────────
# BACKUP LOG — CATAT SETIAP DEPLOY/UPDATE
# ─────────────────────────────────────────────

def log_backup(version: str, filename: str, size_kb: float = 0,
               commit_hash: str = "", catatan: str = "") -> bool:
    """
    Catat log backup/deploy ke Google Sheets.
    Panggil ini setiap kali ada update kode besar.
    """
    if not sheets_available():
        return False
    try:
        ss_id = st.secrets["gsheets"]["spreadsheet_broker"]  # simpan di sheet yang sama
        ws = _get_sheet(ss_id, "BackupLog", HEADERS["backup"])
        if not ws:
            return False

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        row = [now, version, filename, size_kb, commit_hash, catatan]
        ws.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        _log_error("log_backup", e)
        return False


# ─────────────────────────────────────────────
# EXPORT SEMUA DATA — UNTUK BACKUP MANUAL
# ─────────────────────────────────────────────

def export_all_to_json() -> dict:
    """
    Export semua data dari semua sheet ke satu dict.
    Digunakan untuk tombol "Download Backup" di UI.

    Returns:
        Dict dengan keys: broker_history, reko_history, journal
    """
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "sigma_version": "SIGMA KIPM-UP",
        "broker_history": load_broker_history(limit=1000),
        "reko_history":   load_reko_history(limit=500),
        "journal":        load_journal(limit=500),
    }


# ─────────────────────────────────────────────
# STREAMLIT UI HELPER — KOMPONEN SIAP PAKAI
# ─────────────────────────────────────────────

def render_sheets_status():
    """
    Render status koneksi Google Sheets di sidebar/settings.
    Tampilkan link ke setiap sheet + tombol test koneksi.
    """
    ok = sheets_available()
    status_color = "#26a69a" if ok else "#f23645"
    status_label = "✅ Terhubung" if ok else "❌ Tidak Terhubung"

    st.markdown(
        f"<div style='color:{status_color};font-size:0.85rem;padding:4px 0'>"
        f"📊 Google Sheets: <b>{status_label}</b></div>",
        unsafe_allow_html=True
    )

    if ok:
        try:
            broker_id  = st.secrets["gsheets"].get("spreadsheet_broker", "")
            reko_id    = st.secrets["gsheets"].get("spreadsheet_reko", "")
            journal_id = st.secrets["gsheets"].get("spreadsheet_journal", "")
            base = "https://docs.google.com/spreadsheets/d"

            links_html = ""
            if broker_id:
                links_html += f"<a href='{base}/{broker_id}' target='_blank' style='color:#90caf9;font-size:0.8rem'>📋 Broker History</a> &nbsp;"
            if reko_id:
                links_html += f"<a href='{base}/{reko_id}' target='_blank' style='color:#90caf9;font-size:0.8rem'>🤖 Reko History</a> &nbsp;"
            if journal_id:
                links_html += f"<a href='{base}/{journal_id}' target='_blank' style='color:#90caf9;font-size:0.8rem'>📓 Journal</a>"

            if links_html:
                st.markdown(links_html, unsafe_allow_html=True)
        except Exception:
            pass

    # Tombol test koneksi
    if st.button("🔌 Test Sheets", key="btn_test_sheets", use_container_width=True):
        with st.spinner("Testing koneksi Google Sheets..."):
            if not ok:
                st.error("❌ Credentials tidak ditemukan di Streamlit secrets.\n\nPastikan [gsheets_credentials] dan [gsheets] sudah diisi.")
            else:
                client = _get_gspread_client(force_refresh=True)
                if client:
                    st.success("✅ Koneksi Google Sheets OK!")
                else:
                    _real_err = st.session_state.get("_sheets_last_error", "Unknown error")
                    st.error(f"❌ Gagal connect.\n\n**Error asli:**\n```\n{_real_err}\n```")
                    st.info("💡 Cek:\n- Format private_key di secrets (harus multiline `\"\"\"...\"\"\"`)\n- Service account sudah di-share ke Google Sheets\n- gspread + google-auth ada di requirements.txt")

    # Error log
    errors = st.session_state.get("sheets_errors", [])
    if errors:
        with st.expander(f"⚠️ {len(errors)} Sheets Error", expanded=False):
            for e in reversed(errors[-5:]):
                st.caption(e)
        if st.button("🗑 Clear Errors", key="btn_clear_sheets_err"):
            st.session_state["sheets_errors"] = []
            st.rerun()


def render_backup_button():
    """
    Render tombol Download Backup JSON di UI.
    User bisa download semua data sebagai file JSON.
    """
    if not sheets_available():
        st.caption("⚠️ Google Sheets tidak terhubung — backup tidak tersedia.")
        return

    if st.button("💾 Download Backup Semua Data", key="btn_download_backup",
                 use_container_width=True):
        with st.spinner("Mengambil semua data dari Google Sheets..."):
            data = export_all_to_json()
            import json as _json
            json_str = _json.dumps(data, indent=2, ensure_ascii=False)
            fname = f"SIGMA_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
            st.download_button(
                label=f"⬇️ {fname}",
                data=json_str.encode("utf-8"),
                file_name=fname,
                mime="application/json",
                key="btn_dl_json"
            )
            st.success(f"✅ Data siap download: {len(data['broker_history'])} broker scan, "
                       f"{len(data['reko_history'])} reko, {len(data['journal'])} journal entry.")


def render_history_table(data_type: str = "broker", ticker: str = None, limit: int = 20):
    """
    Render tabel history langsung di UI.

    Args:
        data_type : "broker" / "reko" / "journal"
        ticker    : Filter by ticker. None = semua.
        limit     : Maks rows ditampilkan.
    """
    import pandas as pd

    loaders = {
        "broker":  lambda: load_broker_history(ticker=ticker, limit=limit),
        "reko":    lambda: load_reko_history(ticker=ticker, limit=limit),
        "journal": lambda: load_journal(ticker=ticker, limit=limit),
    }

    if data_type not in loaders:
        st.error(f"data_type tidak valid: {data_type}")
        return

    with st.spinner(f"Memuat {data_type} history..."):
        rows = loaders[data_type]()

    if not rows:
        st.info(f"Belum ada data {data_type} history" +
                (f" untuk {ticker}" if ticker else "") + ".")
        return

    df = pd.DataFrame(rows)
    # Drop kolom internal
    drop_cols = ["session_id"]
    df = df.drop(columns=[c for c in drop_cols if c in df.columns], errors="ignore")
    st.dataframe(df, use_container_width=True, height=400)
    st.caption(f"{len(df)} records ditampilkan")
