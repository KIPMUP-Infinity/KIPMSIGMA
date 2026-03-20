import streamlit as st
from groq import Groq
import yfinance as yf
import fitz  # PyMuPDF untuk PDF
import base64
from PIL import Image
import io

Masalah utama pada kode sebelumnya adalah penggunaan margin: 0 auto dan position: fixed yang bertabrakan dengan cara Streamlit merender Sidebar. Saat konten dipaksa ke tengah secara absolut, Streamlit sering kali menganggap ruang tidak cukup dan menyembunyikan sidebar secara otomatis.

Berikut adalah kode app.py yang telah diperbaiki total. Saya menggunakan metode Padding ketimbang Margin agar Sidebar tetap memiliki ruang "napas" dan tidak hilang.

Python
import streamlit as st
from groq import Groq
from PIL import Image

# 1. Konfigurasi Halaman (WAJIB PERTAMA)
st.set_page_config(page_title="KIPM SIGMA PRO", layout="wide", initial_sidebar_state="expanded")

# 2. CSS CUSTOM (Presisi Tengah + Sidebar Tetap Ada)
st.markdown("""
    <style>
    header {visibility: hidden;}
    
    /* Memastikan area utama tidak menutupi sidebar */
    .stMain {
        margin-left: 0px;
    }

    /* Mengatur kontainer chat agar tepat di tengah */
    [data-testid="stMainBlockContainer"] {
        max-width: 800px !important;
        margin-left: auto !important;
        margin-right: auto !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
    }

    /* Header judul di tengah */
    .main-header {
        text-align: center;
        margin-bottom: 2rem;
    }

    /* Menyatukan Icon Attach (Clip) ke dalam Search Bar */
    div[data-testid="stPopover"] {
        position: fixed;
        bottom: 34px;
        /* Perhitungan posisi dinamis terhadap lebar layar dan sidebar */
        left: calc(50% - 375px + 140px); 
        z-index: 1001;
    }

    /* Responsif untuk layar kecil/HP */
    @media (max-width: 1200px) {
        div[data-testid="stPopover"] { left: calc(50% - 375px); }
    }
    @media (max-width: 850px) {
        div[data-testid="stPopover"] { left: 45px; }
        [data-testid="stMainBlockContainer"] { max-width: 95% !important; }
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
        st.write("📌 **Logo KIPM**")
    
    st.markdown("""
        <div style="text-align: center; line-height: 1.3;">
            <p style="margin:0; font-size:0.9em; color:#bdc3c7;">Komunitas Investasi Pasar Modal</p>
            <p style="font-weight:bold; font-size:1em; color:white;">Universitas Pancasila</p>
        </div>
        """, unsafe_allow_html=True)
    st.divider()

# 4. KONTEN UTAMA (Teks Tengah)
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

# 6. ATTACHMENT & SEARCH BAR
with st.popover("📎"):
    uploaded_file = st.file_uploader("Upload", type=["pdf", "png", "jpg"], label_visibility="collapsed")

if prompt := st.chat_input("Tanya SIGMA..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # AI Response (Groq)
    try:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        res = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=st.session_state.messages)
        ans = res.choices[0].message.content
        st.session_state.messages.append({"role": "assistant", "content": ans})
        with st.chat_message("assistant"):
            st.markdown(ans)
    except Exception as e:
        st.error(f"Gagal memanggil AI: {e}")
