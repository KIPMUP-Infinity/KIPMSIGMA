import streamlit as st
from groq import Groq
import yfinance as yf
import fitz  # PyMuPDF untuk PDF
import base64
from PIL import Image
import io
import streamlit.components.v1 as components
import uuid
from datetime import datetime


import streamlit as st
from groq import Groq
import fitz
import base64
from PIL import Image
import io
import streamlit.components.v1 as components
import uuid
from datetime import datetime

st.set_page_config(page_title="KIPM SIGMA", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"], .stMarkdown, .stChatMessage, p, div {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    }
    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }
    section[data-testid="stSidebar"] > div:first-child { padding-top: 1rem; }
    .main-header { text-align: center; margin-bottom: 2rem; }
    [data-testid="stMainBlockContainer"] {
        padding-bottom: 80px !important;
        max-width: 780px !important;
        margin: 0 auto !important;
    }
    [data-testid="stChatMessage"] {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }
    [data-testid="stChatMessageAvatarUser"] { display: none !important; }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"])
    [data-testid="stMarkdownContainer"] {
        font-size: 0.93rem !important;
        line-height: 1.75 !important;
        color: #e8e8e8 !important;
        background: transparent !important;
    }
    div[data-testid="stSidebar"] button {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        color: #ccc !important;
        font-size: 0.85rem !important;
        text-align: left !important;
        padding: 5px 8px !important;
        border-radius: 8px !important;
    }
    div[data-testid="stSidebar"] button:hover {
        background: #2a2a2a !important;
        color: #fff !important;
    }
    </style>
""", unsafe_allow_html=True)


# ── SESSION STATE ─────────────────────────────────────────
SYSTEM_PROMPT = {
    "role": "system",
    "content": """Kamu adalah SIGMA — analis saham dan chart expert dari KIPM Universitas Pancasila (Market n Mocha).

Kamu menggunakan framework analisa MnM Strategy+ yang terdiri dari 5 modul:

1. INVERSION FAIR VALUE GAP (IFVG)
- FVG terbentuk saat gap antara candle 1 dan 3 (low[0]>high[2]=bullish, high[0]<low[2]=bearish)
- IFVG = FVG yang diinversi → zona confluence kuat
- Bullish IFVG (kotak biru): harga break bawah FVG bullish → jadi resistance → tembus naik = sinyal buy
- Bearish IFVG (kotak abu): harga break atas FVG bearish → jadi support → tembus turun = sinyal sell
- Midline (garis putus) = 50% retracement, magnet harga

2. FAIR VALUE GAP (FVG)
- Gap harga belum terisi = imbalance = magnet harga
- Bullish FVG (biru): low[0] > high[2] → support potensial
- Bearish FVG (abu): high[0] < low[2] → resistance potensial
- Termitigasi saat close menembus batas FVG

3. ORDER BLOCK (OB)
- Bullish OB (hijau): candle bearish terakhir sebelum impuls naik → demand institusional
- Bearish OB (ungu): candle bullish terakhir sebelum impuls turun → supply institusional
- Breaker Block: OB yang ditembus → zona berlawanan
- OB + FVG/IFVG = confluence entry terkuat

4. SUPPLY & DEMAND ZONES
- Supply (abu): 3 candle bearish + volume above average → distribusi bandar
- Demand (biru terang): 3 candle bullish + volume above average → akumulasi bandar
- Delta volume: "Supply: -956M | 6.88%" = distribusi; "Demand: 783M | 5.61%" = akumulasi
- Border dashed = zona sedang diuji; zona dihapus saat close tembus

5. MOVING AVERAGE
- EMA 13 (biru) = momentum pendek; EMA 21 (merah) = medium; EMA 50 (ungu) = trend
- Di atas semua MA = bullish; di bawah = bearish; MA rapat = konsolidasi

