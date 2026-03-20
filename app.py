import streamlit as st
from groq import Groq
import yfinance as yf
import fitz  # PyMuPDF untuk PDF
import base64
from PIL import Image
import io
import streamlit.components.v1 as components


import streamlit as st
from groq import Groq
import fitz
from PIL import Image
import io
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

    [data-testid="stMainBlockContainer"] {
        padding-bottom: 110px !important;
    }

    /* Sembunyikan file uploader bawaan */
    [data-testid="stFileUploader"] {
        position: absolute !important;
        width: 1px !important;
        height: 1px !important;
        overflow: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
    }

    /* Sembunyikan st.text_input yang jadi bridge */
    [data-testid="stTextInput"] {
        position: absolute !important;
        width: 1px !important;
        height: 1px !important;
        overflow: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
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

if "attachment_text" not in st.session_state:
    st.session_state.attachment_text = None


# ── TAMPILKAN RIWAYAT CHAT ────────────────────────────────
for msg in st.session_state.messages[1:]:
    with st.chat_message(msg["role"]):
        display = msg["content"]
        if "Pertanyaan:" in display:
            display = display.split("Pertanyaan:")[-1].strip()
        st.markdown(display)


# ── HIDDEN FILE UPLOADER ──────────────────────────────────
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
        st.session_state.attachment_text = f"[Gambar: {uploaded_file.name}]"
        st.toast("✅ Gambar siap dikirim", icon="🖼️")


# ── HIDDEN TEXT INPUT SEBAGAI BRIDGE ─────────────────────
# JS akan inject teks ke sini lalu trigger 'Enter' untuk submit ke Streamlit
bridge_input = st.text_input("bridge", key="js_bridge", label_visibility="hidden")

if bridge_input and bridge_input != st.session_state.get("last_bridge", ""):
    st.session_state["last_bridge"] = bridge_input
    prompt = bridge_input

    full_prompt = prompt
    if st.session_state.attachment_text:
        full_prompt = f"{st.session_state.attachment_text}\n\nPertanyaan: {prompt}"
        st.session_state.attachment_text = None

    st.session_state.messages.append({"role": "user", "content": full_prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        with st.chat_message("assistant"):
            with st.spinner("SIGMA sedang menganalisis..."):
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

    # Reset bridge
    st.session_state["js_bridge"] = ""
    st.rerun()


# ── ATTACHMENT LABEL ──────────────────────────────────────
attachment_label = ""
if st.session_state.attachment_text:
    attachment_label = st.session_state.attachment_text.split("\n")[0]


# ── CUSTOM CHAT BAR ───────────────────────────────────────
chat_bar_html = f"""
<!DOCTYPE html>
<html>
<head>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: transparent;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 70px;
    padding: 8px 16px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  }}

  .bar {{
    width: 100%;
    max-width: 760px;
    background: #1e1e1e;
    border: 1px solid #3a3a3a;
    border-radius: 16px;
    padding: 10px 14px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.5);
  }}

  .attach-tag {{
    display: {'flex' if attachment_label else 'none'};
    align-items: center;
    gap: 6px;
    font-size: 0.75rem;
    color: #aaa;
  }}
  .attach-tag .chip {{
    background: #2e2e2e;
    border: 1px solid #444;
    padding: 2px 10px;
    border-radius: 20px;
    color: #ccc;
    font-size: 0.75rem;
  }}

  .row {{
    display: flex;
    align-items: center;
    gap: 10px;
  }}

  .btn-attach {{
    background: none;
    border: none;
    cursor: pointer;
    color: #666;
    display: flex;
    align-items: center;
    padding: 4px;
    border-radius: 8px;
    transition: color 0.2s, background 0.2s;
    flex-shrink: 0;
  }}
  .btn-attach:hover {{ color: #fff; background: #2e2e2e; }}

  textarea {{
    flex: 1;
    background: transparent;
    border: none;
    outline: none;
    color: #f0f0f0;
    font-size: 0.92rem;
    resize: none;
    height: 22px;
    max-height: 120px;
    line-height: 1.5;
    font-family: inherit;
    overflow-y: hidden;
  }}
  textarea::placeholder {{ color: #555; }}

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
    transition: background 0.2s, opacity 0.2s;
    opacity: 0.3;
  }}
  .btn-send.active {{ opacity: 1; }}
  .btn-send:hover.active {{ background: #e0e0e0; }}
  .btn-send svg {{ fill: #111; width: 15px; height: 15px; }}
</style>
</head>
<body>
<div class="bar">
  <div class="attach-tag">
    📎 <span class="chip">{attachment_label}</span>
  </div>
  <div class="row">
    <button class="btn-attach" onclick="triggerUpload()" title="Lampirkan file">
      <svg xmlns="http://www.w3.org/2000/svg" width="19" height="19" viewBox="0 0 24 24"
        fill="none" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round">
        <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19
                 a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
      </svg>
    </button>

    <textarea id="inp" placeholder="Tanya SIGMA..."
      oninput="onInput()" onkeydown="onKey(event)"></textarea>

    <button class="btn-send" id="sendBtn" onclick="send()">
      <svg viewBox="0 0 24 24"><path d="M2 12L22 2L12 22L10 14L2 12Z"/></svg>
    </button>
  </div>
</div>

<script>
  const inp     = document.getElementById('inp');
  const sendBtn = document.getElementById('sendBtn');

  function onInput() {{
    // Auto resize
    inp.style.height = 'auto';
    inp.style.height = Math.min(inp.scrollHeight, 120) + 'px';
    // Toggle send button
    sendBtn.classList.toggle('active', inp.value.trim() !== '');
  }}

  function onKey(e) {{
    if (e.key === 'Enter' && !e.shiftKey) {{
      e.preventDefault();
      if (inp.value.trim()) send();
    }}
  }}

  function send() {{
    const text = inp.value.trim();
    if (!text) return;

    // Cari hidden text input Streamlit (bridge) di parent document
    const parentDoc = window.parent.document;
    const inputs = parentDoc.querySelectorAll('input[type="text"]');

    let bridgeInput = null;
    for (let el of inputs) {{
      // Cari input yang labelnya "bridge" (hidden bridge kita)
      const wrapper = el.closest('[data-testid="stTextInput"]');
      if (wrapper) {{ bridgeInput = el; break; }}
    }}

    if (bridgeInput) {{
      // Set nilai input
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value'
      ).set;
      nativeInputValueSetter.call(bridgeInput, text);

      // Trigger React onChange event
      bridgeInput.dispatchEvent(new Event('input', {{ bubbles: true }}));

      // Trigger Enter key untuk submit ke Streamlit
      setTimeout(() => {{
        bridgeInput.dispatchEvent(new KeyboardEvent('keydown', {{
          key: 'Enter', code: 'Enter', keyCode: 13,
          bubbles: true, cancelable: true
        }}));
        bridgeInput.dispatchEvent(new KeyboardEvent('keypress', {{
          key: 'Enter', code: 'Enter', keyCode: 13,
          bubbles: true, cancelable: true
        }}));
        bridgeInput.dispatchEvent(new KeyboardEvent('keyup', {{
          key: 'Enter', code: 'Enter', keyCode: 13,
          bubbles: true, cancelable: true
        }}));
      }}, 100);

      inp.value = '';
      inp.style.height = '22px';
      sendBtn.classList.remove('active');
    }} else {{
      alert('Bridge tidak ditemukan. Coba refresh halaman.');
    }}
  }}

  function triggerUpload() {{
    const parentDoc = window.parent.document;
    const fileInputs = parentDoc.querySelectorAll('input[type="file"]');
    if (fileInputs.length > 0) {{
      fileInputs[fileInputs.length - 1].click();
    }}
  }}
</script>
</body>
</html>
"""

components.html(chat_bar_html, height=80, scrolling=False)
