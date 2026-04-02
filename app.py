def show_system_selector():
    """Halaman pemilihan sistem — v2 fixed: no external fonts, no position:fixed (Streamlit Cloud safe)."""
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

    components.html(f"""<!DOCTYPE html><html><head>
<meta charset="utf-8">
<style>
/* ── SAFE FONT STACK — no external CDN ── */
:root{{
  --ff-display: 'SF Pro Display',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
  --ff-mono: 'SF Mono','Fira Code','Cascadia Code','Consolas','Courier New',monospace;
  --blue:#009dff;
  --gold:#F5C242;
  --gold2:#e0a820;
  --bg:#060a12;
  --card:#0a0f1c;
  --bdr:rgba(255,255,255,0.07);
  --text:#e8ecf4;
  --muted:rgba(232,236,244,0.40);
}}
*{{box-sizing:border-box;margin:0;padding:0;}}
html,body{{
  background:var(--bg);
  font-family:var(--ff-display);
  color:var(--text);
  min-height:100vh;
  overflow-x:hidden;
}}

/* ── BACKGROUND — pakai absolute bukan fixed ── */
.bg-wrap{{
  position:relative;
  min-height:100vh;
  background:
    radial-gradient(ellipse 90% 55% at 10% 5%, rgba(0,80,200,0.13) 0%, transparent 60%),
    radial-gradient(ellipse 70% 50% at 90% 95%, rgba(245,194,66,0.08) 0%, transparent 55%),
    #060a12;
  overflow:hidden;
}}
.grid-layer{{
  position:absolute;inset:0;pointer-events:none;
  background-image:
    linear-gradient(rgba(0,157,255,0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,157,255,0.045) 1px, transparent 1px);
  background-size:72px 72px;
  animation:gp 10s ease-in-out infinite;
}}
.scan-layer{{
  position:absolute;inset:0;pointer-events:none;
  background:repeating-linear-gradient(
    0deg,transparent,transparent 2px,
    rgba(0,157,255,0.015) 2px,rgba(0,157,255,0.015) 4px
  );
}}
@keyframes gp{{0%,100%{{opacity:0.5}}50%{{opacity:1}}}}

/* ── MAIN WRAPPER ── */
.wrap{{
  position:relative;z-index:2;
  min-height:100vh;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:56px 24px 48px;
}}

/* ── HEADER ── */
.hdr{{text-align:center;margin-bottom:48px;}}

.sbadge{{
  display:inline-flex;align-items:center;gap:8px;
  font-family:var(--ff-mono);
  font-size:0.62rem;letter-spacing:3px;color:rgba(0,157,255,0.7);
  text-transform:uppercase;
  border:1px solid rgba(0,157,255,0.2);
  border-radius:100px;padding:5px 16px;
  background:rgba(0,157,255,0.06);
  margin-bottom:18px;
  animation:fu 0.5s ease both;
}}
.dot-live{{
  width:6px;height:6px;border-radius:50%;
  background:var(--blue);box-shadow:0 0 7px var(--blue);
  animation:blk 2s ease-in-out infinite;
  flex-shrink:0;
}}
@keyframes blk{{0%,100%{{opacity:1}}50%{{opacity:0.15}}}}

.welc{{
  font-size:0.68rem;letter-spacing:4px;color:rgba(0,157,255,0.5);
  text-transform:uppercase;font-family:var(--ff-mono);
  margin-bottom:10px;animation:fu 0.5s 0.08s ease both;
}}
.ttl{{
  font-size:clamp(1.9rem,4vw,3rem);font-weight:700;
  color:#fff;letter-spacing:-0.5px;line-height:1.05;
  margin-bottom:8px;animation:fu 0.5s 0.13s ease both;
}}
.ttl em{{color:var(--gold);font-style:normal;}}
.sub{{
  font-size:0.78rem;color:var(--muted);
  font-family:var(--ff-mono);letter-spacing:0.3px;
  animation:fu 0.5s 0.18s ease both;
}}
.divl{{
  width:70px;height:1px;
  background:linear-gradient(90deg,transparent,rgba(0,157,255,0.55),transparent);
  margin:16px auto 0;
  animation:shr 3s ease-in-out infinite;
}}
@keyframes shr{{0%,100%{{width:36px;opacity:0.4}}50%{{width:90px;opacity:1}}}}
@keyframes fu{{from{{opacity:0;transform:translateY(16px)}}to{{opacity:1;transform:translateY(0)}}}}

/* ── CARDS ── */
.cards{{
  display:flex;gap:22px;flex-wrap:wrap;
  justify-content:center;
  max-width:880px;width:100%;
}}

.card{{
  flex:1;min-width:300px;max-width:410px;
  background:var(--card);
  border:1px solid var(--bdr);
  border-radius:22px;padding:0;
  position:relative;overflow:hidden;cursor:pointer;
  transition:transform 0.32s cubic-bezier(0.34,1.46,0.64,1),
              box-shadow 0.32s ease,border-color 0.28s ease;
  animation:fu 0.5s 0.28s ease both;
}}
.card:nth-child(2){{animation-delay:0.36s}}

/* top accent line */
.card::before{{
  content:'';position:absolute;top:0;left:0;right:0;height:1px;
}}
.cc::before{{background:linear-gradient(90deg,transparent 8%,#009dff 50%,transparent 92%);}}
.ct::before{{background:linear-gradient(90deg,transparent 8%,#F5C242 50%,transparent 92%);}}

/* inner glow blob */
.glw{{
  position:absolute;width:260px;height:260px;border-radius:50%;
  top:-70px;right:-50px;pointer-events:none;
  opacity:0;transition:opacity 0.45s ease;
}}
.cc .glw{{background:radial-gradient(circle,rgba(0,157,255,0.22) 0%,transparent 70%);}}
.ct .glw{{background:radial-gradient(circle,rgba(245,194,66,0.18) 0%,transparent 70%);}}
.card:hover .glw{{opacity:1;}}
.card:hover{{transform:translateY(-7px) scale(1.012);}}
.cc:hover{{border-color:rgba(0,157,255,0.42);box-shadow:0 22px 65px rgba(0,60,255,0.16),0 0 0 1px rgba(0,157,255,0.22);}}
.ct:hover{{border-color:rgba(245,194,66,0.42);box-shadow:0 22px 65px rgba(245,194,66,0.12),0 0 0 1px rgba(245,194,66,0.22);}}

/* corner brackets */
.cbrk{{position:absolute;width:14px;height:14px;pointer-events:none;}}
.cbrk-tl{{top:11px;left:11px;border-top:1px solid;border-left:1px solid;border-radius:2px 0 0 0;opacity:0.28;}}
.cbrk-br{{bottom:11px;right:11px;border-bottom:1px solid;border-right:1px solid;border-radius:0 0 2px 0;opacity:0.28;}}
.cc .cbrk{{border-color:#009dff;}}
.ct .cbrk{{border-color:#F5C242;}}

/* card head */
.ched{{padding:26px 26px 0;display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:18px;}}
.icw{{width:52px;height:52px;border-radius:14px;display:flex;align-items:center;justify-content:center;}}
.cc .icw{{background:rgba(0,157,255,0.1);border:1px solid rgba(0,157,255,0.22);}}
.ct .icw{{background:rgba(245,194,66,0.08);border:1px solid rgba(245,194,66,0.18);}}
.bge{{
  font-family:var(--ff-mono);font-size:0.54rem;letter-spacing:2.5px;
  text-transform:uppercase;padding:4px 10px;border-radius:100px;font-weight:500;
}}
.cc .bge{{background:rgba(0,157,255,0.1);color:#009dff;border:1px solid rgba(0,157,255,0.2);}}
.ct .bge{{background:rgba(245,194,66,0.09);color:#F5C242;border:1px solid rgba(245,194,66,0.18);}}

/* card body */
.cbdy{{padding:0 26px 26px;}}
.cname{{font-size:1.35rem;font-weight:700;color:#fff;letter-spacing:-0.3px;margin-bottom:4px;}}
.ctag{{
  font-size:0.63rem;letter-spacing:3px;text-transform:uppercase;
  font-family:var(--ff-mono);margin-bottom:13px;font-weight:400;
}}
.cc .ctag{{color:rgba(0,157,255,0.6);}}
.ct .ctag{{color:rgba(245,194,66,0.6);}}
.cdesc{{font-size:0.81rem;color:var(--muted);line-height:1.75;margin-bottom:20px;}}

/* features */
.feats{{list-style:none;margin:0 0 24px;padding:0;}}
.feats li{{
  font-size:0.76rem;color:rgba(232,236,244,0.5);
  padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.04);
  display:flex;align-items:center;gap:9px;
}}
.feats li:last-child{{border-bottom:none;}}
.fdot{{width:5px;height:5px;border-radius:50%;flex-shrink:0;}}
.cc .fdot{{background:#009dff;box-shadow:0 0 5px rgba(0,157,255,0.65);}}
.ct .fdot{{background:#F5C242;box-shadow:0 0 5px rgba(245,194,66,0.6);}}

/* CTA */
.cta{{
  width:100%;padding:13px 16px;border-radius:13px;border:none;
  font-size:0.8rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;
  cursor:pointer;font-family:var(--ff-display);
  display:flex;align-items:center;justify-content:center;gap:8px;
  transition:opacity 0.18s,transform 0.15s;
}}
.cc .cta{{background:linear-gradient(135deg,#009dff,#0048ff);color:#fff;box-shadow:0 7px 26px rgba(0,72,255,0.28);}}
.ct .cta{{background:linear-gradient(135deg,#F5C242,#e0a820);color:#07090f;box-shadow:0 7px 26px rgba(245,194,66,0.24);}}
.cta:hover{{opacity:0.9;transform:translateY(-1px);}}
.cta svg{{transition:transform 0.18s;}}
.cta:hover svg{{transform:translateX(3px);}}

/* ── TERMINAL EXTRAS ── */
.tprev{{
  background:rgba(0,0,0,0.55);
  border:1px solid rgba(245,194,66,0.13);
  border-radius:11px;
  padding:11px 13px;
  margin-bottom:16px;
  font-family:var(--ff-mono);
  font-size:0.63rem;
  line-height:1.9;
  position:relative;
  overflow:hidden;
}}
.tprev::after{{
  content:'';position:absolute;bottom:0;left:0;right:0;height:40%;
  background:linear-gradient(transparent,rgba(0,0,0,0.7));
  pointer-events:none;
}}
.trow{{display:flex;gap:10px;}}
.tpmt{{color:rgba(245,194,66,0.55);}}
.tcmd{{color:rgba(255,255,255,0.35);}}
.tlbl{{color:rgba(255,255,255,0.28);min-width:40px;display:inline-block;}}
.tup{{color:#4ade80;}}
.tdn{{color:#f87171;}}
.tcsr{{
  display:inline-block;width:6px;height:11px;
  background:rgba(245,194,66,0.85);vertical-align:middle;margin-left:2px;
  animation:cblk 1.1s step-end infinite;
}}
@keyframes cblk{{0%,100%{{opacity:1}}50%{{opacity:0}}}}

/* pills */
.pills{{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:16px;}}
.pl{{
  font-family:var(--ff-mono);font-size:0.58rem;
  padding:3px 9px;border-radius:5px;border:1px solid;letter-spacing:0.5px;
}}
.pu{{color:#4ade80;border-color:rgba(74,222,128,0.22);background:rgba(74,222,128,0.07);}}
.pd{{color:#f87171;border-color:rgba(248,113,113,0.22);background:rgba(248,113,113,0.07);}}
.pn{{color:rgba(245,194,66,0.85);border-color:rgba(245,194,66,0.18);background:rgba(245,194,66,0.05);}}

/* footer */
.ftr{{
  margin-top:44px;text-align:center;
  font-family:var(--ff-mono);font-size:0.6rem;
  color:rgba(255,255,255,0.14);letter-spacing:1.5px;
  position:relative;z-index:2;
  animation:fu 0.5s 0.5s ease both;
}}
.ftr em{{color:rgba(245,194,66,0.22);font-style:normal;}}

@media(max-width:768px){{
  .wrap{{padding:28px 14px 44px;justify-content:flex-start;}}
  .hdr{{margin-bottom:24px;}}
  .ttl{{font-size:1.75rem;}}
  .cards{{flex-direction:column;align-items:center;gap:14px;}}
  .card{{min-width:unset;max-width:100%;width:100%;}}
  .ched{{padding:20px 20px 0;}}
  .cbdy{{padding:0 20px 20px;}}
}}
</style></head><body>
<div class="bg-wrap">
  <div class="grid-layer"></div>
  <div class="scan-layer"></div>

  <div class="wrap">
    <div class="hdr">
      <div class="sbadge"><span class="dot-live"></span>System Access — Authenticated</div>
      <div class="welc">Welcome back, {_name}</div>
      <h1 class="ttl">Choose Your <em>System</em></h1>
      <p class="sub">// select platform &gt; initialize session</p>
      <div class="divl"></div>
    </div>

    <div class="cards">

      <!-- CHAT CARD -->
      <div class="card cc" id="card-chat" onclick="selectChat()">
        <div class="glw"></div>
        <div class="cbrk cbrk-tl"></div>
        <div class="cbrk cbrk-br"></div>
        <div class="ched">
          <div class="icw">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#009dff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
              <line x1="9" y1="10" x2="15" y2="10"/><line x1="9" y1="14" x2="13" y2="14"/>
            </svg>
          </div>
          <span class="bge">&#9679; Live</span>
        </div>
        <div class="cbdy">
          <div class="cname">SIGMA AI Chat</div>
          <div class="ctag">AI Trading Assistant</div>
          <p class="cdesc">Asisten analisa pasar berbasis AI — teknikal, fundamental, bandarmologi, dan makro dalam satu percakapan.</p>
          <ul class="feats">
            <li><span class="fdot"></span>Analisa teknikal MnM Strategy+</li>
            <li><span class="fdot"></span>Bandarmologi &amp; broker summary IDX</li>
            <li><span class="fdot"></span>Fundamental multi-source real-time</li>
            <li><span class="fdot"></span>Dampak makro global &rarr; emiten IDX</li>
            <li><span class="fdot"></span>Upload chart &amp; PDF prospektus</li>
          </ul>
          <button class="cta" onclick="event.stopPropagation();selectChat()">
            Masuk ke AI Chat
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 8h10M9 4l4 4-4 4"/></svg>
          </button>
        </div>
      </div>

      <!-- TERMINAL CARD -->
      <div class="card ct" id="card-terminal" onclick="selectTerminal()">
        <div class="glw"></div>
        <div class="cbrk cbrk-tl"></div>
        <div class="cbrk cbrk-br"></div>
        <div class="ched">
          <div class="icw">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#F5C242" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <rect x="2" y="3" width="20" height="14" rx="2"/>
              <polyline points="8 21 12 17 16 21"/>
              <line x1="12" y1="17" x2="12" y2="21"/>
              <polyline points="6 8 10 12 6 16" stroke="#F5C242" stroke-width="1.5"/>
              <line x1="13" y1="15" x2="18" y2="15" stroke="#F5C242" stroke-width="1.5"/>
            </svg>
          </div>
          <span class="bge">&#9670; Beta</span>
        </div>
        <div class="cbdy">
          <div class="cname">SIGMA Terminal</div>
          <div class="ctag">Market Dashboard</div>

          <!-- mini terminal preview -->
          <div class="tprev">
            <div class="trow"><span class="tpmt">$</span><span class="tcmd"> sigma.fetch --market IDX --live</span></div>
            <div class="trow"><span class="tlbl">IHSG </span><span class="tup">&#9650; 7,421.88 &nbsp;+0.74%</span></div>
            <div class="trow"><span class="tlbl">LQ45 </span><span class="tdn">&#9660; 862.34 &nbsp;&nbsp;-0.31%</span></div>
            <div class="trow"><span class="tlbl">IDX30</span><span class="tup">&#9650; 487.12 &nbsp;&nbsp;+0.52%</span></div>
            <div class="trow"><span class="tpmt">_</span><span class="tcsr"></span></div>
          </div>

          <!-- data pills -->
          <div class="pills">
            <span class="pl pu">BBRI &#9650;1.4%</span>
            <span class="pl pd">TLKM &#9660;0.8%</span>
            <span class="pl pu">ADRO &#9650;2.1%</span>
            <span class="pl pn">VOL 12.4B</span>
            <span class="pl pu">ANTM &#9650;0.9%</span>
          </div>

          <ul class="feats">
            <li><span class="fdot"></span>Market Overview — IHSG &amp; indeks sektoral</li>
            <li><span class="fdot"></span>Broker Summary real-time IDX</li>
            <li><span class="fdot"></span>Stock Screener filter custom</li>
            <li><span class="fdot"></span>Watchlist personal dengan alert</li>
            <li><span class="fdot"></span>Data langsung dari BEI</li>
          </ul>

          <button class="cta" onclick="event.stopPropagation();selectTerminal()">
            Masuk ke Terminal
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 8h10M9 4l4 4-4 4"/></svg>
          </button>
        </div>
      </div>

    </div><!-- /cards -->

    <div class="ftr">SIGMA <em>&middot;</em> by MarketnMocha(MnM) &times; KIPM Universitas Pancasila</div>
  </div><!-- /wrap -->
</div><!-- /bg-wrap -->

<script>
var TERMINAL_URL = "{_terminal_url}";
function selectChat(){{
  try{{
    var pd=window.parent.document;
    var btns=pd.querySelectorAll('[data-testid="stButton"] button');
    for(var i=0;i<btns.length;i++){{
      var t=(btns[i].innerText||btns[i].textContent||"").toLowerCase();
      if(t.includes('chat')){{btns[i].click();return;}}
    }}
  }}catch(e){{}}
  setTimeout(function(){{
    try{{var u=new URL(window.parent.location.href);u.searchParams.set('action','open_chat');window.parent.location.assign(u.toString());}}catch(e){{}}
  }},150);
}}
function selectTerminal(){{
  if(TERMINAL_URL&&TERMINAL_URL.length>4){{window.parent.location.href=TERMINAL_URL;return;}}
  try{{
    var pd=window.parent.document;
    var btns=pd.querySelectorAll('[data-testid="stButton"] button');
    for(var i=0;i<btns.length;i++){{
      var t=(btns[i].innerText||btns[i].textContent||"").toLowerCase();
      if(t.includes('terminal')){{btns[i].click();return;}}
    }}
  }}catch(e){{}}
  setTimeout(function(){{
    try{{var u=new URL(window.parent.location.href);u.searchParams.set('action','open_terminal');window.parent.location.assign(u.toString());}}catch(e){{}}
  }},150);
}}
</script>
</body></html>
""", height=920, scrolling=False)

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
