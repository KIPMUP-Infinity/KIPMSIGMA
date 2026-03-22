import streamlit as st
from groq import Groq
import fitz
import base64
from PIL import Image
import io
import streamlit.components.v1 as components
import uuid
from datetime import datetime
import requests
from urllib.parse import urlencode
import json
import os
import hashlib
import bcrypt

# ─────────────────────────────────────────────
# MULTI-SOURCE DATA — semua dalam thread daemon
# ─────────────────────────────────────────────
import re as _re

SKIP_WORDS = {"YANG","ATAU","DARI","PADA","UNTUK","DENGAN","SAYA","MINTA",
              "TOLONG","ANALISA","SAHAM","MOHON","BISA","FUNDAMENTAL",
              "ANALISIS","HARI","INI","TREN","TAHUN","APAKAH","BAGAIMANA"}

def _fetch_all_data(tickers):
    """Fetch harga + berita untuk semua ticker, return dalam 10 detik."""
    import threading
    result = {"prices": {}, "news": []}

    def fetch():
        # Fetch berita umum dulu (selalu)
        try:
            import feedparser
            seen = set()
            # Berita umum pasar modal Indonesia
            general_sources = [
                ("CNBC ID", "https://www.cnbcindonesia.com/rss"),
                ("Kontan", "https://rss.kontan.co.id/category/investasi"),
                ("Bisnis", "https://ekonomi.bisnis.com/rss"),
            ]
            mkt_kw = ["ihsg","saham","bursa","ekonomi","rupiah","bi rate",
                      "inflasi","pasar","investor","emiten","perang","global"]
            for src_name, src_url in general_sources:
                try:
                    feed = feedparser.parse(src_url)
                    count = 0
                    for e in feed.entries:
                        if count >= 2: break
                        title = e.title.strip()
                        key = title[:30].lower()
                        if key not in seen and any(k in title.lower() for k in mkt_kw):
                            seen.add(key)
                            result["news"].append(f"[{src_name}] {title}")
                            count += 1
                except: pass
        except: pass

        # Fetch harga saham jika ada ticker
        try:
            import yfinance as yf
            for tk in tickers[:3]:
                try:
                    t = yf.Ticker(f"{tk}.JK")
                    h = t.history(period="2d")
                    if not h.empty:
                        info = t.info
                        last = h.iloc[-1]
                        prev = h.iloc[-2] if len(h)>1 else last
                        chg = ((last["Close"]-prev["Close"])/prev["Close"]*100) if prev["Close"] else 0
                        result["prices"][tk] = {
                            "price": round(last["Close"],0),
                            "chg": round(chg,2),
                            "pe": info.get("trailingPE"),
                            "pbv": info.get("priceToBook"),
                            "eps": info.get("trailingEps"),
                            "roe": info.get("returnOnEquity"),
                        }
                except: pass
        except: pass

        try:
            import feedparser
            seen = set()
            sources = [
                ("Google", f"https://news.google.com/rss/search?q={requests.utils.quote(tickers[0]+' saham IDX')}&hl=id&gl=ID&ceid=ID:id") if tickers else None,
                ("CNBC ID", "https://www.cnbcindonesia.com/rss"),
                ("Kontan", "https://rss.kontan.co.id/category/investasi"),
                ("Bisnis", "https://ekonomi.bisnis.com/rss"),
            ]
            kw = [t.lower() for t in tickers] + ["ihsg","saham","bursa","emiten"]
            for src in sources:
                if not src: continue
                try:
                    feed = feedparser.parse(src[1])
                    count = 0
                    for e in feed.entries:
                        if count >= 3: break
                        title = e.title.strip()
                        key = title[:30].lower()
                        if key in seen: continue
                        if src[0] == "Google" or any(k in title.lower() for k in kw):
                            seen.add(key)
                            result["news"].append(f"[{src[0]}] {title}")
                            count += 1
                except: pass
        except: pass

    th = threading.Thread(target=fetch, daemon=True)
    th.start()
    th.join(timeout=10)
    return result

def build_context(prompt):
    """Build market context untuk inject ke prompt."""
    tickers = [t for t in _re.findall(r'\b([A-Z]{4})\b', prompt.upper())
               if t not in SKIP_WORDS][:3]

    _kw = ["analisa","saham","ihsg","entry","beli","jual","teknikal",
           "fundamental","harga","support","resistance","chart","bandar",
           "volume","breakout","bias","valuasi","berita","news","update",
           "perang","ekonomi","inflasi","suku bunga","bi rate","rupiah",
           "dolar","market","pasar","investor","bursa","emiten","dividen",
           "ipo","right issue","buyback","ojk","bei","idx","makro",
           "global","china","amerika","fed","trump","tarif","ekspor","impor"]
    _p = prompt.lower()
    _has_ticker = bool(tickers)
    # Pertanyaan dengan ticker atau keyword ekonomi/pasar → inject context
    # Pertanyaan sangat umum (hai, bantu tugas, dll) → tidak perlu context berita
    _general_only = ["hai","halo","selamat","terima kasih","makasih","oke","ok",
                     "tugas","pr ","essay","rangkum","jelaskan","apa itu","pengertian"]
    _is_general_chat = any(k in _p for k in _general_only) and not _has_ticker
    _is_relevant = (_has_ticker or any(k in _p for k in _kw)) and not _is_general_chat

    if not _is_relevant:
        return ""

    data = _fetch_all_data(tickers)
    lines = [f"Tanggal: {datetime.now().strftime('%d %B %Y %H:%M WIB')}"]

    # Harga
    for tk, d in data["prices"].items():
        arah = "▲" if d["chg"] >= 0 else "▼"
        line = f"{tk}: Rp{d['price']:,.0f} {arah}{abs(d['chg']):.2f}%"
        if d.get("pe"): line += f" | PER:{d['pe']:.1f}x"
        if d.get("pbv"): line += f" | PBV:{d['pbv']:.1f}x"
        if d.get("roe"): line += f" | ROE:{d['roe']*100:.1f}%"
        lines.append(line)

    # Berita
    if data["news"]:
        lines.append("Berita terkini:")
        lines.extend(data["news"][:6])

    return "\n".join(lines) if len(lines) > 1 else ""


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="KIPM SIGMA",
    layout="wide",
    initial_sidebar_state="expanded"
)

DATA_DIR = ".sigma_data"
os.makedirs(DATA_DIR, exist_ok=True)

# ─────────────────────────────────────────────
# PERSISTENCE
# ─────────────────────────────────────────────
def _ukey(email): return hashlib.md5(email.encode()).hexdigest()

def save_user(email, data):
    try:
        with open(os.path.join(DATA_DIR, f"{_ukey(email)}.json"), "w") as f:
            json.dump(data, f, ensure_ascii=False)
    except: pass

def load_user(email):
    try:
        p = os.path.join(DATA_DIR, f"{_ukey(email)}.json")
        if os.path.exists(p):
            with open(p) as f: return json.load(f)
    except: pass
    return None

# Username/password auth
def get_accounts():
    p = os.path.join(DATA_DIR, "accounts.json")
    if os.path.exists(p):
        with open(p) as f: return json.load(f)
    return {}

def save_accounts(acc):
    with open(os.path.join(DATA_DIR, "accounts.json"), "w") as f:
        json.dump(acc, f)

def register_user(username, password, display_name):
    acc = get_accounts()
    if username in acc: return False, "Username sudah dipakai"
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    acc[username] = {"password": hashed, "display_name": display_name, "email": f"{username}@local"}
    save_accounts(acc)
    return True, "Berhasil daftar"

def login_user(username, password):
    acc = get_accounts()
    if username not in acc: return None
    if bcrypt.checkpw(password.encode(), acc[username]["password"].encode()):
        return {"email": acc[username]["email"], "name": acc[username]["display_name"], "picture": ""}
    return None

# ─────────────────────────────────────────────
# THEME COLORS
# ─────────────────────────────────────────────
def get_colors(theme="dark"):
    dark = theme == "dark"
    return {
        "bg":           "#212121" if dark else "#f0f0f0",
        "sidebar_bg":   "#171717" if dark else "#e3e3e3",
        "text":         "#ececec" if dark else "#0d0d0d",
        "text_muted":   "#8e8ea0" if dark else "#6e6e80",
        "border":       "#2f2f2f" if dark else "#d0d0d0",
        "hover":        "#2f2f2f" if dark else "#d0d0d0",
        "input_bg":     "#2f2f2f" if dark else "#ffffff",
        "bubble":       "#1B2A4A",
        "bubble_text":  "#ffffff",
        "divider":      "#2f2f2f" if dark else "#d0d0d0",
        "gold":         "#F5C242",
        "active_bg":    "#2f2f2f" if dark else "#c8c8c8",
    }