URUTAN ANALISA:
1. Bias → posisi harga vs Supply/Demand terbesar
2. Struktur → OB aktif, swing high/low
3. Confluence → FVG + IFVG + OB overlap
4. Bandarmologi → delta volume (akumulasi vs distribusi)
5. Entry trigger → confluence + konfirmasi candle

FORMAT TRADE PLAN (SELALU GUNAKAN):
📊 TRADE PLAN — [SAHAM] ([TIMEFRAME])
⚡ Bias: [Bullish/Bearish/Sideways] — [alasan singkat]
🎯 Entry: [harga/range]
🛑 Stop Loss: [harga] — [alasan]
✅ Target 1: [harga] — [alasan]
✅ Target 2: [harga] — [alasan]
📦 Bandarmologi: [ringkasan delta volume]
⚠️ Invalidasi: [kondisi batal]

ATURAN:
- WAJIB analisa gambar langsung, JANGAN bilang tidak bisa melihat
- Warna: biru gelap=FVG/demand, abu=supply/bearish, hijau=bullish OB, ungu=bearish OB
- Selalu komentari angka delta volume di chart
- Jawab Bahasa Indonesia, tegas, no-bias"""
}

def new_session():
    return {"id": str(uuid.uuid4())[:8], "title": "Obrolan Baru",
            "messages": [SYSTEM_PROMPT], "created": datetime.now().strftime("%H:%M")}

if "sessions"   not in st.session_state:
    s = new_session()
    st.session_state.sessions  = [s]
    st.session_state.active_id = s["id"]
if "rename_id"  not in st.session_state: st.session_state.rename_id  = None
if "img_data"   not in st.session_state: st.session_state.img_data   = None  # (b64, mime, name)
if "pdf_data"   not in st.session_state: st.session_state.pdf_data   = None  # (text, name)

def get_active():
    for s in st.session_state.sessions:
        if s["id"] == st.session_state.active_id: return s
    return st.session_state.sessions[0]

def delete_session(sid):
    st.session_state.sessions = [s for s in st.session_state.sessions if s["id"] != sid]
    if not st.session_state.sessions:
        ns = new_session(); st.session_state.sessions = [ns]
    if st.session_state.active_id == sid:
        st.session_state.active_id = st.session_state.sessions[0]["id"]


# ── SIDEBAR ACTIONS VIA QUERY PARAMS ─────────────────────
qp = st.query_params
if "action" in qp:
    a, sid = qp.get("action",""), qp.get("sid","")
    if a == "new":
        ns = new_session(); st.session_state.sessions.insert(0, ns)
        st.session_state.active_id = ns["id"]
        st.query_params.clear(); st.rerun()
    elif a == "sel" and sid:
        st.session_state.active_id = sid; st.session_state.rename_id = None
        st.query_params.clear(); st.rerun()
    elif a == "del" and sid:
        delete_session(sid); st.query_params.clear(); st.rerun()
    elif a == "ren" and sid:
        st.session_state.rename_id = sid; st.query_params.clear(); st.rerun()


# ── SIDEBAR ───────────────────────────────────────────────
with st.sidebar:
    try:
        logo = Image.open("Mate KIPM LOGO.png")
        c1,c2,c3 = st.columns([1,2,1])
        with c2: st.image(logo, use_container_width=True)
    except: st.markdown("### 🏛️ KIPM-UP")

    st.markdown("""
        <div style="text-align:center;line-height:1.4;margin-top:8px;font-family:Inter,sans-serif;">
            <p style="margin:0;font-size:0.78rem;color:#aaa;">Komunitas
                <span style="color:#F5C242;font-weight:600;">Investasi</span> Pasar Modal</p>
            <p style="margin:4px 0 0 0;font-size:1.05rem;font-weight:700;color:#fff;">Universitas Pancasila</p>
        </div>
    """, unsafe_allow_html=True)

    st.divider()

    st.markdown("""
        <a href="?action=new" target="_self" style="
            display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:8px;
            color:#ccc;text-decoration:none;font-size:0.88rem;font-family:Inter,sans-serif;"
           onmouseover="this.style.background='#2a2a2a';this.style.color='#fff'"
           onmouseout="this.style.background='transparent';this.style.color='#ccc'">
            ✏️ &nbsp;Obrolan baru
        </a>
    """, unsafe_allow_html=True)

    st.markdown('<p style="font-size:0.68rem;font-weight:600;color:#555;text-transform:uppercase;letter-spacing:1.2px;margin:10px 0 4px 6px;">Obrolan Anda</p>', unsafe_allow_html=True)

    for sesi in st.session_state.sessions:
        sid = sesi["id"]; is_active = sid == st.session_state.active_id
        title_d = sesi["title"][:34] + "..." if len(sesi["title"]) > 34 else sesi["title"]
        if st.session_state.rename_id == sid:
            new_t = st.text_input("Rename", value=sesi["title"], key=f"ren_{sid}", label_visibility="collapsed")
            co, cc = st.columns([1,1])
            with co:
                if st.button("✓", key=f"ok_{sid}"):
                    sesi["title"] = new_t.strip() or sesi["title"]
                    st.session_state.rename_id = None; st.rerun()
            with cc:
                if st.button("✗", key=f"cx_{sid}"):
                    st.session_state.rename_id = None; st.rerun()
        else:
            bg = "#1e2d45" if is_active else "transparent"
            clr = "#fff" if is_active else "#bbb"
            acts = (
                f'<a href="?action=ren&sid={sid}" target="_self" style="color:#666;text-decoration:none;font-size:0.78rem;padding:2px 5px;" onmouseover="this.style.color=\'#fff\'" onmouseout="this.style.color=\'#666\'">✏️</a>'
                f'<a href="?action=del&sid={sid}" target="_self" style="color:#666;text-decoration:none;font-size:0.78rem;padding:2px 5px;" onmouseover="this.style.color=\'#f66\'" onmouseout="this.style.color=\'#666\'">🗑️</a>'
            ) if is_active else ""
            st.markdown(f"""
                <div style="display:flex;align-items:center;background:{bg};border-radius:8px;margin:1px 0;">
                    <a href="?action=sel&sid={sid}" target="_self" style="flex:1;padding:7px 10px;color:{clr};
                        text-decoration:none;font-size:0.83rem;font-family:Inter,sans-serif;
                        white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block;">
                        💬 {title_d}</a>
                    <div style="display:flex;gap:2px;padding-right:6px;">{acts}</div>
                </div>
            """, unsafe_allow_html=True)


# ── MAIN ─────────────────────────────────────────────────
active = get_active()

st.markdown("""
    <div class="main-header">
        <h1 style="margin:0;">KIPM SIGMA ∑</h1>
        <p style="color:gray;">Strategic Intelligence & Global Market Analysis</p>
    </div>
