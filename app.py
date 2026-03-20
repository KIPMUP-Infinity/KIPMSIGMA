import streamlit as st
from groq import Groq
import yfinance as yf
import fitz  # PyMuPDF untuk PDF
import base64
from PIL import Image
import io

# 1. KONFIGURASI HALAMAN (Wajib di paling atas)
st.set_page_config(page_title="KIPM SIGMA PRO", page_icon="📈", layout="wide")

# 2. CSS CUSTOM (UI Modern & Floating Icon)
st.markdown("""
    <style>
    header {visibility: hidden;}
    .block-container {padding-top: 2rem;}
    
    /* Memposisikan Popover (Ikon Klip) agar masuk ke area Chat Input */
    div[data-testid="stPopover"] {
        position: fixed;
        bottom: 34px;
        left: 55px;
        z-index: 1000;
    }
    
    /* Memberi ruang di kiri input agar teks tidak tertutup ikon */
    .stChatInputContainer textarea {
        padding-left: 50px !important;
    }
    
    /* Gaya tombol klip bulat */
    div[data-testid="stPopover"] > button {
        border-radius: 50% !important;
        width: 38px !important;
        height: 38px !important;
        background-color: #262730 !important;
        border: 1px solid #464b5d !important;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    </style>
    """, unsafe_allow_html=True)

# 3. SIDEBAR (Hanya Identitas)
with st.sidebar:
    try:
        # Ganti dengan nama file logo Anda yang ada di GitHub
        logo_img = Image.open("Mate KIPM LOGO.png")
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m:
            st.image(logo_img, use_container_width=True)
    except:
        st.warning("Logo 'Mate KIPM LOGO.png' tidak ditemukan.")

    st.markdown("""
        <div style="text-align: center; line-height: 1.2; margin-top: 10px;">
            <p style="margin: 0; font-size: 0.85em; color: #bdc3c7;">Komunitas Investasi Pasar Modal</p>
            <p style="margin: 0; font-size: 1.1em; font-weight: bold; color: #ffffff;">Universitas Pancasila</p>
        </div>
        <hr style="margin: 15px 0; border-color: #464b5d;">
        <div style="text-align: center;">
            <h2 style="margin: 0; font-size: 1.4em;">🛡️ KIPM SIGMA</h2>
            <p style="font-size: 0.75em; color: #7f8c8d;">Strategic Intelligence & Global Market Analysis</p>
        </div>
        """, unsafe_allow_html=True)

# 4. INISIALISASI SESSION STATE (Memori Chat)
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": "Anda adalah SIGMA, asisten AI cerdas dari KIPM Universitas Pancasila. Ahli dalam analisis teknikal, fundamental, dan bandarmology saham Indonesia."}
    ]

# Tampilkan Riwayat Chat
for msg in st.session_state.messages[1:]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 5. FLOATING ATTACHMENT & INPUT BAR
# Tombol klip di kiri bawah
with st.popover("📎"):
    uploaded_file = st.file_uploader("Upload PDF/Chart", type=["pdf", "png", "jpg", "jpeg"], label_visibility="collapsed")
    if uploaded_file:
        st.success(f"File '{uploaded_file.name}' dimuat.")

# Bar Input Chat
if prompt := st.chat_input("Tanya SIGMA..."):
    # Simpan pesan user
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # PROSES RESPON AI
    try:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        
        # Logika tambahan jika ada file (Vision/PDF) bisa disisipkan di sini
        # Untuk saat ini, kita proses teks via Llama 3
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=st.session_state.messages,
            temperature=0.7
        )
        
        full_response = response.choices[0].message.content
        
        # Simpan dan tampilkan respon asisten
        st.session_state.messages.append({"role": "assistant", "content": full_response})
        with st.chat_message("assistant"):
            st.markdown(full_response)
            
    except Exception as e:
        st.error(f"Terjadi kesalahan koneksi: {str(e)}")
