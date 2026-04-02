def show_system_selector():
    """Halaman pemilihan sistem — v2 redesign: Syne + IBM Plex Mono, terminal preview, data pills."""
    _user = st.session_state.user
    _name = (_user.get("name") or _user.get("email","")).split()[0] if _user else "Trader"

    st.markdown("""
    <style>
    [data-testid="stSidebar"]{display:none!important;}
    header[data-testid="stHeader"]{display:none!important;}
    #MainMenu{display:none!important;}
    footer{display:none!important;}
    .stApp,[data-testid="stAppViewContainer"],section[data-testid="stMain"],
    [data-testid="stMainBlockContainer"]{
        background:#060a12!important;
        max-width:100%!important;padding:0!important;margin:0!important;
    }
    [data-testid="stVerticalBlock"]{gap:0!important;}
    [data-testid="stHorizontalBlock"]{
        position:fixed!important;bottom:-300px!important;
        opacity:0!important;height:1px!important;width:1px!important;
        overflow:hidden!important;z-index:-999!important;
    }
    </style>
    """, unsafe_allow_html=True)

    _terminal_url = st.secrets.get("SIGMA_TERMINAL_URL", "")

    components.html(f"""
<!DOCTYPE html><html><head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500&family=Syne:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
:root{{--blue:#009dff;--gold:#F5C242;--gold2:#e0a820;--bg:#060a12;--card-bg:rgba(10,15,28,0.85);--bdr:rgba(255,255,255,0.07);--text:#e8ecf4;--muted:rgba(232,236,244,0.38);}}
body{{background:var(--bg);font-family:'Syne',sans-serif;color:var(--text);min-height:100vh;overflow-x:hidden;}}
.bg-layer{{position:fixed;inset:0;pointer-events:none;z-index:0;background:radial-gradient(ellipse 80% 60% at 15% 10%,rgba(0,80,200,0.10) 0%,transparent 65%),radial-gradient(ellipse 60% 50% at 85% 90%,rgba(245,194,66,0.07) 0%,transparent 60%);}}
.grid-bg{{position:fixed;inset:0;pointer-events:none;z-index:0;background-image:linear-gradient(rgba(0,157,255,0.04) 1px,transparent 1px),linear-gradient(90deg,rgba(0,157,255,0.04) 1px,transparent 1px);background-size:80px 80px;animation:gridPulse 10s ease-in-out infinite;}}
.scanlines{{position:fixed;inset:0;pointer-events:none;z-index:0;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,157,255,0.012) 2px,rgba(0,157,255,0.012) 4px);}}
@keyframes gridPulse{{0%,100%{{opacity:0.5}}50%{{opacity:1}}}}
.wrapper{{position:relative;z-index:2;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:60px 24px 48px;}}
.header{{text-align:center;margin-bottom:52px;}}
.sys-badge{{display:inline-flex;align-items:center;gap:8px;font-family:'IBM Plex Mono',monospace;font-size:0.65rem;letter-spacing:3px;color:rgba(0,157,255,0.65);text-transform:uppercase;border:1px solid rgba(0,157,255,0.18);border-radius:100px;padding:5px 16px;background:rgba(0,157,255,0.05);margin-bottom:20px;animation:fadeUp 0.6s ease both;}}
.sys-badge::before{{content:'';width:6px;height:6px;border-radius:50%;background:var(--blue);box-shadow:0 0 8px var(--blue);animation:blink 2s ease-in-out infinite;}}
@keyframes blink{{0%,100%{{opacity:1}}50%{{opacity:0.2}}}}
.welcome{{font-size:0.72rem;letter-spacing:4px;color:rgba(0,157,255,0.5);text-transform:uppercase;font-family:'IBM Plex Mono',monospace;margin-bottom:12px;animation:fadeUp 0.6s 0.1s ease both;}}
.title{{font-size:clamp(2rem,4vw,3.2rem);font-weight:800;color:#fff;letter-spacing:-0.5px;line-height:1.05;margin-bottom:10px;animation:fadeUp 0.6s 0.15s ease both;}}
.title span{{color:var(--gold);}}
.subtitle{{font-size:0.82rem;color:var(--muted);letter-spacing:0.5px;line-height:1.6;animation:fadeUp 0.6s 0.2s ease both;font-family:'IBM Plex Mono',monospace;}}
.divider{{width:80px;height:1px;background:linear-gradient(90deg,transparent,rgba(0,157,255,0.5),transparent);margin:18px auto 0;animation:shimmer 3s ease-in-out infinite;}}
@keyframes shimmer{{0%,100%{{width:40px;opacity:0.4}}50%{{width:100px;opacity:1}}}}
.cards{{display:flex;gap:24px;flex-wrap:wrap;justify-content:center;max-width:900px;width:100%;}}
.card{{flex:1;min-width:310px;max-width:420px;background:var(--card-bg);border:1px solid var(--bdr);border-radius:24px;padding:0;position:relative;overflow:hidden;cursor:pointer;transition:transform 0.35s cubic-bezier(0.34,1.56,0.64,1),box-shadow 0.35s ease,border-color 0.3s ease;backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);animation:fadeUp 0.6s 0.3s ease both;}}
.card:nth-child(2){{animation-delay:0.4s}}
.card:hover{{transform:translateY(-8px) scale(1.01);}}
.card::before{{content:'';position:absolute;top:0;left:0;right:0;height:1px;border-radius:24px 24px 0 0;transition:opacity 0.3s;}}
.card-chat::before{{background:linear-gradient(90deg,transparent 10%,#009dff 50%,transparent 90%);}}
.card-terminal::before{{background:linear-gradient(90deg,transparent 10%,#F5C242 50%,transparent 90%);}}
.glow{{position:absolute;width:280px;height:280px;border-radius:50%;filter:blur(80px);opacity:0;transition:opacity 0.5s ease;pointer-events:none;}}
.card-chat .glow{{background:rgba(0,157,255,0.25);top:-80px;right:-60px;}}
.card-terminal .glow{{background:rgba(245,194,66,0.2);top:-80px;right:-60px;}}
.card:hover .glow{{opacity:1;}}
.card-chat:hover{{border-color:rgba(0,157,255,0.45);box-shadow:0 24px 70px rgba(0,80,255,0.18),0 0 0 1px rgba(0,157,255,0.25);}}
.card-terminal:hover{{border-color:rgba(245,194,66,0.45);box-shadow:0 24px 70px rgba(245,194,66,0.12),0 0 0 1px rgba(245,194,66,0.25);}}
.card-head{{padding:28px 28px 0;display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:20px;}}
.badge{{font-family:'IBM Plex Mono',monospace;font-size:0.56rem;letter-spacing:2.5px;text-transform:uppercase;padding:4px 10px;border-radius:100px;font-weight:500;}}
.card-chat .badge{{background:rgba(0,157,255,0.12);color:#009dff;border:1px solid rgba(0,157,255,0.22);}}
.card-terminal .badge{{background:rgba(245,194,66,0.1);color:#F5C242;border:1px solid rgba(245,194,66,0.2);}}
.icon-wrap{{width:56px;height:56px;border-radius:16px;display:flex;align-items:center;justify-content:center;}}
.card-chat .icon-wrap{{background:rgba(0,157,255,0.1);border:1px solid rgba(0,157,255,0.22);}}
.card-terminal .icon-wrap{{background:rgba(245,194,66,0.08);border:1px solid rgba(245,194,66,0.18);}}
.icon-wrap svg{{width:26px;height:26px;}}
.card-body{{padding:0 28px 28px;}}
.card-name{{font-size:1.4rem;font-weight:800;color:#fff;letter-spacing:-0.3px;margin-bottom:5px;}}
.card-tagline{{font-size:0.66rem;letter-spacing:3px;text-transform:uppercase;font-family:'IBM Plex Mono',monospace;margin-bottom:14px;font-weight:400;}}
.card-chat .card-tagline{{color:rgba(0,157,255,0.65);}}
.card-terminal .card-tagline{{color:rgba(245,194,66,0.65);}}
.card-desc{{font-size:0.83rem;color:var(--muted);line-height:1.75;margin-bottom:22px;font-weight:400;}}
.features{{list-style:none;margin:0 0 26px;padding:0;}}
.features li{{font-size:0.78rem;color:rgba(232,236,244,0.55);padding:7px 0;border-bottom:1px solid rgba(255,255,255,0.045);display:flex;align-items:center;gap:10px;font-weight:400;}}
.features li:last-child{{border-bottom:none;}}
.feat-dot{{width:5px;height:5px;border-radius:50%;flex-shrink:0;}}
.card-chat .feat-dot{{background:#009dff;box-shadow:0 0 6px rgba(0,157,255,0.7);}}
.card-terminal .feat-dot{{background:#F5C242;box-shadow:0 0 6px rgba(245,194,66,0.6);}}
.cta{{width:100%;padding:14px;border-radius:14px;border:none;font-size:0.82rem;font-weight:700;letter-spacing:1.5px;cursor:pointer;transition:opacity 0.2s,transform 0.15s;text-transform:uppercase;font-family:'Syne',sans-serif;display:flex;align-items:center;justify-content:center;gap:8px;}}
.card-chat .cta{{background:linear-gradient(135deg,#009dff,#0048ff);color:#fff;box-shadow:0 8px 30px rgba(0,80,255,0.3);}}
.card-terminal .cta{{background:linear-gradient(135deg,#F5C242,#e0a820);color:#0a0e18;box-shadow:0 8px 30px rgba(245,194,66,0.25);}}
.cta:hover{{opacity:0.9;transform:translateY(-1px);}}
.cta svg{{width:14px;height:14px;transition:transform 0.2s;}}
.cta:hover svg{{transform:translateX(3px);}}
/* terminal preview */
.term-preview{{background:rgba(0,0,0,0.5);border:1px solid rgba(245,194,66,0.12);border-radius:12px;padding:12px 14px;margin-bottom:18px;font-family:'IBM Plex Mono',monospace;font-size:0.65rem;line-height:1.85;overflow:hidden;position:relative;}}
.term-preview::after{{content:'';position:absolute;inset:0;background:linear-gradient(180deg,transparent 55%,rgba(0,0,0,0.65) 100%);pointer-events:none;}}
.tl{{display:flex;gap:8px;align-items:center;}}
.tp{{color:rgba(245,194,66,0.6);}}
.tc{{color:rgba(255,255,255,0.38);}}
.tv-up{{color:#4ade80;}}
.tv-dn{{color:#f87171;}}
.tlb{{color:rgba(255,255,255,0.28);min-width:38px;}}
.tcursor{{display:inline-block;width:6px;height:10px;background:rgba(245,194,66,0.8);animation:cblink 1.1s step-end infinite;vertical-align:middle;margin-left:2px;}}
@keyframes cblink{{0%,100%{{opacity:1}}50%{{opacity:0}}}}
/* data pills */
.pills{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:18px;}}
.pill{{font-family:'IBM Plex Mono',monospace;font-size:0.6rem;padding:4px 10px;border-radius:6px;border:1px solid;letter-spacing:0.5px;}}
.pu{{color:#4ade80;border-color:rgba(74,222,128,0.2);background:rgba(74,222,128,0.06);}}
.pd{{color:#f87171;border-color:rgba(248,113,113,0.2);background:rgba(248,113,113,0.06);}}
.pn{{color:rgba(245,194,66,0.8);border-color:rgba(245,194,66,0.15);background:rgba(245,194,66,0.04);}}
/* corner decorations */
.ctlc,.cbrc{{position:absolute;width:16px;height:16px;pointer-events:none;opacity:0.3;}}
.ctlc{{top:12px;left:12px;border-top:1px solid;border-left:1px solid;border-radius:2px 0 0 0;}}
.cbrc{{bottom:12px;right:12px;border-bottom:1px solid;border-right:1px solid;border-radius:0 0 2px 0;}}
.card-chat .ctlc,.card-chat .cbrc{{border-color:#009dff;}}
.card-terminal .ctlc,.card-terminal .cbrc{{border-color:#F5C242;}}
.footer{{margin-top:48px;text-align:center;font-family:'IBM Plex Mono',monospace;font-size:0.62rem;color:rgba(255,255,255,0.15);letter-spacing:1.5px;position:relative;z-index:2;animation:fadeUp 0.6s 0.5s ease both;}}
.footer span{{color:rgba(245,194,66,0.25);}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(18px);}}to{{opacity:1;transform:translateY(0);}}}}
@media(max-width:768px){{
  .wrapper{{padding:32px 16px 48px;justify-content:flex-start;}}
  .header{{margin-bottom:28px;}}
  .title{{font-size:1.85rem;}}
  .cards{{flex-direction:column;align-items:center;gap:16px;}}
  .card{{min-width:unset;max-width:100%;width:100%;}}
  .card-head{{padding:22px 22px 0;}}
  .card-body{{padding:0 22px 22px;}}
}}
</style>
</head>
<body>
<div class="bg-layer"></div>
<div class="grid-bg"></div>
<div class="scanlines"></div>
<div class="wrapper">
  <div class="header">
    <div class="sys-badge">System Access — Authenticated</div>
    <div class="welcome">Welcome back, {_name}</div>
    <h1 class="title">Choose Your <span>System</span></h1>
    <p class="subtitle">// select platform &gt; initialize session</p>
    <div class="divider"></div>
  </div>

  <div class="cards">
    <!-- CHAT CARD -->
    <div class="card card-chat" id="card-chat" onclick="selectChat()">
      <div class="glow"></div>
      <div class="ctlc"></div><div class="cbrc"></div>
      <div class="card-head">
        <div class="icon-wrap">
          <svg viewBox="0 0 24 24" fill="none" stroke="#009dff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" width="26" height="26">
            <path d="M12 2C6.48 2 2 6.48 2 12c0 1.74.45 3.37 1.23 4.79L2 22l5.21-1.23A9.94 9.94 0 0012 22c5.52 0 10-4.48 10-10S17.52 2 12 2z"/>
            <path d="M8 10h8M8 14h5" stroke="#009dff" stroke-width="1.5"/>
          </svg>
        </div>
        <span class="badge">● Live</span>
      </div>
      <div class="card-body">
        <div class="card-name">SIGMA AI Chat</div>
        <div class="card-tagline">AI Trading Assistant</div>
        <p class="card-desc">Asisten analisa pasar berbasis AI — teknikal, fundamental, bandarmologi, dan makro dalam satu percakapan.</p>
        <ul class="features">
          <li><span class="feat-dot"></span>Analisa teknikal MnM Strategy+</li>
          <li><span class="feat-dot"></span>Bandarmologi & broker summary IDX</li>
          <li><span class="feat-dot"></span>Fundamental multi-source real-time</li>
          <li><span class="feat-dot"></span>Dampak makro global → emiten IDX</li>
          <li><span class="feat-dot"></span>Upload chart & PDF prospektus</li>
        </ul>
        <button class="cta" onclick="event.stopPropagation();selectChat()">
          Masuk ke AI Chat
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M3 8h10M9 4l4 4-4 4"/></svg>
        </button>
      </div>
    </div>

    <!-- TERMINAL CARD -->
    <div class="card card-terminal" id="card-terminal" onclick="selectTerminal()">
      <div class="glow"></div>
      <div class="ctlc"></div><div class="cbrc"></div>
      <div class="card-head">
        <div class="icon-wrap">
          <svg viewBox="0 0 24 24" fill="none" stroke="#F5C242" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" width="26" height="26">
            <rect x="2" y="3" width="20" height="14" rx="2"/>
            <path d="M7 8l3 3-3 3M13 14h4"/>
          </svg>
        </div>
        <span class="badge">◈ Beta</span>
      </div>
      <div class="card-body">
        <div class="card-name">SIGMA Terminal</div>
        <div class="card-tagline">Market Dashboard</div>
        <div class="term-preview">
          <div class="tl"><span class="tp">$</span><span class="tc">sigma.fetch --market IDX --live</span></div>
          <div class="tl"><span class="tlb">IHSG</span><span class="tv-up">▲ 7,421.88 &nbsp;+0.74%</span></div>
          <div class="tl"><span class="tlb">LQ45</span><span class="tv-dn">▼ 862.34 &nbsp;-0.31%</span></div>
          <div class="tl"><span class="tlb">IDX30</span><span class="tv-up">▲ 487.12 &nbsp;+0.52%</span></div>
          <div class="tl"><span class="tp">_</span><span class="tcursor"></span></div>
        </div>
        <div class="pills">
          <span class="pill pu">BBRI ▲1.4%</span>
          <span class="pill pd">TLKM ▼0.8%</span>
          <span class="pill pu">ADRO ▲2.1%</span>
          <span class="pill pn">VOL 12.4B</span>
          <span class="pill pu">ANTM ▲0.9%</span>
        </div>
        <ul class="features">
          <li><span class="feat-dot"></span>Market Overview — IHSG & indeks sektoral</li>
          <li><span class="feat-dot"></span>Broker Summary real-time IDX</li>
          <li><span class="feat-dot"></span>Stock Screener filter custom</li>
          <li><span class="feat-dot"></span>Watchlist personal dengan alert</li>
          <li><span class="feat-dot"></span>Data langsung dari BEI</li>
        </ul>
        <button class="cta" onclick="event.stopPropagation();selectTerminal()">
          Masuk ke Terminal
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M3 8h10M9 4l4 4-4 4"/></svg>
        </button>
      </div>
    </div>
  </div>

  <div class="footer">SIGMA <span>·</span> by MarketnMocha(MnM) × KIPM Universitas Pancasila</div>
</div>

<script>
var TERMINAL_URL = "{_terminal_url}";
function selectChat() {{
    try {{
        var pd = window.parent.document;
        var btns = pd.querySelectorAll('[data-testid="stButton"] button');
        for (var i = 0; i < btns.length; i++) {{
            var txt = (btns[i].innerText || btns[i].textContent || "").toLowerCase();
            if (txt.includes('chat')) {{ btns[i].click(); return; }}
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
    if (TERMINAL_URL && TERMINAL_URL.length > 4) {{ window.parent.location.href = TERMINAL_URL; return; }}
    try {{
        var pd = window.parent.document;
        var btns = pd.querySelectorAll('[data-testid="stButton"] button');
        for (var i = 0; i < btns.length; i++) {{
            var txt = (btns[i].innerText || btns[i].textContent || "").toLowerCase();
            if (txt.includes('terminal')) {{ btns[i].click(); return; }}
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
</body></html>
""", height=900, scrolling=False)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("__chat__", key="btn_sys_chat", use_container_width=True):
            st.session_state.current_view = "chat"
            st.session_state.selected_system = "chat"
            st.rerun()
    with col2:
        if st.button("__terminal__", key="btn_sys_terminal", use_container_width=True):
            st.session_state.current_view = "terminal"
            st.session_state.selected_system = "terminal"
            st.rerun()
