import streamlit as st
from groq import Groq
import yfinance as yf
import fitz  # PyMuPDF untuk PDF
import base64
from PIL import Image
import io

# 1. Konfigurasi Halaman (Hanya satu kali)
st.set_page_config(page_title="KIPM SIGMA PRO", layout="wide")

# 2. CSS Advanced untuk Sidebar Tetap Ada & Konten di Tengah
st.markdown("""
    <style>
    header {visibility: hidden;}
    
    /* Memastikan Sidebar tetap lebar standar */
    [data-testid="stSidebar"] {
        min-width: 300px;
        max-width: 300px;
    }

    /* Mengatur area utama agar Flex */
    .stMain {
        display: flex;
        justify-content: center;
    }

    /* Membatasi lebar konten chat di tengah layar */
    .stMainBlockContainer {
        max-width: 800px !important;
        padding-top: 2rem !important;
        margin: 0 auto !important;
    }

    /* Judul Header di Tengah */
    .main-header {
        text-align: center;
        margin-bottom: 30px;
    }

    /* Posisi Icon Attach (Clip) presisi di dalam Bar Chat */
    div[data-testid="stPopover"] {
        position: fixed;
        bottom: 34px;
        /* Menghitung posisi berdasarkan lebar container 800px + offset sidebar */
        left: calc(50% - 385px + 150px); 
        z-index: 1001;
    }

    /* Responsif untuk layar kecil/HP */
    @media (max-width: 1200px) {
        div[data-testid="stPopover"] { left: calc(50% - 385px); }
    }
    
    @media (max-width: 850px) {
        div[data-testid="stPopover"] { left: 45px; }
        .stMainBlockContainer { max-width: 95% !important; }
    }

    /* Input Chat Styling */
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

# 3. SIDEBAR (Identitas Kampus)
with st.sidebar:
    try:
        logo = Image.open("Mate KIPM LOGO.png")
        st.image(logo, use_container_width=True)
    except:
        pass
    st.markdown("""
        <div style="text-align: center;">
            <p style="margin:0; font-size:0.9em;">Komunitas Investasi Pasar Modal</p>
            <p style="font-weight:bold; font-size:1em;">Universitas Pancasila</p>
        </div>
        """, unsafe_allow_html=True)

# 4. KONTEN TENGAH
st.markdown("""
    <div class="main-header">
        <h1 style="margin:0;">🛡️ KIPM SIGMA</h1>
        <p style="color:gray;">Strategic Intelligence & Global Market Analysis</p>
    </div>
    """, unsafe_allow_html=True)

# 5. LOGIKA CHAT
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": "Analis Saham KIPM UP."}]

for msg in st.session_state.messages[1:]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 6. ATTACHMENT DI DALAM SEARCH BAR
with st.popover("📎"):
    uploaded_file = st.file_uploader("Upload", type=["pdf", "png", "jpg"], label_visibility="collapsed")

if prompt := st.chat_input("Tanya SIGMA..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # Bagian API Groq (Sesuaikan dengan Secret Anda)
    try:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        res = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=st.session_state.messages)
        ans = res.choices[0].message.content
        st.session_state.messages.append({"role": "assistant", "content": ans})
        with st.chat_message("assistant"):
            st.markdown(ans)
    except Exception as e:
        st.error(f"Error: {e}")