# ─────────────────────────────────────────────
# SESSION INIT
# ─────────────────────────────────────────────
def init_session():
    defaults = {
        "user": None,
        "theme": "dark",
        "data_loaded": False,
        "sessions": None,
        "active_id": None,
        "rename_id": None,
        "img_data": None,
        "pdf_data": None,
        "show_settings": False,
        "auth_mode": "login",  # login | register | google
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session()

# Proses delete PALING AWAL sebelum apapun — termasuk sebelum sigma_token restore
if "del" in st.query_params:
    _del_sid = st.query_params.get("del", "")
    st.write(f"DEBUG del param: '{_del_sid}'")  # debug sementara
    if _del_sid:
        # Load user data dari token jika belum ada
        if st.session_state.user is None:
            _tok = st.query_params.get("sigma_token", "")
            if _tok:
                _tfile = os.path.join(DATA_DIR, f"token_{_tok}.json")
                if os.path.exists(_tfile):
                    try:
                        with open(_tfile) as _f:
                            _uinfo = json.load(_f)
                        st.session_state.user = _uinfo
                        _saved = load_user(_uinfo["email"])
                        if _saved and _saved.get("sessions"):
                            st.session_state.sessions = _saved["sessions"]
                            st.session_state.active_id = _saved.get("active_id")
                        st.session_state.data_loaded = True
                    except: pass
        # Hapus session
        if st.session_state.sessions:
            delete_session(_del_sid)
            # Simpan ke disk
            if st.session_state.user:
                _sv = []
                for _s in st.session_state.sessions:
                    _msgs = [dict(m) for m in _s["messages"] if m["role"] != "system"]
                    _sv.append({"id": _s["id"], "title": _s["title"],
                                "created": _s["created"], "messages": _msgs})
                save_user(st.session_state.user["email"], {
                    "theme": st.session_state.get("theme", "dark"),
                    "sessions": _sv,
                    "active_id": st.session_state.active_id,
                })
        st.query_params.pop("del")
        st.rerun()

C = get_colors(st.session_state.theme)

# ─────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────
SYSTEM_PROMPT = {
    "role": "system",
    "content": """Kamu adalah SIGMA — asisten cerdas dari KIPM Universitas Pancasila, by Market n Mocha (MnM).

IDENTITAS:
Kamu adalah teman yang sangat pintar, berpengalaman luas, dan selalu siap membantu siapa saja dengan topik apapun. Kamu bukan hanya analis saham — kamu adalah asisten lengkap yang bisa diandalkan.

KEPRIBADIAN:
- Selalu ramah, hangat, dan natural dalam percakapan biasa
- Saat diminta analisa atau penjelasan teknis → profesional, tajam, terstruktur
- Bahasa Indonesia yang natural dan mudah dipahami
- Empati — pahami konteks pertanyaan sebelum menjawab
- Jangan langsung jejalkan data teknis saat user hanya menyapa

KEMAMPUAN UTAMA:

1. TRADING & PASAR MODAL
- Analisa teknikal: IFVG, FVG, Order Block, Supply & Demand, EMA 13/21/50
- Bandarmologi: akumulasi/distribusi, delta volume, anomali
- Analisa fundamental: ROE, ROA, NIM, NPL, CAR, BOPO, LDR, PER, PBV
- Berita pasar, sentimen market, geopolitik yang mempengaruhi saham

2. EKONOMI & BISNIS
- Makroekonomi: inflasi, suku bunga, kebijakan moneter, fiskal
- Mikroekonomi: penawaran, permintaan, elastisitas, pasar
- Geopolitik: perang dagang, sanksi, hubungan internasional dan dampaknya ke market
- Bisnis: strategi, manajemen, pemasaran, operasional, keuangan perusahaan
- Akuntansi: laporan keuangan, jurnal, neraca, laba rugi, arus kas
- Investasi: saham, obligasi, reksa dana, properti, kripto

3. PENDIDIKAN & TUGAS
- Bantu mengerjakan tugas kuliah/sekolah semua mata pelajaran
- Jelaskan konsep dengan cara yang mudah dipahami
- Buat rangkuman, essay, laporan, presentasi
- Analisa kasus bisnis dan ekonomi
- Matematika, statistika, riset

4. UMUM
- Jawab pertanyaan apapun dengan jujur dan informatif
- Berikan solusi praktis untuk masalah sehari-hari
- Diskusi ide, brainstorming, creative thinking

FORMAT TRADE PLAN (saat diminta analisa teknikal saham):
📊 TRADE PLAN — [SAHAM] ([TIMEFRAME])
⚡ Bias: [Bullish/Bearish/Sideways]
🎯 Entry: [harga]
🛑 Stop Loss: [harga]
✅ Target 1: [harga]
✅ Target 2: [harga]
📦 Bandarmologi: [ringkasan volume & aksi bandar]
⚠️ Invalidasi: [kondisi]
⚠️ DYOR — bukan rekomendasi investasi

FRAKSI HARGA BEI (wajib untuk semua harga saham IDX):
- < Rp200: tick Rp1 | Rp200-500: tick Rp2 | Rp500-2.000: tick Rp5
- Rp2.000-5.000: tick Rp10 | > Rp5.000: tick Rp25

ATURAN:
- Jawab Bahasa Indonesia kecuali user pakai bahasa lain
- Gambar/chart masuk → analisa teknikal langsung
- PDF laporan keuangan masuk → analisa fundamental langsung
- Selalu berikan jawaban yang berguna dan actionable
- Untuk topik di luar keahlian → tetap bantu sebaik mungkin"""
}

# ─────────────────────────────────────────────
# CHAT SESSION HELPERS
# ─────────────────────────────────────────────
def new_session():
    return {
        "id": str(uuid.uuid4())[:8],
        "title": "Obrolan Baru",
        "messages": [SYSTEM_PROMPT],
        "created": datetime.now().strftime("%d/%m %H:%M")
    }

def init_chat():
    if not st.session_state.sessions:
        s = new_session()
        st.session_state.sessions = [s]
        st.session_state.active_id = s["id"]
    else:
        for s in st.session_state.sessions:
            if not s["messages"] or s["messages"][0].get("role") != "system":
                s["messages"].insert(0, SYSTEM_PROMPT)
            else:
                s["messages"][0] = SYSTEM_PROMPT

def restore_images_from_messages():
    """Restore gambar dari message ke session_state agar tampil setelah refresh."""
    if not st.session_state.sessions:
        return
    for sesi in st.session_state.sessions:
        for i, msg in enumerate(sesi.get("messages", [])):
            if msg.get("role") == "user" and msg.get("img_b64"):
                key = f"thumb_{sesi['id']}_{i-1}"
                if key not in st.session_state:
                    st.session_state[key] = (msg["img_b64"], msg.get("img_mime", "image/jpeg"))

def get_active():
    for s in st.session_state.sessions:
        if s["id"] == st.session_state.active_id:
            return s
    return st.session_state.sessions[0]
    for s in st.session_state.sessions:
        if s["id"] == st.session_state.active_id:
            return s
    return st.session_state.sessions[0]

def delete_session(sid):
    st.session_state.sessions = [s for s in st.session_state.sessions if s["id"] != sid]
    if not st.session_state.sessions:
        ns = new_session()
        st.session_state.sessions = [ns]
    if st.session_state.active_id == sid:
        st.session_state.active_id = st.session_state.sessions[0]["id"]

# ─────────────────────────────────────────────
# GOOGLE OAUTH
# ─────────────────────────────────────────────
def google_auth_url():
    params = {
        "client_id": st.secrets.get("GOOGLE_CLIENT_ID", ""),
        "redirect_uri": st.secrets.get("GOOGLE_REDIRECT_URI", ""),
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

def handle_oauth(code):
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": st.secrets.get("GOOGLE_CLIENT_ID", ""),
        "client_secret": st.secrets.get("GOOGLE_CLIENT_SECRET", ""),
        "redirect_uri": st.secrets.get("GOOGLE_REDIRECT_URI", ""),
        "grant_type": "authorization_code",
    })
    if r.status_code != 200: return None
    token = r.json().get("access_token", "")
    if not token: return None
    u = requests.get("https://www.googleapis.com/oauth2/v2/userinfo",
                     headers={"Authorization": f"Bearer {token}"})
    return u.json() if u.status_code == 200 else None

# ─────────────────────────────────────────────
# HANDLE OAUTH CALLBACK
# ─────────────────────────────────────────────
if "code" in st.query_params and st.session_state.user is None:
    info = handle_oauth(st.query_params["code"])
    if info:
        st.session_state.user = info
        saved = load_user(info["email"])
        if saved:
            st.session_state.theme = saved.get("theme", "dark")
            if saved.get("sessions"):
                st.session_state.sessions = saved["sessions"]
                st.session_state.active_id = saved.get("active_id")
        st.session_state.data_loaded = True
        # Buat token untuk auto-login — sama seperti username login
        token = str(uuid.uuid4()).replace("-","")
        with open(os.path.join(DATA_DIR, f"token_{token}.json"), "w") as f:
            json.dump(info, f)
        st.session_state.current_token = token
        st.query_params.clear()
        st.query_params["sigma_token"] = token  # Set di URL agar persist saat refresh
        st.rerun()

