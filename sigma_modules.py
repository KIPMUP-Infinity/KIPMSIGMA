# ═══════════════════════════════════════════════════════════════════════
# SIGMA MODULES v5 — Persistent Storage + Full UI Render
# Storage: JSON lokal (./sigma_data/) + Google Sheets (via sigma_sheets)
# UI    : render_daily_plan, render_weekly_plan, render_broker_summary,
#         render_track_record, render_fundamental_screener, render_alpha_stock_insight
# by MnM Strategy+ / KIPM-UP
# ═══════════════════════════════════════════════════════════════════════

import json
import os
from datetime import datetime, date, timedelta

try:
    import pytz
    WIB = pytz.timezone("Asia/Jakarta")
except ImportError:
    WIB = None

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sigma_data")
os.makedirs(DATA_DIR, exist_ok=True)

# ── In-memory store ──────────────────────────────────────────────────
_store = {
    "auto_plan":        {},   # {plan_type: {slot_key: data}}
    "daily_plans":      [],
    "daily_summaries":  [],
    "weekly_plans":     [],
    "weekly_summaries": [],
    "broker_results":   [],
    "screened_stocks":  [],
    "fundamental_data": [],
    "alpha_history":    [],
    "track_record":     [],
}

_MAX_HISTORY = 365
_MAX_BROKER  = 60
_MAX_WEEKLY  = 104

# ═══════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS — Local JSON
# ═══════════════════════════════════════════════════════════════════════

def _local_path(name: str) -> str:
    return os.path.join(DATA_DIR, f"sm_{name}.json")


