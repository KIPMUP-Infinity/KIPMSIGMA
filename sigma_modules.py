"""
sigma_modules.py
================
SIGMA AI — semua modul dalam satu file.

Berisi:
  [STORAGE]   load/save JSON lokal ke ./sigma_data/
  [DAILY]     render_daily_plan(), append_daily_plan(), append_daily_summary()
  [WEEKLY]    render_weekly_plan(), append_weekly_plan(), append_weekly_summary()
  [FUNSCREEN] render_fundamental_screener(), append_fundamental_data()
  [ALPHA]     render_alpha_stock_insight(), append_alpha_insight()
  [BROKSUM]   render_broker_summary(), save_broker_screening_result()
  [TRACKRECORD] render_track_record(), record_trade_result()

Data disimpan ke ./sigma_data/*.json — tidak hilang saat restart.
"""

import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime, date, timedelta
import pytz

WIB = pytz.timezone("Asia/Jakarta")

# ══════════════════════════════════════════════════════════════════════════════
#  STORAGE
# ══════════════════════════════════════════════════════════════════════════════

DATA_DIR = "./sigma_data"
os.makedirs(DATA_DIR, exist_ok=True)

_FILES = {
    "sigma_daily_plans":      f"{DATA_DIR}/daily_plans.json",
    "sigma_daily_summaries":  f"{DATA_DIR}/daily_summaries.json",
    "sigma_weekly_plans":     f"{DATA_DIR}/weekly_plans.json",
    "sigma_weekly_summaries": f"{DATA_DIR}/weekly_summaries.json",
    "sigma_screened_stocks":  f"{DATA_DIR}/screened_stocks.json",
    "sigma_fundamental_data": f"{DATA_DIR}/fundamental_data.json",
    "sigma_alpha_history":    f"{DATA_DIR}/alpha_history.json",
    "sigma_track_record":     f"{DATA_DIR}/track_record.json",
}


def _read_json(path: str) -> list:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _write_json(path: str, data: list):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_all():
    """Load semua data dari file JSON ke session_state (hanya jika belum ada).
    Prioritas: session_state (dari DB user) > disk lokal."""
    for key, path in _FILES.items():
        if key not in st.session_state:
            # Coba load dari disk lokal (fallback)
            st.session_state[key] = _read_json(path)
        # sigma_track_record: jika disk punya data tapi DB tidak (atau sebaliknya), merge
        # Prioritas session_state yg sudah di-restore dari DB oleh app.py


def save_key(key: str):
    """Simpan satu key dari session_state ke file JSON."""
    if key in _FILES:
        _write_json(_FILES[key], st.session_state.get(key, []))
    # Untuk sigma_track_record: juga simpan ke user DB agar persist saat redeploy
    if key == "sigma_track_record":
        try:
            _user = st.session_state.get("user")
            if _user and _user.get("email"):
                # Import save_field dari app.py context (jika tersedia di builtins)
                import builtins
                _sf = getattr(builtins, "_sigma_save_field", None)
                if _sf:
                    _sf(_user["email"], "sigma_track_record", st.session_state.get("sigma_track_record", []))
        except Exception:
            pass


def save_all():
    """Simpan semua key ke file JSON."""
    for key, path in _FILES.items():
        _write_json(path, st.session_state.get(key, []))


def _get_all(key: str) -> list:
    return st.session_state.get(key, [])


def _upsert_by_date(key: str, entry: dict, date_field: str = "date_iso", max_records: int = 365):
    """Tambah / update entry berdasarkan date_field. Entry terbaru di index 0."""
    data = st.session_state.get(key, [])
    data = [d for d in data if d.get(date_field) != entry.get(date_field)]
    data.insert(0, entry)
    st.session_state[key] = data[:max_records]
    save_key(key)


def _append_screened_stock(stock: dict):
    """Upsert satu screened stock by ticker+date_iso."""
    data = st.session_state.get("sigma_screened_stocks", [])
    uid = f"{stock.get('ticker','')}_{stock.get('date_iso','')}"
    data = [d for d in data if f"{d.get('ticker','')}_{d.get('date_iso','')}" != uid]
    data.insert(0, stock)
    st.session_state["sigma_screened_stocks"] = data[:10_000]
    save_key("sigma_screened_stocks")


def _get_screened_by_date(date_iso: str) -> list:
    return [d for d in st.session_state.get("sigma_screened_stocks", [])
            if d.get("date_iso") == date_iso]


# ══════════════════════════════════════════════════════════════════════════════
#  DAILY PLAN — public API
# ══════════════════════════════════════════════════════════════════════════════

def append_daily_plan(rows: list, market_note: str = ""):
    """
    Simpan Trade Plan harian. Auto-dipanggil jam 20:00 WIB hari kerja.

    rows: list of dict — ticker, price, entry_low, entry_high,
          tp1, tp2, sl, rr, horizon, vol, rating, alasan
    """
    now = datetime.now(WIB)
    _upsert_by_date("sigma_daily_plans", {
        "date":          now.strftime("%d %b %Y"),
        "date_iso":      now.strftime("%Y-%m-%d"),
        "generated_at":  now.strftime("%d %b %Y, %H:%M") + " WIB",
        "session_label": "Sesi Malam (21:00)",
        "market_note":   market_note,
        "rows":          rows,
    }, max_records=365)


