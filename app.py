"""
SIGMA AI — Trade Plan & Signal Board Component
Paste fungsi-fungsi ini ke dalam app.py kamu.

Struktur:
  - render_tradeplan_tab()     → dipanggil di tab "Trade Plan"
  - _render_plan_subtab()      → sub-tab: Trade Plan (tabel harian)
  - _render_signalboard_subtab() → sub-tab: Signal Board (card top 10)
  - append_daily_plan()        → dipanggil scheduler / tombol generate
  - append_daily_summary()     → dipanggil setelah AI generate top 10
"""

import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, date, timedelta
import json
import pytz

WIB = pytz.timezone("Asia/Jakarta")


# ─────────────────────────────────────────────
#  DATA HELPERS
# ─────────────────────────────────────────────

def _init_state():
    """Pastikan session_state punya key yang diperlukan."""
    if "trade_plan_history" not in st.session_state:
        st.session_state["trade_plan_history"] = _demo_plan_data()
    if "signal_board_history" not in st.session_state:
        st.session_state["signal_board_history"] = _demo_signal_data()


def append_daily_plan(rows: list[dict], session_label: str = "Sesi Malam (21:00)"):
    """
    Tambah satu entry Trade Plan baru.
    Dipanggil otomatis jam 20:00 WIB hari kerja, atau setelah generate.

    rows: list of dict, tiap dict berisi:
        ticker, price, entry_low, entry_high, tp1, tp2, sl, rr,
        horizon, vol, rating, alasan
    session_label: label sesi (default "Sesi Malam (21:00)")
    """
    _init_state()
    now = datetime.now(WIB)
    entry = {
        "date": now.strftime("%d %b %Y"),
        "date_iso": now.strftime("%Y-%m-%d"),
        "generated_at": now.strftime("%d %b %Y, %H:%M") + " WIB",
        "session_label": session_label,
        "rows": rows,
    }
    history = st.session_state["trade_plan_history"]
    # Cegah duplikasi: hapus entry tanggal yang sama jika ada
    history = [h for h in history if h["date_iso"] != entry["date_iso"]]
    history.insert(0, entry)
    # Simpan max 30 hari kerja (~6 minggu)
    st.session_state["trade_plan_history"] = history[:30]


def append_daily_summary(stocks: list[dict]):
    """
    Tambah satu entry Signal Board baru (top 10 saham hari ini).

    stocks: list of dict, tiap dict berisi:
        ticker, name, price, ta_score, fa_score, combined,
        vol_spike, vol_type, rsi, macd, wyckoff, rating
    """
    _init_state()
    now = datetime.now(WIB)
    entry = {
        "date": now.strftime("%d %b %Y"),
        "date_iso": now.strftime("%Y-%m-%d"),
        "generated_at": now.strftime("%H:%M") + " WIB",
        "top_score": max((s.get("combined", 0) for s in stocks), default=0),
        "tickers": [s["ticker"] for s in stocks],
        "stocks": stocks,
    }
    history = st.session_state["signal_board_history"]
    history = [h for h in history if h["date_iso"] != entry["date_iso"]]
    history.insert(0, entry)
    st.session_state["signal_board_history"] = history[:30]


# ─────────────────────────────────────────────
#  MAIN RENDER
# ─────────────────────────────────────────────

def render_tradeplan_tab():
    """Entry point — panggil ini di dalam tab Trade Plan di app.py."""
    _init_state()

    sub = st.session_state.get("tradeplan_sub", "plan")

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "📋 Trade Plan",
            use_container_width=True,
            type="primary" if sub == "plan" else "secondary",
        ):
            st.session_state["tradeplan_sub"] = "plan"
            st.rerun()
    with col2:
        if st.button(
            "📡 Signal Board",
            use_container_width=True,
            type="primary" if sub == "signal" else "secondary",
        ):
            st.session_state["tradeplan_sub"] = "signal"
            st.rerun()

    st.markdown("---")

    if sub == "plan":
        _render_plan_subtab()
    else:
        _render_signalboard_subtab()


