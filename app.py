import streamlit as st
from groq import Groq
import yfinance as yf
import fitz  # PyMuPDF untuk PDF
import base64
from PIL import Image
import io

import streamlit as st
from groq import Groq
import fitz
from PIL import Image
import io
import base64
import streamlit.components.v1 as components

st.set_page_config(
    page_title="KIPM SIGMA PRO",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }

    section[data-testid="stSidebar"] > div:first-child {
        padding-top: 4rem;
    }

    .main-header { text-align: center; margin-bottom: 2rem; }

    /* Beri ruang di bawah untuk custom chat bar */
    [data-testid="stMainBlockContainer"] {
        padding-bottom: 100px !important;
    }
    </style>
""", unsafe_allow_html=True)


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
        <div style="text-align: center; line-height: 1.2; margin-top: 10px;">
            <p style="margin: 0; font-size: 0.8em; color: gray;">Komunitas Investasi Pasar Modal</p>
            <p style="margin: 0; font-size: 1em; font-weight: bold;">Universitas Pancasila</p>
        </div>
    """, unsafe_allow_html=True)

    st.divider()
    st.subheader("📜 History Searching")

    if "messages" in st.session_state:
        for msg in st.session_state.messages[1:]:
            if msg["role"] == "user":
                display = msg["content"]
                if "Pertanyaan:" in display:
                    display = display.split("Pertanyaan:")[-1].strip()
                preview = display[:50] + "..." if len(display) > 50 else display
                st.markdown(f"🔍 {preview}")


# ── MAIN HEADER ───────────────────────────────────────────
st.markdown("""
    <div class="main-header">
        <h1 style="margin:0;">KIPM SIGMA ∑</h1>
        <p style="color:gray;">Strategic Intelligence & Global Market Analysis</p>
    </div>
""", unsafe_allow_html=True)


# ── SESSION STATE ─────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "system",
            "content": (
                "Kamu adalah SIGMA, analis saham ahli dari KIPM Universitas Pancasila. "
                "Jawab pertanyaan seputar investasi, pasar modal, saham, dan analisis keuangan "
                "dengan bahasa yang jelas, profesional, dan berbasis data."
            )
        }
    ]

if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None

if "attachment_text" not in st.session_state:
    st.session_state.attachment_text = None


# ── TAMPILKAN RIWAYAT CHAT ────────────────────────────────
for msg in st.session_state.messages[1:]:
    with st.chat_message(msg["role"]):
        display = msg["content"]
        if "Pertanyaan:" in display:
            display = display.split("Pertanyaan:")[-1].strip()
        st.markdown(display)


