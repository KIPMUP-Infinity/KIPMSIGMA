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


st.set_page_config(
    page_title="KIPM SIGMA",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"], .stMarkdown, .stChatMessage, p, div {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    }
    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }
    section[data-testid="stSidebar"] > div:first-child { padding-top: 1rem; }
    .main-header { text-align: center; margin-bottom: 2rem; }
    [data-testid="stMainBlockContainer"] {
        padding-bottom: 80px !important;
        max-width: 780px !important;
        margin: 0 auto !important;
    }
    [data-testid="stChatMessage"] {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }
    [data-testid="stChatMessageAvatarUser"] { display: none !important; }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"])
    [data-testid="stMarkdownContainer"] {
        font-size: 0.93rem !important;
        line-height: 1.75 !important;
        color: #e8e8e8 !important;
        background: transparent !important;
    }
    div[data-testid="stSidebar"] button {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        color: #ccc !important;
        font-size: 0.85rem !important;
        text-align: left !important;
        padding: 5px 8px !important;
        border-radius: 8px !important;
    }
    div[data-testid="stSidebar"] button:hover {
        background: #2a2a2a !important;
        color: #fff !important;
    }
    /* Sembunyikan label file uploader di sidebar */
    section[data-testid="stSidebar"] [data-testid="stFileUploader"] label {
        display: none !important;
    }
    </style>
