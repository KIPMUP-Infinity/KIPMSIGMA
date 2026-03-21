import streamlit as st
from groq import Groq
import yfinance as yf
import fitz  # PyMuPDF untuk PDF
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


# ── FILE-BASED PERSISTENCE ────────────────────────────────
DATA_DIR = ".sigma_data"
os.makedirs(DATA_DIR, exist_ok=True)

def _user_key(email):
    return hashlib.md5(email.encode()).hexdigest()

def save_user_data(email, data):
    """Simpan theme + sessions ke file JSON berdasarkan email."""
    try:
        path = os.path.join(DATA_DIR, f"{_user_key(email)}.json")
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False)
    except: pass

def load_user_data(email):
    """Muat data user dari file."""
    try:
        path = os.path.join(DATA_DIR, f"{_user_key(email)}.json")
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except: pass
    return None


st.set_page_config(page_title="KIPM SIGMA", layout="wide", initial_sidebar_state="expanded")

# ── DYNAMIC THEME CSS ────────────────────────────────────
_t = st.session_state.get("theme", "dark")
_is_dark = _t == "dark"

# Warna ChatGPT-style
_bg              = "#212121"  if _is_dark else "#ffffff"
_sidebar_bg      = "#171717"  if _is_dark else "#e3e3e3"
_text            = "#ececec"  if _is_dark else "#0d0d0d"
_text_muted      = "#8e8ea0"  if _is_dark else "#6e6e80"
_border          = "#2f2f2f"  if _is_dark else "#e5e5e5"
_btn_hover       = "#2f2f2f"  if _is_dark else "#d8d8d8"
_btn_color       = "#ececec"  if _is_dark else "#0d0d0d"
_assistant_color = "#ececec"  if _is_dark else "#0d0d0d"
_header_color    = "#ffffff"  if _is_dark else "#0d0d0d"
_sub_color       = "#8e8ea0"  if _is_dark else "#6e6e80"
_input_bg        = "#2f2f2f"  if _is_dark else "#e8e8e8"
_input_border    = "#3f3f3f"  if _is_dark else "#e5e5e5"
_divider_color   = "#2f2f2f"  if _is_dark else "#e5e5e5"
_assistant_bg    = "transparent"
_assistant_brd   = "none"
_user_bubble     = "#2f2f2f"  if _is_dark else "#dcdcdc"
_sidebar_label   = "#8e8ea0"  if _is_dark else "#6e6e80"
_active_chat_bg  = "#2f2f2f"  if _is_dark else "#d8d8d8"
_active_chat_clr = "#ffffff"  if _is_dark else "#0d0d0d"
_inactive_chat   = "#ececec"  if _is_dark else "#0d0d0d"
_sidebar_border  = "none"     if _is_dark else "1px solid #e5e5e5"