# ── PROSES PROMPT DARI CUSTOM BAR ────────────────────────
if st.session_state.pending_prompt:
    prompt = st.session_state.pending_prompt
    st.session_state.pending_prompt = None

    full_prompt = prompt
    if st.session_state.attachment_text:
        full_prompt = f"{st.session_state.attachment_text}\n\nPertanyaan: {prompt}"
        st.session_state.attachment_text = None

    st.session_state.messages.append({"role": "user", "content": full_prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        res = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=st.session_state.messages,
            temperature=0.7,
            max_tokens=2048
        )
        ans = res.choices[0].message.content
        st.session_state.messages.append({"role": "assistant", "content": ans})
        with st.chat_message("assistant"):
            st.markdown(ans)
    except Exception as e:
        st.error(f"❌ Error: {e}")


# ── HANDLE FILE UPLOAD (tersembunyi, dipicu JS) ───────────
uploaded_file = st.file_uploader(
    "upload",
    type=["pdf", "png", "jpg", "jpeg"],
    label_visibility="hidden",
    key="hidden_uploader"
)

if uploaded_file is not None and st.session_state.attachment_text is None:
    if uploaded_file.type == "application/pdf":
        pdf_bytes = uploaded_file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pdf_text = "".join(page.get_text() for page in doc)
        st.session_state.attachment_text = f"[PDF: {uploaded_file.name}]\n{pdf_text[:3000]}"
        st.toast(f"✅ {uploaded_file.name} siap dikirim", icon="📄")
    else:
        image = Image.open(uploaded_file)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        st.session_state.attachment_text = f"[Gambar: {uploaded_file.name}]"
        st.toast("✅ Gambar siap dikirim", icon="🖼️")


# ── CUSTOM CHAT BAR (HTML + JS) ───────────────────────────
attachment_label = ""
if st.session_state.attachment_text:
    name = st.session_state.attachment_text.split("\n")[0]
    attachment_label = name

chat_bar_html = f"""
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: transparent;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    height: 80px;
    padding: 0 1rem;
  }}

  .chat-bar-wrapper {{
    width: 100%;
    max-width: 760px;
    background: #2b2b2b;
    border: 1px solid #444;
    border-radius: 16px;
    padding: 10px 14px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.4);
  }}

  /* Label attachment jika ada file */
  .attach-label {{
    display: {'flex' if attachment_label else 'none'};
    align-items: center;
    gap: 6px;
    font-size: 0.78rem;
    color: #aaa;
    padding: 2px 4px;
  }}

  .attach-label span {{
    background: #3a3a3a;
    padding: 2px 10px;
    border-radius: 20px;
    color: #ccc;
  }}

  /* Row input utama */
  .input-row {{
    display: flex;
    align-items: center;
    gap: 8px;
  }}

  /* Tombol attach (paperclip) */
  .btn-attach {{
    background: none;
    border: none;
    cursor: pointer;
    color: #888;
    font-size: 1.2rem;
    padding: 4px;
    border-radius: 8px;
    flex-shrink: 0;
    transition: color 0.2s;
  }}
  .btn-attach:hover {{ color: #fff; }}

  /* Textarea */
  textarea {{
    flex: 1;
    background: transparent;
    border: none;
    outline: none;
    color: #fff;
    font-size: 0.95rem;
    resize: none;
    height: 24px;
    max-height: 120px;
    line-height: 1.5;
    font-family: inherit;
    overflow-y: hidden;
  }}

  textarea::placeholder {{ color: #666; }}

  /* Tombol kirim */
  .btn-send {{
    background: #fff;
    border: none;
    border-radius: 8px;
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    flex-shrink: 0;
    transition: background 0.2s;
  }}
  .btn-send:hover {{ background: #ddd; }}
  .btn-send svg {{ fill: #111; width: 16px; height: 16px; }}
  .btn-send:disabled {{ background: #444; cursor: not-allowed; }}
  .btn-send:disabled svg {{ fill: #666; }}
</style>

<div class="chat-bar-wrapper">
  <!-- Label file terlampir -->
  <div class="attach-label">
    📎 <span>{attachment_label}</span>
  </div>

  <!-- Row input -->
  <div class="input-row">
    <!-- Tombol attach -->
    <button class="btn-attach" onclick="triggerUpload()" title="Lampirkan file">
      <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66
                 l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
      </svg>
    </button>

    <!-- Input teks -->
    <textarea id="chatInput" placeholder="Tanya SIGMA..." rows="1"
      onkeydown="handleKey(event)" oninput="autoResize(this)"></textarea>

    <!-- Tombol kirim -->
    <button class="btn-send" id="sendBtn" onclick="sendMessage()" disabled>
      <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
        <path d="M2 12L22 2L12 22L10 14L2 12Z"/>
      </svg>
    </button>
  </div>
</div>

<script>
  const textarea = document.getElementById('chatInput');
  const sendBtn  = document.getElementById('sendBtn');

  // Enable/disable tombol kirim
  textarea.addEventListener('input', () => {{
    sendBtn.disabled = textarea.value.trim() === '';
  }});

  // Auto resize textarea
  function autoResize(el) {{
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  }}

  // Enter = kirim, Shift+Enter = newline
  function handleKey(e) {{
    if (e.key === 'Enter' && !e.shiftKey) {{
      e.preventDefault();
      if (!sendBtn.disabled) sendMessage();
    }}
  }}

  // Kirim pesan ke Streamlit via query param trick
  function sendMessage() {{
    const text = textarea.value.trim();
    if (!text) return;

    // Kirim ke parent Streamlit lewat URL hash
    window.parent.postMessage({{
      type: 'SIGMA_PROMPT',
      payload: text
    }}, '*');

    textarea.value = '';
    textarea.style.height = '24px';
    sendBtn.disabled = true;
  }}

  // Trigger file uploader Streamlit yang tersembunyi
  function triggerUpload() {{
    // Cari file input dari Streamlit hidden uploader
    const inputs = window.parent.document.querySelectorAll('input[type="file"]');
    if (inputs.length > 0) {{
      inputs[inputs.length - 1].click();
    }}
  }}
</script>
"""

# Render custom chat bar
components.html(chat_bar_html, height=90, scrolling=False)


# ── LISTENER PESAN DARI JS ────────────────────────────────
# Karena postMessage tidak langsung bisa masuk Streamlit,
# kita pakai st.query_params sebagai bridge
listener_html = """
<script>
window.addEventListener('message', function(e) {
  if (e.data && e.data.type === 'SIGMA_PROMPT') {
    // Set query param sebagai trigger ke Streamlit
    const url = new URL(window.parent.location.href);
    url.searchParams.set('sigma_prompt', encodeURIComponent(e.data.payload));
    window.parent.history.pushState({}, '', url);
    window.parent.location.reload();
  }
});
</script>
"""
components.html(listener_html, height=0)

# Baca prompt dari query params
params = st.query_params
if "sigma_prompt" in params:
    raw = params["sigma_prompt"]
    st.session_state.pending_prompt = raw
    st.query_params.clear()
    st.rerun()