def append_daily_summary(stocks: list, market_note: str = ""):
    """
    Simpan History Summary top 10 saham harian.

    stocks: list of dict — ticker, name, price, ta_score, fa_score,
            combined, vol_spike, vol_type, rsi, macd, wyckoff, rating
    """
    now = datetime.now(WIB)
    top_score = max((s.get("combined", 0) for s in stocks), default=0)
    _upsert_by_date("sigma_daily_summaries", {
        "date":         now.strftime("%d %b %Y"),
        "date_iso":     now.strftime("%Y-%m-%d"),
        "generated_at": now.strftime("%H:%M") + " WIB",
        "market_note":  market_note,
        "top_score":    top_score,
        "tickers":      [s["ticker"] for s in stocks],
        "stocks":       stocks,
    }, max_records=365)


def check_and_auto_append_daily(generate_fn):
    """
    Cek jam 20:00+ WIB hari kerja, plan hari ini belum ada → panggil generate_fn().
    generate_fn() harus return {"rows": [...], "stocks": [...], "market_note": "..."}
    """
    now = datetime.now(WIB)
    if now.weekday() >= 5 or now.hour < 20:
        return False
    today_iso = now.strftime("%Y-%m-%d")
    if any(p["date_iso"] == today_iso for p in _get_all("sigma_daily_plans")):
        return False
    result = generate_fn()
    if result:
        append_daily_plan(result.get("rows", []), result.get("market_note", ""))
        append_daily_summary(result.get("stocks", []), result.get("market_note", ""))
    return True


# ══════════════════════════════════════════════════════════════════════════════
#  DAILY PLAN — render
# ══════════════════════════════════════════════════════════════════════════════

def render_daily_plan():
    """Entry point untuk tab Daily Plan."""
    sub_key = "daily_sub"
    if sub_key not in st.session_state:
        st.session_state[sub_key] = "plan"

    col1, col2 = st.columns(2)
    with col1:
        if st.button("📋 Trade Plan", key="daily_btn_plan", use_container_width=True,
                     type="primary" if st.session_state[sub_key] == "plan" else "secondary"):
            st.session_state[sub_key] = "plan"
            st.rerun()
    with col2:
        if st.button("📊 History Summary", key="daily_btn_summary", use_container_width=True,
                     type="primary" if st.session_state[sub_key] == "summary" else "secondary"):
            st.session_state[sub_key] = "summary"
            st.rerun()

    st.markdown("---")

    if st.session_state[sub_key] == "plan":
        _render_daily_trade_plan()
    else:
        _render_daily_history_summary()


def _render_daily_trade_plan():
    history = _get_all("sigma_daily_plans")
    if not history:
        st.info("📭 Belum ada Trade Plan.\n\nPlan pertama akan auto-generate setiap "
                "**Senin–Jumat jam 20:00 WIB**.\nData tersimpan permanen selama 1 tahun.")
        return

    today_iso = date.today().strftime("%Y-%m-%d")
    for entry in history:
        is_today = entry["date_iso"] == today_iso
        label = (f"📅 {entry['date']} — {entry.get('session_label','Sesi Malam (21:00)')}"
                 + ("  🟢 HARI INI" if is_today else ""))
        with st.expander(label, expanded=is_today):
            st.caption(f"🕐 Generated: {entry.get('generated_at','—')}")
            if entry.get("market_note"):
                st.info(f"💡 {entry['market_note']}")
            rows = entry.get("rows", [])
            if not rows:
                st.warning("Tidak ada data saham untuk hari ini.")
                continue
            df = pd.DataFrame(rows)
            col_order = ["ticker","price","entry_low","entry_high","tp1","tp2",
                         "sl","rr","horizon","vol","rating","alasan"]
            col_rename = {"ticker":"TICKER","price":"PRICE","entry_low":"ENTRY LOW",
                          "entry_high":"ENTRY HIGH","tp1":"TP1","tp2":"TP2","sl":"SL",
                          "rr":"RR","horizon":"HORIZON","vol":"VOL","rating":"RATING","alasan":"ALASAN"}
            cols = [c for c in col_order if c in df.columns]
            st.dataframe(df[cols].rename(columns=col_rename), use_container_width=True, hide_index=True)
            st.caption(f"📌 {len(rows)} saham · scroll kanan untuk semua kolom")


def _render_daily_history_summary():
    history = _get_all("sigma_daily_summaries")
    if not history:
        st.info("📭 Belum ada History Summary.\n\n"
                "Summary muncul setelah sistem melakukan analisis Top 10 harian.")
        return

    today_iso = date.today().strftime("%Y-%m-%d")
    for entry in history:
        is_today = entry["date_iso"] == today_iso
        label = (f"📊 {entry['date']} — Top Score: {entry.get('top_score','—')}"
                 + ("  🟢 HARI INI" if is_today else ""))
        with st.expander(label, expanded=is_today):
            st.caption(f"Generated {entry.get('generated_at','—')}  ·  "
                       f"{'  '.join(entry.get('tickers',[])[:10])}")
            if entry.get("market_note"):
                st.info(f"💡 {entry['market_note']}")
            for i, s in enumerate(entry.get("stocks", []), 1):
                _render_stock_card(i, s)


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED: stock card
# ══════════════════════════════════════════════════════════════════════════════