# ─────────────────────────────────────────────
#  SUB-TAB: TRADE PLAN
# ─────────────────────────────────────────────

def _render_plan_subtab():
    history = st.session_state.get("trade_plan_history", [])
    if not history:
        st.info("Belum ada Trade Plan. Plan pertama akan muncul jam 21:00 WIB hari kerja.")
        return

    today_iso = date.today().strftime("%Y-%m-%d")

    for entry in history:
        is_today = entry["date_iso"] == today_iso
        label = f"📅 {entry['date']} — {entry['session_label']}"
        badge = " 🟢 HARI INI" if is_today else ""

        with st.expander(label + badge, expanded=is_today):
            st.caption(f"🕐 Generated: {entry['generated_at']}")

            if entry.get("market_note"):
                st.info(f"💡 {entry['market_note']}")

            rows = entry.get("rows", [])
            if rows:
                import pandas as pd
                df = pd.DataFrame(rows)
                # Rename kolom untuk display
                col_map = {
                    "ticker": "TICKER", "price": "PRICE",
                    "entry_low": "ENTRY LOW", "entry_high": "ENTRY HIGH",
                    "tp1": "TP1", "tp2": "TP2", "sl": "SL",
                    "rr": "RR", "horizon": "HORIZON",
                    "vol": "VOL", "rating": "RATING", "alasan": "ALASAN",
                }
                df = df.rename(columns=col_map)
                # Tampilkan kolom yang ada saja
                cols_show = [v for v in col_map.values() if v in df.columns]
                st.dataframe(
                    df[cols_show],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.warning("Tidak ada data saham untuk hari ini.")


# ─────────────────────────────────────────────
#  SUB-TAB: SIGNAL BOARD
# ─────────────────────────────────────────────

def _render_signalboard_subtab():
    history = st.session_state.get("signal_board_history", [])
    if not history:
        st.info("Belum ada Signal Board. Data muncul setelah generate Daily Top 10.")
        return

    today_iso = date.today().strftime("%Y-%m-%d")

    for entry in history:
        is_today = entry["date_iso"] == today_iso
        tickers_str = "  ".join(entry.get("tickers", [])[:10])
        badge = " 🟢 HARI INI" if is_today else ""
        label = f"📊 {entry['date']} — Top Score: {entry['top_score']}{badge}"

        with st.expander(label, expanded=is_today):
            st.caption(f"Generated {entry['generated_at']}  ·  {tickers_str}")

            for i, s in enumerate(entry.get("stocks", []), 1):
                _render_signal_card(i, s)


def _render_signal_card(rank: int, s: dict):
    """Render satu card saham di Signal Board."""
    vol_type = s.get("vol_type", "Normal")
    is_inst = "nstitusi" in vol_type or "nstitution" in vol_type

    with st.container(border=True):
        col_left, col_right = st.columns([3, 1])

        with col_left:
            st.markdown(
                f"**#{rank} {s.get('ticker','')}** "
                f"<span style='font-size:12px;color:#888'>{s.get('name','')}</span> "
                f"<span style='font-size:12px'>Rp {s.get('price','')}</span>",
                unsafe_allow_html=True,
            )
            c1, c2, c3 = st.columns(3)
            c1.metric("TA", s.get("ta_score", "-"))
            c2.metric("FA", s.get("fa_score", "-"))
            c3.metric("Vol", f"{s.get('vol_spike','-')}x")

            c4, c5, c6 = st.columns(3)
            c4.metric("RSI", s.get("rsi", "-"))
            c5.metric("MACD", s.get("macd", "-"))
            c6.metric("Wyckoff", s.get("wyckoff", "-"))

            vol_color = "🟢" if is_inst else "⚪"
            st.caption(f"{vol_color} {vol_type}")

        with col_right:
            st.metric("Combined", s.get("combined", "-"))
            rating = s.get("rating", "BUY")
            color = "green" if rating == "BUY" else "red"
            st.markdown(
                f"<div style='text-align:center;"
                f"color:{color};font-weight:700;font-size:14px'>"
                f"► {rating}</div>",
                unsafe_allow_html=True,
            )


# ─────────────────────────────────────────────
#  DEMO DATA (hapus setelah data real tersedia)
# ─────────────────────────────────────────────

def _demo_plan_data():
    return [
        {
            "date": "20 Apr 2026",
            "date_iso": "2026-04-20",
            "generated_at": "20 Apr 2026, 11:56 WIB",
            "session_label": "Sesi Malam (21:00)",
            "market_note": "Pasar daily cenderung bullish (+14.3% avg top picks). Fokus block trade konfirmasi.",
            "rows": [
                {"ticker":"KICI","price":"258","entry_low":"191","entry_high":"258","tp1":"268","tp2":"276","sl":"112","rr":"0.1x","horizon":"Intraday","vol":"4.0x","rating":"BUY","alasan":"Vol spike 4.0x · BullScore tinggi · +34.4%"},
                {"ticker":"PRIM","price":"77","entry_low":"70","entry_high":"77","tp1":"80","tp2":"82","sl":"58","rr":"0.2x","horizon":"Intraday","vol":"3.3x","rating":"BUY","alasan":"Vol spike 3.3x · BullScore tinggi · +8.4%"},
                {"ticker":"YULE","price":"3.400","entry_low":"3.370","entry_high":"3.410","tp1":"3.550","tp2":"3.650","sl":"3.250","rr":"0.9x","horizon":"Intraday","vol":"4.8x","rating":"BUY","alasan":"Vol spike 4.8x · BullScore tinggi"},
                {"ticker":"ASJT","price":"193","entry_low":"187","entry_high":"193","tp1":"200","tp2":"206","sl":"180","rr":"0.5x","horizon":"1-3 hari","vol":"2.5x","rating":"BUY","alasan":"BullScore tinggi · +2.7% hari ini"},
                {"ticker":"TBLA","price":"750","entry_low":"720","entry_high":"750","tp1":"780","tp2":"800","sl":"670","rr":"0.4x","horizon":"1-3 hari","vol":"1.6x","rating":"BUY","alasan":"BullScore tinggi · +3.5% hari ini"},
            ],
        },
        {
            "date": "17 Apr 2026",
            "date_iso": "2026-04-17",
            "generated_at": "17 Apr 2026, 20:01 WIB",
            "session_label": "Sesi Malam (21:00)",
            "rows": [
                {"ticker":"GOTO","price":"74","entry_low":"70","entry_high":"74","tp1":"78","tp2":"82","sl":"65","rr":"0.4x","horizon":"Intraday","vol":"3.1x","rating":"BUY","alasan":"Vol spike 3.1x · Breakout level"},
                {"ticker":"BRIS","price":"1.560","entry_low":"1.520","entry_high":"1.560","tp1":"1.620","tp2":"1.680","sl":"1.440","rr":"0.5x","horizon":"1-3 hari","vol":"2.8x","rating":"BUY","alasan":"Akumulasi institusi · MACD bullish"},
                {"ticker":"TLKM","price":"2.820","entry_low":"2.760","entry_high":"2.820","tp1":"2.920","tp2":"3.000","sl":"2.660","rr":"0.6x","horizon":"1-3 hari","vol":"1.9x","rating":"BUY","alasan":"Support kuat · RSI recovery"},
            ],
        },
        {
            "date": "16 Apr 2026",
            "date_iso": "2026-04-16",
            "generated_at": "16 Apr 2026, 20:02 WIB",
            "session_label": "Sesi Malam (21:00)",
            "rows": [
                {"ticker":"BBRI","price":"4.100","entry_low":"4.020","entry_high":"4.100","tp1":"4.240","tp2":"4.350","sl":"3.880","rr":"0.6x","horizon":"1-3 hari","vol":"2.2x","rating":"BUY","alasan":"MACD golden cross · Vol konfirmasi"},
                {"ticker":"MDKA","price":"1.840","entry_low":"1.800","entry_high":"1.840","tp1":"1.920","tp2":"1.980","sl":"1.720","rr":"0.7x","horizon":"Intraday","vol":"3.6x","rating":"BUY","alasan":"Vol spike 3.6x · Wyckoff markup"},
            ],
        },
    ]


def _demo_signal_data():
    return [
        {
            "date": "20 Apr 2026",
            "date_iso": "2026-04-20",
            "generated_at": "11:56 WIB",
            "top_score": 88.8,
            "tickers": ["KICI","YULE","PRIM","ASJT","TBLA"],
            "stocks": [
                {"ticker":"KICI","name":"KICI","price":"258","ta_score":95,"fa_score":55,"combined":86.1,"vol_spike":4.0,"vol_type":"Mixed / Institusi","rsi":97.6,"macd":"Bullish X","wyckoff":"Markup 65%","rating":"BUY"},
                {"ticker":"YULE","name":"YULE","price":"3.400","ta_score":95,"fa_score":55,"combined":88.8,"vol_spike":4.8,"vol_type":"Mixed / Institusi","rsi":46.3,"macd":"Mendekati","wyckoff":"Accum 55%","rating":"BUY"},
                {"ticker":"PRIM","name":"PRIM","price":"77","ta_score":95,"fa_score":55,"combined":83.4,"vol_spike":3.3,"vol_type":"Mixed / Institusi","rsi":55.4,"macd":"Bullish X","wyckoff":"Markup 65%","rating":"BUY"},
                {"ticker":"ASJT","name":"ASJT","price":"193","ta_score":95,"fa_score":55,"combined":80.9,"vol_spike":2.5,"vol_type":"Mixed / Institusi","rsi":51.5,"macd":"Bullish X","wyckoff":"Accum 55%","rating":"BUY"},
                {"ticker":"TBLA","name":"TBLA","price":"750","ta_score":94,"fa_score":55,"combined":77.6,"vol_spike":1.6,"vol_type":"Normal","rsi":50.2,"macd":"Bullish X","wyckoff":"Accum 55%","rating":"BUY"},
            ],
        },
        {
            "date": "17 Apr 2026",
            "date_iso": "2026-04-17",
            "generated_at": "20:01 WIB",
            "top_score": 84.2,
            "tickers": ["GOTO","BRIS","TLKM"],
            "stocks": [
                {"ticker":"GOTO","name":"GOTO","price":"74","ta_score":91,"fa_score":55,"combined":84.2,"vol_spike":3.1,"vol_type":"Institusi","rsi":61.2,"macd":"Bullish X","wyckoff":"Markup 60%","rating":"BUY"},
                {"ticker":"BRIS","name":"BRIS","price":"1.560","ta_score":88,"fa_score":58,"combined":80.1,"vol_spike":2.8,"vol_type":"Institusi","rsi":58.7,"macd":"Bullish X","wyckoff":"Accum 60%","rating":"BUY"},
            ],
        },
    ]


# ─────────────────────────────────────────────
#  AUTO-APPEND SCHEDULER (opsional)
#  Taruh di bagian atas app.py, sebelum render tab
# ─────────────────────────────────────────────

def maybe_auto_append(generate_fn):
    """
    Cek apakah sudah jam 20:00+ WIB hari kerja dan plan hari ini
    belum ada. Jika ya, panggil generate_fn() untuk dapat rows,
    lalu append otomatis.

    Cara pakai di app.py:
        def my_generate():
            # panggil AI / logic kamu, return list of row dicts
            return [...]

        maybe_auto_append(my_generate)
        render_tradeplan_tab()
    """
    _init_state()
    now = datetime.now(WIB)
    today_iso = now.strftime("%Y-%m-%d")
    is_weekday = now.weekday() < 5  # Senin–Jumat
    is_after_8pm = now.hour >= 20

    if not is_weekday or not is_after_8pm:
        return

    existing = [h for h in st.session_state["trade_plan_history"] if h["date_iso"] == today_iso]
    if existing:
        return  # Sudah ada hari ini, skip

    rows = generate_fn()
    if rows:
        append_daily_plan(rows)
