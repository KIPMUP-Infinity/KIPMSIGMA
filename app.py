import streamlit as st
from groq import Groq
import yfinance as yf
import fitz  # PyMuPDF untuk PDF
import base64
from PIL import Image
import io

# 1. Konfigurasi Halaman
st.set_page_config(page_title="KIPM SIGMA PRO", layout="wide")

# 2. CSS FIX: Sidebar Muncul + Konten Tengah + Icon Integrated
st.markdown("""
    <style>
    header {visibility: hidden;}
    
    /* Memastikan Sidebar punya ruang dan tidak tertutup */
    [data-testid="stSidebar"] {
        background-color: #111b21;
    }

    /* Target khusus area konten agar di tengah tanpa merusak Sidebar */
    [data-testid="stMainBlockContainer"] {
        max-width: 850px !important;
        margin: 0 auto !important;
        padding-left: 5rem !important;
        padding-right: 5rem !important;
    }

    /* Judul Header di Tengah */
    .main-header {
        text-align: center;
        margin-bottom: 2rem;
        margin-top: -2rem;
    }

    /* Menyatukan Icon Attach (Clip) ke dalam Search Bar */
    div[data-testid="stPopover"] {
        position: fixed;
        bottom: 34px;
        /* Mengunci posisi relatif terhadap bar input di tengah */
        left: calc(50% - 370px + 130px); 
        z-index: 1001;
    }

    /* Responsif: Geser icon jika sidebar tertutup/layar kecil */
    @media (max-width: 1200px) {
        div[data-testid="stPopover"] { left: calc(50% - 380px); }
    }
    @media (max-width: 850px) {
        div[data-testid="stPopover"] { left: 45px; }
        [data-testid="stMainBlockContainer"] { padding: 1rem !important; }
    }

    /* Styling Input Bar */
    .stChatInputContainer textarea {
        padding-left: 55px !important;
        border-radius: 25px !important;
    }

    /* Tombol Klip Transparan */
    div[data-testid="stPopover"] > button {
        border: none !important;
        background: transparent !important;
        font-size: 22px !important;
        color: #888 !important;
    }
    </style>
    """, unsafe_allow_html=True)

# 3. SIDEBAR (Identitas)
with st.sidebar:
    try:
        logo = Image.open("Mate KIPM LOGO.png")
        st.image(logo, use_container_width=True)
    except:
        pass
    st.markdown("<div style='text-align: center; color: gray;'>Komunitas Investasi Pasar Modal<br><b>Universitas Pancasila</b></div>", unsafe_allow_html=True)

# 4. HEADER TENGAH
st.markdown("""
    <div class="main-header">
        <h1 style="margin:0;">∑ KIPM SIGMA</h1>
        <p style="color:gray;">Strategic Intelligence & Global Market Analysis</p>
    </div>
    """, unsafe_allow_html=True)

# 5. LOGIKA CHAT & SEARCH BAR
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": "Analis Saham KIPM UP."}]

for msg in st.session_state.messages[1:]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Popover Attachment (📎)
with st.popover("📎"):
    uploaded_file = st.file_uploader("Upload", type=["pdf", "png", "jpg"], label_visibility="collapsed")

# Input Chat
if prompt := st.chat_input("Tanya SIGMA..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # AI Response
    try:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        res = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=st.session_state.messages)
        ans = res.choices[0].message.content
        st.session_state.messages.append({"role": "assistant", "content": ans})
        with st.chat_message("assistant"):
            st.markdown(ans)
    except Exception as e:
        st.error(f"API Error: {e}")