def _render_stock_card(rank: int, s: dict):
    vol_type = s.get("vol_type", "Normal")
    is_inst = "institusi" in vol_type.lower()
    rating = s.get("rating", "BUY")
    rating_color = "green" if rating == "BUY" else "red"
    combined = s.get("combined", "—")

    with st.container(border=True):
        hcol, scol = st.columns([4, 1])
        with hcol:
            st.markdown(
                f"**#{rank} {s.get('ticker','')}** &nbsp;"
                f"<span style='color:#888;font-size:12px'>{s.get('name','')}</span> &nbsp;"
                f"<span style='font-size:12px'>Rp {s.get('price','')}</span>",
                unsafe_allow_html=True)
        with scol:
            st.markdown(
                f"<div style='text-align:right'>"
                f"<span style='font-size:22px;font-weight:700;color:#7c6ff7'>{combined}</span>"
                f"<br><span style='font-size:9px;color:#666'>COMBINED</span>"
                f"<br><span style='color:{rating_color};font-weight:700;font-size:12px'>► {rating}</span>"
                f"</div>", unsafe_allow_html=True)
        c1,c2,c3,c4,c5,c6 = st.columns(6)
        c1.metric("TA",      s.get("ta_score","—"))
        c2.metric("FA",      s.get("fa_score","—"))
        c3.metric("Vol",     f"{s.get('vol_spike','—')}x")
        c4.metric("RSI",     s.get("rsi","—"))
        c5.metric("MACD",    s.get("macd","—"))
        c6.metric("Wyckoff", s.get("wyckoff","—"))
        st.caption(f"{'🟢' if is_inst else '⚪'} {vol_type}")


# ══════════════════════════════════════════════════════════════════════════════
#  WEEKLY PLAN — helpers
# ══════════════════════════════════════════════════════════════════════════════

def _week_label(dt: date) -> str:
    monday = dt - timedelta(days=dt.weekday())
    friday = monday + timedelta(days=4)
    if monday.month == friday.month:
        return f"Minggu {monday.day}–{friday.day} {monday.strftime('%b %Y')}"
    return f"Minggu {monday.strftime('%d %b')}–{friday.strftime('%d %b %Y')}"


def _week_iso(dt: date) -> str:
    return dt.strftime("%G-W%V")


def _get_week_screened(n_weeks: int = 2) -> list:
    today = date.today()
    result = []
    for days_back in range(n_weeks * 7):
        d = today - timedelta(days=days_back)
        result.extend(_get_screened_by_date(d.strftime("%Y-%m-%d")))
    seen = {}
    for s in result:
        tk = s.get("ticker", "")
        if tk and tk not in seen:
            seen[tk] = s
    return list(seen.values())


# ══════════════════════════════════════════════════════════════════════════════
#  WEEKLY PLAN — public API
# ══════════════════════════════════════════════════════════════════════════════

def append_weekly_plan(rows: list, analysis_note: str = "", n_weeks_data: int = 2):
    """
    Simpan Weekly Trade Plan. Auto-dipanggil setiap Sabtu jam 12:00 WIB.

    rows: list of dict — ticker, price, entry_low, entry_high, tp1, tp2, sl, rr,
          horizon, vol, acc_weeks, bandarmology_score, rating, alasan
    """
    now = datetime.now(WIB)
    today = now.date()
    _upsert_by_date("sigma_weekly_plans", {
        "week_iso":      _week_iso(today),
        "week_label":    _week_label(today),
        "date_iso":      today.strftime("%Y-%m-%d"),
        "generated_at":  now.strftime("%d %b %Y, %H:%M") + " WIB",
        "n_weeks_data":  n_weeks_data,
        "analysis_note": analysis_note,
        "rows":          rows,
    }, date_field="week_iso", max_records=104)


def append_weekly_summary(stocks: list, analysis_note: str = ""):
    """Simpan Weekly History Summary top saham mingguan."""
    now = datetime.now(WIB)
    today = now.date()
    top_score = max((s.get("bandarmology_score", s.get("combined", 0)) for s in stocks), default=0)
    _upsert_by_date("sigma_weekly_summaries", {
        "week_iso":      _week_iso(today),
        "week_label":    _week_label(today),
        "date_iso":      today.strftime("%Y-%m-%d"),
        "generated_at":  now.strftime("%H:%M") + " WIB",
        "analysis_note": analysis_note,
        "top_score":     top_score,
        "tickers":       [s["ticker"] for s in stocks],
        "stocks":        stocks,
    }, date_field="week_iso", max_records=104)


def check_and_auto_append_weekly(generate_fn):
    """
    Cek Sabtu jam 12:00+ WIB, plan minggu ini belum ada → panggil generate_fn(screened).
    generate_fn(screened_stocks) harus return {"rows":[...], "stocks":[...], "analysis_note":"..."}
    """
    now = datetime.now(WIB)
    if now.weekday() != 5 or now.hour < 12:
        return False
    week_iso = _week_iso(now.date())
    if any(p.get("week_iso") == week_iso for p in _get_all("sigma_weekly_plans")):
        return False
    result = generate_fn(_get_week_screened(n_weeks=2))
    if result:
        append_weekly_plan(result.get("rows", []), result.get("analysis_note", ""))
        append_weekly_summary(result.get("stocks", []), result.get("analysis_note", ""))
    return True


# ══════════════════════════════════════════════════════════════════════════════
#  WEEKLY PLAN — render
# ══════════════════════════════════════════════════════════════════════════════

