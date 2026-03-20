import streamlit as st
from groq import Groq
import yfinance as yf
import fitz  # PyMuPDF untuk PDF
import base64
from PIL import Image
import io

# 1. Konfigurasi Halaman
st.set_page_config(
    page_title="KIPM SIGMA PRO",
    layout="wide",
    initial_sidebar_state="expanded"  # Bisa diganti "collapsed" jika ingin mulai tertutup
)

# 2. CSS — BERSIH, tanpa override paksa pada sidebar
st.markdown("""
    <style>
    /* Sembunyikan header bawaan Streamlit */
    header {visibility: hidden;}

    /* 
        KUNCI UTAMA: JANGAN override width sidebar dengan !important.
        Biarkan Streamlit mengatur toggle sidebar secara native.
        CSS di bawah hanya mempercantik tampilan, bukan memaksanya.
    */

    /* Container utama — tengah layar dengan max-width nyaman */
    [data-testid="stMainBlockContainer"] {
        max-width: 820px !important;
        margin: 0 auto !important;
        padding-top: 2rem !important;
    }

    /* Header judul */
    .main-header {
        text-align: center;
        margin-bottom: 2rem;
    }

    /* Input Chat — padding kiri agar tidak tertimpa ikon clip */
    .stChatInputContainer textarea {
        padding-left: 55px !important;
        border-radius: 25px !important;
    }

    /* 
        Ikon Attach (Popover / Paperclip)
        Gunakan 'left' berbasis vw agar responsif saat sidebar buka/tutup.
        Nilai ini perlu kamu fine-tune sesuai resolusi monitor kamu.
    */
    div[data-testid="stPopover"] {
        position: fixed;
        bottom: 34px;
        left: calc(50% - 360px);  /* Sesuaikan angka ini jika posisi meleset */
        z-index: 1001;
    }

    /* Responsivitas layar kecil / mobile */
    @media (max-width: 850px) {
        div[data-testid="stPopover"] {
            left: 48px;
        }
        [data-testid="stMainBlockContainer"] {
            max-width: 95% !important;
        }
    }

    /* Tombol Klip — transparan, menyatu dengan chat bar */
    div[data-testid="stPopover"] > button {
        border: none !important;
        background: transparent !important;
        font-size: 22px !important;
        color: #888 !important;
        cursor: pointer !important;
    }

    /* Sidebar: hanya styling visual, TIDAK ada width override */
    section[data-testid="stSidebar"] > div {
        padding-top: 1.5rem;
    }
    </style>
    """, unsafe_allow_html=True)


# 3. SIDEBAR
with st.sidebar:
    try:
        logo = Image.open("Mate KIPM LOGO.png")
        st.image(logo, use_container_width=True)
    except:
        st.write("Logo Organisasi")

    st.markdown("""
        <div style="text-align: center; line-height: 1.2; margin-top: 10px;">
            <p style="margin: 0; font-size: 0.8em; color: gray;">Komunitas Investasi Pasar Modal</p>
            <p style="margin: 0; font-size: 1em; font-weight: bold;">Universitas Pancasila</p>
        </div>
        """, unsafe_allow_html=True)

    st.divider()
    st.subheader("📜 History Searching")

    # Tampilkan history dari session state
    if "messages" in st.session_state:
        for msg in st.session_state.messages[1:]:
            if msg["role"] == "user":
                # Potong teks panjang agar rapi di sidebar
                preview = msg["content"][:50] + "..." if len(msg["content"]) > 50 else msg["content"]
                st.markdown(f"🔍 {preview}")


# 4. HEADER UTAMA
st.markdown("""
    <div class="main-header">
        <h1 style="margin:0;">KIPM SIGMA ∑</h1>
        <p style="color:gray;">Strategic Intelligence & Global Market Analysis</p>
    </div>
    """, unsafe_allow_html=True)


# 5. INISIALISASI SESSION STATE
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

# Tampilkan riwayat chat (skip index 0 = system prompt)
for msg in st.session_state.messages[1:]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])


# 6. UPLOAD ATTACHMENT
with st.popover("📎"):
    uploaded_file = st.file_uploader(
        "Upload file (PDF / Gambar)",
        type=["pdf", "png", "jpg", "jpeg"],
        label_visibility="collapsed"
    )

    # Proses file yang diupload
    if uploaded_file is not None:
        file_type = uploaded_file.type

        if file_type == "application/pdf":
            # Ekstrak teks dari PDF
            pdf_bytes = uploaded_file.read()
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            pdf_text = ""
            for page in doc:
                pdf_text += page.get_text()
            st.session_state["attachment_text"] = f"[PDF diunggah]\n{pdf_text[:3000]}"
            st.success(f"✅ PDF berhasil dibaca ({len(pdf_text)} karakter)")

        elif file_type in ["image/png", "image/jpeg", "image/jpg"]:
            image = Image.open(uploaded_file)
            st.image(image, caption="Gambar diunggah", use_container_width=True)
            # Simpan sebagai base64 jika ingin dikirim ke model vision
            buffered = io.BytesIO()
            image.save(buffered, format="PNG")
            img_b64 = base64.b64encode(buffered.getvalue()).decode()
            st.session_state["attachment_text"] = f"[Gambar diunggah — deskripsi manual diperlukan]"
            st.info("Gambar berhasil dimuat. Tanyakan sesuatu tentang gambar ini.")


# 7. CHAT INPUT & RESPONSE
if prompt := st.chat_input("Tanya SIGMA..."):

    # Gabungkan attachment jika ada
    full_prompt = prompt
    if "attachment_text" in st.session_state:
        full_prompt = f"{st.session_state['attachment_text']}\n\nPertanyaan: {prompt}"
        del st.session_state["attachment_text"]  # Reset setelah dipakai

    st.session_state.messages.append({"role": "user", "content": full_prompt})
    with st.chat_message("user"):
        st.markdown(prompt)  # Tampilkan prompt asli tanpa attachment text

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
