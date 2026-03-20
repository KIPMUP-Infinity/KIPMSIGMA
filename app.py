import streamlit as st
from groq import Groq
import yfinance as yf
import fitz  # PyMuPDF
import base64
from PIL import Image
import io

# Konfigurasi Halaman
st.set_page_config(page_title="KIPM SIGMA ", layout="wide")
st.sidebar.title("Kontrol Panel")

# 1. Pengaturan Tema & Logo
st.set_page_config(page_title="KIPM SIGMA", page_icon="📈", layout="wide")

# CSS untuk Background Gelap & Styling Chat (Mirip contoh gambar Anda)
st.markdown("""
    <style>
    .stApp {
        background-color: #0E1117;
        color: white;
    }
    [data-testid="stSidebar"] {
        background-color: #1A1C24;
    }
    .stChatMessage {
        border-radius: 10px;
        margin-bottom: 15px;
        border: 1px solid #30363d;
    }
    </style>
    """, unsafe_allow_html=True)

# 2. Menampilkan Logo di Sidebar
with st.sidebar:
    try:
        # Ganti 'logo.jpg' dengan nama file logo Anda di GitHub
        logo = Image.open("logo.jpg") 
        st.image(logo, use_container_width=True)
    except:
        st.error("File logo.jpg tidak ditemukan di GitHub")
    
    st.title("🛡️ KIPM SIGMA")
    st.markdown("---")
    st.info("Strategic Intelligence & Global Market Analysis")

# 3. Header Utama
st.title("KIPM SIGMA $\Sigma$")
st.write("Strategic Intelligence & Global Market Analysis")
st.divider()

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

# Tampilkan Chat
for msg in st.session_state.messages[1:]:
    with st.chat_message(msg["role"]):
        content = msg["content"]
        st.markdown(content[0]["text"] if isinstance(content, list) else content)

# Input Chat
if prompt := st.chat_input("Tanya SIGMA... (atau ketik 'cek BBCA')"):
    if prompt.lower().startswith("cek "):
        ticker = prompt.split(" ")[1].upper()
        prompt = get_stock_info(ticker)
    
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        model = "llama-3.2-11b-vision-preview" if isinstance(st.session_state.messages[-1]["content"], list) else "llama-3.3-70b-versatile"
        response = client.chat.completions.create(model=model, messages=st.session_state.messages).choices[0].message.content
        st.markdown(response)
        st.session_state.messages.append({"role": "assistant", "content": response})