st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/icon?family=Material+Icons');

    * {{
        font-family: ui-sans-serif, -apple-system, system-ui, "Segoe UI",
                     Helvetica, Arial, sans-serif !important;
    }}
    .material-icons {{ font-family: 'Material Icons' !important; }}

    /* ── GLOBAL BACKGROUND ── */
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stAppViewContainer"] > section,
    section[data-testid="stMain"],
    [data-testid="stMainBlockContainer"],
    [data-testid="stBottom"],
    [data-testid="stBottom"] > div {{
        background-color: {_bg} !important;
    }}


    /* ── SIDEBAR BACKGROUND — cover semua layer ── */
    section[data-testid="stSidebar"],
    section[data-testid="stSidebar"] > div,
    section[data-testid="stSidebar"] > div > div,
    section[data-testid="stSidebar"] > div > div > div,
    section[data-testid="stSidebar"] > div > div > div > div,
    [data-testid="stSidebarContent"],
    [data-testid="stSidebarUserContent"],
    [data-testid="stSidebarUserContent"] > div,
    [data-testid="stSidebarUserContent"] > div > div {{
        background-color: {_sidebar_bg} !important;
        box-shadow: none !important;
    }}
    section[data-testid="stSidebar"] {{
        border-right: {"none" if _is_dark else "1px solid #e5e5e5"} !important;
    }}

    /* ── FORCE ALL SIDEBAR PADDING = 0 ── */
    section[data-testid="stSidebar"] > div,
    section[data-testid="stSidebar"] > div > div,
    section[data-testid="stSidebar"] > div > div > div,
    [data-testid="stSidebarContent"],
    [data-testid="stSidebarUserContent"],
    [data-testid="stSidebarUserContent"] > div,
    [data-testid="stSidebarUserContent"] > div > div {{
        padding-top: 0 !important;
        margin-top: 0 !important;
    }}

    /* ── TOMBOL COLLAPSE — biarkan Streamlit default, hanya hide teks ── */
    [data-testid="stSidebarCollapseButton"] span[style*="overflow"],
    [data-testid="collapsedControl"] span[style*="overflow"] {{
        display: none !important;
    }}

    /* ── SIDEBAR LAYOUT — flex column agar sticky bottom bekerja ── */
    section[data-testid="stSidebar"] > div:first-child {{
        display: flex !important;
        flex-direction: column !important;
        height: 100vh !important;
        overflow: hidden !important;
    }}
    section[data-testid="stSidebar"] > div:first-child > div:first-child {{
        flex: 1 !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;
    }}

    /* ── TOMBOL OBROLAN BARU ── */
    section[data-testid="stSidebar"] .stButton > button {{
        background: transparent !important;
        border: none !important; box-shadow: none !important;
        color: {_text} !important;
        font-size: 0.875rem !important;
        padding: 8px 12px !important;
        border-radius: 8px !important; width: 100% !important;
        display: flex !important; align-items: center !important;
        justify-content: flex-start !important;
    }}
    section[data-testid="stSidebar"] .stButton > button:hover {{
        background: {_btn_hover} !important;
    }}
    section[data-testid="stSidebar"] .stButton > button p {{
        margin: 0 !important; text-align: left !important;
        color: inherit !important;
    }}
    }}

    /* ── CHAT MESSAGES — ASSISTANT ── */
    [data-testid="stChatMessage"] {{
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }}
    /* Sembunyikan avatar user DAN assistant — biar bersih seperti ChatGPT */
    [data-testid="stChatMessageAvatarUser"],
    [data-testid="stChatMessageAvatarAssistant"] {{
        display: none !important;
    }}
    [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {{
        font-size: 0.93rem !important;
        line-height: 1.75 !important;
        color: {_assistant_color} !important;
        background: transparent !important;
    }}

    /* ── MAIN CONTENT TEXT ── */
    [data-testid="stMainBlockContainer"] p,
    [data-testid="stMainBlockContainer"] li,
    [data-testid="stMainBlockContainer"] h1,
    [data-testid="stMainBlockContainer"] h2,
    [data-testid="stMainBlockContainer"] h3 {{
        color: {_text} !important;
    }}
    [data-testid="stMainBlockContainer"] {{
        padding-bottom: 80px !important;
        max-width: 780px !important;
        margin: 0 auto !important;
    }}

    /* ── HEADER TITLE ── */
    .main-header {{ text-align: center; margin-bottom: 2rem; }}
    .main-header h1 {{ color: {_header_color} !important; }}
    .main-header p  {{ color: {_sub_color} !important; }}

    /* ── CHAT INPUT ── */
    div[data-testid="stChatInputContainer"] {{
        border: 1px solid {_input_border} !important;
        background-color: {_input_bg} !important;
        border-radius: 12px !important;
    }}
    [data-testid="stChatInput"] textarea {{
        background-color: {_input_bg} !important;
        color: {_text} !important;
    }}
    [data-testid="stChatInput"] textarea::placeholder {{
        color: {_text_muted} !important;
    }}
    [data-testid="stChatInputContainer"] textarea:focus {{
        box-shadow: none !important;
        outline: none !important;
    }}

    footer {{ visibility: hidden; }}
    #MainMenu {{ visibility: hidden; }}

    /* Sembunyikan tombol collapse bawaan Streamlit */
    [data-testid="collapsedControl"],
    [data-testid="stSidebarCollapseButton"] {{
        display: none !important;
    }}
    </style>
""", unsafe_allow_html=True)



# ── GOOGLE OAUTH ──────────────────────────────────────────
def show_login_page():
    st.markdown("""
        <style>
        [data-testid="stSidebar"] { display: none !important; }
        [data-testid="stMainBlockContainer"] {
            max-width: 420px !important;
            margin: 8vh auto 0 auto !important;
            padding-bottom: 0 !important;
        }
        </style>
    """, unsafe_allow_html=True)

    try:
        logo = Image.open("Mate KIPM LOGO.png")
        c1, c2, c3 = st.columns([1, 1, 1])
        with c2: st.image(logo, use_container_width=True)
    except: pass

    st.markdown("""
        <div style="text-align:center;margin:24px 0 32px;font-family:Inter,sans-serif;">
            <h2 style="margin:0;font-size:1.6rem;font-weight:700;color:#fff;">Masuk ke SIGMA</h2>
            <p style="margin:8px 0 0;color:#888;font-size:0.9rem;">
                Platform analisa saham KIPM Universitas Pancasila
            </p>
        </div>
    """, unsafe_allow_html=True)

    client_id    = st.secrets.get("GOOGLE_CLIENT_ID", "")
    redirect_uri = st.secrets.get("GOOGLE_REDIRECT_URI", "")

    if not client_id or not redirect_uri:
        st.error("Isi GOOGLE_CLIENT_ID dan GOOGLE_REDIRECT_URI di Streamlit Secrets.")
        st.stop()

    params = {
        "client_id": client_id, "redirect_uri": redirect_uri,
        "response_type": "code", "scope": "openid email profile",
        "access_type": "offline", "prompt": "select_account",
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

    st.markdown(f"""
        <a href="{auth_url}" style="
            display:flex;align-items:center;justify-content:center;gap:10px;
            background:#fff;color:#1a1a1a;border-radius:10px;padding:13px 20px;
            text-decoration:none;font-size:0.95rem;font-weight:500;
            font-family:Inter,sans-serif;border:1px solid #ddd;">
            <svg width="20" height="20" viewBox="0 0 24 24">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/>
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg>
            Lanjutkan dengan Google
        </a>
        <p style="text-align:center;color:#555;font-size:0.75rem;margin-top:20px;font-family:Inter,sans-serif;">
            Dengan masuk, kamu menyetujui penggunaan platform ini untuk analisa pasar modal.
        </p>
    """, unsafe_allow_html=True)
    st.stop()


def handle_oauth_callback():
    code         = st.query_params.get("code", "")
    client_id    = st.secrets.get("GOOGLE_CLIENT_ID", "")
    client_sec   = st.secrets.get("GOOGLE_CLIENT_SECRET", "")
    redirect_uri = st.secrets.get("GOOGLE_REDIRECT_URI", "")

    if not all([code, client_id, client_sec, redirect_uri]):
        st.error(f"Config missing — code:{bool(code)} id:{bool(client_id)} sec:{bool(client_sec)} uri:{bool(redirect_uri)}")
        return None

    r = requests.post("https://oauth2.googleapis.com/token", data={
        "code": code, "client_id": client_id, "client_secret": client_sec,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    })

    if r.status_code != 200:
        st.error(f"Token error {r.status_code}: {r.text}")
        return None

    token = r.json().get("access_token", "")
    if not token:
        st.error(f"No token in response: {r.json()}")
        return None

    u = requests.get("https://www.googleapis.com/oauth2/v2/userinfo",
                     headers={"Authorization": f"Bearer {token}"})
    return u.json() if u.status_code == 200 else None


# ── CEK LOGIN ─────────────────────────────────────────────
if "user" not in st.session_state:
    st.session_state.user = None
if "theme" not in st.session_state:
    st.session_state.theme = "dark"
if "data_loaded" not in st.session_state:
    st.session_state.data_loaded = False

# ── HANDLE OAUTH CALLBACK ──────────────────────────────────
if "code" in st.query_params and st.session_state.user is None:
    info = handle_oauth_callback()
    if info:
        st.session_state.user = info
        saved = load_user_data(info["email"])
        if saved:
            st.session_state.theme = saved.get("theme", "dark")
            if saved.get("sessions"):
                st.session_state.sessions  = saved["sessions"]
                st.session_state.active_id = saved.get("active_id", saved["sessions"][0]["id"])
        # Buat token unik untuk sesi ini
        token = str(uuid.uuid4()).replace("-","")
        token_file = os.path.join(DATA_DIR, f"token_{token}.json")
        with open(token_file, "w") as f:
            json.dump(info, f)
        # Simpan token ke session state — akan dikirim ke localStorage via JS
        st.session_state.new_token = token
        st.query_params.clear()
        st.rerun()
    else:
        st.error("Login gagal. Coba lagi.")
        st.query_params.clear()

# ── RESTORE DARI TOKEN (query param yang dikirim JS) ───────
if "sigma_token" in st.query_params and st.session_state.user is None:
    token = st.query_params.get("sigma_token", "")
    # Cari file user berdasarkan token
    token_file = os.path.join(DATA_DIR, f"token_{token}.json")
    if os.path.exists(token_file):
        try:
            with open(token_file) as f:
                user_info = json.load(f)
            st.session_state.user = user_info
            saved = load_user_data(user_info["email"])
            if saved:
                st.session_state.theme = saved.get("theme", "dark")
                if saved.get("sessions"):
                    st.session_state.sessions  = saved["sessions"]
                    st.session_state.active_id = saved.get("active_id", saved["sessions"][0]["id"])
            st.session_state.data_loaded = True
        except: pass
    st.query_params.clear()
    if st.session_state.user:
        st.rerun()

# ── RESTORE SESSION DATA ────────────────────────────────────
if st.session_state.user is not None and not st.session_state.data_loaded:
    saved = load_user_data(st.session_state.user["email"])
    if saved:
        st.session_state.theme = saved.get("theme", "dark")
        if saved.get("sessions") and "sessions" not in st.session_state:
            st.session_state.sessions  = saved["sessions"]
            st.session_state.active_id = saved.get("active_id", saved["sessions"][0]["id"])
    st.session_state.data_loaded = True

# ── JIKA BELUM LOGIN ────────────────────────────────────────
if st.session_state.user is None:
    show_login_page()
    st.stop()

user = st.session_state.user
SYSTEM_PROMPT = {
    "role": "system",
    "content": """Kamu adalah SIGMA — analis saham dan chart expert dari KIPM Universitas Pancasila.

Kamu menggunakan framework analisa MnM Strategy+ yang terdiri dari 5 modul:

1. INVERSION FAIR VALUE GAP (IFVG)
- FVG terbentuk saat gap antara candle 1 dan 3 (low[0]>high[2]=bullish, high[0]<low[2]=bearish)
- IFVG = FVG yang diinversi → zona confluence kuat
- Bullish IFVG (kotak biru): harga break bawah FVG bullish → jadi resistance → tembus naik = sinyal buy
- Bearish IFVG (kotak abu): harga break atas FVG bearish → jadi support → tembus turun = sinyal sell
- Midline (garis putus) = 50% retracement, magnet harga

2. FAIR VALUE GAP (FVG)
- Gap harga belum terisi = imbalance = magnet harga
- Bullish FVG (biru): low[0] > high[2] → support potensial
- Bearish FVG (abu): high[0] < low[2] → resistance potensial
- Termitigasi saat close menembus batas FVG

3. ORDER BLOCK (OB)
- Bullish OB (hijau): candle bearish terakhir sebelum impuls naik → demand institusional
- Bearish OB (ungu): candle bullish terakhir sebelum impuls turun → supply institusional
- Breaker Block: OB yang ditembus → zona berlawanan
- OB + FVG/IFVG = confluence entry terkuat

4. SUPPLY & DEMAND ZONES
- Supply (abu): 3 candle bearish + volume above average → distribusi bandar
- Demand (biru terang): 3 candle bullish + volume above average → akumulasi bandar
- Delta volume: "Supply: -956M | 6.88%" = distribusi; "Demand: 783M | 5.61%" = akumulasi
- Border dashed = zona sedang diuji; zona dihapus saat close tembus

5. MOVING AVERAGE
- EMA 13 (biru) = momentum pendek; EMA 21 (merah) = medium; EMA 50 (ungu) = trend
- Di atas semua MA = bullish; di bawah = bearish; MA rapat = konsolidasi

URUTAN ANALISA:
1. Bias → posisi harga vs Supply/Demand terbesar
2. Struktur → OB aktif, swing high/low
3. Confluence → FVG + IFVG + OB overlap
4. Bandarmologi → delta volume (akumulasi vs distribusi)
5. Entry trigger → confluence + konfirmasi candle

FORMAT TRADE PLAN (SELALU GUNAKAN):
📊 TRADE PLAN — [SAHAM] ([TIMEFRAME])
⚡ Bias: [Bullish/Bearish/Sideways] — [alasan singkat]
🎯 Entry: [harga/range]
🛑 Stop Loss: [harga] — [alasan]
✅ Target 1: [harga] — [alasan]
✅ Target 2: [harga] — [alasan]
📦 Bandarmologi: [ringkasan delta volume]
⚠️ Invalidasi: [kondisi batal]

ATURAN:
- WAJIB analisa gambar langsung, JANGAN bilang tidak bisa melihat
- Warna: biru gelap=FVG/demand, abu=supply/bearish, hijau=bullish OB, ungu=bearish OB
- Selalu komentari angka delta volume di chart
- Jawab Bahasa Indonesia, tegas, no-bias"""
}

def new_session():
    return {"id": str(uuid.uuid4())[:8], "title": "Obrolan Baru",
            "messages": [SYSTEM_PROMPT], "created": datetime.now().strftime("%H:%M")}

if "sessions" not in st.session_state:
    s = new_session()
    st.session_state.sessions  = [s]
    st.session_state.active_id = s["id"]
else:
    # Pastikan setiap sesi yang di-restore punya system prompt yang benar
    for s in st.session_state.sessions:
        if not s["messages"] or s["messages"][0].get("role") != "system":
            s["messages"].insert(0, SYSTEM_PROMPT)
        else:
            s["messages"][0] = SYSTEM_PROMPT  # update system prompt terbaru
if "rename_id"  not in st.session_state: st.session_state.rename_id  = None
if "img_data"   not in st.session_state: st.session_state.img_data   = None
if "pdf_data"   not in st.session_state: st.session_state.pdf_data   = None

def get_active():
    for s in st.session_state.sessions:
        if s["id"] == st.session_state.active_id: return s
    return st.session_state.sessions[0]

def delete_session(sid):
    st.session_state.sessions = [s for s in st.session_state.sessions if s["id"] != sid]
    if not st.session_state.sessions:
        ns = new_session(); st.session_state.sessions = [ns]
    if st.session_state.active_id == sid:
        st.session_state.active_id = st.session_state.sessions[0]["id"]


# ── SIDEBAR ACTIONS VIA QUERY PARAMS ─────────────────────
qp = st.query_params
if "action" in qp:
    a = qp.get("action","")
    if a == "logout":
        # Hapus semua token file user ini
        if st.session_state.user:
            try:
                for f in os.listdir(DATA_DIR):
                    if f.startswith("token_"):
                        os.remove(os.path.join(DATA_DIR, f))
            except: pass
        st.session_state.clear()
        st.query_params.clear()
        st.rerun()


# ── SIDEBAR ───────────────────────────────────────────────
_stext = "#ececec" if _is_dark else "#0d0d0d"
_shov  = "#2f2f2f" if _is_dark else "#d8d8d8"
_sact  = "#343434" if _is_dark else "#e8e8e8"
_slbl  = "#8e8ea0" if _is_dark else "#6e6e80"

# Load logo sebagai base64
try:
    _logo_img = Image.open("Mate KIPM LOGO.png")
    _buf = io.BytesIO()
    _logo_img.save(_buf, format="PNG")
    _logo_b64 = base64.b64encode(_buf.getvalue()).decode()
    _logo_src = f"data:image/png;base64,{_logo_b64}"
except:
    _logo_src = ""

with st.sidebar:
    st.markdown(f"""
        <style>
        /* Force semua padding = 0 */
        [data-testid="stSidebarUserContent"],
        [data-testid="stSidebarUserContent"] > div,
        [data-testid="stSidebarUserContent"] > div > div {{
            padding-top: 0 !important;
            margin-top: 0 !important;
        }}
        /* Sembunyikan teks keyboard icon */
        [data-testid="stSidebarCollapseButton"] span,
        [data-testid="collapsedControl"] span,
        button[kind="header"] span {{
            font-size: 0 !important;
            width: 0 !important;
            height: 0 !important;
            overflow: hidden !important;
            display: block !important;
        }}
        /* Logo + org block */
        .sb-top {{
            text-align: center;
            padding: 8px 12px 10px;
            font-family: Inter, sans-serif;
        }}
        .sb-top img {{
            width: 72px; height: 72px;
            object-fit: contain;
            display: block;
            margin: 0 auto 6px;
        }}
        .sb-top .sb-sub {{
            font-size: 0.7rem;
            color: {_slbl};
            margin: 0;
            line-height: 1.4;
        }}
        .sb-top .sb-name {{
            font-size: 0.9rem;
            font-weight: 700;
            color: {'#fff' if _is_dark else '#0d0d0d'};
            margin: 2px 0 0;
        }}
        .sb-divider {{
            border: none;
            border-top: 1px solid {'#2f2f2f' if _is_dark else '#e5e5e5'};
            margin: 4px 0 6px;
        }}
        /* Obrolan baru button */
        section[data-testid="stSidebar"] .stButton > button {{
            background: transparent !important;
            border: none !important; box-shadow: none !important;
            color: {_stext} !important;
            font-size: 0.875rem !important;
            padding: 7px 12px !important;
            border-radius: 8px !important; width: 100% !important;
            display: flex !important; align-items: center !important;
            justify-content: flex-start !important;
            text-align: left !important;
        }}
        section[data-testid="stSidebar"] .stButton > button:hover {{
            background: {_shov} !important;
        }}
        section[data-testid="stSidebar"] .stButton > button p,
        section[data-testid="stSidebar"] .stButton > button span,
        section[data-testid="stSidebar"] .stButton > button div {{
            margin: 0 !important; text-align: left !important;
            color: inherit !important;
            justify-content: flex-start !important;
            width: 100% !important;
        }}
        /* Label seksi */
        .sb-lbl {{
            font-size: 0.7rem; font-weight: 500;
            color: {_slbl};
            padding: 8px 12px 3px;
            display: block; font-family: Inter, sans-serif;
        }}
        /* ChatGPT-style chat item */
        .sb-item {{
            display: flex; align-items: center;
            padding: 6px 12px; border-radius: 8px;
            margin: 1px 4px; cursor: pointer;
            font-size: 0.875rem; font-family: Inter, sans-serif;
            color: {_stext}; text-decoration: none;
            overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
            position: relative;
        }}
        .sb-item:hover {{ background: {_shov}; }}
        .sb-item.active {{ background: {_sact}; }}
        .sb-item-title {{
            flex: 1; overflow: hidden;
            text-overflow: ellipsis; white-space: nowrap;
        }}
        .sb-item-acts {{
            display: none; gap: 2px; flex-shrink: 0;
        }}
        .sb-item:hover .sb-item-acts,
        .sb-item.active .sb-item-acts {{
            display: flex;
        }}
        .sb-btn {{
            font-size: 0.72rem; padding: 2px 5px;
            border-radius: 4px; cursor: pointer;
            color: {_slbl}; background: transparent;
            border: none;
        }}
        .sb-btn:hover {{ color: {'#fff' if _is_dark else '#000'}; }}
        .sb-btn-del:hover {{ color: #f55 !important; }}
        </style>

        <div class="sb-top">
            {"" if not _logo_src else f'<img src="{_logo_src}">'}
            <p class="sb-sub">KOMUNITAS <span style="color:#F5C242;font-weight:600;">INVESTASI</span> PASAR MODAL</p>
            <p class="sb-name">UNIVERSITAS PANCASILA</p>
        </div>
        <hr class="sb-divider">
    """, unsafe_allow_html=True)

    # Inject Lucide icons script sekali
    st.markdown("""
        <script src="https://unpkg.com/lucide@latest"></script>
        <script>document.addEventListener('DOMContentLoaded', function() {{ if(window.lucide) lucide.createIcons(); }});</script>
    """, unsafe_allow_html=True)

    if st.button("◎  Obrolan baru", key="btn_new_chat", use_container_width=True):
        ns = new_session()
        st.session_state.sessions.insert(0, ns)
        st.session_state.active_id = ns["id"]
        st.rerun()

    st.markdown('<span class="sb-lbl">Obrolan Anda</span>', unsafe_allow_html=True)

    for sesi in st.session_state.sessions:
        sid = sesi["id"]
        is_active = sid == st.session_state.active_id
        title_d = sesi["title"][:22] + "..." if len(sesi["title"]) > 22 else sesi["title"]

        if st.session_state.rename_id == sid:
            new_t = st.text_input("Rename", value=sesi["title"], key=f"ren_{sid}", label_visibility="collapsed")
            co, cc = st.columns([1,1])
            with co:
                if st.button("✓", key=f"ok_{sid}"):
                    sesi["title"] = new_t.strip() or sesi["title"]
                    st.session_state.rename_id = None; st.rerun()
            with cc:
                if st.button("✗", key=f"cx_{sid}"):
                    st.session_state.rename_id = None; st.rerun()
        else:
            if is_active:
                c1, c2, c3 = st.columns([6, 1, 1])
                with c1:
                    if st.button(title_d, key=f"sel_{sid}", use_container_width=True):
                        st.session_state.active_id = sid
                        st.session_state.rename_id = None
                        st.rerun()
                with c2:
                    if st.button("◎", key=f"ren_{sid}"):
                        st.session_state.rename_id = sid; st.rerun()
                with c3:
                    if st.button("⊘", key=f"del_{sid}"):
                        delete_session(sid); st.rerun()
            else:
                if st.button(title_d, key=f"sel_{sid}", use_container_width=True):
                    st.session_state.active_id = sid
                    st.session_state.rename_id = None
                    st.rerun()

    # ── SETTINGS di bawah sidebar ── pure Streamlit, pasti muncul
    st.divider()
    if "show_settings" not in st.session_state:
        st.session_state.show_settings = False

    if st.button("⚙  Pengaturan", key="btn_settings", use_container_width=True):
        st.session_state.show_settings = not st.session_state.show_settings
        st.rerun()

    if st.session_state.show_settings:
        _cur_theme = st.session_state.get("theme", "dark")
        st.markdown(f'<p style="font-size:0.7rem;color:{"#8e8ea0" if _is_dark else "#6e6e80"};padding:4px 12px 2px;margin:0;">PENAMPILAN</p>', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🌙 Gelap", key="btn_dark", disabled=_cur_theme=="dark", use_container_width=True):
                st.session_state.theme = "dark"; st.session_state.show_settings = False; st.rerun()
        with col2:
            if st.button("☀️ Terang", key="btn_light", disabled=_cur_theme=="light", use_container_width=True):
                st.session_state.theme = "light"; st.session_state.show_settings = False; st.rerun()
        st.divider()
        if st.button("🚪 Keluar", key="btn_logout", use_container_width=True):
            st.session_state.clear(); st.rerun()

# Handle sidebar HTML nav actions
if "sb_sel" in st.query_params:
    st.session_state.active_id = st.query_params["sb_sel"]
    st.session_state.rename_id = None
    st.query_params.clear(); st.rerun()
if "sb_del" in st.query_params:
    delete_session(st.query_params["sb_del"])
    st.query_params.clear(); st.rerun()
if "sb_ren" in st.query_params:
    st.session_state.rename_id = st.query_params["sb_ren"]
    st.query_params.clear(); st.rerun()
if "action" in st.query_params:
    _a = st.query_params.get("action","")
    if _a == "theme_dark":
        st.session_state.theme = "dark"; st.query_params.clear(); st.rerun()
    elif _a == "theme_light":
        st.session_state.theme = "light"; st.query_params.clear(); st.rerun()
    elif _a == "logout":
        st.session_state.clear(); st.query_params.clear(); st.rerun()

# ── TOMBOL TOGGLE SIDEBAR CUSTOM ──────────────────────────
if "sidebar_open" not in st.session_state:
    st.session_state.sidebar_open = True

_sb_icon = "‹" if st.session_state.sidebar_open else "›"
_sb_left = "244px" if st.session_state.sidebar_open else "0px"

st.markdown(f"""
    <style>
    {'section[data-testid="stSidebar"] {{ display: none !important; }}' if not st.session_state.sidebar_open else ''}
    /* Tombol toggle custom */
    div[data-testid="stMainBlockContainer"] > div > div > div:first-child .stButton > button#sb_toggle_btn,
    .stButton button[kind="secondary"][id="sb_toggle_btn"] {{
        position: fixed !important;
        top: 50% !important;
        transform: translateY(-50%) !important;
        left: {_sb_left} !important;
        width: 18px !important;
        height: 48px !important;
        min-height: 0 !important;
        background: {_sidebar_bg} !important;
        color: {_text_muted} !important;
        border: none !important;
        border-radius: 0 6px 6px 0 !important;
        cursor: pointer !important;
        z-index: 9999 !important;
        font-size: 18px !important;
        padding: 0 !important;
        line-height: 1 !important;
        box-shadow: 2px 0 6px rgba(0,0,0,0.2) !important;
    }}
    </style>
""", unsafe_allow_html=True)

if st.button(_sb_icon, key="sb_toggle_btn"):
    st.session_state.sidebar_open = not st.session_state.sidebar_open
    st.rerun()

# ── SETTINGS BOTTOM BAR — via components.html (JS manipulates sidebar DOM) ───
_cur_theme = st.session_state.get("theme", "dark")
_popup_bg      = "#2f2f2f" if _is_dark else "#e8e8e8"
_popup_border  = "#3f3f3f" if _is_dark else "#e5e5e5"
_popup_text    = "#ececec" if _is_dark else "#0d0d0d"
_popup_hover   = "#3f3f3f" if _is_dark else "#dcdcdc"
_bar_bg        = "#171717" if _is_dark else "#e3e3e3"
_bar_border    = "#2f2f2f" if _is_dark else "#e5e5e5"
_bar_text      = "#8e8ea0" if _is_dark else "#6e6e80"
_active_dot    = "#4a90d9" if _is_dark else "#1a4fa8"
_theme_dark_check  = "✓" if _cur_theme == "dark"  else ""
_theme_light_check = "✓" if _cur_theme == "light" else ""

components.html(f"""
<script>
(function() {{
    function fixSidebarTop() {{
        var pd = window.parent.document;
        var sbg = '{_sidebar_bg}';

        // Inject CSS ke head parent dengan specificity tertinggi — override inline style
        var headStyleId = 'sigma-force-top';
        var headStyle = pd.getElementById(headStyleId);
        if (!headStyle) {{
            headStyle = pd.createElement('style');
            headStyle.id = headStyleId;
            pd.head.appendChild(headStyle);
        }}
        headStyle.textContent = [
            '[data-testid="stSidebarUserContent"] {{',
            '  padding-top: 0 !important;',
            '  margin-top: 0 !important;',
            '}}',
            '[data-testid="stSidebarContent"] {{',
            '  padding-top: 0 !important;',
            '  margin-top: 0 !important;',
            '}}',
            'section[data-testid="stSidebar"] > div > div {{',
            '  padding-top: 0 !important;',
            '  margin-top: 0 !important;',
            '}}'
        ].join('\n');

        // Direct inline style — hapus padding yang sudah ada lalu set 0
        [
            '[data-testid="stSidebarUserContent"]',
            '[data-testid="stSidebarContent"]',
            'section[data-testid="stSidebar"] > div',
            'section[data-testid="stSidebar"] > div > div',
            'section[data-testid="stSidebar"] > div > div > div'
        ].forEach(function(sel) {{
            pd.querySelectorAll(sel).forEach(function(el) {{
                el.style.removeProperty('padding-top');
                el.style.removeProperty('margin-top');
                el.style.paddingTop = '0px';
                el.style.marginTop = '0px';
            }});
        }});
    }}

    function injectToggleBtn() {{
        var pd = window.parent.document;
        if (pd.getElementById('sigma-toggle-btn')) return;

        var sbg = '{_sidebar_bg}';
        var clr = '{_text_muted}';

        var btn = pd.createElement('button');
        btn.id = 'sigma-toggle-btn';
        btn.innerHTML = '&#8249;';
        btn.style.cssText = [
            'position:fixed',
            'top:50%',
            'transform:translateY(-50%)',
            'left:244px',
            'width:16px',
            'height:48px',
            'background:' + sbg,
            'color:' + clr,
            'border:none',
            'border-radius:0 6px 6px 0',
            'cursor:pointer',
            'z-index:9999',
            'font-size:18px',
            'line-height:1',
            'padding:0',
            'display:flex',
            'align-items:center',
            'justify-content:center',
            'transition:left 0.3s'
        ].join(';');

        btn.addEventListener('click', function() {{
            var sidebar = pd.querySelector('section[data-testid="stSidebar"]');
            var isOpen = sidebar && sidebar.getAttribute('aria-expanded') !== 'false'
                         && getComputedStyle(sidebar).width !== '0px';
            // Klik tombol collapse bawaan (tersembunyi tapi masih ada)
            var native = pd.querySelector('[data-testid="stSidebarCollapseButton"] button, [data-testid="collapsedControl"] button');
            if (native) native.click();
        }});

        pd.body.appendChild(btn);

        // Update posisi dan icon saat sidebar buka/tutup
        setInterval(function() {{
            var sidebar = pd.querySelector('section[data-testid="stSidebar"]');
            if (!sidebar) return;
            var w = sidebar.getBoundingClientRect().width;
            var b = pd.getElementById('sigma-toggle-btn');
            if (!b) return;
            if (w > 50) {{
                b.style.left = w + 'px';
                b.innerHTML = '&#8249;';
            }} else {{
                b.style.left = '0px';
                b.innerHTML = '&#8250;';
            }}
        }}, 300);
    }}
        var parentDoc = window.parent.document;
        var sidebar = parentDoc.querySelector('section[data-testid="stSidebar"] > div:first-child');
        if (!sidebar) return;

        // Cek sudah ada belum
        if (parentDoc.getElementById('sigma-settings-wrap')) return;

        // Buat wrapper settings di bawah sidebar
        var wrap = parentDoc.createElement('div');
        wrap.id = 'sigma-settings-wrap';
        wrap.style.cssText = [
            'position:fixed',
            'bottom:0',
            'left:0',
            'width:244px',
            'background:{_bar_bg}',
            'border-top:1px solid {_bar_border}',
            'z-index:999',
            'font-family:Inter,sans-serif'
        ].join(';');

        // ── Define sigmaSetTheme di window.parent DULU sebelum inject HTML ──
        window.parent.sigmaSetTheme = function(mode) {{
            var pd = window.parent.document;
            var isDark = mode === 'dark';
            var bg     = isDark ? '#212121' : '#ffffff';
            var sbg    = isDark ? '#171717' : '#f9f9f9';
            var txt    = isDark ? '#ececec' : '#0d0d0d';
            var inp    = isDark ? '#2f2f2f' : '#ffffff';
            var brd    = isDark ? '#3f3f3f' : '#e5e5e5';

            var styleId = 'sigma-live-theme';
            var el = pd.getElementById(styleId);
            if (!el) {{ el = pd.createElement('style'); el.id = styleId; pd.head.appendChild(el); }}

            el.textContent = `
                .stApp,
                [data-testid="stAppViewContainer"],
                [data-testid="stAppViewContainer"] > section,
                section[data-testid="stMain"],
                [data-testid="stMainBlockContainer"],
                [data-testid="stBottom"],
                [data-testid="stBottom"] > div,
                [data-testid="stVerticalBlock"] {{
                    background-color: ${{bg}} !important;
                }}
                section[data-testid="stSidebar"],
                section[data-testid="stSidebar"] > div,
                section[data-testid="stSidebar"] > div > div,
                section[data-testid="stSidebar"] [data-testid="stSidebarContent"],
                section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"],
                #sigma-settings-wrap {{
                    background-color: ${{sbg}} !important;
                }}
                #sp-btn {{ color: ${{isDark ? '#aaa' : '#5a6a82'}} !important; }}
                [data-testid="stMarkdownContainer"] p,
                [data-testid="stMarkdownContainer"] li,
                [data-testid="stMarkdownContainer"] h1,
                [data-testid="stMarkdownContainer"] h2,
                [data-testid="stMarkdownContainer"] h3,
                [data-testid="stMainBlockContainer"] p {{
                    color: ${{txt}} !important;
                }}
                .main-header h1 {{ color: ${{isDark ? '#fff' : '#1a1a2e'}} !important; }}
                .main-header p  {{ color: ${{isDark ? '#888' : '#5a6a82'}} !important; }}
                div[data-testid="stChatInputContainer"] {{
                    background-color: ${{inp}} !important;
                    border-color: ${{brd}} !important;
                }}
                [data-testid="stChatInput"] textarea {{
                    background-color: ${{inp}} !important;
                    color: ${{txt}} !important;
                }}
                div[data-testid="stSidebar"] .stButton > button {{
                    color: ${{isDark ? '#bbb' : '#2c3a52'}} !important;
                    background: transparent !important;
                    border: none !important;
                }}
            `;

            var ckDark  = pd.getElementById('sp-ck-dark');
            var ckLight = pd.getElementById('sp-ck-light');
            if (ckDark)  ckDark.textContent  = isDark  ? '✓' : '';
            if (ckLight) ckLight.textContent = !isDark ? '✓' : '';

            var pop = pd.getElementById('sp-popup');
            if (pop) pop.style.display = 'none';

            try {{ localStorage.setItem('sigma_theme', mode); }} catch(e) {{}}
        }};

        wrap.innerHTML = `
            <div id="sp-popup" style="
                display:none;position:absolute;bottom:100%;left:8px;right:8px;
                background:{_popup_bg};border:1px solid {_popup_border};
                border-radius:12px;box-shadow:0 -6px 28px rgba(0,0,0,0.3);
                overflow:hidden;margin-bottom:6px;font-family:Inter,sans-serif;
            ">
                <div style="padding:10px 14px 6px;font-size:0.68rem;font-weight:600;
                    color:{_bar_text};text-transform:uppercase;letter-spacing:1.2px;">
                    Penampilan
                </div>
                <div id="sp-theme-dark" class="sp-item" style="cursor:pointer;">
                    <span>Gelap</span><span id="sp-ck-dark" class="sp-ck" style="color:{_active_dot};font-weight:700;">{_theme_dark_check}</span>
                </div>
                <div id="sp-theme-light" class="sp-item" style="cursor:pointer;">
                    <span>Terang</span><span id="sp-ck-light" class="sp-ck" style="color:{_active_dot};font-weight:700;">{_theme_light_check}</span>
                </div>
                <div style="border-top:1px solid {_popup_border};margin:4px 0;"></div>
                <a href="?action=logout" target="_self" class="sp-item" style="color:#e55;cursor:pointer;">
                    <span>🚪 Keluar</span>
                </a>
            </div>

            <div id="sp-btn" style="
                display:flex;align-items:center;gap:8px;padding:11px 14px;
                cursor:pointer;color:{_bar_text};font-size:0.87rem;
                transition:background 0.15s;user-select:none;
            ">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" stroke-width="2"
                    stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="3"/>
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
                </svg>
                Pengaturan
            </div>

            <style>
            .sp-item {{
                display:flex;align-items:center;justify-content:space-between;
                padding:9px 16px;font-size:0.88rem;color:{_popup_text};
                text-decoration:none;transition:background 0.12s;
            }}
            .sp-item:hover {{ background:{_popup_hover}; }}
            </style>
        `;

        parentDoc.body.appendChild(wrap);

        // Pasang event listener setelah inject — bukan inline onclick
        // Ini yang benar karena kita akses fungsi di parentDoc scope langsung
        parentDoc.getElementById('sp-theme-dark').addEventListener('click', function() {{
            window.parent.sigmaSetTheme('dark');
        }});
        parentDoc.getElementById('sp-theme-light').addEventListener('click', function() {{
            window.parent.sigmaSetTheme('light');
        }});

        // Toggle popup
        var btn = parentDoc.getElementById('sp-btn');
        var pop = parentDoc.getElementById('sp-popup');
        btn.addEventListener('click', function(e) {{
            e.stopPropagation();
            pop.style.display = pop.style.display === 'block' ? 'none' : 'block';
        }});
        btn.addEventListener('mouseover', function() {{
            btn.style.background = '{_popup_hover}';
        }});
        btn.addEventListener('mouseout', function() {{
            btn.style.background = 'transparent';
        }});

        // Tutup saat klik di luar
        parentDoc.addEventListener('click', function(e) {{
            if (pop && btn && !btn.contains(e.target) && !pop.contains(e.target)) {{
                pop.style.display = 'none';
            }}
        }});
    }}

    // Apply theme dari localStorage saat load
    try {{
        var saved = localStorage.getItem('sigma_theme');
        if (saved) {{
            setTimeout(function() {{ window.parent.sigmaSetTheme(saved); }}, 600);
        }}
    }} catch(e) {{}}

    // Coba inject segera dan dengan retry
    fixSidebarTop();
    injectSettings();
    injectToggleBtn();
    setTimeout(function() {{ fixSidebarTop(); injectToggleBtn(); }}, 100);
    setTimeout(function() {{ fixSidebarTop(); injectSettings(); injectToggleBtn(); }}, 300);
    setTimeout(function() {{ fixSidebarTop(); injectSettings(); injectToggleBtn(); }}, 800);
    setTimeout(function() {{ fixSidebarTop(); injectSettings(); injectToggleBtn(); }}, 2000);
    setInterval(function() {{ fixSidebarTop(); }}, 5000);

    var obs = new MutationObserver(function() {{ fixSidebarTop(); injectSettings(); }});
    obs.observe(window.parent.document.body, {{childList:true, subtree:true}});
}})();
</script>
""", height=0)


# ── MAIN ─────────────────────────────────────────────────
active = get_active()

st.markdown("""
    <div class="main-header">
        <h1 style="margin:0;">  KIPM SIGMA ∑</h1>
        <p style="color:gray;">Strategic Intelligence & Global Market Analysis</p>
    </div>
""", unsafe_allow_html=True)

# Tampilkan history
for i, msg in enumerate(active["messages"][1:]):
    with st.chat_message(msg["role"]):
        display = msg["content"]
        if "Pertanyaan:" in display:
            display = display.split("Pertanyaan:")[-1].strip()
        key = f"thumb_{active['id']}_{i}"
        if msg["role"] == "user" and key in st.session_state:
            b64, mime = st.session_state[key]
            st.markdown(f'<img src="data:{mime};base64,{b64}" style="max-width:100%;max-height:240px;border-radius:10px;margin-bottom:6px;display:block;">', unsafe_allow_html=True)
        st.markdown(display)


# ── CHAT INPUT ────────────────────────────────────────────
# Coba gunakan accept_file (Streamlit >= 1.37)
try:
    result = st.chat_input(
        'Tanya SIGMA... DYOR - bukan financial advice.',
        accept_file="multiple",
        file_type=["pdf", "png", "jpg", "jpeg"]
    )
except TypeError:
    result = st.chat_input("Tanya SIGMA...")

# Parse result
prompt    = None
file_obj  = None

if result is not None:
    if hasattr(result, 'text'):
        # Streamlit 1.37+ object
        prompt   = (result.text or "").strip()
        files    = getattr(result, 'files', None) or []
        if files: file_obj = files[0]
    elif isinstance(result, str):
        prompt = result.strip()
    
    # Kalau ada file dari chat_input, proses langsung
    if file_obj is not None:
        raw = file_obj.read()
        if file_obj.type == "application/pdf":
            doc = fitz.open(stream=raw, filetype="pdf")
            pdf_text = "".join(p.get_text() for p in doc)
            st.session_state.pdf_data = (f"[PDF: {file_obj.name}]\n{pdf_text[:6000]}", file_obj.name)
            st.session_state.img_data = None
        else:
            b64  = base64.b64encode(raw).decode()
            ext  = file_obj.name.split(".")[-1].lower()
            mime = "image/png" if ext == "png" else "image/jpeg"
            st.session_state.img_data  = (b64, mime, file_obj.name)
            st.session_state.pdf_data  = None
    
    # Kalau prompt kosong tapi ada file, beri default prompt
    if not prompt and (file_obj or st.session_state.img_data or st.session_state.pdf_data):
        prompt = "Tolong analisa file yang saya kirim"

if prompt:
    # Ambil data attachment
    img_data = st.session_state.img_data
    pdf_data = st.session_state.pdf_data
    has_image = img_data is not None
    has_pdf   = pdf_data is not None

    # Reset attachment state
    st.session_state.img_data = None
    st.session_state.pdf_data = None

    # Bangun full prompt
    full_prompt = prompt
    if has_image:
        full_prompt = f"[Gambar: {img_data[2]}]\n\nPertanyaan: {prompt}"
    elif has_pdf:
        full_prompt = f"{pdf_data[0]}\n\nPertanyaan: {prompt}"

    # Auto-title
    if active["title"] == "Obrolan Baru":
        active["title"] = prompt[:40] + ("..." if len(prompt) > 40 else "")

    # Simpan thumbnail
    thumb_idx = len(active["messages"]) - 1
    if has_image:
        st.session_state[f"thumb_{active['id']}_{thumb_idx}"] = (img_data[0], img_data[1])

    # Tampilkan pesan user
    active["messages"].append({"role": "user", "content": full_prompt})
    with st.chat_message("user"):
        if has_image:
            st.markdown(
                f'<img src="data:{img_data[1]};base64,{img_data[0]}" style="max-width:100%;max-height:240px;border-radius:10px;margin-bottom:6px;display:block;">',
                unsafe_allow_html=True
            )
        st.markdown(prompt)

    # Panggil API
    try:
        groq_client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        with st.chat_message("assistant"):
            with st.spinner("SIGMA sedang menganalisis..."):
                if has_image:
                    res = groq_client.chat.completions.create(
                        model="meta-llama/llama-4-scout-17b-16e-instruct",
                        messages=[
                            {"role": "system", "content": (
                                "Kamu adalah SIGMA, analis chart expert. "
                                "Lihat gambar chart ini dengan seksama dan langsung analisa: "
                                "1) Nama saham & timeframe 2) Trend (uptrend/downtrend/sideways) "
                                "3) Support & Resistance 4) Pola teknikal 5) Volume & bandarmologi "
                                "6) Trade plan (entry, stop loss, target). "
                                "WAJIB analisa gambar secara langsung. Jawab Bahasa Indonesia."
                            )},
                            {"role": "user", "content": [
                                {"type": "image_url", "image_url": {
                                    "url": f"data:{img_data[1]};base64,{img_data[0]}"
                                }},
                                {"type": "text", "text": prompt}
                            ]}
                        ],
                        max_tokens=2048
                    )
                else:
                    res = groq_client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=active["messages"],
                        temperature=0.7,
                        max_tokens=2048
                    )
                ans = res.choices[0].message.content
            st.markdown(ans)
        active["messages"].append({"role": "assistant", "content": ans})

    except Exception as e:
        import traceback
        st.error(f"❌ Error: {e}")
        st.code(traceback.format_exc())

    st.rerun()


# ── SAVE DATA KE FILE (setiap render) ────────────────────
if st.session_state.user:
    _sessions_to_save = [
        {"id": s["id"], "title": s["title"], "created": s["created"],
         "messages": [m for m in s["messages"] if m["role"] != "system"]}
        for s in st.session_state.sessions
    ]
    save_user_data(st.session_state.user["email"], {
        "theme":     st.session_state.get("theme", "dark"),
        "sessions":  _sessions_to_save,
        "active_id": st.session_state.active_id,
    })

# ── KIRIM TOKEN BARU KE LOCALSTORAGE (sekali setelah login) ──
_new_token = st.session_state.pop("new_token", None)
if _new_token:
    components.html(f"""
<script>
try {{
    localStorage.setItem('sigma_token', '{_new_token}');
}} catch(e) {{}}
</script>
""", height=0)

# ── JS: Bubble user ke kanan + Ctrl+V paste support ──────
_bubble_color = "#1B2A4A"
_bubble_text  = "#ffffff"
components.html(f"""
<script>
const BUBBLE_COLOR = "{_bubble_color}";
const BUBBLE_TEXT  = "{_bubble_text}";
// Fix bubble kanan
function fixBubbles() {{
    const doc = window.parent.document;
    doc.querySelectorAll('[data-testid="stChatMessage"]').forEach(msg => {{
        const isUser = msg.querySelector('[data-testid="stChatMessageAvatarUser"]');
        if (!isUser) return;
        msg.style.cssText += 'display:flex!important;justify-content:flex-end!important;background:transparent!important;border:none!important;box-shadow:none!important;padding:4px 0!important;';
        const av = msg.querySelector('[data-testid="stChatMessageAvatarUser"]');
        if (av) av.style.display = 'none';
        const ct = msg.querySelector('[data-testid="stChatMessageContent"]');
        if (ct) ct.style.cssText += 'background:transparent!important;display:flex!important;justify-content:flex-end!important;max-width:100%!important;padding:0!important;';
        msg.querySelectorAll('[data-testid="stMarkdownContainer"]').forEach(md => {{
            md.style.background = 'transparent';
            md.style.display = 'flex';
            md.style.justifyContent = 'flex-end';
            var existing = md.querySelector('.navy-pill');
            if (existing) {{
                existing.style.backgroundColor = BUBBLE_COLOR;
                existing.querySelectorAll('*').forEach(el => el.style.color = BUBBLE_TEXT);
            }} else if (!md.querySelector('.navy-pill')) {{
                const pill = document.createElement('div');
                pill.className = 'navy-pill';
                pill.style.cssText = `background-color:${{BUBBLE_COLOR}};color:${{BUBBLE_TEXT}};border-radius:18px 18px 4px 18px;padding:10px 16px;max-width:72%;display:inline-block;font-size:0.93rem;line-height:1.6;font-family:Inter,sans-serif;word-wrap:break-word;`;
                while (md.firstChild) pill.appendChild(md.firstChild);
                md.appendChild(pill);
                pill.querySelectorAll('*').forEach(el => el.style.color = BUBBLE_TEXT);
            }} // end else
        }});
    }});
}}
fixBubbles();
setInterval(fixBubbles, 800);
new MutationObserver(() => setTimeout(fixBubbles, 100)).observe(
    window.parent.document.body, {{childList:true, subtree:true}}
);

// Ctrl+V paste gambar — listen di window.parent level
function handlePasteImage(file) {{
    const parentDoc = window.parent.document;

    // Cari file input dari st.chat_input (accept_file)
    const fileInputs = parentDoc.querySelectorAll('input[type="file"]');
    let injected = false;

    for (let fi of fileInputs) {{
        try {{
            const dt = new DataTransfer();
            dt.items.add(file);
            Object.defineProperty(fi, 'files', {{
                value: dt.files,
                configurable: true,
                writable: true
            }});
            fi.dispatchEvent(new Event('change', {{bubbles: true}}));
            fi.dispatchEvent(new Event('input', {{bubbles: true}}));
            injected = true;
            break;
        }} catch(err) {{}}
    }}

    if (injected) {{
        // Feedback visual di textarea
        const ta = parentDoc.querySelector('[data-testid="stChatInput"] textarea');
        if (ta) {{
            const prev = ta.placeholder;
            ta.style.border = '2px solid #0048ff';
            ta.placeholder = '📎 Gambar di-paste! Ketik pertanyaan lalu Enter...';
            setTimeout(() => {{
                ta.style.border = '';
                ta.placeholder = prev;
            }}, 3000);
            ta.focus();
        }}
    }}
    return injected;
}}

function setupPaste() {{
    const pw = window.parent;
    if (pw._sigmapasteOK) return;

    // Pasang di WINDOW level (bukan document) — ini yang benar untuk Chrome
    pw.addEventListener('paste', function(e) {{
        const items = e.clipboardData && e.clipboardData.items;
        if (!items) return;
        for (let item of items) {{
            if (item.type.startsWith('image/')) {{
                const file = item.getAsFile();
                if (file) {{
                    e.preventDefault();
                    e.stopPropagation();
                    handlePasteImage(file);
                }}
                break;
            }}
        }}
    }}, true); // useCapture=true agar tidak di-intercept Streamlit

    // Juga pasang di document untuk fallback
    pw.document.addEventListener('paste', function(e) {{
        const items = e.clipboardData && e.clipboardData.items;
        if (!items) return;
        for (let item of items) {{
            if (item.type.startsWith('image/')) {{
                const file = item.getAsFile();
                if (file) {{
                    e.preventDefault();
                    handlePasteImage(file);
                }}
                break;
            }}
        }}
    }}, true);

    pw._sigmapasteOK = true;
}}

// Setup langsung dan dengan delay
setupPaste();
setTimeout(setupPaste, 1500);
setTimeout(setupPaste, 4000);
</script>
""", height=0)
