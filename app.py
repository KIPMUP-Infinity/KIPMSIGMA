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

C = get_colors(st.session_state.theme)

# ─────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────
SYSTEM_PROMPT = {
    "role": "system",
    "content": """Kamu adalah SIGMA — analis saham dan chart expert dari KIPM Universitas Pancasila.

Kamu menggunakan framework analisa MnM Strategy+:
1. IFVG — Inversion Fair Value Gap
2. FVG — Fair Value Gap
3. Order Block (OB)
4. Supply & Demand Zones
5. Moving Average (EMA 13/21/50)

FORMAT TRADE PLAN:
📊 TRADE PLAN — [SAHAM] ([TIMEFRAME])
⚡ Bias: [Bullish/Bearish/Sideways]
🎯 Entry: [harga]
🛑 Stop Loss: [harga]
✅ Target 1: [harga]
✅ Target 2: [harga]
📦 Bandarmologi: [delta volume]
⚠️ Invalidasi: [kondisi]

ATURAN: Jawab Bahasa Indonesia, analisa gambar langsung, tegas."""
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
            st.session_state.current_token = token  # simpan token di session
            saved = load_user(user_info["email"])
            if saved:
                st.session_state.theme = saved.get("theme", "dark")
                if saved.get("sessions"):
                    st.session_state.sessions = saved["sessions"]
                    st.session_state.active_id = saved.get("active_id")
            st.session_state.data_loaded = True
            restore_images_from_messages()
            # JANGAN clear query params — biarkan token tetap di URL
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
    [data-testid="stAppViewContainer"],
    section[data-testid="stMain"],
    [data-testid="stMainBlockContainer"] {{
        background: url('data:image/png;base64,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') center/cover no-repeat fixed !important;
        min-height: 100vh !important;
    }}
    [data-testid="stMainBlockContainer"] {{
        max-width: 440px !important;
        margin: 0 auto !important;
        padding: 4vh 16px 40px !important;
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

    # Background gambar kiri
    _bg = "data:image/png;base64,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"
    st.markdown(f'''<style>
    #slbg{{position:fixed;top:0;left:0;right:440px;bottom:0;
    background:url("{_bg}") center/cover no-repeat;z-index:-1;}}
    @media(max-width:768px){{#slbg{{display:none}}}}
    </style><div id="slbg"></div>''', unsafe_allow_html=True)
    st.markdown('''<div style="text-align:center;margin:0 0 28px;">
    <h2 style="margin:0;font-size:1.6rem;font-weight:800;color:#ffffff;">Masuk ke SIGMA</h2>
    </div>''', unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["🔑 Masuk", "📝 Daftar", "🌐 Google"])

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
        Analisa bersifat <em>do your own research</em> dan disclaimer berlaku.
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
</style>
""", unsafe_allow_html=True)

_hist_items = ""
for _sesi in st.session_state.sessions:
    _sid = _sesi["id"]
    _is_act = _sid == st.session_state.active_id
    _td = _sesi["title"][:35].replace("'","").replace("`","").replace("\\","").replace('"',"")
    _fw = "700" if _is_act else "400"
    _bg = C['hover'] if _is_act else "transparent"
    # Pakai <a href> langsung — tidak perlu JS event listener
    _hist_items += f"""
(function(){{
    var a=pd.createElement('a');
    a.textContent='{_td}';
    var u=new URL(window.parent.location.href);
    u.searchParams.set('do','sel_{_sid}');
    a.href=u.toString();
    a.style.cssText='display:block;width:100%;padding:12px 18px;font-size:1rem;color:{C["text"]};background:{_bg};font-weight:{_fw};border:none;text-align:left;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-decoration:none;';
    a.onmouseenter=function(){{this.style.background='{C["hover"]}'}};
    a.onmouseleave=function(){{this.style.background='{_bg}'}};
    h.appendChild(a);
}})();
"""

# Inject menu ke parent document via components.html
components.html(f"""
<script>
(function(){{
var pd=window.parent.document;

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
        var hi = document.createElement('button');
        hi.textContent = '{title_d}';
        hi.dataset.sid = '{sid}';
        hi.style.cssText = 'display:block;width:100%;padding:11px 16px;font-size:0.95rem;color:{C["text"]};background:{bg};font-weight:{fw};border:none;text-align:left;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
        hi.onmouseenter = function(){{this.style.background='{C["hover"]}'}};
        hi.onmouseleave = function(){{this.style.background='{bg}'}};
        hi.onclick = function(){{
            var url = new URL(window.parent.location.href);
            url.searchParams.set('do', 'sel_{sid}');
            window.parent.location.href = url.toString();
        }};
        drawer.appendChild(hi);
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

# Chat history
for i, msg in enumerate(active["messages"][1:]):
    with st.chat_message(msg["role"]):
        display = msg["content"]
        if "Pertanyaan:" in display:
            display = display.split("Pertanyaan:")[-1].strip()
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
    if hasattr(result, 'text'):
        prompt = (result.text or "").strip()
        files = getattr(result, 'files', None) or []
        if files: file_obj = files[0]
    elif isinstance(result, str):
        prompt = result.strip()

    if file_obj:
        raw = file_obj.read()
        if file_obj.type == "application/pdf":
            doc = fitz.open(stream=raw, filetype="pdf")
            txt = "".join(p.get_text() for p in doc)
            st.session_state.pdf_data = (f"[PDF: {file_obj.name}]\n{txt[:6000]}", file_obj.name)
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

    if active["title"] == "Obrolan Baru":
        active["title"] = prompt[:40] + ("..." if len(prompt) > 40 else "")

    # Simpan gambar di dalam message agar tetap ada setelah refresh
    user_msg = {"role": "user", "content": full_prompt}
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
        st.error(f"Error: {e}")

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
