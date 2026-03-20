import streamlit as st
from groq import Groq
import yfinance as yf
import fitz  # PyMuPDF untuk PDF
import base64
from PIL import Image
import io

# 1. Konfigurasi Halaman
st.set_page_config(page_title="KIPM SIGMA PRO", layout="wide")

# 2. CSS untuk Menyatukan Icon ke Search Bar & Teks ke Tengah
st.markdown("""
    <style>
    /* Menghilangkan header default */
    header {visibility: hidden;}
    
    /* Memposisikan teks header ke tengah layar */
    .main-header {
        text-align: center;
        margin-top: -50px;
        margin-bottom: 20px;
    }

    /* Menggabungkan Icon Attach ke dalam Search Bar */
    div[data-testid="stPopover"] {
        position: fixed;
        bottom: 34px;
        /* Geser ke kanan agar masuk ke dalam kotak input */
        left: calc(20% + 15px); 
        z-index: 1001;
    }

    /* Penyesuaian untuk layar HP */
    @media (max-width: 768px) {
        div[data-testid="stPopover"] { left: 45px; bottom: 34px; }
        .stChatInputContainer { padding-left: 40px !important; }
    }

    /* Styling kotak input agar teks tidak menabrak icon */
    .stChatInputContainer textarea {
        padding-left: 55px !important;
        border-radius: 25px !important;
    }

    /* Gaya tombol klip agar transparan/minimalis */
    div[data-testid="stPopover"] > button {
        border: none !important;
        background: transparent !important;
        color: #888 !important;
        font-size: 20px !important;
    }
    </style>
    """, unsafe_allow_html=True)

# 3. Sidebar (Branding Minimalis)
with st.sidebar:
    try:
        image = Image.open("Mate KIPM LOGO.png")
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m:
            st.image(image, use_container_width=True)
    except:
        pass

    st.markdown("""
        <div style="text-align: center; line-height: 1.2;">
            <p style="margin: 0; font-size: 0.8em; color: gray;">Komunitas Investasi Pasar Modal</p>
            <p style="margin: 0; font-size: 1em; font-weight: bold;">Universitas Pancasila</p>
        </div>
        """, unsafe_allow_html=True)

# 4. Konten Utama (Teks Tengah)
st.markdown("""
    <div class="main-header">
        <h1 style="margin-bottom: 0;">🛡️ KIPM SIGMA</h1>
        <p style="color: gray;">Strategic Intelligence & Global Market Analysis</p>
    </div>
    """, unsafe_allow_html=True)

# 5. Inisialisasi & Riwayat Chat
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": "Analis Saham KIPM UP."}]

for msg in st.session_state.messages[1:]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 6. Bar Pencarian dengan Icon Attach di Dalamnya
with st.popover("📎"):
    uploaded_file = st.file_uploader("Upload File", type=["pdf", "png", "jpg"], label_visibility="collapsed")
    if uploaded_file:
        st.toast(f"File {uploaded_file.name} berhasil diunggah!")

if prompt := st.chat_input("Tanya SIGMA..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Logika Groq
    try:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=st.session_state.messages
        )
        response = completion.choices[0].message.content
        st.session_state.messages.append({"role": "assistant", "content": response})
        with st.chat_message("assistant"):
            st.markdown(response)
    except Exception as e:
        st.error(f"Error: {e}")
