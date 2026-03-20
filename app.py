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

st.set_page_config(
    page_title="KIPM SIGMA PRO",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS MINIMAL — hanya hide elemen yang tidak perlu, TIDAK sentuh header sama sekali
st.markdown("""
    <style>

    /* Hanya hide footer dan main menu hamburger bawaan */
    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }

    /* Sidebar padding agar tidak terlalu ke atas */
    section[data-testid="stSidebar"] > div:first-child {
        padding-top: 4rem;
    }

    /* Main content */
    .main-header { text-align: center; margin-bottom: 2rem; }

    /* Chat input */
    .stChatInputContainer textarea {
        border-radius: 25px !important;
    }

    </style>
""", unsafe_allow_html=True)


# SIDEBAR
with st.sidebar:
    try:
        logo = Image.open("Mate KIPM LOGO.png")
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
                preview = msg["content"][:50] + "..." if len(msg["content"]) > 50 else msg["content"]
                st.markdown(f"🔍 {preview}")


# MAIN
st.markdown("""
    <div class="main-header">
        <h1 style="margin:0;">KIPM SIGMA ∑</h1>
        <p style="color:gray;">Strategic Intelligence & Global Market Analysis</p>
    </div>
""", unsafe_allow_html=True)


# SESSION STATE
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

for msg in st.session_state.messages[1:]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])


# ATTACHMENT
with st.popover("📎 Lampirkan File"):
    uploaded_file = st.file_uploader(
        "Upload PDF atau Gambar",
        type=["pdf", "png", "jpg", "jpeg"],
        label_visibility="collapsed"
    )

    if uploaded_file is not None:
        if uploaded_file.type == "application/pdf":
            pdf_bytes = uploaded_file.read()
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            pdf_text = "".join(page.get_text() for page in doc)
            st.session_state["attachment_text"] = f"[PDF diunggah]\n{pdf_text[:3000]}"
            st.success(f"✅ PDF dibaca ({len(pdf_text)} karakter)")
        else:
            image = Image.open(uploaded_file)
            st.image(image, use_container_width=True)
            st.session_state["attachment_text"] = "[Gambar diunggah]"
            st.info("Gambar siap.")


# CHAT
if prompt := st.chat_input("Tanya SIGMA..."):
    full_prompt = prompt
    if "attachment_text" in st.session_state:
        full_prompt = f"{st.session_state.pop('attachment_text')}\n\nPertanyaan: {prompt}"

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