def render_weekly_plan():
    """Entry point untuk tab Weekly Plan."""
    sub_key = "weekly_sub"
    if sub_key not in st.session_state:
        st.session_state[sub_key] = "plan"

    col1, col2 = st.columns(2)
    with col1:
        if st.button("📋 Trade Plan", key="weekly_btn_plan", use_container_width=True,
                     type="primary" if st.session_state[sub_key] == "plan" else "secondary"):
            st.session_state[sub_key] = "plan"
            st.rerun()
    with col2:
        if st.button("📊 History Summary", key="weekly_btn_summary", use_container_width=True,
                     type="primary" if st.session_state[sub_key] == "summary" else "secondary"):
            st.session_state[sub_key] = "summary"
            st.rerun()

    st.markdown("---")

    if st.session_state[sub_key] == "plan":
        _render_weekly_trade_plan()
    else:
        _render_weekly_history_summary()


def _render_weekly_trade_plan():
    history = _get_all("sigma_weekly_plans")
    if not history:
        st.info("📭 Belum ada Weekly Trade Plan.\n\n"
                "Plan pertama akan auto-generate setiap **Sabtu jam 12:00 WIB** "
                "berdasarkan akumulasi bandarmologi 2 minggu terakhir dari 30 saham aktif.\n\n"
                "Data tersimpan permanen.")
        return

    this_week = _week_iso(date.today())
    for entry in history:
        is_this = entry.get("week_iso") == this_week
        label = (f"📆 {entry.get('week_label', entry['date_iso'])}  ·  "
                 f"Data {entry.get('n_weeks_data',2)}W akumulasi"
                 + ("  🟢 MINGGU INI" if is_this else ""))
        with st.expander(label, expanded=is_this):
            st.caption(f"🕐 Generated: {entry.get('generated_at','—')}")
            if entry.get("analysis_note"):
                st.info(f"📊 {entry['analysis_note']}")
            rows = entry.get("rows", [])
            if not rows:
                st.warning("Tidak ada data untuk minggu ini.")
                continue
            df = pd.DataFrame(rows)
            col_order = ["ticker","price","entry_low","entry_high","tp1","tp2","sl","rr",
                         "horizon","acc_weeks","bandarmology_score","vol","rating","alasan"]
            col_rename = {"ticker":"TICKER","price":"PRICE","entry_low":"ENTRY LOW",
                          "entry_high":"ENTRY HIGH","tp1":"TP1","tp2":"TP2","sl":"SL",
                          "rr":"RR","horizon":"HORIZON","acc_weeks":"ACC WEEKS",
                          "bandarmology_score":"BANDARM SCORE","vol":"VOL",
                          "rating":"RATING","alasan":"ALASAN"}
            cols = [c for c in col_order if c in df.columns]
            st.dataframe(df[cols].rename(columns=col_rename), use_container_width=True, hide_index=True)
            st.caption(f"📌 {len(rows)} saham  ·  Timeframe: Swing/Struktural (1–4 minggu)")


def _render_weekly_history_summary():
    history = _get_all("sigma_weekly_summaries")
    if not history:
        st.info("📭 Belum ada Weekly History Summary.\n\n"
                "Summary muncul setelah sistem melakukan analisis Top Saham Mingguan.")
        return

    this_week = _week_iso(date.today())
    for entry in history:
        is_this = entry.get("week_iso") == this_week
        label = (f"📊 {entry.get('week_label', entry['date_iso'])} — "
                 f"Top Score: {entry.get('top_score','—')}"
                 + ("  🟢 MINGGU INI" if is_this else ""))
        with st.expander(label, expanded=is_this):
            st.caption(f"Generated {entry.get('generated_at','—')}  ·  "
                       f"{'  '.join(entry.get('tickers',[])[:10])}")
            if entry.get("analysis_note"):
                st.info(f"📊 {entry['analysis_note']}")
            for i, s in enumerate(entry.get("stocks", []), 1):
                _render_weekly_stock_card(i, s)


def _render_weekly_stock_card(rank: int, s: dict):
    vol_type = s.get("vol_type", "Normal")
    is_inst = "institusi" in vol_type.lower()
    rating = s.get("rating", "BUY")
    rating_color = "green" if rating == "BUY" else "red"
    score = s.get("bandarmology_score", s.get("combined", "—"))

    with st.container(border=True):
        hcol, scol = st.columns([4, 1])
        with hcol:
            st.markdown(
                f"**#{rank} {s.get('ticker','')}** &nbsp;"
                f"<span style='color:#888;font-size:12px'>{s.get('name','')}</span> &nbsp;"
                f"<span style='font-size:12px'>Rp {s.get('price','')}</span>",
                unsafe_allow_html=True)
        with scol:
            st.markdown(
                f"<div style='text-align:right'>"
                f"<span style='font-size:22px;font-weight:700;color:#2dd4a0'>{score}</span>"
                f"<br><span style='font-size:9px;color:#666'>BANDARM</span>"
                f"<br><span style='color:{rating_color};font-weight:700;font-size:12px'>► {rating}</span>"
                f"</div>", unsafe_allow_html=True)
        c1,c2,c3,c4,c5,c6 = st.columns(6)
        c1.metric("TA",      s.get("ta_score","—"))
        c2.metric("FA",      s.get("fa_score","—"))
        c3.metric("Acc Wks", s.get("acc_weeks","—"))
        c4.metric("RSI",     s.get("rsi","—"))
        c5.metric("MACD",    s.get("macd","—"))
        c6.metric("Horizon", s.get("horizon","Swing"))
        st.caption(f"{'🟢' if is_inst else '⚪'} {vol_type}  ·  {s.get('alasan','')}")