""", unsafe_allow_html=True)

# Tampilkan history
for i, msg in enumerate(active["messages"][1:]):
    with st.chat_message(msg["role"]):
        display = msg["content"]
        if "Pertanyaan:" in display:
            display = display.split("Pertanyaan:")[-1].strip()
        key = f"thumb_{active['id']}_{i}"
        if msg["role"] == "user" and key in st.session_state:
            b64, mime = st.session_state[key]
            st.markdown(f'<img src="data:{mime};base64,{b64}" style="max-width:100%;max-height:240px;border-radius:10px;margin-bottom:6px;display:block;">', unsafe_allow_html=True)
        st.markdown(display)


# ── CHAT INPUT ────────────────────────────────────────────
# Coba gunakan accept_file (Streamlit >= 1.37)
try:
    result = st.chat_input(
        "Tanya SIGMA... (attach file via tombol +)",
        accept_file="multiple",
        file_type=["pdf", "png", "jpg", "jpeg"]
    )
except TypeError:
    result = st.chat_input("Tanya SIGMA...")

# Parse result
prompt    = None
file_obj  = None

if result is not None:
    if hasattr(result, 'text'):
        # Streamlit 1.37+ object
        prompt   = (result.text or "").strip()
        files    = getattr(result, 'files', None) or []
        if files: file_obj = files[0]
    elif isinstance(result, str):
        prompt = result.strip()
    
    # Kalau ada file dari chat_input, proses langsung
    if file_obj is not None:
        raw = file_obj.read()
        if file_obj.type == "application/pdf":
            doc = fitz.open(stream=raw, filetype="pdf")
            pdf_text = "".join(p.get_text() for p in doc)
            st.session_state.pdf_data = (f"[PDF: {file_obj.name}]\n{pdf_text[:6000]}", file_obj.name)
            st.session_state.img_data = None
        else:
            b64  = base64.b64encode(raw).decode()
            ext  = file_obj.name.split(".")[-1].lower()
            mime = "image/png" if ext == "png" else "image/jpeg"
            st.session_state.img_data  = (b64, mime, file_obj.name)
            st.session_state.pdf_data  = None
    
    # Kalau prompt kosong tapi ada file, beri default prompt
    if not prompt and (file_obj or st.session_state.img_data or st.session_state.pdf_data):
        prompt = "Tolong analisa file yang saya kirim"

if prompt:
    # Ambil data attachment
    img_data = st.session_state.img_data
    pdf_data = st.session_state.pdf_data
    has_image = img_data is not None
    has_pdf   = pdf_data is not None

    # Reset attachment state
    st.session_state.img_data = None
    st.session_state.pdf_data = None

    # Bangun full prompt
    full_prompt = prompt
    if has_image:
        full_prompt = f"[Gambar: {img_data[2]}]\n\nPertanyaan: {prompt}"
    elif has_pdf:
        full_prompt = f"{pdf_data[0]}\n\nPertanyaan: {prompt}"

    # Auto-title
    if active["title"] == "Obrolan Baru":
        active["title"] = prompt[:40] + ("..." if len(prompt) > 40 else "")

    # Simpan thumbnail
    thumb_idx = len(active["messages"]) - 1
    if has_image:
        st.session_state[f"thumb_{active['id']}_{thumb_idx}"] = (img_data[0], img_data[1])

    # Tampilkan pesan user
    active["messages"].append({"role": "user", "content": full_prompt})
    with st.chat_message("user"):
        if has_image:
            st.markdown(
                f'<img src="data:{img_data[1]};base64,{img_data[0]}" style="max-width:100%;max-height:240px;border-radius:10px;margin-bottom:6px;display:block;">',
                unsafe_allow_html=True
            )
        st.markdown(prompt)

    # Panggil API
    try:
        groq_client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        with st.chat_message("assistant"):
            with st.spinner("SIGMA sedang menganalisis..."):
                if has_image:
                    res = groq_client.chat.completions.create(
                        model="meta-llama/llama-4-scout-17b-16e-instruct",
                        messages=[
                            {"role": "system", "content": (
                                "Kamu adalah SIGMA, analis chart expert. "
                                "Lihat gambar chart ini dengan seksama dan langsung analisa: "
                                "1) Nama saham & timeframe 2) Trend (uptrend/downtrend/sideways) "
                                "3) Support & Resistance 4) Pola teknikal 5) Volume & bandarmologi "
                                "6) Trade plan (entry, stop loss, target). "
                                "WAJIB analisa gambar secara langsung. Jawab Bahasa Indonesia."
                            )},
                            {"role": "user", "content": [
                                {"type": "image_url", "image_url": {
                                    "url": f"data:{img_data[1]};base64,{img_data[0]}"
                                }},
                                {"type": "text", "text": prompt}
                            ]}
                        ],
                        max_tokens=2048
                    )
                else:
                    res = groq_client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=active["messages"],
                        temperature=0.7,
                        max_tokens=2048
                    )
                ans = res.choices[0].message.content
            st.markdown(ans)
        active["messages"].append({"role": "assistant", "content": ans})

    except Exception as e:
        import traceback
        st.error(f"❌ Error: {e}")
        st.code(traceback.format_exc())

    st.rerun()


# ── JS: Bubble user ke kanan + Ctrl+V paste support ──────
components.html("""
<script>
// Fix bubble kanan
function fixBubbles() {
    const doc = window.parent.document;
    doc.querySelectorAll('[data-testid="stChatMessage"]').forEach(msg => {
        const isUser = msg.querySelector('[data-testid="stChatMessageAvatarUser"]');
        if (!isUser) return;
        msg.style.cssText += 'display:flex!important;justify-content:flex-end!important;background:transparent!important;border:none!important;box-shadow:none!important;padding:4px 0!important;';
        const av = msg.querySelector('[data-testid="stChatMessageAvatarUser"]');
        if (av) av.style.display = 'none';
        const ct = msg.querySelector('[data-testid="stChatMessageContent"]');
        if (ct) ct.style.cssText += 'background:transparent!important;display:flex!important;justify-content:flex-end!important;max-width:100%!important;padding:0!important;';
        msg.querySelectorAll('[data-testid="stMarkdownContainer"]').forEach(md => {
            md.style.background = 'transparent';
            md.style.display = 'flex';
            md.style.justifyContent = 'flex-end';
            if (!md.querySelector('.navy-pill')) {
                const pill = document.createElement('div');
                pill.className = 'navy-pill';
                pill.style.cssText = 'background-color:#1B2A4A;color:#fff;border-radius:18px 18px 4px 18px;padding:10px 16px;max-width:72%;display:inline-block;font-size:0.93rem;line-height:1.6;font-family:Inter,sans-serif;word-wrap:break-word;';
                while (md.firstChild) pill.appendChild(md.firstChild);
                md.appendChild(pill);
                pill.querySelectorAll('*').forEach(el => el.style.color = '#fff');
            }
        });
    });
}
fixBubbles();
setInterval(fixBubbles, 800);
new MutationObserver(() => setTimeout(fixBubbles, 100)).observe(
    window.parent.document.body, {childList:true, subtree:true}
);