""", unsafe_allow_html=True)


# ── SESSION STATE ─────────────────────────────────────────
SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "Kamu adalah SIGMA, analis saham ahli dari KIPM Universitas Pancasila. "
        "Analisa chart, pola teknikal, bandarmologi, support/resistance, dan buat trade plan. "
        "Jawab dalam Bahasa Indonesia yang jelas, tegas, dan profesional."
    )
}

def new_session():
    return {
        "id": str(uuid.uuid4())[:8],
        "title": "Obrolan Baru",
        "messages": [SYSTEM_PROMPT],
        "created": datetime.now().strftime("%H:%M")
    }

if "sessions" not in st.session_state:
    s = new_session()
    st.session_state.sessions  = [s]
    st.session_state.active_id = s["id"]
if "rename_id" not in st.session_state:
    st.session_state.rename_id = None
if "attachment" not in st.session_state:
    st.session_state.attachment = None  # {"type": "pdf"/"image", "text": ..., "b64": ..., "mime": ..., "name": ...}

def get_active():
    for s in st.session_state.sessions:
        if s["id"] == st.session_state.active_id:
            return s
    return st.session_state.sessions[0]

def delete_session(sid):
    st.session_state.sessions = [s for s in st.session_state.sessions if s["id"] != sid]
    if not st.session_state.sessions:
        ns = new_session(); st.session_state.sessions = [ns]
    if st.session_state.active_id == sid:
        st.session_state.active_id = st.session_state.sessions[0]["id"]


# ── HANDLE SIDEBAR ACTIONS ────────────────────────────────
qp = st.query_params
if "action" in qp:
    action    = qp.get("action", "")
    sid_param = qp.get("sid", "")
    if action == "new":
        ns = new_session()
        st.session_state.sessions.insert(0, ns)
        st.session_state.active_id = ns["id"]
        st.query_params.clear(); st.rerun()
    elif action == "sel" and sid_param:
        st.session_state.active_id = sid_param
        st.session_state.rename_id = None
        st.query_params.clear(); st.rerun()
    elif action == "del" and sid_param:
        delete_session(sid_param)
        st.query_params.clear(); st.rerun()
    elif action == "ren" and sid_param:
        st.session_state.rename_id = sid_param
        st.query_params.clear(); st.rerun()


# ── SIDEBAR ───────────────────────────────────────────────
with st.sidebar:
    try:
        logo = Image.open("Mate KIPM LOGO.png")
        c1, c2, c3 = st.columns([1,2,1])
        with c2: st.image(logo, use_container_width=True)
    except:
        st.markdown("### 🏛️ KIPM-UP")

    st.markdown("""
        <div style="text-align:center;line-height:1.4;margin-top:8px;font-family:Inter,sans-serif;">
            <p style="margin:0;font-size:0.78rem;color:#aaa;">
                Komunitas <span style="color:#F5C242;font-weight:600;">Investasi</span> Pasar Modal
            </p>
            <p style="margin:4px 0 0 0;font-size:1.05rem;font-weight:700;color:#fff;">Universitas Pancasila</p>
        </div>
    """, unsafe_allow_html=True)

    st.divider()

    # Upload file di sidebar
    st.markdown('<p style="font-size:0.72rem;color:#666;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">📎 Lampirkan File</p>', unsafe_allow_html=True)

    if "upload_key" not in st.session_state:
        st.session_state.upload_key = 0

    uploaded = st.file_uploader(
        "upload", type=["pdf","png","jpg","jpeg"],
        key=f"up_{st.session_state.upload_key}",
        label_visibility="hidden"
    )

    if uploaded is not None:
        if uploaded.type == "application/pdf":
            pdf_bytes = uploaded.read()
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            pdf_text = "".join(p.get_text() for p in doc)
            st.session_state.attachment = {
                "type": "pdf", "name": uploaded.name,
                "text": f"[PDF: {uploaded.name}]\n{pdf_text[:6000]}"
            }
            st.success(f"📄 {uploaded.name}")
        else:
            img_bytes = uploaded.read()
            b64 = base64.b64encode(img_bytes).decode()
            ext  = uploaded.name.split(".")[-1].lower()
            mime = "image/png" if ext == "png" else "image/jpeg"
            st.session_state.attachment = {
                "type": "image", "name": uploaded.name,
                "b64": b64, "mime": mime,
                "text": f"[Gambar: {uploaded.name}]"
            }
            img = Image.open(io.BytesIO(img_bytes))
            st.image(img, use_container_width=True)
            st.success(f"🖼️ {uploaded.name} siap dianalisa")

    # Tampilkan status attachment
    if st.session_state.attachment:
        att = st.session_state.attachment
        st.info(f"📎 {att['name']} — ketik pertanyaan di chat lalu Enter")
        if st.button("🗑️ Hapus lampiran"):
            st.session_state.attachment = None
            st.session_state.upload_key += 1
            st.rerun()

    st.divider()

    # New chat
    st.markdown("""
        <a href="?action=new" target="_self" style="
            display:flex;align-items:center;gap:8px;padding:8px 10px;
            border-radius:8px;color:#ccc;text-decoration:none;
            font-size:0.88rem;font-family:Inter,sans-serif;margin-bottom:2px;"
           onmouseover="this.style.background='#2a2a2a';this.style.color='#fff'"
           onmouseout="this.style.background='transparent';this.style.color='#ccc'">
            ✏️ &nbsp;Obrolan baru
        </a>
    """, unsafe_allow_html=True)

    st.markdown('<p style="font-size:0.68rem;font-weight:600;color:#555;text-transform:uppercase;letter-spacing:1.2px;margin:10px 0 4px 6px;">Obrolan Anda</p>', unsafe_allow_html=True)

    for sesi in st.session_state.sessions:
        sid = sesi["id"]
        is_active = sid == st.session_state.active_id
        title_display = sesi["title"][:34] + "..." if len(sesi["title"]) > 34 else sesi["title"]

        if st.session_state.rename_id == sid:
            new_title = st.text_input("Rename", value=sesi["title"], key=f"rename_{sid}", label_visibility="collapsed")
            col_ok, col_cancel = st.columns([1,1])
            with col_ok:
                if st.button("✓", key=f"ok_{sid}"):
                    sesi["title"] = new_title.strip() or sesi["title"]
                    st.session_state.rename_id = None; st.rerun()
            with col_cancel:
                if st.button("✗", key=f"cancel_{sid}"):
                    st.session_state.rename_id = None; st.rerun()
        else:
            bg  = "#1e2d45" if is_active else "transparent"
            clr = "#fff"    if is_active else "#bbb"
            actions = (
                f'<a href="?action=ren&sid={sid}" target="_self" style="color:#666;text-decoration:none;font-size:0.78rem;padding:2px 5px;border-radius:4px;" onmouseover="this.style.color=\'#fff\'" onmouseout="this.style.color=\'#666\'">✏️</a>'
                f'<a href="?action=del&sid={sid}" target="_self" style="color:#666;text-decoration:none;font-size:0.78rem;padding:2px 5px;border-radius:4px;" onmouseover="this.style.color=\'#ff6b6b\'" onmouseout="this.style.color=\'#666\'">🗑️</a>'
                if is_active else ""
            )
            st.markdown(f"""
                <div style="display:flex;align-items:center;background:{bg};border-radius:8px;margin:1px 0;">
                    <a href="?action=sel&sid={sid}" target="_self" style="
                        flex:1;padding:7px 10px;color:{clr};text-decoration:none;
                        font-size:0.83rem;font-family:Inter,sans-serif;
                        white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block;">
                        💬 {title_display}
                    </a>
                    <div style="display:flex;gap:2px;padding-right:6px;">{actions}</div>
                </div>
            """, unsafe_allow_html=True)


# ── MAIN ─────────────────────────────────────────────────
active = get_active()

st.markdown("""
    <div class="main-header">
        <h1 style="margin:0;">KIPM SIGMA ∑</h1>
        <p style="color:gray;">Strategic Intelligence & Global Market Analysis</p>
    </div>