# ─────────────────────────────────────────────
# RESTORE SESSION DARI TOKEN (auto-login saat refresh)
# ─────────────────────────────────────────────
if "sigma_token" in st.query_params and st.session_state.user is None:
    token = st.query_params.get("sigma_token", "")
    token_file = os.path.join(DATA_DIR, f"token_{token}.json")
    if os.path.exists(token_file):
        try:
            with open(token_file) as f:
                user_info = json.load(f)
            st.session_state.user = user_info
            st.session_state.current_token = token
            saved = load_user(user_info["email"])
            if saved:
                st.session_state.theme = saved.get("theme", "dark")
                if saved.get("sessions"):
                    st.session_state.sessions = saved["sessions"]
                    st.session_state.active_id = saved.get("active_id", saved["sessions"][0]["id"])
            st.session_state.data_loaded = True
            restore_images_from_messages()
            # Jika ada do=del_ bersamaan, proses delete dulu sebelum rerun
            _pending_do = st.query_params.get("do", "")
            if _pending_do.startswith("del_"):
                _del_sid = _pending_do[4:]
                delete_session(_del_sid)
                _sessions_save = []
                for _s in st.session_state.sessions:
                    _msgs = [dict(m) for m in _s["messages"] if m["role"] != "system"]
                    _sessions_save.append({"id": _s["id"], "title": _s["title"],
                                           "created": _s["created"], "messages": _msgs})
                save_user(user_info["email"], {
                    "theme": st.session_state.get("theme", "dark"),
                    "sessions": _sessions_save,
                    "active_id": st.session_state.active_id,
                })
                st.query_params["do"] = ""
            st.rerun()
        except: pass

# Load data setelah login
if st.session_state.user and not st.session_state.data_loaded:
    saved = load_user(st.session_state.user["email"])
    if saved:
        st.session_state.theme = saved.get("theme", "dark")
        if saved.get("sessions") and not st.session_state.sessions:
            st.session_state.sessions = saved["sessions"]
            st.session_state.active_id = saved.get("active_id")
    st.session_state.data_loaded = True
    restore_images_from_messages()

# Refresh colors after theme load
C = get_colors(st.session_state.theme)