// Ctrl+V paste gambar — inject ke SEMUA file input yang ada
function setupPaste() {
    const parentDoc = window.parent.document;

    // Pasang listener di document level (lebih reliable)
    if (parentDoc._pasteListenerSet) return;
    parentDoc._pasteListenerSet = true;

    parentDoc.addEventListener('paste', function(e) {
        const items = e.clipboardData && e.clipboardData.items;
        if (!items) return;

        for (let item of items) {
            if (!item.type.startsWith('image/')) continue;

            const file = item.getAsFile();
            if (!file) continue;

            // Cari semua file input di halaman
            const fileInputs = parentDoc.querySelectorAll('input[type="file"]');
            let injected = false;

            for (let fi of fileInputs) {
                try {
                    const dt = new DataTransfer();
                    dt.items.add(file);
                    // Override files property
                    Object.defineProperty(fi, 'files', {
                        value: dt.files,
                        configurable: true,
                        writable: true
                    });
                    fi.dispatchEvent(new Event('change', {bubbles: true}));
                    fi.dispatchEvent(new Event('input',  {bubbles: true}));
                    injected = true;
                    break;
                } catch(err) {}
            }

            if (injected) {
                // Beri feedback visual ke user
                const textarea = parentDoc.querySelector('[data-testid="stChatInput"] textarea');
                if (textarea) {
                    const prev = textarea.placeholder;
                    textarea.placeholder = '📎 Gambar berhasil di-paste! Ketik pertanyaan lalu Enter...';
                    setTimeout(() => { textarea.placeholder = prev; }, 3000);
                }
            }
            break; // hanya proses 1 gambar per paste
        }
    });
}
// Setup segera dan pastikan terpasang
setupPaste();
setTimeout(setupPaste, 2000);
setTimeout(setupPaste, 5000);
</script>
""", height=0)