# ══════════════════════════════════════════════════════════════════════════════
#  FUNDAMENTAL SCREENER
# ══════════════════════════════════════════════════════════════════════════════

def append_fundamental_data(stocks: list):
    """
    Simpan hasil screening fundamental.

    stocks: list of dict — ticker, name, sector, pe_ratio, pb_ratio, roe, der,
            revenue_growth, profit_growth, div_yield, market_cap, score, rating, notes
    """
    now = datetime.now(WIB)
    _upsert_by_date("sigma_fundamental_data", {
        "date_iso":     now.strftime("%Y-%m-%d"),
        "date":         now.strftime("%d %b %Y"),
        "generated_at": now.strftime("%H:%M") + " WIB",
        "stocks":       stocks,
    }, max_records=365)


def render_fundamental_screener():
    """Entry point untuk tab Fundamental Screener."""
    st.markdown(
        "<div style='font-size:10px;font-weight:700;letter-spacing:1px;"
        "text-transform:uppercase;color:#2dd4a0;margin-bottom:8px'>"
        "🔍 FUNDAMENTAL SCREENER — IDX</div>",
        unsafe_allow_html=True)

    history = _get_all("sigma_fundamental_data")
    if not history:
        st.info("📭 Belum ada data Fundamental Screener.\n\n"
                "Data akan muncul setelah sistem melakukan screening fundamental saham IDX.")
        return

    dates = [e["date"] for e in history]
    selected = st.selectbox("📅 Pilih tanggal screening:", dates, index=0)
    entry = next((e for e in history if e["date"] == selected), None)
    if not entry:
        return

    st.caption(f"Generated: {entry.get('generated_at','—')}")
    stocks = entry.get("stocks", [])
    if not stocks:
        st.warning("Tidak ada data untuk tanggal ini.")
        return

    sectors = sorted(set(s.get("sector", "—") for s in stocks))
    sector_filter = st.multiselect("Filter Sektor:", sectors, default=sectors, key="funscreen_sector")
    filtered = [s for s in stocks if s.get("sector", "—") in sector_filter]

    col_r, col_sort = st.columns(2)
    with col_r:
        rating_filter = st.selectbox("Rating:", ["Semua","BUY","HOLD","SELL"], key="funscreen_rating")
    with col_sort:
        sort_by = st.selectbox("Sort by:", ["score","pe_ratio","roe","revenue_growth"], key="funscreen_sort")

    if rating_filter != "Semua":
        filtered = [s for s in filtered if s.get("rating") == rating_filter]
    if not filtered:
        st.warning("Tidak ada saham sesuai filter.")
        return

    filtered = sorted(filtered, key=lambda x: x.get(sort_by, 0) or 0, reverse=True)
    df = pd.DataFrame(filtered)
    col_order = ["ticker","name","sector","pe_ratio","pb_ratio","roe","der",
                 "revenue_growth","profit_growth","div_yield","market_cap","score","rating","notes"]
    col_rename = {"ticker":"TICKER","name":"NAMA","sector":"SEKTOR","pe_ratio":"P/E",
                  "pb_ratio":"P/B","roe":"ROE %","der":"DER","revenue_growth":"REV GROWTH %",
                  "profit_growth":"PROFIT GROWTH %","div_yield":"DIV YIELD %",
                  "market_cap":"MKTCAP (T)","score":"SCORE","rating":"RATING","notes":"NOTES"}
    cols = [c for c in col_order if c in df.columns]
    st.dataframe(df[cols].rename(columns=col_rename), use_container_width=True, hide_index=True)
    st.caption(f"📌 {len(filtered)} dari {len(stocks)} saham")


# ══════════════════════════════════════════════════════════════════════════════
#  ALPHA STOCK INSIGHT
# ══════════════════════════════════════════════════════════════════════════════

def append_alpha_insight(ticker: str, insight: dict):
    """
    Simpan hasil Alpha Insight untuk satu saham.

    insight: dict — name, price, date_iso, date, summary,
             bandarmology{net_buy,acc_days,dominant_broker,verdict},
             technical{trend,support,resistance,rsi,macd,wyckoff},
             fundamental{pe,pb,roe,der,sector_rank,fa_score},
             sentiment{news_score,social_score,catalyst},
             recommendation{action,entry,tp1,tp2,sl,rr,horizon},
             ai_note, sources
    """
    now = datetime.now(WIB)
    entry = {
        "ticker":       ticker.upper(),
        "date_iso":     insight.get("date_iso", now.strftime("%Y-%m-%d")),
        "date":         insight.get("date", now.strftime("%d %b %Y")),
        "generated_at": now.strftime("%H:%M") + " WIB",
        **insight,
    }
    uid = f"{ticker.upper()}_{entry['date_iso']}"
    data = st.session_state.get("sigma_alpha_history", [])
    data = [d for d in data if f"{d.get('ticker','')}_{d.get('date_iso','')}" != uid]
    data.insert(0, entry)
    st.session_state["sigma_alpha_history"] = data[:1000]
    save_key("sigma_alpha_history")