""", unsafe_allow_html=True)

# Tampilkan history chat
for i, msg in enumerate(active["messages"][1:]):
    with st.chat_message(msg["role"]):
        display = msg["content"]
        if "Pertanyaan:" in display:
            display = display.split("Pertanyaan:")[-1].strip()
        # Tampilkan thumbnail jika ada
        thumb_key = f"thumb_{active['id']}_{i}"
        if msg["role"] == "user" and thumb_key in st.session_state:
            b64, mime = st.session_state[thumb_key]
            st.markdown(
                f'<img src="data:{mime};base64,{b64}" style="max-width:100%;max-height:240px;border-radius:10px;margin-bottom:6px;display:block;">',
                unsafe_allow_html=True
            )
        st.markdown(display)


# ── CHAT INPUT NATIVE ─────────────────────────────────────
if prompt := st.chat_input("Tanya SIGMA..."):
    att = st.session_state.attachment
    has_image = att is not None and att["type"] == "image"
    has_pdf   = att is not None and att["type"] == "pdf"

    # Bangun full prompt
    full_prompt = prompt
    if att:
        full_prompt = f"{att['text']}\n\nPertanyaan: {prompt}"

    # Auto-title sesi
    if active["title"] == "Obrolan Baru":
        active["title"] = prompt[:40] + ("..." if len(prompt) > 40 else "")

    # Simpan thumbnail untuk history
    thumb_idx = len(active["messages"]) - 1
    if has_image:
        st.session_state[f"thumb_{active['id']}_{thumb_idx}"] = (att["b64"], att["mime"])

    # Tampilkan pesan user
    active["messages"].append({"role": "user", "content": full_prompt})
    with st.chat_message("user"):
        if has_image:
            st.markdown(
                f'<img src="data:{att["mime"]};base64,{att["b64"]}" style="max-width:100%;max-height:240px;border-radius:10px;margin-bottom:6px;display:block;">',
                unsafe_allow_html=True
            )
        st.markdown(prompt)

    # Reset attachment setelah dipakai
    st.session_state.attachment = None
    st.session_state.upload_key += 1

    # Panggil API
    try:
        with st.chat_message("assistant"):
            with st.spinner("SIGMA sedang menganalisis..."):
                groq_client = Groq(api_key=st.secrets["GROQ_API_KEY"])

                if has_image:
                    # Vision: Groq llama-3.2-90b
                    res = groq_client.chat.completions.create(
                        model="llama-3.2-90b-vision-preview",
                        messages=[
                            {"role": "system", "content": (
                                "Kamu adalah SIGMA, analis chart dan saham expert KIPM Universitas Pancasila. "
                                "Analisa HANYA gambar yang dikirim. Identifikasi saham, timeframe, trend, "
                                "support/resistance, pola teknikal, volume, bandarmologi, dan buat trade plan. "
                                "Jawab Bahasa Indonesia, tegas dan profesional."
                            )},
                            {"role": "user", "content": [
                                {"type": "image_url", "image_url": {"url": f"data:{att['mime']};base64,{att['b64']}"}},
                                {"type": "text", "text": prompt}
                            ]}
                        ],
                        max_tokens=2048
                    )
                else:
                    # Teks / PDF: Groq llama-3.3-70b
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


# ── JS: Fix bubble user ke kanan ─────────────────────────
components.html("""
<script>
function fixBubbles() {
    const doc = window.parent.document;
    doc.querySelectorAll('[data-testid="stChatMessage"]').forEach(msg => {
        const isUser = msg.querySelector('[data-testid="stChatMessageAvatarUser"]');
        if (!isUser) return;
        msg.style.cssText += 'display:flex!important;justify-content:flex-end!important;background:transparent!important;border:none!important;box-shadow:none!important;padding:4px 0!important;';
        const av = msg.querySelector('[data-testid="stChatMessageAvatarUser"]');
        if (av) av.style.display = 'none';
        const ct = msg.querySelector('[data-testid="stChatMessageContent"]');
        if (ct) ct.style.cssText += 'background:transparent!important;display:flex!important;justify-content:flex-end!important;max-width:100%!important;padding:0!important;';
        msg.querySelectorAll('[data-testid="stMarkdownContainer"]').forEach(md => {
            md.style.background = 'transparent';
            md.style.display = 'flex';
            md.style.justifyContent = 'flex-end';
            if (!md.querySelector('.navy-pill')) {
                const pill = document.createElement('div');
                pill.className = 'navy-pill';
                pill.style.cssText = 'background-color:#1B2A4A;color:#fff;border-radius:18px 18px 4px 18px;padding:10px 16px;max-width:72%;display:inline-block;font-size:0.93rem;line-height:1.6;font-family:Inter,sans-serif;word-wrap:break-word;';
                while (md.firstChild) pill.appendChild(md.firstChild);
                md.appendChild(pill);
                pill.querySelectorAll('*').forEach(el => el.style.color = '#fff');
            }
        });
    });
}
fixBubbles();
setInterval(fixBubbles, 800);
new MutationObserver(() => setTimeout(fixBubbles, 100)).observe(
    window.parent.document.body, {childList:true, subtree:true}
);
</script>
""", height=0)
