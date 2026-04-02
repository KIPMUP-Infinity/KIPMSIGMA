# ─────────────────────────────────────────────
# REPLACE FUNGSI show_system_selector() di app.py
# Ini adalah versi upgrade dengan perubahan MINIMAL dari original:
# - CSS diperbarui (font tetap system font, warna lebih tajam, corner brackets)
# - Card terminal mendapat: mini terminal preview + data pills
# - Struktur HTML/JS identik dengan aslinya (tidak ada perubahan arsitektur)
# ─────────────────────────────────────────────

def show_system_selector():
    """Halaman promosi pemilihan sistem — upgraded terminal card."""
    _user = st.session_state.user
    _name = (_user.get("name") or _user.get("email","")).split()[0] if _user else "Trader"

    st.markdown("""
    <style>
    [data-testid="stSidebar"] { display: none !important; }
    header[data-testid="stHeader"] { display: none !important; }
    #MainMenu { display: none !important; }
    footer { display: none !important; }
    .stApp, [data-testid="stAppViewContainer"], section[data-testid="stMain"],
    [data-testid="stMainBlockContainer"] {
        background: #080c14 !important;
        max-width: 100% !important;
        padding: 0 !important;
        margin: 0 !important;
    }
    [data-testid="stVerticalBlock"] { gap: 0 !important; }
    [data-testid="stHorizontalBlock"] {
        position: fixed !important; bottom: -300px !important;
        opacity: 0 !important; height: 1px !important; width: 1px !important; overflow: hidden !important; z-index: -999 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    _terminal_url = st.secrets.get("SIGMA_TERMINAL_URL", "")

    components.html(f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; }}
body {{ background: #080c14; }}

.sys-wrapper {{
    min-height: 100vh; background: #080c14;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    padding: 40px 20px; position: relative; overflow: hidden;
}}
.sys-wrapper::before {{
    content: ''; position: absolute; inset: 0;
    background-image: linear-gradient(rgba(0,157,255,0.06) 1px, transparent 1px),
                      linear-gradient(90deg, rgba(0,157,255,0.06) 1px, transparent 1px);
    background-size: 60px 60px;
    animation: gridPulse 8s ease-in-out infinite; pointer-events: none;
}}
@keyframes gridPulse {{ 0%,100% {{ opacity:0.4; }} 50% {{ opacity:1; }} }}
.orb {{
    position: absolute; width: 600px; height: 600px; border-radius: 50%;
    background: radial-gradient(circle, rgba(0,100,255,0.12) 0%, transparent 70%);
    top: -150px; left: -100px; pointer-events: none;
    animation: orbFloat 12s ease-in-out infinite;
}}
.orb2 {{
    position: absolute; width: 400px; height: 400px; border-radius: 50%;
    background: radial-gradient(circle, rgba(245,194,66,0.07) 0%, transparent 70%);
    bottom: -100px; right: -80px; pointer-events: none;
    animation: orbFloat 15s ease-in-out infinite reverse;
}}
@keyframes orbFloat {{ 0%,100% {{ transform:translate(0,0); }} 50% {{ transform:translate(60px,40px); }} }}

.sys-header {{ text-align:center; margin-bottom:48px; position:relative; z-index:2; }}
.sys-welcome {{ font-size:0.8rem; letter-spacing:4px; color:rgba(0,157,255,0.7); text-transform:uppercase; margin-bottom:10px; }}
.sys-title {{ font-size:2.8rem; font-weight:700; color:#fff; letter-spacing:2px; line-height:1.1; margin-bottom:6px; }}
.sys-title span {{ color:#F5C242; }}
.sys-subtitle {{ font-size:0.85rem; color:rgba(255,255,255,0.35); letter-spacing:1px; }}
.sys-divider {{ width:60px; height:2px; background:linear-gradient(90deg,transparent,#009dff,transparent); margin:14px auto 0; animation:shimmer 2.5s ease-in-out infinite; }}
@keyframes shimmer {{ 0%,100% {{ opacity:0.4; width:40px; }} 50% {{ opacity:1; width:80px; }} }}

.sys-cards {{ display:flex; gap:28px; flex-wrap:wrap; justify-content:center; position:relative; z-index:2; max-width:860px; width:100%; }}

.sys-card {{
    flex:1; min-width:300px; max-width:400px;
    background:rgba(10,14,26,0.9); border:1px solid rgba(255,255,255,0.08);
    border-radius:20px; padding:28px 26px 26px;
    position:relative; overflow:hidden; cursor:pointer;
    transition:transform 0.3s ease, box-shadow 0.3s ease, border-color 0.3s ease;
}}
.sys-card::before {{
    content:''; position:absolute; top:0; left:0; right:0; height:1px; border-radius:20px 20px 0 0;
}}
.sigma-chat::before {{ background:linear-gradient(90deg,transparent,#009dff,#0048ff,transparent); }}
.sigma-terminal::before {{ background:linear-gradient(90deg,transparent,#F5C242,#e0a820,transparent); }}

/* corner brackets */
.sys-card::after {{
    content:''; position:absolute; bottom:12px; right:12px;
    width:14px; height:14px; border-bottom:1px solid; border-right:1px solid; border-radius:0 0 3px 0;
    opacity:0.22;
}}
.sigma-chat::after {{ border-color:#009dff; }}
.sigma-terminal::after {{ border-color:#F5C242; }}
.corner-tl {{
    position:absolute; top:12px; left:12px;
    width:14px; height:14px; border-top:1px solid; border-left:1px solid; border-radius:3px 0 0 0;
    opacity:0.22; pointer-events:none;
}}
.sigma-chat .corner-tl {{ border-color:#009dff; }}
.sigma-terminal .corner-tl {{ border-color:#F5C242; }}

.card-glow {{
    position:absolute; width:220px; height:220px; border-radius:50%;
    filter:blur(60px); opacity:0; top:-60px; right:-40px;
    transition:opacity 0.4s ease; pointer-events:none;
}}
.sigma-chat .card-glow {{ background:rgba(0,157,255,0.3); }}
.sigma-terminal .card-glow {{ background:rgba(245,194,66,0.22); }}
.sys-card:hover .card-glow {{ opacity:1; }}
.sys-card:hover {{ transform:translateY(-6px); }}
.sigma-chat:hover {{ border-color:rgba(0,157,255,0.45); box-shadow:0 20px 60px rgba(0,100,255,0.18),0 0 0 1px rgba(0,157,255,0.28); }}
.sigma-terminal:hover {{ border-color:rgba(245,194,66,0.45); box-shadow:0 20px 60px rgba(245,194,66,0.12),0 0 0 1px rgba(245,194,66,0.28); }}

.card-badge {{ position:absolute; top:18px; right:20px; font-size:0.6rem; letter-spacing:2.5px; text-transform:uppercase; padding:3px 10px; border-radius:20px; font-weight:600; }}
.sigma-chat .card-badge {{ background:rgba(0,157,255,0.12); color:#009dff; border:1px solid rgba(0,157,255,0.22); }}
.sigma-terminal .card-badge {{ background:rgba(245,194,66,0.1); color:#F5C242; border:1px solid rgba(245,194,66,0.18); }}

.card-icon {{ width:52px; height:52px; border-radius:14px; display:flex; align-items:center; justify-content:center; font-size:1.4rem; margin-bottom:18px; }}
.sigma-chat .card-icon {{ background:rgba(0,157,255,0.1); border:1px solid rgba(0,157,255,0.22); }}
.sigma-terminal .card-icon {{ background:rgba(245,194,66,0.08); border:1px solid rgba(245,194,66,0.18); }}

.card-name {{ font-size:1.35rem; font-weight:700; color:#fff; margin-bottom:5px; letter-spacing:-0.2px; }}
.card-tagline {{ font-size:0.65rem; letter-spacing:3px; text-transform:uppercase; margin-bottom:14px; font-weight:400; }}
.sigma-chat .card-tagline {{ color:rgba(0,157,255,0.65); }}
.sigma-terminal .card-tagline {{ color:rgba(245,194,66,0.65); }}
.card-desc {{ font-size:0.83rem; color:rgba(255,255,255,0.45); line-height:1.75; margin-bottom:20px; }}

/* ── TERMINAL PREVIEW (hanya untuk card terminal) ── */
.term-preview {{
    background:rgba(0,0,0,0.45);
    border:1px solid rgba(245,194,66,0.12);
    border-radius:10px;
    padding:10px 12px;
    margin-bottom:14px;
    font-family: 'SF Mono','Fira Code','Consolas','Courier New',monospace;
    font-size:0.62rem;
    line-height:1.85;
    position:relative;
    overflow:hidden;
}}
.term-preview::after {{
    content:'';position:absolute;bottom:0;left:0;right:0;height:35%;
    background:linear-gradient(transparent,rgba(0,0,0,0.6));
    pointer-events:none;
}}
.t-row {{ display:flex; gap:8px; }}
.t-prompt {{ color:rgba(245,194,66,0.55); }}
.t-cmd {{ color:rgba(255,255,255,0.3); }}
.t-label {{ color:rgba(255,255,255,0.25); min-width:38px; }}
.t-up {{ color:#4ade80; }}
.t-dn {{ color:#f87171; }}
.t-cursor {{
    display:inline-block; width:5px; height:10px;
    background:rgba(245,194,66,0.8); vertical-align:middle; margin-left:2px;
    animation:cursorBlink 1.1s step-end infinite;
}}
@keyframes cursorBlink {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:0; }} }}

/* ── DATA PILLS ── */
.data-pills {{ display:flex; flex-wrap:wrap; gap:5px; margin-bottom:16px; }}
.pill {{
    font-family: 'SF Mono','Fira Code','Consolas','Courier New',monospace;
    font-size:0.57rem; padding:3px 8px; border-radius:5px; border:1px solid; letter-spacing:0.3px;
}}
.pill-up {{ color:#4ade80; border-color:rgba(74,222,128,0.2); background:rgba(74,222,128,0.06); }}
.pill-dn {{ color:#f87171; border-color:rgba(248,113,113,0.2); background:rgba(248,113,113,0.06); }}
.pill-neu {{ color:rgba(245,194,66,0.8); border-color:rgba(245,194,66,0.15); background:rgba(245,194,66,0.04); }}

.card-features {{ list-style:none; padding:0; margin:0 0 24px 0; }}
.card-features li {{ font-size:0.78rem; color:rgba(255,255,255,0.5); padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.05); display:flex; align-items:center; gap:8px; }}
.card-features li:last-child {{ border-bottom:none; }}
.feat-dot {{ width:5px; height:5px; border-radius:50%; flex-shrink:0; }}
.sigma-chat .feat-dot {{ background:#009dff; box-shadow:0 0 5px rgba(0,157,255,0.7); }}
.sigma-terminal .feat-dot {{ background:#F5C242; box-shadow:0 0 5px rgba(245,194,66,0.6); }}

.card-cta {{ width:100%; padding:13px; border-radius:12px; border:none; font-size:0.85rem; font-weight:700; letter-spacing:1px; cursor:pointer; transition:opacity 0.2s, transform 0.15s; text-transform:uppercase; display:flex; align-items:center; justify-content:center; gap:8px; }}
.sigma-chat .card-cta {{ background:linear-gradient(135deg,#009dff,#0048ff); color:#fff; box-shadow:0 6px 24px rgba(0,100,255,0.32); }}
.sigma-terminal .card-cta {{ background:linear-gradient(135deg,#F5C242,#e0a820); color:#07090f; box-shadow:0 6px 24px rgba(245,194,66,0.26); }}
.card-cta:hover {{ opacity:0.88; transform:translateY(-1px); }}

.sys-footer {{ margin-top:48px; text-align:center; font-size:0.72rem; color:rgba(255,255,255,0.2); letter-spacing:1px; position:relative; z-index:2; }}

@media (max-width:768px) {{
    .sys-wrapper {{ padding: 20px 16px 40px; justify-content: flex-start; min-height: 100vh; }}
    .sys-header {{ margin-bottom: 24px; }}
    .sys-welcome {{ font-size: 0.65rem; margin-bottom: 4px; }}
    .sys-title {{ font-size: 1.8rem; margin-bottom: 4px; }}
    .sys-subtitle {{ font-size: 0.75rem; }}
    .sys-divider {{ margin-top: 10px; margin-bottom: 0; }}
    .sys-cards {{ gap: 14px; flex-direction: column; align-items: center; width: 100%; }}
    .sys-card {{ width: 100%; min-width: unset; max-width: 100%; padding: 22px 18px 18px; border-radius: 16px; }}
    .card-icon {{ width: 44px; height: 44px; font-size: 1.2rem; margin-bottom: 12px; }}
    .card-badge {{ top: 14px; right: 14px; font-size: 0.55rem; padding: 3px 8px; }}
    .card-name {{ font-size: 1.2rem; margin-bottom: 4px; }}
    .card-tagline {{ font-size: 0.65rem; margin-bottom: 12px; }}
    .card-desc {{ font-size: 0.78rem; margin-bottom: 14px; line-height: 1.5; }}
    .card-features {{ margin-bottom: 18px; }}
    .card-features li {{ font-size: 0.75rem; padding: 5px 0; gap: 6px; }}
    .card-cta {{ padding: 12px; font-size: 0.85rem; }}
    .sys-footer {{ margin-top: 32px; font-size: 0.65rem; }}
}}
</style>
</head>
<body>
<div class="sys-wrapper">
    <div class="orb"></div>
    <div class="orb2"></div>

    <div class="sys-header">
        <div class="sys-welcome">Welcome back, {_name}</div>
        <div class="sys-title">Choose Your <span>System</span></div>
        <div class="sys-subtitle">Select the platform you want to access today</div>
        <div class="sys-divider"></div>
    </div>

    <div class="sys-cards">
        <div class="sys-card sigma-chat" id="card-chat" onclick="selectChat()">
            <div class="card-glow"></div>
            <div class="corner-tl"></div>
            <div class="card-badge">&#9679; Live</div>
            <div class="card-icon">&#9889;</div>
            <div class="card-name">SIGMA AI Chat</div>
            <div class="card-tagline">AI Trading Assistant</div>
            <div class="card-desc">Asisten analisa pasar berbasis AI &#8212; teknikal, fundamental, bandarmologi, dan makro dalam satu percakapan.</div>
            <ul class="card-features">
                <li><span class="feat-dot"></span>Analisa teknikal MnM Strategy+</li>
                <li><span class="feat-dot"></span>Bandarmologi &amp; broker summary IDX</li>
                <li><span class="feat-dot"></span>Fundamental multi-source real-time</li>
                <li><span class="feat-dot"></span>Dampak makro global &#8594; emiten IDX</li>
                <li><span class="feat-dot"></span>Upload chart &amp; PDF prospektus</li>
            </ul>
            <button class="card-cta" onclick="event.stopPropagation(); selectChat()">Masuk ke AI Chat &#8594;</button>
        </div>

        <div class="sys-card sigma-terminal" id="card-terminal" onclick="selectTerminal()">
            <div class="card-glow"></div>
            <div class="corner-tl"></div>
            <div class="card-badge">&#9670; Beta</div>
            <div class="card-icon">&#128187;</div>
            <div class="card-name">SIGMA Terminal</div>
            <div class="card-tagline">Market Dashboard</div>
            <div class="card-desc">Dashboard pasar real-time &#8212; Market Overview, Broker Summary, Screener, dan Watchlist dalam satu layar.</div>

            <div class="term-preview">
                <div class="t-row"><span class="t-prompt">$</span><span class="t-cmd"> sigma.fetch --market IDX --live</span></div>
                <div class="t-row"><span class="t-label">IHSG </span><span class="t-up">&#9650; 7,421  +0.74%</span></div>
                <div class="t-row"><span class="t-label">LQ45 </span><span class="t-dn">&#9660; 862.3  -0.31%</span></div>
                <div class="t-row"><span class="t-label">IDX30</span><span class="t-up">&#9650; 487.1  +0.52%</span></div>
                <div class="t-row"><span class="t-prompt">_</span><span class="t-cursor"></span></div>
            </div>

            <div class="data-pills">
                <span class="pill pill-up">BBRI &#9650;1.4%</span>
                <span class="pill pill-dn">TLKM &#9660;0.8%</span>
                <span class="pill pill-up">ADRO &#9650;2.1%</span>
                <span class="pill pill-neu">VOL 12.4B</span>
                <span class="pill pill-up">ANTM &#9650;0.9%</span>
            </div>

            <ul class="card-features">
                <li><span class="feat-dot"></span>Market Overview &#8212; IHSG &amp; indeks sektoral</li>
                <li><span class="feat-dot"></span>Broker Summary real-time IDX</li>
                <li><span class="feat-dot"></span>Stock Screener dengan filter custom</li>
                <li><span class="feat-dot"></span>Watchlist personal dengan alert</li>
                <li><span class="feat-dot"></span>Data langsung dari BEI</li>
            </ul>
            <button class="card-cta" onclick="event.stopPropagation(); selectTerminal()">Masuk ke Terminal &#8594;</button>
        </div>
    </div>

    <div class="sys-footer">SIGMA &middot; by MarketnMocha(MnM) &times; KIPM Universitas Pancasila</div>
</div>

<script>
var TERMINAL_URL = "{_terminal_url}";

function selectChat() {{
    try {{
        var pd = window.parent.document;
        var btns = pd.querySelectorAll('[data-testid="stButton"] button');
        for (var i = 0; i < btns.length; i++) {{
            var txt = (btns[i].innerText || btns[i].textContent || "").toLowerCase();
            if (txt.includes('chat')) {{
                btns[i].click();
                return;
            }}
        }}
    }} catch(e) {{}}
    setTimeout(function() {{
        try {{
            var u = new URL(window.parent.location.href);
            u.searchParams.set('action', 'open_chat');
            window.parent.location.assign(u.toString());
        }} catch(e) {{}}
    }}, 150);
}}

function selectTerminal() {{
    if (TERMINAL_URL && TERMINAL_URL.length > 4) {{
        window.parent.location.href = TERMINAL_URL;
        return;
    }}
    try {{
        var pd = window.parent.document;
        var btns = pd.querySelectorAll('[data-testid="stButton"] button');
        for (var i = 0; i < btns.length; i++) {{
            var txt = (btns[i].innerText || btns[i].textContent || "").toLowerCase();
            if (txt.includes('terminal')) {{
                btns[i].click();
                return;
            }}
        }}
    }} catch(e) {{}}
    setTimeout(function() {{
        try {{
            var u = new URL(window.parent.location.href);
            u.searchParams.set('action', 'open_terminal');
            window.parent.location.assign(u.toString());
        }} catch(e) {{}}
    }}, 150);
}}
</script>

</body>
</html>
    """, height=1350, scrolling=False)

    # ── JALUR ANDROID / WINDOWS: Tombol Streamlit Tersembunyi ──
    col1, col2 = st.columns(2)
    with col1:
        btn_chat = st.button("chat", key="btn_sys_chat", use_container_width=True)
    with col2:
        btn_terminal = st.button("terminal", key="btn_sys_terminal", use_container_width=True)

    if btn_chat:
        st.session_state.selected_system = "chat"
        st.session_state.current_view = "chat"
        st.rerun()

    if btn_terminal:
        _turl = st.secrets.get("SIGMA_TERMINAL_URL", "")
        if _turl:
            st.session_state.selected_system = "terminal"
        else:
            st.session_state.selected_system = "terminal_local"
            st.session_state.current_view = "dashboard"
        st.rerun()

    # ── JALUR APPLE SAFARI: Menangkap sinyal dari URL Parameter ──
    if "action" in st.query_params:
        _action = st.query_params.get("action")
        try: st.query_params.pop("action", None)
        except: pass

        if _action == "open_chat":
            st.session_state.selected_system = "chat"
            st.session_state.current_view = "chat"
            st.rerun()
        elif _action == "open_terminal":
            _turl = st.secrets.get("SIGMA_TERMINAL_URL", "")
            if _turl:
                st.session_state.selected_system = "terminal"
            else:
                st.session_state.selected_system = "terminal_local"
                st.session_state.current_view = "dashboard"
            st.rerun()

    st.stop()