# ─────────────────────────────────────────────
# GLOBAL CSS
# ─────────────────────────────────────────────
st.markdown(f"""
<style>
* {{ font-family: ui-sans-serif,-apple-system,system-ui,"Segoe UI",sans-serif !important; box-sizing: border-box; }}

/* Global BG */
.stApp, [data-testid="stAppViewContainer"],
[data-testid="stAppViewContainer"] > section,
section[data-testid="stMain"],
[data-testid="stMainBlockContainer"],
[data-testid="stBottom"],
[data-testid="stBottom"] > div {{
    background: {C['bg']} !important;
}}

/* Sidebar */
section[data-testid="stSidebar"],
section[data-testid="stSidebar"] > div,
section[data-testid="stSidebar"] > div > div,
section[data-testid="stSidebar"] > div > div > div,
[data-testid="stSidebarContent"],
[data-testid="stSidebarUserContent"],
[data-testid="stSidebarUserContent"] > div,
[data-testid="stSidebarUserContent"] > div > div {{
    background: {C['sidebar_bg']} !important;
    box-shadow: none !important;
}}
section[data-testid="stSidebar"] {{
    border-right: 1px solid {C['border']} !important;
}}

/* Zero padding sidebar */
section[data-testid="stSidebar"] > div,
section[data-testid="stSidebar"] > div > div,
[data-testid="stSidebarContent"],
[data-testid="stSidebarUserContent"],
[data-testid="stSidebarUserContent"] > div {{
    padding-top: 0 !important;
    margin-top: 0 !important;
}}

/* Hide Streamlit collapse button */
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"] {{
    display: none !important;
}}

/* Sidebar buttons */
section[data-testid="stSidebar"] .stButton > button {{
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: {C['text']} !important;
    font-size: 0.875rem !important;
    padding: 7px 12px !important;
    border-radius: 8px !important;
    width: 100% !important;
    display: flex !important;
    align-items: center !important;
    justify-content: flex-start !important;
    text-align: left !important;
    min-height: 36px !important;
}}
section[data-testid="stSidebar"] .stButton > button:hover {{
    background: {C['hover']} !important;
}}
section[data-testid="stSidebar"] .stButton > button p,
section[data-testid="stSidebar"] .stButton > button span {{
    margin: 0 !important;
    text-align: left !important;
    color: inherit !important;
    width: 100% !important;
}}

/* Chat messages */
[data-testid="stChatMessage"] {{
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}}
[data-testid="stChatMessageAvatarUser"],
[data-testid="stChatMessageAvatarAssistant"] {{
    display: none !important;
}}
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {{
    font-size: 0.9rem !important;
    line-height: 1.75 !important;
    color: {C['text']} !important;
    background: transparent !important;
}}

/* Main content */
[data-testid="stMainBlockContainer"] {{
    max-width: 800px !important;
    margin: 0 auto !important;
    padding: 0 16px 120px !important;
    overflow-y: visible !important;
}}
[data-testid="stMainBlockContainer"] p,
[data-testid="stMainBlockContainer"] li,
[data-testid="stMainBlockContainer"] h1,
[data-testid="stMainBlockContainer"] h2,
[data-testid="stMainBlockContainer"] h3 {{
    color: {C['text']} !important;
}}

/* Chat input */
div[data-testid="stChatInputContainer"] {{
    border: 1px solid {C['border']} !important;
    background: {C['input_bg']} !important;
    border-radius: 16px !important;
}}
[data-testid="stChatInput"] textarea {{
    background: {C['input_bg']} !important;
    color: {C['text']} !important;
    font-size: 0.9rem !important;
}}
[data-testid="stChatInput"] textarea::placeholder {{
    color: {C['text_muted']} !important;
}}
[data-testid="stChatInputContainer"] textarea:focus {{
    box-shadow: none !important;
    outline: none !important;
}}

footer, #MainMenu {{ visibility: hidden !important; }}

/* Divider */
hr {{ border-color: {C['border']} !important; }}

/* ── BASE FONT — konsisten semua ukuran ── */
[data-testid="stMarkdownContainer"] *,
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] span,
[data-testid="stMarkdownContainer"] div {{
    font-size: 0.95rem !important;
    line-height: 1.8 !important;
}}
[data-testid="stMarkdownContainer"] strong,
[data-testid="stMarkdownContainer"] b {{
    font-size: inherit !important;
}}
[data-testid="stMarkdownContainer"] h1 {{ font-size: 1.3rem !important; }}
[data-testid="stMarkdownContainer"] h2 {{ font-size: 1.15rem !important; }}
[data-testid="stMarkdownContainer"] h3 {{ font-size: 1.05rem !important; }}

/* ── MOBILE ── */
@media (max-width: 768px) {{

    [data-testid="stMainBlockContainer"] {{
        max-width: 100% !important;
        padding: 12px 16px 120px !important;
    }}

    /* Font konsisten di mobile — semua elemen sama */
    [data-testid="stMarkdownContainer"],
    [data-testid="stMarkdownContainer"] *,
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stMarkdownContainer"] span,
    [data-testid="stMarkdownContainer"] strong,
    [data-testid="stMarkdownContainer"] b,
    [data-testid="stMarkdownContainer"] em {{
        font-size: 1rem !important;
        line-height: 1.85 !important;
    }}
    [data-testid="stMarkdownContainer"] h1 {{ font-size: 1.25rem !important; }}
    [data-testid="stMarkdownContainer"] h2 {{ font-size: 1.1rem !important; }}
    [data-testid="stMarkdownContainer"] h3 {{ font-size: 1rem !important; font-weight: 700 !important; }}

    /* List lebih rapi */
    [data-testid="stMarkdownContainer"] ul,
    [data-testid="stMarkdownContainer"] ol {{
        padding-left: 20px !important;
        margin: 6px 0 !important;
    }}
    [data-testid="stMarkdownContainer"] li {{
        margin-bottom: 4px !important;
    }}

    /* Code block */
    [data-testid="stMarkdownContainer"] code {{
        font-size: 0.85rem !important;
        padding: 2px 6px !important;
        border-radius: 4px !important;
        background: rgba(255,255,255,0.08) !important;
    }}
    [data-testid="stMarkdownContainer"] pre {{
        font-size: 0.82rem !important;
        overflow-x: auto !important;
        padding: 12px !important;
        border-radius: 8px !important;
    }}

    /* Chat input */
    div[data-testid="stChatInputContainer"] {{
        border-radius: 26px !important;
        margin: 0 6px 8px !important;
    }}
    [data-testid="stChatInput"] textarea {{
        font-size: 16px !important;
        line-height: 1.5 !important;
    }}

    /* Pesan lebih bernapas */
    [data-testid="stChatMessage"] {{
        padding: 10px 0 !important;
    }}

    /* Bubble user */
    .navy-pill {{
        max-width: 82% !important;
        font-size: 1rem !important;
        line-height: 1.7 !important;
        padding: 12px 16px !important;
    }}
}}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# LOGIN PAGE
# ─────────────────────────────────────────────
def show_login():
    st.markdown(f"""
    <style>
    [data-testid="stSidebar"] {{ display: none !important; }}

    /* Background full screen kipmd.png (desktop) / kipmm.png (mobile) */
    [data-testid="stAppViewContainer"],
    section[data-testid="stMain"] {{
        background: url('https://raw.githubusercontent.com/kipmuniversitaspancasila-commits/KIPMSIGMA/main/kipmd.png') center/cover no-repeat fixed !important;
        min-height: 100vh !important;
    }}

    /* Hapus pseudo-element kiri */
    section[data-testid="stMain"]::before {{
        display: none !important;
    }}

    /* Form container — transparan glass, compact, geser 1cm dari kanan */
    [data-testid="stMainBlockContainer"] {{
        max-width: 300px !important;
        margin: 1.5vh 74px 0 auto !important;
        padding: 8px 18px 16px !important;
        position: relative;
        z-index: 1;
        min-height: unset !important;
        height: fit-content !important;
        background: rgba(5, 8, 20, 0.60) !important;
        backdrop-filter: blur(20px) saturate(1.4) !important;
        -webkit-backdrop-filter: blur(20px) saturate(1.4) !important;
        border: 1px solid rgba(255,255,255,0.10) !important;
        border-radius: 20px !important;
        box-shadow: 0 8px 40px rgba(0,0,0,0.5) !important;
    }}
    @media(max-width: 768px) {{
        [data-testid="stMainBlockContainer"] {{
            margin: 5vh auto 0 auto !important;
            max-width: 88% !important;
            padding: 20px 20px 28px !important;
            backdrop-filter: blur(20px) !important;
            border-radius: 20px !important;
            border: 1px solid rgba(255,255,255,0.12) !important;
            box-shadow: 0 8px 40px rgba(0,0,0,0.5) !important;
        }}
    }}

    /* Sembunyikan header toolbar Streamlit bawaan */
    header[data-testid="stHeader"] {{
        display: none !important;
    }}
    #MainMenu {{
        display: none !important;
    }}

    /* Mobile — pastikan background terlihat di atas & bawah kotak */
    @media(max-width: 768px) {{
        [data-testid="stAppViewContainer"],
        section[data-testid="stMain"] {{
            background: url('https://raw.githubusercontent.com/kipmuniversitaspancasila-commits/KIPMSIGMA/main/kipmm.png') center top/cover no-repeat fixed !important;
        }}
        /* Kotak login beri ruang logo KIPM di atas */
        [data-testid="stMainBlockContainer"] {{
            margin-top: 75px !important;
        }}
    }}

    /* Glass card */
    .stTabs, [data-testid="stVerticalBlock"] {{
        background: transparent !important;
    }}

    /* Input fields glass style */
    [data-testid="stTextInput"] input {{
        background: rgba(255,255,255,0.06) !important;
        border: 1px solid rgba(255,255,255,0.12) !important;
        border-radius: 12px !important;
        color: #fff !important;
        padding: 12px 16px !important;
        font-size: 0.95rem !important;
        backdrop-filter: blur(10px) !important;
        transition: border 0.2s !important;
    }}
    [data-testid="stTextInput"] input:focus {{
        border: 1px solid {C['gold']} !important;
        box-shadow: 0 0 0 2px rgba(245,194,66,0.15) !important;
        outline: none !important;
    }}
    [data-testid="stTextInput"] input::placeholder {{ color: rgba(255,255,255,0.35) !important; }}
    [data-testid="stTextInput"] label {{ color: rgba(255,255,255,0.6) !important; font-size: 0.82rem !important; }}

    /* Masuk button */
    [data-testid="stMainBlockContainer"] .stButton > button {{
        background: linear-gradient(135deg, {C['gold']}, #e0a820) !important;
        color: #000 !important;
        font-weight: 700 !important;
        border: none !important;
        border-radius: 12px !important;
        padding: 12px !important;
        font-size: 0.95rem !important;
        letter-spacing: 0.5px !important;
        transition: opacity 0.2s, transform 0.1s !important;
        box-shadow: 0 4px 20px rgba(245,194,66,0.3) !important;
    }}
    [data-testid="stMainBlockContainer"] .stButton > button:hover {{
        opacity: 0.92 !important; transform: translateY(-1px) !important;
    }}

    /* Tabs glass */
    [data-testid="stTabs"] [role="tablist"] {{
        background: rgba(255,255,255,0.05) !important;
        border-radius: 12px !important;
        padding: 4px !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        gap: 2px !important;
    }}
    [data-testid="stTabs"] button[role="tab"] {{
        border-radius: 9px !important;
        color: rgba(255,255,255,0.5) !important;
        font-size: 0.85rem !important;
        padding: 7px 12px !important;
        border: none !important;
        background: transparent !important;
    }}
    [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{
        background: rgba(245,194,66,0.15) !important;
        color: {C['gold']} !important;
        font-weight: 600 !important;
    }}
    [data-testid="stTabs"] [role="tabpanel"] {{
        background: rgba(255,255,255,0.03) !important;
        border-radius: 16px !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        padding: 20px 16px !important;
        margin-top: 8px !important;
        backdrop-filter: blur(10px) !important;
    }}

    /* Alert colors */
    [data-testid="stAlert"] {{ border-radius: 10px !important; }}

    /* Animasi background */
    @keyframes gradMove {{
        0% {{ background-position: 0% 50%; }}
        50% {{ background-position: 100% 50%; }}
        100% {{ background-position: 0% 50%; }}
    }}
    </style>
    """, unsafe_allow_html=True)

    # Background sudah di-set via CSS (URL GitHub raw)

    # Inject logo KIPM khusus mobile — hanya saat halaman login
    components.html(f"""
<script>
(function() {{
    var pd = window.parent.document;

    // Sembunyikan Fork bar & toolbar GitHub Streamlit
    var forkStyle = pd.getElementById('hide-fork-bar');
    if (!forkStyle) {{
        var fs = pd.createElement('style');
        fs.id = 'hide-fork-bar';
        fs.textContent = `
            /* Fork bar & GitHub badge */
            .viewerBadge_container__r5tak,
            .viewerBadge_link__qRIco,
            [class*="viewerBadge"],
            [class*="styles_viewerBadge"],
            #MainMenu,
            footer,
            /* Streamlit toolbar atas */
            [data-testid="stToolbar"],
            [data-testid="stDecoration"],
            [data-testid="stStatusWidget"],
            header[data-testid="stHeader"],
            /* Tombol deploy/fork */
            .stDeployButton,
            [kind="header"],
            div[data-testid="collapsedControl"] {{
                display: none !important;
                visibility: hidden !important;
                height: 0 !important;
                overflow: hidden !important;
            }}
        `;
        pd.head.appendChild(fs);
    }}

    if (pd.getElementById('kipm-mobile-logo')) return;

    var s = pd.createElement('style');
    s.id = 'kipm-mobile-logo-style';
    s.textContent = `
        #kipm-mobile-logo {{
            display: none;
            text-align: center;
            padding: 14px 0 10px;
            position: fixed;
            top: 0; left: 0; right: 0;
            z-index: 10;
            pointer-events: none;
        }}
        #kipm-mobile-logo img {{
            width: 80px; height: 80px;
            object-fit: contain;
            filter: drop-shadow(0 2px 12px rgba(0,0,0,0.6));
        }}
        #kipm-mobile-logo .kipm-name {{
            font-size: 0.7rem;
            color: rgba(255,255,255,0.7);
            letter-spacing: 2px;
            font-family: sans-serif;
            margin-top: 4px;
        }}
        @media(max-width: 768px) {{
            #kipm-mobile-logo {{ display: block !important; }}
        }}
    `;
    pd.head.appendChild(s);

    var div = pd.createElement('div');
    div.id = 'kipm-mobile-logo';
    div.innerHTML = `
        <img src="https://raw.githubusercontent.com/kipmuniversitaspancasila-commits/KIPMSIGMA/main/Mate%20KIPM%20LOGO.png"
             onerror="this.style.display='none'"
             style="width:80px;height:80px;object-fit:contain;">
        <div class="kipm-name">KIPM-UP</div>
    `;
    pd.body.appendChild(div);
}})();
</script>
""", height=0)
    st.markdown('''
        <div style="text-align:center;margin:0 0 10px;">
            <div style="font-size:2.8rem;font-weight:900;letter-spacing:5px;color:#ffffff;font-family:sans-serif;line-height:1.2;">
                SIGMA <span style="color:#F5C242;">Σ</span>
            </div>
            <div class="sigma-tagline" style="font-size:0.65rem;color:rgba(255,255,255,0.5);letter-spacing:2px;margin-top:4px;font-family:sans-serif;">
                Strategic Intelligence & Global Market Analysis
            </div>
        </div>
        <style>
            @media(min-width: 769px) { .sigma-tagline { display: none !important; } }
        </style>
    ''', unsafe_allow_html=True)
    tab1, tab2, tab3 = st.tabs(["🔑 Sign In", "📝 Sign Up", "🌐 Google"])

    with tab1:
        uname = st.text_input("Username", key="li_user", placeholder="Masukkan username")
        pwd   = st.text_input("Password", key="li_pwd",  type="password", placeholder="Masukkan password")
        if st.button("Masuk", key="btn_login", use_container_width=True):
            if uname and pwd:
                info = login_user(uname.strip(), pwd)
                if info:
                    token = str(uuid.uuid4()).replace("-","")
                    with open(os.path.join(DATA_DIR, f"token_{token}.json"), "w") as f:
                        json.dump(info, f)
                    st.query_params["sigma_token"] = token
                    st.session_state.user = info
                    st.session_state.current_token = token
                    st.session_state.data_loaded = False
                    st.rerun()
                else:
                    st.error("Username atau password salah")
            else:
                st.warning("Isi username dan password")

    with tab2:
        rname  = st.text_input("Nama Tampil", key="rg_name", placeholder="Nama lengkap kamu")
        runame = st.text_input("Username", key="rg_user", placeholder="username (huruf/angka)")
        rpwd   = st.text_input("Password", key="rg_pwd",  type="password", placeholder="min. 6 karakter")
        rpwd2  = st.text_input("Ulangi Password", key="rg_pwd2", type="password", placeholder="ulangi password")
        if st.button("Daftar Sekarang", key="btn_register", use_container_width=True):
            if not all([rname, runame, rpwd, rpwd2]):
                st.warning("Lengkapi semua field")
            elif rpwd != rpwd2:
                st.error("Password tidak cocok")
            elif len(rpwd) < 6:
                st.error("Password minimal 6 karakter")
            else:
                ok, msg = register_user(runame.strip(), rpwd, rname.strip())
                if ok:
                    st.success(f"✅ {msg} — silakan masuk")
                else:
                    st.error(msg)

    with tab3:
        try:
            auth_url = google_auth_url()
            st.markdown(f"""
            <div style="margin-top:8px;">
                <a href="{auth_url}" style="
                    display:flex;align-items:center;justify-content:center;gap:10px;
                    background:rgba(255,255,255,0.95);color:#1a1a1a;border-radius:12px;padding:13px;
                    text-decoration:none;font-size:0.9rem;font-weight:600;
                    border:none;box-shadow:0 4px 15px rgba(0,0,0,0.3);">
                    <svg width="18" height="18" viewBox="0 0 24 24">
                        <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                        <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                        <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/>
                        <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                    </svg>
                    Lanjutkan dengan Google
                </a>
            </div>
            """, unsafe_allow_html=True)
        except:
            st.info("Google login belum dikonfigurasi di Secrets")

    st.markdown(f"""
    <p style="text-align:center;color:rgba(255,255,255,0.25);font-size:0.72rem;margin-top:24px;line-height:1.6;">
        Dengan masuk, kamu menyetujui penggunaan platform untuk analisa.<br>
        Analisa bersifat <em>do your own research</em> dan disclaimer berlaku. by MarketnMocha
    </p>
    """, unsafe_allow_html=True)
    st.stop()

# ─────────────────────────────────────────────
# GUARD: LOGIN REQUIRED
# ─────────────────────────────────────────────
if st.session_state.user is None:
    show_login()

# Init chat after login
init_chat()
user = st.session_state.user
C = get_colors(st.session_state.theme)


# ─────────────────────────────────────────────
# SEMBUNYIKAN SIDEBAR
# ─────────────────────────────────────────────
st.markdown("""
<style>
section[data-testid="stSidebar"],
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"] { display: none !important; }

/* Sembunyikan Fork bar, GitHub badge, Streamlit logo di semua halaman */
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
.viewerBadge_container__r5tak,
[class*="viewerBadge"],
.stDeployButton,
#MainMenu,
footer,
/* Bar hitam Fork */
[data-testid="stHeader"],
iframe[title="streamlit_analytics"],
div[class*="Toolbar"],
div[class*="toolbar"],
div[class*="ActionButton"],
div[class*="HeaderActionButton"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

_hist_items = ""
for _sesi in st.session_state.sessions:
    _sid = _sesi["id"]
    _is_act = _sid == st.session_state.active_id
    _td = _sesi["title"][:35].replace("'","").replace("`","").replace("\\","").replace('"',"")
    _fw = "700" if _is_act else "400"
    _bg = C['hover'] if _is_act else "transparent"
    _hist_items += f"""
(function(){{
    var row=pd.createElement('div');
    row.style.cssText='display:flex;align-items:center;width:100%;';

    var a=pd.createElement('a');
    a.textContent='{_td}';
    var u=new URL(window.parent.location.href);
    u.searchParams.set('do','sel_{_sid}');
    a.href=u.toString();
    a.style.cssText='flex:1;display:block;padding:12px 8px 12px 18px;font-size:1rem;color:{C["text"]};background:{_bg};font-weight:{_fw};border:none;text-align:left;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-decoration:none;min-width:0;';
    a.onmouseenter=function(){{this.style.background='{C["hover"]}'}};
    a.onmouseleave=function(){{this.style.background='{_bg}'}};

    var del=pd.createElement('button');
    del.innerHTML='🗑';
    del.title='Hapus';
    del.style.cssText='padding:8px 12px;background:transparent;border:none;cursor:pointer;font-size:0.9rem;opacity:0.35;flex-shrink:0;color:{C["text"]};';
    del.onmouseenter=function(){{this.style.opacity='1';this.style.color='#ff5555';}};
    del.onmouseleave=function(){{this.style.opacity='0.35';this.style.color='{C["text"]}';}};
    del.onclick=function(e){{
        e.preventDefault();e.stopPropagation();
        if(confirm('Hapus obrolan ini?')){{
            var u2=new URL(window.parent.location.href);
            u2.searchParams.set('del','{_sid}');
            u2.searchParams.delete('do');
            window.parent.location.href=u2.toString();
        }}
    }};

    row.appendChild(a);
    row.appendChild(del);
    h.appendChild(row);
}})();
"""

# Inject menu ke parent document via components.html
components.html(f"""
<script>
(function(){{
var pd=window.parent.document;

// Sembunyikan logo KIPM login saat sudah masuk ke halaman utama
var kipmLogo = pd.getElementById('kipm-mobile-logo');
if (kipmLogo) kipmLogo.style.display = 'none !important';
var kipmStyle = pd.getElementById('kipm-mobile-logo-style');
if (kipmStyle) kipmStyle.remove();

// Hapus elemen lama kalau ada, inject ulang yang baru
['spbtn','spmenu','sphist','spui','sigma-mobile-css'].forEach(function(id){{
    var el=pd.getElementById(id);
    if(el) el.remove();
}});

// CSS
var s=pd.createElement('style');
s.id='sigma-mobile-css';
s.textContent=`
#spbtn{{position:fixed;bottom:16px;left:14px;width:38px;height:38px;border-radius:50%;
    background:{C["sidebar_bg"]};color:{C["text"]};border:1px solid {C["border"]};
    cursor:pointer;font-size:24px;font-weight:300;z-index:99999;
    display:flex;align-items:center;justify-content:center;
    box-shadow:0 2px 10px rgba(0,0,0,0.5);padding:0;line-height:1;}}
#spbtn:hover{{transform:scale(1.1)}}
#spmenu,#sphist{{position:fixed;left:12px;bottom:62px;
    background:{C["sidebar_bg"]};border:1px solid {C["border"]};
    border-radius:16px;box-shadow:0 -4px 24px rgba(0,0,0,0.5);
    z-index:99998;display:none;overflow:hidden;min-width:250px;}}
#sphist{{max-height:55vh;overflow-y:auto;}}
.smi{{display:flex;align-items:center;gap:14px;padding:13px 18px;
    font-size:1rem;color:{C["text"]};cursor:pointer;border:none;
    background:transparent;width:100%;text-align:left;}}
.smi:hover{{background:{C["hover"]}}}
.smico{{width:32px;height:32px;border-radius:8px;display:flex;
    align-items:center;justify-content:center;font-size:16px;
    background:{C["hover"]};flex-shrink:0;}}
.smsp{{border:none;border-top:1px solid {C["border"]};margin:4px 0;}}
.smhd{{padding:8px 18px 4px;font-size:0.68rem;color:{C["text_muted"]};
    font-weight:600;letter-spacing:1px;}}
.smred{{color:#f55!important}}
`;
pd.head.appendChild(s);

// + button
var btn=pd.createElement('button');
btn.id='spbtn';btn.textContent='+';pd.body.appendChild(btn);

// Menu
var m=pd.createElement('div');m.id='spmenu';
m.innerHTML=`
<a class="smi" id="smi-new"><span class="smico">✎</span>Obrolan baru</a>
<button class="smi" id="smi-hist"><span class="smico">☰</span>Riwayat obrolan</button>
<div class="smsp"></div>
<div class="smhd">PENAMPILAN</div>
<a class="smi" id="smi-dark"><span class="smico">🌙</span>Mode Gelap {'✓' if st.session_state.theme=='dark' else ''}</a>
<a class="smi" id="smi-light"><span class="smico">☀️</span>Mode Terang {'✓' if st.session_state.theme=='light' else ''}</a>
<div class="smsp"></div>
<a class="smi smred" id="smi-out"><span class="smico">🚪</span>Keluar</a>
`;
pd.body.appendChild(m);

// Nav function
function nav(params){{
    var u=new URL(window.parent.location.href);
    Object.keys(params).forEach(function(k){{u.searchParams.set(k,params[k])}});
    window.parent.location.href=u.toString();
}}

// History drawer
var h=pd.createElement('div');h.id='sphist';
h.innerHTML='<div class="smhd">RIWAYAT OBROLAN</div>';
{_hist_items}
pd.body.appendChild(h);

btn.onclick=function(e){{e.stopPropagation();m.style.display=m.style.display==='block'?'none':'block';h.style.display='none';}};

// Set href langsung pada menu items
(function(){{
    var u;
    u=new URL(window.parent.location.href); u.searchParams.set('do','newchat');
    pd.getElementById('smi-new').href=u.toString();
    pd.getElementById('smi-new').style.textDecoration='none';
    
    pd.getElementById('smi-hist').onclick=function(){{m.style.display='none';h.style.display=h.style.display==='block'?'none':'block';}};
    
    u=new URL(window.parent.location.href); u.searchParams.set('do','theme_dark');
    pd.getElementById('smi-dark').href=u.toString();
    pd.getElementById('smi-dark').style.textDecoration='none';
    
    u=new URL(window.parent.location.href); u.searchParams.set('do','theme_light');
    pd.getElementById('smi-light').href=u.toString();
    pd.getElementById('smi-light').style.textDecoration='none';
    
    u=new URL(window.parent.location.href); u.searchParams.delete('sigma_token'); u.searchParams.set('do','logout');
    pd.getElementById('smi-out').href=u.toString();
    pd.getElementById('smi-out').style.textDecoration='none';
}})();

pd.addEventListener('click',function(e){{
    if(!btn.contains(e.target)&&!m.contains(e.target))m.style.display='none';
    if(!btn.contains(e.target)&&!h.contains(e.target)&&!m.contains(e.target))h.style.display='none';
}});
}})();
</script>
""", height=0)

# Handle actions
if "do" in st.query_params:
    _do = st.query_params.get("do", "")
    _tok = st.query_params.get("sigma_token", st.session_state.get("current_token", ""))
    if _do == "logout":
        if _tok:
            try: os.remove(os.path.join(DATA_DIR, f"token_{_tok}.json"))
            except: pass
        st.session_state.clear(); st.query_params.clear(); st.rerun()
    elif _do == "theme_dark":
        st.session_state.theme = "dark"
        st.query_params["do"] = ""; st.rerun()
    elif _do == "theme_light":
        st.session_state.theme = "light"
        st.query_params["do"] = ""; st.rerun()
    elif _do == "newchat":
        ns = new_session()
        st.session_state.sessions.insert(0, ns)
        st.session_state.active_id = ns["id"]
        st.query_params["do"] = ""; st.rerun()
    elif _do.startswith("sel_"):
        _sid = _do[4:]
        st.session_state.active_id = _sid
        st.query_params["do"] = ""; st.rerun()
    elif _do.startswith("del_"):
        _sid = _do[4:]
        delete_session(_sid)
        # Simpan LANGSUNG ke disk sebelum rerun agar restore tidak load sesi lama
        if st.session_state.get("user"):
            _u = st.session_state.user
            _sessions_save = []
            for _s in st.session_state.sessions:
                _msgs = [dict(m) for m in _s["messages"] if m["role"] != "system"]
                _sessions_save.append({"id": _s["id"], "title": _s["title"],
                                       "created": _s["created"], "messages": _msgs})
            save_user(_u["email"], {
                "theme": st.session_state.get("theme", "dark"),
                "sessions": _sessions_save,
                "active_id": st.session_state.active_id,
            })
        st.session_state.data_loaded = True
        st.query_params["do"] = ""; st.rerun()

# ─────────────────────────────────────────────
# MAIN CHAT
# ─────────────────────────────────────────────
active = get_active()

# Build history JS untuk drawer — inject items tanpa st.button
_hist_items = ""
for sesi in st.session_state.sessions:
    sid = sesi["id"]
    is_active = sid == st.session_state.active_id
    title_d = sesi["title"][:35].replace("'", "\\'").replace("`","")
    fw = "600" if is_active else "400"
    bg = C['hover'] if is_active else "transparent"
    _hist_items += f"""
    (function() {{
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;width:100%;';

        var hi = document.createElement('button');
        hi.textContent = '{title_d}';
        hi.dataset.sid = '{sid}';
        hi.style.cssText = 'flex:1;padding:11px 8px 11px 16px;font-size:0.95rem;color:{C["text"]};background:{bg};font-weight:{fw};border:none;text-align:left;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;';
        hi.onmouseenter = function(){{this.style.background='{C["hover"]}'}};
        hi.onmouseleave = function(){{this.style.background='{bg}'}};
        hi.onclick = function(){{
            var url = new URL(window.parent.location.href);
            url.searchParams.set('do', 'sel_{sid}');
            window.parent.location.href = url.toString();
        }};

        var del = document.createElement('button');
        del.innerHTML = '🗑';
        del.title = 'Hapus obrolan';
        del.style.cssText = 'padding:8px 10px;background:transparent;border:none;cursor:pointer;font-size:0.9rem;opacity:0.4;flex-shrink:0;color:{C["text"]};';
        del.onmouseenter = function(){{this.style.opacity='1';this.style.color='#ff5555';}};
        del.onmouseleave = function(){{this.style.opacity='0.4';this.style.color='{C["text"]}';}};
        del.onclick = function(e){{
            e.stopPropagation();
            if(confirm('Hapus obrolan ini?')){{
                var url = new URL(window.parent.location.href);
                url.searchParams.set('do', 'del_{sid}');
                window.parent.location.href = url.toString();
            }}
        }};

        row.appendChild(hi);
        row.appendChild(del);
        drawer.appendChild(row);
    }})();
"""

# Header
if not active["messages"][1:]:
    uname = user.get("name", "").split()[0] if user.get("name") else "Trader"
    st.markdown(f"""
    <div style="text-align:center;padding:10vh 0 2rem;">
        <h1 style="margin:0;font-size:1.8rem;font-weight:700;color:{C['text']};">Halo, {uname} 👋</h1>
        <p style="margin:8px 0 0;color:{C['text_muted']};font-size:0.9rem;">Ada yang bisa SIGMA bantu analisa hari ini?</p>
    </div>
    """, unsafe_allow_html=True)

# Tampilkan error terakhir jika ada
if st.session_state.get("last_error"):
    st.error(f"⚠️ Error terakhir: {st.session_state['last_error']}")
    if st.button("✕ Tutup error"):
        st.session_state["last_error"] = None
        st.rerun()

# Chat history
for i, msg in enumerate(active["messages"][1:]):
    with st.chat_message(msg["role"]):
        display = msg.get("display") or msg["content"]
        if "Pertanyaan:" in display:
            display = display.split("Pertanyaan:")[-1].strip()
        if "[DATA PASAR]" in display:
            display = display.split("[/DATA PASAR]")[-1].strip()
        if msg["role"] == "user" and msg.get("img_b64"):
            st.markdown(f'<img src="data:{msg.get("img_mime","image/jpeg")};base64,{msg["img_b64"]}" style="max-width:100%;max-height:240px;border-radius:10px;margin-bottom:6px;display:block;">', unsafe_allow_html=True)
        st.markdown(display)

# Chat input
try:
    result = st.chat_input(
        "Tanya SIGMA... DYOR - bukan financial advice.",
        accept_file="multiple",
        file_type=["pdf", "png", "jpg", "jpeg"]
    )
except TypeError:
    result = st.chat_input("Tanya SIGMA...")

prompt = None
file_obj = None

if result is not None:
    # Handle semua format result Streamlit
    if hasattr(result, 'text'):
        prompt = (result.text or "").strip()
        # Coba berbagai cara akses file
        for attr in ['files', 'file', '_files']:
            files = getattr(result, attr, None)
            if files:
                file_obj = files[0] if isinstance(files, (list, tuple)) else files
                break
    elif isinstance(result, str):
        prompt = result.strip()
    else:
        # Format lain — coba konversi
        try:
            prompt = str(result).strip() if result else ""
        except:
            pass

    if file_obj:
        raw = file_obj.read()
        if file_obj.type == "application/pdf":
            doc = fitz.open(stream=raw, filetype="pdf")
            txt = "".join(p.get_text() for p in doc)
            st.session_state.pdf_data = (f"[PDF: {file_obj.name}]\n{txt[:4000]}", file_obj.name)
            st.session_state.img_data = None
        else:
            b64 = base64.b64encode(raw).decode()
            mime = "image/png" if file_obj.name.endswith(".png") else "image/jpeg"
            st.session_state.img_data = (b64, mime, file_obj.name)
            st.session_state.pdf_data = None

    if not prompt and (file_obj or st.session_state.img_data or st.session_state.pdf_data):
        prompt = "Tolong analisa file yang saya kirim"

if prompt:
    img_data = st.session_state.img_data
    pdf_data = st.session_state.pdf_data
    st.session_state.img_data = None
    st.session_state.pdf_data = None

    full_prompt = prompt
    if img_data:
        full_prompt = f"[Gambar: {img_data[2]}]\n\nPertanyaan: {prompt}"
    elif pdf_data:
        full_prompt = f"{pdf_data[0]}\n\nPertanyaan: {prompt}"
    else:
        try:
            ctx = build_context(prompt)
            if ctx:
                full_prompt = f"[DATA PASAR]\n{ctx}\n[/DATA PASAR]\n\n{prompt}"
        except:
            pass

    if active["title"] == "Obrolan Baru":
        active["title"] = prompt[:40] + ("..." if len(prompt) > 40 else "")

    # Simpan gambar di dalam message agar tetap ada setelah refresh
    user_msg = {"role": "user", "content": full_prompt, "display": prompt}
    if img_data:
        user_msg["img_b64"] = img_data[0]
        user_msg["img_mime"] = img_data[1]
        # Juga simpan di session_state untuk render langsung
        thumb_idx = len(active["messages"]) - 1
        st.session_state[f"thumb_{active['id']}_{thumb_idx}"] = (img_data[0], img_data[1])

    active["messages"].append(user_msg)
    with st.chat_message("user"):
        if img_data:
            st.markdown(f'<img src="data:{img_data[1]};base64,{img_data[0]}" style="max-width:100%;max-height:240px;border-radius:10px;margin-bottom:6px;display:block;">', unsafe_allow_html=True)
        st.markdown(prompt)

    try:
        groq_client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        with st.chat_message("assistant"):
            with st.spinner("SIGMA menganalisis..."):
                if img_data:
                    res = groq_client.chat.completions.create(
                        model="meta-llama/llama-4-scout-17b-16e-instruct",
                        messages=[
                            {"role": "system", "content": "Kamu SIGMA, analis chart. Analisa gambar langsung. Jawab Bahasa Indonesia."},
                            {"role": "user", "content": [
                                {"type": "image_url", "image_url": {"url": f"data:{img_data[1]};base64,{img_data[0]}"}},
                                {"type": "text", "text": prompt}
                            ]}
                        ],
                        max_tokens=2048
                    )
                else:
                    _msgs = [
                        {"role": m["role"], "content": m.get("content") or ""}
                        for m in active["messages"]
                        if m.get("role") in ("user","assistant","system")
                    ]
                    # Cek apakah pesan terakhir PDF/besar
                    _last_len = len(_msgs[-1]["content"]) if _msgs else 0
                    if _last_len > 3000:
                        # Kirim hanya system + pesan terakhir, potong di 8000 char
                        _msgs = [
                            _msgs[0],
                            {"role": _msgs[-1]["role"],
                             "content": _msgs[-1]["content"][:8000]}
                        ]
                    res = groq_client.chat.completions.create(
                        model="llama-3.1-8b-instant",
                        messages=_msgs,
                        temperature=0.7,
                        max_tokens=1500
                    )
                ans = res.choices[0].message.content
            st.markdown(ans)
        active["messages"].append({"role": "assistant", "content": ans})
    except Exception as e:
        err_str = str(e)
        st.error(f"Error: {err_str}")
        # Simpan error ke session agar tidak hilang setelah rerun
        st.session_state["last_error"] = err_str

    st.rerun()

# ─────────────────────────────────────────────
# SAVE DATA
# ─────────────────────────────────────────────
if user:
    sessions_to_save = []
    for s in st.session_state.sessions:
        msgs = [dict(m) for m in s["messages"] if m["role"] != "system"]
        sessions_to_save.append({"id": s["id"], "title": s["title"], "created": s["created"], "messages": msgs})
    save_user(user["email"], {
        "theme": st.session_state.get("theme", "dark"),
        "sessions": sessions_to_save,
        "active_id": st.session_state.active_id,
    })

# Kirim token baru ke localStorage setelah login
_new_token = st.session_state.pop("new_token", None)
if _new_token:
    components.html(f"""
<script>
try {{ localStorage.setItem('sigma_token', '{_new_token}'); }} catch(e) {{}}
</script>
""", height=0)

# Auto-restore token saat refresh — baca localStorage lalu redirect
if st.session_state.user is None:
    components.html("""
<script>
(function() {
    try {
        var token = localStorage.getItem('sigma_token');
        if (token) {
            var url = window.parent.location.href.split('?')[0];
            window.parent.location.replace(url + '?sigma_token=' + token);
        }
    } catch(e) {}
})();
</script>
""", height=0)

# ─────────────────────────────────────────────
# JS: bubble kanan + paste gambar + mobile CSS
# ─────────────────────────────────────────────
components.html(f"""
<script>
const BC = "{C['bubble']}";
const BT = "#ffffff";

// ── Inject mobile CSS ke parent <head> — cara paling kuat ──
(function() {{
    var pd = window.parent.document;
    if (pd.getElementById('sigma-mobile-css')) return;
    var s = pd.createElement('style');
    s.id = 'sigma-mobile-css';
    s.textContent = `
        /* Base font konsisten */
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] li,
        [data-testid="stMarkdownContainer"] span,
        [data-testid="stMarkdownContainer"] div,
        [data-testid="stMarkdownContainer"] strong,
        [data-testid="stMarkdownContainer"] b,
        [data-testid="stMarkdownContainer"] em {{
            font-size: 1rem !important;
            line-height: 1.85 !important;
        }}

        @media (max-width: 768px) {{
            /* Konten full width rapat */
            [data-testid="stMainBlockContainer"] {{
                max-width: 100% !important;
                padding: 8px 12px 120px !important;
                margin: 0 !important;
            }}
            /* Semua teks AI besar dan nyaman */
            [data-testid="stMarkdownContainer"],
            [data-testid="stMarkdownContainer"] p,
            [data-testid="stMarkdownContainer"] li,
            [data-testid="stMarkdownContainer"] span,
            [data-testid="stMarkdownContainer"] div,
            [data-testid="stMarkdownContainer"] strong,
            [data-testid="stMarkdownContainer"] b,
            [data-testid="stMarkdownContainer"] em,
            [data-testid="stMarkdownContainer"] a {{
                font-size: 1.05rem !important;
                line-height: 1.9 !important;
            }}
            [data-testid="stMarkdownContainer"] h1 {{ font-size: 1.3rem !important; }}
            [data-testid="stMarkdownContainer"] h2 {{ font-size: 1.15rem !important; }}
            [data-testid="stMarkdownContainer"] h3 {{ font-size: 1.05rem !important; font-weight: 700 !important; }}

            /* List rapi */
            [data-testid="stMarkdownContainer"] ul,
            [data-testid="stMarkdownContainer"] ol {{
                padding-left: 18px !important;
                margin: 4px 0 !important;
            }}
            [data-testid="stMarkdownContainer"] li {{
                margin-bottom: 6px !important;
            }}

            /* Jarak antar chat */
            [data-testid="stChatMessage"] {{
                padding: 10px 0 !important;
            }}

            /* Chat input */
            div[data-testid="stChatInputContainer"] {{
                border-radius: 26px !important;
                margin: 0 4px 8px !important;
            }}
            [data-testid="stChatInput"] textarea {{
                font-size: 16px !important;
                line-height: 1.5 !important;
            }}

            /* Bubble */
            .navy-pill {{
                max-width: 82% !important;
                font-size: 1.05rem !important;
                line-height: 1.75 !important;
                padding: 12px 16px !important;
            }}

            /* Code */
            [data-testid="stMarkdownContainer"] code {{
                font-size: 0.88rem !important;
            }}
            [data-testid="stMarkdownContainer"] pre {{
                font-size: 0.85rem !important;
                overflow-x: auto !important;
                padding: 12px !important;
            }}
        }}
    `;
    pd.head.appendChild(s);
}})();

function fixBubbles() {{
    const doc = window.parent.document;
    doc.querySelectorAll('[data-testid="stChatMessage"]').forEach(msg => {{
        if (!msg.querySelector('[data-testid="stChatMessageAvatarUser"]')) return;
        msg.style.cssText += 'display:flex!important;justify-content:flex-end!important;background:transparent!important;border:none!important;box-shadow:none!important;padding:4px 0!important;';
        const av = msg.querySelector('[data-testid="stChatMessageAvatarUser"]');
        if (av) av.style.display = 'none';
        const ct = msg.querySelector('[data-testid="stChatMessageContent"]');
        if (ct) ct.style.cssText += 'background:transparent!important;display:flex!important;justify-content:flex-end!important;max-width:100%!important;padding:0!important;';
        msg.querySelectorAll('[data-testid="stMarkdownContainer"]').forEach(md => {{
            md.style.background = 'transparent';
            md.style.display = 'flex';
            md.style.justifyContent = 'flex-end';
            if (!md.querySelector('.navy-pill')) {{
                const pill = document.createElement('div');
                pill.className = 'navy-pill';
                var mob=window.parent.innerWidth<=768;
                pill.style.cssText=`background:linear-gradient(135deg,#42a8e0,#1a4fad);color:#ffffff;border-radius:18px 18px 4px 18px;padding:${{mob?"12px 16px":"10px 16px"}};max-width:${{mob?"85%":"72%"}};display:inline-block;font-size:${{mob?"1rem":"0.9rem"}};line-height:1.7;word-wrap:break-word;`;
                while (md.firstChild) pill.appendChild(md.firstChild);
                md.appendChild(pill);
            }}
            // Force putih semua elemen dalam bubble
            var pill = md.querySelector('.navy-pill');
            if (pill) {{
                pill.style.setProperty('color','#ffffff','important');
                pill.style.setProperty('background','linear-gradient(135deg,#42a8e0,#1a4fad)','important');
                pill.querySelectorAll('*').forEach(function(el){{
                    el.style.setProperty('color','#ffffff','important');
                }});
            }}
        }});
    }});
}}

fixBubbles();
setInterval(fixBubbles, 800);
new MutationObserver(() => setTimeout(fixBubbles, 100)).observe(
    window.parent.document.body, {{childList:true,subtree:true}}
);

// ── Tombol aksi di bawah bubble & pesan AI ──
function addActionButtons() {{
    var doc = window.parent.document;
    doc.querySelectorAll('[data-testid="stChatMessage"]').forEach(function(msg) {{
        if (msg.querySelector('.sigma-actions')) return;
        if (!!msg.querySelector('[data-testid="stChatMessageAvatarUser"]')) return;
        function getMsgText() {{
            var md = msg.querySelector('[data-testid="stMarkdownContainer"]');
            return md ? md.innerText : '';
        }}
        var bar = doc.createElement('div');
        bar.className = 'sigma-actions';
        bar.style.cssText = 'display:flex;gap:2px;margin-top:6px;padding:0 2px;';
        var copyBtn = doc.createElement('button');
        copyBtn.title = 'Salin';
        copyBtn.innerHTML = '<svg width=\"16\" height=\"16\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#8e8ea0\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"9\" y=\"9\" width=\"13\" height=\"13\" rx=\"2\"></rect><path d=\"M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1\"></path></svg>';
        copyBtn.style.cssText = 'background:transparent;border:none;cursor:pointer;padding:5px 6px;border-radius:6px;display:flex;align-items:center;';
        copyBtn.onmouseenter=function(){{this.style.background='rgba(255,255,255,0.08)'}};
        copyBtn.onmouseleave=function(){{this.style.background='transparent'}};
        copyBtn.onclick = function() {{
            var txt = getMsgText();
            function showOk() {{
                copyBtn.innerHTML = '<svg width=\"16\" height=\"16\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#4CAF50\" stroke-width=\"2.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><polyline points=\"20 6 9 17 4 12\"></polyline></svg>';
                setTimeout(function(){{ copyBtn.innerHTML = '<svg width=\"16\" height=\"16\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#8e8ea0\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"9\" y=\"9\" width=\"13\" height=\"13\" rx=\"2\"></rect><path d=\"M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1\"></path></svg>'; }}, 2000);
            }}
            navigator.clipboard.writeText(txt).then(showOk).catch(function(){{
                var ta=doc.createElement('textarea'); ta.value=txt;
                doc.body.appendChild(ta); ta.select(); doc.execCommand('copy'); doc.body.removeChild(ta);
                showOk();
            }});
        }};
        bar.appendChild(copyBtn);
        msg.style.flexDirection='column';
        msg.appendChild(bar);
    }});
}}

setInterval(addActionButtons, 1000);

// Paste image support — lebih robust
function setupPaste() {{
    var pw = window.parent;

    // Hapus handler lama dulu
    if (pw._sigmaPasteHandler) {{
        pw.removeEventListener('paste', pw._sigmaPasteHandler, true);
        pw.document.removeEventListener('paste', pw._sigmaPasteHandler, true);
    }}

    function handlePaste(e) {{
        var items = e.clipboardData && e.clipboardData.items;
        if (!items) return;
        for (var i=0; i<items.length; i++) {{
            if (items[i].type.startsWith('image/')) {{
                var file = items[i].getAsFile();
                if (!file) continue;
                e.preventDefault();
                e.stopPropagation();
                var inputs = pw.document.querySelectorAll('input[type="file"]');
                for (var fi of inputs) {{
                    try {{
                        var dt = new DataTransfer();
                        dt.items.add(file);
                        Object.defineProperty(fi, 'files', {{value: dt.files, configurable:true, writable:true}});
                        fi.dispatchEvent(new Event('change', {{bubbles:true}}));
                        fi.dispatchEvent(new Event('input', {{bubbles:true}}));
                        var ta = pw.document.querySelector('[data-testid="stChatInput"] textarea');
                        if (ta) {{
                            ta.style.outline = '2px solid #4a90d9';
                            ta.placeholder = '📎 Gambar siap — ketik pertanyaan lalu Enter';
                            setTimeout(function(){{
                                ta.style.outline='';
                                ta.placeholder='Tanya SIGMA... DYOR - bukan financial advice.';
                            }}, 3000);
                            ta.focus();
                        }}
                        break;
                    }} catch(err) {{ console.log('paste err',err); }}
                }}
                break;
            }}
        }}
    }}

    pw._sigmaPasteHandler = handlePaste;
    pw.addEventListener('paste', handlePaste, true);
    pw.document.addEventListener('paste', handlePaste, true);
}}
setupPaste();
setTimeout(setupPaste, 1000);
setTimeout(setupPaste, 3000);

// ── Drag & Drop file (PDF/gambar) ke area chat ──
function setupDragDrop() {{
    var pw = window.parent;
    var pd = pw.document;
    if (pw._sigmaDragOK) return;

    // Overlay saat drag
    var overlay = pd.createElement('div');
    overlay.id = 'sigma-drop-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(27,42,74,0.55);z-index:99997;display:none;align-items:center;justify-content:center;pointer-events:none;';
    overlay.innerHTML = '<div style="background:#1B2A4A;color:#fff;border:2px dashed #4a90d9;border-radius:16px;padding:32px 48px;font-size:1.1rem;text-align:center;">📂 Lepaskan file di sini<br><span style="font-size:0.85rem;opacity:0.7;">PDF, PNG, JPG</span></div>';
    pd.body.appendChild(overlay);

    var dragCount = 0;

    pd.addEventListener('dragenter', function(e) {{
        e.preventDefault();
        dragCount++;
        overlay.style.display = 'flex';
    }}, true);

    pd.addEventListener('dragleave', function(e) {{
        dragCount--;
        if (dragCount <= 0) {{ dragCount = 0; overlay.style.display = 'none'; }}
    }}, true);

    pd.addEventListener('dragover', function(e) {{
        e.preventDefault();
    }}, true);

    pd.addEventListener('drop', function(e) {{
        e.preventDefault();
        dragCount = 0;
        overlay.style.display = 'none';

        var files = e.dataTransfer && e.dataTransfer.files;
        if (!files || files.length === 0) return;

        var file = files[0];
        var allowed = ['application/pdf','image/png','image/jpeg','image/jpg'];
        if (!allowed.includes(file.type)) {{
            alert('File tidak didukung. Gunakan PDF, PNG, atau JPG.');
            return;
        }}

        // Inject ke file input Streamlit
        var inputs = pd.querySelectorAll('input[type="file"]');
        for (var fi of inputs) {{
            try {{
                var dt = new DataTransfer();
                dt.items.add(file);
                Object.defineProperty(fi, 'files', {{value: dt.files, configurable:true, writable:true}});
                fi.dispatchEvent(new Event('change', {{bubbles:true}}));
                fi.dispatchEvent(new Event('input', {{bubbles:true}}));
                var ta = pd.querySelector('[data-testid="stChatInput"] textarea');
                if (ta) {{
                    ta.style.outline = '2px solid #4a90d9';
                    var fname = file.name;
                    ta.placeholder = '📎 ' + fname + ' siap — ketik pertanyaan lalu Enter';
                    setTimeout(function(){{
                        ta.style.outline = '';
                        ta.placeholder = 'Tanya SIGMA... DYOR - bukan financial advice.';
                    }}, 3000);
                    ta.focus();
                }}
                break;
            }} catch(err) {{ console.log('drop err', err); }}
        }}
    }}, true);

    pw._sigmaDragOK = true;
}}
setupDragDrop();
setTimeout(setupDragDrop, 2000);
</script>
""", height=0)