def render_alpha_stock_insight():
    """Entry point untuk tab Alpha Stock Insight."""
    st.markdown(
        "<div style='font-size:10px;font-weight:700;letter-spacing:1px;"
        "text-transform:uppercase;color:#f0d060;margin-bottom:8px'>"
        "⚡ ALPHA STOCK INSIGHT — AI DEEP ANALYSIS</div>",
        unsafe_allow_html=True)

    history = _get_all("sigma_alpha_history")

    col_search, col_date = st.columns([2, 1])
    with col_search:
        search_ticker = st.text_input("🔎 Cari Ticker:", placeholder="BBRI, GOTO, TLKM...",
                                      key="alpha_search").upper().strip()
    with col_date:
        dates = sorted(set(e.get("date") for e in history if e.get("date")), reverse=True)
        selected_date = st.selectbox("📅 Filter Tanggal:", ["Semua"] + dates, key="alpha_date")

    filtered = history
    if search_ticker:
        filtered = [e for e in filtered if search_ticker in e.get("ticker", "")]
    if selected_date != "Semua":
        filtered = [e for e in filtered if e.get("date") == selected_date]

    if not filtered:
        if not history:
            st.info("📭 Belum ada Alpha Stock Insight.\n\n"
                    "Insight muncul setelah AI menganalisis saham secara mendalam.")
        else:
            st.warning("Tidak ada insight untuk ticker/tanggal yang dipilih.")
        return

    st.caption(f"📌 {len(filtered)} insight ditemukan")
    for entry in filtered:
        _render_alpha_card(entry)


def _render_alpha_card(e: dict):
    rec = e.get("recommendation", {})
    action = rec.get("action", "—")
    action_color = {"BUY": "green", "SELL": "red", "HOLD": "#f0d060"}.get(action, "#888")
    label = f"⚡ {e.get('ticker','')}  ·  {e.get('name','')}  ·  Rp {e.get('price','—')}  ·  {e.get('date','')}"

    with st.expander(label, expanded=False):
        st.caption(f"Generated {e.get('generated_at','—')}")
        if e.get("summary"):
            st.markdown(f"> {e['summary']}")

        if rec:
            c1,c2,c3,c4,c5 = st.columns(5)
            c1.metric("Action",  action)
            c2.metric("Entry",   f"Rp {rec.get('entry','—')}")
            c3.metric("TP1",     f"Rp {rec.get('tp1','—')}")
            c4.metric("SL",      f"Rp {rec.get('sl','—')}")
            c5.metric("Horizon", rec.get("horizon","—"))

        st.markdown("---")
        tab_b, tab_t, tab_f, tab_s, tab_ai = st.tabs([
            "🏦 Bandarmologi","📈 Technical","📋 Fundamental","📡 Sentiment","🤖 AI Note"])

        with tab_b:
            b = e.get("bandarmology", {})
            if b:
                c1,c2,c3,c4 = st.columns(4)
                c1.metric("Net Buy",     b.get("net_buy","—"))
                c2.metric("Acc Days",    b.get("acc_days","—"))
                c3.metric("Dom Broker",  b.get("dominant_broker","—"))
                c4.metric("Verdict",     b.get("verdict","—"))
            else:
                st.caption("Data bandarmologi belum tersedia.")

        with tab_t:
            t = e.get("technical", {})
            if t:
                c1,c2,c3 = st.columns(3)
                c1.metric("Trend",      t.get("trend","—"))
                c2.metric("Support",    f"Rp {t.get('support','—')}")
                c3.metric("Resistance", f"Rp {t.get('resistance','—')}")
                c4,c5,c6 = st.columns(3)
                c4.metric("RSI",     t.get("rsi","—"))
                c5.metric("MACD",    t.get("macd","—"))
                c6.metric("Wyckoff", t.get("wyckoff","—"))
            else:
                st.caption("Data teknikal belum tersedia.")

        with tab_f:
            f = e.get("fundamental", {})
            if f:
                c1,c2,c3,c4 = st.columns(4)
                c1.metric("P/E",         f.get("pe","—"))
                c2.metric("P/B",         f.get("pb","—"))
                c3.metric("ROE %",       f.get("roe","—"))
                c4.metric("Sector Rank", f.get("sector_rank","—"))
            else:
                st.caption("Data fundamental belum tersedia.")

        with tab_s:
            s = e.get("sentiment", {})
            if s:
                c1,c2 = st.columns(2)
                c1.metric("News Score",   s.get("news_score","—"))
                c2.metric("Social Score", s.get("social_score","—"))
                if s.get("catalyst"):
                    st.info(f"🔔 Catalyst: {s['catalyst']}")
            else:
                st.caption("Data sentiment belum tersedia.")

        with tab_ai:
            ai_note = e.get("ai_note", "")
            if ai_note:
                st.markdown(ai_note)
            else:
                st.caption("AI Note belum tersedia.")
            sources = e.get("sources", [])
            if sources:
                st.caption("Sumber: " + "  ·  ".join(sources))


# ══════════════════════════════════════════════════════════════════════════════
#  BROKER SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

def save_broker_screening_result(stocks: list):
    """
    Simpan hasil screening broker GoAPI. Dipanggil setelah screening selesai.

    stocks: list of dict — ticker, name, sector, price,
            net_buy_1d, net_buy_3d, net_buy_5d, acc_buy_lot, dist_sell_lot,
            dominant_broker, dominant_type, bpr_score, bandarmology_score,
            vol_spike, vol_type, verdict, date_iso
    """
    now = datetime.now(WIB)
    today_iso = now.strftime("%Y-%m-%d")
    for s in stocks:
        if "date_iso" not in s:
            s["date_iso"] = today_iso
        if "date" not in s:
            s["date"] = now.strftime("%d %b %Y")
        _append_screened_stock(s)


