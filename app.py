import streamlit as st
from groq import Groq
import yfinance as yf
import fitz  # PyMuPDF untuk PDF
import base64
from PIL import Image
import io


# 1. Konfigurasi Halaman - Memaksa Sidebar Terbuka
st.set_page_config(page_title="KIPM SIGMA PRO", layout="wide", initial_sidebar_state="expanded")

# 2. CSS Terkoreksi: Sidebar Tetap Ada + Konten Tengah + Icon Presisi
st.markdown("""
    <style>
    header {visibility: hidden;}
    
    /* Memastikan Sidebar tetap lebar 300px */
    [data-testid="stSidebar"] {
        min-width: 300px !important;
        max-width: 300px !important;
    }

    /* Mengatur area utama: Menghapus margin auto agar Sidebar tidak tertutup */
    [data-testid="stMainBlockContainer"] {
        max-width: 850px !important;
        padding-top: 2rem !important;
        margin-left: 350px !important; /* Memberi ruang 300px untuk sidebar + 50px jarak */
    }

    /* Judul Header (TIDAK DIRUBAH) */
    .main-header {
        text-align: center;
        margin-bottom: 2rem;
    }

    /* Menyatukan Icon Attach (Clip) ke dalam Search Bar */
    div[data-testid="stPopover"] {
        position: fixed;
        bottom: 34px;
        /* Posisi ikon berdasarkan margin-left konten utama */
        left: 365px; 
        z-index: 1001;
    }

    /* Penyesuaian Responsif untuk Layar Kecil */
    @media (max-width: 1200px) {
        [data-testid="stMainBlockContainer"] { margin: 0 auto !important; }
        div[data-testid="stPopover"] { left: calc(50% - 370px); }
    }
    
    @media (max-width: 850px) {
        div[data-testid="stPopover"] { left: 45px; }
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

# 3. SIDEBAR (Logo dan Nama Organisasi)
with st.sidebar:
    try:
        # Memastikan logo tampil di sidebar
        logo = Image.open("Mate KIPM LOGO.png")
        st.image(logo, use_container_width=True)
    except:
        st.error("File 'Mate KIPM LOGO.png' tidak ditemukan.")

    st.markdown("""
        <div style="text-align: center; line-height: 1.2; margin-top: 10px;">
            <p style="margin: 0; font-size: 0.8em; color: gray;">Komunitas Investasi Pasar Modal</p>
            <p style="margin: 0; font-size: 1em; font-weight: bold;">Universitas Pancasila</p>
        </div>
        """, unsafe_allow_html=True)

# 4. KONTEN UTAMA (Judul Anda)
st.markdown("""
    <div class="main-header">
        <h1 style="margin:0;">   KIPM SIGMA ∑</h1>
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
    
    try:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        res = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=st.session_state.messages)
        ans = res.choices[0].message.content
        st.session_state.messages.append({"role": "assistant", "content": ans})
        with st.chat_message("assistant"):
            st.markdown(ans)
    except Exception as e:
        st.error(f"Error API: {e}")
