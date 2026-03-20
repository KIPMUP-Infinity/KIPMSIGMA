import streamlit as st
from groq import Groq
import yfinance as yf
import fitz  # PyMuPDF
import base64
from PIL import Image
import io


# Konfigurasi Halaman
st.set_page_config(page_title="KIPM SIGMA ", layout="wide")

# 1. Pengaturan Tema & Logo
st.set_page_config(page_title="KIPM SIGMA", page_icon="📈", layout="wide")

st.markdown("""
    <style>
    /* Mengubah warna background input chat */
    .stChatInputContainer {
        padding-bottom: 20px;
        background-color: transparent;
    }
    /* Menghilangkan border uploader agar lebih minimalis */
    .stFileUploader {
        padding-top: 0;
    }
    </style>
    """, unsafe_allow_html=True)


with st.sidebar:
    # 1. Logo (Ukuran 1/3 di tengah)
    try:
        image = Image.open("Mate KIPM LOGO.png")
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m:
            st.image(image, use_container_width=True)
    except FileNotFoundError:
        st.error("Logo tidak ditemukan.")

    # 2. Tulisan Nama Organisasi (Centered)
    st.markdown("""
        <div style="text-align: center; line-height: 1.2; margin-top: 10px;">
            <p style="margin: 0; font-size: 0.9em; color: #ecf0f1;">Komunitas Investasi Pasar Modal</p>
            <p style="margin: 0; font-size: 1.1em; font-weight: bold; color: #ffffff;">Universitas Pancasila</p>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("---")

    

    # 3. Branding SIGMA (Centered)
    st.markdown("""
        <div style="text-align: center;">
            <h2 style="margin-bottom: 0;">🛡️ KIPM SIGMA</h2>
            <p style="font-size: 0.8em; color: #95a5a6;">Strategic Intelligence & Global Market Analysis</p>
        </div>
        """, unsafe_allow_html=True)
    
    st.divider()

# 1. Konfigurasi Halaman & CSS untuk UI "Clean"
st.set_page_config(page_title="KIPM SIGMA PRO", layout="wide")

st.markdown("""
    <style>
    /* Menghilangkan header default streamlit */
    header {visibility: hidden;}
    
    /* Styling Floating Chat Input agar icon dan bar sejajar */
    .stChatInputContainer {
        padding-bottom: 30px;
    }
    
    /* Merapikan posisi popover agar terlihat seperti icon attach */
    div[data-testid="stPopover"] {
        position: fixed;
        bottom: 38px;
        left: 20%;
        z-index: 1000;
    }
    
    @media (max-width: 768px) {
        div[data-testid="stPopover"] { left: 5%; bottom: 35px; }
    }
    </style>
    """, unsafe_allow_html=True)

# 2. Sidebar (Hanya Nama Organisasi & Logo)
with st.sidebar:
    try:
        image = Image.open("logo.jpg")
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m:
            st.image(image, use_container_width=True)
    except:
        pass

    st.markdown("""
        <div style="text-align: center; line-height: 1.2;">
            <p style="margin: 0; font-size: 0.9em;">Komunitas Investasi Pasar Modal</p>
            <p style="margin: 0; font-size: 1.1em; font-weight: bold;">Universitas Pancasila</p>
        </div>
        <hr>
        <div style="text-align: center;">
            <h2 style="margin-bottom: 0;">🛡️ KIPM SIGMA</h2>
            <p style="font-size: 0.8em; color: gray;">Strategic Intelligence & Global Market Analysis</p>
        </div>
        """, unsafe_allow_html=True)

# 3. Logika Utama Chat
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": "Analis Saham Profesional KIPM UP."}]

# Tampilkan riwayat chat
for msg in st.session_state.messages[1:]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 4. Floating Attachment & Search Bar
# Tombol popover yang terlihat seperti icon "attach"
with st.popover("📎"):
    uploaded_file = st.file_uploader("Upload Chart/PDF", type=["pdf", "png", "jpg", "jpeg"], label_visibility="collapsed")
    if uploaded_file:
        st.success(f"File {uploaded_file.name} siap dianalisis!")

# Bar input utama
if prompt := st.chat_input("Tanya SIGMA..."):
    # Logika Chat
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # Respon AI (Contoh simpel)
    with st.chat_message("assistant"):
        st.write("Analisis sedang diproses...")



# Inisialisasi API Groq via Secrets
if "GROQ_API_KEY" not in st.secrets:
    st.error("API Key belum disetting di Streamlit Secrets!")
    st.stop()

client = Groq(api_key=st.secrets["GROQ_API_KEY"])

# Inisialisasi Memori Chat
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": "Identitas: KIPM SIGMA (Strategic Intelligence & Global Market Analysis). Analis Saham Profesional. Anda bisa baca PDF, Gambar Chart, dan Data Live."}
    ]

# Fungsi Pendukung
def get_stock_info(ticker):
    if not ticker.endswith(".JK"): ticker += ".JK"
    try:
        s = yf.Ticker(ticker).info
        return f"Data {ticker}: Harga {s.get('currentPrice')}, PE {s.get('trailingPE')}, PBV {s.get('priceToBook')}"
    except: return "Gagal mengambil data saham."

# Sidebar: Fitur Upload
st.sidebar.subheader("Upload Dokumen/Chart")
uploaded_file = st.sidebar.file_uploader("Pilih PDF atau Gambar Chart", type=["pdf", "png", "jpg", "jpeg"])

if uploaded_file:
    if uploaded_file.type == "application/pdf":
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        text = "".join([page.get_text() for page in doc])
        st.sidebar.success("PDF Terbaca!")
        if st.sidebar.button("Analisis PDF Ini"):
            st.session_state.messages.append({"role": "user", "content": f"Analisis teks PDF ini: {text[:5000]}"})
    else:
        st.sidebar.image(uploaded_file, caption="Preview Chart")
        if st.sidebar.button("Analisis Gambar Ini"):
            img_bytes = uploaded_file.getvalue()
            base64_image = base64.b64encode(img_bytes).decode('utf-8')
            st.session_state.messages.append({
                "role": "user", 
                "content": [
                    {"type": "text", "text": "Analisis teknikal/bandarmology dari gambar ini."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            })

# 1. Tampilkan riwayat chat terlebih dahulu
for msg in st.session_state.messages[1:]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 2. Letakkan Baris Upload & Input Chat di paling bawah
# Buat kolom untuk tombol upload agar sejajar/di atas bar chat
col_action1, col_action2 = st.columns([1, 5])

with col_action1:
    with st.popover("📎 Upload"):
        uploaded_file = st.file_uploader("Pilih PDF/Chart", type=["pdf", "png", "jpg", "jpeg"], label_visibility="collapsed")

# Bar input chat utama
prompt = st.chat_input("Tanya SIGMA... (atau ketik 'cek BBCA')")

# 3. Logika Pemrosesan (Setelah Input)
if prompt:
    # Simpan dan tampilkan pesan user
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # Jalankan AI Groq di sini
    with st.chat_message("assistant"):
        # (Kode client.chat.completions.create Anda di sini)
        pass