def render_broker_summary():
    """Entry point untuk tab Broker Summary."""
    st.markdown(
        "<div style='font-size:10px;font-weight:700;letter-spacing:1px;"
        "text-transform:uppercase;color:#7c6ff7;margin-bottom:8px'>"
        "🏦 BROKER SUMMARY — BANDARMOLOGI SCREENING</div>",
        unsafe_allow_html=True)

    today_iso = date.today().strftime("%Y-%m-%d")
    today_stocks = _get_screened_by_date(today_iso)

    col1,col2,col3,col4 = st.columns(4)
    col1.metric("🟢 Total Screened", len(today_stocks))
    col2.metric("📈 Akumulasi",
                len([s for s in today_stocks if "kumulasi" in s.get("verdict","").lower()]))
    col3.metric("📉 Distribusi",
                len([s for s in today_stocks if "istribusi" in s.get("verdict","").lower()]))
    col4.metric("⚪ Netral",
                len([s for s in today_stocks if "etral" in s.get("verdict","").lower()]))

    st.markdown("---")

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        period = st.selectbox("📅 Periode:", ["1D","3D","5D"], key="broksum_period")
    with col_f2:
        verdict_filter = st.selectbox("Verdict:", ["Semua","Akumulasi","Distribusi","Netral"],
                                      key="broksum_verdict")
    with col_f3:
        search_bs = st.text_input("🔎 Cari Ticker:", key="broksum_search",
                                  placeholder="BBRI...").upper().strip()

    all_screened = _get_all("sigma_screened_stocks")
    available_dates = sorted(set(s.get("date_iso","") for s in all_screened), reverse=True)
    if not available_dates:
        st.info("📭 Belum ada data Broker Summary.\n\n"
                "Jalankan screening untuk mulai menyimpan data bandarmologi.\n"
                "Data akan terus tersimpan dan dipakai oleh Weekly Plan & Alpha Insight.")
        return

    selected_date = st.selectbox("📅 Lihat data tanggal:", available_dates,
                                 index=0, key="broksum_date")
    stocks = _get_screened_by_date(selected_date)

    if verdict_filter != "Semua":
        stocks = [s for s in stocks if verdict_filter.lower() in s.get("verdict","").lower()]
    if search_bs:
        stocks = [s for s in stocks if search_bs in s.get("ticker","").upper()]
    if not stocks:
        st.warning("Tidak ada data sesuai filter untuk tanggal ini.")
        return

    stocks = sorted(stocks, key=lambda x: x.get("bandarmology_score", 0) or 0, reverse=True)

    akum = [s for s in stocks if "kumulasi" in s.get("verdict","").lower()]
    dist = [s for s in stocks if "istribusi" in s.get("verdict","").lower()]

    if akum:
        st.markdown("#### 📈 Saham Akumulasi")
        _render_broker_grid(akum, period)
    if dist:
        st.markdown("#### 📉 Saham Distribusi")
        _render_broker_grid(dist, period)

    with st.expander("📋 Tabel Detail Broker Flow", expanded=False):
        _render_broker_table(stocks, period)

    ai_key = f"broksum_ai_{selected_date}"
    if st.session_state.get(ai_key):
        with st.expander("🤖 AI Market Insight", expanded=True):
            st.markdown(st.session_state[ai_key])


def _net_buy_field(period: str) -> str:
    return {"1D":"net_buy_1d","3D":"net_buy_3d","5D":"net_buy_5d"}.get(period, "net_buy_1d")


def _render_broker_grid(stocks: list, period: str):
    nb_field = _net_buy_field(period)
    cols = st.columns(2)
    for i, s in enumerate(stocks[:20]):
        nb = s.get(nb_field, 0) or 0
        nb_str = f"+{nb:,.0f}" if nb >= 0 else f"{nb:,.0f}"
        is_acc = "kumulasi" in s.get("verdict","").lower()
        bc = "#2dd4a0" if is_acc else "#ff5c5c"
        with cols[i % 2]:
            st.markdown(
                f"<div style='border:1px solid {bc}33;border-left:3px solid {bc};"
                f"border-radius:4px;padding:8px 10px;margin-bottom:6px;"
                f"background:rgba(255,255,255,0.02)'>"
                f"<div style='font-weight:700;font-size:13px'>{s.get('ticker','')}</div>"
                f"<div style='font-size:10px;color:#888;margin-bottom:4px'>{s.get('name','')}</div>"
                f"<div style='display:flex;justify-content:space-between'>"
                f"<span style='font-size:11px;color:#888'>Net {period}</span>"
                f"<span style='font-size:11px;font-weight:700;color:{bc}'>{nb_str}</span></div>"
                f"<div style='display:flex;justify-content:space-between;margin-top:2px'>"
                f"<span style='font-size:10px;color:#888'>BPR</span>"
                f"<span style='font-size:11px;color:#a89cf7'>{s.get('bpr_score','—')}</span></div>"
                f"<div style='display:flex;justify-content:space-between;margin-top:2px'>"
                f"<span style='font-size:10px;color:#888'>Vol Spike</span>"
                f"<span style='font-size:11px;color:#e8e8f5'>{s.get('vol_spike','—')}x</span></div>"
                f"</div>",
                unsafe_allow_html=True)