def _local_save(name: str, data) -> bool:
    try:
        with open(_local_path(name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def _local_load(name: str):
    try:
        p = _local_path(name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS — Google Sheets (optional)
# ═══════════════════════════════════════════════════════════════════════

def _sheets_write(key: str, value) -> bool:
    try:
        from sigma_sheets import _write
        return _write("sigma_modules", key, value)
    except Exception:
        return False


def _sheets_read(key: str):
    try:
        from sigma_sheets import _load_sheet
        data = _load_sheet("sigma_modules")
        return data.get(key)
    except Exception:
        return None


def _save(name: str, data):
    """Simpan ke lokal + Google Sheets (fire-and-forget untuk Sheets)."""
    _local_save(name, data)
    try:
        _sheets_write(name, data)
    except Exception:
        pass


def _load_from_any(name: str):
    """Load dari Sheets dulu, fallback lokal."""
    try:
        from_sheets = _sheets_read(name)
        if from_sheets is not None:
            return from_sheets
    except Exception:
        pass
    return _local_load(name)


def _now_wib() -> datetime:
    """Return datetime sekarang dalam WIB (atau UTC jika pytz tidak tersedia)."""
    if WIB:
        return datetime.now(WIB)
    return datetime.now()


# ═══════════════════════════════════════════════════════════════════════
# WEEK HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _week_iso(dt: date) -> str:
    return dt.strftime("%G-W%V")


def _week_label(dt: date) -> str:
    monday = dt - timedelta(days=dt.weekday())
    friday = monday + timedelta(days=4)
    if monday.month == friday.month:
        return f"Minggu {monday.day}–{friday.day} {monday.strftime('%b %Y')}"
    return f"Minggu {monday.strftime('%d %b')}–{friday.strftime('%d %b %Y')}"


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API — load_all (dipanggil saat startup)
# ═══════════════════════════════════════════════════════════════════════

def load_all():
    """Load semua data tersimpan ke _store (in-memory). Dipanggil sekali saat startup."""
    for name in list(_store.keys()):
        val = _load_from_any(name)
        if val is not None:
            _store[name] = val


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API — Auto Plan Storage
# ═══════════════════════════════════════════════════════════════════════

def save_auto_plan(plan_type: str, slot_key: str, data) -> bool:
    """
    Simpan satu slot auto plan.
    plan_type : 'daily' | 'weekly' | 'bsjp'
    slot_key  : identifier slot (e.g. '2026-05-01')
    data      : dict berisi list saham + metadata plan
    """
    if plan_type not in _store["auto_plan"]:
        _store["auto_plan"][plan_type] = {}
    _store["auto_plan"][plan_type][slot_key] = data
    # Batasi 90 slot per plan_type
    slots = _store["auto_plan"][plan_type]
    if len(slots) > 90:
        for k in sorted(slots.keys())[:-90]:
            del slots[k]
    _save("auto_plan", _store["auto_plan"])
    return True


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API — Daily Plan
# ═══════════════════════════════════════════════════════════════════════

def append_daily_plan(rows: list, outlook: str = "") -> bool:
    """
    Append snapshot daily plan ke history.
    rows: list of dict — ticker, price, entry_low, entry_high,
          tp1, tp2, sl, rr, horizon, vol, rating, alasan
    """
    now = _now_wib()
    today_iso = now.strftime("%Y-%m-%d")

    # Upsert: hapus entry hari yang sama agar tidak duplikat
    _store["daily_plans"] = [e for e in _store["daily_plans"] if e.get("date_iso") != today_iso]
    _store["daily_plans"].insert(0, {
        "rows":         rows,
        "outlook":      outlook,
        "date":         now.strftime("%d %b %Y"),
        "date_iso":     today_iso,
        "generated_at": now.strftime("%d %b %Y, %H:%M") + " WIB",
        "saved_at":     now.isoformat(),
    })
    _store["daily_plans"] = _store["daily_plans"][:_MAX_HISTORY]
    _save("daily_plans", _store["daily_plans"])
    return True


def append_daily_summary(rows: list, outlook: str = "") -> bool:
    """Append summary daily plan."""
    now = _now_wib()
    today_iso = now.strftime("%Y-%m-%d")
    _store["daily_summaries"] = [e for e in _store["daily_summaries"] if e.get("date_iso") != today_iso]
    _store["daily_summaries"].insert(0, {
        "rows":      rows,
        "outlook":   outlook,
        "date":      now.strftime("%d %b %Y"),
        "date_iso":  today_iso,
        "top_score": max((r.get("combined", r.get("ta_score", 0)) or 0 for r in rows), default=0),
        "tickers":   [r.get("ticker", "") for r in rows],
        "saved_at":  now.isoformat(),
    })
    _store["daily_summaries"] = _store["daily_summaries"][:_MAX_HISTORY]
    _save("daily_summaries", _store["daily_summaries"])
    return True


def render_daily_plan(limit: int = 10):
    """Render tabel daily plan history di Streamlit."""
    try:
        import streamlit as st
        import pandas as pd

        sub_key = "sm_daily_sub"
        if sub_key not in st.session_state:
            st.session_state[sub_key] = "plan"

        col1, col2 = st.columns(2)
        with col1:
            if st.button("📋 Trade Plan", key="sm_daily_btn_plan", use_container_width=True,
                         type="primary" if st.session_state[sub_key] == "plan" else "secondary"):
                st.session_state[sub_key] = "plan"
                st.rerun()
        with col2:
            if st.button("📊 History Summary", key="sm_daily_btn_summary", use_container_width=True,
                         type="primary" if st.session_state[sub_key] == "summary" else "secondary"):
                st.session_state[sub_key] = "summary"
                st.rerun()

        st.markdown("---")

        plans = _store["daily_plans" if st.session_state[sub_key] == "plan" else "daily_summaries"]
        if not plans:
            st.info("📭 Belum ada Daily Plan tersimpan. Plan akan otomatis tersimpan setiap kali di-generate.")
            return

        today_iso = date.today().strftime("%Y-%m-%d")
        for entry in plans[:limit]:
            is_today = entry.get("date_iso") == today_iso
            label = f"📅 {entry.get('date', entry.get('date_iso', 'N/A'))}" + (" 🟢 HARI INI" if is_today else "")
            with st.expander(label, expanded=is_today):
                st.caption(f"🕐 Generated: {entry.get('generated_at', entry.get('saved_at', '—'))}")
                if entry.get("outlook"):
                    st.info(f"💡 {entry['outlook']}")
                rows = entry.get("rows", [])
                if rows:
                    col_order = ["ticker", "price", "entry_low", "entry_high", "tp1", "tp2",
                                 "sl", "rr", "horizon", "vol", "rating", "alasan"]
                    col_rename = {
                        "ticker": "TICKER", "price": "PRICE", "entry_low": "ENTRY LOW",
                        "entry_high": "ENTRY HIGH", "tp1": "TP1", "tp2": "TP2", "sl": "SL",
                        "rr": "RR", "horizon": "HORIZON", "vol": "VOL",
                        "rating": "RATING", "alasan": "ALASAN"
                    }
                    df = pd.DataFrame(rows)
                    cols = [c for c in col_order if c in df.columns]
                    st.dataframe(df[cols].rename(columns=col_rename),
                                 use_container_width=True, hide_index=True)
                    st.caption(f"📌 {len(rows)} saham")
                else:
                    st.info("Tidak ada data baris plan.")
    except Exception as e:
        try:
            import streamlit as st
            st.warning(f"Tidak bisa render daily plan: {e}")
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API — Weekly Plan
# ═══════════════════════════════════════════════════════════════════════

def append_weekly_plan(rows: list, outlook: str = "") -> bool:
    """
    Append snapshot weekly plan ke history.
    rows: list of dict — ticker, price, entry_low, entry_high, tp1, tp2, sl, rr,
          horizon, acc_weeks, bandarmology_score, vol, rating, alasan
    """
    now = _now_wib()
    today = now.date() if hasattr(now, 'date') else date.today()
    week_iso = _week_iso(today)

    _store["weekly_plans"] = [e for e in _store["weekly_plans"] if e.get("week_iso") != week_iso]
    _store["weekly_plans"].insert(0, {
        "rows":         rows,
        "outlook":      outlook,
        "date":         now.strftime("%d %b %Y"),
        "date_iso":     today.strftime("%Y-%m-%d"),
        "week_iso":     week_iso,
        "week_label":   _week_label(today),
        "generated_at": now.strftime("%d %b %Y, %H:%M") + " WIB",
        "saved_at":     now.isoformat(),
    })
    _store["weekly_plans"] = _store["weekly_plans"][:_MAX_WEEKLY]
    _save("weekly_plans", _store["weekly_plans"])
    return True


def append_weekly_summary(rows: list, outlook: str = "") -> bool:
    """Append summary weekly plan."""
    now = _now_wib()
    today = now.date() if hasattr(now, 'date') else date.today()
    week_iso = _week_iso(today)

    _store["weekly_summaries"] = [e for e in _store["weekly_summaries"] if e.get("week_iso") != week_iso]
    _store["weekly_summaries"].insert(0, {
        "rows":      rows,
        "outlook":   outlook,
        "date":      now.strftime("%d %b %Y"),
        "date_iso":  today.strftime("%Y-%m-%d"),
        "week_iso":  week_iso,
        "week_label": _week_label(today),
        "top_score": max((r.get("bandarmology_score", r.get("combined", 0)) or 0 for r in rows), default=0),
        "tickers":   [r.get("ticker", "") for r in rows],
        "saved_at":  now.isoformat(),
    })
    _store["weekly_summaries"] = _store["weekly_summaries"][:_MAX_WEEKLY]
    _save("weekly_summaries", _store["weekly_summaries"])
    return True


def render_weekly_plan(limit: int = 10):
    """Render tabel weekly plan history di Streamlit."""
    try:
        import streamlit as st
        import pandas as pd

        sub_key = "sm_weekly_sub"
        if sub_key not in st.session_state:
            st.session_state[sub_key] = "plan"

        col1, col2 = st.columns(2)
        with col1:
            if st.button("📋 Trade Plan", key="sm_weekly_btn_plan", use_container_width=True,
                         type="primary" if st.session_state[sub_key] == "plan" else "secondary"):
                st.session_state[sub_key] = "plan"
                st.rerun()
        with col2:
            if st.button("📊 History Summary", key="sm_weekly_btn_summary", use_container_width=True,
                         type="primary" if st.session_state[sub_key] == "summary" else "secondary"):
                st.session_state[sub_key] = "summary"
                st.rerun()

        st.markdown("---")

        plans = _store["weekly_plans" if st.session_state[sub_key] == "plan" else "weekly_summaries"]
        if not plans:
            st.info("📭 Belum ada Weekly Plan tersimpan. Plan akan otomatis tersimpan setiap kali di-generate.")
            return

        this_week = _week_iso(date.today())
        for entry in plans[:limit]:
            is_this = entry.get("week_iso") == this_week
            label_date = entry.get("week_label", entry.get("date", entry.get("date_iso", "N/A")))
            label = f"📆 {label_date}" + (" 🟢 MINGGU INI" if is_this else "")
            with st.expander(label, expanded=is_this):
                st.caption(f"🕐 Generated: {entry.get('generated_at', entry.get('saved_at', '—'))}")
                if entry.get("outlook"):
                    st.info(f"💡 {entry['outlook']}")
                rows = entry.get("rows", [])
                if rows:
                    col_order = ["ticker", "price", "entry_low", "entry_high", "tp1", "tp2", "sl", "rr",
                                 "horizon", "acc_weeks", "bandarmology_score", "vol", "rating", "alasan"]
                    col_rename = {
                        "ticker": "TICKER", "price": "PRICE", "entry_low": "ENTRY LOW",
                        "entry_high": "ENTRY HIGH", "tp1": "TP1", "tp2": "TP2", "sl": "SL",
                        "rr": "RR", "horizon": "HORIZON", "acc_weeks": "ACC WEEKS",
                        "bandarmology_score": "BANDARM SCORE", "vol": "VOL",
                        "rating": "RATING", "alasan": "ALASAN"
                    }
                    df = pd.DataFrame(rows)
                    cols = [c for c in col_order if c in df.columns]
                    st.dataframe(df[cols].rename(columns=col_rename),
                                 use_container_width=True, hide_index=True)
                    st.caption(f"📌 {len(rows)} saham · Timeframe: Swing/Struktural (1–4 minggu)")
                else:
                    st.info("Tidak ada data baris plan.")
    except Exception as e:
        try:
            import streamlit as st
            st.warning(f"Tidak bisa render weekly plan: {e}")
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API — Broker Screening Result
# ═══════════════════════════════════════════════════════════════════════

def save_broker_screening_result(top30: list) -> bool:
    """
    Simpan hasil broker screening (top30 list).
    Dipanggil setelah BS30 selesai dijalankan.
    stocks: list of dict — ticker, name, sector, price,
            net_buy_1d, net_buy_3d, net_buy_5d, acc_buy_lot, dist_sell_lot,
            dominant_broker, dominant_type, bpr_score, bandarmology_score,
            vol_spike, vol_type, verdict, date_iso
    """
    now = _now_wib()
    today_iso = now.strftime("%Y-%m-%d")

    # Simpan ke screened_stocks (per ticker+date, untuk weekly plan)
    for s in top30:
        if "date_iso" not in s:
            s["date_iso"] = today_iso
        if "date" not in s:
            s["date"] = now.strftime("%d %b %Y")
        uid = f"{s.get('ticker', '')}_{s.get('date_iso', '')}"
        _store["screened_stocks"] = [d for d in _store["screened_stocks"]
                                      if f"{d.get('ticker','')}_{d.get('date_iso','')}" != uid]
        _store["screened_stocks"].insert(0, s)
    _store["screened_stocks"] = _store["screened_stocks"][:10_000]
    _save("screened_stocks", _store["screened_stocks"])

    # Simpan juga sebagai snapshot broker_results
    entry = {
        "top30":    top30,
        "count":    len(top30),
        "date":     now.strftime("%d %b %Y"),
        "date_iso": today_iso,
        "saved_at": now.isoformat(),
    }
    _store["broker_results"] = [e for e in _store["broker_results"] if e.get("date_iso") != today_iso]
    _store["broker_results"].insert(0, entry)
    _store["broker_results"] = _store["broker_results"][:_MAX_BROKER]
    _save("broker_results", _store["broker_results"])
    return True


def get_latest_broker_result() -> list:
    """Return hasil broker screening terbaru."""
    if _store["broker_results"]:
        return _store["broker_results"][0].get("top30", [])
    return []


def get_screened_by_date(date_iso: str) -> list:
    """Return screened stocks untuk tanggal tertentu."""
    return [d for d in _store["screened_stocks"] if d.get("date_iso") == date_iso]


def get_week_screened(n_weeks: int = 2) -> list:
    """Return screened stocks n_weeks terakhir (untuk Weekly Plan)."""
    today = date.today()
    result = []
    for days_back in range(n_weeks * 7):
        d = today - timedelta(days=days_back)
        result.extend(get_screened_by_date(d.strftime("%Y-%m-%d")))
    seen = {}
    for s in result:
        tk = s.get("ticker", "")
        if tk and tk not in seen:
            seen[tk] = s
    return list(seen.values())


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API — Track Record
# ═══════════════════════════════════════════════════════════════════════

def record_trade_result(result: dict) -> bool:
    """
    Simpan hasil satu trade.
    result: dict — ticker, name, plan_type ('daily'/'weekly'), plan_date_iso,
            entry_price, exit_price, exit_date_iso, tp_hit (1/2/None),
            sl_hit (True/False), return_pct (float), profit_loss, horizon_actual, notes
    """
    now = _now_wib()
    uid = f"{result.get('ticker', '')}_{result.get('plan_date_iso', '')}"
    entry = {
        **result,
        "recorded_at": now.strftime("%Y-%m-%d %H:%M"),
        "date_iso": result.get("exit_date_iso", now.strftime("%Y-%m-%d")),
    }
    _store["track_record"] = [d for d in _store["track_record"]
                               if f"{d.get('ticker','')}_{d.get('plan_date_iso','')}" != uid]
    _store["track_record"].insert(0, entry)
    _store["track_record"] = _store["track_record"][:_MAX_HISTORY]
    _save("track_record", _store["track_record"])
    return True


def render_track_record():
    """Render Track Record di Streamlit."""
    try:
        import streamlit as st
        import pandas as pd

        st.markdown(
            "<div style='font-size:10px;font-weight:700;letter-spacing:1px;"
            "text-transform:uppercase;color:#f0d060;margin-bottom:8px'>"
            "📈 TRACK RECORD — HASIL AKTUAL TRADE</div>",
            unsafe_allow_html=True)

        data = _store["track_record"]
        if not data:
            st.info("📭 Belum ada Track Record. Data muncul setelah hasil trade dicatat ke sistem.")
            return

        total  = len(data)
        wins   = len([d for d in data if (d.get("return_pct") or 0) > 0])
        win_rate = (wins / total * 100) if total else 0
        returns  = [d.get("return_pct") or 0 for d in data]
        avg_ret  = sum(returns) / len(returns) if returns else 0
        tp_hits  = len([d for d in data if d.get("tp_hit")])
        sl_hits  = len([d for d in data if d.get("sl_hit")])

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Trade", total)
        c2.metric("Win Rate",    f"{win_rate:.1f}%")
        c3.metric("Avg Return",  f"{avg_ret:+.2f}%")
        c4.metric("TP Hit",      tp_hits)
        c5.metric("SL Hit",      sl_hits)

        st.markdown("---")

        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            pt_filter = st.selectbox("Plan Type:", ["Semua", "daily", "weekly"], key="tr_plan_type")
        with col_f2:
            res_filter = st.selectbox("Hasil:", ["Semua", "Win", "Loss", "TP Hit", "SL Hit"], key="tr_result")
        with col_f3:
            search_tr = st.text_input("🔎 Ticker:", key="tr_search", placeholder="BBRI...").upper().strip()

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
            filtered = [d for d in filtered if search_tr in d.get("ticker", "").upper()]

        if not filtered:
            st.warning("Tidak ada data sesuai filter.")
            return

        rows = [{
            "TICKER":    d.get("ticker", ""),
            "PLAN TYPE": d.get("plan_type", "").upper(),
            "PLAN DATE": d.get("plan_date_iso", ""),
            "ENTRY":     d.get("entry_price", ""),
            "EXIT":      d.get("exit_price", ""),
            "EXIT DATE": d.get("exit_date_iso", ""),
            "RETURN %":  f"{(d.get('return_pct') or 0):+.2f}%",
            "TP HIT":    d.get("tp_hit", "—"),
            "SL HIT":    "✓" if d.get("sl_hit") else "—",
            "HOLD DAYS": d.get("horizon_actual", "—"),
            "NOTES":     d.get("notes", ""),
        } for d in filtered]

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption(f"📌 {len(filtered)} trade ditampilkan")

        if len(filtered) >= 2:
            with st.expander("📊 Chart Return Kumulatif", expanded=False):
                cum, cum_rets = 0, []
                for r in [d.get("return_pct") or 0 for d in reversed(filtered)]:
                    cum += r
                    cum_rets.append(cum)
                st.line_chart(pd.DataFrame(
                    {"Return Kumulatif (%)": cum_rets},
                    index=range(1, len(cum_rets) + 1)
                ))
    except Exception as e:
        try:
            import streamlit as st
            st.warning(f"Tidak bisa render track record: {e}")
        except Exception:
            pass
