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

    section[data-testid="stSidebar"] > div:first-child {
        padding-top: 1rem;
    }

    .main-header { text-align: center; margin-bottom: 2rem; }

    [data-testid="stMainBlockContainer"] {
        padding-bottom: 110px !important;
        max-width: 780px !important;
        margin: 0 auto !important;
    }

    /* File uploader — SEPENUHNYA tersembunyi, diklik via JS */
    [data-testid="stFileUploader"] {
        position: absolute !important;
        width: 0 !important;
        height: 0 !important;
        overflow: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
        margin: 0 !important;
        padding: 0 !important;
    }

    /* Bridge text input — collapsed tapi ada di DOM, disembunyikan via posisi */
    [data-testid="stTextInput"] {
        position: fixed !important;
        bottom: -100px !important;
        left: 0 !important;
        width: 1px !important;
        height: 1px !important;
        overflow: hidden !important;
        opacity: 0 !important;
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

    /* Semua button sidebar: transparan, rata kiri, no border */
    div[data-testid="stSidebar"] button {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        color: #ccc !important;
        font-size: 0.85rem !important;
        font-weight: 400 !important;
        text-align: left !important;
        padding: 5px 8px !important;
        border-radius: 8px !important;
        transition: background 0.15s !important;
        outline: none !important;
    }
    div[data-testid="stSidebar"] button:hover {
        background: #2a2a2a !important;
        color: #fff !important;
    }
    </style>
""", unsafe_allow_html=True)


# ── SESSION STATE INIT ────────────────────────────────────

SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "Kamu adalah SIGMA, analis saham ahli dari KIPM Universitas Pancasila. "
        "Jawab pertanyaan seputar investasi, pasar modal, saham, dan analisis keuangan "
        "dengan bahasa yang jelas, profesional, dan berbasis data."
    )
}

def new_session():
    sid = str(uuid.uuid4())[:8]
    return {
        "id": sid,
        "title": "Obrolan Baru",
        "messages": [SYSTEM_PROMPT],
        "created": datetime.now().strftime("%H:%M")
    }

if "sessions" not in st.session_state:
    first = new_session()
    st.session_state.sessions = [first]
    st.session_state.active_id = first["id"]

if "attachment_text" not in st.session_state:
    st.session_state.attachment_text = None

if "rename_id" not in st.session_state:
    st.session_state.rename_id = None

# Helper: ambil sesi aktif
def get_active():
    for s in st.session_state.sessions:
        if s["id"] == st.session_state.active_id:
            return s
    return st.session_state.sessions[0]

def set_active(sid):
    st.session_state.active_id = sid

def delete_session(sid):
    st.session_state.sessions = [s for s in st.session_state.sessions if s["id"] != sid]
    if not st.session_state.sessions:
        first = new_session()
        st.session_state.sessions = [first]
    if st.session_state.active_id == sid:
        st.session_state.active_id = st.session_state.sessions[0]["id"]


# ── HANDLE SIDEBAR ACTIONS VIA QUERY PARAMS ─────────────
qp = st.query_params
if "action" in qp:
    action = qp.get("action", "")
    sid_param = qp.get("sid", "")
    if action == "new":
        ns = new_session()
        st.session_state.sessions.insert(0, ns)
        st.session_state.active_id = ns["id"]
        st.query_params.clear()
        st.rerun()
    elif action == "sel" and sid_param:
        st.session_state.active_id = sid_param
        st.session_state.rename_id = None
        st.query_params.clear()
        st.rerun()
    elif action == "del" and sid_param:
        delete_session(sid_param)
        st.query_params.clear()
        st.rerun()
    elif action == "ren" and sid_param:
        st.session_state.rename_id = sid_param
        st.query_params.clear()
        st.rerun()

# ── SIDEBAR ───────────────────────────────────────────────
with st.sidebar:

    try:
        logo = Image.open("Mate KIPM LOGO.png")
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.image(logo, use_container_width=True)
    except:
        st.markdown("### 🏛️ KIPM-UP")

    st.markdown("""
        <div style="text-align:center;line-height:1.4;margin-top:8px;font-family:Inter,sans-serif;">
            <p style="margin:0;font-size:0.78rem;color:#aaa;">Komunitas <span style="color:#F5C242;font-weight:600;">Investasi</span> Pasar Modal</p>
            <p style="margin:4px 0 0 0;font-size:1.05rem;font-weight:700;color:#fff;">Universitas Pancasila</p>
        </div>
    """, unsafe_allow_html=True)

    st.divider()

    # New Chat — pure HTML, no st.button
    st.markdown("""
        <a href="?action=new" target="_self" style="
            display:flex;align-items:center;gap:8px;
            padding:8px 10px;border-radius:8px;
            color:#ccc;text-decoration:none;
            font-size:0.88rem;font-family:Inter,sans-serif;
            margin-bottom:2px;
        " onmouseover="this.style.background='#2a2a2a';this.style.color='#fff'"
           onmouseout="this.style.background='transparent';this.style.color='#ccc'">
            ✏️ &nbsp;Obrolan baru
        </a>
    """, unsafe_allow_html=True)

    st.markdown('<p style="font-size:0.68rem;font-weight:600;color:#555;text-transform:uppercase;letter-spacing:1.2px;margin:10px 0 4px 6px;font-family:Inter,sans-serif;">Obrolan Anda</p>', unsafe_allow_html=True)

    # Daftar sesi — pure HTML links, zero st.button
    for sesi in st.session_state.sessions:
        sid = sesi["id"]
        is_active = sid == st.session_state.active_id
        title_display = sesi["title"][:34] + "..." if len(sesi["title"]) > 34 else sesi["title"]

        if st.session_state.rename_id == sid:
            new_title = st.text_input("Rename", value=sesi["title"],
                key=f"rename_{sid}", label_visibility="collapsed")
            col_ok, col_cancel = st.columns([1, 1])
            with col_ok:
                if st.button("✓", key=f"ok_{sid}"):
                    sesi["title"] = new_title.strip() or sesi["title"]
                    st.session_state.rename_id = None
                    st.rerun()
            with col_cancel:
                if st.button("✗", key=f"cancel_{sid}"):
                    st.session_state.rename_id = None
                    st.rerun()
        else:
            bg = "#1e2d45" if is_active else "transparent"
            txt_color = "#fff" if is_active else "#bbb"
            actions = (
                f'''<a href="?action=ren&sid={sid}" target="_self" title="Rename"
                       style="color:#777;text-decoration:none;font-size:0.78rem;padding:2px 5px;border-radius:4px;"
                       onmouseover="this.style.color='#fff'" onmouseout="this.style.color='#777'">✏️</a>
                    <a href="?action=del&sid={sid}" target="_self" title="Hapus"
                       style="color:#777;text-decoration:none;font-size:0.78rem;padding:2px 5px;border-radius:4px;"
                       onmouseover="this.style.color='#ff6b6b'" onmouseout="this.style.color='#777'">🗑️</a>'''
                if is_active else ""
            )
            st.markdown(f"""
                <div style="display:flex;align-items:center;background:{bg};border-radius:8px;margin:1px 0;">
                    <a href="?action=sel&sid={sid}" target="_self" style="
                        flex:1;padding:7px 10px;color:{txt_color};text-decoration:none;
                        font-size:0.83rem;font-family:Inter,sans-serif;
                        white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block;">
                        💬 {title_display}
                    </a>
                    <div style="display:flex;gap:2px;padding-right:6px;">{actions}</div>
                </div>
            """, unsafe_allow_html=True)

# ── MAIN HEADER ───────────────────────────────────────────
active = get_active()

st.markdown("""
    <div class="main-header">
        <h1 style="margin:0;">  KIPM SIGMA ∑</h1>
        <p style="color:gray;">Strategic Intelligence & Global Market Analysis</p>
    </div>
""", unsafe_allow_html=True)


# ── TAMPILKAN CHAT AKTIF ──────────────────────────────────
for i, msg in enumerate(active["messages"][1:]):
    with st.chat_message(msg["role"]):
        display = msg["content"]
        if "Pertanyaan:" in display:
            display = display.split("Pertanyaan:")[-1].strip()
        # Tampilkan thumbnail gambar jika ada
        thumb_key = f"img_thumb_{i+1}"

# ── CHAT INPUT NATIVE (support file upload) ──────────────
if prompt := st.chat_input("Tanya SIGMA..."):
    uploaded_imgs = []
    # st.chat_input di Streamlit ≥1.31 tidak support file langsung
    # Kita tetap pakai session state dari file uploader di bawah
    pass

# ── FILE UPLOADER VISIBLE ────────────────────────────────
if "upload_key" not in st.session_state:
    st.session_state["upload_key"] = 0

if st.session_state.get("do_reset_uploader"):
    st.session_state["upload_key"] += 1
    st.session_state["do_reset_uploader"] = False

uploaded_file = st.file_uploader(
    "upload",
    type=["pdf", "png", "jpg", "jpeg"],
    key=f"uploader_{st.session_state['upload_key']}",
    label_visibility="hidden"
)

if uploaded_file is not None:
    ftype = uploaded_file.type
    fname = uploaded_file.name
    if ftype == "application/pdf":
        pdf_bytes = uploaded_file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pdf_text = "".join(page.get_text() for page in doc)
        st.session_state.attachment_text = f"[PDF: {fname}]\n{pdf_text[:6000]}"
        st.session_state.pop("image_b64", None)
        st.session_state.pop("image_mime", None)
        st.toast(f"✅ {fname} siap dikirim — ketik pertanyaan lalu Enter", icon="📄")
        st.rerun()
    else:
        img_bytes = uploaded_file.read()
        st.session_state["image_b64"]  = base64.b64encode(img_bytes).decode("utf-8")
        ext = fname.split(".")[-1].lower()
        st.session_state["image_mime"] = "image/png" if ext == "png" else "image/jpeg"
        st.session_state.attachment_text = f"[Gambar: {fname}]"
        st.toast(f"✅ {fname} siap dianalisa — ketik pertanyaan lalu Enter", icon="🖼️")
        st.rerun()


# ── BRIDGE INPUT ──────────────────────────────────────────
bridge_input = st.text_input("bridge", key="js_bridge_widget", label_visibility="collapsed")

if bridge_input and bridge_input.strip() and bridge_input != st.session_state.get("last_bridge", ""):
    st.session_state["last_bridge"] = bridge_input
    prompt = bridge_input

    full_prompt = prompt
    if st.session_state.attachment_text:
        full_prompt = f"{st.session_state.attachment_text}\n\nPertanyaan: {prompt}"
        st.session_state.attachment_text = None
        st.session_state["do_reset_uploader"] = True

    if active["title"] == "Obrolan Baru":
        active["title"] = prompt[:40] + ("..." if len(prompt) > 40 else "")

    has_image = "image_b64" in st.session_state and bool(st.session_state["image_b64"])
    img_b64   = st.session_state.pop("image_b64", None)
    img_mime  = st.session_state.pop("image_mime", "image/jpeg")

    if has_image:
        st.toast("📸 Vision aktif — menganalisa gambar...", icon="🔍")

    # Simpan thumbnail untuk ditampilkan di history
    thumb_idx = len(active["messages"])
    if has_image and img_b64:
        st.session_state[f"img_thumb_{thumb_idx}"] = (img_b64, img_mime)

    active["messages"].append({"role": "user", "content": full_prompt})
    with st.chat_message("user"):
        if has_image and img_b64:
            st.markdown(
                f'''<img src="data:{img_mime};base64,{img_b64}"
                style="max-width:100%;max-height:260px;border-radius:10px;margin-bottom:6px;display:block;">''',
                unsafe_allow_html=True
            )
        st.markdown(prompt)

    try:
        with st.chat_message("assistant"):
            with st.spinner("SIGMA sedang menganalisis..."):
                groq_client = Groq(api_key=st.secrets["GROQ_API_KEY"])

                if has_image and img_b64:
                    vision_messages = [
                        {"role": "system", "content": (
                            "Kamu adalah SIGMA, analis saham dan chart expert dari KIPM Universitas Pancasila. "
                            "Analisa HANYA berdasarkan gambar/chart yang dikirim user. "
                            "Identifikasi: nama saham jika terlihat, timeframe, trend, support/resistance, "
                            "pola teknikal, volume, bandarmologi, dan buat trade plan. "
                            "Jawab dalam Bahasa Indonesia yang profesional."
                        )},
                        {"role": "user", "content": [
                            {"type": "image_url", "image_url": {
                                "url": f"data:{img_mime};base64,{img_b64}"
                            }},
                            {"type": "text", "text": prompt}
                        ]}
                    ]
                    res = groq_client.chat.completions.create(
                        model="llama-3.2-90b-vision-preview",
                        messages=vision_messages,
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

        active["messages"].append({"role": "assistant", "content": ans})
        with st.chat_message("assistant"):
            st.markdown(ans)

    except Exception as e:
        import traceback
        st.error(f"❌ Error: {e}")
        st.code(traceback.format_exc(), language="text")

    st.rerun()


# ── CUSTOM CHAT BAR (hanya untuk styling input) ───────────
attachment_label = ""
if st.session_state.get("attachment_text"):
    attachment_label = st.session_state["attachment_text"].split("\n")[0]

chat_bar_html = f"""
<!DOCTYPE html>
<html>
<head>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ background: transparent; margin: 0; padding: 0; font-family: Inter, sans-serif; }}
  body {{ display: flex; align-items: flex-end; justify-content: center; padding: 4px 16px 8px; }}
  .bar {{
    width: 100%; max-width: 760px;
    background: #1e1e1e; border: 1px solid #3a3a3a;
    border-radius: 16px; padding: 10px 14px;
    display: flex; flex-direction: column; gap: 6px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.5);
  }}
  .attach-tag {{
    display: {'flex' if attachment_label else 'none'};
    align-items: center; gap: 6px; font-size: 0.75rem; color: #aaa;
  }}
  .attach-tag .chip {{
    background: #2e2e2e; border: 1px solid #444;
    padding: 2px 10px; border-radius: 20px; color: #ccc; font-size: 0.75rem;
  }}
  .row {{ display: flex; align-items: flex-end; gap: 10px; }}
  .btn-attach {{
    background: none; border: none; cursor: pointer; color: #666;
    display: flex; align-items: center; padding: 4px; border-radius: 8px;
    transition: color 0.2s, background 0.2s; flex-shrink: 0; margin-bottom: 3px;
  }}
  .btn-attach:hover {{ color: #fff; background: #2e2e2e; }}
  textarea {{
    flex: 1; background: transparent; border: none; outline: none;
    color: #f0f0f0; font-size: 0.92rem; resize: none;
    min-height: 24px; max-height: 150px; line-height: 1.6;
    font-family: inherit; overflow-y: auto; padding: 2px 0; word-break: break-word;
  }}
  textarea::placeholder {{ color: #555; }}
  .btn-send {{
    background: #fff; border: none; border-radius: 8px;
    width: 32px; height: 32px; display: flex; align-items: center;
    justify-content: center; cursor: pointer; flex-shrink: 0;
    transition: background 0.2s, opacity 0.2s; opacity: 0.3; margin-bottom: 2px;
  }}
  .btn-send.active {{ opacity: 1; }}
  .btn-send:hover.active {{ background: #e0e0e0; }}
  .btn-send svg {{ fill: #111; width: 15px; height: 15px; }}
  /* Paste preview */
  .paste-preview {{
    display: none; align-items: center; gap: 8px; padding: 4px 0;
  }}
  .paste-preview img {{ height: 44px; border-radius: 6px; border: 1px solid #444; }}
  .paste-preview span {{ font-size: 0.75rem; color: #aaa; }}
  .paste-preview button {{
    background: none; border: none; color: #888;
    cursor: pointer; font-size: 1rem; padding: 0 4px;
  }}
</style>
</head>
<body>
<div class="bar">
  <div class="attach-tag">📎 <span class="chip">{attachment_label}</span></div>
  <div id="pastePreview" class="paste-preview">
    <img id="pasteThumb" src="" />
    <span>Screenshot (paste)</span>
    <button onclick="clearPaste()">✕</button>
  </div>
  <div class="row">
    <button class="btn-attach" onclick="triggerUpload()" title="Lampirkan file">
      <svg xmlns="http://www.w3.org/2000/svg" width="19" height="19" viewBox="0 0 24 24"
        fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19
                 a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
      </svg>
    </button>
    <textarea id="inp" placeholder="Tanya SIGMA... (Ctrl+V untuk paste gambar)"
      oninput="onInput()" onkeydown="onKey(event)" onpaste="onPaste(event)"></textarea>
    <button class="btn-send" id="sendBtn" onclick="send()">
      <svg viewBox="0 0 24 24"><path d="M2 12L22 2L12 22L10 14L2 12Z"/></svg>
    </button>
  </div>
</div>
<script>
  const inp = document.getElementById('inp');
  const sendBtn = document.getElementById('sendBtn');
  let pastedFile = null;

  function onInput() {{
    inp.style.height = 'auto';
    inp.style.height = Math.min(inp.scrollHeight, 150) + 'px';
    updateBtn();
  }}
  function updateBtn() {{
    sendBtn.classList.toggle('active', inp.value.trim() !== '' || pastedFile !== null);
  }}
  function onKey(e) {{
    if (e.key === 'Enter' && !e.shiftKey) {{
      e.preventDefault();
      if (inp.value.trim() || pastedFile) send();
    }}
  }}
  function onPaste(e) {{
    const items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    for (let item of items) {{
      if (item.type.startsWith('image/')) {{
        e.preventDefault();
        pastedFile = item.getAsFile();
        const reader = new FileReader();
        reader.onload = ev => {{
          document.getElementById('pasteThumb').src = ev.target.result;
          document.getElementById('pastePreview').style.display = 'flex';
          updateBtn();
        }};
        reader.readAsDataURL(pastedFile);
        return;
      }}
    }}
  }}
  function clearPaste() {{
    pastedFile = null;
    document.getElementById('pastePreview').style.display = 'none';
    document.getElementById('pasteThumb').src = '';
    updateBtn();
  }}
  function send() {{
    const text = inp.value.trim();
    if (!text && !pastedFile) return;

    if (pastedFile) {{
      // Kirim gambar via file uploader Streamlit yang visible
      const parentDoc = window.parent.document;
      const uploader = parentDoc.querySelector('input[type="file"]');
      if (uploader) {{
        const dt = new DataTransfer();
        dt.items.add(pastedFile);
        // Inject file ke uploader
        Object.defineProperty(uploader, 'files', {{ value: dt.files, configurable: true }});
        uploader.dispatchEvent(new Event('change', {{ bubbles: true }}));
      }}
      // Kirim teks setelah 800ms (beri waktu Streamlit proses file)
      setTimeout(() => sendText(text || 'Tolong analisa gambar ini'), 800);
      clearPaste();
    }} else {{
      sendText(text);
    }}
  }}
  function sendText(text) {{
    const parentDoc = window.parent.document;

    // Cari SEMUA input text, ambil yang pertama ditemukan di stTextInput
    const allInputs = parentDoc.querySelectorAll('[data-testid="stTextInput"] input');
    const bridge = allInputs.length > 0 ? allInputs[0] : null;

    if (!bridge) {{
      // Fallback: cari input text biasa
      const fallback = parentDoc.querySelector('input[type="text"]');
      if (fallback) {{
        doSend(fallback, text);
      }}
      return;
    }}
    doSend(bridge, text);
  }}

  function doSend(bridge, text) {{
    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    nativeSetter.call(bridge, text);
    bridge.dispatchEvent(new Event('input', {{ bubbles: true }}));
    bridge.dispatchEvent(new Event('change', {{ bubbles: true }}));
    setTimeout(() => {{
      ['keydown', 'keypress', 'keyup'].forEach(evtType => {{
        bridge.dispatchEvent(new KeyboardEvent(evtType, {{
          key: 'Enter', code: 'Enter', keyCode: 13,
          which: 13, bubbles: true, cancelable: true
        }}));
      }});
    }}, 150);
    inp.value = '';
    inp.style.height = '24px';
    sendBtn.classList.remove('active');
  }}
  function triggerUpload() {{
    const parentDoc = window.parent.document;
    // Cari semua file inputs
    const fileInputs = parentDoc.querySelectorAll('input[type="file"]');
    if (fileInputs.length > 0) {{
      const fi = fileInputs[fileInputs.length - 1];
      // Sementara enable pointer-events untuk klik
      fi.style.pointerEvents = 'auto';
      fi.style.position = 'fixed';
      fi.style.top = '0';
      fi.style.left = '0';
      fi.style.width = '1px';
      fi.style.height = '1px';
      fi.style.opacity = '0';
      fi.click();
      // Restore setelah klik
      setTimeout(() => {{
        fi.style.position = '';
        fi.style.pointerEvents = '';
      }}, 500);
    }}
  }}
</script>
</body>
</html>
"""

components.html(chat_bar_html, height=200, scrolling=False)

# ── JS: Fix bubble user ke kanan ─────────────────────────
components.html("""
<script>
function fixBubbles() {
    const doc = window.parent.document;
    doc.querySelectorAll('[data-testid="stChatMessage"]').forEach(msg => {
        const isUser = msg.querySelector('[data-testid="stChatMessageAvatarUser"]');
        if (!isUser) return;
        msg.style.cssText += 'display:flex!important;justify-content:flex-end!important;background:transparent!important;border:none!important;box-shadow:none!important;padding:4px 0!important;';
        const avatar = msg.querySelector('[data-testid="stChatMessageAvatarUser"]');
        if (avatar) avatar.style.display = 'none';
        const content = msg.querySelector('[data-testid="stChatMessageContent"]');
        if (content) content.style.cssText += 'background:transparent!important;display:flex!important;justify-content:flex-end!important;max-width:100%!important;padding:0!important;';
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
new MutationObserver(() => setTimeout(fixBubbles, 100)).observe(window.parent.document.body, {childList:true, subtree:true});
</script>
""", height=0)