def _render_broker_table(stocks: list, period: str):
    nb_field = _net_buy_field(period)
    rows = [{
        "TICKER":       s.get("ticker",""),
        "NAMA":         s.get("name",""),
        "PRICE":        s.get("price",""),
        f"NET {period}":s.get(nb_field, 0),
        "BPR":          s.get("bpr_score",""),
        "DOM BROKER":   s.get("dominant_broker",""),
        "VOL SPIKE":    s.get("vol_spike",""),
        "VOL TYPE":     s.get("vol_type",""),
        "VERDICT":      s.get("verdict",""),
        "SCORE":        s.get("bandarmology_score",""),
    } for s in stocks]
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TRACK RECORD
# ══════════════════════════════════════════════════════════════════════════════

def record_trade_result(result: dict):
    """
    Simpan hasil satu trade.

    result: dict — ticker, name, plan_type ("daily"/"weekly"), plan_date_iso,
            entry_price, exit_price, exit_date_iso, tp_hit (1/2/None),
            sl_hit (True/False), return_pct (float), profit_loss, horizon_actual, notes
    """
    now = datetime.now(WIB)
    uid = f"{result.get('ticker','')}_{result.get('plan_date_iso','')}"
    entry = {
        **result,
        "recorded_at": now.strftime("%Y-%m-%d %H:%M"),
        "date_iso":    result.get("exit_date_iso", now.strftime("%Y-%m-%d")),
    }
    data = st.session_state.get("sigma_track_record", [])
    data = [d for d in data if f"{d.get('ticker','')}_{d.get('plan_date_iso','')}" != uid]
    data.insert(0, entry)
    st.session_state["sigma_track_record"] = data
    save_key("sigma_track_record")


def render_track_record():
    """Entry point untuk tab Track Record."""
    st.markdown(
        "<div style='font-size:10px;font-weight:700;letter-spacing:1px;"
        "text-transform:uppercase;color:#f0d060;margin-bottom:8px'>"
        "📈 TRACK RECORD — HASIL AKTUAL TRADE</div>",
        unsafe_allow_html=True)

    data = _get_all("sigma_track_record")
    if not data:
        st.info("📭 Belum ada Track Record.\n\nData muncul setelah hasil trade dicatat ke sistem.")
        return

    total     = len(data)
    wins      = len([d for d in data if (d.get("return_pct") or 0) > 0])
    win_rate  = (wins / total * 100) if total else 0
    returns   = [d.get("return_pct") or 0 for d in data]
    avg_ret   = sum(returns) / len(returns) if returns else 0
    tp_hits   = len([d for d in data if d.get("tp_hit")])
    sl_hits   = len([d for d in data if d.get("sl_hit")])

    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("Total Trade", total)
    c2.metric("Win Rate",    f"{win_rate:.1f}%")
    c3.metric("Avg Return",  f"{avg_ret:+.2f}%")
    c4.metric("TP Hit",      tp_hits)
    c5.metric("SL Hit",      sl_hits)

    st.markdown("---")

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        pt_filter = st.selectbox("Plan Type:", ["Semua","daily","weekly"], key="tr_plan_type")
    with col_f2:
        res_filter = st.selectbox("Hasil:", ["Semua","Win","Loss","TP Hit","SL Hit"], key="tr_result")
    with col_f3:
        search_tr = st.text_input("🔎 Ticker:", key="tr_search",
                                  placeholder="BBRI...").upper().strip()

    filtered = data
    if pt_filter != "Semua":
        filtered = [d for d in filtered if d.get("plan_type") == pt_filter]
    if res_filter == "Win":
        filtered = [d for d in filtered if (d.get("return_pct") or 0) > 0]
    elif res_filter == "Loss":
        filtered = [d for d in filtered if (d.get("return_pct") or 0) < 0]
    elif res_filter == "TP Hit":
        filtered = [d for d in filtered if d.get("tp_hit")]
    elif res_filter == "SL Hit":
        filtered = [d for d in filtered if d.get("sl_hit")]
    if search_tr:
        filtered = [d for d in filtered if search_tr in d.get("ticker","").upper()]

    if not filtered:
        st.warning("Tidak ada data sesuai filter.")
        return

    rows = [{
        "TICKER":    d.get("ticker",""),
        "PLAN TYPE": d.get("plan_type","").upper(),
        "PLAN DATE": d.get("plan_date_iso",""),
        "ENTRY":     d.get("entry_price",""),
        "EXIT":      d.get("exit_price",""),
        "EXIT DATE": d.get("exit_date_iso",""),
        "RETURN %":  f"{(d.get('return_pct') or 0):+.2f}%",
        "TP HIT":    d.get("tp_hit","—"),
        "SL HIT":    "✓" if d.get("sl_hit") else "—",
        "HOLD DAYS": d.get("horizon_actual","—"),
        "NOTES":     d.get("notes",""),
    } for d in filtered]

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(f"📌 {len(filtered)} trade ditampilkan")

    if len(filtered) >= 2:
        with st.expander("📊 Chart Return Kumulatif", expanded=False):
            cum, cum_rets = 0, []
            for r in [d.get("return_pct") or 0 for d in reversed(filtered)]:
                cum += r
                cum_rets.append(cum)
            st.line_chart(pd.DataFrame({
                "Return Kumulatif (%)": cum_rets
            }, index=range(1, len(cum_rets)+1)))
