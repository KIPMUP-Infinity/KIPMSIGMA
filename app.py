import streamlit as st
from groq import Groq
import fitz
import base64
from PIL import Image
import io
import streamlit.components.v1 as components
import uuid
from datetime import datetime
import requests
from urllib.parse import urlencode
import json
import os
import hashlib
import bcrypt
import re


# ─── GEMINI API — fallback saat Groq limit ───
def _call_gemini(messages, api_key="AIzaSyApoyO1dTWFPJ7Z5fykbLTxM0GN3MsYV8o"):
    """Call Gemini 2.5 Flash via REST API."""
    try:
        import urllib.request, json as _j
        api_key = api_key or st.secrets.get("GEMINI_KEY", "AIzaSyApoyO1dTWFPJ7Z5fykbLTxM0GN3MsYV8o")
        
        # Convert messages ke format Gemini
        gemini_contents = []
        system_text = ""
        for m in messages:
            role = m.get("role","")
            text = m.get("content","") or ""
            if role == "system":
                system_text = text
            elif role == "user":
                gemini_contents.append({"role":"user","parts":[{"text":text}]})
            elif role == "assistant":
                gemini_contents.append({"role":"model","parts":[{"text":text}]})
        
        # Gemini butuh minimal 1 message
        if not gemini_contents:
            gemini_contents = [{"role":"user","parts":[{"text":"Halo"}]}]
        payload = {"contents": gemini_contents}
        if system_text:
            payload["system_instruction"] = {"parts":[{"text":system_text}]}
        payload["generationConfig"] = {
            "temperature": 0.7,
            "maxOutputTokens": 2048,
        }
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
        req = urllib.request.Request(
            url,
            data=_j.dumps(payload).encode(),
            headers={"Content-Type":"application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = _j.loads(r.read())
        
        # Extract text dari response
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content",{}).get("parts",[])
            if parts:
                return parts[0].get("text","")
        return None
    except Exception as e:
        # Log error Gemini ke session state untuk debugging
        try:
            import streamlit as _st
            _st.session_state["last_error"] = f"Gemini error: {str(e)}"
        except: pass
        return None


# ─── MULTI-SOURCE DATA (yfinance → stooq → IDX API) ───
def _fetch_all_data(tickers):
    import threading
    result = {"prices": {}, "news": []}

    def fetch():
        # Layer 1: yfinance
        try:
            import yfinance as yf
            for tk in tickers[:3]:
                try:
                    t = yf.Ticker(f"{tk}.JK")
                    h = t.history(period="2d")
                    if not h.empty:
                        info = t.info
                        last = h.iloc[-1]
                        prev = h.iloc[-2] if len(h)>1 else last
                        chg = ((last["Close"]-prev["Close"])/prev["Close"]*100) if prev["Close"] else 0
                        result["prices"][tk] = {
                            "price": round(last["Close"],0),
                            "chg": round(chg,2),
                            "pe": info.get("trailingPE"),
                            "pbv": info.get("priceToBook"),
                            "eps": info.get("trailingEps"),
                            "roe": info.get("returnOnEquity"),
                            "source": "yfinance"
                        }
                except: pass
        except: pass

        # Layer 2: stooq — backup jika yfinance gagal
        try:
            import pandas_datareader as pdr
            from datetime import timedelta
            for tk in tickers[:3]:
                if tk not in result["prices"]:
                    try:
                        df = pdr.get_data_stooq(
                            f"{tk}.JK",
                            start=datetime.now()-timedelta(days=7),
                            end=datetime.now()
                        )
                        if not df.empty:
                            df = df.sort_index()
                            last = df.iloc[-1]
                            prev = df.iloc[-2] if len(df)>1 else last
                            chg = ((last["Close"]-prev["Close"])/prev["Close"]*100) if prev["Close"] else 0
                            result["prices"][tk] = {
                                "price": round(last["Close"],0),
                                "chg": round(chg,2),
                                "source": "stooq"
                            }
                    except: pass
        except: pass

        # Layer 3: IDX API — backup terakhir
        for tk in tickers[:3]:
            if tk not in result["prices"]:
                try:
                    import urllib.request, json as _j
                    req = urllib.request.Request(
                        f"https://www.idx.co.id/umbraco/Surface/StockData/GetTradingInfoSS?code={tk}",
                        headers={"User-Agent":"Mozilla/5.0","Referer":"https://www.idx.co.id/"}
                    )
                    with urllib.request.urlopen(req, timeout=3) as r:
                        d = _j.loads(r.read())
                    if d and d.get("LastPrice"):
                        result["prices"][tk] = {
                            "price": d["LastPrice"],
                            "chg": d.get("ChangePercentage", 0),
                            "source": "IDX"
                        }
                except: pass

        # Berita: Google News + CNBC ID + Kontan + Bisnis
        try:
            import feedparser
            seen = set()
            q = tickers[0] if tickers else "ihsg"
            sources = [
                ("Google", f"https://news.google.com/rss/search?q={requests.utils.quote(q+' saham IDX')}&hl=id&gl=ID&ceid=ID:id"),
                ("CNBC ID", "https://www.cnbcindonesia.com/rss"),
                ("Kontan", "https://rss.kontan.co.id/category/investasi"),
                ("Bisnis", "https://ekonomi.bisnis.com/rss"),
            ]
            mkt_kw = [q.lower(),"ihsg","saham","bursa","ekonomi","rupiah","pasar",
                      "inflasi","perang","global","emiten","investor"]
            for sn, su in sources:
                try:
                    feed = feedparser.parse(su)
                    cnt = 0
                    for e in feed.entries:
                        if cnt >= 2: break
                        title = e.title.strip()
                        key = title[:30].lower()
                        if key not in seen and (sn=="Google" or any(k in title.lower() for k in mkt_kw)):
                            seen.add(key)
                            result["news"].append(f"[{sn}] {title}")
                            cnt += 1
                except: pass
        except: pass

    th = threading.Thread(target=fetch, daemon=True)
    th.start()
    th.join(timeout=10)
    return result

def _fetch_finnhub(ticker, api_key=None):
    api_key = api_key or st.secrets.get("FINNHUB_KEY", "d705ab9r01qtb4r9hgpgd705ab9r01qtb4r9hgq0")
    """Fetch fundamental data dari Finnhub."""
    try:
        import urllib.request, json as _j
        # Basic financials
        url = f"https://finnhub.io/api/v1/stock/metric?symbol={ticker}.JK&metric=all&token={api_key}"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = _j.loads(r.read())
        metrics = data.get("metric", {})
        result = {}
        # Mapping key Finnhub ke nama yang kita pakai
        mapping = {
            "revenueGrowthTTMYoy": "revenue_growth",
            "roeTTM": "roe",
            "roaTTM": "roa",
            "netProfitMarginTTM": "net_margin",
            "peBasicExclExtraTTM": "pe",
            "pbAnnual": "pbv",
            "dividendYieldIndicatedAnnual": "div_yield",
            "epsBasicExclExtraItemsTTM": "eps",
            "totalDebt/totalEquityAnnual": "der",
            "currentRatioAnnual": "current_ratio",
            "52WeekHigh": "w52h",
            "52WeekLow": "w52l",
        }
        for fh_key, our_key in mapping.items():
            if metrics.get(fh_key) is not None:
                result[our_key] = metrics[fh_key]
        return result
    except:
        return {}

def _fetch_alphavantage(ticker, api_key=None):
    api_key = api_key or st.secrets.get("ALPHAVANTAGE_KEY", "GYZKT8YU8RV3QX65")
    """Fetch fundamental data dari Alpha Vantage."""
    try:
        import urllib.request, json as _j
        result = {}
        # Overview (fundamental)
        url = f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={ticker}.JKT&apikey={api_key}"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = _j.loads(r.read())
        if data and "Symbol" in data:
            if data.get("PERatio") and data["PERatio"] != "None":
                result["pe"] = float(data["PERatio"])
            if data.get("PriceToBookRatio") and data["PriceToBookRatio"] != "None":
                result["pbv"] = float(data["PriceToBookRatio"])
            if data.get("EPS") and data["EPS"] != "None":
                result["eps"] = float(data["EPS"])
            if data.get("ReturnOnEquityTTM") and data["ReturnOnEquityTTM"] != "None":
                result["roe"] = float(data["ReturnOnEquityTTM"])
            if data.get("ReturnOnAssetsTTM") and data["ReturnOnAssetsTTM"] != "None":
                result["roa"] = float(data["ReturnOnAssetsTTM"])
            if data.get("DividendYield") and data["DividendYield"] != "None":
                result["div_yield"] = float(data["DividendYield"])
            if data.get("MarketCapitalization") and data["MarketCapitalization"] != "None":
                result["mktcap"] = float(data["MarketCapitalization"])
            if data.get("52WeekHigh") and data["52WeekHigh"] != "None":
                result["w52h"] = float(data["52WeekHigh"])
            if data.get("52WeekLow") and data["52WeekLow"] != "None":
                result["w52l"] = float(data["52WeekLow"])
            if data.get("Description"):
                result["description"] = data["Description"][:200]
        return result
    except:
        return {}

def _fetch_fmp(ticker, api_key=None):
    api_key = api_key or st.secrets.get("FMP_KEY", "6ckg4EdDYUqKkkpPK4Weo4b9PbKD6IUK")
    """Fetch fundamental dari Financial Modeling Prep — 250 req/hari."""
    try:
        import urllib.request, json as _j
        result = {}
        base = "https://financialmodelingprep.com/api/v3"

        # Profile (harga, market cap, sektor, deskripsi)
        url = f"{base}/profile/{ticker}.JK?apikey={api_key}"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = _j.loads(r.read())
        if data and isinstance(data, list) and len(data) > 0:
            d = data[0]
            if d.get("price"): result["price"] = d["price"]
            if d.get("mktCap"): result["mktcap"] = d["mktCap"]
            if d.get("pe"): result["pe"] = d["pe"]
            if d.get("eps"): result["eps"] = d["eps"]
            if d.get("beta"): result["beta"] = d["beta"]
            if d.get("sector"): result["sector"] = d["sector"]
            if d.get("industry"): result["industry"] = d["industry"]
            if d.get("description"): result["description"] = d["description"][:300]

        # Key Metrics TTM (ROE, ROA, PBV, dll)
        url2 = f"{base}/key-metrics-ttm/{ticker}.JK?apikey={api_key}"
        req2 = urllib.request.Request(url2, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req2, timeout=5) as r2:
            data2 = _j.loads(r2.read())
        if data2 and isinstance(data2, list) and len(data2) > 0:
            m = data2[0]
            if m.get("roeTTM"): result["roe"] = m["roeTTM"]
            if m.get("roaTTM"): result["roa"] = m["roaTTM"]
            if m.get("pbRatioTTM"): result["pbv"] = m["pbRatioTTM"]
            if m.get("peRatioTTM"): result["pe"] = result.get("pe") or m["peRatioTTM"]
            if m.get("dividendYieldTTM"): result["div_yield"] = m["dividendYieldTTM"]
            if m.get("debtToEquityTTM"): result["der"] = m["debtToEquityTTM"]
            if m.get("currentRatioTTM"): result["current_ratio"] = m["currentRatioTTM"]
            if m.get("netProfitMarginTTM"): result["net_margin"] = m["netProfitMarginTTM"]
            if m.get("bookValuePerShareTTM"): result["bv"] = m["bookValuePerShareTTM"]
            if m.get("earningsYieldTTM"): result["earnings_yield"] = m["earningsYieldTTM"]
            if m.get("freeCashFlowPerShareTTM"): result["fcf_per_share"] = m["freeCashFlowPerShareTTM"]

        # Income Statement historis (3 tahun)
        url3 = f"{base}/income-statement/{ticker}.JK?limit=4&apikey={api_key}"
        req3 = urllib.request.Request(url3, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req3, timeout=5) as r3:
            data3 = _j.loads(r3.read())
        if data3 and isinstance(data3, list):
            hist_ni = []
            hist_eps = []
            hist_rev = []
            for row in data3[:4]:
                yr = str(row.get("date",""))[:4]
                ni = row.get("netIncome")
                eps = row.get("eps")
                rev = row.get("revenue")
                if ni: hist_ni.append((yr, ni))
                if eps: hist_eps.append((yr, eps))
                if rev: hist_rev.append((yr, rev))
            if hist_ni: result["hist_ni"] = hist_ni
            if hist_eps: result["hist_eps"] = hist_eps
            if hist_rev: result["hist_rev"] = hist_rev

        result["source"] = "FMP"
        return result
    except:
        return {}

def _fetch_multi_fundamental(ticker):
    """
    Fetch fundamental berlapis — saling melengkapi:
    Layer 1: yfinance (harga, PE, PBV, EPS, ROE, ROA)
    Layer 2: FMP (historis, DER, FCF, sektor, deskripsi)
    Layer 3: Finnhub (rasio tambahan)
    Layer 4: Alpha Vantage (backup)
    Layer 5: hitung manual dari rumus
    """
    import threading
    result = [{}]
    def fetch():
        combined = {}

        # ── Layer 1: yfinance ──
        try:
            import yfinance as yf
            t = yf.Ticker(f"{ticker}.JK")
            info = t.info
            hist = t.history(period="5d")
            if not hist.empty:
                combined["price"] = round(hist.iloc[-1]["Close"], 0)
            for k, v in {
                "pe": info.get("trailingPE"),
                "pbv": info.get("priceToBook"),
                "eps": info.get("trailingEps"),
                "bv": info.get("bookValue"),
                "roe": info.get("returnOnEquity"),
                "roa": info.get("returnOnAssets"),
                "div_yield": info.get("dividendYield"),
                "mktcap": info.get("marketCap"),
                "w52h": info.get("fiftyTwoWeekHigh"),
                "w52l": info.get("fiftyTwoWeekLow"),
                "shares": info.get("sharesOutstanding"),
            }.items():
                if v is not None:
                    combined[k] = v
            combined["source_price"] = "yfinance"
        except: pass

        # ── Layer 2: FMP (isi yang kosong + data historis) ──
        try:
            fmp = _fetch_fmp(ticker)
            for k, v in fmp.items():
                if k not in combined or combined[k] is None:
                    combined[k] = v
                elif k in ("hist_ni","hist_eps","hist_rev","sector","industry","description"):
                    combined[k] = v  # selalu ambil dari FMP untuk data ini
            if fmp:
                combined["source_fundamental"] = "FMP"
        except: pass

        # ── Layer 3: Finnhub (isi yang masih kosong) ──
        try:
            fh = _fetch_finnhub(ticker)
            for k, v in fh.items():
                if k not in combined or combined[k] is None:
                    combined[k] = v
        except: pass

        # ── Layer 4: Alpha Vantage (backup terakhir) ──
        try:
            av = _fetch_alphavantage(ticker)
            for k, v in av.items():
                if k not in combined or combined[k] is None:
                    combined[k] = v
        except: pass

        # ── Layer 5: Hitung manual dari rumus ──
        price = combined.get("price")
        eps   = combined.get("eps")
        bv    = combined.get("bv")
        if price and eps and eps > 0 and not combined.get("pe"):
            combined["pe"] = round(price / eps, 2)
            combined["source_pe"] = "hitung (Harga÷EPS)"
        if price and bv and bv > 0 and not combined.get("pbv"):
            combined["pbv"] = round(price / bv, 2)
            combined["source_pbv"] = "hitung (Harga÷BV)"

        result[0] = combined
    th = threading.Thread(target=fetch, daemon=True)
    th.start()
    th.join(timeout=18)
    return result[0]

# ─── KOMODITAS via FMP ───
def _fetch_commodities(api_key=None):
    """Fetch harga komoditas dari FMP — pakai key yang sudah ada."""
    try:
        import urllib.request, json as _j
        api_key = api_key or st.secrets.get("FMP_KEY", "6ckg4EdDYUqKkkpPK4Weo4b9PbKD6IUK")
        result = {}

        # Commodity list yang relevan untuk market Indonesia
        symbols = {
            "GCUSD": "Gold (Emas)",
            "SIUSD": "Silver (Perak)",
            "CLUSD": "WTI Crude Oil",
            "BZUSD": "Brent Crude Oil",
            "NGUSD": "Natural Gas",
            "HGUSD": "Copper (Tembaga)",
            "NZUSD": "Nickel",
            "ALUSD": "Aluminum (Aluminium)",
            "ZSUSD": "Soybeans (Kedelai)",
            "KCUSD": "Coffee (Kopi)",
        }

        # Batch quote
        syms = ",".join(symbols.keys())
        url = f"https://financialmodelingprep.com/api/v3/quote/{syms}?apikey={api_key}"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = _j.loads(r.read())

        if data and isinstance(data, list):
            for item in data:
                sym = item.get("symbol","")
                if sym in symbols:
                    result[symbols[sym]] = {
                        "price": item.get("price"),
                        "chg": item.get("changesPercentage"),
                        "symbol": sym
                    }
        return result
    except:
        return {}

def _fetch_us_china_stock(ticker, market="US"):
    """Fetch saham US atau China via yfinance + FMP."""
    try:
        import yfinance as yf, threading
        result = [{}]
        def fetch():
            try:
                # Format ticker: US biasa, HK tambah .HK, China .SS atau .SZ
                if market == "HK":
                    yf_ticker = f"{ticker}.HK"
                elif market == "CN_SH":
                    yf_ticker = f"{ticker}.SS"
                elif market == "CN_SZ":
                    yf_ticker = f"{ticker}.SZ"
                else:
                    yf_ticker = ticker  # US langsung

                t = yf.Ticker(yf_ticker)
                hist = t.history(period="2d")
                info = t.info
                if not hist.empty:
                    last = hist.iloc[-1]
                    prev = hist.iloc[-2] if len(hist) > 1 else last
                    chg = ((last["Close"]-prev["Close"])/prev["Close"]*100) if prev["Close"] else 0
                    result[0] = {
                        "price": round(last["Close"], 2),
                        "chg": round(chg, 2),
                        "pe": info.get("trailingPE"),
                        "pbv": info.get("priceToBook"),
                        "eps": info.get("trailingEps"),
                        "mktcap": info.get("marketCap"),
                        "name": info.get("longName",""),
                        "sector": info.get("sector",""),
                        "currency": info.get("currency","USD"),
                    }
            except: pass
        th = threading.Thread(target=fetch, daemon=True)
        th.start()
        th.join(timeout=8)
        return result[0]
    except:
        return {}

# ─── GLOBAL NEWS RSS ───
GLOBAL_NEWS_SOURCES = [
    ("Al Jazeera",  "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Reuters",     "https://feeds.reuters.com/reuters/businessNews"),
    ("BBC World",   "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("BBC Business","https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("CNBC Global", "https://www.cnbc.com/id/100727362/device/rss/rss.html"),
    ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
    ("WSJ Markets", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
]

def _fetch_global_news(keywords=None, max_per_source=2):
    """
    Fetch berita global dari semua sumber.
    keywords: list kata kunci filter (opsional)
    Return: list berita dengan label sumber
    """
    try:
        import feedparser, threading
        result = [[]]

        def fetch():
            news = []
            seen = set()
            kw = [k.lower() for k in keywords] if keywords else []

            for src_name, src_url in GLOBAL_NEWS_SOURCES:
                try:
                    feed = feedparser.parse(src_url)
                    count = 0
                    for entry in feed.entries:
                        if count >= max_per_source:
                            break
                        title = entry.get("title","").strip()
                        if not title:
                            continue
                        key = title[:30].lower()
                        if key in seen:
                            continue
                        # Filter keyword jika ada
                        if kw and not any(k in title.lower() for k in kw):
                            continue
                        seen.add(key)
                        news.append({
                            "source": src_name,
                            "title": title,
                            "link": entry.get("link",""),
                        })
                        count += 1
                except: pass
            result[0] = news

        th = threading.Thread(target=fetch, daemon=True)
        th.start()
        th.join(timeout=12)
        return result[0]
    except:
        return []

def build_global_context(prompt):
    """
    Build context lengkap untuk pertanyaan global:
    komoditas + saham US/China + berita internasional
    Semua berita asing → instruksi translate ke Bahasa Indonesia
    """
    import threading
    _p = prompt.lower()

    # Keyword untuk trigger global context
    global_kw = [
        "gold","emas","oil","minyak","crude","coal","batubara","nikel","nickel",
        "copper","tembaga","commodity","komoditas","silver","perak",
        "us stock","nasdaq","nyse","dow jones","s&p","sp500",
        "china stock","shanghai","hang seng","hkex","szse",
        "perang","war","geopolitik","geopolitical","fed","federal reserve",
        "inflation","inflasi","interest rate","suku bunga","dollar","usd",
        "al jazeera","reuters","bbc","global","international","world",
        "bitcoin","btc","crypto","ethereum","eth",
        "apple","tesla","nvidia","microsoft","google","amazon","meta",
        "baba","alibaba","tencent","xiaomi","pdd",
    ]

    if not any(k in _p for k in global_kw):
        return ""

    result = [{}]
    def fetch():
        lines = [f"=== DATA GLOBAL ({datetime.now().strftime('%d %b %Y %H:%M WIB')}) ==="]

        # 1. Komoditas
        try:
            commodities = _fetch_commodities()
            if commodities:
                lines.append("\n── KOMODITAS ──")
                for name, d in commodities.items():
                    if d.get("price"):
                        arah = "▲" if (d.get("chg") or 0) >= 0 else "▼"
                        chg = abs(d.get("chg") or 0)
                        lines.append(f"{name}: {d['price']:,.2f} {arah}{chg:.2f}%")
        except: pass

        # 2. Deteksi saham US/China dari prompt
        import re as _re
        us_tickers = _re.findall(r'([A-Z]{1,5})', prompt.upper())
        us_skip = {"THE","AND","FOR","IDX","BEI","USD","IDR","RSI","EMA","FVG","OB"}
        for tk in us_tickers[:3]:
            if tk not in us_skip and len(tk) >= 2:
                d = _fetch_us_china_stock(tk, "US")
                if d.get("price"):
                    arah = "▲" if d.get("chg",0) >= 0 else "▼"
                    line = f"\n{tk}"
                    if d.get("name"): line += f" ({d['name'][:30]})"
                    line += f": ${d['price']:,.2f} {arah}{abs(d['chg']):.2f}%"
                    if d.get("pe"): line += f" | PER:{d['pe']:.1f}x"
                    lines.append(line)

        # 3. Berita global — filter berdasarkan keyword dari prompt
        prompt_words = [w for w in _p.split() if len(w) > 3]
        news = _fetch_global_news(keywords=prompt_words[:5], max_per_source=2)
        if not news:
            # Fallback: ambil headline terbaru tanpa filter
            news = _fetch_global_news(max_per_source=1)
        if news:
            lines.append("\n── BERITA GLOBAL (terjemahkan ke Bahasa Indonesia) ──")
            for item in news[:8]:
                lines.append(f"[{item['source']}] {item['title']}")

        lines.append("\n⚠️ INSTRUKSI: Terjemahkan semua berita asing di atas ke Bahasa Indonesia")
        lines.append("Kaitkan data komoditas/saham global dengan dampaknya ke pasar Indonesia")
        lines.append("=== AKHIR DATA GLOBAL ===")
        result[0] = "\n".join(lines)

    th = threading.Thread(target=fetch, daemon=True)
    th.start()
    th.join(timeout=15)
    return result[0]


# ─── CACHE SISTEM — simpan data fundamental agar hemat API request ───
import hashlib as _hashlib

def _cache_key(ticker):
    return os.path.join(CACHE_DIR, f"{ticker.upper()}.json")

def _cache_get(ticker, max_days=85):
    """Ambil dari cache jika masih fresh (default 85 hari untuk data kuartal)."""
    try:
        path = _cache_key(ticker)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            cached = json.load(f)
        # Cek umur cache
        cached_at = cached.get("_cached_at", "")
        if not cached_at:
            return None
        from datetime import datetime as _dt
        age = (_dt.now() - _dt.fromisoformat(cached_at)).days
        if age > max_days:
            return None  # Cache expired
        return cached
    except:
        return None

def _cache_set(ticker, data):
    """Simpan data ke cache dengan timestamp."""
    try:
        path = _cache_key(ticker)
        data["_cached_at"] = datetime.now().isoformat()
        data["_ticker"] = ticker.upper()
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False, default=str)
    except:
        pass

def _cache_info(ticker):
    """Info cache — berapa hari lagi valid."""
    try:
        path = _cache_key(ticker)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            cached = json.load(f)
        from datetime import datetime as _dt
        cached_at = cached.get("_cached_at","")
        if not cached_at:
            return None
        age = (_dt.now() - _dt.fromisoformat(cached_at)).days
        sisa = 85 - age
        return {"age": age, "sisa": sisa, "cached_at": cached_at[:10]}
    except:
        return None

def fetch_fundamental_with_cache(ticker):
    """
    Fetch fundamental dengan cache cerdas:
    - Harga saham: SELALU fresh (dari yfinance, tidak di-cache)
    - Data fundamental: cache 85 hari (data kuartal update per 90 hari)
    """
    # Cek cache untuk data fundamental
    cached = _cache_get(ticker, max_days=85)

    if cached:
        # Punya cache — hanya update harga terkini
        try:
            import yfinance as yf
            t = yf.Ticker(f"{ticker}.JK")
            hist = t.history(period="2d")
            if not hist.empty:
                cached["price"] = round(hist.iloc[-1]["Close"], 0)
                cached["price_updated"] = datetime.now().strftime("%d %b %Y")
        except: pass
        cached["_from_cache"] = True
        return cached
    else:
        # Tidak ada cache / expired — fetch semua dari API
        data = _fetch_multi_fundamental(ticker)
        if data and data.get("price"):
            # Simpan ke cache (tanpa harga — harga selalu fresh)
            cache_data = {k: v for k, v in data.items()
                         if k not in ("price", "price_updated", "_from_cache")}
            _cache_set(ticker, cache_data)
        data["_from_cache"] = False
        return data

def build_context(prompt):
    """Build market context — inject ke prompt jika relevan."""
    tickers = [t for t in re.findall(r'\b([A-Z]{4})\b', prompt.upper())
               if t not in {"YANG","ATAU","DARI","PADA","UNTUK","SAYA","TOLONG",
                            "ANALISA","SAHAM","MOHON","BISA","FUNDAMENTAL","DENGAN",
                            "MINTA","ANALISIS","APAKAH","BAGAIMANA","KENAPA"}][:3]
    _p = prompt.lower()
    _kw = ["analisa","saham","ihsg","entry","beli","jual","teknikal","fundamental",
           "harga","support","resistance","chart","bandar","volume","valuasi",
           "berita","news","perang","ekonomi","inflasi","rupiah","market","pasar",
           "global","china","amerika","fed","trump","tarif","ekspor","impor",
           "geopolitik","dividen","ipo","ojk","bei","idx","makro","mikro"]
    _skip = ["hai","halo","selamat","makasih","oke","tugas","pr ","essay","apa itu","pengertian"]
    if any(k in _p for k in _skip) and not tickers:
        return ""
    if not tickers and not any(k in _p for k in _kw):
        return ""

    # Deteksi apakah ini permintaan fundamental — jika ya, skip berita agar tidak overflow
    _is_fundamental = any(k in _p for k in ["fundamental","laporan","keuangan","valuasi","roe","roa","per ","pbv"])

    data = _fetch_all_data(tickers)
    current_year = datetime.now().year
    lines = [f"Tanggal: {datetime.now().strftime('%d %B %Y %H:%M WIB')} | Tahun: {current_year}"]

    # Harga & rasio
    for tk, d in data["prices"].items():
        arah = "▲" if d["chg"]>=0 else "▼"
        line = f"{tk}: Rp{d['price']:,.0f} {arah}{abs(d['chg']):.2f}% [{d.get('source','')}]"
        if d.get("pe"): line += f" PER:{d['pe']:.1f}x"
        if d.get("pbv"): line += f" PBV:{d['pbv']:.1f}x"
        if d.get("roe"): line += f" ROE:{d['roe']*100:.1f}%"
        if d.get("eps"): line += f" EPS:Rp{d['eps']:,.0f}"
        lines.append(line)

    # Berita hanya untuk non-fundamental agar tidak overflow token
    if not _is_fundamental and data["news"]:
        lines.append("Berita terkini:")
        lines.extend(data["news"][:3])

    return "\n".join(lines) if len(lines)>1 else ""

def _calc_cagr(values_sorted_new_to_old):
    """Hitung CAGR dari list nilai [terbaru, ..., terlama]."""
    vals = [v for v in values_sorted_new_to_old if v and v > 0]
    if len(vals) < 2:
        return None
    n = len(vals) - 1
    try:
        return (vals[0] / vals[-1]) ** (1/n) - 1
    except:
        return None


def build_combined_context(prompt):
    """Gabungkan IDX + global context secara parallel."""
    import threading
    local_ctx = [""]
    global_ctx = [""]
    def fl(): local_ctx[0] = build_context(prompt)
    def fg(): global_ctx[0] = build_global_context(prompt)
    t1 = threading.Thread(target=fl, daemon=True)
    t2 = threading.Thread(target=fg, daemon=True)
    t1.start(); t2.start()
    t1.join(timeout=12); t2.join(timeout=15)
    parts = []
    if local_ctx[0]: parts.append("[DATA PASAR IDX]\n" + local_ctx[0] + "\n[/DATA PASAR IDX]")
    if global_ctx[0]: parts.append("[DATA GLOBAL]\n" + global_ctx[0] + "\n[/DATA GLOBAL]")
    return "\n\n".join(parts)

def build_fundamental_from_text(prompt):
    """
    Untuk perintah teks seperti 'analisa fundamental BBNI' tanpa PDF.
    Deteksi ticker → cek sektor → fetch yfinance → hitung CAGR → proyeksi 3 tahun.
    """
    ticker = detect_ticker_from_prompt(prompt)
    if not ticker:
        return ""
    import threading
    result = [""]
    def fetch():
        try:
            # Fetch dari semua sumber dengan cache
            multi = fetch_fundamental_with_cache(ticker)
            _from_cache = multi.get("_from_cache", False)
            import yfinance as yf
            t = yf.Ticker(f"{ticker}.JK")
            info = t.info
            hist_price = t.history(period="5d")
            current_year = datetime.now().year

            # Deteksi sektor otomatis
            is_bank = is_bank_sector(ticker, info)
            sektor = "Perbankan" if is_bank else "Non-Perbankan"
            if is_bank:
                framework = "Perbankan (NIM, NPL, LDR, CAR, BOPO, CIR)"
                per_default = 12.0  # PER historis bank IDX rata-rata
            else:
                # Pilih framework berdasarkan sektor
                sector_yf = (info.get("sector") or "").lower()
                if "energ" in sector_yf or "mining" in sector_yf or "tambang" in sector_yf:
                    framework = "Graham (Deep Value) + Buffett"
                    per_default = 10.0
                elif "consumer" in sector_yf or "retail" in sector_yf:
                    framework = "Lynch (GARP) + Buffett"
                    per_default = 18.0
                elif "tech" in sector_yf or "technology" in sector_yf:
                    framework = "CAN SLIM + Lynch"
                    per_default = 25.0
                else:
                    framework = "Buffett + Graham"
                    per_default = 15.0

            # Info cache
            cache_info = _cache_info(ticker)
            cache_label = ""
            if _from_cache and cache_info:
                cache_label = f" [cache: {cache_info['cached_at']}, sisa {cache_info['sisa']} hari]"
            elif not _from_cache:
                cache_label = " [data baru di-fetch]"

            lines = [f"=== DATA FUNDAMENTAL {ticker} ({sektor}){cache_label} ===",
                     f"Tahun sekarang: {current_year}",
                     f"Sektor: {sektor} | Framework: {framework}"]

            # ── Harga & valuasi live ──
            # Prioritas: yfinance → Finnhub → Alpha Vantage
            price     = round(hist_price.iloc[-1]["Close"], 0) if not hist_price.empty else multi.get("price")
            eps_yf    = info.get("trailingEps") or multi.get("eps")
            bv_yf     = info.get("bookValue") or multi.get("bv")
            pe_yf     = info.get("trailingPE") or multi.get("pe")
            pbv_yf    = info.get("priceToBook") or multi.get("pbv")
            shares    = info.get("sharesOutstanding") or multi.get("shares")
            div_yield = info.get("dividendYield") or multi.get("div_yield")
            roe_data  = info.get("returnOnEquity") or multi.get("roe")
            roa_data  = info.get("returnOnAssets") or multi.get("roa")

            if price:
                lines.append(f"💹 Harga Saham Saat Ini : Rp{price:,.0f} (per {datetime.now().strftime('%d %b %Y')})")
            if info.get("marketCap"):
                lines.append(f"Market Cap     : Rp{info['marketCap']/1e12:.1f} T")
            if info.get("fiftyTwoWeekHigh"):
                lines.append(f"52W High/Low   : Rp{info['fiftyTwoWeekHigh']:,.0f} / Rp{info['fiftyTwoWeekLow']:,.0f}")

            # PER — yfinance atau hitung manual
            if pe_yf:
                lines.append(f"PER            : {pe_yf:.2f}× [yfinance]")
            elif price and eps_yf and eps_yf > 0:
                pe_calc = price / eps_yf
                lines.append(f"PER (hitung)   : {pe_calc:.2f}× = Rp{price:,.0f} ÷ Rp{eps_yf:,.0f}")
                pe_yf = pe_calc
            else:
                lines.append(f"PER            : hitung dari knowledge (EPS tidak tersedia)")

            # PBV — yfinance atau hitung manual
            if pbv_yf:
                lines.append(f"PBV            : {pbv_yf:.2f}× [yfinance]")
            elif price and bv_yf and bv_yf > 0:
                pbv_calc = price / bv_yf
                lines.append(f"PBV (hitung)   : {pbv_calc:.2f}× = Rp{price:,.0f} ÷ Rp{bv_yf:,.0f}")
                pbv_yf = pbv_calc
            else:
                lines.append(f"PBV            : hitung dari (Ekuitas ÷ Saham) ÷ Harga")

            if eps_yf:
                lines.append(f"EPS (TTM)      : Rp{eps_yf:,.0f}")
            if bv_yf:
                lines.append(f"Book Value/Sh  : Rp{bv_yf:,.0f}")
            if info.get("returnOnEquity"):
                lines.append(f"ROE            : {info['returnOnEquity']*100:.2f}%")
            if info.get("returnOnAssets"):
                lines.append(f"ROA            : {info['returnOnAssets']*100:.2f}%")
            if div_yield:
                lines.append(f"Div Yield      : {div_yield*100:.2f}%")

            # ── Laporan keuangan historis + CAGR ──
            ni_vals = []
            eps_vals = []
            ni_years = []

            # Prioritas: FMP historis (lebih lengkap) → yfinance income_stmt
            if multi.get("hist_ni"):
                lines.append("\n── Historis Keuangan (FMP) ──")
                vals_str = [f"{yr}: Rp{ni/1e12:.1f}T" for yr, ni in multi["hist_ni"]]
                lines.append("Laba Bersih    : " + " | ".join(vals_str))
                ni_vals = [ni for _, ni in multi["hist_ni"]]
                ni_years = [yr for yr, _ in multi["hist_ni"]]
            if multi.get("hist_eps"):
                vals_str = [f"{yr}: Rp{eps:,.0f}" for yr, eps in multi["hist_eps"]]
                lines.append("EPS Historis   : " + " | ".join(vals_str))
                eps_vals = [eps for _, eps in multi["hist_eps"]]
            if multi.get("hist_rev"):
                vals_str = [f"{yr}: Rp{rev/1e12:.1f}T" for yr, rev in multi["hist_rev"]]
                lines.append("Pendapatan     : " + " | ".join(vals_str))

            # Fallback ke yfinance jika FMP tidak ada data historis
            if not ni_vals:
                try:
                    inc = None
                    for method in ["income_stmt", "financials"]:
                        try:
                            inc = getattr(t, method)
                            if inc is not None and not inc.empty:
                                break
                        except: pass
                    if inc is not None and not inc.empty:
                        inc = inc.reindex(sorted(inc.columns, reverse=True), axis=1)
                        lines.append("\n── Historis Keuangan (yfinance) ──")
                        if "Net Income" in inc.index:
                            row = inc.loc["Net Income"].dropna()
                            cols = sorted(row.index, reverse=True)[:5]
                            vals_str = []
                            for col in cols:
                                v = row[col]
                                ni_vals.append(v)
                                ni_years.append(str(col)[:4])
                                vals_str.append(f"{str(col)[:4]}: Rp{v/1e12:.1f}T")
                            lines.append("Laba Bersih    : " + " | ".join(vals_str))
                        if "Basic EPS" in inc.index:
                            row = inc.loc["Basic EPS"].dropna()
                            cols = sorted(row.index, reverse=True)[:5]
                            vals_str = []
                            for col in cols:
                                v = row[col]
                                eps_vals.append(v)
                                vals_str.append(f"{str(col)[:4]}: Rp{v:,.0f}")
                            lines.append("EPS Historis   : " + " | ".join(vals_str))
                except: pass

            # ── CAGR & Proyeksi Python ──
            lines.append("\n── Kalkulasi CAGR & Proyeksi ──")
            cagr_ni = _calc_cagr(ni_vals)
            cagr_eps = _calc_cagr(eps_vals)

            if cagr_ni is not None:
                lines.append(f"CAGR Laba Bersih: {cagr_ni*100:.1f}% per tahun ({ni_years[-1]}→{ni_years[0]})")
            if cagr_eps is not None:
                lines.append(f"CAGR EPS        : {cagr_eps*100:.1f}% per tahun")

            # Proyeksi 3 tahun
            base_eps = eps_vals[0] if eps_vals else eps_yf
            base_ni  = ni_vals[0] if ni_vals else None
            growth   = cagr_ni if cagr_ni else (cagr_eps if cagr_eps else 0.08)
            per_base = pe_yf if pe_yf else 12.0  # fallback PER 12x untuk bank

            if base_eps and growth is not None:
                lines.append(f"\n── Proyeksi 3 Tahun (CAGR {growth*100:.1f}%/thn, PER basis {per_base:.1f}x) ──")
                proj_list = []
                for i in range(1, 4):
                    yr = current_year + i
                    proj_eps = base_eps * (1 + growth) ** i
                    proj_ni  = (base_ni * (1 + growth) ** i / 1e12) if base_ni else None
                    t_konservatif = round_to_tick(proj_eps * per_base * 0.8)
                    t_moderat     = round_to_tick(proj_eps * per_base)
                    t_optimis     = round_to_tick(proj_eps * per_base * 1.2)
                    ni_str = f" | Laba ~Rp{proj_ni:.1f}T" if proj_ni else ""
                    lines.append(f"  {yr}: EPS ~Rp{proj_eps:,.0f}{ni_str}")
                    lines.append(f"       🎯 Konservatif: Rp{t_konservatif:,.0f} | Moderat: Rp{t_moderat:,.0f} | Optimis: Rp{t_optimis:,.0f}")
                    proj_list.append(t_moderat)

                # Nilai wajar saat ini berdasarkan EPS TTM × PER
                if base_eps and per_base:
                    nilai_wajar_low  = round_to_tick(base_eps * per_base * 0.8)
                    nilai_wajar_mid  = round_to_tick(base_eps * per_base)
                    nilai_wajar_high = round_to_tick(base_eps * per_base * 1.2)
                    lines.append(f"\n💎 NILAI WAJAR SAAT INI (EPS × PER {per_base:.1f}x):")
                    lines.append(f"   Harga Saat Ini : Rp{price:,.0f}" if price else "   Harga Saat Ini : N/A")
                    lines.append(f"   Konservatif    : Rp{nilai_wajar_low:,.0f}")
                    lines.append(f"   Moderat        : Rp{nilai_wajar_mid:,.0f}")
                    lines.append(f"   Optimis        : Rp{nilai_wajar_high:,.0f}")
                    if price:
                        selisih = ((price - nilai_wajar_mid) / nilai_wajar_mid * 100)
                        if price < nilai_wajar_low:
                            lines.append(f"   Status: 🟢 UNDERVALUE — diskon {abs(selisih):.1f}% dari nilai wajar")
                        elif price > nilai_wajar_high:
                            lines.append(f"   Status: 🔴 OVERVALUE — premium {selisih:.1f}% di atas nilai wajar")
                        else:
                            lines.append(f"   Status: 🟡 FAIRVALUE — harga dalam range wajar ({selisih:+.1f}%)")

            # Cek IPO date
            ipo_year = None
            try:
                hist_all = t.history(period="max")
                if not hist_all.empty:
                    ipo_year = hist_all.index[0].year
            except: pass

            lines.append(f"\n=== INSTRUKSI OUTPUT ===")
            if price:
                lines.append(f"BARIS PERTAMA WAJIB: 💹 Harga: Rp{price:,.0f} | {datetime.now().strftime('%d %b %Y')}")
            lines.append(f"SEKTOR: {sektor} | FRAMEWORK: {framework}")
            lines.append(f"Icon: pilih SATU — ✅ pass, ⚠️ perhatian, ❌ fail.")
            lines.append(f"PENTING: yfinance tidak punya NIM/NPL/CAR/BOPO/LDR/CIR.")
            lines.append(f"Untuk metrik yang tidak ada di data di atas: WAJIB isi dari knowledge model.")
            if ipo_year and ipo_year >= current_year - 2:
                lines.append(f"⚠️ EMITEN BARU — IPO {ipo_year}. JANGAN tulis tren sebelum {ipo_year}.")
                lines.append(f"Untuk tren: tulis 'Baru IPO {ipo_year} — historis belum tersedia'")
            else:
                lines.append(f"Data yfinance sering hanya s/d 2022-2023. Beri label (est.) jika perkiraan.")
                lines.append(f"Tren 3 tahun: {current_year-2}→{current_year-1}→{current_year}")
            lines.append(f"Untuk bank: WAJIB isi NIM, NPL, LDR, CAR, BOPO, CIR dari knowledge model.")
            lines.append(f"Untuk non-bank: WAJIB isi Gross Margin, DER, Current Ratio dari knowledge.")
            lines.append(f"Tren & proyeksi: isi dengan angka knowledge model, beri label (est.)")
            lines.append(f"JANGAN tulis N/A untuk data yang kamu tahu — tulis angkanya.")
            lines.append(f"Nilai wajar sudah dihitung Python — tampilkan di VALUASI.")
            lines.append("=== AKHIR DATA ===")
        except Exception as e:
            result[0] = f"[Gagal fetch {ticker}: {e}] Gunakan knowledge model untuk {ticker}."
    th = threading.Thread(target=fetch, daemon=True)
    th.start()
    th.join(timeout=15)
    return result[0]

# ─── PDF ENRICHMENT — deteksi emiten & lengkapi data dari yfinance ───
# Emiten map dengan sektor
EMITEN_MAP = {
    # Bank — urutan PENTING: nama lebih spesifik/panjang duluan
    "bank syariah indonesia": "BRIS", "bris": "BRIS",
    "bank central asia": "BBCA", "bbca": "BBCA",
    "bank rakyat indonesia": "BBRI", "bbri": "BBRI",
    "bank mandiri": "BMRI", "bmri": "BMRI",
    "bank negara indonesia": "BBNI", "bbni": "BBNI",
    "bank tabungan negara": "BBTN", "bbtn": "BBTN",
    "bank cimb niaga": "BNGA", "bnga": "BNGA",
    "bank danamon": "BDMN", "bdmn": "BDMN",
    "bank permata": "BNLI", "bnli": "BNLI",
    "bank panin": "PNBN", "pnbn": "PNBN",
    # Alias pendek — letakkan SETELAH kode 4 huruf agar tidak override
    "bca": "BBCA", "bri": "BBRI", "mandiri": "BMRI",
    "bni": "BBNI", "btn": "BBTN", "bsi": "BRIS",
    "cimb": "BNGA", "danamon": "BDMN", "permata": "BNLI", "panin": "PNBN",
    # Telko & Tech → sektor "non-bank"
    "telkom": "TLKM", "tlkm": "TLKM",
    "xl axiata": "EXCL", "xl": "EXCL", "excl": "EXCL",
    "indosat": "ISAT", "isat": "ISAT",
    "goto": "GOTO", "gojek": "GOTO", "tokopedia": "GOTO", "goto": "GOTO",
    "bukalapak": "BUKA", "buka": "BUKA",
    # Consumer & Industri → sektor "non-bank"
    "astra": "ASII", "asii": "ASII",
    "unilever": "UNVR", "unvr": "UNVR",
    "indofood": "INDF", "indf": "INDF",
    "indofood cbp": "ICBP", "icbp": "ICBP",
    "mayora": "MYOR", "myor": "MYOR",
    "kalbe": "KLBF", "klbf": "KLBF",
    "sido muncul": "SIDO", "sido": "SIDO",
    # Energi & Tambang → sektor "non-bank"
    "adaro": "ADRO", "adro": "ADRO",
    "antam": "ANTM", "antm": "ANTM",
    "ptba": "PTBA", "bukit asam": "PTBA",
    "pgas": "PGAS", "perusahaan gas": "PGAS",
    "medc": "MEDC", "medco": "MEDC",
    "brms": "BRMS", "bumi resources minerals": "BRMS",
    "bumi resources": "BUMI", "bumi": "BUMI",
    "vale": "INCO", "inco": "INCO",
    # Properti & Semen → sektor "non-bank"
    "semen indonesia": "SMGR", "smgr": "SMGR",
    "indocement": "INTP", "intp": "INTP",
    "ciputra": "CTRA", "ctra": "CTRA",
    "bsde": "BSDE", "summarecon": "SMRA",
}

# Ticker yang diketahui sebagai bank
BANK_TICKERS = {"BBCA","BBRI","BMRI","BBNI","BBTN","BRIS","BNGA","BDMN",
                "BNLI","PNBN","BJTM","BJBR","BMAS","MEGA","NISP","BTPN"}

def is_bank_sector(ticker, info=None):
    """Deteksi apakah emiten adalah bank."""
    if ticker in BANK_TICKERS:
        return True
    if info:
        sector = (info.get("sector") or "").lower()
        industry = (info.get("industry") or "").lower()
        if "bank" in sector or "bank" in industry or "financial" in sector:
            return True
    return False

def round_to_tick(price):
    """Bulatkan harga ke fraksi BEI yang valid."""
    if price is None or price <= 0:
        return price
    if price < 200:
        tick = 1
    elif price < 500:
        tick = 2
    elif price < 2000:
        tick = 5
    elif price < 5000:
        tick = 10
    else:
        tick = 25
    return round(price / tick) * tick

def detect_emiten(text):
    """Deteksi kode emiten dari teks PDF atau prompt."""
    text_lower = text[:3000].lower()
    # Cek EMITEN_MAP dulu (nama lengkap dan kode)
    for name, ticker in EMITEN_MAP.items():
        if name in text_lower:
            return ticker
    # Cari 4 huruf kapital yang valid sebagai ticker IDX
    matches = re.findall(r'\b([A-Z]{4})\b', text[:2000])
    skip = {"PADA","YANG","ATAU","DARI","BANK","TBKK","ANAK","ASET","LABA",
            "RUGI","TOTAL","BERSIH","TAHUN","SALDO","DANA","PIHAK","USAHA",
            "MODAL","KREDIT","BIAYA","BUNGA","PAJAK","LAIN","ATAS","DALAM"}
    for m in matches:
        if m not in skip:
            return m
    return None

def detect_ticker_from_prompt(prompt):
    """Deteksi ticker dari perintah teks user (bukan PDF)."""
    prompt_upper = prompt.upper()
    prompt_lower = prompt.lower()

    skip = {"YANG","ATAU","DARI","PADA","UNTUK","SAYA","TOLONG","ANALISA",
            "SAHAM","MOHON","BISA","FUNDAMENTAL","DENGAN","MINTA","ANALISIS",
            "APAKAH","BAGAIMANA","KENAPA","COBA"}

    # Step 1: Cari 4 huruf kapital yang valid sebagai ticker langsung
    matches = re.findall(r'\b([A-Z]{4})\b', prompt_upper)
    for m in matches:
        if m not in skip:
            return m  # BRIS, BBCA, BMRI, dll langsung ketemu

    # Step 2: Cek nama panjang di EMITEN_MAP (bank syariah indonesia → BRIS)
    for name, ticker in EMITEN_MAP.items():
        if len(name) > 4 and name in prompt_lower:
            return ticker

    # Step 3: Cek alias pendek (bca, bri, dll)
    for name, ticker in EMITEN_MAP.items():
        if len(name) <= 4 and name in prompt_lower.split():
            return ticker

    return None

def fetch_price_for_pdf(ticker):
    """Fetch harga live untuk melengkapi data PDF."""
    import threading
    result = [{}]
    def fetch():
        try:
            import yfinance as yf
            t = yf.Ticker(f"{ticker}.JK")
            hist = t.history(period="5d")
            info = t.info
            if not hist.empty:
                price = round(hist.iloc[-1]["Close"], 0)
                result[0] = {
                    "price": price,
                    "pe": info.get("trailingPE"),
                    "pbv": info.get("priceToBook"),
                    "eps_yf": info.get("trailingEps"),
                    "bv": info.get("bookValue"),
                    "shares": info.get("sharesOutstanding"),
                    "mktcap": info.get("marketCap"),
                    "div_yield": info.get("dividendYield"),
                    "w52h": info.get("fiftyTwoWeekHigh"),
                    "w52l": info.get("fiftyTwoWeekLow"),
                    "roe": info.get("returnOnEquity"),
                    "roa": info.get("returnOnAssets"),
                    "source": "yfinance"
                }
        except: pass
        # Fallback stooq
        if not result[0].get("price"):
            try:
                import pandas_datareader as pdr
                from datetime import timedelta
                df = pdr.get_data_stooq(f"{ticker}.JK",
                    start=datetime.now()-timedelta(days=7),
                    end=datetime.now())
                if not df.empty:
                    result[0] = {"price": round(df.sort_index().iloc[-1]["Close"],0), "source": "stooq"}
            except: pass
        # Fallback IDX API
        if not result[0].get("price"):
            try:
                import urllib.request, json as _j
                req = urllib.request.Request(
                    f"https://www.idx.co.id/umbraco/Surface/StockData/GetTradingInfoSS?code={ticker}",
                    headers={"User-Agent":"Mozilla/5.0","Referer":"https://www.idx.co.id/"})
                with urllib.request.urlopen(req, timeout=3) as r:
                    d = _j.loads(r.read())
                if d and d.get("LastPrice"):
                    result[0] = {"price": d["LastPrice"], "source": "IDX"}
            except: pass
    th = threading.Thread(target=fetch, daemon=True)
    th.start()
    th.join(timeout=12)
    return result[0]

def enrich_pdf_context(pdf_text):
    """
    Lengkapi data PDF dengan harga live + hitung rasio yang kurang.
    Return string tambahan untuk diinject ke prompt.
    """
    ticker = detect_emiten(pdf_text)
    if not ticker:
        return ""
    price_data = fetch_price_for_pdf(ticker)
    if not price_data.get("price"):
        return ""
    price = price_data["price"]
    lines = [
        f"\n=== DATA LIVE {ticker} (sumber: {price_data.get('source','-')}) ===",
        f"Harga Saham    : Rp{price:,.0f}",
    ]
    if price_data.get("mktcap"):
        lines.append(f"Market Cap     : Rp{price_data['mktcap']/1e12:.1f} triliun")
    if price_data.get("w52h"):
        lines.append(f"52W High/Low   : Rp{price_data['w52h']:,.0f} / Rp{price_data['w52l']:,.0f}")
    # PER — dari yfinance atau hitung manual
    if price_data.get("pe"):
        lines.append(f"PER            : {price_data['pe']:.2f}× [yfinance]")
    elif price_data.get("eps_yf") and price_data["eps_yf"] > 0:
        per_calc = price / price_data["eps_yf"]
        lines.append(f"PER (hitung)   : {per_calc:.2f}× = Rp{price:,.0f} ÷ Rp{price_data['eps_yf']:,.0f}")
    else:
        lines.append(f"PER            : hitung dari EPS laporan ÷ Rp{price:,.0f}")
    # PBV — dari yfinance atau hitung manual
    if price_data.get("pbv"):
        lines.append(f"PBV            : {price_data['pbv']:.2f}× [yfinance]")
    elif price_data.get("bv") and price_data["bv"] > 0:
        pbv_calc = price / price_data["bv"]
        lines.append(f"PBV (hitung)   : {pbv_calc:.2f}× = Rp{price:,.0f} ÷ Rp{price_data['bv']:,.0f}")
    else:
        lines.append(f"PBV            : hitung dari (Total Ekuitas ÷ Jumlah Saham) lalu bagi Rp{price:,.0f}")
    if price_data.get("eps_yf"):
        lines.append(f"EPS (TTM)      : Rp{price_data['eps_yf']:,.0f}")
    if price_data.get("bv"):
        lines.append(f"Book Value/Sh  : Rp{price_data['bv']:,.0f}")
    if price_data.get("div_yield"):
        lines.append(f"Dividend Yield : {price_data['div_yield']*100:.2f}%")
    if price_data.get("roe"):
        lines.append(f"ROE (TTM)      : {price_data['roe']*100:.2f}%")
    if price_data.get("roa"):
        lines.append(f"ROA (TTM)      : {price_data['roa']*100:.2f}%")
    current_year = datetime.now().year
    current_year = datetime.now().year
    # Rumus kalkulasi yang tersedia jika data kurang
    lines.append(f"\n── Rumus Hitung Manual ──")
    lines.append(f"PER  = Harga (Rp{price_data.get('price','?'):,}) ÷ EPS laporan")
    lines.append(f"PBV  = Harga (Rp{price_data.get('price','?'):,}) ÷ (Total Ekuitas ÷ Jumlah Saham)")
    lines.append(f"DPS  = Total Dividen ÷ Jumlah Saham Beredar")
    lines.append(f"Payout Ratio = Total Dividen ÷ Laba Bersih × 100")
    lines.append(f"ROA  = Laba Sebelum Pajak ÷ Rata-rata Total Aset × 100")
    lines.append(f"\nTAHUN SEKARANG: {current_year}")
    lines.append(f"Tren 3 tahun: {current_year-2}→{current_year-1}→{current_year}")
    lines.append(f"Proyeksi: {current_year+1}, {current_year+2}, {current_year+3}")
    lines.append(f"Gunakan rumus di atas untuk hitung metrik yang tidak ada di PDF.")
    lines.append("=== AKHIR DATA LIVE ===")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="KIPM SIGMA",
    layout="wide",
    initial_sidebar_state="expanded"
)

DATA_DIR = ".sigma_data"
os.makedirs(DATA_DIR, exist_ok=True)
CACHE_DIR = os.path.join(DATA_DIR, "fundamental_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# ─────────────────────────────────────────────
# PERSISTENCE
# ─────────────────────────────────────────────
def _ukey(email): return hashlib.md5(email.encode()).hexdigest()

def save_user(email, data):
    try:
        with open(os.path.join(DATA_DIR, f"{_ukey(email)}.json"), "w") as f:
            json.dump(data, f, ensure_ascii=False)
    except: pass

def load_user(email):
    try:
        p = os.path.join(DATA_DIR, f"{_ukey(email)}.json")
        if os.path.exists(p):
            with open(p) as f: return json.load(f)
    except: pass
    return None

# Username/password auth
def get_accounts():
    p = os.path.join(DATA_DIR, "accounts.json")
    if os.path.exists(p):
        with open(p) as f: return json.load(f)
    return {}

def save_accounts(acc):
    with open(os.path.join(DATA_DIR, "accounts.json"), "w") as f:
        json.dump(acc, f)

def register_user(username, password, display_name):
    acc = get_accounts()
    if username in acc: return False, "Username sudah dipakai"
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    acc[username] = {"password": hashed, "display_name": display_name, "email": f"{username}@local"}
    save_accounts(acc)
    return True, "Berhasil daftar"

def login_user(username, password):
    acc = get_accounts()
    if username not in acc: return None
    if bcrypt.checkpw(password.encode(), acc[username]["password"].encode()):
        return {"email": acc[username]["email"], "name": acc[username]["display_name"], "picture": ""}
    return None

# ─────────────────────────────────────────────
# THEME COLORS
# ─────────────────────────────────────────────
def get_colors(theme="dark"):
    dark = theme == "dark"
    return {
        "bg":           "#212121" if dark else "#f0f0f0",
        "sidebar_bg":   "#171717" if dark else "#e3e3e3",
        "text":         "#ececec" if dark else "#0d0d0d",
        "text_muted":   "#8e8ea0" if dark else "#6e6e80",
        "border":       "#2f2f2f" if dark else "#d0d0d0",
        "hover":        "#2f2f2f" if dark else "#d0d0d0",
        "input_bg":     "#2f2f2f" if dark else "#ffffff",
        "bubble":       "#1B2A4A",
        "bubble_text":  "#ffffff",
        "divider":      "#2f2f2f" if dark else "#d0d0d0",
        "gold":         "#F5C242",
        "active_bg":    "#2f2f2f" if dark else "#c8c8c8",
    }

# ─────────────────────────────────────────────
# SESSION INIT
# ─────────────────────────────────────────────
def init_session():
    defaults = {
        "user": None,
        "theme": "dark",
        "data_loaded": False,
        "sessions": None,
        "active_id": None,
        "rename_id": None,
        "img_data": None,
        "pdf_data": None,
        "show_settings": False,
        "auth_mode": "login",  # login | register | google
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session()

C = get_colors(st.session_state.theme)

# ─────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────
SYSTEM_PROMPT = {
    "role": "system",
    "content": """Kamu adalah SIGMA — asisten cerdas KIPM Universitas Pancasila, by Market n Mocha (MnM).

KEPRIBADIAN: Ramah saat ngobrol biasa, profesional saat analisa. Bahasa Indonesia natural.
PENTING: SIGMA boleh memberikan pandangan analitis berbasis data (contoh: "secara fundamental 
saham ini undervalue dan layak diakumulasi"). Yang TIDAK BOLEH adalah menjanjikan keuntungan 
atau menyuruh beli/jual dengan uang nyata tanpa konteks risiko. Selalu akhiri dengan DYOR.

════════════════════════════════════
KOMITMEN PEMAHAMAN WAJIB SIGMA
════════════════════════════════════

1. CONFLUENCE = KEKUATAN AREA
   Ketika komponen MnM Strategy+ bertumpuk di satu area harga yang sama:
   IFVG + FVG + OB + Supply/Demand + EMA → area SANGAT KUAT
   Semakin banyak komponen overlap → probabilitas reversal makin tinggi
   Urutan kekuatan: IFVG > FVG > OB > Supply/Demand > EMA
   WAJIB sebutkan semua komponen confluence yang ditemukan saat analisa

2. PASAR IDX = LONG ONLY
   BEI tidak mengenal short selling untuk retail investor
   → Profit HANYA dari harga naik
   → Trade plan SELALU: entry di bawah, target di atas candle
   → SL SELALU di bawah entry
   → TP SELALU di atas entry
   → Bias BEARISH = rekomendasikan WAIT, BUKAN short
   → Bias SIDEWAYS = rekomendasikan WAIT sampai arah jelas

3. PRIORITAS ANALISA (TIDAK BOLEH DIBALIK)
   PERTAMA  : Logika Pine Script MnM Strategy+ (parameter exact, warna, kondisi)
   KEDUA    : Knowledge trading umum (hanya pelengkap jika Pine Script tidak cover)
   KONFLIK  : Selalu ikuti logika Pine Script
   
4. ALUR WAJIB SAAT MENERIMA SCREENSHOT CHART
   Step 1: Identifikasi SEMUA zona berdasarkan warna exact Pine Script
   Step 2: Hitung confluence — komponen apa saja yang bertumpuk
   Step 3: Tentukan posisi harga vs EMA 13/21/50/100/200
   Step 4: Cek IFVG/FVG yang belum dimitigasi (magnet harga)
   Step 5: Identifikasi OB aktif vs Breaker Block
   Step 6: Cek Supply/Demand zone — approaching atau dalam zone
   Step 7: Tentukan bias BULLISH atau WAIT
   Step 8: Jika BULLISH + confluence kuat → buat trade plan
   Step 9: Entry, SL (bawah entry), TP1/TP2 (atas entry)
   Step 10: SEMUA harga WAJIB sesuai fraksi tick BEI

KEMAMPUAN:
1. Trading & Pasar Modal — teknikal, fundamental, bandarmologi, berita pasar
2. Ekonomi & Bisnis — makro, mikro, geopolitik, akuntansi, manajemen, investasi
3. Pendidikan — bantu tugas, jelaskan konsep, essay, laporan, matematika
4. Umum — jawab pertanyaan apapun, berikan solusi praktis

════════════════════════════════════
FRAMEWORK TEKNIKAL — MnM Strategy+ (Pine Script v6)
════════════════════════════════════

── IDENTIFIKASI WARNA DI CHART ──
Saat menerima screenshot chart, kenali zona berdasarkan warna:

IFVG (Inversion Fair Value Gap):
  Biru (#0048ff, opacity 80)     = IFVG Bullish (sebelum inversi)
  Abu gelap (#575757, opacity 83) = IFVG Bearish (sebelum inversi)
  Setelah inversi → warna DIBALIK (bullish jadi abu, bearish jadi biru)
  Garis putus-putus di tengah    = midline IFVG

FVG (Fair Value Gap):
  Biru tua (#0015ff, opacity 60) = FVG Bullish
  Abu gelap (#575757, opacity 60) = FVG Bearish
  ⚠️ FVG Bear & IFVG Bear warna SAMA → bedakan dari struktur (IFVG punya midline)

Order Block:
  Hijau neon (#09ff00, opacity 90) = Bullish OB (aktif)
  Pink/Magenta (#ea00ff, opacity 95) = Bearish OB (aktif)
  Abu terang (#9e9e9e)              = Breaker Block (OB yang sudah ditembus → terbalik)

Supply & Demand:
  Abu sedang (rgb 114,114,114, opacity 69) = Supply Zone
  Biru muda/Cyan (rgb 0,159,212, opacity 60) = Demand Zone
  Border dashed = zona sudah di-test tapi belum break

Moving Average:
  Garis Biru (#009dff)  = EMA 13 (jangka pendek)
  Garis Merah (#ff0000) = EMA 21 (jangka pendek)
  Garis Ungu (#cc00ff)  = EMA 50 (medium term)
  EMA 100 & 200         = konfirmasi trend jangka panjang

── PARAMETER & SETUP DEFAULT ──
IFVG : ATR(200) × 0.25 filter | Display last 3 pasang | Signal: Close
FVG  : Extend 20 bar | Mitigasi: close menembus zone
OB   : Swing lookback 10 | Show last 3 Bull + 3 Bear | Pakai High/Low
S&D  : Volume MA 1000 | ATR(200)×2 untuk tinggi zone | Cooldown 15 candle | Max 5 Supply

── LOGIKA SETIAP KOMPONEN ──

1. IFVG — Inversion Fair Value Gap:
   Bullish: low > high[2] AND close[1] > high[2] → gap dikonfirmasi
   Bearish: high < low[2] AND close[1] < low[2] → gap dikonfirmasi
   Ukuran gap harus > ATR(200)×0.25 → filter gap kecil tidak valid
   Signal entry: close menembus zona IFVG setelah retest
   Bullish entry: close > zona top, close[1] dalam zona
   Bearish entry: close < zona bottom, close[1] dalam zona

2. FVG — Fair Value Gap:
   Bullish: low > high[2] → gap antara candle 1 dan 3
   Bearish: high < low[2] → gap antara candle 1 dan 3
   Mitigasi: FVG dihapus saat harga close menembus zone
   Unmitigated FVG = masih valid sebagai magnet harga

3. Order Block:
   Bullish OB: candle low terendah sebelum breakout swing high
   Bearish OB: candle high tertinggi sebelum breakout swing low
   Breaker: OB ditembus → fungsi terbalik (support jadi resistance)
   Breaker dihapus saat harga menembus sisi lainnya

4. Supply & Demand:
   Supply: 3 candle bear + volume > avg → cari candle bull sebelumnya
   Demand: 3 candle bull + volume > avg → cari candle bear sebelumnya
   Tinggi zone = ATR(200) × 2
   Delta volume ditampilkan (rasio buy vs sell di zone)
   Tested zone (border dashed) = harga pernah masuk tapi belum break

5. Moving Average (EMA default):
   EMA 13  → entry signal jangka pendek, scalping/swing
   EMA 21  → konfirmasi trend jangka pendek
   EMA 50  → trend medium term, konfirmasi bias
   EMA 100 → support/resistance dinamis jangka menengah
   EMA 200 → trend besar | harga > EMA200 = uptrend | < EMA200 = downtrend
   Golden Cross: EMA50 cross up EMA200 → sinyal bullish kuat
   Death Cross : EMA50 cross down EMA200 → sinyal bearish kuat
   Support MTF (multi-timeframe) untuk konfirmasi lebih kuat

── CONFLUENCE MULTI-DIMENSI ──

SIGMA menganalisa dari 3 lapisan sekaligus:

LAPISAN 1 — TEKNIKAL (MnM Strategy+):
  Semakin banyak komponen bertumpuk di satu area harga → makin kuat
  1 komponen  = lemah
  2 komponen  = moderate
  3+ komponen = KUAT — potensi reversal tinggi
  Urutan kekuatan: IFVG > FVG > OB > Supply/Demand > EMA
  Contoh: IFVG Bullish + Demand Zone + OB Bullish + EMA 50 = confluence sangat kuat

LAPISAN 2 — KOMODITAS (kaitkan ke sektor saham IDX):
  Coal/Batubara naik  → PTBA, ADRO, BUMI, ITMG bullish
  Nikel naik          → INCO, ANTM bullish
  CPO/Palm Oil naik   → AALI, LSIP, SIMP bullish
  Minyak/Crude naik   → PGAS, MEDC, ELSA bullish
  Emas/Gold naik      → ANTM, MDKA bullish
  Tembaga/Copper naik → ANTM, MDKA, INCO bullish
  Aluminum naik       → INALUM, INAI bullish

LAPISAN 3 — NEWS & GEOPOLITIK:
  Perang di timur tengah → minyak naik → emiten energi bullish
  Konflik supply chain   → komoditas naik → emiten tambang bullish
  Fed tahan/turun rate   → IHSG bullish, rupiah menguat
  Fed naikkan rate       → IHSG bearish, rupiah melemah
  China stimulus         → komoditas naik, saham China bullish
  Perang dagang US-China → supply chain terganggu → volatilitas tinggi
  Dollar menguat (DXY↑)  → komoditas turun, IHSG tertekan
  Dollar melemah (DXY↓)  → komoditas naik, IHSG menguat

CARA GABUNGKAN 3 LAPISAN:
  Teknikal kuat + Komoditas mendukung + News positif
  = Confluence 3 dimensi → probabilitas reversal SANGAT TINGGI

  Teknikal kuat + Komoditas netral + News negatif
  = Confluence lemah → WAIT, risiko tinggi

  Teknikal lemah + Komoditas + News kuat
  = Potensi ada tapi entry belum ideal → tunggu konfirmasi teknikal

SELALU sebutkan confluence dari 3 lapisan dalam analisa:
  "Secara teknikal ada IFVG + Demand Zone, didukung harga coal yang naik X%,
   dikonfirmasi berita [sumber] — confluence 3 dimensi → potensi reversal kuat"

── ATURAN POSISI PER MARKET ──

🇮🇩 SAHAM INDONESIA (IDX/BEI):
  ✅ LONG ONLY — tidak ada short selling untuk retail
  → Target SELALU di atas entry | SL di bawah entry
  → Bias bearish = WAIT, jangan masuk

🇺🇸 SAHAM US (NYSE/NASDAQ):
  ✅ LONG ONLY — analisa untuk posisi beli
  → Target di atas entry | SL di bawah entry
  → Bias bearish = WAIT
  → Harga dalam USD, tidak perlu fraksi tick BEI

🇨🇳 SAHAM CHINA (SSE/SZSE/HK):
  ✅ LONG ONLY — analisa untuk posisi beli
  → Target di atas entry | SL di bawah entry
  → Bias bearish = WAIT

₿ CRYPTO SPOT (BTC/ETH/dll beli langsung):
  ✅ LONG ONLY — beli aset crypto langsung
  → Target di atas entry | SL di bawah entry
  → Bias bearish = WAIT atau reduce position

📈 CRYPTO FUTURES (perpetual/delivery):
  ✅ LONG & SHORT tersedia
  → Long: target atas, SL bawah
  → Short: target bawah, SL atas
  → Sebutkan leverage jika relevan
  → Perhatikan liquidation price

💱 FOREX FUTURES (currency pairs):
  ✅ LONG & SHORT tersedia
  → Long: target atas, SL bawah (misal EUR/USD naik)
  → Short: target bawah, SL atas (misal EUR/USD turun)
  → Pip value berbeda per pair

ATURAN UMUM SEMUA MARKET:
  → Risk/Reward minimal 1:2
  → Selalu sebutkan market/exchange yang dimaksud
  → Fraksi tick BEI hanya untuk saham IDX
  → Untuk market lain gunakan harga yang logis sesuai instrumen

── PRIORITAS PEMAHAMAN ──
1. UTAMA : Logika MnM Strategy+ dari Pine Script (parameter, warna, kondisi)
2. KEDUA : Knowledge trading umum sebagai pelengkap
Jika ada konflik → ikuti logika Pine Script

── CARA ANALISA SAAT MENERIMA SCREENSHOT ──
1. Identifikasi SEMUA zona berdasarkan warna (IFVG, FVG, OB, S&D, EMA)
2. Hitung confluence — berapa komponen bertumpuk di satu area
3. Tentukan posisi harga vs EMA 13/21/50/100/200
4. Cek IFVG/FVG yang belum dimitigasi → magnet harga terdekat
5. Identifikasi OB aktif vs Breaker Block
6. Cek Supply/Demand — approaching zone atau dalam zone
7. Tentukan bias: Bullish / Sideways / Bearish (wait)
8. Jika Bullish → buat trade plan dengan entry, SL (bawah), TP1/TP2 (atas)
9. Semua harga WAJIB sesuai fraksi tick BEI
10. Sebutkan confluence yang ditemukan sebagai dasar analisa

FORMAT TRADE PLAN:
📊 TRADE PLAN — [SAHAM] ([TIMEFRAME])
⚡ Bias: [Bullish/Bearish/Sideways]
🎯 Entry : [harga]
🛑 SL    : [harga]
✅ TP1   : [harga]
✅ TP2   : [harga]
📦 Bandarmologi : [ringkasan volume & aksi bandar]
⚠️ Invalidasi   : [kondisi]
⚠️ DYOR — bukan rekomendasi investasi

FRAKSI HARGA BEI (wajib semua harga):
< Rp200: tick Rp1 | Rp200-500: tick Rp2 | Rp500-2rb: tick Rp5
Rp2rb-5rb: tick Rp10 | > Rp5rb: tick Rp25

════════════════════════════════════
FRAMEWORK FUNDAMENTAL — MULTI-FRAMEWORK
════════════════════════════════════

DETEKSI SEKTOR OTOMATIS:
- Ada kata NPL/NIM/DPK/CAR/LDR/BOPO → gunakan FRAMEWORK PERBANKAN
- Selainnya → gunakan FRAMEWORK UMUM

── FRAMEWORK UMUM ──

1. Warren Buffett (Value Investing):
   ROE > 15% konsisten | DER < 0.5 | Net Profit Margin naik konsisten
   EPS Growth positif & konsisten | FCF > Net Income | Ada moat bisnis

2. Peter Lynch (Growth at Reasonable Price):
   PEG Ratio < 1 (ideal), < 2 (acceptable) | PEG = PER ÷ EPS Growth Rate
   Revenue Growth > 20% YoY | DER < 0.35

3. Benjamin Graham (Deep Value):
   PBV < 1.5 | PER < 15 | PER × PBV < 22.5
   Current Ratio > 2 | EPS positif min 5 tahun berturut

4. CAN SLIM (William O'Neil):
   C: EPS quarter naik > 25% YoY
   A: EPS tahunan naik > 25% selama 3 tahun
   N: Ada katalis baru (produk/manajemen)
   S: Volume naik saat harga naik
   L: RS Rating > 80
   I: Ada institusi besar masuk
   M: Beli saat market uptrend

── FRAMEWORK PERBANKAN (khusus bank) ──
   NIM > 4%      → selisih bunga pinjaman vs simpanan
   NPL < 3%      → kredit macet (kritis jika > 5%)
   LDR 80-92%    → rasio kredit vs dana pihak ketiga
   CAR > 14%     → ketahanan modal (min BI 8%)
   ROA > 1.5%    → return on assets
   ROE > 15%     → return on equity
   BOPO < 70%    → efisiensi operasional
   CIR < 45%     → cost to income ratio
   EPS Growth    → konsisten naik
   DPS & Payout  → konsisten bayar dividen

FORMAT ANALISA FUNDAMENTAL:
📋 ANALISA FUNDAMENTAL — [EMITEN] ([TAHUN])
🏦 Sektor: [Perbankan / Non-Perbankan]
📌 Framework: [Buffett / Graham / Lynch / CAN SLIM / Perbankan]

💰 PROFITABILITAS
- ROE      : X% → Buffett >15% [✅/⚠️/❌]
- ROA      : X% → standar >1.5% [✅/⚠️/❌]
- NIM      : X% → standar >4% [✅/⚠️/❌]
- BOPO     : X% → efisien <70% [✅/⚠️/❌]
- Laba Bersih: RpX T → YoY [+/-X]%
- EPS      : RpX → YoY [+/-X]%

🛡️ KUALITAS ASET
- NPL Gross: X% → sehat <3% [✅/⚠️/❌]
- NPL Net  : X% → sehat <1% [✅/⚠️/❌]
- CAR      : X% → aman >14% [✅/⚠️/❌]
- LDR      : X% → ideal 80-92% [✅/⚠️/❌]
- CIR      : X% → ideal <45% [✅/⚠️/❌]

📈 VALUASI
- PER  : Xx → Graham <15 [✅/⚠️/❌]
- PBV  : Xx → Graham <1.5 [✅/⚠️/❌]
- PEG  : X → Lynch <1 [✅/⚠️/❌]
- Harga Wajar: RpX – RpX

🏆 DIVIDEN
- DPS         : RpX
- Payout Ratio: X%
- Konsistensi : [naik/stabil/turun sejak tahun X]

📊 TREN 3-5 TAHUN
- Laba Bersih: [Y-2] → [Y-1] → [Y] (CAGR ~X%)
- EPS        : [Y-2] → [Y-1] → [Y] (tren naik/turun)
- ROE        : [Y-2] → [Y-1] → [Y]
- Dividen    : [konsisten/tidak]

🔭 PROYEKSI 3 TAHUN KE DEPAN
Basis: CAGR laba X% × PER historis rata-rata
- [Y+1]: EPS RpX → Target Harga RpX–RpX
- [Y+2]: EPS RpX → Target Harga RpX–RpX
- [Y+3]: EPS RpX → Target Harga RpX–RpX
Skenario: Konservatif RpX | Moderat RpX | Optimis RpX

⚖️ VERDICT
- Score    : X/10
- Kekuatan :
  → [poin kekuatan 1 dengan angka]
  → [poin kekuatan 2 dengan angka]
- Risiko   :
  → [poin risiko 1 dengan angka]
  → [poin risiko 2 dengan angka]
- Valuasi  : [Undervalue/Fairvalue/Overvalue] — harga Rp[X] vs wajar Rp[X]
- Kesimpulan: [Paragraph 4-5 kalimat yang menceritakan: kondisi bisnis saat ini,
  tren pertumbuhan, posisi valuasi, risiko utama yang perlu diperhatikan,
  dan saran konkret: accumulate/wait/avoid dengan alasan spesifik]
⚠️ DYOR — analisa ini berbasis data, bukan rekomendasi investasi. Keputusan final ada di tangan investor.

ATURAN OUTPUT WAJIB:
- Setiap metrik di BARIS TERPISAH — DILARANG digabung horizontal
- Isi angka AKTUAL dari data — jika tidak ada, hitung dari rumus atau knowledge
- Jika ada [DATA PASAR] atau [DATA LIVE] → gunakan harga dan rasio dari sana
- TAHUN di judul: isi dengan tahun AKTUAL laporan atau tahun sekarang (2026)
- Tren 3 tahun: gunakan 2024→2025→2026, BUKAN 2020/2021/2022
- Proyeksi dihitung dari CAGR aktual
- ICON STATUS: pilih SATU saja — ✅ (pass) atau ⚠️ (perhatian) atau ❌ (fail)
  DILARANG menulis [✅/⚠️/❌] — harus pilih salah satu
  Contoh BENAR: ROE: 14,5% → standar >15% [❌]
  Contoh SALAH: ROE: 14,5% → standar >15% [✅/⚠️/❌]
- Harga saat ini WAJIB tampil di baris pertama setelah header
- Data yfinance untuk saham IDX TIDAK PUNYA: NIM, NPL, CAR, BOPO, LDR, CIR
  Untuk metrik ini: WAJIB isi dari knowledge model kamu tentang emiten tersebut
  Beri label "(est.)" jika dari knowledge model
- DILARANG tulis "N/A" untuk metrik yang kamu TAHU dari knowledge model
  Contoh: NIM BBRI sekitar 7-8%, NPL BBRI sekitar 3%, CAR BBRI >20% — TULIS angkanya
- Hanya tulis "N/A" jika benar-benar tidak ada data sama sekali dan tidak tahu
- Untuk emiten baru (IPO < 2 tahun): tren historis TIDAK ADA — tulis "Baru IPO [tahun]"
- Tren dan proyeksi: WAJIB isi dengan estimasi dari knowledge, beri label "(est.)"
- Jawab Bahasa Indonesia. Gambar/PDF → analisa langsung."""
}

# ─────────────────────────────────────────────
# DELETE SESSION HANDLER — proses sebelum render UI
# ─────────────────────────────────────────────
def process_delete_if_pending():
    """Proses delete session jika ada del param di URL."""
    _del_sid = st.query_params.get("del", "")
    if not _del_sid:
        return False
    _user = st.session_state.get("user")
    if not _user:
        # User belum ada di session — load dari token dulu
        _tok = st.query_params.get("sigma_token", "")
        if _tok:
            _tfile = os.path.join(DATA_DIR, f"token_{_tok}.json")
            if os.path.exists(_tfile):
                try:
                    with open(_tfile) as _f:
                        _user = json.load(_f)
                    st.session_state.user = _user
                    st.session_state.current_token = _tok
                except: pass
    if not _user:
        return False
    _email = _user.get("email", "")
    if not _email:
        return False
    _saved = load_user(_email)
    if not _saved:
        return False
    _sessions = _saved.get("sessions", [])
    _new_sessions = [s for s in _sessions if s["id"] != _del_sid]
    if not _new_sessions:
        _new_sessions = [new_session()]
    _new_active = _saved.get("active_id", "")
    if _new_active == _del_sid:
        _new_active = _new_sessions[0]["id"]
    # Simpan ke disk
    save_user(_email, {
        "theme": _saved.get("theme", "dark"),
        "sessions": _new_sessions,
        "active_id": _new_active,
    })
    # Update session state
    st.session_state.sessions = _new_sessions
    st.session_state.active_id = _new_active
    st.session_state.data_loaded = True
    # Hapus param
    try:
        del st.query_params["del"]
    except:
        try: st.query_params.pop("del")
        except: pass
    return True

# ─────────────────────────────────────────────
# CHAT SESSION HELPERS
# ─────────────────────────────────────────────
def new_session():
    return {
        "id": str(uuid.uuid4())[:8],
        "title": "Obrolan Baru",
        "messages": [SYSTEM_PROMPT],
        "created": datetime.now().strftime("%d/%m %H:%M")
    }

def init_chat():
    if not st.session_state.sessions:
        s = new_session()
        st.session_state.sessions = [s]
        st.session_state.active_id = s["id"]
    else:
        for s in st.session_state.sessions:
            if not s["messages"] or s["messages"][0].get("role") != "system":
                s["messages"].insert(0, SYSTEM_PROMPT)
            else:
                s["messages"][0] = SYSTEM_PROMPT

def restore_images_from_messages():
    """Restore gambar dari message ke session_state agar tampil setelah refresh."""
    if not st.session_state.sessions:
        return
    for sesi in st.session_state.sessions:
        for i, msg in enumerate(sesi.get("messages", [])):
            if msg.get("role") == "user" and msg.get("img_b64"):
                key = f"thumb_{sesi['id']}_{i-1}"
                if key not in st.session_state:
                    st.session_state[key] = (msg["img_b64"], msg.get("img_mime", "image/jpeg"))

def get_active():
    for s in st.session_state.sessions:
        if s["id"] == st.session_state.active_id:
            return s
    return st.session_state.sessions[0]
    for s in st.session_state.sessions:
        if s["id"] == st.session_state.active_id:
            return s
    return st.session_state.sessions[0]

def delete_session(sid):
    st.session_state.sessions = [s for s in st.session_state.sessions if s["id"] != sid]
    if not st.session_state.sessions:
        ns = new_session()
        st.session_state.sessions = [ns]
    if st.session_state.active_id == sid:
        st.session_state.active_id = st.session_state.sessions[0]["id"]

# ─────────────────────────────────────────────
# GOOGLE OAUTH
# ─────────────────────────────────────────────
def google_auth_url():
    params = {
        "client_id": st.secrets.get("GOOGLE_CLIENT_ID", ""),
        "redirect_uri": st.secrets.get("GOOGLE_REDIRECT_URI", ""),
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

def handle_oauth(code):
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": st.secrets.get("GOOGLE_CLIENT_ID", ""),
        "client_secret": st.secrets.get("GOOGLE_CLIENT_SECRET", ""),
        "redirect_uri": st.secrets.get("GOOGLE_REDIRECT_URI", ""),
        "grant_type": "authorization_code",
    })
    if r.status_code != 200: return None
    token = r.json().get("access_token", "")
    if not token: return None
    u = requests.get("https://www.googleapis.com/oauth2/v2/userinfo",
                     headers={"Authorization": f"Bearer {token}"})
    return u.json() if u.status_code == 200 else None

# ─────────────────────────────────────────────
# HANDLE OAUTH CALLBACK
# ─────────────────────────────────────────────
if "code" in st.query_params and st.session_state.user is None:
    info = handle_oauth(st.query_params["code"])
    if info:
        st.session_state.user = info
        saved = load_user(info["email"])
        if saved:
            st.session_state.theme = saved.get("theme", "dark")
            if saved.get("sessions"):
                st.session_state.sessions = saved["sessions"]
                st.session_state.active_id = saved.get("active_id")
        st.session_state.data_loaded = True
        # Buat token untuk auto-login — sama seperti username login
        token = str(uuid.uuid4()).replace("-","")
        with open(os.path.join(DATA_DIR, f"token_{token}.json"), "w") as f:
            json.dump(info, f)
        st.session_state.current_token = token
        st.query_params.clear()
        st.query_params["sigma_token"] = token  # Set di URL agar persist saat refresh
        st.rerun()

# ─────────────────────────────────────────────
# RESTORE SESSION DARI TOKEN (auto-login saat refresh)
# ─────────────────────────────────────────────
if "sigma_token" in st.query_params and st.session_state.user is None:
    token = st.query_params.get("sigma_token", "")
    token_file = os.path.join(DATA_DIR, f"token_{token}.json")
    if os.path.exists(token_file):
        try:
            with open(token_file) as f:
                user_info = json.load(f)
            st.session_state.user = user_info
            st.session_state.current_token = token

            # Proses delete DI SINI sebelum load sessions
            _del_sid = st.query_params.get("del", "")
            if _del_sid:
                saved_pre = load_user(user_info["email"])
                if saved_pre and saved_pre.get("sessions"):
                    # Hapus session dari data disk
                    new_sessions = [s for s in saved_pre["sessions"] if s["id"] != _del_sid]
                    if not new_sessions:
                        new_sessions = [{"id": str(uuid.uuid4()), "title": "Obrolan Baru",
                                        "created": datetime.now().isoformat(), "messages": []}]
                    new_active = saved_pre.get("active_id")
                    if new_active == _del_sid:
                        new_active = new_sessions[0]["id"]
                    # Simpan ke disk SEKARANG
                    save_user(user_info["email"], {
                        "theme": saved_pre.get("theme", "dark"),
                        "sessions": new_sessions,
                        "active_id": new_active,
                    })
                st.query_params.pop("del")

            # Load sessions dari disk (sudah terupdate jika ada delete)
            saved = load_user(user_info["email"])
            if saved:
                st.session_state.theme = saved.get("theme", "dark")
                if saved.get("sessions"):
                    st.session_state.sessions = saved["sessions"]
                    st.session_state.active_id = saved.get("active_id")
            st.session_state.data_loaded = True
            restore_images_from_messages()
            st.rerun()
        except: pass

# Proses delete jika ada
if "del" in st.query_params:
    if process_delete_if_pending():
        st.rerun()

# Load data setelah login
if st.session_state.user and not st.session_state.data_loaded:
    saved = load_user(st.session_state.user["email"])
    if saved:
        st.session_state.theme = saved.get("theme", "dark")
        if saved.get("sessions") and not st.session_state.sessions:
            st.session_state.sessions = saved["sessions"]
            st.session_state.active_id = saved.get("active_id")
    st.session_state.data_loaded = True
    restore_images_from_messages()

# Refresh colors after theme load
C = get_colors(st.session_state.theme)

# ─────────────────────────────────────────────
# GLOBAL CSS
# ─────────────────────────────────────────────
st.markdown(f"""
<style>
* {{ font-family: ui-sans-serif,-apple-system,system-ui,"Segoe UI",sans-serif !important; box-sizing: border-box; }}

/* Global BG */
.stApp, [data-testid="stAppViewContainer"],
[data-testid="stAppViewContainer"] > section,
section[data-testid="stMain"],
[data-testid="stMainBlockContainer"],
[data-testid="stBottom"],
[data-testid="stBottom"] > div {{
    background: {C['bg']} !important;
}}

/* Sidebar */
section[data-testid="stSidebar"],
section[data-testid="stSidebar"] > div,
section[data-testid="stSidebar"] > div > div,
section[data-testid="stSidebar"] > div > div > div,
[data-testid="stSidebarContent"],
[data-testid="stSidebarUserContent"],
[data-testid="stSidebarUserContent"] > div,
[data-testid="stSidebarUserContent"] > div > div {{
    background: {C['sidebar_bg']} !important;
    box-shadow: none !important;
}}
section[data-testid="stSidebar"] {{
    border-right: 1px solid {C['border']} !important;
}}

/* Zero padding sidebar */
section[data-testid="stSidebar"] > div,
section[data-testid="stSidebar"] > div > div,
[data-testid="stSidebarContent"],
[data-testid="stSidebarUserContent"],
[data-testid="stSidebarUserContent"] > div {{
    padding-top: 0 !important;
    margin-top: 0 !important;
}}

/* Hide Streamlit collapse button */
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"] {{
    display: none !important;
}}

/* Sidebar buttons */
section[data-testid="stSidebar"] .stButton > button {{
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: {C['text']} !important;
    font-size: 0.875rem !important;
    padding: 7px 12px !important;
    border-radius: 8px !important;
    width: 100% !important;
    display: flex !important;
    align-items: center !important;
    justify-content: flex-start !important;
    text-align: left !important;
    min-height: 36px !important;
}}
section[data-testid="stSidebar"] .stButton > button:hover {{
    background: {C['hover']} !important;
}}
section[data-testid="stSidebar"] .stButton > button p,
section[data-testid="stSidebar"] .stButton > button span {{
    margin: 0 !important;
    text-align: left !important;
    color: inherit !important;
    width: 100% !important;
}}

/* Chat messages */
[data-testid="stChatMessage"] {{
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}}
[data-testid="stChatMessageAvatarUser"],
[data-testid="stChatMessageAvatarAssistant"] {{
    display: none !important;
}}
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {{
    font-size: 0.9rem !important;
    line-height: 1.75 !important;
    color: {C['text']} !important;
    background: transparent !important;
}}

/* Main content */
[data-testid="stMainBlockContainer"] {{
    max-width: 800px !important;
    margin: 0 auto !important;
    padding: 0 16px 120px !important;
    overflow-y: visible !important;
}}
[data-testid="stMainBlockContainer"] p,
[data-testid="stMainBlockContainer"] li,
[data-testid="stMainBlockContainer"] h1,
[data-testid="stMainBlockContainer"] h2,
[data-testid="stMainBlockContainer"] h3 {{
    color: {C['text']} !important;
}}

/* Chat input */
div[data-testid="stChatInputContainer"] {{
    border: 1px solid {C['border']} !important;
    background: {C['input_bg']} !important;
    border-radius: 16px !important;
}}
[data-testid="stChatInput"] textarea {{
    background: {C['input_bg']} !important;
    color: {C['text']} !important;
    font-size: 0.9rem !important;
}}
[data-testid="stChatInput"] textarea::placeholder {{
    color: {C['text_muted']} !important;
}}
[data-testid="stChatInputContainer"] textarea:focus {{
    box-shadow: none !important;
    outline: none !important;
}}

footer, #MainMenu {{ visibility: hidden !important; }}

/* Divider */
hr {{ border-color: {C['border']} !important; }}

/* ── BASE FONT — konsisten semua ukuran ── */
[data-testid="stMarkdownContainer"] *,
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] span,
[data-testid="stMarkdownContainer"] div {{
    font-size: 0.95rem !important;
    line-height: 1.8 !important;
}}
[data-testid="stMarkdownContainer"] strong,
[data-testid="stMarkdownContainer"] b {{
    font-size: inherit !important;
}}
[data-testid="stMarkdownContainer"] h1 {{ font-size: 1.3rem !important; }}
[data-testid="stMarkdownContainer"] h2 {{ font-size: 1.15rem !important; }}
[data-testid="stMarkdownContainer"] h3 {{ font-size: 1.05rem !important; }}

/* ── MOBILE ── */
@media (max-width: 768px) {{

    [data-testid="stMainBlockContainer"] {{
        max-width: 100% !important;
        padding: 12px 16px 120px !important;
    }}

    /* Font konsisten di mobile — semua elemen sama */
    [data-testid="stMarkdownContainer"],
    [data-testid="stMarkdownContainer"] *,
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stMarkdownContainer"] span,
    [data-testid="stMarkdownContainer"] strong,
    [data-testid="stMarkdownContainer"] b,
    [data-testid="stMarkdownContainer"] em {{
        font-size: 1rem !important;
        line-height: 1.85 !important;
    }}
    [data-testid="stMarkdownContainer"] h1 {{ font-size: 1.25rem !important; }}
    [data-testid="stMarkdownContainer"] h2 {{ font-size: 1.1rem !important; }}
    [data-testid="stMarkdownContainer"] h3 {{ font-size: 1rem !important; font-weight: 700 !important; }}

    /* List lebih rapi */
    [data-testid="stMarkdownContainer"] ul,
    [data-testid="stMarkdownContainer"] ol {{
        padding-left: 20px !important;
        margin: 6px 0 !important;
    }}
    [data-testid="stMarkdownContainer"] li {{
        margin-bottom: 4px !important;
    }}

    /* Code block */
    [data-testid="stMarkdownContainer"] code {{
        font-size: 0.85rem !important;
        padding: 2px 6px !important;
        border-radius: 4px !important;
        background: rgba(255,255,255,0.08) !important;
    }}
    [data-testid="stMarkdownContainer"] pre {{
        font-size: 0.82rem !important;
        overflow-x: auto !important;
        padding: 12px !important;
        border-radius: 8px !important;
    }}

    /* Chat input */
    div[data-testid="stChatInputContainer"] {{
        border-radius: 26px !important;
        margin: 0 6px 8px !important;
    }}
    [data-testid="stChatInput"] textarea {{
        font-size: 16px !important;
        line-height: 1.5 !important;
    }}

    /* Pesan lebih bernapas */
    [data-testid="stChatMessage"] {{
        padding: 10px 0 !important;
    }}

    /* Bubble user */
    .navy-pill {{
        max-width: 82% !important;
        font-size: 1rem !important;
        line-height: 1.7 !important;
        padding: 12px 16px !important;
    }}
}}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# LOGIN PAGE
# ─────────────────────────────────────────────
def show_login():
    st.markdown(f"""
    <style>
    [data-testid="stSidebar"] {{ display: none !important; }}

    /* Background full screen kipmd.png (desktop) / kipmm.png (mobile) */
    [data-testid="stAppViewContainer"],
    section[data-testid="stMain"] {{
        background: url('https://raw.githubusercontent.com/kipmuniversitaspancasila-commits/KIPMSIGMA/main/kipmd.png') center/cover no-repeat fixed !important;
        min-height: 100vh !important;
    }}

    /* Hapus pseudo-element kiri */
    section[data-testid="stMain"]::before {{
        display: none !important;
    }}

    /* Form container — transparan glass, compact, geser 1cm dari kanan */
    [data-testid="stMainBlockContainer"] {{
        max-width: 300px !important;
        margin: 1.5vh 74px 0 auto !important;
        padding: 8px 18px 16px !important;
        position: relative;
        z-index: 1;
        min-height: unset !important;
        height: fit-content !important;
        background: rgba(5, 8, 20, 0.60) !important;
        backdrop-filter: blur(20px) saturate(1.4) !important;
        -webkit-backdrop-filter: blur(20px) saturate(1.4) !important;
        border: 1px solid rgba(255,255,255,0.10) !important;
        border-radius: 20px !important;
        box-shadow: 0 8px 40px rgba(0,0,0,0.5) !important;
    }}
    @media(max-width: 768px) {{
        [data-testid="stMainBlockContainer"] {{
            margin: 5vh auto 0 auto !important;
            max-width: 88% !important;
            padding: 20px 20px 28px !important;
            backdrop-filter: blur(20px) !important;
            border-radius: 20px !important;
            border: 1px solid rgba(255,255,255,0.12) !important;
            box-shadow: 0 8px 40px rgba(0,0,0,0.5) !important;
        }}
    }}

    /* Sembunyikan header toolbar Streamlit bawaan */
    header[data-testid="stHeader"] {{
        display: none !important;
    }}
    #MainMenu {{
        display: none !important;
    }}

    /* Mobile — pastikan background terlihat di atas & bawah kotak */
    @media(max-width: 768px) {{
        [data-testid="stAppViewContainer"],
        section[data-testid="stMain"] {{
            background: url('https://raw.githubusercontent.com/kipmuniversitaspancasila-commits/KIPMSIGMA/main/kipmm.png') center top/cover no-repeat fixed !important;
        }}
        /* Kotak login beri ruang logo KIPM di atas */
        [data-testid="stMainBlockContainer"] {{
            margin-top: 75px !important;
        }}
    }}

    /* Glass card */
    .stTabs, [data-testid="stVerticalBlock"] {{
        background: transparent !important;
    }}

    /* Input fields glass style */
    [data-testid="stTextInput"] input {{
        background: rgba(255,255,255,0.06) !important;
        border: 1px solid rgba(255,255,255,0.12) !important;
        border-radius: 12px !important;
        color: #fff !important;
        padding: 12px 16px !important;
        font-size: 0.95rem !important;
        backdrop-filter: blur(10px) !important;
        transition: border 0.2s !important;
    }}
    [data-testid="stTextInput"] input:focus {{
        border: 1px solid {C['gold']} !important;
        box-shadow: 0 0 0 2px rgba(245,194,66,0.15) !important;
        outline: none !important;
    }}
    [data-testid="stTextInput"] input::placeholder {{ color: rgba(255,255,255,0.35) !important; }}
    [data-testid="stTextInput"] label {{ color: rgba(255,255,255,0.6) !important; font-size: 0.82rem !important; }}

    /* Masuk button */
    [data-testid="stMainBlockContainer"] .stButton > button {{
        background: linear-gradient(135deg, {C['gold']}, #e0a820) !important;
        color: #000 !important;
        font-weight: 700 !important;
        border: none !important;
        border-radius: 12px !important;
        padding: 12px !important;
        font-size: 0.95rem !important;
        letter-spacing: 0.5px !important;
        transition: opacity 0.2s, transform 0.1s !important;
        box-shadow: 0 4px 20px rgba(245,194,66,0.3) !important;
    }}
    [data-testid="stMainBlockContainer"] .stButton > button:hover {{
        opacity: 0.92 !important; transform: translateY(-1px) !important;
    }}

    /* Tabs glass */
    [data-testid="stTabs"] [role="tablist"] {{
        background: rgba(255,255,255,0.05) !important;
        border-radius: 12px !important;
        padding: 4px !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        gap: 2px !important;
    }}
    [data-testid="stTabs"] button[role="tab"] {{
        border-radius: 9px !important;
        color: rgba(255,255,255,0.5) !important;
        font-size: 0.85rem !important;
        padding: 7px 12px !important;
        border: none !important;
        background: transparent !important;
    }}
    [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{
        background: rgba(245,194,66,0.15) !important;
        color: {C['gold']} !important;
        font-weight: 600 !important;
    }}
    [data-testid="stTabs"] [role="tabpanel"] {{
        background: rgba(255,255,255,0.03) !important;
        border-radius: 16px !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        padding: 20px 16px !important;
        margin-top: 8px !important;
        backdrop-filter: blur(10px) !important;
    }}

    /* Alert colors */
    [data-testid="stAlert"] {{ border-radius: 10px !important; }}

    /* Animasi background */
    @keyframes gradMove {{
        0% {{ background-position: 0% 50%; }}
        50% {{ background-position: 100% 50%; }}
        100% {{ background-position: 0% 50%; }}
    }}
    </style>
    """, unsafe_allow_html=True)

    # Background sudah di-set via CSS (URL GitHub raw)

    # Inject logo KIPM khusus mobile — hanya saat halaman login
    components.html(f"""
<script>
(function() {{
    var pd = window.parent.document;

    // Sembunyikan Fork bar & toolbar GitHub Streamlit
    var forkStyle = pd.getElementById('hide-fork-bar');
    if (!forkStyle) {{
        var fs = pd.createElement('style');
        fs.id = 'hide-fork-bar';
        fs.textContent = `
            /* Fork bar & GitHub badge */
            .viewerBadge_container__r5tak,
            .viewerBadge_link__qRIco,
            [class*="viewerBadge"],
            [class*="styles_viewerBadge"],
            #MainMenu,
            footer,
            /* Streamlit toolbar atas */
            [data-testid="stToolbar"],
            [data-testid="stDecoration"],
            [data-testid="stStatusWidget"],
            header[data-testid="stHeader"],
            /* Tombol deploy/fork */
            .stDeployButton,
            [kind="header"],
            div[data-testid="collapsedControl"] {{
                display: none !important;
                visibility: hidden !important;
                height: 0 !important;
                overflow: hidden !important;
            }}
        `;
        pd.head.appendChild(fs);
    }}

    if (pd.getElementById('kipm-mobile-logo')) return;

    var s = pd.createElement('style');
    s.id = 'kipm-mobile-logo-style';
    s.textContent = `
        #kipm-mobile-logo {{
            display: none;
            text-align: center;
            padding: 14px 0 10px;
            position: fixed;
            top: 0; left: 0; right: 0;
            z-index: 10;
            pointer-events: none;
        }}
        #kipm-mobile-logo img {{
            width: 80px; height: 80px;
            object-fit: contain;
            filter: drop-shadow(0 2px 12px rgba(0,0,0,0.6));
        }}
        #kipm-mobile-logo .kipm-name {{
            font-size: 0.7rem;
            color: rgba(255,255,255,0.7);
            letter-spacing: 2px;
            font-family: sans-serif;
            margin-top: 4px;
        }}
        @media(max-width: 768px) {{
            #kipm-mobile-logo {{ display: block !important; }}
        }}
    `;
    pd.head.appendChild(s);

    var div = pd.createElement('div');
    div.id = 'kipm-mobile-logo';
    div.innerHTML = `
        <img src="https://raw.githubusercontent.com/kipmuniversitaspancasila-commits/KIPMSIGMA/main/Mate%20KIPM%20LOGO.png"
             onerror="this.style.display='none'"
             style="width:80px;height:80px;object-fit:contain;">
        <div class="kipm-name">KIPM-UP</div>
    `;
    pd.body.appendChild(div);
}})();
</script>
""", height=0)
    st.markdown('''
        <div style="text-align:center;margin:0 0 10px;">
            <div style="font-size:2.8rem;font-weight:900;letter-spacing:5px;color:#ffffff;font-family:sans-serif;line-height:1.2;">
                SIGMA <span style="color:#F5C242;">Σ</span>
            </div>
            <div class="sigma-tagline" style="font-size:0.65rem;color:rgba(255,255,255,0.5);letter-spacing:2px;margin-top:4px;font-family:sans-serif;">
                Strategic Intelligence & Global Market Analysis
            </div>
        </div>
        <style>
            @media(min-width: 769px) { .sigma-tagline { display: none !important; } }
        </style>
    ''', unsafe_allow_html=True)
    tab1, tab2, tab3 = st.tabs(["🔑 Sign In", "📝 Sign Up", "🌐 Google"])

    with tab1:
        uname = st.text_input("Username", key="li_user", placeholder="Masukkan username")
        pwd   = st.text_input("Password", key="li_pwd",  type="password", placeholder="Masukkan password")
        if st.button("Masuk", key="btn_login", use_container_width=True):
            if uname and pwd:
                info = login_user(uname.strip(), pwd)
                if info:
                    token = str(uuid.uuid4()).replace("-","")
                    with open(os.path.join(DATA_DIR, f"token_{token}.json"), "w") as f:
                        json.dump(info, f)
                    st.query_params["sigma_token"] = token
                    st.session_state.user = info
                    st.session_state.current_token = token
                    st.session_state.data_loaded = False
                    st.rerun()
                else:
                    st.error("Username atau password salah")
            else:
                st.warning("Isi username dan password")

    with tab2:
        rname  = st.text_input("Nama Tampil", key="rg_name", placeholder="Nama lengkap kamu")
        runame = st.text_input("Username", key="rg_user", placeholder="username (huruf/angka)")
        rpwd   = st.text_input("Password", key="rg_pwd",  type="password", placeholder="min. 6 karakter")
        rpwd2  = st.text_input("Ulangi Password", key="rg_pwd2", type="password", placeholder="ulangi password")
        if st.button("Daftar Sekarang", key="btn_register", use_container_width=True):
            if not all([rname, runame, rpwd, rpwd2]):
                st.warning("Lengkapi semua field")
            elif rpwd != rpwd2:
                st.error("Password tidak cocok")
            elif len(rpwd) < 6:
                st.error("Password minimal 6 karakter")
            else:
                ok, msg = register_user(runame.strip(), rpwd, rname.strip())
                if ok:
                    st.success(f"✅ {msg} — silakan masuk")
                else:
                    st.error(msg)

    with tab3:
        try:
            auth_url = google_auth_url()
            st.markdown(f"""
            <div style="margin-top:8px;">
                <a href="{auth_url}" style="
                    display:flex;align-items:center;justify-content:center;gap:10px;
                    background:rgba(255,255,255,0.95);color:#1a1a1a;border-radius:12px;padding:13px;
                    text-decoration:none;font-size:0.9rem;font-weight:600;
                    border:none;box-shadow:0 4px 15px rgba(0,0,0,0.3);">
                    <svg width="18" height="18" viewBox="0 0 24 24">
                        <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                        <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                        <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/>
                        <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                    </svg>
                    Lanjutkan dengan Google
                </a>
            </div>
            """, unsafe_allow_html=True)
        except:
            st.info("Google login belum dikonfigurasi di Secrets")

    st.markdown(f"""
    <p style="text-align:center;color:rgba(255,255,255,0.25);font-size:0.72rem;margin-top:24px;line-height:1.6;">
        Dengan masuk, kamu menyetujui penggunaan platform untuk analisa.<br>
        Analisa bersifat <em>do your own research</em> dan disclaimer berlaku. by MarketnMocha
    </p>
    """, unsafe_allow_html=True)
    st.stop()

# ─────────────────────────────────────────────
# GUARD: LOGIN REQUIRED
# ─────────────────────────────────────────────
if st.session_state.user is None:
    show_login()

# Init chat after login
init_chat()
user = st.session_state.user
C = get_colors(st.session_state.theme)


# ─────────────────────────────────────────────
# SEMBUNYIKAN SIDEBAR
# ─────────────────────────────────────────────
st.markdown("""
<style>
section[data-testid="stSidebar"],
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"] { display: none !important; }

/* Sembunyikan Fork bar, GitHub badge, Streamlit logo di semua halaman */
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
.viewerBadge_container__r5tak,
[class*="viewerBadge"],
.stDeployButton,
#MainMenu,
footer,
/* Bar hitam Fork */
[data-testid="stHeader"],
iframe[title="streamlit_analytics"],
div[class*="Toolbar"],
div[class*="toolbar"],
div[class*="ActionButton"],
div[class*="HeaderActionButton"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

_hist_items = ""
for _sesi in st.session_state.sessions:
    _sid = _sesi["id"]
    _is_act = _sid == st.session_state.active_id
    _td = _sesi["title"][:35].replace("'","").replace("`","").replace("\\","").replace('"',"")
    _fw = "700" if _is_act else "400"
    _bg = C['hover'] if _is_act else "transparent"
    _hist_items += f"""
(function(){{
    var row=pd.createElement('div');
    row.style.cssText='display:flex;align-items:center;width:100%;';

    var a=pd.createElement('a');
    a.textContent='{_td}';
    var u=new URL(window.parent.location.href);
    u.searchParams.set('do','sel_{_sid}');
    a.href=u.toString();
    a.style.cssText='flex:1;display:block;padding:12px 8px 12px 18px;font-size:1rem;color:{C["text"]};background:{_bg};font-weight:{_fw};border:none;text-align:left;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-decoration:none;min-width:0;';
    a.onmouseenter=function(){{this.style.background='{C["hover"]}'}};
    a.onmouseleave=function(){{this.style.background='{_bg}'}};

    var del=pd.createElement('button');
    del.innerHTML='🗑';
    del.title='Hapus';
    del.style.cssText='padding:8px 12px;background:transparent;border:none;cursor:pointer;font-size:0.85rem;opacity:0.35;flex-shrink:0;color:{C["text"]};';
    del.onmouseenter=function(){{this.style.opacity='1';this.style.color='#ff5555';}};
    del.onmouseleave=function(){{this.style.opacity='0.35';this.style.color='{C["text"]}';}};
    del.onclick=function(e){{
        e.preventDefault();e.stopPropagation();
        if(confirm('Hapus obrolan ini?')){{
            var u2=new URL(window.parent.location.href);
            u2.searchParams.set('del','{_sid}');
            u2.searchParams.delete('do');
            window.parent.location.href=u2.toString();
        }}
    }};

    row.appendChild(a);
    row.appendChild(del);
    h.appendChild(row);
}})();
"""

# Inject menu ke parent document via components.html
components.html(f"""
<script>
(function(){{
var pd=window.parent.document;

// Sembunyikan logo KIPM login saat sudah masuk ke halaman utama
var kipmLogo = pd.getElementById('kipm-mobile-logo');
if (kipmLogo) kipmLogo.style.display = 'none !important';
var kipmStyle = pd.getElementById('kipm-mobile-logo-style');
if (kipmStyle) kipmStyle.remove();

// Hapus elemen lama kalau ada, inject ulang yang baru
['spbtn','spmenu','sphist','spui','sigma-mobile-css'].forEach(function(id){{
    var el=pd.getElementById(id);
    if(el) el.remove();
}});

// CSS
var s=pd.createElement('style');
s.id='sigma-mobile-css';
s.textContent=`
#spbtn{{position:fixed;bottom:16px;left:14px;width:38px;height:38px;border-radius:50%;
    background:{C["sidebar_bg"]};color:{C["text"]};border:1px solid {C["border"]};
    cursor:pointer;font-size:24px;font-weight:300;z-index:99999;
    display:flex;align-items:center;justify-content:center;
    box-shadow:0 2px 10px rgba(0,0,0,0.5);padding:0;line-height:1;}}
#spbtn:hover{{transform:scale(1.1)}}
#spmenu,#sphist{{position:fixed;left:12px;bottom:62px;
    background:{C["sidebar_bg"]};border:1px solid {C["border"]};
    border-radius:16px;box-shadow:0 -4px 24px rgba(0,0,0,0.5);
    z-index:99998;display:none;overflow:hidden;min-width:250px;}}
#sphist{{max-height:55vh;overflow-y:auto;}}
.smi{{display:flex;align-items:center;gap:14px;padding:13px 18px;
    font-size:1rem;color:{C["text"]};cursor:pointer;border:none;
    background:transparent;width:100%;text-align:left;}}
.smi:hover{{background:{C["hover"]}}}
.smico{{width:32px;height:32px;border-radius:8px;display:flex;
    align-items:center;justify-content:center;font-size:16px;
    background:{C["hover"]};flex-shrink:0;}}
.smsp{{border:none;border-top:1px solid {C["border"]};margin:4px 0;}}
.smhd{{padding:8px 18px 4px;font-size:0.68rem;color:{C["text_muted"]};
    font-weight:600;letter-spacing:1px;}}
.smred{{color:#f55!important}}
`;
pd.head.appendChild(s);

// + button
var btn=pd.createElement('button');
btn.id='spbtn';btn.textContent='+';pd.body.appendChild(btn);

// Menu
var m=pd.createElement('div');m.id='spmenu';
m.innerHTML=`
<a class="smi" id="smi-new"><span class="smico">✎</span>Obrolan baru</a>
<button class="smi" id="smi-hist"><span class="smico">☰</span>Riwayat obrolan</button>
<div class="smsp"></div>
<div class="smhd">PENAMPILAN</div>
<a class="smi" id="smi-dark"><span class="smico">🌙</span>Mode Gelap {'✓' if st.session_state.theme=='dark' else ''}</a>
<a class="smi" id="smi-light"><span class="smico">☀️</span>Mode Terang {'✓' if st.session_state.theme=='light' else ''}</a>
<div class="smsp"></div>
<a class="smi smred" id="smi-out"><span class="smico">🚪</span>Keluar</a>
`;
pd.body.appendChild(m);

// Nav function
function nav(params){{
    var u=new URL(window.parent.location.href);
    Object.keys(params).forEach(function(k){{u.searchParams.set(k,params[k])}});
    window.parent.location.href=u.toString();
}}

// History drawer
var h=pd.createElement('div');h.id='sphist';
h.innerHTML='<div class="smhd">RIWAYAT OBROLAN</div>';
{_hist_items}
pd.body.appendChild(h);

btn.onclick=function(e){{e.stopPropagation();m.style.display=m.style.display==='block'?'none':'block';h.style.display='none';}};

// Set href langsung pada menu items
(function(){{
    var u;
    u=new URL(window.parent.location.href); u.searchParams.set('do','newchat');
    pd.getElementById('smi-new').href=u.toString();
    pd.getElementById('smi-new').style.textDecoration='none';
    
    pd.getElementById('smi-hist').onclick=function(){{m.style.display='none';h.style.display=h.style.display==='block'?'none':'block';}};
    
    u=new URL(window.parent.location.href); u.searchParams.set('do','theme_dark');
    pd.getElementById('smi-dark').href=u.toString();
    pd.getElementById('smi-dark').style.textDecoration='none';
    
    u=new URL(window.parent.location.href); u.searchParams.set('do','theme_light');
    pd.getElementById('smi-light').href=u.toString();
    pd.getElementById('smi-light').style.textDecoration='none';
    
    u=new URL(window.parent.location.href); u.searchParams.delete('sigma_token'); u.searchParams.set('do','logout');
    pd.getElementById('smi-out').href=u.toString();
    pd.getElementById('smi-out').style.textDecoration='none';
}})();

pd.addEventListener('click',function(e){{
    if(!btn.contains(e.target)&&!m.contains(e.target))m.style.display='none';
    if(!btn.contains(e.target)&&!h.contains(e.target)&&!m.contains(e.target))h.style.display='none';
}});
}})();
</script>
""", height=0)

# Handle actions
if "do" in st.query_params:
    _do = st.query_params.get("do", "")
    _tok = st.query_params.get("sigma_token", st.session_state.get("current_token", ""))
    if _do == "logout":
        if _tok:
            try: os.remove(os.path.join(DATA_DIR, f"token_{_tok}.json"))
            except: pass
        st.session_state.clear(); st.query_params.clear(); st.rerun()
    elif _do == "theme_dark":
        st.session_state.theme = "dark"
        st.query_params["do"] = ""; st.rerun()
    elif _do == "theme_light":
        st.session_state.theme = "light"
        st.query_params["do"] = ""; st.rerun()
    elif _do == "newchat":
        ns = new_session()
        st.session_state.sessions.insert(0, ns)
        st.session_state.active_id = ns["id"]
        st.query_params["do"] = ""; st.rerun()
    elif _do.startswith("sel_"):
        _sid = _do[4:]
        st.session_state.active_id = _sid
        st.query_params["do"] = ""; st.rerun()

# ─────────────────────────────────────────────
# MAIN CHAT
# ─────────────────────────────────────────────
active = get_active()

# Build history JS untuk drawer — inject items tanpa st.button
_hist_items = ""
for sesi in st.session_state.sessions:
    sid = sesi["id"]
    is_active = sid == st.session_state.active_id
    title_d = sesi["title"][:35].replace("'", "\\'").replace("`","")
    fw = "600" if is_active else "400"
    bg = C['hover'] if is_active else "transparent"
    _hist_items += f"""
    (function() {{
        var hi = document.createElement('button');
        hi.textContent = '{title_d}';
        hi.dataset.sid = '{sid}';
        hi.style.cssText = 'display:block;width:100%;padding:11px 16px;font-size:0.95rem;color:{C["text"]};background:{bg};font-weight:{fw};border:none;text-align:left;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
        hi.onmouseenter = function(){{this.style.background='{C["hover"]}'}};
        hi.onmouseleave = function(){{this.style.background='{bg}'}};
        hi.onclick = function(){{
            var url = new URL(window.parent.location.href);
            url.searchParams.set('do', 'sel_{sid}');
            window.parent.location.href = url.toString();
        }};
        drawer.appendChild(hi);
    }})();
"""

# Header
if not active["messages"][1:]:
    uname = user.get("name", "").split()[0] if user.get("name") else "Trader"
    st.markdown(f"""
    <div style="text-align:center;padding:10vh 0 2rem;">
        <h1 style="margin:0;font-size:1.8rem;font-weight:700;color:{C['text']};">Halo, {uname} 👋</h1>
        <p style="margin:8px 0 0;color:{C['text_muted']};font-size:0.9rem;">Ada yang bisa SIGMA bantu analisa hari ini?</p>
    </div>
    """, unsafe_allow_html=True)

# Tampilkan error terakhir
if st.session_state.get("last_error"):
    st.error(f"⚠️ Error: {st.session_state['last_error']}")
    st.session_state["last_error"] = None

# Chat history
for i, msg in enumerate(active["messages"][1:]):
    with st.chat_message(msg["role"]):
        display = msg.get("display") or msg["content"]
        if "Pertanyaan:" in display:
            display = display.split("Pertanyaan:")[-1].strip()
        if "[DATA PASAR IDX]" in display or "[DATA GLOBAL]" in display:
            # Ambil hanya teks setelah semua tag data
            for tag in ["[/DATA GLOBAL]", "[/DATA PASAR IDX]", "[/DATA PASAR]"]:
                if tag in display:
                    display = display.split(tag)[-1].strip()
        if "[DATA PASAR]" in display:
            display = display.split("[/DATA PASAR]")[-1].strip()
        if msg["role"] == "user" and msg.get("img_b64"):
            st.markdown(f'<img src="data:{msg.get("img_mime","image/jpeg")};base64,{msg["img_b64"]}" style="max-width:100%;max-height:240px;border-radius:10px;margin-bottom:6px;display:block;">', unsafe_allow_html=True)
        st.markdown(display)

# Chat input
try:
    result = st.chat_input(
        "Tanya SIGMA... DYOR - bukan financial advice.",
        accept_file="multiple",
        file_type=["pdf", "png", "jpg", "jpeg"]
    )
except TypeError:
    result = st.chat_input("Tanya SIGMA...")

prompt = None
file_obj = None

if result is not None:
    if hasattr(result, 'text'):
        prompt = (result.text or "").strip()
        files = getattr(result, 'files', None) or []
        if files: file_obj = files[0]
    elif isinstance(result, str):
        prompt = result.strip()

    if file_obj:
        raw = file_obj.read()
        if file_obj.type == "application/pdf":
            doc = fitz.open(stream=raw, filetype="pdf")
            txt = "".join(p.get_text() for p in doc)
            # Enrichment: tambah data live untuk melengkapi PDF
            enrichment = ""
            try:
                enrichment = enrich_pdf_context(txt)
            except: pass
            pdf_content = f"[PDF: {file_obj.name}]\n{txt[:2000]}"
            if enrichment:
                pdf_content += enrichment
            st.session_state.pdf_data = (pdf_content, file_obj.name)
            st.session_state.img_data = None
        else:
            b64 = base64.b64encode(raw).decode()
            mime = "image/png" if file_obj.name.endswith(".png") else "image/jpeg"
            st.session_state.img_data = (b64, mime, file_obj.name)
            st.session_state.pdf_data = None

    if not prompt and (file_obj or st.session_state.img_data or st.session_state.pdf_data):
        prompt = "Tolong analisa file yang saya kirim"

if prompt:
    img_data = st.session_state.img_data
    pdf_data = st.session_state.pdf_data
    st.session_state.img_data = None
    st.session_state.pdf_data = None

    full_prompt = prompt
    if img_data:
        full_prompt = f"[Gambar: {img_data[2]}]\n\nPertanyaan: {prompt}"
    elif pdf_data:
        full_prompt = f"{pdf_data[0]}\n\nPertanyaan: {prompt}"
    else:
        _p = prompt.lower()
        _is_fund_cmd = any(k in _p for k in ["fundamental","valuasi","laporan keuangan",
                                               "keuangan","roe","roa","per ","pbv","analisa saham"])
        _ticker_found = detect_ticker_from_prompt(prompt)

        if _is_fund_cmd and _ticker_found:
            # Perintah fundamental tanpa PDF — fetch data lengkap
            fund_data = ""
            try:
                fund_data = build_fundamental_from_text(prompt)
            except Exception as _fe:
                fund_data = f"[Data fetch error: {_fe}] Gunakan knowledge model untuk {_ticker_found}."
            # Ekstrak harga dari fund_data jika ada
            _harga_line = ""
            for _l in fund_data.split("\n"):
                if "Harga Saham Saat Ini" in _l or "Harga Saham" in _l:
                    _harga_line = _l.strip()
                    break
            full_prompt = (
                f"{fund_data}\n\n"
                f"Perintah: Buat ANALISA FUNDAMENTAL lengkap untuk {_ticker_found}.\n"
                f"FORMAT OUTPUT WAJIB dimulai tepat seperti ini:\n"
                f"📋 ANALISA FUNDAMENTAL — {_ticker_found} (2026)\n"
                f"{_harga_line if _harga_line else '💹 Harga: (dari data di atas)'}\n"
                f"🏦 Sektor: ...\n"
                f"Kemudian lanjutkan dengan semua seksi.\n"
                f"Icon status: pilih SATU — ✅ pass, ⚠️ perhatian, ❌ fail. JANGAN [✅/⚠️/❌].\n"
                f"VERDICT harus minimal 4-5 kalimat: kondisi bisnis, tren, valuasi, risiko utama, saran konkret."
            )
            st.session_state["fund_no_history"] = True
        else:
            try:
                ctx = build_combined_context(prompt)
                if ctx:
                    full_prompt = f"{ctx}\n\n{prompt}"
            except: pass

    if active["title"] == "Obrolan Baru":
        active["title"] = prompt[:40] + ("..." if len(prompt) > 40 else "")

    # Simpan gambar di dalam message agar tetap ada setelah refresh
    user_msg = {"role": "user", "content": full_prompt, "display": prompt}
    if img_data:
        user_msg["img_b64"] = img_data[0]
        user_msg["img_mime"] = img_data[1]
        # Juga simpan di session_state untuk render langsung
        thumb_idx = len(active["messages"]) - 1
        st.session_state[f"thumb_{active['id']}_{thumb_idx}"] = (img_data[0], img_data[1])

    active["messages"].append(user_msg)
    with st.chat_message("user"):
        if img_data:
            st.markdown(f'<img src="data:{img_data[1]};base64,{img_data[0]}" style="max-width:100%;max-height:240px;border-radius:10px;margin-bottom:6px;display:block;">', unsafe_allow_html=True)
        st.markdown(prompt)

    try:
        groq_client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        with st.chat_message("assistant"):
            with st.spinner("SIGMA menganalisis..."):
                if img_data:
                    # Coba Groq vision dulu, fallback ke Gemini vision
                    _img_ans = None
                    try:
                        _img_res = groq_client.chat.completions.create(
                            model="meta-llama/llama-4-scout-17b-16e-instruct",
                            messages=[
                                {"role": "system", "content": "Kamu SIGMA, analis chart. Analisa gambar langsung. Jawab Bahasa Indonesia."},
                                {"role": "user", "content": [
                                    {"type": "image_url", "image_url": {"url": f"data:{img_data[1]};base64,{img_data[0]}"}},
                                    {"type": "text", "text": prompt}
                                ]}
                            ],
                            max_tokens=2048
                        )
                        _img_ans = _img_res.choices[0].message.content
                    except Exception as _img_e:
                        if "rate_limit" in str(_img_e) or "429" in str(_img_e):
                            # Fallback ke Gemini untuk gambar
                            try:
                                import json as _j2, urllib.request as _ur
                                _gkey = st.secrets.get("GEMINI_KEY","AIzaSyApoyO1dTWFPJ7Z5fykbLTxM0GN3MsYV8o")
                                _gpayload = {
                                    "contents":[{"role":"user","parts":[
                                        {"inline_data":{"mime_type":img_data[1],"data":img_data[0]}},
                                        {"text": f"Kamu SIGMA analis chart KIPM. {prompt}. Jawab Bahasa Indonesia."}
                                    ]}],
                                    "generationConfig":{"temperature":0.7,"maxOutputTokens":2048}
                                }
                                _gurl = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={_gkey}"
                                _greq = _ur.Request(_gurl, data=_j2.dumps(_gpayload).encode(), headers={"Content-Type":"application/json"})
                                with _ur.urlopen(_greq, timeout=30) as _gr:
                                    _gdata = _j2.loads(_gr.read())
                                _img_ans = _gdata["candidates"][0]["content"]["parts"][0]["text"]
                            except: pass
                        if _img_ans is None:
                            raise _img_e
                    
                    class _FakeImgRes:
                        class _C:
                            class _M:
                                pass
                            message = _M()
                        choices = [_C()]
                    res = _FakeImgRes()
                    res.choices[0].message.content = _img_ans
                else:
                    _all_msgs = [
                        {"role": m["role"], "content": m.get("content") or ""}
                        for m in active["messages"]
                        if m.get("role") in ("user","assistant","system")
                    ]
                    _last_content = _all_msgs[-1]["content"] if _all_msgs else ""
                    _is_big = len(_last_content) > 2000
                    _no_history = st.session_state.pop("fund_no_history", False)

                    if _no_history or _is_big:
                        # Fundamental atau PDF — kirim hanya system + pesan terakhir
                        # Hindari konteks percakapan sebelumnya agar tidak ada "maaf"
                        _msgs = [
                            _all_msgs[0],  # system prompt
                            {"role": _all_msgs[-1]["role"],
                             "content": _last_content[:20000]}
                        ]
                    else:
                        # Chat biasa — kirim history normal (max 5 pesan terakhir)
                        _msgs = [_all_msgs[0]] + _all_msgs[-4:]

                    # Urutan: Groq 70b → Gemini → Groq 8b
                    ans = None

                    # Step 1: Groq 70b
                    try:
                        _res = groq_client.chat.completions.create(
                            model="llama-3.3-70b-versatile",
                            messages=_msgs,
                            temperature=0.7,
                            max_tokens=2048
                        )
                        ans = _res.choices[0].message.content
                    except Exception as _me:
                        if not ("rate_limit" in str(_me) or "429" in str(_me) or "quota" in str(_me).lower()):
                            raise _me

                    # Step 2: Gemini 2.0 Flash
                    if ans is None:
                        try:
                            ans = _call_gemini(_msgs)
                        except: pass

                    # Step 3: Groq 8b
                    if ans is None:
                        try:
                            _res = groq_client.chat.completions.create(
                                model="llama-3.1-8b-instant",
                                messages=_msgs,
                                temperature=0.7,
                                max_tokens=2048
                            )
                            ans = _res.choices[0].message.content
                        except: pass

                    if ans is None:
                        raise Exception("Semua model sedang sibuk — tunggu beberapa menit lalu coba lagi.")
                    
                    # Buat res object compatible
                    class _FakeRes:
                        class _Choice:
                            class _Msg:
                                content = ans
                            message = _Msg()
                        choices = [_Choice()]
                    res = _FakeRes()
                ans = res.choices[0].message.content
            st.markdown(ans)
        active["messages"].append({"role": "assistant", "content": ans})
    except Exception as e:
        st.session_state["last_error"] = str(e)
        st.error(f"⚠️ {str(e)}")

    st.rerun()

# ─────────────────────────────────────────────
# SAVE DATA
# ─────────────────────────────────────────────
if user:
    sessions_to_save = []
    for s in st.session_state.sessions:
        msgs = [dict(m) for m in s["messages"] if m["role"] != "system"]
        sessions_to_save.append({"id": s["id"], "title": s["title"], "created": s["created"], "messages": msgs})
    save_user(user["email"], {
        "theme": st.session_state.get("theme", "dark"),
        "sessions": sessions_to_save,
        "active_id": st.session_state.active_id,
    })

# Kirim token baru ke localStorage setelah login
_new_token = st.session_state.pop("new_token", None)
if _new_token:
    components.html(f"""
<script>
try {{ localStorage.setItem('sigma_token', '{_new_token}'); }} catch(e) {{}}
</script>
""", height=0)

# Auto-restore token saat refresh — baca localStorage lalu redirect
if st.session_state.user is None:
    components.html("""
<script>
(function() {
    try {
        var token = localStorage.getItem('sigma_token');
        if (token) {
            var url = window.parent.location.href.split('?')[0];
            window.parent.location.replace(url + '?sigma_token=' + token);
        }
    } catch(e) {}
})();
</script>
""", height=0)

# ─────────────────────────────────────────────
# JS: bubble kanan + paste gambar + mobile CSS
# ─────────────────────────────────────────────
components.html(f"""
<script>
const BC = "{C['bubble']}";
const BT = "#ffffff";

// ── Inject mobile CSS ke parent <head> — cara paling kuat ──
(function() {{
    var pd = window.parent.document;
    if (pd.getElementById('sigma-mobile-css')) return;
    var s = pd.createElement('style');
    s.id = 'sigma-mobile-css';
    s.textContent = `
        /* Base font konsisten */
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] li,
        [data-testid="stMarkdownContainer"] span,
        [data-testid="stMarkdownContainer"] div,
        [data-testid="stMarkdownContainer"] strong,
        [data-testid="stMarkdownContainer"] b,
        [data-testid="stMarkdownContainer"] em {{
            font-size: 1rem !important;
            line-height: 1.85 !important;
        }}

        @media (max-width: 768px) {{
            /* Konten full width rapat */
            [data-testid="stMainBlockContainer"] {{
                max-width: 100% !important;
                padding: 8px 12px 120px !important;
                margin: 0 !important;
            }}
            /* Semua teks AI besar dan nyaman */
            [data-testid="stMarkdownContainer"],
            [data-testid="stMarkdownContainer"] p,
            [data-testid="stMarkdownContainer"] li,
            [data-testid="stMarkdownContainer"] span,
            [data-testid="stMarkdownContainer"] div,
            [data-testid="stMarkdownContainer"] strong,
            [data-testid="stMarkdownContainer"] b,
            [data-testid="stMarkdownContainer"] em,
            [data-testid="stMarkdownContainer"] a {{
                font-size: 1.05rem !important;
                line-height: 1.9 !important;
            }}
            [data-testid="stMarkdownContainer"] h1 {{ font-size: 1.3rem !important; }}
            [data-testid="stMarkdownContainer"] h2 {{ font-size: 1.15rem !important; }}
            [data-testid="stMarkdownContainer"] h3 {{ font-size: 1.05rem !important; font-weight: 700 !important; }}

            /* List rapi */
            [data-testid="stMarkdownContainer"] ul,
            [data-testid="stMarkdownContainer"] ol {{
                padding-left: 18px !important;
                margin: 4px 0 !important;
            }}
            [data-testid="stMarkdownContainer"] li {{
                margin-bottom: 6px !important;
            }}

            /* Jarak antar chat */
            [data-testid="stChatMessage"] {{
                padding: 10px 0 !important;
            }}

            /* Chat input */
            div[data-testid="stChatInputContainer"] {{
                border-radius: 26px !important;
                margin: 0 4px 8px !important;
            }}
            [data-testid="stChatInput"] textarea {{
                font-size: 16px !important;
                line-height: 1.5 !important;
            }}

            /* Bubble */
            .navy-pill {{
                max-width: 82% !important;
                font-size: 1.05rem !important;
                line-height: 1.75 !important;
                padding: 12px 16px !important;
            }}

            /* Code */
            [data-testid="stMarkdownContainer"] code {{
                font-size: 0.88rem !important;
            }}
            [data-testid="stMarkdownContainer"] pre {{
                font-size: 0.85rem !important;
                overflow-x: auto !important;
                padding: 12px !important;
            }}
        }}
    `;
    pd.head.appendChild(s);
}})();

function fixBubbles() {{
    const doc = window.parent.document;
    doc.querySelectorAll('[data-testid="stChatMessage"]').forEach(msg => {{
        if (!msg.querySelector('[data-testid="stChatMessageAvatarUser"]')) return;
        msg.style.cssText += 'display:flex!important;justify-content:flex-end!important;background:transparent!important;border:none!important;box-shadow:none!important;padding:4px 0!important;';
        const av = msg.querySelector('[data-testid="stChatMessageAvatarUser"]');
        if (av) av.style.display = 'none';
        const ct = msg.querySelector('[data-testid="stChatMessageContent"]');
        if (ct) ct.style.cssText += 'background:transparent!important;display:flex!important;justify-content:flex-end!important;max-width:100%!important;padding:0!important;';
        msg.querySelectorAll('[data-testid="stMarkdownContainer"]').forEach(md => {{
            md.style.background = 'transparent';
            md.style.display = 'flex';
            md.style.justifyContent = 'flex-end';
            if (!md.querySelector('.navy-pill')) {{
                const pill = document.createElement('div');
                pill.className = 'navy-pill';
                var mob=window.parent.innerWidth<=768;
                pill.style.cssText=`background:linear-gradient(135deg,#42a8e0,#1a4fad);color:#ffffff;border-radius:18px 18px 4px 18px;padding:${{mob?"12px 16px":"10px 16px"}};max-width:${{mob?"85%":"72%"}};display:inline-block;font-size:${{mob?"1rem":"0.9rem"}};line-height:1.7;word-wrap:break-word;`;
                while (md.firstChild) pill.appendChild(md.firstChild);
                md.appendChild(pill);
            }}
            // Force putih semua elemen dalam bubble
            var pill = md.querySelector('.navy-pill');
            if (pill) {{
                pill.style.setProperty('color','#ffffff','important');
                pill.style.setProperty('background','linear-gradient(135deg,#42a8e0,#1a4fad)','important');
                pill.querySelectorAll('*').forEach(function(el){{
                    el.style.setProperty('color','#ffffff','important');
                }});
            }}
        }});
    }});
}}

fixBubbles();
setInterval(fixBubbles, 800);
new MutationObserver(() => setTimeout(fixBubbles, 100)).observe(
    window.parent.document.body, {{childList:true,subtree:true}}
);

// ── Tombol aksi di bawah bubble & pesan AI ──
function addActionButtons() {{
    var doc = window.parent.document;
    doc.querySelectorAll('[data-testid="stChatMessage"]').forEach(function(msg) {{
        if (msg.querySelector('.sigma-actions')) return;
        if (!!msg.querySelector('[data-testid="stChatMessageAvatarUser"]')) return;
        function getMsgText() {{
            var md = msg.querySelector('[data-testid="stMarkdownContainer"]');
            return md ? md.innerText : '';
        }}
        var bar = doc.createElement('div');
        bar.className = 'sigma-actions';
        bar.style.cssText = 'display:flex;gap:2px;margin-top:6px;padding:0 2px;';
        var copyBtn = doc.createElement('button');
        copyBtn.title = 'Salin';
        copyBtn.innerHTML = '<svg width=\"16\" height=\"16\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#8e8ea0\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"9\" y=\"9\" width=\"13\" height=\"13\" rx=\"2\"></rect><path d=\"M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1\"></path></svg>';
        copyBtn.style.cssText = 'background:transparent;border:none;cursor:pointer;padding:5px 6px;border-radius:6px;display:flex;align-items:center;';
        copyBtn.onmouseenter=function(){{this.style.background='rgba(255,255,255,0.08)'}};
        copyBtn.onmouseleave=function(){{this.style.background='transparent'}};
        copyBtn.onclick = function() {{
            var txt = getMsgText();
            function showOk() {{
                copyBtn.innerHTML = '<svg width=\"16\" height=\"16\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#4CAF50\" stroke-width=\"2.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><polyline points=\"20 6 9 17 4 12\"></polyline></svg>';
                setTimeout(function(){{ copyBtn.innerHTML = '<svg width=\"16\" height=\"16\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#8e8ea0\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"9\" y=\"9\" width=\"13\" height=\"13\" rx=\"2\"></rect><path d=\"M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1\"></path></svg>'; }}, 2000);
            }}
            navigator.clipboard.writeText(txt).then(showOk).catch(function(){{
                var ta=doc.createElement('textarea'); ta.value=txt;
                doc.body.appendChild(ta); ta.select(); doc.execCommand('copy'); doc.body.removeChild(ta);
                showOk();
            }});
        }};
        bar.appendChild(copyBtn);
        msg.style.flexDirection='column';
        msg.appendChild(bar);
    }});
}}

setInterval(addActionButtons, 1000);

// Paste image support — lebih robust
function setupPaste() {{
    var pw = window.parent;

    // Hapus handler lama dulu
    if (pw._sigmaPasteHandler) {{
        pw.removeEventListener('paste', pw._sigmaPasteHandler, true);
        pw.document.removeEventListener('paste', pw._sigmaPasteHandler, true);
    }}

    function handlePaste(e) {{
        var items = e.clipboardData && e.clipboardData.items;
        if (!items) return;
        for (var i=0; i<items.length; i++) {{
            if (items[i].type.startsWith('image/')) {{
                var file = items[i].getAsFile();
                if (!file) continue;
                e.preventDefault();
                e.stopPropagation();
                var inputs = pw.document.querySelectorAll('input[type="file"]');
                for (var fi of inputs) {{
                    try {{
                        var dt = new DataTransfer();
                        dt.items.add(file);
                        Object.defineProperty(fi, 'files', {{value: dt.files, configurable:true, writable:true}});
                        fi.dispatchEvent(new Event('change', {{bubbles:true}}));
                        fi.dispatchEvent(new Event('input', {{bubbles:true}}));
                        var ta = pw.document.querySelector('[data-testid="stChatInput"] textarea');
                        if (ta) {{
                            ta.style.outline = '2px solid #4a90d9';
                            ta.placeholder = '📎 Gambar siap — ketik pertanyaan lalu Enter';
                            setTimeout(function(){{
                                ta.style.outline='';
                                ta.placeholder='Tanya SIGMA... DYOR - bukan financial advice.';
                            }}, 3000);
                            ta.focus();
                        }}
                        break;
                    }} catch(err) {{ console.log('paste err',err); }}
                }}
                break;
            }}
        }}
    }}

    pw._sigmaPasteHandler = handlePaste;
    pw.addEventListener('paste', handlePaste, true);
    pw.document.addEventListener('paste', handlePaste, true);
}}
setupPaste();
setTimeout(setupPaste, 1000);
setTimeout(setupPaste, 3000);

// ── Drag & Drop file (PDF/gambar) ke area chat ──
function setupDragDrop() {{
    var pw = window.parent;
    var pd = pw.document;
    if (pw._sigmaDragOK) return;

    // Overlay saat drag
    var overlay = pd.createElement('div');
    overlay.id = 'sigma-drop-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(27,42,74,0.55);z-index:99997;display:none;align-items:center;justify-content:center;pointer-events:none;';
    overlay.innerHTML = '<div style="background:#1B2A4A;color:#fff;border:2px dashed #4a90d9;border-radius:16px;padding:32px 48px;font-size:1.1rem;text-align:center;">📂 Lepaskan file di sini<br><span style="font-size:0.85rem;opacity:0.7;">PDF, PNG, JPG</span></div>';
    pd.body.appendChild(overlay);

    var dragCount = 0;

    pd.addEventListener('dragenter', function(e) {{
        e.preventDefault();
        dragCount++;
        overlay.style.display = 'flex';
    }}, true);

    pd.addEventListener('dragleave', function(e) {{
        dragCount--;
        if (dragCount <= 0) {{ dragCount = 0; overlay.style.display = 'none'; }}
    }}, true);

    pd.addEventListener('dragover', function(e) {{
        e.preventDefault();
    }}, true);

    pd.addEventListener('drop', function(e) {{
        e.preventDefault();
        dragCount = 0;
        overlay.style.display = 'none';

        var files = e.dataTransfer && e.dataTransfer.files;
        if (!files || files.length === 0) return;

        var file = files[0];
        var allowed = ['application/pdf','image/png','image/jpeg','image/jpg'];
        if (!allowed.includes(file.type)) {{
            alert('File tidak didukung. Gunakan PDF, PNG, atau JPG.');
            return;
        }}

        // Inject ke file input Streamlit
        var inputs = pd.querySelectorAll('input[type="file"]');
        for (var fi of inputs) {{
            try {{
                var dt = new DataTransfer();
                dt.items.add(file);
                Object.defineProperty(fi, 'files', {{value: dt.files, configurable:true, writable:true}});
                fi.dispatchEvent(new Event('change', {{bubbles:true}}));
                fi.dispatchEvent(new Event('input', {{bubbles:true}}));
                var ta = pd.querySelector('[data-testid="stChatInput"] textarea');
                if (ta) {{
                    ta.style.outline = '2px solid #4a90d9';
                    var fname = file.name;
                    ta.placeholder = '📎 ' + fname + ' siap — ketik pertanyaan lalu Enter';
                    setTimeout(function(){{
                        ta.style.outline = '';
                        ta.placeholder = 'Tanya SIGMA... DYOR - bukan financial advice.';
                    }}, 3000);
                    ta.focus();
                }}
                break;
            }} catch(err) {{ console.log('drop err', err); }}
        }}
    }}, true);

    pw._sigmaDragOK = true;
}}
setupDragDrop();
setTimeout(setupDragDrop, 2000);
</script>
""", height=0)
