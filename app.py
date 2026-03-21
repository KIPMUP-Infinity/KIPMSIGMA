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
        # Buat token untuk auto-login
        token = str(uuid.uuid4()).replace("-","")
        with open(os.path.join(DATA_DIR, f"token_{token}.json"), "w") as f:
            json.dump(info, f)
        st.session_state.new_token = token
    st.query_params.clear()
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
    [data-testid="stMainBlockContainer"] {{
        max-width: 420px !important;
        margin: 6vh auto 0 !important;
        padding: 0 16px !important;
    }}
    section[data-testid="stMain"] {{ background: {C['bg']} !important; }}
    </style>
    """, unsafe_allow_html=True)

    # Logo
    try:
        logo = Image.open("Mate KIPM LOGO.png")
        c1,c2,c3 = st.columns([1,1,1])
        with c2: st.image(logo, use_container_width=True)
    except: pass

    st.markdown(f"""
    <div style="text-align:center;margin:16px 0 24px;">
        <h2 style="margin:0;font-size:1.5rem;font-weight:700;color:{C['text']};">Masuk ke SIGMA</h2>
        <p style="margin:6px 0 0;color:{C['text_muted']};font-size:0.85rem;">
            Platform analisa saham KIPM Universitas Pancasila
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Tab pilihan login
    tab1, tab2, tab3 = st.tabs(["🔑 Username", "🔐 Daftar", "🌐 Google"])

    with tab1:
        uname = st.text_input("Username", key="li_user", placeholder="username")
        pwd   = st.text_input("Password", key="li_pwd",  type="password", placeholder="password")
        if st.button("Masuk", key="btn_login", use_container_width=True):
            if uname and pwd:
                info = login_user(uname.strip(), pwd)
                if info:
                    # Buat token
                    token = str(uuid.uuid4()).replace("-","")
                    with open(os.path.join(DATA_DIR, f"token_{token}.json"), "w") as f:
                        json.dump(info, f)
                    # Set token di URL — ini yang persist saat refresh
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
        rname = st.text_input("Nama Tampil", key="rg_name", placeholder="Nama kamu")
        runame = st.text_input("Username", key="rg_user", placeholder="username (huruf/angka)")
        rpwd  = st.text_input("Password", key="rg_pwd",  type="password", placeholder="min. 6 karakter")
        rpwd2 = st.text_input("Ulangi Password", key="rg_pwd2", type="password", placeholder="ulangi password")
        if st.button("Daftar", key="btn_register", use_container_width=True):
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
                    background:#fff;color:#1a1a1a;border-radius:10px;padding:12px;
                    text-decoration:none;font-size:0.9rem;font-weight:500;
                    border:1px solid #ddd;">
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

    st.markdown(f'<p style="text-align:center;color:{C["text_muted"]};font-size:0.72rem;margin-top:20px;">Dengan masuk, kamu menyetujui penggunaan platform untuk analisa pasar modal.</p>', unsafe_allow_html=True)
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
                pill.style.cssText=`background:#1B2A4A;color:#ffffff;border-radius:18px 18px 4px 18px;padding:${{mob?"12px 16px":"10px 16px"}};max-width:${{mob?"85%":"72%"}};display:inline-block;font-size:${{mob?"1rem":"0.9rem"}};line-height:1.7;word-wrap:break-word;`;
                while (md.firstChild) pill.appendChild(md.firstChild);
                md.appendChild(pill);
            }}
            // Force putih semua elemen dalam bubble
            var pill = md.querySelector('.navy-pill');
            if (pill) {{
                pill.style.setProperty('color','#ffffff','important');
                pill.style.setProperty('background','#1B2A4A','important');
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

        var isUser = !!msg.querySelector('[data-testid="stChatMessageAvatarUser"]');

        // Ambil teks pesan
        function getMsgText() {{
            var pill = msg.querySelector('.navy-pill');
            if (pill) return pill.innerText;
            var md = msg.querySelector('[data-testid="stMarkdownContainer"]');
            return md ? md.innerText : '';
        }}

        var bar = doc.createElement('div');
        bar.className = 'sigma-actions';
        bar.style.cssText = 'width:100%;display:flex;gap:2px;margin-top:6px;padding:0 2px;justify-content:' + (isUser ? 'flex-end' : 'flex-start') + ';clear:both;';

        function makeBtn(icon, label) {{
            var b = doc.createElement('button');
            b.innerHTML = icon;
            b.title = label;
            b.style.cssText = 'background:transparent;border:none;cursor:pointer;padding:5px 7px;border-radius:6px;font-size:15px;color:{C["text_muted"]};line-height:1;';
            b.onmouseenter = function() {{ this.style.background = '{C["hover"]}'; }};
            b.onmouseleave = function() {{ this.style.background = 'transparent'; }};
            return b;
        }}

        // Tombol SALIN
        var copyBtn = makeBtn('📋', 'Salin');
        copyBtn.onclick = function() {{
            var txt = getMsgText();
            navigator.clipboard.writeText(txt).then(function() {{
                copyBtn.innerHTML = '✅';
                setTimeout(function() {{ copyBtn.innerHTML = '📋'; }}, 2000);
            }}).catch(function() {{
                // Fallback
                var ta = doc.createElement('textarea');
                ta.value = getMsgText();
                doc.body.appendChild(ta);
                ta.select();
                doc.execCommand('copy');
                doc.body.removeChild(ta);
                copyBtn.innerHTML = '✅';
                setTimeout(function() {{ copyBtn.innerHTML = '📋'; }}, 2000);
            }});
        }};
        bar.appendChild(copyBtn);

        if (isUser) {{
            // Tombol EDIT
            var editBtn = makeBtn('✏️', 'Edit');
            editBtn.onclick = function() {{
                var txt = getMsgText();
                var ta = doc.querySelector('[data-testid="stChatInput"] textarea');
                if (!ta) return;
                ta.focus();
                ta.value = txt;
                // Trigger React
                var ev = new Event('input', {{bubbles:true}});
                Object.defineProperty(ev, 'target', {{writable:false, value:ta}});
                ta.dispatchEvent(ev);
            }};
            bar.appendChild(editBtn);
        }} else {{
            // Tombol ULANGI
            var retryBtn = makeBtn('🔄', 'Ulangi');
            retryBtn.onclick = function() {{
                // Cari pesan user sebelum pesan AI ini
                var allMsgs = Array.from(doc.querySelectorAll('[data-testid="stChatMessage"]'));
                var idx = allMsgs.indexOf(msg);
                var userMsg = null;
                for (var i = idx - 1; i >= 0; i--) {{
                    if (allMsgs[i].querySelector('[data-testid="stChatMessageAvatarUser"]')) {{
                        userMsg = allMsgs[i];
                        break;
                    }}
                }}
                if (!userMsg) return;
                var pill = userMsg.querySelector('.navy-pill');
                var txt = pill ? pill.innerText : (userMsg.querySelector('[data-testid="stMarkdownContainer"]') || {{}}).innerText || '';
                var ta = doc.querySelector('[data-testid="stChatInput"] textarea');
                if (!ta || !txt) return;
                ta.focus();
                ta.value = txt;
                var ev = new Event('input', {{bubbles:true}});
                ta.dispatchEvent(ev);
            }};
            bar.appendChild(retryBtn);
        }}

        // Pasang bar SETELAH seluruh message element
        msg.style.flexDirection = 'column';
        if (isUser) {{
            bar.style.justifyContent = 'flex-end';
            bar.style.marginRight = '0';
            // Cari container markdown (parent of navy-pill) dan insert bar setelahnya
            var md = msg.querySelector('[data-testid="stMarkdownContainer"]');
            if (md && md.parentNode) {{
                md.parentNode.style.flexDirection = 'column';
                md.parentNode.style.alignItems = 'flex-end';
                md.parentNode.appendChild(bar);
            }} else {{
                msg.appendChild(bar);
            }}
        }} else {{
            msg.appendChild(bar);
        }}
    }});
}}

addActionButtons();
setInterval(addActionButtons, 1000);

// Paste image support — lebih robust
function setupPaste() {{
    var pw = window.parent;
    if (pw._sigmaOK) return;

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

    pw.addEventListener('paste', handlePaste, true);
    pw.document.addEventListener('paste', handlePaste, true);
    pw._sigmaOK = true;
}}
setupPaste();
setTimeout(setupPaste, 1000);
setTimeout(setupPaste, 3000);
</script>
""", height=0)
