import streamlit as st
from groq import Groq
import yfinance as yf
import fitz  # PyMuPDF untuk PDF
import base64
from PIL import Image
import io


# 1. Konfigurasi Halaman - Memaksa Sidebar Terbuka Sejak Awal
st.set_page_config(page_title="KIPM SIGMA PRO", layout="wide", initial_sidebar_state="expanded")

# 2. CSS REVOLUTION: Sidebar & Centered Chat Tanpa Konflik
st.markdown("""
    <style>
    header {visibility: hidden;}
    
    /* Memperbaiki struktur dasar agar Sidebar dan Konten Utama tidak bertabrakan */
    .stAppViewMain {
        display: flex;
        justify-content: center;
    }

    /* Mengatur area konten utama agar tetap ramping di tengah (800px) */
    [data-testid="stMainBlockContainer"] {
        max-width: 800px !important;
        width: 100% !important;
        padding-top: 2rem !important;
        margin: 0 auto !important;
    }

    /* Gaya judul header (TIDAK DIRUBAH) */
    .main-header {
        text-align: center;
        margin-bottom: 2rem;
    }

    /* Menyatukan Icon Attach (Clip) ke dalam Search Bar */
    /* Posisi 'left' disesuaikan agar dinamis mengikuti box chat */
    div[data-testid="stPopover"] {
        position: fixed;
        bottom: 34px;
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

# 3. SIDEBAR (Identitas Organisasi)
with st.sidebar:
    try:
        # Menampilkan logo (1/3 ukuran sidebar secara visual)
        logo = Image.open("Mate KIPM LOGO.png")
        col_l, col_m, col_r = st.columns([1, 2, 1])
        with col_m:
            st.image(logo, use_container_width=True)
    except:
        st.write("🛡️")

    st.markdown("""
        <div style="text-align: center; line-height: 1.2; margin-top: 10px;">
            <p style="margin: 0; font-size: 0.8em; color: gray;">Komunitas Investasi Pasar Modal</p>
            <p style="margin: 0; font-size: 1em; font-weight: bold;">Universitas Pancasila</p>
        </div>
        """, unsafe_allow_html=True)
    st.divider()

# 4. KONTEN UTAMA (Judul Asli Anda)
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
        st.error(f"Gagal memanggil AI: {e}")
