# ─────────────────────────────────────────────
# PART 1: IMPORTS & BASIC FETCHERS
# ─────────────────────────────────────────────
import streamlit as st
from groq import Groq
import google.generativeai as genai
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

# ─── MULTI-SOURCE DATA (yfinance → stooq → IDX API) ───
def _fetch_all_data(tickers):
    import threading
    result = {"prices": {}, "news": []}

    def fetch():
        # Layer 1: IDX API — sumber PALING AKURAT, langsung dari bursa
        for tk in tickers[:3]:
            try:
                import urllib.request, json as _j
                req = urllib.request.Request(
                    f"https://www.idx.co.id/umbraco/Surface/StockData/GetTradingInfoSS?code={tk}",
                    headers={"User-Agent":"Mozilla/5.0","Referer":"https://www.idx.co.id/"}
                )
                with urllib.request.urlopen(req, timeout=5) as r:
                    d = _j.loads(r.read())
                if d and d.get("LastPrice") and d["LastPrice"] > 0:
                    result["prices"][tk] = {
                        "price": d["LastPrice"],
                        "chg": d.get("ChangePercentage", 0),
                        "open": d.get("OpenPrice", 0),
                        "high": d.get("HighPrice", 0),
                        "low": d.get("LowPrice", 0),
                        "vol": d.get("Volume", 0),
                        "source": "IDX"
                    }
            except: pass

        # Layer 2: Finnhub — reliable, adjusted
        try:
            import urllib.request as _ufh, json as _jfh
            _fh_key = st.secrets.get("FINNHUB_KEY", "")
            if _fh_key:
                for tk in tickers[:3]:
                    if tk not in result["prices"]:
                        try:
                            _fh_url = f"https://finnhub.io/api/v1/quote?symbol={tk}.JK&token={_fh_key}"
                            _fh_req = _ufh.Request(_fh_url, headers={"User-Agent":"Mozilla/5.0"})
                            with _ufh.urlopen(_fh_req, timeout=5) as r:
                                _fh_d = _jfh.loads(r.read())
                            _fh_price = _fh_d.get("c", 0)  # current price
                            _fh_prev  = _fh_d.get("pc", 0) # previous close
                            if _fh_price and _fh_price > 0:
                                _fh_chg = ((_fh_price - _fh_prev) / _fh_prev * 100) if _fh_prev else 0
                                result["prices"][tk] = {
                                    "price": round(_fh_price, 0),
                                    "chg": round(_fh_chg, 2),
                                    "high": _fh_d.get("h", 0),
                                    "low": _fh_d.get("l", 0),
                                    "source": "Finnhub"
                                }
                        except: pass
        except: pass

        # Layer 3: FMP — financial data provider
        try:
            import urllib.request as _ufmp, json as _jfmp
            _fmp_key = st.secrets.get("FMP_KEY", "")
            if _fmp_key:
                for tk in tickers[:3]:
                    if tk not in result["prices"]:
                        try:
                            _fmp_url = f"https://financialmodelingprep.com/api/v3/quote/{tk}.JK?apikey={_fmp_key}"
                            _fmp_req = _ufmp.Request(_fmp_url, headers={"User-Agent":"Mozilla/5.0"})
                            with _ufmp.urlopen(_fmp_req, timeout=5) as r:
                                _fmp_d = _jfmp.loads(r.read())
                            if _fmp_d and isinstance(_fmp_d, list) and _fmp_d[0].get("price"):
                                _fmp_q = _fmp_d[0]
                                result["prices"][tk] = {
                                    "price": round(_fmp_q["price"], 0),
                                    "chg": round(_fmp_q.get("changesPercentage", 0), 2),
                                    "high": _fmp_q.get("dayHigh", 0),
                                    "low": _fmp_q.get("dayLow", 0),
                                    "vol": _fmp_q.get("volume", 0),
                                    "source": "FMP"
                                }
                        except: pass
        except: pass

        # Layer 4: Yahoo Finance query API — realtime, adjusted
        for tk in tickers[:3]:
            if tk not in result["prices"]:
                try:
                    import urllib.request, json as _j
                    _url = f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}.JK?interval=1d&range=5d"
                    _req = urllib.request.Request(_url, headers={"User-Agent":"Mozilla/5.0"})
                    with urllib.request.urlopen(_req, timeout=5) as r:
                        _d = _j.loads(r.read())
                    _meta = _d["chart"]["result"][0]["meta"]
                    _price = _meta.get("regularMarketPrice") or _meta.get("previousClose")
                    _prev  = _meta.get("previousClose", _price)
                    if _price and _price > 0:
                        _chg = ((_price - _prev) / _prev * 100) if _prev else 0
                        result["prices"][tk] = {
                            "price": round(_price, 0),
                            "chg": round(_chg, 2),
                            "high": _meta.get("regularMarketDayHigh", 0),
                            "low": _meta.get("regularMarketDayLow", 0),
                            "vol": _meta.get("regularMarketVolume", 0),
                            "source": "Yahoo"
                        }
                except: pass

        # Layer 5: yfinance — backup dengan auto_adjust + averageVolume
        try:
            import yfinance as yf
            for tk in tickers[:3]:
                try:
                    t = yf.Ticker(f"{tk}.JK")
                    info = t.info
                    # Selalu ambil averageVolume meski harga sudah ada dari layer sebelumnya
                    avg_vol = info.get("averageVolume") or info.get("averageDailyVolume10Day")
                    avg_vol3m = info.get("averageVolume3Month") or info.get("averageVolume")
                    if avg_vol and tk in result["prices"]:
                        result["prices"][tk]["avg_vol"] = avg_vol
                        result["prices"][tk]["avg_vol_src"] = "yfinance(3M)"
                    if avg_vol3m and tk in result["prices"] and not result["prices"][tk].get("avg_vol"):
                        result["prices"][tk]["avg_vol"] = avg_vol3m
                    # Kalau belum ada harga sama sekali, pakai yfinance
                    if tk not in result["prices"]:
                        h = t.history(period="5d", auto_adjust=True)
                        if not h.empty:
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
                                "avg_vol": avg_vol,
                                "avg_vol_src": "yfinance(3M)",
                                "source": "yfinance"
                            }
                except: pass
        except: pass

        # Layer 6: stooq — backup terakhir
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



# ─────────────────────────────────────────────
# PART 2: FUNDAMENTAL APIs
# ─────────────────────────────────────────────
def _fetch_finnhub(ticker, api_key=None):
    """Fetch fundamental data dari Finnhub."""
    api_key = api_key or st.secrets.get("FINNHUB_KEY", "")
    try:
        import urllib.request, json as _j
        url = f"https://finnhub.io/api/v1/stock/metric?symbol={ticker}.JK&metric=all&token={api_key}"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = _j.loads(r.read())
        metrics = data.get("metric", {})
        result = {}
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
    """Fetch fundamental data dari Alpha Vantage."""
    api_key = api_key or st.secrets.get("ALPHAVANTAGE_KEY", "")
    try:
        import urllib.request, json as _j
        result = {}
        url = f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={ticker}.JK&apikey={api_key}"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = _j.loads(r.read())
        if data and "Symbol" in data:
            if data.get("PERatio") and data["PERatio"] != "None": result["pe"] = float(data["PERatio"])
            if data.get("PriceToBookRatio") and data["PriceToBookRatio"] != "None": result["pbv"] = float(data["PriceToBookRatio"])
            if data.get("EPS") and data["EPS"] != "None": result["eps"] = float(data["EPS"])
            if data.get("ReturnOnEquityTTM") and data["ReturnOnEquityTTM"] != "None": result["roe"] = float(data["ReturnOnEquityTTM"])
            if data.get("ReturnOnAssetsTTM") and data["ReturnOnAssetsTTM"] != "None": result["roa"] = float(data["ReturnOnAssetsTTM"])
            if data.get("DividendYield") and data["DividendYield"] != "None": result["div_yield"] = float(data["DividendYield"])
            if data.get("MarketCapitalization") and data["MarketCapitalization"] != "None": result["mktcap"] = float(data["MarketCapitalization"])
            if data.get("52WeekHigh") and data["52WeekHigh"] != "None": result["w52h"] = float(data["52WeekHigh"])
            if data.get("52WeekLow") and data["52WeekLow"] != "None": result["w52l"] = float(data["52WeekLow"])
            if data.get("Description"): result["description"] = data["Description"][:200]
        return result
    except:
        return {}

def _fetch_fmp(ticker, api_key=None):
    """Fetch fundamental dari Financial Modeling Prep."""
    api_key = api_key or st.secrets.get("FMP_KEY", "")
    try:
        import urllib.request, json as _j
        result = {}
        base = "https://financialmodelingprep.com/api/v3"

        try:
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
        except: pass

        try:
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
        except: pass

        try:
            url3 = f"{base}/income-statement/{ticker}.JK?limit=4&apikey={api_key}"
            req3 = urllib.request.Request(url3, headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req3, timeout=5) as r3:
                data3 = _j.loads(r3.read())
            if data3 and isinstance(data3, list):
                hist_ni, hist_eps, hist_rev = [], [], []
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
        except: pass

        if result: result["source"] = "FMP"
        return result
    except:
        return {}

# PENGAMAN LIMIT API: Menyimpan memori selama 1 jam (3600 detik)
@st.cache_data(ttl=3600)
def _fetch_multi_fundamental(ticker):
    """Fetch fundamental berlapis — saling melengkapi."""
    import threading
    result = [{}]
    def fetch():
        combined = {}
        try:
            import urllib.request, json as _j
            req = urllib.request.Request(
                f"https://www.idx.co.id/umbraco/Surface/StockData/GetTradingInfoSS?code={ticker}",
                headers={"User-Agent":"Mozilla/5.0","Referer":"https://www.idx.co.id/"}
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                d = _j.loads(r.read())
            if d and d.get("LastPrice") and d["LastPrice"] > 0:
                combined["price"] = d["LastPrice"]
                combined["source_price"] = "IDX (real-time)"
        except: pass

        try:
            fmp = _fetch_fmp(ticker)
            for k, v in fmp.items():
                if v is not None: combined[k] = v
            if fmp: combined["source_fundamental"] = "FMP"
        except: pass

        try:
            fh = _fetch_finnhub(ticker)
            for k, v in fh.items():
                if k not in combined or combined[k] is None: combined[k] = v
            if fh and "source_fundamental" not in combined: combined["source_fundamental"] = "Finnhub"
        except: pass

        try:
            av = _fetch_alphavantage(ticker)
            for k, v in av.items():
                if k not in combined or combined[k] is None: combined[k] = v
            if av and "source_fundamental" not in combined: combined["source_fundamental"] = "AlphaVantage"
        except: pass

        try:
            import yfinance as yf
            t = yf.Ticker(f"{ticker}.JK")
            info = t.info
            hist = t.history(period="5d", auto_adjust=True)
            if not combined.get("price") and not hist.empty:
                combined["price"] = round(hist.iloc[-1]["Close"], 0)
                combined["source_price"] = "yfinance (adjusted)"
            for k, v in {
                "pe": info.get("trailingPE"), "pbv": info.get("priceToBook"),
                "eps": info.get("trailingEps"), "bv": info.get("bookValue"),
                "roe": info.get("returnOnEquity"), "roa": info.get("returnOnAssets"),
                "div_yield": info.get("dividendYield"), "mktcap": info.get("marketCap"),
                "w52h": info.get("fiftyTwoWeekHigh"), "w52l": info.get("fiftyTwoWeekLow"),
                "shares": info.get("sharesOutstanding"),
            }.items():
                if v is not None and k not in combined: combined[k] = v
        except: pass

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


# ─────────────────────────────────────────────
# PART 3: GLOBAL DATA & CONTEXT BUILDERS
# ─────────────────────────────────────────────
def _fetch_commodities(api_key=None):
    try:
        import urllib.request, json as _j
        api_key = api_key or st.secrets.get("FMP_KEY", "")
        result = {}
        symbols = {
            "GCUSD": "Gold (Emas)", "SIUSD": "Silver (Perak)", "CLUSD": "WTI Crude Oil",
            "BZUSD": "Brent Crude Oil", "NGUSD": "Natural Gas", "HGUSD": "Copper (Tembaga)",
            "NZUSD": "Nickel", "ALUSD": "Aluminum (Aluminium)", "ZSUSD": "Soybeans (Kedelai)", "KCUSD": "Coffee (Kopi)"
        }
        syms = ",".join(symbols.keys())
        url = f"https://financialmodelingprep.com/api/v3/quote/{syms}?apikey={api_key}"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r: data = _j.loads(r.read())
        if data and isinstance(data, list):
            for item in data:
                sym = item.get("symbol","")
                if sym in symbols:
                    result[symbols[sym]] = {"price": item.get("price"), "chg": item.get("changesPercentage"), "symbol": sym}
        return result
    except: return {}

def _fetch_us_china_stock(ticker, market="US"):
    try:
        import yfinance as yf, threading
        result = [{}]
        def fetch():
            try:
                if market == "HK": yf_ticker = f"{ticker}.HK"
                elif market == "CN_SH": yf_ticker = f"{ticker}.SS"
                elif market == "CN_SZ": yf_ticker = f"{ticker}.SZ"
                else: yf_ticker = ticker
                t = yf.Ticker(yf_ticker)
                hist = t.history(period="5d", auto_adjust=True)
                info = t.info
                if not hist.empty:
                    last = hist.iloc[-1]
                    prev = hist.iloc[-2] if len(hist) > 1 else last
                    chg = ((last["Close"]-prev["Close"])/prev["Close"]*100) if prev["Close"] else 0
                    result[0] = {
                        "price": round(last["Close"], 2), "chg": round(chg, 2), "pe": info.get("trailingPE"),
                        "pbv": info.get("priceToBook"), "eps": info.get("trailingEps"), "mktcap": info.get("marketCap"),
                        "name": info.get("longName",""), "sector": info.get("sector",""), "currency": info.get("currency","USD")
                    }
            except: pass
        th = threading.Thread(target=fetch, daemon=True)
        th.start()
        th.join(timeout=8)
        return result[0]
    except: return {}

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
                        if count >= max_per_source: break
                        title = entry.get("title","").strip()
                        if not title: continue
                        key = title[:30].lower()
                        if key in seen: continue
                        if kw and not any(k in title.lower() for k in kw): continue
                        seen.add(key)
                        news.append({"source": src_name, "title": title, "link": entry.get("link","")})
                        count += 1
                except: pass
            result[0] = news
        th = threading.Thread(target=fetch, daemon=True)
        th.start()
        th.join(timeout=12)
        return result[0]
    except: return []

def build_global_context(prompt):
    import threading
    _p = prompt.lower()
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
        "kesimpulan dampak","dampak","pengaruh","efek","imbas",
        "msci","ftse","rating","moody","fitch","s&p rating",
        "rupiah","ihsg","apbn","subsidi","bi rate","bank indonesia",
        "rebalancing","capital outflow","capital inflow",
        "risk on","risk off","bullish","bearish","accumulate",
    ]
    if not any(k in _p for k in global_kw): return ""

    result = [{}]
    def fetch():
        lines = [f"=== DATA GLOBAL ({datetime.now().strftime('%d %b %Y %H:%M WIB')}) ==="]
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

        import re as _re
        us_tickers = _re.findall(r' ([A-Z]{1,5}) ', prompt.upper())
        us_skip = {
            "THE","AND","FOR","IDX","BEI","USD","IDR","RSI","EMA","FVG","OB",
            "YANG","ATAU","DARI","PADA","UNTUK","SAYA","TOLONG","ANALISA",
            "SAHAM","MOHON","BISA","DENGAN","MINTA","APAKAH","BAGAIMANA",
            "KENAPA","COBA","IHSG","BURSA","PASAR","HARGA","ENTRY","BELI",
            "JUAL","WAIT","HOLD","RUPIAH","APBN","DAMPAK","PENGARUH","EFEK",
            "IMBAS","GLOBAL","BERITA","NEWS","PERANG","EKONOMI","INFLASI",
            "MAKRO","MIKRO","SEKTOR","EMITEN","DIVIDEN","VALUASI","TEKNIKAL",
            "IFVG","OBJ","SMA","ATR","MACD","VWAP","POC","VAH","VAL",
            "BI","FED","IMF","GDP","CPI","PDB","SBI","SUN","OJK","LPS",
        }
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

        prompt_words = [w for w in _p.split() if len(w) > 3]
        news = _fetch_global_news(keywords=prompt_words[:5], max_per_source=2)
        if not news: news = _fetch_global_news(max_per_source=1)
        if news:
            lines.append("\n── BERITA GLOBAL (terjemahkan ke Bahasa Indonesia) ──")
            for item in news[:8]: lines.append(f"[{item['source']}] {item['title']}")

        lines.extend([
            "\n=== INSTRUKSI ANALISA DAMPAK ===",
            "1. TERJEMAHKAN semua berita asing ke Bahasa Indonesia",
            "2. Analisa dampak ke RUPIAH: DXY naik→Rupiah melemah, komoditas naik→devisa masuk→Rupiah menguat",
            "3. Analisa dampak ke APBN: minyak naik→subsidi membengkak, komoditas ekspor naik→penerimaan naik",
            "4. Sebutkan 10 EMITEN IDX yang paling terdampak:",
            "   Coal naik→PTBA,ADRO,ITMG,HRUM | Nikel→INCO,ANTM,MDKA,NCKL | CPO→AALI,LSIP,SIMP",
            "   Minyak→PGAS,MEDC,ELSA | Emas→ANTM,MDKA,BRMS | Dollar kuat→eksportir untung,importir rugi",
            "   Rate naik→BBCA,BBRI,BMRI,BBNI | Rate turun→BSDE,CTRA,SMGR,WIKA",
            "5. Jika user tanya emiten di luar list→analisa berdasarkan sektor dan exposure komoditasnya",
            "⚠️ WAJIB: Terjemahkan SEMUA judul berita asing ke Bahasa Indonesia dalam output",
            "6. Analisa dampak ke INDEKS INDONESIA jika relevan:",
            "   IHSG (Composite) | LQ45 | IDX30 | IDX80 | KOMPAS100 | BISNIS27 | PEFINDO25",
            "   JII (Jakarta Islamic Index) | SMINFRA18 | IDXBUMN20 | IDXSMC-CAP",
            "7. Analisa dampak MSCI/FTSE/indeks global jika relevan:",
            "   MSCI rebalancing → saham masuk/keluar = capital inflow/outflow besar",
            "   MSCI naik bobot IDX → dana asing masuk → IHSG naik",
            "   FTSE Russell review → dampak ke likuiditas saham IDX",
            "   S&P500 turun → risk off global → IHSG ikut tertekan",
            "8. Lembaga rating dunia:",
            "   S&P / Moody's / Fitch upgrade Indonesia → obligasi naik, rupiah menguat, IHSG naik",
            "   Downgrade → capital outflow, rupiah melemah, IHSG turun",
            "   Rating saat ini: S&P BBB / Moody's Baa2 / Fitch BBB (investment grade)",
            "=== AKHIR DATA GLOBAL ==="
        ])
        result[0] = "\n".join(lines)
    th = threading.Thread(target=fetch, daemon=True)
    th.start()
    th.join(timeout=15)
    return result[0]


# ─────────────────────────────────────────────
# PART 4: LOCAL CONTEXT BUILDERS
# ─────────────────────────────────────────────

def fetch_fundamental_with_cache(ticker):
    """Fetch fundamental langsung — selalu fresh, tanpa cache."""
    data = _fetch_multi_fundamental(ticker)
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

    _is_fundamental = any(k in _p for k in [
        "fundamental","laporan","keuangan","valuasi","roe","roa","per ","pbv",
        "eps","nim","npl","car","ldr","bopo","cir","dividen","laba","revenue"
    ])

    data = _fetch_all_data(tickers)
    current_year = datetime.now().year
    lines = [f"Tanggal: {datetime.now().strftime('%d %B %Y %H:%M WIB')} | Tahun: {current_year}"]

    for tk, d in data["prices"].items():
        arah = "▲" if d["chg"]>=0 else "▼"
        line = f"{tk}: Rp{d['price']:,.0f} {arah}{abs(d['chg']):.2f}% [Sumber:{d.get('source','')}]"
        if d.get("pe"): line += f" PER:{d['pe']:.1f}x"
        if d.get("pbv"): line += f" PBV:{d['pbv']:.1f}x"
        if d.get("roe"): line += f" ROE:{d['roe']*100:.1f}%"
        if d.get("eps"): line += f" EPS:Rp{d['eps']:,.0f}"
        lines.append(line)
        vol_today = d.get("vol", 0)
        avg_vol = d.get("avg_vol", 0)
        if vol_today and vol_today > 0:
            lines.append(f"  Volume hari ini: {vol_today:,.0f} lot")
        if avg_vol and avg_vol > 0:
            lines.append(f"  Rata-rata volume: {avg_vol:,.0f} lot/hari [{d.get('avg_vol_src','yfinance')}]")
            if vol_today and vol_today > 0:
                ratio = vol_today / avg_vol
                if ratio >= 50: label = "🚨 SANGAT EKSTREM"
                elif ratio >= 10: label = "⚠️ ANOMALI KUAT"
                elif ratio >= 5: label = "⚠️ ANOMALI SIGNIFIKAN"
                elif ratio >= 2: label = "👀 MULAI PERHATIKAN"
                else: label = "✅ Normal"
                lines.append(f"  Ratio volume: {ratio:.1f}x normal → {label}")

    if _is_fundamental and tickers:
        for tk in tickers[:2]:
            try:
                fund = fetch_fundamental_with_cache(tk)
                if fund:
                    flines = [f"\n── DATA FUNDAMENTAL {tk} [{fund.get('source_fundamental','multi-source')}] ──"]
                    if fund.get("price"):
                        flines.append(f"Harga: Rp{fund['price']:,.0f} [Sumber:{fund.get('source_price','IDX')}]")
                    for label, key, fmt in [
                        ("ROE", "roe", lambda v: f"{v*100:.1f}%" if v<10 else f"{v:.1f}%"),
                        ("ROA", "roa", lambda v: f"{v*100:.1f}%" if v<10 else f"{v:.1f}%"),
                        ("NIM", "nim", lambda v: f"{v:.1f}%"),("NPL Gross", "npl_gross", lambda v: f"{v:.1f}%"),
                        ("NPL Net", "npl_net", lambda v: f"{v:.1f}%"),("LDR", "ldr", lambda v: f"{v:.1f}%"),
                        ("CAR", "car", lambda v: f"{v:.1f}%"),("BOPO", "bopo", lambda v: f"{v:.1f}%"),
                        ("PER", "pe", lambda v: f"{v:.1f}x"),("PBV", "pbv", lambda v: f"{v:.1f}x"),
                        ("EPS", "eps", lambda v: f"Rp{v:,.0f}"),("DER", "der", lambda v: f"{v:.2f}x"),
                        ("Div Yield", "div_yield", lambda v: f"{v*100:.1f}%" if v<1 else f"{v:.1f}%"),
                        ("Market Cap", "mktcap", lambda v: f"Rp{v/1e12:.1f}T"),
                        ("52W High", "w52h", lambda v: f"Rp{v:,.0f}"),("52W Low", "w52l", lambda v: f"Rp{v:,.0f}"),
                        ("Sektor", "sector", lambda v: str(v)),
                    ]:
                        val = fund.get(key)
                        if val is not None:
                            try: flines.append(f"{label}: {fmt(val)}")
                            except: flines.append(f"{label}: {val}")
                    if fund.get("hist_ni"): flines.append(f"Hist Laba Bersih: {fund['hist_ni']}")
                    if fund.get("hist_eps"): flines.append(f"Hist EPS: {fund['hist_eps']}")
                    if fund.get("hist_rev"): flines.append(f"Hist Revenue: {fund['hist_rev']}")
                    lines.extend(flines)
            except: pass

    if not _is_fundamental and data["news"]:
        lines.append("Berita terkini:")
        lines.extend(data["news"][:3])

    return "\n".join(lines) if len(lines)>1 else ""

def _calc_cagr(values_sorted_new_to_old):
    vals = [v for v in values_sorted_new_to_old if v and v > 0]
    if len(vals) < 2: return None
    n = len(vals) - 1
    try: return (vals[0] / vals[-1]) ** (1/n) - 1
    except: return None

def build_combined_context(prompt):
    import threading
    local_ctx = [""]; global_ctx = [""]
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
    ticker = detect_ticker_from_prompt(prompt)
    if not ticker: return ""
    import threading
    result = [""]
    
    def fetch():
        try:
            multi = fetch_fundamental_with_cache(ticker)
            current_year = datetime.now().year

            # Cari harga live yang valid
            price_live = multi.get("price")
            price_src = multi.get("source_price", "Unknown")
            
            if not price_live:
                try:
                    import urllib.request as _ur, json as _jj
                    _req = _ur.Request(f"https://www.idx.co.id/umbraco/Surface/StockData/GetTradingInfoSS?code={ticker}", headers={"User-Agent":"Mozilla/5.0"})
                    with _ur.urlopen(_req, timeout=3) as _r: _d = _jj.loads(_r.read())
                    if _d and _d.get("LastPrice"): price_live = _d["LastPrice"]; price_src = "IDX (real-time)"
                except: pass
            
            if not price_live:
                try:
                    import yfinance as yf
                    hist_price = yf.Ticker(f"{ticker}.JK").history(period="1d")
                    if not hist_price.empty: price_live = round(hist_price.iloc[-1]["Close"], 0); price_src = "yfinance"
                except: pass

            # Deteksi sektor
            is_bank = is_bank_sector(ticker)
            sektor = "Perbankan" if is_bank else "Non-Perbankan"
            framework = "Perbankan (NIM, NPL, LDR, dll)" if is_bank else "Buffett + Graham + Lynch"

            lines = [
                f"=== INSTRUKSI DARURAT (WAJIB DIBACA AI) ===",
                f"Jika metrik di bawah ada yang kosong/N/A, KAMU DILARANG MENOLAK MENJAWAB.",
                f"KAMU WAJIB menggunakan knowledge internal kamu tentang {ticker} untuk mengisi kekosongan tersebut.",
                f"Selalu utamakan data paling aktual (TTM/{current_year}). JANGAN pakai data usang.",
                f"Jika rasio valuasi kosong, WAJIB HITUNG MANUAL: PER = Harga ÷ EPS. PBV = Harga ÷ BV.",
                f"==========================================\n",
                f"=== DATA FUNDAMENTAL {ticker} ({sektor}) ===",
                f"Sektor: {sektor} | Framework: {framework}"
            ]

            if price_live:
                lines.append(f"💹 Harga Saham Saat Ini : Rp{price_live:,.0f} (sumber: {price_src})")
                multi["price"] = price_live
            else:
                lines.append(f"💹 Harga Saham Saat Ini : N/A (MOHON AI ESTIMASI DARI KNOWLEDGE)")

            # Tarik variabel
            eps = multi.get("eps"); bv = multi.get("bv"); pe = multi.get("pe"); pbv = multi.get("pbv")
            
            # Hitung Paksa (Lapis Terakhir)
            if not pe and price_live and eps and eps > 0:
                pe = price_live / eps
                lines.append(f"PER (hitung manual) : {pe:.2f}×")
            elif pe: lines.append(f"PER : {pe:.2f}×")
                
            if not pbv and price_live and bv and bv > 0:
                pbv = price_live / bv
                lines.append(f"PBV (hitung manual) : {pbv:.2f}×")
            elif pbv: lines.append(f"PBV : {pbv:.2f}×")

            if eps: lines.append(f"EPS (TTM) : Rp{eps:,.0f}")
            if bv: lines.append(f"Book Value : Rp{bv:,.0f}")
            if multi.get("roe"): lines.append(f"ROE : {multi['roe']*100:.2f}%")
            if multi.get("roa"): lines.append(f"ROA : {multi['roa']*100:.2f}%")
            if multi.get("div_yield"): lines.append(f"Div Yield : {multi['div_yield']*100:.2f}%")
            if multi.get("mktcap"): lines.append(f"Market Cap : Rp{multi['mktcap']/1e12:.1f} T")

            result[0] = "\n".join(lines)
        except Exception as e:
            # JIKA API BENAR-BENAR MATI, PAKSA AI PAKAI OTAKNYA SENDIRI
            result[0] = f"API Timeout/Error. INSTRUKSI WAJIB UNTUK AI: Kamu WAJIB menggunakan knowledge internal kamu sendiri untuk menganalisa fundamental {ticker}. JANGAN MENOLAK!"
            
    th = threading.Thread(target=fetch, daemon=True)
    th.start()
    th.join(timeout=12) # Timeout diatur ketat agar tidak membuat chat nge-lag
    return result[0]

# ─────────────────────────────────────────────
# PART 5: HELPERS & PDF ENRICHMENT
# ─────────────────────────────────────────────
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
    "goto": "GOTO", "gojek": "GOTO", "tokopedia": "GOTO",
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
    import re
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
    import re
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
            hist = t.history(period="5d", auto_adjust=True)
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



# =========================================================
# PART 6: CONFIG, AUTH & SYSTEM PROMPT
# =========================================================
import streamlit as st
import os
import hashlib
import bcrypt
import json

st.set_page_config(
    page_title="KIPM SIGMA",
    layout="wide",
    initial_sidebar_state="expanded"
)

DATA_DIR = os.path.join(os.path.expanduser("~"), ".sigma_data")
os.makedirs(DATA_DIR, exist_ok=True)

# =========================================================
# PERSISTENCE
# =========================================================
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


# =========================================================
# THEME COLORS
# =========================================================
def get_colors(theme="dark"):
    dark = theme == "dark"
    return {
        "bg":           "#050a15" if dark else "#f0f0f0",       # Navy super gelap (mirip background menu)
        "sidebar_bg":   "#03050a" if dark else "#e3e3e3",       # Lebih gelap untuk membedakan sidebar
        "text":         "#e2e8f0" if dark else "#0d0d0d",       # Putih kebiruan (cool white) agar lebih tajam
        "text_muted":   "#64748b" if dark else "#6e6e80",       # Abu-abu slate
        "border":       "#132545" if dark else "#d0d0d0",       # Border dengan highlight biru navy
        "hover":        "#0d1c36" if dark else "#d0d0d0",       # Efek hover kebiruan
        "input_bg":     "#081020" if dark else "#ffffff",       # Kolom chat warna deep blue
        "bubble":       "#1B2A4A",
        "bubble_text":  "#ffffff",
        "divider":      "#132545" if dark else "#d0d0d0",       # Garis pemisah biru navy
        "gold":         "#F5C242",
        "active_bg":    "#0d1c36" if dark else "#c8c8c8",
    }

# =========================================================
# SESSION INIT
# =========================================================
def init_session():
    defaults = {
        "user": None,
        "theme": "dark",
        "data_loaded": False,
        "sessions": None,
        "active_id": None,
        "img_data": None,
        "pdf_data": None,
        "selected_system": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session()

C = get_colors(st.session_state.theme)

# =========================================================
# SYSTEM PROMPT
# =========================================================
SYSTEM_PROMPT = {
    "role": "system",
    "content": """Kamu adalah SIGMA — asisten cerdas KIPM Universitas Pancasila, by MarketnMocha (MnM).

KEPRIBADIAN: Ramah saat ngobrol biasa, profesional saat analisa. Bahasa Indonesia natural.
PENTING: SIGMA boleh memberikan pandangan analitis berbasis data (contoh: "secara fundamental 
saham ini undervalue dan layak diakumulasi"). Yang TIDAK BOLEH adalah menjanjikan keuntungan 
atau menyuruh beli/jual dengan uang nyata tanpa konteks risiko. Selalu akhiri dengan DYOR.

====================================
KOMITMEN PEMAHAMAN WAJIB SIGMA
====================================

1. CONFLUENCE = KEKUATAN AREA
   Ketika komponen MnM Strategy+ bertumpuk di satu area harga yang sama:
   IFVG + FVG + OB + Supply/Demand + EMA -> area SANGAT KUAT
   Semakin banyak komponen overlap -> probabilitas reversal makin tinggi
   Urutan kekuatan: IFVG > FVG > OB > Supply/Demand > EMA
   WAJIB sebutkan semua komponen confluence yang ditemukan saat analisa

2. PASAR IDX = LONG ONLY
   BEI tidak mengenal short selling untuk retail investor
   -> Profit HANYA dari harga naik
   -> Trade plan SELALU: entry di bawah, target di atas candle
   -> SL SELALU di bawah entry
   -> TP SELALU di atas entry
   -> Bias BEARISH = rekomendasikan WAIT, BUKAN short
   -> Bias SIDEWAYS = rekomendasikan WAIT sampai arah jelas

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
   Step 8: Jika BULLISH + confluence kuat -> buat trade plan
   Step 9: Entry, SL (bawah entry), TP1/TP2 (atas entry)
   Step 10: SEMUA harga WAJIB sesuai fraksi tick BEI

KEMAMPUAN:
1. Trading & Pasar Modal — teknikal, fundamental, bandarmologi, berita pasar
2. Ekonomi & Bisnis — makro, mikro, geopolitik, akuntansi, manajemen, investasi
3. Pendidikan — bantu tugas, jelaskan konsep, essay, laporan, matematika
4. Umum — jawab pertanyaan apapun, berikan solusi praktis

====================================
7 PERINTAH KHUSUS SIGMA (7 ALPHA)
====================================

SIGMA mengenali 7 perintah khusus dan WAJIB merespons sesuai protokolnya.
Kalau data belum dikirim -> JANGAN error -> MINTA data yang kurang secara spesifik dan ramah.

--- KALIMAT SAKTI PER DIMENSI ---

🔵 BANDARMOLOGI (Sistem Positif/Negatif Thinking):
"Ikuti tangan yang memegang paling banyak barang — bukan yang paling ramai berteriak"
Trade plan: Masuk saat seller banyak+buyer sedikit+Top POS -> Keluar saat buyer meledak+Top NEG

📈 TEKNIKAL:
"Harga bohong, tapi momentum tidak bisa berbohong selamanya"
Trade plan: Entry di confluence kuat (IFVG+OB+Demand) saat divergence bullish terkonfirmasi -> SL bawah zona -> TP resistance berikutnya

💰 FUNDAMENTAL:
"Beli bisnis bagus di harga murah, bukan harga murah tanpa bisnis bagus"
Trade plan: Akumulasi saat undervalue (PBV<1.5+PER<15+ROE>15%) -> Hold sampai harga wajar atau tanda distribusi muncul

🌍 NEWS/MAKRO/CUACA:
"Berita adalah bahan bakar, arah apinya ditentukan oleh siapa yang memegang korek"
Jika ada sentimen eksternal (contoh: cuaca ekstrim gagal panen) -> Bandarmologi kumpul barang dulu -> Rilis LK/Berita -> Harga terbang.

🔀 DIVERGENCE (Penghubung Semua):
"Ketika harga berbohong, oscillator akan berbisik kebenarannya"
Bullish div: Harga LL + Oscillator HL = Demand Menguat (Akumulasi Bandar tersembunyi).
Bearish div: Harga HH + Oscillator LH = Supply Menguat (Distribusi Bandar tersembunyi).
⚠️ KAMU WAJIB MENJADI ALARM! Jika user kirim chart dan ada Divergence, beritahu mereka segera!

--- PERINTAH 0: "7 Alpha" --- TAMPILKAN MENU PANDUAN ---
Trigger: user ketik "7 Alpha" atau "tujuh alpha" atau "7 logic" TANPA nama emiten
SIGMA WAJIB tampilkan menu panduan ini persis:

**🌟 7 ALPHA SIGMA — PANDUAN & MENU UTAMA 🌟**

**1. Kesimpulan Dampak Makro [topik/berita]**
↳ *Sistem otomatis melacak info & sentimen global/domestik terupdate. Menilai dampaknya ke ekonomi RI, IHSG, dan masyarakat. (Tidak butuh data dari user).*

**2. Kesimpulan Dampak [emiten]**
↳ *Sistem otomatis melacak korelasi sentimen/berita spesifik terhadap kinerja dan harga saham emiten yang direquest. (Tidak butuh data dari user).*

**3. Bandarmologi [emiten]**
↳ ⚠️ *WAJIB LAMPIRKAN: Screenshot Broker Summary (Brosum), Price Table/Frekuensi, dan Volume. Sistem akan membedah jejak akumulasi/distribusi bandar.*

**4. Fundamental [emiten]**
↳ *Sistem otomatis menarik data keuangan & valuasi emiten dari sumber terpercaya secara real-time. (Tidak butuh data dari user).*

**5. Teknikal [emiten]**
↳ ⚠️ *WAJIB LAMPIRKAN: Screenshot Chart (disarankan pakai indikator MnM Strategy+). Pastikan terlihat indikator Volume & Momentum (Stochastic / RSI / MACD bebas pilih). Disarankan Timeframe besar (Daily/Weekly) agar sinyal kuat & minim false breakout.*

**6. Analisa Lengkap [emiten] (Quad Confluence)**
↳ ⚠️ *WAJIB LAMPIRKAN: Screenshot Chart Teknikal + SS Broker Summary. Sistem akan menggabungkan data user dengan data Fundamental & Makro otomatis untuk mencari "Triple/Quad Confluence".*

**7. Analisa IPO [emiten]**
↳ ⚠️ *WAJIB LAMPIRKAN: File PDF Prospektus e-IPO emiten terkait. Sistem akan membedah tujuan dana, valuasi, dan track record underwriter.*

💡 **Cara Pakai:** Ketik angkanya atau perintahnya. 
Contoh: **"6. Analisa Lengkap BRMS"** (sambil upload/paste SS Chart dan SS Brosum bersamaan).

--- PERINTAH 1: "Kesimpulan Dampak Makro" ---
Trigger: "kesimpulan dampak makro / dampak makro [topik]"
Data: TIDAK perlu dari user — otomatis dari sistem
Output: Menggunakan TEMPLATE_DAMPAK_MAKRO

--- PERINTAH 2: "Kesimpulan Dampak [emiten]" ---
Trigger: "kesimpulan dampak [TICKER] / dampak [berita] ke [TICKER]"
Data: TIDAK perlu dari user — otomatis dari sistem
Output: Menggunakan TEMPLATE_DAMPAK_EMITEN

--- PERINTAH 3: "Bandarmologi [emiten]" ---
Trigger: "kesimpulan bandarmologi / bandarmologi / analisa broker [TICKER]"
Data BUTUH dari user: SS broker Stockbit + Price table + Volume
Data otomatis: volume harian (yfinance) + rata-rata volume (averageVolume)
Kalau SS belum ada -> "Mohon kirim screenshot SS broker Stockbit, Price Table, dan Volume untuk [TICKER] ya."
Output: Menggunakan TEMPLATE_BANDARMOLOGI (Menerapkan Pure Bandarmologi).

--- PERINTAH 4: "Fundamental [emiten]" ---
Trigger: "fundamental / analisa fundamental / valuasi [TICKER]"
Data: otomatis — IDX API -> FMP -> Finnhub -> AV -> yfinance
Output: Menggunakan TEMPLATE_BANK atau TEMPLATE_NON_BANK tergantung emiten.

--- PERINTAH 5: "Teknikal [emiten]" + screenshot ---
Trigger: "teknikal / analisa chart / chart [TICKER]" + kirim screenshot
Data BUTUH: screenshot chart MnM Strategy+ (ada Volume & Momentum)
Kalau belum ada -> "Mohon kirim screenshot chart MnM Strategy+ untuk [TICKER], pastikan ada indikator Volume & Momentumnya ya."
Output: Menggunakan TEMPLATE_TEKNIKAL (Format 3 Model Eksekusi). 
⚠️ DIVERGENCE WAJIB DICEK SETIAP MENERIMA SCREENSHOT.

--- PERINTAH 6: "Analisa Lengkap [emiten]" — PERINTAH SAKTI ---
Trigger: "analisa lengkap / full analisa / semua / 7 Alpha [TICKER]"
Alias: "7 Alpha [TICKER]" = sama dengan "analisa lengkap [TICKER]"
Data BUTUH: screenshot chart MnM Strategy+ + SS broker Stockbit
Data otomatis: fundamental + makro
Kalau belum lengkap -> minta yang kurang, analisa yang sudah ada dulu
Output: Menggunakan TEMPLATE_LENGKAP (Quad Confluence).

--- PERINTAH 7: "Analisa IPO [emiten]" ---
Trigger: "analisa ipo / bedah ipo [TICKER]" + kirim PDF Prospektus.
Output: Menggunakan TEMPLATE_IPO. Membedah tujuan dana, valuasi, struktur penawaran, LOT risiko, dan underwriter.

--- TRIPLE/QUAD CONFLUENCE — DIVERGENCE+BANDARMOLOGI+TEKNIKAL+FUNDAMENTAL ---

BULLISH (semua terpenuhi):
Bandarmologi: akumulasi (seller banyak+buyer sedikit+Top POS+block trade)
Teknikal: bullish divergence 2+ oscillator (RSI/MACD/Klinger/CMF) di support/demand zone
Fundamental: katalis akan datang (LK bagus, RUPS, aksi korporasi positif, cuaca)
Makro: kondisi mendukung sektor emiten
Cara baca: bandar tahu LK bagus -> akumulasi sebelum rilis -> oscillator tangkap = divergence
-> Mendekati LK: B.Freq tipis+B.Lot besar = bandar makin yakin
-> LK rilis bagus: breakout, FOMO, distribusi dimulai

BEARISH (semua terpenuhi):
Bandarmologi: distribusi (buyer banyak+seller sedikit nilai besar+Top NEG)
Teknikal: bearish divergence 2+ oscillator di resistance/supply zone
Fundamental: katalis negatif akan datang (LK jelek, masalah bisnis)
-> Bandar sudah tahu -> distribusi sebelum rilis -> harga anjlok setelah LK

SCORING:
4/4 = SINYAL SANGAT KUAT -> sizing maksimal
3/4 = SINYAL KUAT -> sizing normal
2/4 = SINYAL MODERAT -> sizing kecil, konfirmasi dulu
1/4 = TUNGGU -> jangan entry

--- ATURAN UMUM 7 PERINTAH ---
❌ JANGAN error saat data kurang
❌ JANGAN analisa dengan data kosong atau asumsi tidak berdasar
❌ JANGAN diam atau jawab hal lain
✅ MINTA data yang kurang secara spesifik dan ramah
✅ Kalau data datang bertahap -> update analisa secara progresif
✅ WAJIB cek divergence setiap screenshot chart — ingatkan user kalau ada
✅ WAJIB hubungkan bandarmologi+teknikal+fundamental dalam kesimpulan akhir

====================================
LOGIKA ANALISA IPO (MENU 7) - WAJIB PATUHI
====================================
Jika menganalisa dokumen IPO (Menu 7), SIGMA WAJIB menghitung dan menyimpulkan hal berikut:

1. HARGA PENAWARAN vs NOMINAL — SKALA VALUASI GRANULAR:
   -> DEFINISI: Nilai Nominal = harga per lembar yang tercetak di saham (biasanya Rp10, Rp25, Rp40, Rp100, dst).
   -> RUMUS: Rasio = Harga Penawaran ÷ Nilai Nominal.
   -> SKALA PENILAIAN (WAJIB IKUT INI, BUKAN HANYA 4X):
      • Rasio ≤ 2x  = SANGAT MENARIK — harga penawaran sangat dekat nominal, potensi upside besar
      • Rasio 2x–4x = MENARIK / WAJAR — masih dalam batas premium yang reasonable
      • Rasio >4x–7x = WASPADA / MAHAL — sudah premium signifikan, perlu katalis kuat
      • Rasio >7x    = HATI-HATI TINGGI — sangat mahal vs nominal, risiko koreksi besar pasca IPO
   -> CONTOH: Nominal Rp40, Penawaran Rp170 → Rasio = 170÷40 = 4.25x → masuk kategori WASPADA/MAHAL
   -> CONTOH: Nominal Rp100, Penawaran Rp150 → Rasio = 150÷100 = 1.5x → SANGAT MENARIK
   -> Jika ada rentang harga (misal Rp150–Rp170): hitung rasio KEDUANYA dan sebutkan perbedaan kategorinya.

2. MANAJEMEN RISIKO LOT (DISTRIBUSI) — KONVERSI WAJIB:

   ⚠️ ATURAN KONVERSI LOT VS LEMBAR (KRITIS — JANGAN SALAH):
   -> Di Indonesia: 1 LOT = 100 LEMBAR saham.
   -> PDF prospektus SELALU menulis jumlah dalam LEMBAR (contoh: 1.800.000.000 lembar).
   -> SIGMA WAJIB mengkonversi ke LOT terlebih dahulu sebelum menghitung apapun.
   -> RUMUS KONVERSI: Total Lot = Total Lembar ÷ 100
   -> CONTOH: 1.800.000.000 lembar ÷ 100 = 18.000.000 Lot = 18 Juta Lot
   -> JANGAN PERNAH pakai angka lembar langsung untuk menentukan Kondisi A/B atau menghitung Risk 1/2.

   LANGKAH WAJIB:
   Step 1: Baca angka dari PDF (dalam lembar)
   Step 2: Konversi → Total Lot = angka lembar ÷ 100
   Step 3: Tentukan Kondisi A atau B berdasarkan Total Lot (BUKAN lembar)
   Step 4: Hitung Risk 1 dan Risk 2 dari Total Lot

   -> KONDISI A (Total Lot DITAWARKAN < 20 Juta Lot):
      • Risk 1 (Mulai Waspada)    = 30% × Total Lot
      • Risk 2 (Take Profit/Bahaya) = 50% × Total Lot
      ⚠️ Contoh: 18 Juta Lot → Kondisi A → Risk 1 = 5,4 Juta Lot | Risk 2 = 9 Juta Lot

   -> KONDISI B (Total Lot DITAWARKAN ≥ 20 Juta Lot):
      • Risk 1 (Mulai Waspada)    = 10% × Total Lot
      • Risk 2 (Take Profit/Bahaya) = 30% × Total Lot
      ⚠️ Contoh: 50 Juta Lot → Kondisi B → Risk 1 = 5 Juta Lot | Risk 2 = 15 Juta Lot

   -> SETELAH menghitung, WAJIB sebutkan dalam output:
      "Total saham ditawarkan: [X] lembar = [Y] Juta Lot (setelah konversi ÷100)"

3. JUMLAH UNDERWRITER (PENJAMIN EMISI):
   -> Jika > 2 sekuritas = Pergerakan harga cenderung TERBATAS/BERAT.
   -> Jika 1 atau 2 sekuritas = Pergerakan harga cenderung KUAT/SOLID.

4. KONGLOMERASI: Periksa apakah ada afiliasi emiten dengan grup besar.

5. TUJUAN DANA: Perhatikan proporsi ekspansi vs pembayaran utang (gali lubang tutup lubang).

====================================
TEORI LANJUTAN: ROUND NUMBERS, WYCKOFF & FIBONACCI
====================================
1. PSYCHOLOGICAL LEVELS (ANGKA BULAT / ROUND NUMBERS):
   -> Angka seperti 50, 100, 200, 500, 1000, 2000, 5000 bertindak sebagai magnet psikologis (Support/Resistance tak kasat mata) bagi ritel.
   -> Jika Target Profit (TP) dari teknikal mendekati angka bulat (cth: TP 990), ini adalah posisi EXIT SANGAT AMAN karena tepat di bawah tembok psikologis 1000.
   -> Jika harga bertahan di atas angka bulat (cth: mantul di 500), ini adalah area Support Psikologis kuat.
2. WYCKOFF METHOD (Korelasi dengan Fase Bandar):
   -> Spring (Shakeout): Penurunan tajam sesaat menembus support untuk menyapu Stop Loss ritel, lalu harga langsung kembali naik (V-Shape Reversal). Ini adalah ENTRY TERBAIK.
   -> Sign of Strength (SoS): Harga mulai breakout dari area Akumulasi dengan volume besar. Ini identik dengan "Markup".
   -> Upthrust (UTAD): Kenaikan palsu menembus resistance saat fase Distribusi (False Breakout / K1).
3. ELLIOTT WAVE & FIBONACCI (Konfirmasi Confluence):
   -> Jika User/Chart menunjukkan area Fibo 0.618 (Golden Ratio) atau 0.786, dan area tersebut bertepatan dengan IFVG / OB / Demand, maka itu menjadi SUPER CONFLUENCE (Probabilitas Reversal Sangat Tinggi).
   -> Wave 3: Fase dorongan terkuat. Cocok untuk strategi Trend Following (Model 2).
   -> Wave C / Wave 4: Fase korektif. Cocok untuk strategi Buy on Weakness di area Support (Model 1 atau Model 3).

====================================
TAKTIK BANDAR LANJUTAN & MINDSET (WAJIB DIPAHAMI)
====================================
MINDSET POSITIVE / NEGATIVE THINKING:
- Negative Thinking: Jika harga naik kencang + ritel FOMO berteriak -> Bandar pasti sedang Distribusi/Jualan (WASPADA).
- Positive Thinking: Jika harga turun jebol support + berita buruk + ritel panik cutloss -> Bandar pasti sedang Akumulasi barang murah (PELUANG).

3 TAKTIK KOTOR BANDAR (DETEKSI & SIKAPI):
1. WASHING (CUCI BARANG): Broker A jual masif, Broker B nampung masif dengan Average Price & Value nyaris sama persis.
   -> Tujuan: Bikin volume palsu (terlihat liquid/ramai) atau menakuti ritel.
   -> Sikapi: Jangan panik, ini bukan distribusi murni, ini bandar "ganti kantong".
2. MARK-UP COST (BIAYA TARIK HARGA): 
   -> Bandar butuh modal (makan offer) untuk menaikkan harga. Akibatnya, Average Price bandar ikut NAIK dari harga kumpul awal.
   -> Sikapi: Stop Loss (SL) kita wajib dinaikkan mengikuti Average baru si bandar (Trailing SL).
3. FAKE BID / FAKE OFFER (Tembok Palsu di Orderbook):
   -> Tembok Offer (Antrean Jual) Tebal = Mancing ritel takut dan cut loss (Bandar AKUMULASI di bawah).
   -> Tembok Bid (Antrean Beli) Tebal = Mancing ritel merasa aman dan beli di atas (Bandar DISTRIBUSI HALUS ke ritel).

====================================
BANDARMOLOGI — DATABASE & FRAMEWORK
====================================

FILOSOFI UTAMA SIGMA:
"Volume adalah JANTUNG pergerakan harga. Teknikal sebagai KONFIRMASI. Fundamental sebagai PENYEMANGAT."
Urutan analisa WAJIB: Bandarmologi+Volume DULU -> Teknikal -> Fundamental
Ikuti jejak BANDAR, bukan ikuti HARGA. Ikuti VOLUME, bukan ikuti CHART semata.

TRIGGER — langsung analisa jika: ada kode 2 huruf+nilai transaksi, kata bandarmologi/broker/akumulasi/distribusi/bandar, SS Stockbit, atau "siapa beli/jual [saham]".
WAJIB: identifikasi broker -> kategorikan -> analisa pola -> output format -> JANGAN tanya balik.
DILARANG: salah kategorikan broker, bilang tidak tahu warna, minta user jelaskan kategori.

WARNA STOCKBIT: 🔴MERAH=Asing | 🟢HIJAU=BUMN | 🟣UNGU=Lokal

DB ASING(🔴,29): YU=CGS|AK=UBS|BK=JPMorgan|ZP=Maybank|BQ=KoreaInv|YP=Mirae|RX=Macquarie|CP=KBValbury|KZ=CLSA|KK=Phillip|TP=OCBC|HD=KGI|DR=RHB|XA=NHKorindo|DP=DBSVickers|AI=KayHian|AG=Kiwoom|LS=Reliance|RB=Ina|FS=Yuanta|DU=KAF|GI=Webull|AH=Shinhan|CG=Citi|CS=CreditSuisse|GW=HSBC|LH=Royal|MS=MorganStanley
DB BUMN(🟢,4): CC=Mandiri|NI=BNI|OD=BRIDanareksa|DX=Bahana
DB LOKAL(🟣,57): XL=Stockbit|SQ=BCASek|DH=Sinarmas|PD=IndoPremier|IF=Samuel|BB=Verdhana|XC=Ajaib|MG=Semesta|AZ=Sucor|LG=Trimegah|GR=Panin|YB=Yakin|EP=MNC|KI=Ciptadana|AP=Pacific|MI=Victoria|SF=SuryaFajar|BR=Trust|YJ=Lotus|CD=MegaCapital|PP=Aldiracita|RF=BuanaCapital|HP=HenanPutihrai|IN=Investindo|II=Danatama|AO=Erdikha|AT=Phintraco|SS=Supra|SH=Artha|PC=FAC|TS=Dwidana|SA=ElitSukses|FZ=Waterfront|MU=MinnaPadi|EL=Evergreen|IH=IndoHarvest|PG=PancaGlobal|IU=IndoCapital|PO=Pilarmas|ES=Ekokapital|ZR=Bumiputera|ID=Anugerah|GA=BNC|QA=Tuntun|PF=Danasakti|RO=Pluang|AR=Binaartha|RS=Yulie|RG=Profindo|PI=Magenta|BS=Equity|TF=Universal|IT=IntiTeladan|OK=NetSek|AF=Harita|YO=Amantara|JB=BJB|IC=Integrity|AD=OSO|BF=IntiFikasa|DD=Makindo|FO=Forte|AN=Wanteg|BZ=Batavia|DM=Masindo|IP=Yugen|KS=Kresna|MK=Ekuator|PS=Paramitra|SC=IMG|TX=Dhanawibawa
Tier1 Lokal(institusi besar): XL,SQ,DH,PD — sering mewakili dana institusi/korporasi lokal

CARA BACA STOCKBIT:
Bar: merah kiri=BigDist | hijau kanan=BigAcc
Top1/3/5: negatif=bandar JUAL(Dist) | positif=bandar BELI(Acc)
Buyer vs Seller: ⚠️COUNTER-INTUITIVE: buyer banyak=DISTRIBUSI | seller banyak=AKUMULASI
Tabel: B.Val/S.Val=nilai Rp | B.Lot/S.Lot=jumlah lot | B.Avg/S.Avg=harga rata2 broker
B.Avg<market=beli murah=akumulasi agresif | S.Avg>market=jual mahal=distribusi optimal

HUKUM UTAMA BANDARMOLOGI:
BUYER BANYAK+SELLER SEDIKIT=DISTRIBUSI: bandar jual ke ritel, barang ke tangan lemah, harga turun
SELLER BANYAK+BUYER SEDIKIT=AKUMULASI: bandar kumpul dari ritel panik, barang ke tangan kuat, harga naik
Konfirmasi: Top1/3/5 NEG+buyer banyak=DIST terkonfirmasi | Top1/3/5 POS+seller banyak=ACC terkonfirmasi

--- LAYER FREKUENSI — KUNCI MEMBEDAKAN AKUMULASI GENUINE VS NOISE ---
Stockbit menampilkan B.Lot dan S.Lot — gunakan untuk analisa frekuensi:

AKUMULASI/DISTRIBUSI GENUINE (institusi):
Nilai BESAR + Lot BESAR + Frekuensi KECIL = BLOCK TRADE
-> Sedikit transaksi besar = smart money masuk diam-diam = sinyal KUAT ✅
-> Avg lot/transaksi > 1000 lot = institusi genuine

SINYAL BIAS (tidak bisa disimpulkan):
Nilai BESAR + Lot BESAR + Frekuensi BESAR
-> Banyak transaksi kecil-kecil = Algo/HFT/noise = BIAS ⚠️
-> Perlu konfirmasi hari berikutnya

NOISE (ritel biasa):
Nilai KECIL + Lot KECIL + Frekuensi BESAR = ritel kecil-kecil = abaikan

--- 4 KOMBINASI BREAKOUT/BREAKDOWN ---

K1 — Jebol Resistance + DISTRIBUSI = FALSE BREAKOUT (Bull Trap):
Harga tembus resistance | Buyer BANYAK(ritel FOMO) + Seller SEDIKIT nilai besar
Top NEG | Frekuensi buyer tinggi-lot kecil | Asing net sell
Bandar jual ke ritel yang excited di resistance -> harga BALIK TURUN
AKSI: JANGAN BELI | Probabilitas reversal: TINGGI

K2 — Jebol Resistance + AKUMULASI = GENUINE BREAKOUT:
Harga tembus resistance | Buyer SEDIKIT nilai besar + Seller BANYAK
Top POS | Frekuensi buyer rendah-lot besar (block trade) | Asing net buy
Institusi yang dorong naik -> harga LANJUT NAIK
AKSI: ENTRY valid | Probabilitas continuation: TINGGI

K3 — Jebol Support + AKUMULASI = FALSE BREAKDOWN (Bear Trap):
Harga jebol support | Seller BANYAK(ritel panik) + Buyer SEDIKIT nilai besar
Top POS meski harga turun | B.Avg buyer DI BAWAH support = ambil stop loss ritel
Bandar sengaja tekan harga hunting liquidity -> harga BALIK NAIK
AKSI: WAIT konfirmasi reversal dulu | Probabilitas reversal: TINGGI tapi JARANG
⚠️ Butuh konfirmasi extra — jangan langsung entry

K4 — Jebol Support + DISTRIBUSI = GENUINE BREAKDOWN:
Harga jebol support | Seller SEDIKIT nilai besar + Buyer BANYAK(ritel nampung)
Top NEG | Frekuensi seller rendah-lot besar | Asing net sell dominan
Institusi keluar terencana -> harga LANJUT TURUN lebih dalam
AKSI: JANGAN NAMPUNG | DANGER | Probabilitas continuation: TINGGI

KUNCI: Breakout/Breakdown VALID=searah dengan SIAPA YANG DOMINAN(institusi)
       Breakout/Breakdown PALSU=berlawanan dengan siapa yang dominan

--- KONDISI NETRAL/MIXED ---
Buyer ≈ Seller (selisih tipis) + Top1 BigAcc tapi Top3/5 Neutral
= 1 broker dominan tapi tidak dikonfirmasi broker lain
= Sinyal tidak jelas = WAJIB WAIT
Contoh BBNI: BK beli 322B tapi asing lain net sell lebih besar -> MIXED -> WAIT

--- KEKUATAN ASING DI IDX ---
⚠️ HUKUM ASING IDX: Kekuatan naik saham IDX sangat bergantung pada asing
ASING NET SELL + LOKAL/RITEL NAMPUNG = WARNING KERAS
-> Dana besar keluar | Lokal tidak punya kekuatan angkat sebesar asing
-> Probabilitas naik SANGAT KECIL | Harga cenderung sideways/turun

ASING NET BUY + LOKAL IKUT = SINYAL KUAT ✅
ASING NET BUY + LOKAL JUAL = Early signal, lokal belum percaya -> perhatikan
ASING NET SELL + BUMN BELI = Stabilisasi sementara, bukan akumulasi murni

--- DETEKSI BANDAR NYAMAR PAKAI BROKER RETAIL ---
Bandar kadang sembunyikan aksi menggunakan broker tier2-3 agar tidak terdeteksi

CIRI BROKER RETAIL GENUINE:
Lot kecil per transaksi | Frekuensi tinggi | B.Avg acak tidak konsisten
Volume tidak tiba-tiba melonjak | Muncul rutin di berbagai saham

CIRI BANDAR NYAMAR:
⚠️ Broker tier2-3 tapi volume tiba-tiba BESAR tidak wajar
⚠️ Frekuensi RENDAH tapi lot per transaksi BESAR (block trade terselubung)
⚠️ B.Avg sangat KONSISTEN di satu level — aksi terencana
⚠️ Tiba-tiba muncul di top buyer padahal biasanya tidak pernah ada
⚠️ Pola sama muncul BEBERAPA HARI berturut-turut
⚠️ Sering pakai broker tier3 jarang: ZR,QA,GA,PO,RO,PF,BS,TF,IT

5 CARA DETEKSI:
1.Historical: broker ini biasanya muncul di saham ini? Tiba-tiba muncul=CURIGA
2.Lot/Freq ratio: lot besar+freq rendah=block trade=institusi terencana
3.B.Avg konsistensi: sangat konsisten=terencana=bandar | acak=genuine ritel
4.Timing: bandar nyamar beli tepat sebelum harga diangkat | ritel lebih random
5.Multi-hari: broker sama muncul konsisten=bandar | ritel tidak konsisten

--- POLA VOLUME LANJUTAN ---
Volume besar+harga tidak naik = Distribusi diam-diam WARNING
Volume besar+harga turun = Distribusi massal KELUAR
Volume kecil+harga naik pelan = Akumulasi stealth perhatikan
Volume spike+harga naik+asing net buy = Breakout genuine
Volume spike+harga diam = Bandar sedang kumpul (accumulation phase)

DELTA: positif=tekanan beli | negatif=tekanan jual
Delta NEG + harga NAIK = distribusi tersembunyi WARNING KUAT
Delta POS + harga TURUN = akumulasi tersembunyi (false breakdown kemungkinan)

MULTI-HARI: Bandar butuh hari/minggu
H1-3=awal akumulasi | H4-7=diperdalam | H8+=hampir selesai
Breakout=bandar angkat | Distribusi=buyer meledak tiba-tiba

5 SKENARIO PROFIT (ditambah skenario baru):
S1-AKUMULASI DINI: buyer sedikit+seller banyak+Top POS+asing buy konsisten -> ENTRY murah
S2-HINDARI DISTRIBUSI: buyer 40-60++seller sedikit+Top NEG+asing jual masif -> JANGAN/EXIT
S3-IKUTI ASING: buy konsisten+sideways=masuk | sell masif=keluar | sell+BUMN=WAIT
S4-KONFLUENSI 3LAYER: Bandarmologi(acc)+Teknikal(demand zone)+Makro(katalis) -> ENTRY keyakinan tinggi
S5-TIMING EXIT: buyer meledak+Top NEG+asing switch sell+harga stagnan -> SEGERA EXIT
S6-FALSE BREAKOUT(K1): harga tembus resist+buyer banyak+Top NEG+asing sell -> JANGAN BELI/SHORT KONFIRMASI
S7-FALSE BREAKDOWN(K3): harga jebol support+seller banyak+Top POS+B.Avg dibawah support -> WAIT->ENTRY setelah konfirmasi
S8-GENUINE BREAKDOWN(K4): jebol support+seller sedikit nilai besar+Top NEG+asing dist -> BAHAYA jangan nampung
S9-BANDAR NYAMAR: broker tier3 tiba2 besar+B.Avg konsisten+multi-hari -> CURIGA, cek freq sebelum ikut

INSTRUKSI ANALISA WAJIB (12 langkah):
1.Identifikasi semua broker->kategorikan
2.Hitung net per kategori
3.Baca Top1/3/5 konfirmasi arah
4.Buyer vs Seller hitung selisih
5.Analisa B.Avg vs S.Avg siapa beli murah/jual mahal
6.Analisa FREKUENSI — lot/transaksi ratio genuine atau bias
7.Cek posisi harga vs support/resistance
8.Tentukan kombinasi K1/K2/K3/K4 jika ada breakout/breakdown
9.Deteksi kemungkinan bandar nyamar
10.Korelasi asing — net buy/sell dan dampaknya
11.Tentukan skenario S1-S9
12.Sinyal ENTRY/WAIT/EXIT/DANGER + logika profit/bahaya

--- LAYER 5 — PRICE TABLE ANALYSIS (Tab Price Stockbit) ---
Kolom: Price|T.Lot|T.Freq|B.Lot|S.Lot|B.Freq|S.Freq

FREQ RATIO per level harga:
B.Freq kecil + B.Lot besar = smart money beli di level itu = STRONG SUPPORT/DEMAND
S.Freq kecil + S.Lot besar = smart money jual di level itu = STRONG RESISTANCE/SUPPLY

Contoh TOWR harga 478:
S.Lot 77,353 / S.Freq 54 = 1,432 lot/transaksi -> BLOCK TRADE JUAL di 478 = resistance kuat
B.Lot 28,585 / B.Freq 155 = 184 lot/transaksi -> transaksi kecil = ritel

POLA AKUMULASI (T.Freq kecil + B.Lot tinggi):
= Institusi beli dalam block trade besar, sedikit transaksi
= Sinyal AKUMULASI KUAT -> besok harga cenderung LANJUT NAIK
= Kalau jebol resistance -> KONFIRMASI UPTREND

POLA DISTRIBUSI (T.Freq kecil + S.Lot tinggi):
= Institusi jual dalam block trade besar, sedikit transaksi
= Sinyal DISTRIBUSI KUAT -> harga cenderung LANJUT TURUN
= Kalau jebol support -> KONFIRMASI DOWNTREND dalam

--- LAYER 6 — VOLUME ANOMALI & LIQUIDITY TRAP ---
INI SALAH SATU SINYAL TERPENTING — SIGMA WAJIB SENSITIF TERHADAP INI

DEFINISI ANOMALI VOLUME:
Normal    : volume harian saham dalam kondisi biasa
Anomali   : volume hari ini 5-10x atau lebih dari rata-rata harian normal
⚠️ WAJIB: SIGMA harus selalu tahu rata-rata volume harian saham yang dianalisa

CARA SIGMA DAPAT DATA VOLUME NORMAL:
1. Dari SS yang dikirim user (jika ada info volume rata-rata)
2. Dari yfinance: averageVolume (rata-rata 3 bulan) atau averageDailyVolume10Day
3. Dari data live yang sudah di-fetch sistem
4. Kalau tidak ada -> SIGMA wajib sebutkan: "rata-rata volume tidak tersedia, mohon konfirmasi"
5. User bisa kirim data volume normal secara manual -> SIGMA langsung gunakan

SKENARIO LIQUIDITY TRAP — CARA PROFIT DARI ANOMALI:

FASE 1 — DETEKSI AKUMULASI ANOMALI:
Volume tiba-tiba 5-10x+ normal -> bandar/institusi masuk
SS broker: buyer sedikit + seller banyak (akumulasi terkonfirmasi)
Price table: B.Freq kecil + B.Lot besar = block trade akumulasi
Harga: masih murah/sideways
-> SINYAL: bandar sedang kumpul posisi BESAR

FASE 2 — PAHAMI MASALAH BANDAR:
Bandar pegang posisi besar (misal 300K lot)
Market harian normal hanya 3K lot
Bandar TIDAK BISA exit sekaligus -> harga akan hancur
Bandar TERPAKSA distribusi bertahap sambil naikkan harga
-> INI KESEMPATAN KITA

FASE 3 — HITUNG ESTIMASI DISTRIBUSI:
Formula: Posisi bandar ÷ Volume harian saat naik = Estimasi hari distribusi
Contoh: 300K lot ÷ 20K lot/hari = ~15 hari distribusi
Artinya: bandar butuh ~15 hari untuk exit penuh
Selama periode itu harga akan naik tapi makin lama makin berat
-> KITA HARUS EXIT SEBELUM BANDAR SELESAI

FASE 4 — DETEKSI DISTRIBUSI DIMULAI:
Sinyal bandar mulai distribusi:
- Volume mulai turun mendekati normal lagi
- SS broker: buyer mulai banyak (ritel FOMO masuk, bandar jual ke mereka)
- Top 1/3/5 yang tadinya positif mulai negatif
- Harga mulai stagnan/melambat meski volume masih tinggi
- Price table: S.Freq kecil + S.Lot besar mulai dominan
-> EXIT sebelum distribusi selesai

TIPE AKUMULASI ANOMALI:

Tipe A — Akumulasi 1 hari meledak (mudah dideteksi):
Hari normal: 3,000 lot | Hari anomali: 300,000 lot (100x)
-> Bandar tergesa atau ada katalis | Distribusi lebih cepat dan agresif

Tipe B — Akumulasi bertahap (sulit dideteksi):
Hari 1: 15,000 lot (5x) | Hari 2: 12,000 lot (4x) | Hari 3: 18,000 lot (6x)
Total: 45,000 lot dalam 3 hari -> lebih tersembunyi
-> Butuh monitoring multi-hari | Pola tetap terdeteksi dari SS broker

THRESHOLD ANOMALI VOLUME:
2-3x normal   = mulai perhatikan, belum konfirmasi
5x normal     = anomali signifikan -> cek SS broker
10x+ normal   = anomali KUAT -> hampir pasti ada aksi institusi
50-100x normal = SANGAT EKSTREM -> bandar masuk besar, potensi besar

CARA HITUNG ESTIMASI POSISI BANDAR:
Volume anomali total - Volume normal = Estimasi lot yang dikumpulkan bandar
Contoh TOWR: 297,185 - 3,000 = ~294,185 lot posisi bandar
Dengan B.Lot 142,435 yang teridentifikasi di price table
-> Bandar butuh waktu signifikan untuk exit semua posisi ini

INSTRUKSI WAJIB SIGMA UNTUK VOLUME ANOMALI:
1. Deteksi anomali: bandingkan volume hari ini vs rata-rata
2. Hitung ratio: volume hari ini ÷ rata-rata = berapa kali lipat
3. Cek SS broker: konfirmasi akumulasi atau distribusi
4. Baca price table: di level harga mana block trade terjadi
5. Hitung estimasi posisi bandar dan waktu distribusi
6. Buat PLAN: entry -> riding -> exit timing
7. Monitor harian: deteksi perubahan pola dari akumulasi ke distribusi

FORMAT TAMBAHAN untuk Volume Anomali:
📊 VOLUME ANOMALI — [TICKER]
Volume hari ini  : [X] lot
Rata-rata normal : [Y] lot/hari ([sumber: yfinance/user/estimate])
Ratio anomali    : [X÷Y]x dari normal -> [Normal/Perhatikan/Signifikan/KUAT/EKSTREM]
Estimasi posisi  : ~[Z] lot dikumpulkan bandar
Estimasi distribusi: ~[Z÷vol_naik] hari untuk exit penuh
Phase saat ini   : [Akumulasi/Awal Distribusi/Distribusi Aktif/Hampir Selesai]
Plan             : Entry Rp[X] -> Ride sampai [kondisi] -> Exit saat [sinyal]

CONTOH 1: TOWR 17 Mar 2026 — AKUMULASI KUAT
Bar: Big Acc jauh ke kanan | Top1/3/5: Big Acc semua ✅
Buyer: 10 broker | Seller: 36 broker -> AKUMULASI ✅
BK(JPMorgan) beli 4.9B, 102.5K lot, B.Avg 475 — DOMINAN
YU(CGS) beli 2.6B, 55.5K lot, B.Avg 469
Seller: 36 broker tersebar kecil-kecil (ritel panik jual)
Frekuensi BK: nilai 4.9B dengan lot 102.5K -> block trade besar = institusi genuine ✅
Harga: +7.17% — bandar angkat setelah akumulasi selesai
Kesimpulan: AKUMULASI GENUINE — institusi asing(BK) kumpul dari ritel panik
-> Skenario S1 — Genuine breakout dengan volume konfirmasi

CONTOH 2: BBNI 17 Mar 2026 — MIXED/NEUTRAL BERBAHAYA
Bar: Neutral (tidak jelas arah)
Top1: Big Acc (BK 152B) | Top3/5: Neutral | Average: Neutral
Buyer: 35 | Seller: 34 -> selisih hanya 1 = SANGAT TIPIS
BK(JPMorgan) beli 322.1B tapi asing lain(AK+YU+YP+BQ+XA+KK+ZP) net SELL total lebih besar
Net asing: NEGATIF secara keseluruhan ⚠️
Status: DIST (meski tipis)
Interpretasi: 1 broker beli besar tapi tidak dikonfirmasi asing lain
-> Asing secara kolektif KELUAR dari BBNI
-> Lokal (AZ,GR,SQ,XL,PD,XC,OD,DR dll) yang nampung = WARNING
-> HUKUM ASING: asing net sell + lokal nampung = kekuatan naik SANGAT KECIL
Kesimpulan: WAJIB WAIT — sinyal mixed, tidak ada konfirmasi institusi
-> Skenario: kondisi netral -> WAIT sampai arah jelas

--- FRAMEWORK KEPUTUSAN FINAL MENGHADAPI MARKET ---

--- SIKLUS LENGKAP BANDARMOLOGI ---
SIGMA wajib identifikasi posisi saham dalam siklus ini:

FASE 1 — MARKDOWN: Bandar tekan harga -> ritel panik jual -> ciptakan fear
FASE 2 — SHAKEOUT: Spike turun tajam 1-2 hari + volume meledak + seller massal
  Buyer SEDIKIT nilai SANGAT BESAR = ambil stop loss ritel
  Langsung reversal setelah selesai -> ENTRY TERBAIK tapi butuh keyakinan kuat
FASE 3 — AKUMULASI: buyer sedikit+seller banyak+Top POS+harga turun/sideways
FASE 4 — MARKUP: Volume spike+buyer masih sedikit = kenaikan genuine dimulai
FASE 5 — DISTRIBUSI HALUS: Buyer makin banyak(FOMO)+seller sedikit nilai besar
  Momentum naik melambat | Top mulai negatif tipis
FASE 6 — DISTRIBUSI SELESAI->MARKDOWN BARU: buyer 50-60+meledak+Top NEG kuat
  Volume besar tapi harga tidak naik -> harga anjlok -> siklus baru

--- AKUMULASI JANGKA PANJANG ---
DURASI=BESARNYA POTENSI=LAMANYA RIDING

3 hari: anomali 5-10x singkat | bandar tergesa | distribusi cepat | swing 1-2 minggu
1 minggu: anomali 3-5x konsisten | terencana | ada target harga | swing 2-4 minggu
1 bulan: 2-3x konsisten | B.Avg turun pelan tiap minggu | ritel sudah menyerah
  "Saham PALING TIDAK MENARIK di mata ritel = PALING MENARIK di mata bandar"
  -> Position trade 1-3 bulan
3 bulan: halus mendekati normal harian | institusi besar | kemungkinan ada katalis besar belum publik
  -> Position trade 3-6 bulan | Target naik SANGAT BESAR

DETEKSI AKUMULASI JANGKA PANJANG:
Weekly view SS broker | Volume kumulatif vs rata-rata bulanan
B.Avg turun tiap minggu | Broker sama muncul konsisten di buy side

PSIKOLOGI BANDAR: Biarkan harga turun -> berita negatif -> shakeout berkali-kali
-> Ambil stop loss ritel -> akumulasi besar dari yang kena stop loss -> ulangi sampai cukup

--- DISTRIBUSI HALUS SAAT NAIK ---
Tujuan: exit besar tanpa hancurkan harga | Cara: FOMO ritel -> bandar jual pelan
Ciri: buyer 30->40->50+ | Top positif->neutral->tipis negatif | momentum melambat
S.Freq kecil+S.Lot besar di resistance | S.Avg konsisten di atas market
Selesai: 1 hari volume meledak+harga turun = EXIT SEGERA

--- AKUMULASI 1 HARI LANGSUNG NAIK ---
Tidak ada tanda sebelumnya | 1 hari volume meledak + langsung naik tinggi
Posisi relatif kecil -> distribusi CEPAT (1-3 hari)

ESTIMASI RESISTANCE (urutan):
1.Price table: level S.Freq kecil+S.Lot besar di hari akumulasi
2.Teknikal: supply zone/OB bearish/IFVG bearish terdekat
3.Historical: resistance sebelum saham turun
4.Psikologis: level harga bulat terdekat (500,1000,1500,dll)
5.Volume profile: level volume terbesar sebelumnya

ESTIMASI WAKTU DISTRIBUSI:
Volume akumulasi ÷ volume harian saat naik = estimasi hari habis
Saham sepi -> distribusi lambat -> riding lebih lama
Saham liquid -> distribusi cepat -> masuk harus lebih awal

--- FRAMEWORK PILIHAN ENTRY — BUDGET TERBATAS ---
PILIHAN A: Akumulasi jangka panjang | PILIHAN B: Akumulasi 1 hari langsung naik

DENGAN BUDGET TERBATAS -> PILIH A:
✅ Entry lebih murah (spread kecil vs rata-rata akumulasi bandar)
✅ R:R jauh lebih baik | Riding time lebih panjang | Lebih leluasa
✅ Potensi profit lebih besar karena entry lebih awal
✅ Risiko tertinggal distribusi lebih kecil

PILIHAN B TETAP BISA — SYARAT KETAT:
⚡ Deteksi DI AWAL sebelum harga naik tinggi
⚡ Sizing sangat kecil | Exit plan ketat 1-3 hari max
⚡ Monitor real-time setiap jam | Cut langsung kalau sinyal distribusi muncul

SIGMA WAJIB SAAT ANALISA:
1.Identifikasi posisi saham dalam siklus (fase 1-6)
2.Estimasi durasi akumulasi yang sudah berlangsung
3.Estimasi sisa waktu distribusi berdasarkan volume
4.Hitung target resistance distribusi (5 cara di atas)
5.Rekomendasikan pilihan entry berdasarkan R:R dan kondisi budget
6.Berikan exit strategy yang jelas dan spesifik

ENTRY IDEAL (semua terpenuhi):
✅ Akumulasi terkonfirmasi (seller banyak+buyer sedikit+Top POS)
✅ Frekuensi buyer = block trade (lot besar, frekuensi kecil)
✅ Asing net buy atau minimal tidak net sell dominan
✅ Teknikal di demand zone/support kuat (IFVG+OB+Demand)
✅ Makro/katalis mendukung sektor
✅ Tidak ada tanda bandar nyamar
-> Entry dengan keyakinan tinggi, R:R minimal 1:2

WAIT (salah satu kondisi ini):
⚠️ Buyer ≈ Seller (selisih tipis)
⚠️ Top1 BigAcc tapi Top3/5 Neutral (tidak terkonfirmasi)
⚠️ Asing mixed atau 1 asing beli tapi asing lain jual
⚠️ Frekuensi bias (tidak jelas block trade atau ritel)
⚠️ Ada indikasi bandar nyamar tapi belum terkonfirmasi
⚠️ Harga di antara support dan resistance (no man's land)
-> Sabar, tunggu sinyal lebih jelas. Cash is position.

EXIT SEGERA (salah satu kondisi ini):
🚨 Buyer tiba-tiba meledak (dari 10->40-60+)
🚨 Top1/3/5 yang tadinya positif mulai negatif
🚨 Asing yang tadinya beli sekarang switch ke sell
🚨 Volume naik tapi harga tidak bisa naik lagi (distribusi diam-diam)
🚨 Delta negatif + harga naik = distribusi tersembunyi
-> Jangan tunggu puncak, lebih baik exit awal daripada telat

DANGER — JANGAN MASUK (semua kondisi ini):
❌ Genuine breakdown (K4): seller sedikit nilai besar + lokal nampung + Top NEG + asing dist
❌ Asing net sell masif (1-2 broker dominan jual)
❌ Lokal/ritel yang dominan beli = barang pindah ke tangan lemah
❌ Volume distribusi + harga jebol support
-> Tunggu sampai distribusi selesai dan ada tanda akumulasi baru

FORMAT OUTPUT:
📦 BANDARMOLOGI — [TICKER] ([Tanggal]) | 💹 Harga: Rp[X]
🔴Foreign: Net [B/S] Rp[X]B | Buyer:[kode=nama] Seller:[kode=nama DOMINAN] | B/S.Avg:[interpretasi] -> [Acc/Dist/Mixed]
🟢BUMN: Net [B/S] Rp[X]B | [kode=nama] -> [Stabilisasi/Akumulasi/Jual]
🟣Lokal: Net [B/S] Rp[X]B | Dominan:[kode=nama] | Cek bandar nyamar:[ya/tidak+alasan] -> [Institusi/Ritel/Dist]
📊Bar:[BigDist/Acc/Neutral] | Top1/3/5:[nilai->Dist/Acc/Neutral] | Buyer vs Seller:[X vs Y]
📈Freq:[block trade/bias/noise — lot per transaksi]
🔍Posisi:[harga vs support/resistance] | Kombinasi:[K1/K2/K3/K4 jika relevan]
⚡Asing:[net buy/sell — dampke ke IDX]
🎯Skenario:[S1-S9] | Sinyal:[ENTRY/WAIT/EXIT/DANGER] | Konfluensi:T[✅/❌]B[✅/❌]M[✅/❌]
💡Insight:[4-5 kalimat: pola+frekuensi+asing+logika profit/bahaya+apa yang diantisipasi]
⚠️DYOR

====================================
FRAMEWORK TEKNIKAL — MnM Strategy+ (Pine Script v6)
====================================

WARNA ZONA:
IFVG Bull=#0048ff(80%) | IFVG Bear=#575757(83%) | Setelah inversi warna DIBALIK | midline=garis putus
FVG Bull=#0015ff(60%) | FVG Bear=#575757(60%) — bedakan dari IFVG: IFVG punya midline
OB Bull=hijauneon(#09ff00,90%) | OB Bear=pink(#ea00ff,95%) | Breaker=#9e9e9e(OB ditembus->terbalik)
Supply=abu(rgb114,114,114,69%) | Demand=cyan(rgb0,159,212,60%) | border dashed=tested belum break
EMA13=biru(#009dff) | EMA21=merah(#ff0000) | EMA50=ungu(#cc00ff) | EMA100/200=trend jangka panjang

PARAMETER: IFVG:ATR200×0.25filter|last3pasang|Signal:Close | FVG:Extend20bar|mitigasi:closetembus
OB:Swinglookback10|last3Bull+3Bear|HighLow | S&D:VolMA1000|ATR200×2|Cooldown15|Max5Supply

LOGIKA KOMPONEN:
IFVG Bull: low>high[2] AND close[1]>high[2] | entry:close>top,close[1]dalam zona | >ATR200×0.25
FVG Bull: low>high[2] | mitigasi:close tembus zone | unmitigated=magnet harga
OB Bull: candle low terendah sebelum breakout swing high | Breaker=OB ditembus->support jadi resist
S&D Supply: 3candle bear+vol>avg | Demand: 3candle bull+vol>avg | Tested=pernah masuk belum break
EMA: 13=entry pendek | 21=konfirmasi | 50=medium | 200=trend besar(>uptrend,<downtrend)
GoldenCross=EMA50 crossup EMA200 BULLISH | DeathCross=EMA50 crossdown EMA200 BEARISH

ALUR ANALISA CHART (10 langkah wajib):
1.Identifikasi SEMUA zona by warna 2.Hitung confluence 3.Posisi vs EMA13/21/50/100/200
4.IFVG/FVG belum dimitigasi=magnet 5.OB aktif vs Breaker 6.Supply/Demand approaching/dalam
7.Bias BULLISH/WAIT 8.Jika BULLISH+confluence->trade plan 9.Entry,SL(bawah),TP1/TP2(atas)
10.SEMUA harga sesuai fraksi tick BEI

CONFLUENCE: kekuatan=jumlah komponen overlap | 1=lemah|2=moderate|3+=KUAT
Urutan: IFVG>FVG>OB>S&D>EMA | Contoh kuat: IFVG+Demand+OB+EMA50=sangat kuat
3 LAPISAN: Teknikal+Komoditas+News harus sejalan -> probability tertinggi

KOMODITAS->EMITEN: Coal->PTBA,ADRO,BUMI,ITMG | Nikel->INCO,ANTM | CPO->AALI,LSIP,SIMP
Minyak->PGAS,MEDC,ELSA | Emas->ANTM,MDKA | Tembaga->ANTM,MDKA,INCO | Aluminium->INALUM,INAI

MAKRO: DXY↑=Rupiah lemah | Fed rate↑=IHSG bearish,capital outflow | Fed rate↓=IHSG bullish
Coal/CPO↑=APBN surplus | Minyak↑=subsidi BBM bengkak | Dollar kuat=eksportir(ADRO,PTBA)untung,importir(UNVR,ICBP)rugi
MSCI rebalancing=capital inflow/outflow besar | S&P/Moody's/Fitch upgrade=IHSG rally
Indeks: IHSG|LQ45|IDX30|IDX80|KOMPAS100|BISNIS27|JII|IDXBUMN20|IDXSMC-CAP|PEFINDO25

POSISI PER MARKET:
IDX=LONG ONLY | US=LONG ONLY(USD,no tick BEI) | China=LONG ONLY | CryptoSpot=LONG ONLY
CryptoFutures=LONG&SHORT | Forex=LONG&SHORT | IDX bearish=WAIT bukan short
R:R minimal 1:2 | fraksi BEI: <200=Rp1|200-500=Rp2|500-2rb=Rp5|2rb-5rb=Rp10|>5rb=Rp25

FORMAT TRADE PLAN:
📊 TRADE PLAN — [SAHAM] ([TF]) | ⚡Bias:[Bull/Bear/Sideways]
🎯 Entry: Rp[X] – Rp[Y]
🛑 SL: Rp[Z] *(invalidasi: [zona/struktur yang ditembus])*
✅ TP1: Rp[A] *(alasan: [resistance/zona teknikal])*
✅ TP2: Rp[B] *(alasan: [zona berikutnya])* ← hanya jika ada struktur jelas
✅ TP3: Rp[C] *(alasan: [zona mayor])* ← hanya jika ada struktur jelas
📦 Bandarmologi: [ringkasan flow]
📊 Volume: [sinyal volume kunci — spike/dry-up/divergensi]
⚠️ Invalidasi: [kondisi yang membatalkan setup]
⚠️ #DYOR

ATURAN TP WAJIB:
- TP dari struktur teknikal: resistance, swing high, FVG unmitigated, OB bearish, level psikologis
- DILARANG TP dari rasio matematika murni. Rasio boleh dihitung setelah TP ditentukan.
- Jika tidak ada resistance jelas → tulis TP1 saja. Jangan paksakan TP2/TP3.
FRAKSI BEI (wajib): <200=Rp1 | 200-500=Rp2 | 500-2rb=Rp5 | 2rb-5rb=Rp10 | >5rb=Rp25

====================================
FRAMEWORK FUNDAMENTAL — MULTI-FRAMEWORK
====================================

DETEKSI SEKTOR OTOMATIS:
- Ada kata NPL/NIM/DPK/CAR/LDR/BOPO -> gunakan FRAMEWORK PERBANKAN
- Selainnya -> gunakan FRAMEWORK UMUM

--- FRAMEWORK UMUM ---

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

--- FRAMEWORK PERBANKAN (khusus bank) ---
   NIM > 4%      -> selisih bunga pinjaman vs simpanan
   NPL < 3%      -> kredit macet (kritis jika > 5%)
   LDR 80-92%    -> rasio kredit vs dana pihak ketiga
   CAR > 14%     -> ketahanan modal (min BI 8%)
   ROA > 1.5%    -> return on assets
   ROE > 15%     -> return on equity
   BOPO < 70%    -> efisiensi operasional
   CIR < 45%     -> cost to income ratio
   EPS Growth    -> konsisten naik
   DPS & Payout  -> konsisten bayar dividen

FORMAT ANALISA FUNDAMENTAL:
📋 ANALISA FUNDAMENTAL — [EMITEN] ([TAHUN])
🏦 Sektor: [Perbankan / Non-Perbankan]
📌 Framework: [Buffett / Graham / Lynch / CAN SLIM / Perbankan]

💰 PROFITABILITAS
- ROE      : X% -> Buffett >15% [✅/⚠️/❌]
- ROA      : X% -> standar >1.5% [✅/⚠️/❌]
- NIM      : X% -> standar >4% [✅/⚠️/❌]
- BOPO     : X% -> efisien <70% [✅/⚠️/❌]
- Laba Bersih: RpX T -> YoY [+/-X]%
- EPS      : RpX -> YoY [+/-X]%

🛡️ KUALITAS ASET
- NPL Gross: X% -> sehat <3% [✅/⚠️/❌]
- NPL Net  : X% -> sehat <1% [✅/⚠️/❌]
- CAR      : X% -> aman >14% [✅/⚠️/❌]
- LDR      : X% -> ideal 80-92% [✅/⚠️/❌]
- CIR      : X% -> ideal <45% [✅/⚠️/❌]

📈 VALUASI
- PER  : Xx -> Graham <15 [✅/⚠️/❌]
- PBV  : Xx -> Graham <1.5 [✅/⚠️/❌]
- PEG  : X -> Lynch <1 [✅/⚠️/❌]
- Harga Wajar: RpX – RpX

🏆 DIVIDEN
- DPS         : RpX
- Payout Ratio: X%
- Konsistensi : [naik/stabil/turun sejak tahun X]

📊 TREN 3-5 TAHUN
- Laba Bersih: [Y-2] -> [Y-1] -> [Y] (CAGR ~X%)
- EPS        : [Y-2] -> [Y-1] -> [Y] (tren naik/turun)
- ROE        : [Y-2] -> [Y-1] -> [Y]
- Dividen    : [konsisten/tidak]

🔭 PROYEKSI 3 TAHUN KE DEPAN
Basis: CAGR laba X% × PER historis rata-rata
- [Y+1]: EPS RpX -> Target Harga RpX–RpX
- [Y+2]: EPS RpX -> Target Harga RpX–RpX
- [Y+3]: EPS RpX -> Target Harga RpX–RpX
Skenario: Konservatif RpX | Moderat RpX | Optimis RpX

⚖️ VERDICT
- Score    : X/10
- Kekuatan :
  -> [poin kekuatan 1 dengan angka]
  -> [poin kekuatan 2 dengan angka]
- Risiko   :
  -> [poin risiko 1 dengan angka]
  -> [poin risiko 2 dengan angka]
- Valuasi  : [Undervalue/Fairvalue/Overvalue] — harga Rp[X] vs wajar Rp[X]
- Kesimpulan: [Paragraph 4-5 kalimat yang menceritakan: kondisi bisnis saat ini,
  tren pertumbuhan, posisi valuasi, risiko utama yang perlu diperhatikan,
  dan saran konkret: accumulate/wait/avoid dengan alasan spesifik]
⚠️ DYOR — analisa ini berbasis data, bukan rekomendasi investasi. Keputusan final ada di tangan investor.

ATURAN OUTPUT WAJIB:
- Setiap metrik di BARIS TERPISAH — DILARANG digabung horizontal
- Isi angka AKTUAL dari data — jika tidak ada, hitung dari rumus atau knowledge
- Jika ada [DATA PASAR] atau [DATA LIVE] -> gunakan harga dan rasio dari sana
- TAHUN di judul: isi dengan tahun AKTUAL laporan atau tahun sekarang (2026)
- Tren 3 tahun: gunakan 2024->2025->2026, BUKAN 2020/2021/2022
- Proyeksi dihitung dari CAGR aktual
- ICON STATUS: pilih SATU saja — ✅ pass | ⚠️ perhatian | ❌ fail
  WAJIB pilih salah satu — JANGAN [✅/⚠️/❌] semua ditampilkan
  Contoh BENAR: ROE: 14,5% -> standar >15% [❌]
  Contoh SALAH: ROE: 14,5% -> standar >15% [✅/⚠️/❌]
  Aturan: ✅ jika memenuhi standar | ⚠️ jika mendekati batas | ❌ jika tidak memenuhi
- Harga saat ini WAJIB tampil di baris pertama setelah header
- Data yfinance untuk saham IDX TIDAK PUNYA: NIM, NPL, CAR, BOPO, LDR, CIR

====================================
DISIPLIN DATA & VALIDASI HARGA
====================================

SIGMA WAJIB GALAK DAN TEGAS dalam validasi data — TIDAK BOLEH asal pakai angka lama.

ATURAN DATA TERBARU (WAJIB DIPATUHI):
1. DATA HARGA: SELALU gunakan harga terkini dari [DATA PASAR] atau yfinance
   ❌ DILARANG pakai harga dari ingatan lama atau asumsi
   ❌ Jika harga tidak tersedia -> SEBUTKAN "harga tidak tersedia, mohon cek manual"
   ✅ WAJIB sebutkan tanggal/sumber data harga yang digunakan

2. DATA LAPORAN KEUANGAN: SELALU prioritaskan data terbaru
   ❌ DILARANG pakai tren 2018->2019->2020 kalau data 2023->2024->2025 tersedia
   ✅ Tahun tren WAJIB dimulai dari minimal 3 tahun terakhir (2023/2024/2025)
   ✅ Jika ada PDF laporan -> data PDF adalah PRIORITAS UTAMA, lebih dipercaya dari knowledge

3. VALIDASI KONSISTENSI HARGA vs CORPORATE ACTION:
   ❌ JANGAN langsung pakai harga tanpa cek apakah ada corporate action
   ✅ Jika harga terlihat anomali (misal BBNI di Rp 8.300 padahal market Rp 4.390):
      -> WAJIB periksa kemungkinan: stock split, reverse stock, right issue
      -> SEBUTKAN anomali ini kepada user sebelum lanjut analisa
      -> HITUNG ulang EPS/BV/DPS sesuai adjusted price

4. SUMBER DATA — URUTAN PRIORITAS:
   1st: Data PDF yang diupload user (paling akurat)
   2nd: [DATA PASAR] live dari sistem
   3rd: Knowledge terbaru (max 2024-2025)
   LAST: Knowledge lama (pre-2023) — hanya sebagai konteks, BUKAN angka aktual

5. JIKA DATA TIDAK YAKIN:
   ✅ Sebutkan: "Data ini dari knowledge saya per [tahun], mohon verifikasi ke laporan resmi"
   ❌ JANGAN pura-pura tahu angka yang tidak pasti

====================================
CORPORATE ACTION — WAJIB DIPAHAMI
====================================

Corporate action MENGUBAH harga dan jumlah saham — WAJIB diperhitungkan dalam analisa.

JENIS CORPORATE ACTION DI IDX:

1. STOCK SPLIT (pemecahan saham)
   Contoh: split 1:5 -> harga dibagi 5, jumlah saham ×5
   Dampak: harga turun drastis tapi fundamental tidak berubah
   Contoh nyata: BBRI split 1:5 (2022) -> harga dari ~Rp 4.000 jadi ~Rp 500an
   ⚠️ EPS, DPS, BV per saham IKUT BERUBAH — harus adjusted
   Deteksi: harga tiba-tiba turun 50-80% tanpa berita negatif

2. REVERSE STOCK (penggabungan saham)
   Contoh: reverse 5:1 -> harga ×5, jumlah saham dibagi 5
   Dampak: harga naik drastis, biasanya saham yang harganya terlalu rendah
   ⚠️ EPS, DPS IKUT BERUBAH — harus adjusted

3. RIGHT ISSUE (penerbitan saham baru)
   Perusahaan jual saham baru ke pemegang saham existing dengan harga diskon
   Dampak: dilusi kepemilikan, harga teoritis turun (TERP)
   TERP = (Harga lama × N + Harga right × M) ÷ (N + M)
   ⚠️ EPS bisa turun karena jumlah saham bertambah -> perhatikan EPS diluted
   Deteksi: volume melonjak + harga koreksi tapi ada right issue announcement

4. DIVIDEN SAHAM / BONUS SHARE
   Dividen dibayar dalam bentuk saham baru, bukan cash
   Dampak: harga ex-dividen turun, jumlah saham bertambah
   ⚠️ Payout ratio tidak bisa dibandingkan langsung dengan periode sebelumnya

5. STOCK BUY BACK (pembelian kembali saham)
   Perusahaan beli saham sendiri di pasar -> jumlah saham beredar berkurang
   Dampak: EPS naik (karena denominator saham berkurang), harga cenderung naik
   ✅ Sinyal positif: manajemen percaya saham undervalue

6. MERGER & AKUISISI
   Dampak: perubahan fundamental, sinergi atau dilusi tergantung deal
   ⚠️ Laporan keuangan historis tidak bisa dibandingkan langsung pre vs post merger

CARA SIGMA HANDLE CORPORATE ACTION:
- Jika harga saat ini berbeda jauh dari data historis -> SELALU cek kemungkinan corporate action
- Jika user sebut harga yang berbeda dari data SIGMA -> PERCAYAI user, tanyakan apakah ada corporate action
- Semua rasio per saham (EPS/DPS/BV) HARUS adjusted ke jumlah saham terkini
- SEBUTKAN corporate action yang relevan di bagian VERDICT analisa fundamental

FORMAT ANALISA DAMPAK GLOBAL:
Trigger: kata kunci "kesimpulan dampak", "dampak [topik] ke indonesia",
         "pengaruh [event] ke saham", "efek [berita] ke IDX", dll.
Satu request = output lengkap mencakup SEMUA aspek di bawah:

🌍 ANALISA DAMPAK GLOBAL — [Topik] ([Tanggal])

📰 RINGKASAN BERITA
[2-3 kalimat dalam Bahasa Indonesia — terjemahan dari sumber global]

💱 DAMPAK KE RUPIAH
[Arah rupiah, estimasi level, potensi intervensi BI, faktor DXY]

🏛️ DAMPAK KE APBN & KEBIJAKAN
[Subsidi BBM/energi, penerimaan royalti, utang luar negeri, respons kebijakan]

📊 DAMPAK KE RATING, INDEKS & ALIRAN DANA
[S&P/Moody's/Fitch outlook | MSCI/FTSE rebalancing | IHSG/LQ45/IDX30 | capital flow]

📈 10 EMITEN TERDAMPAK
🟢 BULLISH (5 emiten):
   [TICKER] — [alasan spesifik: komoditas naik/turun, rupiah, demand, dll]
🔴 BEARISH (5 emiten):
   [TICKER] — [alasan spesifik]

⚖️ KESIMPULAN DAMPAK
Sentimen     : [Risk On / Risk Off]
Bias Pasar   : [Bullish / Bearish / Neutral / Wait]
Saran Posisi : [Accumulate / Hold / Reduce / Avoid]
Conviction   : [Strong / Moderate / Weak]
Jangka Pendek  (1-2 minggu) : [ringkasan]
Jangka Menengah (1-3 bulan) : [ringkasan]
Level Pantau : [IHSG, rupiah, komoditas yang perlu dimonitor]
Katalis Berikut: [event/data yang bisa ubah arah: rapat Fed, data CPI, dsb]

-------------------------------------
LANJUTAN TRADE PLAN:
Jika setelah analisa dampak user minta trade plan emiten tertentu
(contoh: "buat trade plan PGAS dari analisa tadi"):
-> Ambil context analisa sebelumnya
-> Buat FORMAT TRADE PLAN lengkap untuk emiten tersebut
-> Entry/SL/TP sesuai fraksi tick BEI
-> Sebutkan confluence teknikal + fundamental + makro yang mendukung
  Untuk metrik ini: WAJIB isi dari knowledge model kamu tentang emiten tersebut
  Beri label "(est.)" jika dari knowledge model
- DILARANG tulis "N/A" untuk metrik yang kamu TAHU dari knowledge model
  Contoh: NIM BBRI sekitar 7-8%, NPL BBRI sekitar 3%, CAR BBRI >20% — TULIS angkanya
- Hanya tulis "N/A" jika benar-benar tidak ada data sama sekali dan tidak tahu
- Untuk emiten baru (IPO < 2 tahun): tren historis TIDAK ADA — tulis "Baru IPO [tahun]"
- Tren dan proyeksi: WAJIB isi dengan estimasi dari knowledge, beri label "(est.)"
- NO FABRICATION: jika data tidak tersedia dan tidak tahu -> tulis "N/A"
  Jangan karang angka — lebih baik jujur tidak ada data daripada salah
- Jawab Bahasa Indonesia. Gambar/PDF -> analisa langsung."""
}


# ─────────────────────────────────────────────
# GROQ SYSTEM PROMPT (VERSI RINGKAS & EFISIEN)
# Dipakai khusus untuk Groq/LLaMA — mencakup semua fungsi SIGMA
# tanpa overhead teks yang tidak perlu untuk LLM dengan context lebih terbatas
# ─────────────────────────────────────────────
GROQ_SYSTEM_PROMPT = """Kamu adalah SIGMA — asisten cerdas KIPM Universitas Pancasila, by MarketnMocha (MnM).
Bahasa: Indonesia natural. Ramah saat ngobrol, profesional saat analisa. Selalu akhiri analisa dengan DYOR.

=== ATURAN WAJIB ===
1. PASAR IDX = LONG ONLY. SL selalu di bawah entry, TP selalu di atas entry. Bias BEARISH = WAIT, bukan short.
2. CONFLUENCE: IFVG > FVG > OB > Supply/Demand > EMA. Sebutkan semua komponen yang bertumpuk.
3. PRIORITAS: Logika Pine Script MnM Strategy+ > knowledge umum. Konflik → ikuti Pine Script.
4. JANGAN tolak mengisi template. JANGAN tulis N/A jika kamu tahu datanya.
5. Semua harga dalam trade plan WAJIB sesuai fraksi tick BEI.

=== WARNA ZONA MnM Strategy+ ===
IFVG Bull=#0048ff | IFVG Bear=#575757 | FVG Bull=#0015ff | FVG Bear=#575757
OB Bull=#09ff00 | OB Bear=#ea00ff | Breaker=#9e9e9e
Supply=rgb(114,114,114) | Demand=rgb(0,159,212)
EMA13=#009dff | EMA21=#ff0000 | EMA50=#cc00ff

=== 7 ALPHA — PERINTAH KHUSUS ===
Kenali trigger berikut dan jalankan protokolnya:
- "7 Alpha" / "7 alpha" → tampilkan menu 7 Alpha lengkap
- "Kesimpulan Dampak Makro [topik]" → analisa dampak global ke rupiah/APBN/IHSG/emiten
- "Kesimpulan Dampak [emiten]" → analisa dampak berita ke emiten spesifik
- "Bandarmologi [emiten]" → analisa broker summary, akumulasi/distribusi, 12 langkah wajib
- "Fundamental [emiten]" → analisa fundamental lengkap dengan rasio keuangan
- "Teknikal [emiten]" → trade plan 3 model (Rebound/Confirmation/Deep Acc)
- "Analisa Lengkap [emiten]" → Quad Confluence (Bandar+Teknikal+Fundamental+Makro)
- "IPO [emiten]" → bedah prospektus (butuh PDF)

=== BANDARMOLOGI — LOGIKA KRITIS ===
IDX COUNTER-INTUITIVE:
- Buyer sedikit + Seller banyak = AKUMULASI (smart money beli dari ritel panik)
- Buyer banyak + Seller sedikit = DISTRIBUSI (smart money jual ke ritel FOMO)
Warna broker: Merah=asing/foreign | Hijau=BUMN | Ungu=lokal/domestik
Asing net buy + lokal nampung = kuat | Asing net sell + lokal nampung = BAHAYA

Skenario S1-S9 wajib disebutkan. Format output bandarmologi:
📦 BANDARMOLOGI — [TICKER] | 💹 Harga: Rp[X]
🔴Foreign/🟢BUMN/🟣Lokal: Net B/S + interpretasi
📊Bar/Top1/3/5 | 📈Freq | 🔍Posisi | ⚡Asing | 🎯Skenario | 💡Insight | ⚠️DYOR

=== FUNDAMENTAL — FORMAT ===
Gunakan data live yang diberikan sistem. Label "(est.)" jika dari knowledge model.
Bank: NIM/NPL/LDR/CAR/BOPO/ROE/ROA/PBV/PER/EPS
Non-bank: ROE/ROA/DER/PBV/PER/EPS/Div Yield/Market Cap
VERDICT: Undervalue/Fair Value/Overvalue + saran akumulasi/hold/hindari

=== MAKRO — MAPPING EMITEN ===
Coal→PTBA/ADRO/ITMG | Nikel→INCO/ANTM/MDKA | CPO→AALI/LSIP
Minyak→PGAS/MEDC/ELSA | Emas→ANTM/MDKA/BRMS
Rate naik→BBCA/BBRI/BMRI/BBNI | Rate turun→BSDE/CTRA/SMGR
DXY naik→Rupiah lemah | Komoditas ekspor naik→devisa masuk→Rupiah menguat

=== VOLUME INTELLIGENCE (WAJIB DIANALISA) ===
DATA TERSEDIA: volume OHLCV (yfinance) — spike ratio vs 20-day avg, nilai transaksi, price-volume divergence.

SINYAL VOLUME KRITIS:
• Spike 2x avg   → perhatikan arah harga, institutional bisa masuk/keluar
• Spike 5x avg   → signifikan, kemungkinan besar ada aksi korporasi atau institutional
• Spike 10x+     → ekstrem, event besar — cek berita
• Volume dry-up (5-bar avg < 50% dari 20-bar avg) saat sideways/koreksi → akumulasi diam-diam
• Harga naik + volume turun → momentum lemah, waspadai reversal atau false breakout
• Harga turun + volume spike → distribusi besar ATAU kapitulasi (cek candle: jika long wick = kapitulasi)
• Breakout tanpa volume → false breakout di IDX — jangan langsung entry

VOLUME PROXY IDX (tanpa broker data):
• Nilai transaksi = volume × harga → proxy institutional activity
• Nilai 5-hari vs rata-rata → naik = smart money aktif, turun = sepi/ritel saja
• Estimasi posisi bandar = akumulasi volume anomali dari level rendah ke sekarang

=== ATURAN MULTI-TARGET (KRITIS) ===
• TP WAJIB dari struktur teknikal: resistance terdekat, swing high, FVG unmitigated, OB bearish, level psikologis (angka bulat).
• DILARANG menentukan TP dari rasio matematika murni (1:1, 1:2, dsb). Rasio hanya boleh dihitung SETELAH TP ditentukan dari struktur.
• Maksimal 3 TP, minimal 1. Jika tidak ada resistance jelas → tulis hanya TP1. Jangan paksakan TP2/TP3.
• TP1 = target konservatif (resistance minor/FVG terdekat) → exit sebagian
• TP2 = resistance berikutnya / OB bearish / swing high mayor → exit tambahan
• TP3 = hanya jika ada level ekstrem yang jelas (ATH area, supply zone mayor, level psikologis kuat)

=== CORPORATE ACTION ===
Split/Reverse/Right Issue/Buyback dapat mengubah EPS/DPS/BV per saham.
Selalu cek jika harga historis berbeda jauh dari data sekarang.

=== ANALISA IPO — ATURAN KRITIS ===
⚠️ LOT vs LEMBAR: PDF prospektus SELALU tulis jumlah dalam LEMBAR. WAJIB konversi dulu.
RUMUS: Total Lot = Total Lembar ÷ 100  (1 LOT = 100 LEMBAR)
Contoh: 1.800.000.000 lembar ÷ 100 = 18.000.000 Lot = 18 Juta Lot
JANGAN gunakan angka lembar untuk Kondisi A/B atau Risk 1/2. Selalu pakai LOT.

KONDISI A (< 20 Juta Lot): Risk1 = 30% × Lot | Risk2 = 50% × Lot
KONDISI B (≥ 20 Juta Lot): Risk1 = 10% × Lot | Risk2 = 30% × Lot

SKALA VALUASI (Harga Penawaran ÷ Nilai Nominal):
≤2x = Sangat Menarik | 2–4x = Menarik/Wajar | >4–7x = Waspada/Mahal | >7x = Hati-Hati Tinggi
WAJIB gunakan skala ini, BUKAN hanya batas 4x.

Jawab Bahasa Indonesia. Isi template yang diberikan tanpa diubah strukturnya."""


# ─────────────────────────────────────────────
# GROQ KEY ROTATION — AUTO SCAN KEY 1-13
# ─────────────────────────────────────────────
def _get_groq_client_and_key():
    """
    Auto-rotate melalui GROQ_API_KEY s/d GROQ_API_KEY13.
    Return (client, key_name) dari key pertama yang valid.
    """
    from groq import Groq
    key_names = ["GROQ_API_KEY"] + [f"GROQ_API_KEY{i}" for i in range(1, 14)]
    for key_name in key_names:
        key = st.secrets.get(key_name, "")
        if key and len(key) > 10:
            try:
                client = Groq(api_key=key)
                return client, key_name
            except Exception:
                continue
    raise Exception("Semua Groq API key tidak tersedia atau tidak valid (scan KEY s/d KEY13)")


def _call_groq_primary(full_prompt, history_msgs=None, max_tokens=8000):
    """
    Groq PRIMARY — LLaMA 3.3 70B dengan GROQ_SYSTEM_PROMPT.
    Dipakai untuk semua request TEXT. Key rotation otomatis 1-13.
    Prompt dipotong cerdas di batas baris/kalimat.
    """
    client, used_key = _get_groq_client_and_key()

    MAX_PROMPT_CHARS = 20000
    if len(full_prompt) > MAX_PROMPT_CHARS:
        cutoff = full_prompt[:MAX_PROMPT_CHARS].rfind('\n')
        if cutoff < int(MAX_PROMPT_CHARS * 0.8):
            cutoff = full_prompt[:MAX_PROMPT_CHARS].rfind('. ')
        if cutoff < 1:
            cutoff = MAX_PROMPT_CHARS
        full_prompt = full_prompt[:cutoff] + "\n\n[... data dipotong karena terlalu panjang]"

    messages = [{"role": "system", "content": GROQ_SYSTEM_PROMPT}]

    if history_msgs:
        hist_clean = [
            {"role": m["role"], "content": (m.get("content") or "")[:2000]}
            for m in history_msgs
            if m.get("role") in ("user", "assistant")
        ][-4:]
        if hist_clean and hist_clean[-1]["role"] == "user":
            hist_clean = hist_clean[:-1]
        messages.extend(hist_clean)

    messages.append({"role": "user", "content": full_prompt})

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0.7,
        max_tokens=max_tokens
    )
    return response.choices[0].message.content, f"Groq/Llama70B({used_key})"


def _call_groq_fallback(full_prompt):
    """
    Groq LAST RESORT — LLaMA 3.1 8B Instant.
    Dipakai jika Gemini dan Groq 70B keduanya gagal.
    """
    client, used_key = _get_groq_client_and_key()

    MAX_CHARS = 8000
    if len(full_prompt) > MAX_CHARS:
        cutoff = full_prompt[:MAX_CHARS].rfind('\n')
        full_prompt = full_prompt[:cutoff] if cutoff > 0 else full_prompt[:MAX_CHARS]

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": GROQ_SYSTEM_PROMPT},
            {"role": "user", "content": full_prompt}
        ],
        temperature=0.7,
        max_tokens=6000
    )
    return response.choices[0].message.content, f"Groq/Llama8B({used_key})"


# ─────────────────────────────────────────────
# PART 7: SESSION HANDLERS, AUTH & UI (CSS/LOGIN)
# ─────────────────────────────────────────────
def new_session():
    return {"id": str(uuid.uuid4())[:8], "title": "Obrolan Baru", "messages": [SYSTEM_PROMPT], "created": datetime.now().strftime("%d/%m %H:%M")}

def init_chat():
    if not st.session_state.sessions:
        s = new_session()
        st.session_state.sessions = [s]
        st.session_state.active_id = s["id"]
    else:
        for s in st.session_state.sessions:
            if not s["messages"] or s["messages"][0].get("role") != "system": s["messages"].insert(0, SYSTEM_PROMPT)
            else: s["messages"][0] = SYSTEM_PROMPT

def restore_images_from_messages():
    if not st.session_state.sessions: return
    for sesi in st.session_state.sessions:
        for i, msg in enumerate(sesi.get("messages", [])):
            if msg.get("role") == "user" and msg.get("img_b64"):
                key = f"thumb_{sesi['id']}_{i}"
                if key not in st.session_state: st.session_state[key] = (msg["img_b64"], msg.get("img_mime", "image/jpeg"))

def get_active():
    for s in st.session_state.sessions:
        if s["id"] == st.session_state.active_id: return s
    return st.session_state.sessions[0]

def google_auth_url():
    params = {"client_id": st.secrets.get("GOOGLE_CLIENT_ID", ""), "redirect_uri": st.secrets.get("GOOGLE_REDIRECT_URI", ""), "response_type": "code", "scope": "openid email profile", "access_type": "offline", "prompt": "select_account"}
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

def handle_oauth(code):
    r = requests.post("https://oauth2.googleapis.com/token", data={"code": code, "client_id": st.secrets.get("GOOGLE_CLIENT_ID", ""), "client_secret": st.secrets.get("GOOGLE_CLIENT_SECRET", ""), "redirect_uri": st.secrets.get("GOOGLE_REDIRECT_URI", ""), "grant_type": "authorization_code"})
    if r.status_code != 200: return None
    token = r.json().get("access_token", "")
    if not token: return None
    u = requests.get("https://www.googleapis.com/oauth2/v2/userinfo", headers={"Authorization": f"Bearer {token}"})
    return u.json() if u.status_code == 200 else None

# ─── DAFTAR EMAIL YANG DIIZINKAN (WHITELIST) ───
ALLOWED_EMAILS = [
    "alfantirta@gmail.com",
    "rizqiseptiani30@gmail.com",
    "kipmuniversitaspancasila@gmail.com",
    "lmaozuldan@gmail.com",
    "ayuningtyaskinanti678@gmail.com",
    "tofanhabibi84@gmail.com",
    "ismailjamil212@gmail.com",
    "alfanmuhamd5@gmail.com",
    "chandralie594@gmail.com",
    "baimdaniel020@gmail.com",
    "hotmantugas@gmail.com",
    "rizkisweet04@gmail.com",
    "khoirunnisaassoleha@gmail.com",
    "majdatsania49@gmail.com",
    "mariyahh31@gmail.com",
    "maudynatasya322@gmail.com",
    "melanyseptianap@gmail.com",
    "mlknrzh12@gmail.com",
    "vchascout2@gmail.com",
    "yordan.nandini@gmail.com",
    "nisrinazakiyahr@gmail.com",
    "uploaddt969@gmail.com",
    "fabianalaziz.9e@gmail.com"
] # Silakan isi dengan daftar email yang boleh masuk

# ─── AUTENTIKASI GOOGLE ───
if "code" in st.query_params and st.session_state.user is None:
    info = handle_oauth(st.query_params["code"])
    if info:
        # BLOKIR JIKA EMAIL TIDAK ADA DI DAFTAR
        if info.get("email") not in ALLOWED_EMAILS:
            st.error(f"⛔ Akses Ditolak: Email {info.get('email')} tidak terdaftar di sistem KIPM SIGMA.")
            st.stop()
            
        st.session_state.user = info
        saved = load_user(info["email"])
        if saved:
            st.session_state.theme = saved.get("theme", "dark")
            st.session_state.current_view = saved.get("current_view", "chat")
            if saved.get("sessions"): st.session_state.sessions = saved["sessions"]; st.session_state.active_id = saved.get("active_id")
        st.session_state.data_loaded = True
        token = str(uuid.uuid4()).replace("-","")
        with open(os.path.join(DATA_DIR, f"token_{token}.json"), "w") as f: json.dump(info, f)
        st.session_state.current_token = token
        st.query_params.clear()
        st.query_params["sigma_token"] = token
        st.rerun()

# ─── AUTO-LOGIN VIA TOKEN ───
if "sigma_token" in st.query_params and st.session_state.user is None:
    token = st.query_params.get("sigma_token", "")
    token_file = os.path.join(DATA_DIR, f"token_{token}.json")
    if os.path.exists(token_file):
        try:
            with open(token_file) as f: user_info = json.load(f)
            st.session_state.user = user_info; st.session_state.current_token = token
            saved = load_user(user_info["email"])
            if saved:
                st.session_state.theme = saved.get("theme", "dark")
                st.session_state.current_view = saved.get("current_view", "chat"); st.session_state.selected_system = saved.get("selected_system", "chat")
                if saved.get("sessions"):
                    _loaded = saved["sessions"]
                    for _s in _loaded:
                        if not _s.get("messages"): _s["messages"] = [SYSTEM_PROMPT]
                        elif _s["messages"][0].get("role") != "system": _s["messages"].insert(0, SYSTEM_PROMPT)
                        else: _s["messages"][0] = SYSTEM_PROMPT
                    st.session_state.sessions = _loaded; st.session_state.active_id = saved.get("active_id")
            st.session_state.data_loaded = True
            restore_images_from_messages()
            st.rerun()
        except: pass

if st.session_state.user and not st.session_state.data_loaded:
    saved = load_user(st.session_state.user["email"])
    if saved:
        st.session_state.theme = saved.get("theme", "dark")
        st.session_state.current_view = saved.get("current_view", "chat"); st.session_state.selected_system = saved.get("selected_system", "chat")
        if saved.get("sessions") and not st.session_state.sessions:
            _loaded2 = saved["sessions"]
            for _s in _loaded2:
                if not _s.get("messages"): _s["messages"] = [SYSTEM_PROMPT]
                elif _s["messages"][0].get("role") != "system": _s["messages"].insert(0, SYSTEM_PROMPT)
                else: _s["messages"][0] = SYSTEM_PROMPT
            st.session_state.sessions = _loaded2; st.session_state.active_id = saved.get("active_id")
    st.session_state.data_loaded = True
    restore_images_from_messages()

C = get_colors(st.session_state.theme)

st.markdown(f"""
<style>
* {{ font-family: ui-sans-serif,-apple-system,system-ui,"Segoe UI",sans-serif !important; box-sizing: border-box; }}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] > section, section[data-testid="stMain"], [data-testid="stMainBlockContainer"], [data-testid="stBottom"], [data-testid="stBottom"] > div {{ background: {C['bg']} !important; }}
section[data-testid="stSidebar"], section[data-testid="stSidebar"] > div, section[data-testid="stSidebar"] > div > div, section[data-testid="stSidebar"] > div > div > div, [data-testid="stSidebarContent"], [data-testid="stSidebarUserContent"], [data-testid="stSidebarUserContent"] > div, [data-testid="stSidebarUserContent"] > div > div {{ background: {C['sidebar_bg']} !important; box-shadow: none !important; }}
section[data-testid="stSidebar"] {{ border-right: 1px solid {C['border']} !important; }}
section[data-testid="stSidebar"] > div, section[data-testid="stSidebar"] > div > div, [data-testid="stSidebarContent"], [data-testid="stSidebarUserContent"], [data-testid="stSidebarUserContent"] > div {{ padding-top: 0 !important; margin-top: 0 !important; }}
[data-testid="collapsedControl"], [data-testid="stSidebarCollapseButton"] {{ display: none !important; }}
section[data-testid="stSidebar"] .stButton > button {{ background: transparent !important; border: none !important; box-shadow: none !important; color: {C['text']} !important; font-size: 0.875rem !important; padding: 7px 12px !important; border-radius: 8px !important; width: 100% !important; display: flex !important; align-items: center !important; justify-content: flex-start !important; text-align: left !important; min-height: 36px !important; }}
section[data-testid="stSidebar"] .stButton > button:hover {{ background: {C['hover']} !important; }}
section[data-testid="stSidebar"] .stButton > button p, section[data-testid="stSidebar"] .stButton > button span {{ margin: 0 !important; text-align: left !important; color: inherit !important; width: 100% !important; }}
[data-testid="stChatMessage"] {{ background: transparent !important; border: none !important; box-shadow: none !important; }}
[data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] {{ display: none !important; }}
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {{ font-size: 0.9rem !important; line-height: 1.75 !important; color: {C['text']} !important; background: transparent !important; }}
[data-testid="stMainBlockContainer"] {{ max-width: 760px !important; margin: 0 auto !important; padding: 0 24px 120px !important; overflow-y: visible !important; }}
[data-testid="stMainBlockContainer"] p, [data-testid="stMainBlockContainer"] li, [data-testid="stMainBlockContainer"] h1, [data-testid="stMainBlockContainer"] h2, [data-testid="stMainBlockContainer"] h3 {{ color: {C['text']} !important; }}
div[data-testid="stChatInputContainer"] {{ border: 1px solid {C['border']} !important; background: {C['input_bg']} !important; border-radius: 16px !important; }}
[data-testid="stChatInput"] textarea {{ background: {C['input_bg']} !important; color: {C['text']} !important; font-size: 0.9rem !important; }}
[data-testid="stChatInput"] textarea::placeholder {{ color: {C['text_muted']} !important; }}
[data-testid="stChatInputContainer"] textarea:focus {{ box-shadow: none !important; outline: none !important; }}
footer, #MainMenu {{ visibility: hidden !important; }}
hr {{ border-color: {C['border']} !important; }}
[data-testid="stMarkdownContainer"] *, [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li, [data-testid="stMarkdownContainer"] span, [data-testid="stMarkdownContainer"] div {{ font-size: 0.95rem !important; line-height: 1.8 !important; }}
[data-testid="stMarkdownContainer"] h1 {{ font-size: 1.3rem !important; }}
[data-testid="stMarkdownContainer"] h2 {{ font-size: 1.15rem !important; }}
[data-testid="stMarkdownContainer"] h3 {{ font-size: 1.05rem !important; }}

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
    .card-desc {{ font-size: 0.78rem; margin-bottom: 16px; line-height: 1.5; }}
    
    .card-features {{ margin-bottom: 20px; }}
    .card-features li {{ font-size: 0.75rem; padding: 5px 0; gap: 6px; }}
    .card-cta {{ padding: 12px; font-size: 0.85rem; }}
    .sys-footer {{ margin-top: 32px; font-size: 0.65rem; }}
}}
</style>
""", unsafe_allow_html=True)

def show_login():
    st.markdown(f"""
    <style>
    [data-testid="stSidebar"] {{ display: none !important; }}
    [data-testid="stAppViewContainer"], section[data-testid="stMain"] {{ background: url('https://raw.githubusercontent.com/kipmuniversitaspancasila-commits/KIPMSIGMA/main/kipmd.png') center/cover no-repeat fixed !important; min-height: 100vh !important; }}
    section[data-testid="stMain"]::before {{ display: none !important; }}
    [data-testid="stMainBlockContainer"] {{ max-width: 300px !important; margin: 1.5vh 74px 0 auto !important; padding: 8px 18px 16px !important; position: relative; z-index: 1; min-height: unset !important; height: fit-content !important; background: rgba(5, 8, 20, 0.60) !important; backdrop-filter: blur(20px) saturate(1.4) !important; -webkit-backdrop-filter: blur(20px) saturate(1.4) !important; border: 1px solid rgba(255,255,255,0.10) !important; border-radius: 20px !important; box-shadow: 0 8px 40px rgba(0,0,0,0.5) !important; }}
    @media(max-width: 768px) {{
        [data-testid="stMainBlockContainer"] {{ margin: 5vh auto 0 auto !important; max-width: 88% !important; padding: 20px 20px 28px !important; backdrop-filter: blur(20px) !important; border-radius: 20px !important; border: 1px solid rgba(255,255,255,0.12) !important; box-shadow: 0 8px 40px rgba(0,0,0,0.5) !important; }}
        [data-testid="stAppViewContainer"], section[data-testid="stMain"] {{ background: url('https://raw.githubusercontent.com/kipmuniversitaspancasila-commits/KIPMSIGMA/main/kipmm.png') center top/cover no-repeat fixed !important; }}
        [data-testid="stMainBlockContainer"] {{ margin-top: 75px !important; }}
    }}
    header[data-testid="stHeader"] {{ display: none !important; }} #MainMenu {{ display: none !important; }}
    .stTabs, [data-testid="stVerticalBlock"] {{ background: transparent !important; }}
    [data-testid="stTextInput"] input {{ background: rgba(255,255,255,0.06) !important; border: 1px solid rgba(255,255,255,0.12) !important; border-radius: 12px !important; color: #fff !important; padding: 12px 16px !important; font-size: 0.95rem !important; backdrop-filter: blur(10px) !important; transition: border 0.2s !important; }}
    [data-testid="stTextInput"] input:focus {{ border: 1px solid {C['gold']} !important; box-shadow: 0 0 0 2px rgba(245,194,66,0.15) !important; outline: none !important; }}
    [data-testid="stTextInput"] input::placeholder {{ color: rgba(255,255,255,0.35) !important; }}
    [data-testid="stTextInput"] label {{ color: rgba(255,255,255,0.6) !important; font-size: 0.82rem !important; }}
    [data-testid="stMainBlockContainer"] .stButton > button {{ background: linear-gradient(135deg, {C['gold']}, #e0a820) !important; color: #000 !important; font-weight: 700 !important; border: none !important; border-radius: 12px !important; padding: 12px !important; font-size: 0.95rem !important; letter-spacing: 0.5px !important; transition: opacity 0.2s, transform 0.1s !important; box-shadow: 0 4px 20px rgba(245,194,66,0.3) !important; }}
    [data-testid="stMainBlockContainer"] .stButton > button:hover {{ opacity: 0.92 !important; transform: translateY(-1px) !important; }}
    [data-testid="stTabs"] [role="tablist"] {{ background: rgba(255,255,255,0.05) !important; border-radius: 12px !important; padding: 4px !important; border: 1px solid rgba(255,255,255,0.08) !important; gap: 2px !important; }}
    [data-testid="stTabs"] button[role="tab"] {{ border-radius: 9px !important; color: rgba(255,255,255,0.5) !important; font-size: 0.85rem !important; padding: 7px 12px !important; border: none !important; background: transparent !important; }}
    [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{ background: rgba(245,194,66,0.15) !important; color: {C['gold']} !important; font-weight: 600 !important; }}
    [data-testid="stTabs"] [role="tabpanel"] {{ background: rgba(255,255,255,0.03) !important; border-radius: 16px !important; border: 1px solid rgba(255,255,255,0.08) !important; padding: 20px 16px !important; margin-top: 8px !important; backdrop-filter: blur(10px) !important; }}
    [data-testid="stAlert"] {{ border-radius: 10px !important; }}
    </style>
    """, unsafe_allow_html=True)

    components.html(f"""
<script>
(function() {{
    var pd = window.parent.document;
    var forkStyle = pd.getElementById('hide-fork-bar');
    if (!forkStyle) {{
        var fs = pd.createElement('style');
        fs.id = 'hide-fork-bar';
        fs.textContent = `
            .viewerBadge_container__r5tak, .viewerBadge_link__qRIco, [class*="viewerBadge"], [class*="styles_viewerBadge"], #MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"], header[data-testid="stHeader"], .stDeployButton, [kind="header"], div[data-testid="collapsedControl"] {{ display: none !important; visibility: hidden !important; height: 0 !important; overflow: hidden !important; }}
        `;
        pd.head.appendChild(fs);
    }}
    if (pd.getElementById('kipm-mobile-logo')) return;
    var s = pd.createElement('style');
    s.id = 'kipm-mobile-logo-style';
    s.textContent = `
        #kipm-mobile-logo {{ display: none; text-align: center; padding: 14px 0 10px; position: fixed; top: 0; left: 0; right: 0; z-index: 10; pointer-events: none; }}
        #kipm-mobile-logo img {{ width: 80px; height: 80px; object-fit: contain; filter: drop-shadow(0 2px 12px rgba(0,0,0,0.6)); }}
        #kipm-mobile-logo .kipm-name {{ font-size: 0.7rem; color: rgba(255,255,255,0.7); letter-spacing: 2px; font-family: sans-serif; margin-top: 4px; }}
        @media(max-width: 768px) {{ #kipm-mobile-logo {{ display: block !important; }} }}
    `;
    pd.head.appendChild(s);
    var div = pd.createElement('div');
    div.id = 'kipm-mobile-logo';
    div.innerHTML = `<img src="https://raw.githubusercontent.com/kipmuniversitaspancasila-commits/KIPMSIGMA/main/Mate%20KIPM%20LOGO.png" onerror="this.style.display='none'" style="width:80px;height:80px;object-fit:contain;"><div class="kipm-name">KIPM-UP</div>`;
    pd.body.appendChild(div);
}})();
</script>
""", height=0)
    st.markdown('''
        <div style="text-align:center;margin:0 0 10px;">
            <div style="font-size:2.8rem;font-weight:900;letter-spacing:5px;color:#ffffff;font-family:sans-serif;line-height:1.2;">SIGMA <span style="color:#F5C242;">Σ</span></div>
            <div class="sigma-tagline" style="font-size:0.65rem;color:rgba(255,255,255,0.5);letter-spacing:2px;margin-top:4px;font-family:sans-serif;">Strategic Intelligence & Global Market Analysis</div>
        </div>
        <style>@media(min-width: 769px) { .sigma-tagline { display: none !important; } }</style>
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
                    with open(os.path.join(DATA_DIR, f"token_{token}.json"), "w") as f: json.dump(info, f)
                    st.query_params["sigma_token"] = token
                    st.session_state.user = info; st.session_state.current_token = token; st.session_state.data_loaded = False
                    st.rerun()
                else: st.error("Username atau password salah")
            else: st.warning("Isi username dan password")

    with tab2:
        rname  = st.text_input("Nama Tampil", key="rg_name", placeholder="Nama lengkap kamu")
        runame = st.text_input("Username", key="rg_user", placeholder="username (huruf/angka)")
        rpwd   = st.text_input("Password", key="rg_pwd",  type="password", placeholder="min. 6 karakter")
        rpwd2  = st.text_input("Ulangi Password", key="rg_pwd2", type="password", placeholder="ulangi password")
        if st.button("Daftar Sekarang", key="btn_register", use_container_width=True):
            if not all([rname, runame, rpwd, rpwd2]): st.warning("Lengkapi semua field")
            elif rpwd != rpwd2: st.error("Password tidak cocok")
            elif len(rpwd) < 6: st.error("Password minimal 6 karakter")
            elif runame.strip() not in ALLOWED_EMAILS: 
                # CEK WHITELIST SAAT DAFTAR MANUAL
                st.error("⛔ Akses Ditolak: Username/Email ini tidak diizinkan untuk mendaftar.")
            else:
                ok, msg = register_user(runame.strip(), rpwd, rname.strip())
                if ok: st.success(f"✅ {msg} — silakan masuk")
                else: st.error(msg)

    with tab3:
        try:
            auth_url = google_auth_url()
            st.markdown(f"""
            <div style="margin-top:8px;">
                <a href="{auth_url}" style="display:flex;align-items:center;justify-content:center;gap:10px;background:rgba(255,255,255,0.95);color:#1a1a1a;border-radius:12px;padding:13px;text-decoration:none;font-size:0.9rem;font-weight:600;border:none;box-shadow:0 4px 15px rgba(0,0,0,0.3);">
                    <svg width="18" height="18" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
                    Lanjutkan dengan Google
                </a>
            </div>
            """, unsafe_allow_html=True)
        except: st.info("Google login belum dikonfigurasi di Secrets")

    st.markdown(f"""<p style="text-align:center;color:rgba(255,255,255,0.25);font-size:0.72rem;margin-top:24px;line-height:1.6;">Dengan masuk, kamu menyetujui penggunaan platform untuk analisa.<br>Analisa bersifat <em>do your own research</em> dan disclaimer berlaku.<br> by. @MarketnMocha</p>""", unsafe_allow_html=True)
    st.stop()

if st.session_state.user is None: show_login()

# ─────────────────────────────────────────────
# HALAMAN 2: SYSTEM SELECTOR (setelah login, sebelum app)
# ─────────────────────────────────────────────
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

# ── Routing: jika sudah login tapi belum pilih sistem → tampilkan selector ──
if st.session_state.user and not st.session_state.get("selected_system"):
    show_system_selector()

init_chat()
user = st.session_state.user
C = get_colors(st.session_state.theme)

# ─────────────────────────────────────────────
# PART 7: SESSION HANDLERS, AUTH & UI (CSS/LOGIN)
# ─────────────────────────────────────────────
def new_session():
    return {"id": str(uuid.uuid4())[:8], "title": "Obrolan Baru", "messages": [SYSTEM_PROMPT], "created": datetime.now().strftime("%d/%m %H:%M")}

def init_chat():
    if not st.session_state.sessions:
        s = new_session()
        st.session_state.sessions = [s]
        st.session_state.active_id = s["id"]
    else:
        for s in st.session_state.sessions:
            if not s["messages"] or s["messages"][0].get("role") != "system": s["messages"].insert(0, SYSTEM_PROMPT)
            else: s["messages"][0] = SYSTEM_PROMPT

def restore_images_from_messages():
    if not st.session_state.sessions: return
    for sesi in st.session_state.sessions:
        for i, msg in enumerate(sesi.get("messages", [])):
            if msg.get("role") == "user" and msg.get("img_b64"):
                key = f"thumb_{sesi['id']}_{i}"
                if key not in st.session_state: st.session_state[key] = (msg["img_b64"], msg.get("img_mime", "image/jpeg"))

def get_active():
    for s in st.session_state.sessions:
        if s["id"] == st.session_state.active_id: return s
    return st.session_state.sessions[0]

def google_auth_url():
    params = {"client_id": st.secrets.get("GOOGLE_CLIENT_ID", ""), "redirect_uri": st.secrets.get("GOOGLE_REDIRECT_URI", ""), "response_type": "code", "scope": "openid email profile", "access_type": "offline", "prompt": "select_account"}
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

def handle_oauth(code):
    r = requests.post("https://oauth2.googleapis.com/token", data={"code": code, "client_id": st.secrets.get("GOOGLE_CLIENT_ID", ""), "client_secret": st.secrets.get("GOOGLE_CLIENT_SECRET", ""), "redirect_uri": st.secrets.get("GOOGLE_REDIRECT_URI", ""), "grant_type": "authorization_code"})
    if r.status_code != 200: return None
    token = r.json().get("access_token", "")
    if not token: return None
    u = requests.get("https://www.googleapis.com/oauth2/v2/userinfo", headers={"Authorization": f"Bearer {token}"})
    return u.json() if u.status_code == 200 else None

# ─── AUTENTIKASI GOOGLE ───
if "code" in st.query_params and st.session_state.user is None:
    info = handle_oauth(st.query_params["code"])
    if info:
        st.session_state.user = info
        saved = load_user(info["email"])
        if saved:
            st.session_state.theme = saved.get("theme", "dark")
            st.session_state.current_view = saved.get("current_view", "chat"); st.session_state.selected_system = saved.get("selected_system", "chat")
            st.session_state.selected_system = saved.get("selected_system")
            if saved.get("sessions"): st.session_state.sessions = saved["sessions"]; st.session_state.active_id = saved.get("active_id")
        st.session_state.data_loaded = True
        token = str(uuid.uuid4()).replace("-","")
        with open(os.path.join(DATA_DIR, f"token_{token}.json"), "w") as f: json.dump(info, f)
        st.session_state.current_token = token
        st.query_params.clear()
        st.query_params["sigma_token"] = token
        st.rerun()

# ─── AUTO-LOGIN VIA TOKEN ───
if "sigma_token" in st.query_params and st.session_state.user is None:
    token = st.query_params.get("sigma_token", "")
    token_file = os.path.join(DATA_DIR, f"token_{token}.json")
    if os.path.exists(token_file):
        try:
            with open(token_file) as f: user_info = json.load(f)
            st.session_state.user = user_info; st.session_state.current_token = token
            saved = load_user(user_info["email"])
            if saved:
                st.session_state.theme = saved.get("theme", "dark")
                st.session_state.current_view = saved.get("current_view", "chat"); st.session_state.selected_system = saved.get("selected_system", "chat")
                st.session_state.selected_system = saved.get("selected_system")
                if saved.get("sessions"):
                    _loaded = saved["sessions"]
                    for _s in _loaded:
                        if not _s.get("messages"): _s["messages"] = [SYSTEM_PROMPT]
                        elif _s["messages"][0].get("role") != "system": _s["messages"].insert(0, SYSTEM_PROMPT)
                        else: _s["messages"][0] = SYSTEM_PROMPT
                    st.session_state.sessions = _loaded; st.session_state.active_id = saved.get("active_id")
            st.session_state.data_loaded = True
            restore_images_from_messages()
            st.rerun()
        except: pass

if st.session_state.user and not st.session_state.data_loaded:
    saved = load_user(st.session_state.user["email"])
    if saved:
        st.session_state.theme = saved.get("theme", "dark")
        st.session_state.current_view = saved.get("current_view", "chat"); st.session_state.selected_system = saved.get("selected_system", "chat")
        if saved.get("sessions") and not st.session_state.sessions:
            _loaded2 = saved["sessions"]
            for _s in _loaded2:
                if not _s.get("messages"): _s["messages"] = [SYSTEM_PROMPT]
                elif _s["messages"][0].get("role") != "system": _s["messages"].insert(0, SYSTEM_PROMPT)
                else: _s["messages"][0] = SYSTEM_PROMPT
            st.session_state.sessions = _loaded2; st.session_state.active_id = saved.get("active_id")
    st.session_state.data_loaded = True
    restore_images_from_messages()

C = get_colors(st.session_state.theme)

st.markdown(f"""
<style>
* {{ font-family: ui-sans-serif,-apple-system,system-ui,"Segoe UI",sans-serif !important; box-sizing: border-box; }}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] > section, section[data-testid="stMain"], [data-testid="stMainBlockContainer"], [data-testid="stBottom"], [data-testid="stBottom"] > div {{ background: {C['bg']} !important; }}
section[data-testid="stSidebar"], section[data-testid="stSidebar"] > div, section[data-testid="stSidebar"] > div > div, section[data-testid="stSidebar"] > div > div > div, [data-testid="stSidebarContent"], [data-testid="stSidebarUserContent"], [data-testid="stSidebarUserContent"] > div, [data-testid="stSidebarUserContent"] > div > div {{ background: {C['sidebar_bg']} !important; box-shadow: none !important; }}
section[data-testid="stSidebar"] {{ border-right: 1px solid {C['border']} !important; }}
section[data-testid="stSidebar"] > div, section[data-testid="stSidebar"] > div > div, [data-testid="stSidebarContent"], [data-testid="stSidebarUserContent"], [data-testid="stSidebarUserContent"] > div {{ padding-top: 0 !important; margin-top: 0 !important; }}
[data-testid="collapsedControl"], [data-testid="stSidebarCollapseButton"] {{ display: none !important; }}
section[data-testid="stSidebar"] .stButton > button {{ background: transparent !important; border: none !important; box-shadow: none !important; color: {C['text']} !important; font-size: 0.875rem !important; padding: 7px 12px !important; border-radius: 8px !important; width: 100% !important; display: flex !important; align-items: center !important; justify-content: flex-start !important; text-align: left !important; min-height: 36px !important; }}
section[data-testid="stSidebar"] .stButton > button:hover {{ background: {C['hover']} !important; }}
section[data-testid="stSidebar"] .stButton > button p, section[data-testid="stSidebar"] .stButton > button span {{ margin: 0 !important; text-align: left !important; color: inherit !important; width: 100% !important; }}
[data-testid="stChatMessage"] {{ background: transparent !important; border: none !important; box-shadow: none !important; }}
[data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] {{ display: none !important; }}
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {{ font-size: 0.9rem !important; line-height: 1.75 !important; color: {C['text']} !important; background: transparent !important; }}
[data-testid="stMainBlockContainer"] {{ max-width: 760px !important; margin: 0 auto !important; padding: 0 24px 120px !important; overflow-y: visible !important; }}
[data-testid="stMainBlockContainer"] p, [data-testid="stMainBlockContainer"] li, [data-testid="stMainBlockContainer"] h1, [data-testid="stMainBlockContainer"] h2, [data-testid="stMainBlockContainer"] h3 {{ color: {C['text']} !important; }}
div[data-testid="stChatInputContainer"] {{ border: 1px solid {C['border']} !important; background: {C['input_bg']} !important; border-radius: 16px !important; }}
[data-testid="stChatInput"] textarea {{ background: {C['input_bg']} !important; color: {C['text']} !important; font-size: 0.9rem !important; }}
[data-testid="stChatInput"] textarea::placeholder {{ color: {C['text_muted']} !important; }}
[data-testid="stChatInputContainer"] textarea:focus {{ box-shadow: none !important; outline: none !important; }}
footer, #MainMenu {{ visibility: hidden !important; }}
hr {{ border-color: {C['border']} !important; }}
[data-testid="stMarkdownContainer"] *, [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li, [data-testid="stMarkdownContainer"] span, [data-testid="stMarkdownContainer"] div {{ font-size: 0.95rem !important; line-height: 1.8 !important; }}
[data-testid="stMarkdownContainer"] h1 {{ font-size: 1.3rem !important; }}
[data-testid="stMarkdownContainer"] h2 {{ font-size: 1.15rem !important; }}
[data-testid="stMarkdownContainer"] h3 {{ font-size: 1.05rem !important; }}
@media (max-width: 768px) {{
    html, body {{ overflow-x: hidden !important; max-width: 100vw !important; }}
    .stApp {{ overflow-x: hidden !important; }}
    [data-testid="stMainBlockContainer"] {{ max-width: 100% !important; padding: 12px 12px 120px !important; overflow-x: hidden !important; }}
    [data-testid="stMarkdownContainer"] *, [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li, [data-testid="stMarkdownContainer"] span, [data-testid="stMarkdownContainer"] strong, [data-testid="stMarkdownContainer"] b, [data-testid="stMarkdownContainer"] em {{ font-size: 1rem !important; line-height: 1.85 !important; }}
    [data-testid="stMarkdownContainer"] h1 {{ font-size: 1.25rem !important; }}
    [data-testid="stMarkdownContainer"] h2 {{ font-size: 1.1rem !important; }}
    [data-testid="stMarkdownContainer"] h3 {{ font-size: 1rem !important; font-weight: 700 !important; }}
    [data-testid="stMarkdownContainer"] ul, [data-testid="stMarkdownContainer"] ol {{ padding-left: 20px !important; margin: 6px 0 !important; }}
    [data-testid="stMarkdownContainer"] li {{ margin-bottom: 4px !important; }}
    [data-testid="stMarkdownContainer"] code {{ font-size: 0.85rem !important; padding: 2px 6px !important; border-radius: 4px !important; background: rgba(255,255,255,0.08) !important; }}
    [data-testid="stMarkdownContainer"] pre {{ font-size: 0.82rem !important; overflow-x: auto !important; padding: 12px !important; border-radius: 8px !important; }}
    [data-testid="stMarkdownContainer"] div {{ max-width: 100% !important; overflow-x: hidden !important; box-sizing: border-box !important; }}
    div[data-testid="stChatInputContainer"] {{ border-radius: 26px !important; margin: 0 6px 8px !important; }}
    [data-testid="stChatInput"] textarea {{ font-size: 16px !important; line-height: 1.5 !important; }}
    [data-testid="stChatMessage"] {{ padding: 10px 0 !important; }}
    .navy-pill {{ max-width: 82% !important; font-size: 1rem !important; line-height: 1.7 !important; padding: 12px 16px !important; }}
}}
</style>
""", unsafe_allow_html=True)

def show_login():
    st.markdown(f"""
    <style>
    [data-testid="stSidebar"] {{ display: none !important; }}
    [data-testid="stAppViewContainer"], section[data-testid="stMain"] {{ background: url('https://raw.githubusercontent.com/kipmuniversitaspancasila-commits/KIPMSIGMA/main/kipmd.png') center/cover no-repeat fixed !important; min-height: 100vh !important; }}
    section[data-testid="stMain"]::before {{ display: none !important; }}
    [data-testid="stMainBlockContainer"] {{ max-width: 300px !important; margin: 1.5vh 74px 0 auto !important; padding: 8px 18px 16px !important; position: relative; z-index: 1; min-height: unset !important; height: fit-content !important; background: rgba(5, 8, 20, 0.60) !important; backdrop-filter: blur(20px) saturate(1.4) !important; -webkit-backdrop-filter: blur(20px) saturate(1.4) !important; border: 1px solid rgba(255,255,255,0.10) !important; border-radius: 20px !important; box-shadow: 0 8px 40px rgba(0,0,0,0.5) !important; }}
    @media(max-width: 768px) {{
        [data-testid="stMainBlockContainer"] {{ margin: 5vh auto 0 auto !important; max-width: 88% !important; padding: 20px 20px 28px !important; backdrop-filter: blur(20px) !important; border-radius: 20px !important; border: 1px solid rgba(255,255,255,0.12) !important; box-shadow: 0 8px 40px rgba(0,0,0,0.5) !important; }}
        [data-testid="stAppViewContainer"], section[data-testid="stMain"] {{ background: url('https://raw.githubusercontent.com/kipmuniversitaspancasila-commits/KIPMSIGMA/main/kipmm.png') center top/cover no-repeat fixed !important; }}
        [data-testid="stMainBlockContainer"] {{ margin-top: 75px !important; }}
    }}
    header[data-testid="stHeader"] {{ display: none !important; }} #MainMenu {{ display: none !important; }}
    .stTabs, [data-testid="stVerticalBlock"] {{ background: transparent !important; }}
    [data-testid="stTextInput"] input {{ background: rgba(255,255,255,0.06) !important; border: 1px solid rgba(255,255,255,0.12) !important; border-radius: 12px !important; color: #fff !important; padding: 12px 16px !important; font-size: 0.95rem !important; backdrop-filter: blur(10px) !important; transition: border 0.2s !important; }}
    [data-testid="stTextInput"] input:focus {{ border: 1px solid {C['gold']} !important; box-shadow: 0 0 0 2px rgba(245,194,66,0.15) !important; outline: none !important; }}
    [data-testid="stTextInput"] input::placeholder {{ color: rgba(255,255,255,0.35) !important; }}
    [data-testid="stTextInput"] label {{ color: rgba(255,255,255,0.6) !important; font-size: 0.82rem !important; }}
    [data-testid="stMainBlockContainer"] .stButton > button {{ background: linear-gradient(135deg, {C['gold']}, #e0a820) !important; color: #000 !important; font-weight: 700 !important; border: none !important; border-radius: 12px !important; padding: 12px !important; font-size: 0.95rem !important; letter-spacing: 0.5px !important; transition: opacity 0.2s, transform 0.1s !important; box-shadow: 0 4px 20px rgba(245,194,66,0.3) !important; }}
    [data-testid="stMainBlockContainer"] .stButton > button:hover {{ opacity: 0.92 !important; transform: translateY(-1px) !important; }}
    [data-testid="stTabs"] [role="tablist"] {{ background: rgba(255,255,255,0.05) !important; border-radius: 12px !important; padding: 4px !important; border: 1px solid rgba(255,255,255,0.08) !important; gap: 2px !important; }}
    [data-testid="stTabs"] button[role="tab"] {{ border-radius: 9px !important; color: rgba(255,255,255,0.5) !important; font-size: 0.85rem !important; padding: 7px 12px !important; border: none !important; background: transparent !important; }}
    [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{ background: rgba(245,194,66,0.15) !important; color: {C['gold']} !important; font-weight: 600 !important; }}
    [data-testid="stTabs"] [role="tabpanel"] {{ background: rgba(255,255,255,0.03) !important; border-radius: 16px !important; border: 1px solid rgba(255,255,255,0.08) !important; padding: 20px 16px !important; margin-top: 8px !important; backdrop-filter: blur(10px) !important; }}
    [data-testid="stAlert"] {{ border-radius: 10px !important; }}
    </style>
    """, unsafe_allow_html=True)

    components.html(f"""
<script>
(function() {{
    var pd = window.parent.document;
    var forkStyle = pd.getElementById('hide-fork-bar');
    if (!forkStyle) {{
        var fs = pd.createElement('style');
        fs.id = 'hide-fork-bar';
        fs.textContent = `
            .viewerBadge_container__r5tak, .viewerBadge_link__qRIco, [class*="viewerBadge"], [class*="styles_viewerBadge"], #MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"], header[data-testid="stHeader"], .stDeployButton, [kind="header"], div[data-testid="collapsedControl"] {{ display: none !important; visibility: hidden !important; height: 0 !important; overflow: hidden !important; }}
        `;
        pd.head.appendChild(fs);
    }}
    if (pd.getElementById('kipm-mobile-logo')) return;
    var s = pd.createElement('style');
    s.id = 'kipm-mobile-logo-style';
    s.textContent = `
        #kipm-mobile-logo {{ display: none; text-align: center; padding: 14px 0 10px; position: fixed; top: 0; left: 0; right: 0; z-index: 10; pointer-events: none; }}
        #kipm-mobile-logo img {{ width: 80px; height: 80px; object-fit: contain; filter: drop-shadow(0 2px 12px rgba(0,0,0,0.6)); }}
        #kipm-mobile-logo .kipm-name {{ font-size: 0.7rem; color: rgba(255,255,255,0.7); letter-spacing: 2px; font-family: sans-serif; margin-top: 4px; }}
        @media(max-width: 768px) {{ #kipm-mobile-logo {{ display: block !important; }} }}
    `;
    pd.head.appendChild(s);
    var div = pd.createElement('div');
    div.id = 'kipm-mobile-logo';
    div.innerHTML = `<img src="https://raw.githubusercontent.com/kipmuniversitaspancasila-commits/KIPMSIGMA/main/Mate%20KIPM%20LOGO.png" onerror="this.style.display='none'" style="width:80px;height:80px;object-fit:contain;"><div class="kipm-name">KIPM-UP</div>`;
    pd.body.appendChild(div);
}})();
</script>
""", height=0)
    st.markdown('''
        <div style="text-align:center;margin:0 0 10px;">
            <div style="font-size:2.8rem;font-weight:900;letter-spacing:5px;color:#ffffff;font-family:sans-serif;line-height:1.2;">SIGMA <span style="color:#F5C242;">Σ</span></div>
            <div class="sigma-tagline" style="font-size:0.65rem;color:rgba(255,255,255,0.5);letter-spacing:2px;margin-top:4px;font-family:sans-serif;">Strategic Intelligence & Global Market Analysis</div>
        </div>
        <style>@media(min-width: 769px) { .sigma-tagline { display: none !important; } }</style>
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
                    with open(os.path.join(DATA_DIR, f"token_{token}.json"), "w") as f: json.dump(info, f)
                    st.query_params["sigma_token"] = token
                    st.session_state.user = info; st.session_state.current_token = token; st.session_state.data_loaded = False
                    st.rerun()
                else: st.error("Username atau password salah")
            else: st.warning("Isi username dan password")

    with tab2:
        rname  = st.text_input("Nama Tampil", key="rg_name", placeholder="Nama lengkap kamu")
        runame = st.text_input("Username", key="rg_user", placeholder="username (huruf/angka)")
        rpwd   = st.text_input("Password", key="rg_pwd",  type="password", placeholder="min. 6 karakter")
        rpwd2  = st.text_input("Ulangi Password", key="rg_pwd2", type="password", placeholder="ulangi password")
        if st.button("Daftar Sekarang", key="btn_register", use_container_width=True):
            if not all([rname, runame, rpwd, rpwd2]): st.warning("Lengkapi semua field")
            elif rpwd != rpwd2: st.error("Password tidak cocok")
            elif len(rpwd) < 6: st.error("Password minimal 6 karakter")
            else:
                ok, msg = register_user(runame.strip(), rpwd, rname.strip())
                if ok: st.success(f"✅ {msg} — silakan masuk")
                else: st.error(msg)

    with tab3:
        try:
            auth_url = google_auth_url()
            st.markdown(f"""
            <div style="margin-top:8px;">
                <a href="{auth_url}" style="display:flex;align-items:center;justify-content:center;gap:10px;background:rgba(255,255,255,0.95);color:#1a1a1a;border-radius:12px;padding:13px;text-decoration:none;font-size:0.9rem;font-weight:600;border:none;box-shadow:0 4px 15px rgba(0,0,0,0.3);">
                    <svg width="18" height="18" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
                    Lanjutkan dengan Google
                </a>
            </div>
            """, unsafe_allow_html=True)
        except: st.info("Google login belum dikonfigurasi di Secrets")

    st.markdown(f"""<p style="text-align:center;color:rgba(255,255,255,0.25);font-size:0.72rem;margin-top:24px;line-height:1.6;">Dengan masuk, kamu menyetujui penggunaan platform untuk analisa.<br>Analisa bersifat <em>do your own research</em> dan disclaimer berlaku.<br> by. @MarketnMocha</p>""", unsafe_allow_html=True)
    st.stop()

if st.session_state.user is None: show_login()
init_chat()
user = st.session_state.user
C = get_colors(st.session_state.theme)

# --- PENANGANAN PARAMETER URL (DO & DEL) ---
# Ditempatkan SEBELUM pembuatan HTML agar UI selalu ter-update dengan state terbaru
if "del" in st.query_params:
    _del_id = st.query_params.get("del", "")
    if isinstance(_del_id, list): _del_id = _del_id[0] if _del_id else ""
    
    if _del_id and st.session_state.get("user"):
        st.session_state.sessions = [s for s in st.session_state.sessions if s["id"] != _del_id]
        if not st.session_state.sessions: 
            st.session_state.sessions = [new_session()]
        if st.session_state.active_id == _del_id: 
            st.session_state.active_id = st.session_state.sessions[0]["id"]
            
        _to_save = [{"id": s["id"], "title": s["title"], "created": s["created"], "messages": [dict(m) for m in s["messages"] if m["role"] != "system"]} for s in st.session_state.sessions]
        save_user(st.session_state.user["email"], {
            "theme": st.session_state.get("theme", "dark"), 
            "sessions": _to_save, 
            "active_id": st.session_state.active_id,
            "current_view": st.session_state.get("current_view", "chat"), "selected_system": st.session_state.get("selected_system", "chat"), "selected_system": st.session_state.get("selected_system", "chat")
        })
        
    try: del st.query_params["del"]
    except: 
        try: st.query_params.pop("del", None)
        except: pass
    st.rerun()

if "do" in st.query_params:
    _do = st.query_params.get("do", "")
    if isinstance(_do, list): _do = _do[0] if _do else ""
    
    _tok = st.query_params.get("sigma_token", st.session_state.get("current_token", ""))
    if isinstance(_tok, list): _tok = _tok[0] if _tok else ""
    
    if _do == "logout":
        if _tok:
            try: os.remove(os.path.join(DATA_DIR, f"token_{_tok}.json"))
            except: pass
        st.session_state.clear(); st.query_params.clear()
        components.html("""<script>try { localStorage.removeItem('sigma_token'); } catch(e) {} setTimeout(function(){ window.parent.location.replace(window.parent.location.pathname); }, 100);</script>""", height=0)
        st.stop()
    elif _do == "go_home": 
        st.session_state.selected_system = None
        try: del st.query_params["do"]
        except: 
            try: st.query_params.pop("do", None)
            except: pass
        st.rerun()
    elif _do == "theme_dark": st.session_state.theme = "dark"
    elif _do == "theme_light": st.session_state.theme = "light"
    elif _do == "newchat":
        st.session_state.current_view = "chat"
        ns = {"id": str(uuid.uuid4())[:8], "title": "Obrolan Baru", "created": datetime.now().isoformat(), "messages": [{"role": "system", "content": SYSTEM_PROMPT["content"]}]}
        st.session_state.sessions.insert(0, ns)
        st.session_state.active_id = ns["id"]
    elif _do.startswith("sel_"):
        st.session_state.current_view = "chat"
        _sid = _do[4:]
        st.session_state.active_id = _sid

    try: del st.query_params["do"]
    except: 
        try: st.query_params.pop("do", None)
        except: pass
    st.rerun()

# --- PEMBUATAN MENU SIDEBAR HISTORI CHAT ---
_hist_items = ""
for _sesi in st.session_state.sessions:
    _sid = _sesi["id"]
    _is_act = _sid == st.session_state.active_id
    _td = _sesi["title"][:35].replace("'","").replace("`","").replace("\\","").replace('"',"")
    _fw = "700" if _is_act else "400"
    _bg = C['hover'] if _is_act else "transparent"
    _hist_items += f"""
(function(){{
    var row=pd.createElement('div'); row.style.cssText='display:flex;align-items:center;width:100%;';
    
    var a=pd.createElement('a'); 
    a.textContent='{_td}'; 
    var u=new URL(window.parent.location.href); 
    u.searchParams.set('do','sel_{_sid}'); 
    u.searchParams.delete('del');
    a.href=u.toString(); 
    a.style.cssText='flex:1;display:block;padding:12px 8px 12px 18px;font-size:1rem;color:{C["text"]};background:{_bg};font-weight:{_fw};border:none;text-align:left;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-decoration:none;min-width:0;'; 
    a.onmouseenter=function(){{this.style.background='{C["hover"]}'}}; 
    a.onmouseleave=function(){{this.style.background='{_bg}'}};
    
    // PERBAIKAN: Mengubah tombol hapus menjadi Link (Tag a) agar bebas blokir dari browser
    var del=pd.createElement('a'); 
    del.innerHTML='🗑️'; 
    del.title='Hapus Obrolan'; 
    var uDel=new URL(window.parent.location.href); 
    uDel.searchParams.set('del','{_sid}'); 
    uDel.searchParams.delete('do'); 
    del.href=uDel.toString();
    del.style.cssText='padding:12px 16px;background:transparent;border:none;cursor:pointer;font-size:1.1rem;opacity:0.4;flex-shrink:0;color:{C["text"]};text-decoration:none;display:flex;align-items:center;justify-content:center;'; 
    del.onmouseenter=function(){{this.style.opacity='1';this.style.color='#ff5555';}}; 
    del.onmouseleave=function(){{this.style.opacity='0.4';this.style.color='{C["text"]}';}}; 
    
    // Konfirmasi penghapusan
    del.onclick = function(e) {{
        try {{
            if(!confirm('Yakin ingin menghapus riwayat obrolan ini?')) {{
                e.preventDefault();
            }}
        }} catch(err) {{
            // Abaikan jika browser memblokir pop-up confirm
        }}
    }};
    
    row.appendChild(a); 
    row.appendChild(del); 
    h.appendChild(row);
}})();
"""

components.html(f"""
<script>
(function(){{
var pd=window.parent.document;
var kipmLogo = pd.getElementById('kipm-mobile-logo'); if (kipmLogo) kipmLogo.style.display = 'none !important';
var kipmStyle = pd.getElementById('kipm-mobile-logo-style'); if (kipmStyle) kipmStyle.remove();
['spbtn','spmenu','sphist','spui','sigma-mobile-css'].forEach(function(id){{ var el=pd.getElementById(id); if(el) el.remove(); }});
var s=pd.createElement('style'); s.id='sigma-mobile-css';
s.textContent=`
#spbtn{{position:fixed;bottom:20px;left:20px;width:50px;height:50px;border-radius:50%; background:{C["sidebar_bg"]};color:{C["text"]};border:1px solid {C["border"]}; cursor:pointer;z-index:999999; display:flex;align-items:center;justify-content:center; box-shadow:0 6px 20px rgba(0,0,0,0.5);padding:0;transition:transform 0.2s, background 0.2s;}} 
#spbtn:hover{{transform:scale(1.08); background:{C["hover"]};}}
#spmenu,#sphist{{position:fixed;left:20px;bottom:85px; background:{C["sidebar_bg"]};border:1px solid {C["border"]}; border-radius:16px;box-shadow:0 -4px 24px rgba(0,0,0,0.5); z-index:999998;display:none;overflow:hidden;min-width:260px;}} 
#sphist{{max-height:55vh;overflow-y:auto;}}
.smi{{display:flex;align-items:center;gap:14px;padding:13px 18px; font-size:1rem;color:{C["text"]};cursor:pointer;border:none; background:transparent;width:100%;text-align:left;text-decoration:none;transition:background 0.2s;}} .smi:hover{{background:{C["hover"]}}}
.smico{{width:32px;height:32px;border-radius:8px;display:flex; align-items:center;justify-content:center;font-size:16px; background:{C["hover"]};flex-shrink:0;}}
.smsp{{border:none;border-top:1px solid {C["border"]};margin:4px 0;}} .smhd{{padding:8px 18px 4px;font-size:0.68rem;color:{C["text_muted"]}; font-weight:600;letter-spacing:1px;}} .smred{{color:#f55!important}}
`; pd.head.appendChild(s);
var btn=pd.createElement('button'); btn.id='spbtn'; btn.innerHTML='<svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2.5"/><circle cx="12" cy="12" r="2.5"/><circle cx="12" cy="19" r="2.5"/></svg>'; pd.body.appendChild(btn);
var m=pd.createElement('div');m.id='spmenu';
m.innerHTML=`
    <a class="smi" id="smi-new"><span class="smico">✎</span>Percakapan Baru</a>
    <button class="smi" id="smi-hist"><span class="smico">☰</span>History</button>
    <div class="smsp"></div><div class="smhd">FITUR</div>
    <a class="smi" id="smi-ai"><span class="smico">🤖</span>SIGMA AI Chat</a>
    <a class="smi" id="smi-stats"><span class="smico">📊</span>SIGMA Terminal</a>
    <a class="smi" id="smi-diag"><span class="smico">🔧</span>Diagnostik API</a>
    <div class="smsp"></div><div class="smhd">PENAMPILAN</div>
    <a class="smi" id="smi-dark"><span class="smico">🌙</span>Dark Mode {'✓' if st.session_state.theme=='dark' else ''}</a>
    <a class="smi" id="smi-light"><span class="smico">☀️</span>Light Mode {'✓' if st.session_state.theme=='light' else ''}</a>
    <div class="smsp"></div><a class="smi smred" id="smi-out"><span class="smico">🚪</span>Sign Out</a>
`; pd.body.appendChild(m);
var h=pd.createElement('div');h.id='sphist'; h.innerHTML='<div class="smhd">RIWAYAT OBROLAN</div>';
{_hist_items} pd.body.appendChild(h);
btn.onclick=function(e){{ e.preventDefault(); e.stopPropagation(); m.style.display = (m.style.display === 'block') ? 'none' : 'block'; h.style.display = 'none'; }};
(function(){{
    var u; u=new URL(window.parent.location.href); u.searchParams.set('do','newchat'); pd.getElementById('smi-new').href=u.toString();
    pd.getElementById('smi-hist').onclick=function(){{m.style.display='none';h.style.display='block';}};
    u=new URL(window.parent.location.href); u.searchParams.set('do','view_ai'); pd.getElementById('smi-ai').href=u.toString();
    u=new URL(window.parent.location.href); u.searchParams.set('do','view_stats'); pd.getElementById('smi-stats').href=u.toString();
    u=new URL(window.parent.location.href); u.searchParams.set('do','view_diag'); pd.getElementById('smi-diag').href=u.toString();
    u=new URL(window.parent.location.href); u.searchParams.set('do','theme_dark'); pd.getElementById('smi-dark').href=u.toString();
    u=new URL(window.parent.location.href); u.searchParams.set('do','theme_light'); pd.getElementById('smi-light').href=u.toString();
    u=new URL(window.parent.location.href); u.searchParams.delete('sigma_token'); u.searchParams.set('do','logout'); pd.getElementById('smi-out').href=u.toString();
}})();
pd.addEventListener('click',function(e){{ if(!btn.contains(e.target) && !m.contains(e.target)) m.style.display='none'; if(!btn.contains(e.target) && !h.contains(e.target) && !m.contains(e.target)) h.style.display='none'; }});
}})();
</script>
""", height=0)

active = get_active()
current_view = st.session_state.get("current_view", "chat")
# =========================================================
# PART 8: MAIN CHAT ENGINE & UI (STABLE, FIX PASTE, 7 ALPHA COMPLETE + IPO RISK)
# =========================================================
import requests
import re
from datetime import datetime

# --- FUNGSI KOMPRESI GAMBAR UNTUK HEMAT LIMIT API ---
def _compress_image_file(file_obj):
    """Mengkompres file gambar (PNG/JPG) agar ukurannya kecil sebelum dikirim ke API Gemini"""
    try:
        from PIL import Image
        import io, base64
        # Buka gambar dari objek file Streamlit
        img = Image.open(file_obj)
        # Pastikan formatnya RGB agar aman disimpan sebagai JPEG
        if img.mode != 'RGB':
            img = img.convert('RGB')
        # Resize maksimal 1024x1024 (cukup tajam untuk AI membaca tulisan/chart)
        img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        # Simpan sementara di memori dengan quality 80 (sangat hemat)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"
    except Exception as e:
        # Jika gagal kompresi, fallback gunakan ukuran aslinya
        file_obj.seek(0)
        return base64.b64encode(file_obj.read()).decode(), "image/png" if file_obj.name.endswith(".png") else "image/jpeg"

# ─── DAFTAR SAHAM PERBANKAN UNTUK FILTERING ───
BANK_TICKERS = ["BBCA","BBRI","BMRI","BBNI","BBTN","BRIS","BNGA","BDMN","PNBN","ARTO","BBYB","AGRO","BJBR","BSIM","BBKP","BTPN","NISP","MEGA","MCOR","SDRA","MAYA"]

# ─── KUMPULAN TEMPLATE SIGMA ───

TEMPLATE_NON_BANK = """
[INSTRUKSI WAJIB SYSTEM]:
User meminta analisa fundamental saham {emiten} (Sektor Non-Perbankan). 
Kamu WAJIB mematuhi aturan berikut:
1. DILARANG KERAS memunculkan atau membahas metrik Perbankan seperti NIM, BOPO, NPL, CAR, LDR, atau Kualitas Aset.
2. JANGAN PERNAH mengubah format list (- ). Gunakan format di bawah ini persis, perhatikan jarak spasi/enternya agar UI rapi dan tidak bertumpuk!
3. Jika data kosong, hitung manual (PER = Harga/EPS, PBV = Harga/BV) atau gunakan estimasimu.

[DATA LIVE MULTI-SOURCE & KALKULASI DARI {sumber}]:
{data_raw}

[TEMPLATE YANG WAJIB KAMU KELUARKAN SEBAGAI JAWABAN]:
Baik, mari kita lakukan analisa fundamental untuk **{emiten}** berdasarkan data paling aktual.

Harga **{emiten}** saat ini adalah **Rp[ISI HARGA DARI DATA LIVE]**.

📋 **ANALISA FUNDAMENTAL — {emiten} ({tahun})**

- **Sektor:** [ISI SEKTOR]
- **Framework:** Gabungan Warren Buffett, Peter Lynch, dan Benjamin Graham

💰 **PROFITABILITAS**

- **ROE:** [ISI ROE ATAU ESTIMASI]
- **ROA:** [ISI ROA ATAU ESTIMASI]
- **Laba Bersih:** [ANALISA TREN LABA]
- **EPS:** [ISI EPS DARI DATA LIVE]

📈 **VALUASI**

- **PER:** [ISI PER ATAU HITUNG MANUAL: Harga ÷ EPS]
- **PBV:** [ISI PBV ATAU HITUNG MANUAL: Harga ÷ Book Value]
- **PEG:** [ANALISA PEG ATAU ESTIMASI]
- **Harga Wajar:** [ESTIMASI HARGA WAJAR]

🏆 **DIVIDEN**

- **DPS:** [ISI DATA DIVIDEN]
- **Payout Ratio:** [ANALISA PAYOUT]
- **Konsistensi:** [ANALISA KONSISTENSI DIVIDEN]

📊 **TREN 3-5 TAHUN TERAKHIR**

- **Laba Bersih:** [ANALISA SINGKAT TREN]
- **EPS:** [ANALISA SINGKAT TREN]
- **ROE:** [ANALISA SINGKAT TREN]
- **Dividen:** [ANALISA SINGKAT TREN]

🔭 **PROYEKSI 3 TAHUN KE DEPAN**

- **[2027]:** EPS Rp[ESTIMASI] → Target Harga Rp[ESTIMASI]
- **[2028]:** EPS Rp[ESTIMASI] → Target Harga Rp[ESTIMASI]
- **[2029]:** EPS Rp[ESTIMASI] → Target Harga Rp[ESTIMASI] 
- **Skenario:** Konservatif Rp[X] | Moderat Rp[Y] | Optimis Rp[Z]

⚖️ **VERDICT**

- **Score:** [BERI SKOR 1-100]
- **Kekuatan:** → [JELASKAN KEKUATAN]
- **Risiko:** → [JELASKAN RISIKO]
- **Valuasi:** [JELASKAN UNDERVALUED/OVERVALUED]
- **Kesimpulan:** [BUAT KESIMPULAN PROFESIONAL]

⚠️ *DYOR — analisa ini berbasis data yang tersedia dan pengetahuan umum, bukan rekomendasi investasi.*
"""

TEMPLATE_BANK = """
[INSTRUKSI WAJIB SYSTEM]:
User meminta analisa fundamental saham {emiten} (Sektor Perbankan). 
Kamu WAJIB mematuhi aturan berikut:
1. ISI SEMUA KOLOM. Jika NIM, BOPO, NPL, CAR, LDR kosong di data live, kamu WAJIB menggunakan knowledge internalmu untuk mengisi estimasinya!
2. JANGAN PERNAH mengubah format list (- ). Gunakan format di bawah ini persis, perhatikan jarak spasi/enternya agar UI rapi dan tidak bertumpuk!

[DATA LIVE MULTI-SOURCE & KALKULASI DARI {sumber}]:
{data_raw}

[TEMPLATE YANG WAJIB KAMU KELUARKAN SEBAGAI JAWABAN]:
Baik, mari kita lakukan analisa fundamental untuk **{emiten}** berdasarkan data paling aktual.

Harga **{emiten}** saat ini adalah **Rp[ISI HARGA DARI DATA LIVE]**.

📋 **ANALISA FUNDAMENTAL — {emiten} ({tahun})**

- **Sektor:** Perbankan
- **Framework:** Analisa Institusi Keuangan & Value Investing

💰 **PROFITABILITAS**

- **ROE:** [ISI ROE ATAU ESTIMASI]
- **ROA:** [ISI ROA ATAU ESTIMASI]
- **NIM:** [ISI NIM ATAU ESTIMASI]
- **BOPO:** [ISI BOPO ATAU ESTIMASI]
- **Laba Bersih:** [ANALISA TREN LABA]
- **EPS:** [ISI EPS DARI DATA LIVE]

🛡️ **KUALITAS ASET & LIKUIDITAS**

- **NPL Gross:** [ISI ESTIMASI NPL]
- **NPL Net:** [ISI ESTIMASI NPL]
- **CAR:** [ISI ESTIMASI CAR]
- **LDR:** [ISI ESTIMASI LDR]
- **CIR:** [ISI ESTIMASI CIR]

📈 **VALUASI**

- **PER:** [ISI PER ATAU HITUNG MANUAL: Harga ÷ EPS]
- **PBV:** [ISI PBV ATAU HITUNG MANUAL: Harga ÷ Book Value]
- **Harga Wajar:** [ESTIMASI HARGA WAJAR BERDASARKAN PBV BAND HISTORIS]

🏆 **DIVIDEN**

- **DPS:** [ISI DATA DIVIDEN]
- **Payout Ratio:** [ANALISA PAYOUT]
- **Konsistensi:** [ANALISA KONSISTENSI DIVIDEN]

📊 **TREN 3-5 TAHUN TERAKHIR**

- **Laba Bersih:** [ANALISA SINGKAT TREN]
- **EPS:** [ANALISA SINGKAT TREN]
- **ROE:** [ANALISA SINGKAT TREN]
- **Dividen:** [ANALISA SINGKAT TREN]

🔭 **PROYEKSI 3 TAHUN KE DEPAN**

- **[2027]:** EPS Rp[ESTIMASI] → Target Harga Rp[ESTIMASI]
- **[2028]:** EPS Rp[ESTIMASI] → Target Harga Rp[ESTIMASI]
- **[2029]:** EPS Rp[ESTIMASI] → Target Harga Rp[ESTIMASI] 
- **Skenario:** Konservatif Rp[X] | Moderat Rp[Y] | Optimis Rp[Z]

⚖️ **VERDICT**

- **Score:** [BERI SKOR 1-100]
- **Kekuatan:** → [JELASKAN KEKUATAN]
- **Risiko:** → [JELASKAN RISIKO]
- **Valuasi:** [JELASKAN UNDERVALUED/OVERVALUED]
- **Kesimpulan:** [BUAT KESIMPULAN PROFESIONAL]

⚠️ *DYOR — analisa ini berbasis data yang tersedia dan pengetahuan umum, bukan rekomendasi investasi.*
"""

TEMPLATE_DAMPAK_MAKRO = """
[INSTRUKSI WAJIB SYSTEM]:
User meminta analisa "Kesimpulan Dampak Makro".
Fokuskan pada dampak berita/ekonomi ini ke pasar saham secara umum (IHSG) dan sektor apa yang akan diuntungkan atau dirugikan. Gunakan format list (- ) agar rapi!

[TEMPLATE YANG WAJIB KAMU KELUARKAN SEBAGAI JAWABAN]:
Berikut adalah analisa dampak makro pasar dari SIGMA:

🌍 **GAMBARAN UMUM**

- [Jelaskan inti dari isu makro tersebut secara singkat]
- [Pengaruhnya ke ekonomi domestik / inflasi / nilai tukar Rupiah]

🟢 **SEKTOR DIUNTUNGKAN (WINNERS)**

- **[Sektor 1]:** [Alasan fundamental/sentimen mengapa untung]
- **[Sektor 2]:** [Alasan fundamental/sentimen mengapa untung]

🔴 **SEKTOR DIRUGIKAN (LOSERS)**

- **[Sektor 1]:** [Alasan mengapa akan tertekan]
- **[Sektor 2]:** [Alasan mengapa akan tertekan]

📉 **DAMPAK KE IHSG**

- **Tren Jangka Pendek:** [Bullish / Bearish / Volatile]
- **Alasan:** [Jelaskan respons investor asing & lokal terhadap isu ini]

⚖️ **KESIMPULAN & STRATEGI**

- [Berikan saran bijak bagaimana trader harus mengatur portofolionya (misal: perbanyak cash, atau rotasi sektor)]

⚠️ *DYOR — analisa makro bergantung pada data rilis dan kebijakan lanjutan.*
"""

TEMPLATE_DAMPAK_EMITEN = """
[INSTRUKSI WAJIB SYSTEM]:
User meminta analisa "Kesimpulan Dampak" khusus terhadap emiten {emiten}.
Fokuskan 100% analisamu pada BAGAIMANA TOPIK/BERITA INI MEMPENGARUHI KINERJA BISNIS, PENDAPATAN, DAN HARGA SAHAM {emiten}.
Gunakan format list (- ) agar rapi!

[TEMPLATE YANG WAJIB KAMU KELUARKAN SEBAGAI JAWABAN]:
Berikut adalah analisa dampak pasar untuk **{emiten}** terkait isu tersebut:

🔍 **KORELASI BISNIS**

- [Jelaskan spesifik apa hubungan bisnis/operasional {emiten} dengan isu/topik ini]
- [Jelaskan apakah ini berdampak pada biaya bahan baku, daya beli konsumen, atau beban utang mereka]

🟢 **DAMPAK POSITIF (PELUANG)**

- [Poin 1 potensi keuntungan bagi {emiten}]
- [Poin 2 potensi keuntungan bagi {emiten}]

🔴 **DAMPAK NEGATIF (RISIKO)**

- [Poin 1 potensi kerugian/risiko bagi {emiten}]
- [Poin 2 potensi kerugian/risiko bagi {emiten}]

📊 **PROYEKSI REAKSI PASAR**

- **Jangka Pendek:** [Prediksi respons pergerakan teknikal sesaat]
- **Jangka Menengah:** [Prediksi dampak nyata ke laporan keuangan kuartal berikutnya]

⚖️ **KESIMPULAN FINAL**

- **Status Katalis:** [Tulis dengan tegas apakah ini BULLISH, BEARISH, atau NEUTRAL untuk {emiten}]
- **Kesimpulan:** [Langkah apa yang sebaiknya diperhatikan investor terkait {emiten}]

⚠️ *DYOR — analisa ini berbasis sentimen pasar saat ini.*
"""

TEMPLATE_IPO = """
[INSTRUKSI WAJIB SYSTEM]:
User meminta "Analisa IPO" berdasarkan dokumen PDF prospektus yang dilampirkan untuk calon emiten {emiten}.
Tugasmu adalah membongkar isi PDF dan merangkumnya untuk Investor Ritel menggunakan Logika Analisa IPO di system prompt.
JANGAN bertele-tele. Cari data paling krusial di dalam teks PDF!
JANGAN ubah urutan atau struktur template. Isi setiap poin dengan data dari PDF.

⚠️ PERINGATAN KHUSUS SEBELUM MULAI:
- PDF prospektus SELALU menulis jumlah saham dalam LEMBAR. Kamu WAJIB konversi ke LOT dulu.
- RUMUS: Total Lot = Total Lembar ÷ 100  (karena 1 LOT = 100 LEMBAR)
- CONTOH: 1.800.000.000 lembar ÷ 100 = 18.000.000 Lot = 18 Juta Lot
- Jangan gunakan angka lembar untuk menentukan Kondisi A/B atau Risk 1/2. Selalu gunakan LOT.
- Untuk valuasi: WAJIB gunakan skala granular (≤2x / 2-4x / >4-7x / >7x), BUKAN hanya batas 4x.

[ISI TEKS PDF PROSPEKTUS]:
{pdf_content}

[TEMPLATE YANG WAJIB KAMU KELUARKAN SEBAGAI JAWABAN]:
Berikut adalah bedah Prospektus IPO untuk **{emiten}**:

**1. HARGA PENAWARAN vs NOMINAL**
- **Harga Nominal:** Rp[X] per saham
- **Rentang Harga Penawaran:** Rp[Y] hingga Rp[Z] per saham
- **Rasio Harga Penawaran / Harga Nominal:**
  - Pada harga Rp[Y]: [A]x → Kategori: [SANGAT MENARIK / MENARIK / WASPADA / HATI-HATI TINGGI]
  - Pada harga Rp[Z]: [B]x → Kategori: [SANGAT MENARIK / MENARIK / WASPADA / HATI-HATI TINGGI]
- **Skala Acuan:** ≤2x = Sangat Menarik | 2–4x = Menarik/Wajar | >4–7x = Waspada/Mahal | >7x = Hati-Hati Tinggi
- **Kesimpulan:** [Jelaskan implikasi rasio ini — seberapa jauh harga penawaran dari nilai nominal, dan apa artinya bagi investor ritel. Sebutkan di harga mana yang lebih aman untuk masuk.]

**2. MANAJEMEN RISIKO LOT (DISTRIBUSI)**
- **Total Saham Ditawarkan:** [Jumlah] lembar ÷ 100 = **[Jumlah Lot] Lot** *(konversi wajib: 1 Lot = 100 Lembar)*
- **Kondisi yang Berlaku:** [Kondisi A — karena < 20 Juta Lot] ATAU [Kondisi B — karena ≥ 20 Juta Lot]
- **Risk 1 (Mulai Waspada):** [30% jika Kondisi A / 10% jika Kondisi B] × [Total Lot] = **[Hasil] Lot**
  *Artinya: Jika volume transaksi harian mendekati angka ini, mulai pantau ketat — potensi distribusi bandar dimulai.*
- **Risk 2 (Take Profit/Bahaya):** [50% jika Kondisi A / 30% jika Kondisi B] × [Total Lot] = **[Hasil] Lot**
  *Artinya: Jika volume mencapai angka ini, ARA rawan dibongkar. Segera amankan profit — jangan serakah.*
- **Insight:** [1-2 kalimat tentang implikasi ukuran float ini terhadap likuiditas, kemudahan bandar gerakkan harga, dan strategi yang direkomendasikan.]

**3. JUMLAH UNDERWRITER (PENJAMIN EMISI)**
- **Penjamin Pelaksana Emisi Efek:** [Sebutkan nama lengkap semua underwriter]
- **Jumlah:** [N] sekuritas → Penilaian: [≤2 = Pergerakan cenderung KUAT/SOLID | >2 = Pergerakan cenderung TERBATAS/BERAT]
- **Track Record:** [Rekam jejak underwriter ini — sering ARA berjilid atau sering banting di hari pertama?]

**4. KONGLOMERASI**
- [Jelaskan apakah ada afiliasi dengan grup konglomerasi besar atau tokoh kuat. Sebutkan implikasinya bagi investor.]

**5. TUJUAN DANA IPO**
- **Alokasi Dana:**
  [Sebutkan tiap pos penggunaan dana dan persentasenya dari PDF]
- **Penilaian SIGMA:** [Produktif (ekspansi/modal kerja) atau "gali lubang tutup lubang" (mayoritas bayar utang)?]

**6. RISIKO UTAMA YANG DIUNGKAPKAN**
[Sebutkan 2-3 risiko paling kritis dari prospektus yang wajib diperhatikan investor ritel]

**JADWAL PENTING:**
- Masa Penawaran Awal: [tanggal]
- Tanggal Efektif: [tanggal]
- Masa Penawaran Umum Perdana: [tanggal]
- Tanggal Penjatahan: [tanggal]
- Tanggal Distribusi Saham Elektronik: [tanggal]
- Tanggal Pencatatan di BEI: [tanggal]

**Kesimpulan Awal:** [2-3 kalimat merangkai semua poin — sektor bisnis, valuasi (kategori skala), kekuatan underwriter, risiko utama, dan rekomendasi apakah layak dipertimbangkan atau dihindari. Netral dan berbasis data dari PDF.]

⚠️ *DYOR — Analisa ini berdasarkan informasi dari prospektus yang diberikan. Selalu lakukan riset mendalam dan pertimbangkan semua faktor risiko sebelum membuat keputusan investasi. Keputusan final ada di tangan investor.*
"""

TEMPLATE_TEKNIKAL = """
[INSTRUKSI SANGAT TEGAS UNTUK AI]:
Kamu HANYA BOLEH menjawab MENGGUNAKAN FORMAT YANG SAMA PERSIS SEPERTI DI BAWAH INI!
JANGAN MENGOCEH PANJANG LEBAR DI LUAR FORMAT! Jangan hilangkan emoji apapun!
(Jika nama saham "SAHAM INI", BACA SENDIRI nama ticker dari gambar chart yang dilampirkan).

ATURAN MULTI-TARGET (KRITIS):
- TP HARUS berdasarkan struktur teknikal nyata: resistance terdekat, swing high, FVG unmitigated, OB bearish, level psikologis.
- JANGAN menggunakan rasio matematika (1:1, 1:2) sebagai penentu TP. Rasio boleh DIHITUNG setelah TP ditentukan dari struktur.
- Jika tidak ada resistance/zona yang jelas di atas entry → tulis hanya TP1. TP2/TP3 jangan dipaksakan.
- Jumlah TP maksimal 3, minimal 1.

ATURAN VOLUME (WAJIB DIANALISA DARI CHART):
- Lihat histogram volume di bawah chart. Identifikasi: spike, dry-up, atau pola normal.
- Spike volume + candle naik = konfirmasi bullish kuat.
- Spike volume + candle turun = distribusi atau kapitulasi — waspadai.
- Volume dry-up saat sideways/turun = akumulasi diam-diam, potensi reversal.
- Harga breakout tanpa volume = false breakout di IDX — JANGAN langsung ikut.
- Divergensi: harga naik tapi volume makin turun = momentum lemah.

[TEMPLATE YANG WAJIB KAMU KELUARKAN SEBAGAI JAWABAN (JANGAN UBAH STRUKTURNYA)]:
Berikut Trade Plan Teknikal (MnM Strategy+) untuk **{emiten}**:

🟢 **MODEL 1 — REBOUND / MEAN REVERSION (Paling Relevan Saat Ini)**
- **Bias:** [Jelaskan: posisi harga vs IFVG/OB/Demand/EMA. Sebutkan apakah ada confluence zone yang menopang.]
- **Volume:** [Analisa histogram volume di area support ini: spike? dry-up? konfirmasi atau tidak?]
- **Entry:** Rp[X] – Rp[Y]
- **Stop Loss:** Rp[Z] *(invalidasi: [sebutkan zona/candle yang di-breach]*) 
- **Target:**
  - TP1: Rp[A] *(alasan: [resistance/zona apa])*
  - TP2: Rp[B] *(alasan: [sebutkan zona])* ← hapus baris ini jika tidak ada alasan teknikal
  - TP3: Rp[C] *(alasan: [sebutkan zona])* ← hapus baris ini jika tidak ada alasan teknikal
- **Inti Model:** Tangkap pantulan di area diskon. Exit sebagian di TP1, sisanya tunggu TP2 jika struktur konfirmasi.

🔵 **MODEL 2 — CONFIRMATION / REVERSAL STRUCTURE (Paling Aman)**
- **Bias:** [Jelaskan: menunggu konfirmasi break struktur apa, di level berapa.]
- **Volume:** [Volume seperti apa yang kamu butuhkan untuk validasi breakout ini? Sebutkan standar yang perlu dilihat.]
- **Entry:** Buy on Breakout jika harga close di atas Rp[X] *(dengan volume di atas rata-rata)*.
- **Stop Loss:** Rp[Y] *(di bawah candle breakout / retest level)*
- **Target:**
  - TP1: Rp[A] *(alasan: [resistance/zona apa])*
  - TP2: Rp[B] *(alasan: [sebutkan zona])* ← hapus jika tidak ada
- **Inti Model:** Tidak menebak bottom. Konfirmasi tren > prediksi. Volume breakout wajib ada.

🟣 **MODEL 3 — DEEP ACCUMULATION (Spekulatif / Jika Penurunan Berlanjut)**
- **Bias:** [Jelaskan: skenario jika support Model 1 jebol, harga hunting likuiditas ke mana.]
- **Volume:** [Di area yang lebih dalam ini, volume dry-up atau spike seperti apa yang jadi sinyal entry?]
- **Entry:** Rp[X] – Rp[Y] *(area support/demand lebih dalam, cicil/layering)*
- **Stop Loss:** Rp[Z] *(batas invalidasi tren mayor)*
- **Target:**
  - TP1: Rp[A] *(alasan teknikal)*
  - TP2: Rp[B] *(alasan teknikal)* ← hapus jika tidak ada
- **Inti Model:** Entry sebelum konfirmasi penuh. Kompensasi dengan sizing kecil (max 30-50% alokasi normal).

⚖️ **KESIMPULAN FINAL & REKOMENDASI**
- **Struktur Saat Ini:** Mayor [Bullish/Bearish/Sideways] | Minor [Bullish/Bearish/Sideways]
- **Sinyal Volume:** [Ringkas temuan volume paling penting dari chart ini]
- **Makro Relevan:** [Faktor makro apa yang perlu diperhatikan untuk saham ini? (BI Rate/DXY/komoditas/dll)]
- **Konfirmasi Indikator:** [Sebutkan: divergence ada/tidak, posisi harga vs EMA 13/21/100/200]
- **Saran Eksekusi:** Model [1/2/3] paling rasional saat ini karena [alasan 1 kalimat].
- **Conviction Score:** [X/5] [Simbol bintang sesuai angka]

⚠️ *#DYOR. Edge ada di timing eksekusi, bukan sekadar memprediksi arah. Disiplin SL.*
"""

TEMPLATE_BANDARMOLOGI = """
[INSTRUKSI SANGAT TEGAS UNTUK AI]:
User meminta analisa PURE BANDARMOLOGI saham {emiten}.
Fokuskan 100% analisamu pada aliran dana (Broker Summary), Volume, dan Average Price. 
DILARANG KERAS membahas indikator teknikal (RSI/MACD/Support/Resistance chart) atau Laporan Keuangan/Fundamental di dalam output ini!

[TEMPLATE YANG WAJIB KAMU KELUARKAN SEBAGAI JAWABAN (JANGAN UBAH BULLET POINT)]:
Berikut adalah **Peta Kekuatan Bandarmologi (Pure Volume & Flow)** untuk **{emiten}**:

🕵️‍♂️ **1. STATUS AKUMULASI / DISTRIBUSI**
- **Fase Bandar:** [Pilih salah satu: Akumulasi / Distribusi / Mark-Up / Mark-Down / Shakeout]
- **Aktor Dominan:** [Sebutkan Top Buyer dan Top Seller]
- **Jejak Asing (Foreign Flow):** [Jelaskan apakah Asing Net Buy masif, Net Sell, atau Neutral]
- **Taktik Lanjutan:** [Jelaskan jika ada indikasi Washing (cuci barang), Bandar Nyamar pakai broker ritel, atau Fake Bid/Offer]

💰 **2. PETA HARGA & POSISI BANDAR**
- **Average Top Buyer:** Rp[X] (Harga rata-rata bandar kumpul barang)
- **Harga Market Saat Ini:** Rp[Y]
- **Status Bandar:** [Jelaskan apakah bandar sedang Floating Profit, Floating Loss, atau Break Even]

📊 **3. ANALISA VOLUME & FREKUENSI**
- **Karakter Transaksi:** [Pilih: Block Trade (Lot besar, frekuensi kecil) / Eceran (Lot kecil, frekuensi besar)]
- **Anomali Volume:** [Jelaskan apakah ada lonjakan volume signifikan, normal, atau sepi]
- **Tekanan Transaksi:** [Analisa perbandingan lot buy/sell jika terlihat di Price Table]

🎯 **TRADE PLAN (Base on Money Flow)**
- **Skenario Terpilih:** [Pilih S1-S9 berdasarkan kondisi. Contoh: "S1 - Akumulasi Dini" atau "S3 - Ikuti Asing"]
- **Entry Area:** Rp[X] - Rp[Y] (Mendekati atau maksimal setara Average Bandar)
- **Stop Loss:** Bawah Rp[Z] (Wajib cut loss jika harga jebol jauh di bawah Average Bandar dan bandar mulai distribusi)
- **Kesimpulan Aksi:** [Tulis 1 Kalimat instruksi tegas! Cth: "Ikuti akumulasi, cicil beli selama harga dijaga di sekitar area modal bandar."]

⚠️ *Analisa ini murni melacak aliran dana Smart Money. Disiplin cut loss jika aktor dominan berubah arah menjadi distribusi.*
"""

TEMPLATE_LENGKAP = """
[INSTRUKSI SANGAT TEGAS UNTUK AI]:
User meminta ANALISA LENGKAP (QUAD CONFLUENCE) untuk saham {emiten}.
Tugasmu adalah menggabungkan Bandarmologi (dari gambar/data brosum), Teknikal (gambar Chart, WAJIB CEK DIVERGENCE!), Fundamental (data live di bawah ini), dan Makro (sentimen/berita/cuaca saat ini).

[DATA LIVE FUNDAMENTAL (Gunakan sebagai referensi valuasi & kinerja)]:
{data_raw}

[TEMPLATE YANG WAJIB KAMU KELUARKAN SEBAGAI JAWABAN (JANGAN UBAH FORMAT/EMOJI)]:
**🌟 ANALISA LENGKAP (QUAD CONFLUENCE) — {emiten} 🌟**

🕵️‍♂️ **1. BANDARMOLOGI (Money Flow)**
* **Fase Bandar:** [Sebutkan durasi/tipe: Akumulasi Jangka Pendek/Menengah/Panjang, Distribusi, Mark-Up, Mark-Down, atau Shakeout]
* **Aktor Dominan:** [Sebutkan Top Buyer/Seller dan indikasikan jika ada block trade/washing]
* **Posisi Harga:** [Bandingkan Average Bandar vs Harga Market saat ini]
* **Kesimpulan Bandar:** [✅ BULLISH / ⚠️ NEUTRAL / ❌ BEARISH]. [Sebutkan alasannya singkat]

📈 **2. TEKNIKAL (MnM Strategy+)**
* **Status Struktur:** [Jelaskan posisi harga terhadap zona IFVG/OB/Demand/Supply dan indikator EMA]
* **Konfirmasi Divergence:** [⚠️ Tulis dengan TEBAL apakah ada Bullish/Bearish Divergence atau Tidak Ada Divergence]
* **Kesimpulan Teknikal:** [✅ BULLISH / ⚠️ NEUTRAL / ❌ BEARISH]. [Sebutkan alasannya singkat]

💰 **3. FUNDAMENTAL (Valuasi & Bisnis)**
* **Kinerja Terakhir:** [Analisa singkat laba/revenue dari data live atau knowledge]
* **Valuasi:** [Sebutkan rasio PER/PBV saat ini, jelaskan apakah undervalue/fair/overvalue]
* **Kesimpulan Fundamental:** [✅ BULLISH / ⚠️ NEUTRAL / ❌ BEARISH]. [Sebutkan alasannya singkat]

🌍 **4. MAKRO & SENTIMEN (Katalis)**
* **Sentimen Eksternal:** [Sebutkan sentimen makro saat ini, harga komoditas terkait, atau faktor cuaca/ekonomi yang memengaruhi emiten]
* **Kesimpulan Makro:** [✅ BULLISH / ⚠️ NEUTRAL / ❌ BEARISH]. [Sebutkan alasannya singkat]

***

⚖️ **KESIMPULAN MASTER & SUPER TRADE PLAN**

🔥 **SKOR QUAD CONFLUENCE: [X/4] [SANGAT KUAT / KUAT / MODERAT / TUNGGU]**
*(Bandar [✅/⚠️/❌] | Teknikal [✅/⚠️/❌] | Fundamental [✅/⚠️/❌] | Makro [✅/⚠️/❌])*

**🔍 Analisa Logika (The Story):**
[Tulis 3-4 kalimat cerita logis yang merangkai mengapa Bandar melakukan akumulasi/distribusi saat ini, dikaitkan dengan antisipasi rilis Fundamental/Makro, dan bagaimana hal tersebut terbaca oleh Divergence di Teknikal.]

**📋 SUPER TRADE PLAN (Skenario Terpilih: [Sebutkan misal S1 / S3 / S4])**
* **Strategi Eksekusi:** [Cth: Buy on Weakness / Wait for Breakout / Avoid]
* **Area Entry:** Rp[X] - Rp[Y] (Konfluensi antara Average Bandar & Support Teknikal)
* **Target Profit (TP 1):** Rp[A] (Resistance teknikal minor)
* **Target Profit (TP 2):** Rp[B] (Target valuasi / Resistance mayor)
* **Batas Aman (Stop Loss):** Bawah Rp[Z] (Wajib angka mutlak, tempat invalidasi teknikal & bandar)
* **Risk/Reward Ratio:** 1 : [X]
* **Keputusan Final:** **[STRONG BUY / BUY / WAIT / SELL / STRONG SELL]**. [Sertakan alasan porsi sizing dana, cth: Sizing penuh karena probabilitas tinggi].

⚠️ *#DYOR. Edge ada di timing eksekusi, bukan sekadar memprediksi arah. Disiplin SL.*
"""

# ─── FUNGSI API GEMINI ───
def _get_gemini_keys():
    """
    Auto-scan semua Gemini API key dari Secrets.
    Support: GEMINI_API_KEY, GEMINI_API_KEY2–5, GEMINI_KEY, GEMINI_KEY2–5, GOOGLE_API_KEY
    Tambah key baru di Secrets → langsung aktif tanpa edit kode.
    """
    key_names = (
        ["GEMINI_API_KEY"] +
        [f"GEMINI_API_KEY{i}" for i in range(2, 6)] +   # GEMINI_API_KEY2 s/d GEMINI_API_KEY5
        ["GEMINI_KEY"] +
        [f"GEMINI_KEY{i}" for i in range(2, 6)] +        # GEMINI_KEY2 s/d GEMINI_KEY5
        ["GOOGLE_API_KEY"]
    )
    keys = []
    for name in key_names:
        val = st.secrets.get(name, "")
        if val and len(val) > 10 and val not in keys:
            keys.append(val)
    return keys

def _call_gemini_vision(prompt, img_b64, img_mime, multi_imgs=None):
    """Gemini Vision — PRIMARY untuk semua request gambar. Auto-rotate key & model."""
    import urllib.request, json as _j
    keys = _get_gemini_keys()
    if not keys: raise Exception("Tidak ada Gemini API key yang valid di Secrets")
    if not keys: raise Exception("Tidak ada Gemini API key yang valid di Secrets")
    models = ["gemini-2.5-flash", "gemini-2.0-flash"]
    last_err = ""
    for api_key in keys:
        for model_name in models:
            try:
                _parts = []
                if multi_imgs:
                    for _b64, _mime, _ in multi_imgs[:5]: _parts.append({"inlineData": {"mimeType": _mime, "data": _b64}})
                elif img_b64 and img_mime: _parts.append({"inlineData": {"mimeType": img_mime, "data": img_b64}})
                teks_gabungan = f"{SYSTEM_PROMPT['content']}\n\n[PERTANYAAN USER]:\n{prompt}"
                _parts.append({"text": teks_gabungan})
                payload = {"contents": [{"role": "user", "parts": _parts}], "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192}}
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                req = urllib.request.Request(url, data=_j.dumps(payload).encode(), headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=45) as r: data = _j.loads(r.read())
                return data["candidates"][0]["content"]["parts"][0]["text"], model_name
            except Exception as e:
                last_err = str(e); continue
    raise Exception(f"Gemini Vision gagal semua model/key: {last_err}")

def _call_gemini_text(messages):
    """Gemini Text — FALLBACK untuk text jika semua Groq 70B rate limit. Pakai full SYSTEM_PROMPT."""
    import urllib.request, json as _j
    keys = _get_gemini_keys()
    if not keys: raise Exception("Tidak ada Gemini API key yang valid di Secrets")
    models = ["gemini-2.5-flash", "gemini-2.0-flash"]
    last_err = ""
    for api_key in keys:
        for model_name in models:
            try:
                gemini_contents = []
                for m in messages:
                    r = m.get("role", "")
                    t = m.get("content", "") or ""
                    # Bersihkan simbol AI dari history agar tidak double
                    t = re.sub(r'\n\n\*?\([✨⚡🤖].*?\)\*?', '', t)
                    if r == "user": gemini_contents.append({"role": "user", "parts": [{"text": t}]})
                    elif r == "assistant": gemini_contents.append({"role": "model", "parts": [{"text": t}]})
                if not gemini_contents: gemini_contents = [{"role": "user", "parts": [{"text": "Halo"}]}]
                gemini_contents[0]["parts"][0]["text"] = f"{SYSTEM_PROMPT['content']}\n\n{gemini_contents[0]['parts'][0]['text']}"
                payload = {"contents": gemini_contents, "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192}}
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                req = urllib.request.Request(url, data=_j.dumps(payload).encode(), headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=35) as r: data = _j.loads(r.read())
                return data["candidates"][0]["content"]["parts"][0]["text"], model_name
            except Exception as e:
                last_err = str(e); continue
    raise Exception(f"Gemini Text gagal semua model/key: {last_err}")

# ─── PENGATURAN UI CSS KHUSUS ───
st.markdown(f"""
<style>
/* PENANGKAL ERROR COPY PASTE: MEMAKSA STATUS UPLOAD UNTUK TETAP TERLIHAT */
[data-testid="stStatusWidget"] {{ display: flex !important; visibility: visible !important; height: auto !important; overflow: visible !important; opacity: 1 !important; }}

section[data-testid="stSidebar"], [data-testid="collapsedControl"], [data-testid="stSidebarCollapseButton"] {{ display: none !important; }}
[data-testid="stToolbar"], .viewerBadge_container__r5tak, [class*="viewerBadge"], .stDeployButton, #MainMenu, footer {{ display: none !important; }}

/* FIX: MENGHILANGKAN GARIS/GAP PUTIH DI ATAS SECARA TOTAL */
header[data-testid="stHeader"] {{ display: none !important; height: 0 !important; min-height: 0 !important; padding: 0 !important; margin: 0 !important; visibility: hidden !important; border: none !important; background: transparent !important; }}
div[data-testid="stDecoration"] {{ display: none !important; height: 0 !important; visibility: hidden !important; border: none !important; background: transparent !important; }}
.stApp > header {{ display: none !important; background: transparent !important; border: none !important; }}
.stAppViewContainer {{ padding-top: 0 !important; margin-top: 0 !important; }}

[data-testid="stMainBlockContainer"] {{ padding-top: 3rem !important; margin-top: 0 !important; }}
[data-testid="stChatMessageContent"], [data-testid="stMarkdownContainer"] {{ text-align: left !important; }}

/* =========================================================
   FIX SPASI LEBAR DI CHAT (REMOVE SPACE BEFORE PARAGRAPH) 
   ========================================================= */
[data-testid="stMarkdownContainer"] p {{
    margin-top: 0 !important;
    margin-bottom: 4px !important; /* Paksa jarak antar paragraf sangat rapat */
    line-height: 1.5 !important;
}}
[data-testid="stMarkdownContainer"] ul, [data-testid="stMarkdownContainer"] ol {{
    margin-top: 4px !important;
    margin-bottom: 12px !important;
    padding-left: 20px !important;
}}
[data-testid="stMarkdownContainer"] li {{
    margin-top: 0 !important;
    margin-bottom: 4px !important; /* Paksa jarak antar bullet point rapat */
    line-height: 1.5 !important;
}}
/* Jika AI memberikan heading, rapatkan juga dengan teks di bawahnya */
[data-testid="stMarkdownContainer"] h1, 
[data-testid="stMarkdownContainer"] h2, 
[data-testid="stMarkdownContainer"] h3 {{
    margin-top: 16px !important;
    margin-bottom: 8px !important;
}}
/* Menghapus spasi ekstra jika ada tag <p> di dalam <li> */
[data-testid="stMarkdownContainer"] li > p {{
    margin-bottom: 0 !important;
}}
</style>
""", unsafe_allow_html=True)
_hist_items = ""
for _sesi in st.session_state.sessions:
    _sid = _sesi["id"]; _is_act = _sid == st.session_state.active_id; _td = _sesi["title"][:35].replace("'","").replace("`","").replace("\\","").replace('"',""); _fw = "700" if _is_act else "400"; _bg = C['hover'] if _is_act else "transparent"
    _hist_items += f"""
(function(){{
    var row=pd.createElement('div'); row.style.cssText='display:flex;align-items:center;width:100%;';
    var a=pd.createElement('a'); a.textContent='{_td}'; var u=new URL(window.parent.location.href); u.searchParams.set('do','sel_{_sid}'); a.href=u.toString(); a.style.cssText='flex:1;display:block;padding:12px 8px 12px 18px;font-size:1rem;color:{C["text"]};background:{_bg};font-weight:{_fw};border:none;text-align:left;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-decoration:none;min-width:0;'; a.onmouseenter=function(){{this.style.background='{C["hover"]}'}}; a.onmouseleave=function(){{this.style.background='{_bg}'}};
    var del=pd.createElement('button'); del.innerHTML='🗑'; del.title='Hapus'; del.style.cssText='padding:8px 12px;background:transparent;border:none;cursor:pointer;font-size:0.85rem;opacity:0.35;flex-shrink:0;color:{C["text"]};'; del.onmouseenter=function(){{this.style.opacity='1';this.style.color='#ff5555';}}; del.onmouseleave=function(){{this.style.opacity='0.35';this.style.color='{C["text"]}';}}; del.onclick=function(e){{ e.preventDefault();e.stopPropagation(); if(confirm('Hapus obrolan ini?')){{ var u2=new URL(window.parent.location.href); u2.searchParams.set('del','{_sid}'); u2.searchParams.delete('do'); window.parent.location.href=u2.toString(); }} }};
    row.appendChild(a); row.appendChild(del); h.appendChild(row);
}})();
"""

components.html(f"""
<script>
(function(){{
var pd=window.parent.document;
var kipmLogo = pd.getElementById('kipm-mobile-logo'); if (kipmLogo) kipmLogo.style.display = 'none !important';
var kipmStyle = pd.getElementById('kipm-mobile-logo-style'); if (kipmStyle) kipmStyle.remove();
['spbtn','spmenu','sphist','spui','sigma-mobile-css'].forEach(function(id){{ var el=pd.getElementById(id); if(el) el.remove(); }});
var s=pd.createElement('style'); s.id='sigma-mobile-css';
s.textContent=`
#spbtn{{position:fixed;bottom:20px;left:20px;width:50px;height:50px;border-radius:50%; background:{C["sidebar_bg"]};color:{C["text"]};border:1px solid {C["border"]}; cursor:pointer;z-index:999999; display:flex;align-items:center;justify-content:center; box-shadow:0 6px 20px rgba(0,0,0,0.5);padding:0;transition:transform 0.2s, background 0.2s;}} 
#spbtn:hover{{transform:scale(1.08); background:{C["hover"]};}}
#spmenu,#sphist{{position:fixed;left:20px;bottom:85px; background:{C["sidebar_bg"]};border:1px solid {C["border"]}; border-radius:16px;box-shadow:0 -4px 24px rgba(0,0,0,0.5); z-index:999998;display:none;overflow:hidden;min-width:260px;}} 
#sphist{{max-height:55vh;overflow-y:auto;}}
.smi{{display:flex;align-items:center;gap:14px;padding:13px 18px; font-size:1rem;color:{C["text"]};cursor:pointer;border:none; background:transparent;width:100%;text-align:left;text-decoration:none;transition:background 0.2s;}} .smi:hover{{background:{C["hover"]}}}
.smico{{width:32px;height:32px;border-radius:8px;display:flex; align-items:center;justify-content:center;font-size:16px; background:{C["hover"]};flex-shrink:0;}}
.smsp{{border:none;border-top:1px solid {C["border"]};margin:4px 0;}} .smhd{{padding:8px 18px 4px;font-size:0.68rem;color:{C["text_muted"]}; font-weight:600;letter-spacing:1px;}} .smred{{color:#f55!important}}
`; pd.head.appendChild(s);
var btn=pd.createElement('button'); btn.id='spbtn'; btn.innerHTML='<svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2.5"/><circle cx="12" cy="12" r="2.5"/><circle cx="12" cy="19" r="2.5"/></svg>'; pd.body.appendChild(btn);
var m=pd.createElement('div');m.id='spmenu';
m.innerHTML=`
    <a class="smi" id="smi-new"><span class="smico">✎</span>Percakapan Baru</a>
    <button class="smi" id="smi-hist"><span class="smico">☰</span>History</button>
    <div class="smsp"></div><div class="smhd">FITUR</div>
    <a class="smi" id="smi-ai"><span class="smico">🤖</span>SIGMA AI Chat</a>
    <a class="smi" id="smi-stats"><span class="smico">📊</span>SIGMA Terminal</a>
    <div class="smsp"></div><div class="smhd">PENAMPILAN</div>
    <a class="smi" id="smi-dark"><span class="smico">🌙</span>Dark Mode {'✓' if st.session_state.theme=='dark' else ''}</a>
    <a class="smi" id="smi-light"><span class="smico">☀️</span>Light Mode {'✓' if st.session_state.theme=='light' else ''}</a>
    <div class="smsp"></div><a class="smi smred" id="smi-out"><span class="smico">🚪</span>Sign Out</a>
`; pd.body.appendChild(m);
var h=pd.createElement('div');h.id='sphist'; h.innerHTML='<div class="smhd">RIWAYAT OBROLAN</div>';
{_hist_items} pd.body.appendChild(h);
btn.onclick=function(e){{ e.preventDefault(); e.stopPropagation(); m.style.display = (m.style.display === 'block') ? 'none' : 'block'; h.style.display = 'none'; }};
(function(){{
    var u; u=new URL(window.parent.location.href); u.searchParams.set('do','newchat'); pd.getElementById('smi-new').href=u.toString();
    pd.getElementById('smi-hist').onclick=function(){{m.style.display='none';h.style.display='block';}};
    u=new URL(window.parent.location.href); u.searchParams.set('do','view_ai'); pd.getElementById('smi-ai').href=u.toString();
    u=new URL(window.parent.location.href); u.searchParams.set('do','view_stats'); pd.getElementById('smi-stats').href=u.toString();
    u=new URL(window.parent.location.href); u.searchParams.set('do','theme_dark'); pd.getElementById('smi-dark').href=u.toString();
    u=new URL(window.parent.location.href); u.searchParams.set('do','theme_light'); pd.getElementById('smi-light').href=u.toString();
    u=new URL(window.parent.location.href); u.searchParams.delete('sigma_token'); u.searchParams.set('do','logout'); pd.getElementById('smi-out').href=u.toString();
}})();
pd.addEventListener('click',function(e){{ if(!btn.contains(e.target) && !m.contains(e.target)) m.style.display='none'; if(!btn.contains(e.target) && !h.contains(e.target) && !m.contains(e.target)) h.style.display='none'; }});
}})();
</script>
""", height=0)

if "del" in st.query_params:
    _del_id = st.query_params.get("del", "")
    if _del_id and st.session_state.get("user"):
        st.session_state.sessions = [s for s in st.session_state.sessions if s["id"] != _del_id]
        if not st.session_state.sessions: st.session_state.sessions = [new_session()]
        if st.session_state.active_id == _del_id: st.session_state.active_id = st.session_state.sessions[0]["id"]
        _to_save = [{"id": s["id"], "title": s["title"], "created": s["created"], "messages": [dict(m) for m in s["messages"] if m["role"] != "system"]} for s in st.session_state.sessions]
        save_user(st.session_state.user["email"], {"theme": st.session_state.get("theme", "dark"), "sessions": _to_save, "active_id": st.session_state.active_id})
    try: st.query_params.pop("del", None)
    except: pass
    st.rerun()

if "do" in st.query_params:
    _do = st.query_params.get("do", "")
    _tok = st.query_params.get("sigma_token", st.session_state.get("current_token", ""))
    if _do == "logout":
        if _tok:
            try: os.remove(os.path.join(DATA_DIR, f"token_{_tok}.json"))
            except: pass
        st.session_state.clear(); st.query_params.clear()
        components.html("""<script>try { localStorage.removeItem('sigma_token'); } catch(e) {} setTimeout(function(){ window.parent.location.replace(window.parent.location.pathname); }, 100);</script>""", height=0)
        st.stop()
    elif _do == "view_stats": st.session_state.current_view = "dashboard"; st.query_params.pop("do", None); st.rerun()
    elif _do == "view_ai": st.session_state.current_view = "chat"; st.query_params.pop("do", None); st.rerun()
    elif _do == "theme_dark": st.session_state.theme = "dark"; st.query_params.pop("do", None); st.rerun()
    elif _do == "theme_light": st.session_state.theme = "light"; st.query_params.pop("do", None); st.rerun()
    elif _do == "newchat":
        st.session_state.current_view = "chat"
        ns = {"id": str(uuid.uuid4()), "title": "Obrolan Baru", "created": datetime.now().isoformat(), "messages": [{"role": "system", "content": SYSTEM_PROMPT["content"]}]}
        st.session_state.sessions.insert(0, ns); st.session_state.active_id = ns["id"]; st.query_params.pop("do", None); st.rerun()
    elif _do.startswith("sel_"):
        st.session_state.current_view = "chat"; _sid = _do[4:]; st.session_state.active_id = _sid; st.query_params.pop("do", None); st.rerun()

active = get_active()
current_view = st.session_state.get("current_view", "chat")

if user:
    sessions_to_save = [{"id": s["id"], "title": s["title"], "created": s["created"], "messages": [dict(m) for m in s["messages"] if m["role"] != "system"]} for s in st.session_state.sessions]
    
    save_user(user["email"], {
        "theme": st.session_state.get("theme", "dark"), 
        "sessions": sessions_to_save, 
        "active_id": st.session_state.active_id,
        "current_view": st.session_state.get("current_view", "chat"), "selected_system": st.session_state.get("selected_system", "chat"), "selected_system": st.session_state.get("selected_system", "chat"),
        "selected_system": st.session_state.get("selected_system", "chat")
    })
_new_token = st.session_state.pop("new_token", None)
if _new_token: components.html(f"<script>try {{ localStorage.setItem('sigma_token', '{_new_token}'); }} catch(e) {{}}</script>", height=0)
if st.session_state.user is None:
    if "sigma_token" not in st.query_params:
        # Jika tidak ada token di URL, coba cari di memori browser
        components.html("<script>(function() { try { var token = localStorage.getItem('sigma_token'); if (token) { var url = window.parent.location.href.split('?')[0]; window.parent.location.replace(url + '?sigma_token=' + token); } } catch(e) {} })();</script>", height=0)
    else:
        # FIX APPLE LOOP: Jika ada token di URL tapi gagal login (server amnesia), HANCURKAN token lama!
        components.html("<script>try { localStorage.removeItem('sigma_token'); } catch(e) {}</script>", height=0)
        try: st.query_params.pop("sigma_token", None)
        except: pass






# ─────────────────────────────────────────────
# PART 9: SIGMA TERMINAL (MACRO, MSCI TRACKER, HEATMAP & NEWS)
# ─────────────────────────────────────────────

# --- OBAT ANTI AMNESIA ---
if "amnesia_fixed" not in st.session_state and st.session_state.get("user"):
    try:
        _saved_data = load_user(st.session_state.user["email"])
        if _saved_data:
            if "current_view" in _saved_data:
                st.session_state.current_view = _saved_data["current_view"]
            if "selected_system" in _saved_data:
                st.session_state.selected_system = _saved_data["selected_system"]
    except: pass
    st.session_state.amnesia_fixed = True

current_view = st.session_state.get("current_view", "chat")

if current_view == "dashboard":
    try:
        import yfinance as yf
        import pandas as pd
        import streamlit.components.v1 as components
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        import re
        import json
    except ImportError:
        st.error("&#9888; Library 'yfinance', 'pandas', atau 'plotly' belum terinstall.")
        st.stop()

# FIX UKURAN DESKTOP & MOBILE (ANTI TERPOTONG)
    st.markdown("""
    <style>
    /* Desktop: Kasih jarak kanan-kiri */
    [data-testid="stMainBlockContainer"] {
        max-width: 1200px !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        margin: 0 auto !important;
    }
    /* Mobile: Paksa grafik mengecil & anti geser */
    @media (max-width: 768px) {
        .stApp, html, body { overflow-x: hidden !important; width: 100vw !important; }
        [data-testid="stMainBlockContainer"] { padding-left: 12px !important; padding-right: 12px !important; }
        .stLineChart, canvas, iframe, [data-testid="stVerticalBlock"] > div { max-width: 100% !important; width: 100% !important; }
        .stDataFrame { overflow-x: auto !important; }
    }

        
        [data-testid="stMainBlockContainer"] {
            max-width: 100vw !important;
            width: 100vw !important;
            padding-left: 12px !important;
            padding-right: 12px !important;
            padding-top: 1rem !important;
            margin: 0 !important;
            overflow-x: hidden !important;
        }

        .stLineChart, iframe, canvas, [data-testid="stVerticalBlock"] > div {
            max-width: 100% !important;
            width: 100% !important;
        }

        .stDataFrame {
            width: 100% !important;
            overflow-x: auto !important; 
        }

        [data-testid="stMetric"] {
            padding: 10px 10px !important;
        }
        
        [data-testid="stMetricValue"] {
            font-size: 1.1rem !important; 
        }
        
        [data-testid="stVerticalBlock"] {
            gap: 0.5rem !important;
        }
    }

    section[data-testid="stMain"] {
        align-items: center !important;
    }
    </style>
    """, unsafe_allow_html=True)

    is_dark = st.session_state.get("theme", "dark") == "dark"

    text_main  = "#e8eaf0" if is_dark else "#0d1117"
    text_sub   = "#6b7a99" if is_dark else "#64748b"
    card_bg    = "rgba(10,14,26,0.85)" if is_dark else "#ffffff"
    card_border= "rgba(245,194,66,0.12)" if is_dark else "#e2e8f0"
    card_shadow= "0 4px 24px rgba(0,0,0,0.6)" if is_dark else "0 4px 16px rgba(0,0,0,0.06)"
    met_bg     = "rgba(8,12,22,0.9)" if is_dark else "#f8fafc"
    met_border = "rgba(245,194,66,0.18)" if is_dark else "#e2e8f0"
    met_shadow = "0 2px 12px rgba(0,0,0,0.5)" if is_dark else "0 2px 8px rgba(0,0,0,0.04)"
    met_hover  = "#F5C242"
    tv_theme   = "dark" if is_dark else "light"
    # Tambahkan baris ini di bagian inisialisasi variabel dashboard Anda
    news_theme = "dark" if is_dark else "light"
    
    # Sekarang variabel ini aman digunakan di bawah:
    idx_news_widget = f"""
    <div class="tradingview-widget-container" style="height:100%;width:100%;">
      <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-timeline.js" async>
      {{ 
        "feedMode": "market", 
        "market": "indonesia", 
        "isTransparent": true, 
        "displayMode": "regular", 
        "width": "100%", 
        "height": "100%", 
        "colorTheme": "{news_theme}", 
        "locale": "id" 
      }}
      </script>
    </div>
    """
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap');

    .stApp, .stApp * {{ font-family: 'IBM Plex Sans', sans-serif !important; }}

    [data-testid="stDataFrame"] [data-testid="stElementToolbar"],
    [data-testid="stDataFrame"] [aria-haspopup="menu"],
    [data-testid="stDataFrame"] .gdg-header-action,
    [data-testid="stDataFrame"] div[class*="header"] svg {{ display: none !important; }}
    [data-testid="stDataFrame"] div[role="button"] {{ pointer-events: none !important; }}

    [data-testid="stMetric"] {{
        background: {met_bg} !important;
        border: 1px solid {met_border} !important;
        border-radius: 6px !important;
        padding: 14px 18px 12px !important;
        box-shadow: {met_shadow} !important;
        transition: border-color 0.2s, box-shadow 0.2s !important;
        position: relative !important;
        overflow: hidden !important;
    }}
    [data-testid="stMetric"]::before {{
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 2px;
        background: linear-gradient(90deg, transparent, #F5C242, transparent);
        opacity: 0;
        transition: opacity 0.2s;
    }}
    [data-testid="stMetric"]:hover {{ border-color: rgba(245,194,66,0.45) !important; box-shadow: 0 0 20px rgba(245,194,66,0.08) !important; }}
    [data-testid="stMetric"]:hover::before {{ opacity: 1; }}
    [data-testid="stMetricValue"] {{
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 1.35rem !important;
        font-weight: 600 !important;
        color: {text_main} !important;
        letter-spacing: -0.5px !important;
    }}
    [data-testid="stMetricLabel"] {{
        font-size: 0.72rem !important;
        font-weight: 500 !important;
        letter-spacing: 0.08em !important;
        text-transform: uppercase !important;
        color: {text_sub} !important;
    }}
    [data-testid="stMetricDelta"] {{ font-family: 'IBM Plex Mono', monospace !important; font-size: 0.8rem !important; }}

    [data-testid="stTabs"] [role="tablist"] {{
        background: {"rgba(6,9,18,0.95)" if is_dark else "#f1f5f9"} !important;
        border: 1px solid {"rgba(245,194,66,0.1)" if is_dark else "#e2e8f0"} !important;
        border-radius: 8px !important;
        padding: 5px !important;
        gap: 2px !important;
        backdrop-filter: blur(10px) !important;
    }}
    [data-testid="stTabs"] button[role="tab"] {{
        font-family: 'IBM Plex Sans', sans-serif !important;
        font-size: 0.78rem !important;
        font-weight: 500 !important;
        letter-spacing: 0.05em !important;
        text-transform: uppercase !important;
        border-radius: 5px !important;
        color: {"rgba(107,122,153,1)" if is_dark else "#64748b"} !important;
        padding: 8px 16px !important;
        border: none !important;
        background: transparent !important;
        transition: all 0.2s !important;
    }}
    [data-testid="stTabs"] button[role="tab"]:hover {{
        color: {"rgba(232,234,240,0.8)" if is_dark else "#334155"} !important;
        background: {"rgba(245,194,66,0.06)" if is_dark else "rgba(0,0,0,0.04)"} !important;
    }}
    [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{
        background: {"rgba(245,194,66,0.12)" if is_dark else "#ffffff"} !important;
        color: {"#F5C242" if is_dark else "#0d1117"} !important;
        font-weight: 600 !important;
        box-shadow: {"0 1px 8px rgba(245,194,66,0.15), inset 0 0 0 1px rgba(245,194,66,0.2)" if is_dark else "0 1px 4px rgba(0,0,0,0.1)"} !important;
    }}
    [data-testid="stTabs"] [role="tabpanel"] {{
        background: transparent !important;
        border: none !important;
        padding: 0 !important;
        margin-top: 16px !important;
    }}

    .trm-section {{ display: flex; align-items: center; gap: 10px; margin: 28px 0 14px; }}
    .trm-section-line {{ flex: 1; height: 1px; background: {"rgba(245,194,66,0.12)" if is_dark else "#e2e8f0"}; }}
    .trm-section-label {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.68rem;
        font-weight: 600;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: {"#F5C242" if is_dark else "#94a3b8"};
        white-space: nowrap;
        padding: 3px 10px;
        border: 1px solid {"rgba(245,194,66,0.2)" if is_dark else "#e2e8f0"};
        border-radius: 3px;
        background: {"rgba(245,194,66,0.05)" if is_dark else "#f8fafc"};
    }}

    .trm-card {{
        background: {met_bg};
        border: 1px solid {met_border};
        border-radius: 8px;
        padding: 20px 22px;
        box-shadow: {met_shadow};
        transition: border-color 0.2s;
        margin-bottom: 12px;
    }}
    .trm-card:hover {{ border-color: rgba(245,194,66,0.3); }}
    .trm-card-title {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.7rem;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: #F5C242;
        margin-bottom: 10px;
        font-weight: 600;
    }}

    .trm-insight {{
        background: {"rgba(245,194,66,0.05)" if is_dark else "#fffbeb"};
        border-left: 3px solid #F5C242;
        border-radius: 0 6px 6px 0;
        padding: 14px 18px;
        margin: 12px 0;
        font-size: 0.88rem;
        color: {text_main};
        line-height: 1.6;
    }}

    .fancy-divider {{
        border: 0;
        height: 1px;
        background: {"rgba(245,194,66,0.1)" if is_dark else "#e2e8f0"};
        margin: 24px 0;
    }}

    [data-testid="stTabs"] ~ div .stButton > button,
    [data-testid="stVerticalBlock"] .stButton > button {{
        background: {"rgba(245,194,66,0.1)" if is_dark else "rgba(245,194,66,0.08)"} !important;
        color: {"#F5C242" if is_dark else "#92700a"} !important;
        border: 1px solid {"rgba(245,194,66,0.3)" if is_dark else "rgba(245,194,66,0.35)"} !important;
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.78rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.06em !important;
        text-transform: uppercase !important;
        border-radius: 5px !important;
        padding: 10px 18px !important;
        transition: all 0.2s !important;
        box-shadow: none !important;
    }}
    [data-testid="stTabs"] ~ div .stButton > button:hover,
    [data-testid="stVerticalBlock"] .stButton > button:hover {{
        background: {"rgba(245,194,66,0.18)" if is_dark else "rgba(245,194,66,0.15)"} !important;
        border-color: {"rgba(245,194,66,0.6)" if is_dark else "rgba(245,194,66,0.6)"} !important;
        box-shadow: 0 0 12px rgba(245,194,66,0.15) !important;
    }}

   .trm-ticker-wrap {{ overflow: hidden; max-width: 100%;
        white-space: nowrap;
        border-top: 1px solid {"rgba(245,194,66,0.1)" if is_dark else "#e2e8f0"};
        border-bottom: 1px solid {"rgba(245,194,66,0.1)" if is_dark else "#e2e8f0"};
        background: {"rgba(245,194,66,0.03)" if is_dark else "#fffdf0"};
        padding: 7px 0;
        margin: 0 0 20px;
        position: relative;
    }}
    .trm-ticker-tape {{
        display: inline-block;
        animation: ticker-scroll 40s linear infinite;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.72rem;
        letter-spacing: 0.06em;
        color: {"rgba(232,234,240,0.7)" if is_dark else "#64748b"};
    }}
    .trm-ticker-tape .up {{ color: #26a69a; }}
    .trm-ticker-tape .dn {{ color: #f23645; }}
    .trm-ticker-tape .sep {{ color: {"rgba(245,194,66,0.3)" if is_dark else "#d4a800"}; margin: 0 18px; }}
    @keyframes ticker-scroll {{
        0%   {{ transform: translateX(0); }}
        100% {{ transform: translateX(-50%); }}
    }}

    [data-testid="stTextInput"] input {{
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.95rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.08em !important;
        background: {met_bg} !important;
        border: 1px solid {met_border} !important;
        border-radius: 5px !important;
        color: {text_main} !important;
        padding: 10px 14px !important;
    }}
    [data-testid="stTextInput"] input:focus {{
        border-color: rgba(245,194,66,0.5) !important;
        box-shadow: 0 0 0 2px rgba(245,194,66,0.08) !important;
    }}
    [data-testid="stTextInput"] label, [data-testid="stSelectbox"] label {{
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.68rem !important;
        letter-spacing: 0.1em !important;
        text-transform: uppercase !important;
        color: {text_sub} !important;
        font-weight: 500 !important;
    }}

    /* ── MOBILE FIXES ─────────────────────────────── */
    @media (max-width: 768px) {{
        /* Terminal header: wrap instead of overflow */
        [data-testid="stMainBlockContainer"] > div > div > div > div[style*="display: flex"][style*="justify-content: space-between"],
        [data-testid="stMainBlockContainer"] > div > div > div > div[style*="display:flex"][style*="justify-content:space-between"] {{
            flex-wrap: wrap !important;
            gap: 6px !important;
            padding: 12px 4px 6px !important;
        }}

        /* Terminal header title: ukuran lebih kecil */
        span[style*="1.45rem"] {{
            font-size: 1.1rem !important;
            letter-spacing: 0.08em !important;
        }}
        span[style*="KIPM"] {{
            font-size: 0.58rem !important;
        }}

        /* Ticker tape: anti overflow */
        .trm-ticker-wrap {{
            overflow: hidden !important;
            max-width: 100vw !important;
        }}

        /* Tabs: ukuran label lebih kecil */
        [data-testid="stTabs"] button[role="tab"] {{
            font-size: 0.65rem !important;
            padding: 6px 8px !important;
            letter-spacing: 0.02em !important;
        }}

        /* Metric cards: anti overflow */
        [data-testid="stMetric"] {{
            padding: 10px 10px 8px !important;
            min-width: 0 !important;
        }}
        [data-testid="stMetricValue"] {{
            font-size: 1rem !important;
        }}
        [data-testid="stMetricLabel"] {{
            font-size: 0.62rem !important;
        }}

        /* Economic Calendar: stack to 1 column on mobile */
        .cal-wrap {{
            overflow-x: hidden !important;
            width: 100% !important;
        }}
        .cal-row {{
            grid-template-columns: 80px 1fr 90px 44px !important;
            gap: 4px !important;
            padding: 8px 10px !important;
        }}
        .cal-dt {{ font-size: 0.60rem !important; }}
        .cal-ev {{ font-size: 0.66rem !important; }}
        .cal-fc {{ font-size: 0.64rem !important; }}
        .cal-pv {{ font-size: 0.58rem !important; }}
        .cal-bdg {{ font-size: 0.55rem !important; padding: 2px 4px !important; }}

        /* Sector rotation table: full width */
        [data-testid="stDataFrame"] {{
            width: 100% !important;
            overflow-x: auto !important;
        }}

        /* news cards: full height, scrollable */
        .news-card-sigma {{
            height: 420px !important;
        }}

        /* trm-card: no horizontal overflow */
        .trm-card {{
            padding: 14px 14px !important;
            word-break: break-word !important;
        }}
        .trm-insight {{
            font-size: 0.82rem !important;
            padding: 12px 12px !important;
            word-break: break-word !important;
        }}

        /* Line charts: full width */
        [data-testid="stVegaLiteChart"],
        [data-testid="stArrowVegaLiteChart"],
        canvas {{
            max-width: 100% !important;
            width: 100% !important;
        }}

        /* FTSE/MSCI table header label: allow wrap on mobile */
        .trm-section-label {{
            font-size: 0.55rem !important;
            letter-spacing: 0.05em !important;
            padding: 3px 6px !important;
            white-space: normal !important;
            word-break: break-word !important;
            text-align: center !important;
            line-height: 1.3 !important;
        }}
        .trm-section {{
            margin: 20px 0 10px !important;
            gap: 6px !important;
        }}
        .trm-card {{
            padding: 12px 12px !important;
            word-break: break-word !important;
            margin-bottom: 10px !important;
        }}
        .trm-insight {{
            font-size: 0.82rem !important;
            padding: 10px 10px !important;
            word-break: break-word !important;
            margin: 8px 0 !important;
        }}
        .fancy-divider {{
            margin: 14px 0 !important;
        }}
        /* Shareholder screening table */
        .sh-screen-table {{
            font-size: 0.65rem !important;
        }}
        .sh-screen-table th {{
            font-size: 0.52rem !important;
            padding: 5px 5px !important;
        }}
        .sh-screen-table td {{
            padding: 5px 5px !important;
        }}
    }}
    </style>
    """, unsafe_allow_html=True)

    from datetime import datetime as _dt
    _now = _dt.now().strftime("%d %b %Y  %H:%M WIB")
    st.markdown(f"""
    <div style="
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 6px;
        padding: 18px 4px 6px;
        border-bottom: 1px solid {'rgba(245,194,66,0.12)' if is_dark else '#e2e8f0'};
        margin-bottom: 18px;
    ">
        <div style="display:flex; align-items:baseline; gap:10px; flex-wrap:wrap;">
            <span style="
                font-family:'IBM Plex Mono',monospace;
                font-size:clamp(1.0rem, 4vw, 1.45rem);
                font-weight:700;
                letter-spacing:0.10em;
                color:#F5C242;
                text-transform:uppercase;
            ">SIGMA TERMINAL</span>
            <span style="
                font-family:'IBM Plex Mono',monospace;
                font-size:clamp(0.55rem, 2vw, 0.65rem);
                color:{'rgba(107,122,153,0.8)' if is_dark else '#94a3b8'};
                letter-spacing:0.1em;
                border:1px solid {'rgba(107,122,153,0.25)' if is_dark else '#e2e8f0'};
                padding:2px 8px;
                border-radius:3px;
            ">KIPM &mdash; MnM</span>
        </div>
        <div style="
            font-family:'IBM Plex Mono',monospace;
            font-size:clamp(0.60rem, 2vw, 0.70rem);
            color:{'rgba(107,122,153,0.7)' if is_dark else '#94a3b8'};
            letter-spacing:0.08em;
            text-align:right;
        ">
            <span style="color:{'#3ddc84' if is_dark else '#16a34a'}">&#9679; LIVE</span>&nbsp;&nbsp;{_now}
        </div>
    </div>
    """, unsafe_allow_html=True)

    _tape_items = [
        # GLOBAL INDICES & VOLATILITY
        ("IHSG",     "^JKSE"),
        ("S&P500",   "^GSPC"),
        ("Dow Jones","^DJI"),
        ("Nasdaq",   "^IXIC"),
        ("FTSE 100", "^FTSE"),
        ("Nikkei",   "^N225"),
        ("Hang Seng","^HSI"),
        ("Shanghai", "000001.SS"),
        ("VIX",      "^VIX"),
        # COMMODITIES & FOREX
        ("USD/IDR",  "IDR=X"),
        ("DXY",      "DX-Y.NYB"),
        ("Gold",     "GC=F"),
        ("WTI",      "CL=F"),
        ("Brent",    "BZ=F"),
        ("Coal",     "NCF=F"),
        ("Palm Oil", "MYP=F"),
        ("Nickel",   "ALI=F"),
    ]
    _tape_html = ""
    for _name, _tk in _tape_items:
        try:
            import yfinance as _yf
            _h = _yf.Ticker(_tk).history(period="2d")
            if len(_h) >= 2:
                _p  = _h['Close'].iloc[-1]
                _pc = _h['Close'].iloc[-2]
                _chg = (_p - _pc) / _pc * 100
                _cls = "up" if _chg >= 0 else "dn"
                _arr = "&#9650;" if _chg >= 0 else "&#9660;"
                _tape_html += f'<span class="{_cls}">{_name} {_p:,.1f} {_arr}{abs(_chg):.2f}%</span><span class="sep">|</span>'
        except: pass
    if _tape_html:
        _tape_double = _tape_html * 2  
        st.markdown(f"""
        <div class="trm-ticker-wrap">
            <div class="trm-ticker-tape">{_tape_double}</div>
        </div>
        """, unsafe_allow_html=True)

    tab_macro, tab_rotation, tab_shareholder, tab_ai, tab_reco = st.tabs([
        "  GLOBAL MACRO & NEWS  ",
        "  INDEX & SECTOR ROTATION  ",
        "  SHAREHOLDER  ",
        "  AI STOCK INSIGHT  ",
        "  AI REKOMENDASI  ",
    ])

    with tab_macro:
        st.markdown("<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'>LIVE MARKET PULSE</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)
        
        @st.cache_data(ttl=300)
        def get_market_data(ticker_dict):
            data = {}
            for name, tk in ticker_dict.items():
                try: 
                    ticker = yf.Ticker(tk)
                    hist = ticker.history(period="5d") 
                    if len(hist) >= 2:
                        last = float(hist['Close'].iloc[-1])
                        prev = float(hist['Close'].iloc[-2])
                        pct = ((last - prev) / prev) * 100
                        data[name] = {"price": last, "pct": pct}
                    elif len(hist) == 1:
                        last = float(hist['Close'].iloc[-1])
                        data[name] = {"price": last, "pct": 0.0}
                    else:
                        data[name] = {"price": 0, "pct": 0}
                except Exception as e:
                    data[name] = {"price": 0, "pct": 0}
            return data

        indices_tickers = {
            "IHSG": "^JKSE","VIX": "^VIX", "S&P 500": "^GSPC", "Dow Jones": "^DJI",
            "Nasdaq": "^IXIC", "FTSE": "^FTSE", "Nikkei": "^N225",
            "Hang Seng": "^HSI", "Shanghai": "000001.SS",
        }
        
        commodities_tickers = {
            "USD/IDR": "IDR=X", "DXY": "DX-Y.NYB", "Gold (oz)": "GC=F", "WTI Crude": "CL=F",
            "Brent Crude": "BZ=F", "Newcastle Coal": "NCF=F", "Palm Oil": "MYP=F", "Nickel": "ALI=F"          
        }
        
        with st.spinner("Mendeteksi denyut pasar global..."):
            idx_data = get_market_data(indices_tickers)
            com_data = get_market_data(commodities_tickers)
        
        st.markdown("<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'>GLOBAL INDICES &amp; VOLATILITY</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)
        if idx_data:
            items_idx = list(idx_data.items())
            # Chunk into rows of 3 for mobile-friendly display
            chunk_size = 3
            for row_start in range(0, len(items_idx), chunk_size):
                row_items = items_idx[row_start:row_start+chunk_size]
                cols = st.columns(len(row_items))
                for j, (name, info) in enumerate(row_items):
                    with cols[j]:
                        st.metric(label=name, value=f"{info['price']:,.2f}", delta=f"{info['pct']:.2f}%")
        else:
            st.warning("&#9888; Gagal menarik data indeks.")

        st.markdown("<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'>COMMODITIES &amp; FOREX</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)
        if com_data:
            items_com = list(com_data.items())
            chunk_size = 4
            for row_start in range(0, len(items_com), chunk_size):
                row_items = items_com[row_start:row_start+chunk_size]
                cols = st.columns(len(row_items))
                for j, (name, info) in enumerate(row_items):
                    with cols[j]:
                        if name == "USD/IDR": price_str = f"Rp {info['price']:,.0f}"
                        elif info['price'] == 0: price_str = "N/A"
                        else: price_str = f"${info['price']:,.2f}"
                        delta_str = f"{info['pct']:.2f}%" if info['price'] != 0 else "0.00%"
                        st.metric(label=name, value=price_str, delta=delta_str)
        else:
            st.warning("&#9888; Gagal menarik data komoditas.")

        st.markdown("<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'> MAKRO INDONESIA vs US</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)
        st.markdown(f"<p style='font-family:IBM Plex Mono,monospace;font-size:0.7rem;letter-spacing:0.08em;color:{text_sub};margin-bottom:20px;text-transform:uppercase;'>Tren 12 Bulan Terakhir</p>", unsafe_allow_html=True)

        macro_col1, macro_col2 = st.columns(2)
        dates = pd.date_range(start="2025-04-01", end="2026-03-01", freq="MS")

        with macro_col1:
            st.markdown(f"<p style='font-family:IBM Plex Mono,monospace;font-size:0.72rem;letter-spacing:0.1em;color:#F5C242;font-weight:600;text-transform:uppercase;margin-bottom:8px;'>&#127470;&#127465; Makro Indonesia</p>", unsafe_allow_html=True)
            macro_id = pd.DataFrame({
                "BI Rate (%)": [6.00, 6.00, 6.00, 5.75, 5.75, 5.50, 5.25, 5.00, 4.75, 4.75, 4.75, 4.75],
                "Inflasi RI (%)": [2.50, 2.60, 2.70, 2.50, 2.40, 2.30, 2.56, 2.86, 2.61, 3.55, 4.76, 4.76],
                "Yield 10Y RI (%)": [6.90, 7.00, 7.10, 6.90, 6.80, 6.70, 6.60, 6.75, 6.80, 6.70, 6.60, 6.50]
            }, index=dates)
            st.line_chart(macro_id, color=["#F5C242", "#4285F4", "#ff5555"], height=320)

        with macro_col2:
            st.markdown(f"<p style='font-family:IBM Plex Mono,monospace;font-size:0.72rem;letter-spacing:0.1em;color:#F5C242;font-weight:600;text-transform:uppercase;margin-bottom:8px;'>&#127482;&#127480; Makro United States</p>", unsafe_allow_html=True)
            macro_us = pd.DataFrame({
                "Fed Rate (%)": [5.00, 5.00, 5.00, 5.00, 4.75, 4.50, 4.25, 4.00, 3.75, 3.75, 3.75, 3.75],
                "Inflasi US (%)": [3.40, 3.30, 3.00, 2.90, 2.50, 2.40, 2.60, 3.10, 2.90, 2.60, 2.40, 2.40],
                "Yield 10Y US (%)": [4.50, 4.40, 4.30, 4.10, 3.90, 3.80, 4.10, 4.30, 4.20, 4.10, 4.15, 4.20]
            }, index=dates)
            st.line_chart(macro_us, color=["#F5C242", "#4285F4", "#ff5555"], height=320)

        st.markdown(f"<div class='trm-insight'>&#128161; <b>SIGMA VIEW &mdash;</b> Suku bunga global sudah berada di tren pemangkasan. Namun, perhatikan lonjakan <b>Inflasi RI</b> belakangan ini yang membuat BI menunda pemangkasan lanjutan agar nilai tukar Rupiah tetap stabil.</div>", unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"""
            <div class="trm-card">
                <div class="trm-card-title">Fundamental &amp; The Real Macro</div>
                <p style='color:{text_main}; font-size: 0.88rem; line-height: 1.7; margin:0;'>
                <span style='color:#F5C242;font-weight:600;'>GDP &amp; PMI Manufaktur</span><br>
                Perekonomian ditopang konsumsi rumah tangga. PMI di atas 50 menandakan ekspansi pabrik.
                </p>
                <p style='color:{text_main}; font-size: 0.88rem; line-height: 1.7; margin:10px 0 0;'>
                <span style='color:#F5C242;font-weight:600;'>Cadangan Devisa &amp; Neraca Perdagangan</span><br>
                Bantalan krusial untuk intervensi Bank Indonesia dalam menahan gejolak Rupiah.
                </p>
            </div>
            """, unsafe_allow_html=True)

        with col2:
            st.markdown(f"""
            <div class="trm-card">
                <div class="trm-card-title" style="color:#f23645;">Rotasi &amp; Kurva Imbal Hasil</div>
                <p style='color:{text_main}; font-size: 0.88rem; line-height: 1.7; margin:0;'>
                <span style='color:#f23645;font-weight:600;'>Yield Curve Obligasi RI</span><br>
                Pemantauan inversi kurva sebagai indikator awal pelambatan ekonomi atau resesi.
                </p>
                <p style='color:{text_main}; font-size: 0.88rem; line-height: 1.7; margin:10px 0 0;'>
                <span style='color:#f23645;font-weight:600;'>Sektor Fokus</span><br>
                Komoditas memanas &rarr; Coal &amp; Gold. Suku bunga turun &rarr; Big Banks &amp; Properti.
                </p>
            </div>
            """, unsafe_allow_html=True)


        # ---------------------------------------------------------
        # LIVE MARKET PULSE & NEWS - FIX FINAL
        # ---------------------------------------------------------
        import feedparser

        # 1. DIVIDER & HEADER (Pagar Pembatas)
        st.markdown("<hr class='fancy-divider'>", unsafe_allow_html=True)
        st.markdown("<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'>LIVE MARKET PULSE & NEWS</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)

        # 2. CSS STYLING (Pastikan Box Rapi & Tidak Bocor)
        st.markdown(f"""
        <style>
        .news-card-sigma {{
            background: {met_bg};
            border: 1px solid {met_border};
            border-radius: 12px;
            height: 500px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            margin-bottom: 20px;
        }}
        .news-header-sigma {{
            padding: 12px 15px;
            background: rgba(245,194,66,0.1);
            border-bottom: 1px solid {met_border};
            color: #F5C242;
            font-family: 'IBM Plex Mono', monospace;
            font-weight: 700;
            font-size: 11px;
            letter-spacing: 1px;
        }}
        .news-scroll-sigma {{
            flex: 1;
            overflow-y: auto;
            padding: 10px;
        }}
        .news-entry-sigma {{
            display: block;
            padding: 12px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            text-decoration: none !important;
            transition: 0.2s ease;
        }}
        .news-entry-sigma:hover {{ background: rgba(245,194,66,0.05); }}
        .news-title-sigma {{
            color: {text_main};
            font-size: 13px;
            line-height: 1.5;
            margin-bottom: 5px;
        }}
        .news-meta-sigma {{
            color: {text_sub};
            font-size: 10px;
            font-family: 'IBM Plex Mono', monospace;
        }}
        @media (max-width: 768px) {{
            .news-card-sigma {{
                height: 360px !important;
            }}
            .news-title-sigma {{
                font-size: 12px !important;
            }}
        }}
        .news-scroll-sigma::-webkit-scrollbar {{ width: 4px; }}
        .news-scroll-sigma::-webkit-scrollbar-thumb {{ background: {met_border}; border-radius: 10px; }}
        </style>
        """, unsafe_allow_html=True)

        # 3. FUNGSI RENDER (PASTIKAN RETURN HANYA STRING HTML)
        # --- FUNGSI NEWS (PASTIKAN RETURN STRING HTML) ---
        def render_news_feed(url, tag_label):
            import feedparser
            try:
                feed = feedparser.parse(url)
                html_str = ""
                for entry in feed.entries[:10]:
                    date_str = entry.get('published', '')[:16]
                    # Kita susun jadi string HTML di sini agar tidak bocor coding
                    html_str += f"""
                    <a href='{entry.link}' target='_blank' style='text-decoration:none;'>
                        <div style='padding:10px; border-bottom:1px solid rgba(255,255,255,0.05);'>
                            <div style='color:{text_main}; font-size:13px; line-height:1.4;'>{entry.title}</div>
                            <div style='color:{text_sub}; font-size:10px; margin-top:4px;'>[{tag_label}] • {date_str}</div>
                        </div>
                    </a>"""
                return html_str if html_str else "No news found."
            except:
                return "Failed to load news."

        # RENDER BOX NEWS
        st.markdown("<hr class='fancy-divider'>", unsafe_allow_html=True)
        col_n1, col_n2 = st.columns(2)
        
        with col_n1:
            content_id = render_news_feed("https://www.cnbcindonesia.com/market/rss", "DOMESTIC")
            st.markdown(f"""
            <div class='news-box' style='background:{met_bg}; border:1px solid {met_border}; border-radius:10px; height:450px; overflow:hidden; display:flex; flex-direction:column;'>
                <div style='padding:10px; background:rgba(245,194,66,0.1); border-bottom:1px solid {met_border}; color:#F5C242; font-weight:bold; font-size:11px;'>🇮🇩 DOMESTIC NEWS</div>
                <div style='flex:1; overflow-y:auto;'>{content_id}</div>
            </div>""", unsafe_allow_html=True)

        with col_n2:
            content_glob = render_news_feed("https://www.cnbc.com/id/15839069/device/rss/rss.html", "GLOBAL")
            st.markdown(f"""
            <div class='news-box' style='background:{met_bg}; border:1px solid {met_border}; border-radius:10px; height:450px; overflow:hidden; display:flex; flex-direction:column;'>
                <div style='padding:10px; background:rgba(245,194,66,0.1); border-bottom:1px solid {met_border}; color:#F5C242; font-weight:bold; font-size:11px;'>🌎 GLOBAL NEWS</div>
                <div style='flex:1; overflow-y:auto;'>{content_glob}</div>
            </div>""", unsafe_allow_html=True)



        st.markdown("<hr class='fancy-divider'>", unsafe_allow_html=True)
        # ── ECONOMIC CALENDAR ─────────────────────────────────────
        st.markdown("<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'>ECONOMIC CALENDAR — ID · US · CN · JP</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)

        cal_bg      = met_bg
        cal_border  = met_border
        cal_text    = text_main
        cal_sub_clr = text_sub

        calendar_data = {
            "🇮🇩 INDONESIA": [
                {"tanggal": "07 Apr 2026", "event": "BI Rate Decision",           "forecast": "5.75%",   "prev": "5.75%",   "dampak": "HIGH",   "keterangan": "Keputusan suku bunga Bank Indonesia. Penting bagi sektor perbankan & properti."},
                {"tanggal": "15 Apr 2026", "event": "Inflasi CPI YoY",             "forecast": "2.9%",    "prev": "2.60%",   "dampak": "HIGH",   "keterangan": "Indeks Harga Konsumen tahunan. Data di atas ekspektasi bisa menunda pemangkasan BI Rate."},
                {"tanggal": "22 Apr 2026", "event": "Cadangan Devisa",             "forecast": "$155B",   "prev": "$154.5B", "dampak": "MEDIUM", "keterangan": "Cadangan devisa RI. Semakin tinggi = Rupiah makin terlindungi dari gejolak global."},
                {"tanggal": "05 Mei 2026", "event": "PMI Manufaktur",              "forecast": "51.2",    "prev": "51.0",    "dampak": "MEDIUM", "keterangan": "Di atas 50 = ekspansi industri. Berpengaruh ke sektor consumer & basic materials."},
                {"tanggal": "15 Mei 2026", "event": "GDP Q1 2026 (Flash)",         "forecast": "5.1%",    "prev": "5.02%",   "dampak": "HIGH",   "keterangan": "Pertumbuhan ekonomi kuartal 1. Angka lebih tinggi dari ekspektasi = bullish IHSG."},
                {"tanggal": "20 Mei 2026", "event": "Neraca Perdagangan Apr",      "forecast": "$3.2B",   "prev": "$2.8B",   "dampak": "MEDIUM", "keterangan": "Surplus perdagangan mendukung Rupiah dan capital inflow ke pasar saham."},
            ],
            "🇺🇸 UNITED STATES": [
                {"tanggal": "10 Apr 2026", "event": "CPI Inflasi YoY",             "forecast": "2.8%",    "prev": "2.82%",   "dampak": "HIGH",   "keterangan": "Data inflasi AS paling dinantikan. Jika turun → ekspektasi Fed cut meningkat → risk-on global."},
                {"tanggal": "17 Apr 2026", "event": "Retail Sales MoM",            "forecast": "+0.4%",   "prev": "+0.2%",   "dampak": "MEDIUM", "keterangan": "Kekuatan konsumsi AS. Data kuat = ekonomi solid = Fed lebih hawkish."},
                {"tanggal": "30 Apr 2026", "event": "FOMC Rate Decision",          "forecast": "4.25%",   "prev": "4.50%",   "dampak": "HIGH",   "keterangan": "Keputusan suku bunga Fed. Pemangkasan = dollar melemah = hot money masuk EM termasuk IDX."},
                {"tanggal": "01 Mei 2026", "event": "Non-Farm Payrolls Apr",       "forecast": "195K",    "prev": "228K",    "dampak": "HIGH",   "keterangan": "Data tenaga kerja utama AS. Angka di bawah ekspektasi → pasar antisipasi Fed cut lebih cepat."},
                {"tanggal": "15 Mei 2026", "event": "PPI Inflasi Produsen YoY",    "forecast": "2.5%",    "prev": "2.7%",    "dampak": "MEDIUM", "keterangan": "Leading indicator inflasi konsumen. Berpengaruh ke ekspektasi kebijakan Fed ke depan."},
                {"tanggal": "29 Mei 2026", "event": "GDP Q1 2026 (Revisi)",        "forecast": "2.3%",    "prev": "2.4%",    "dampak": "MEDIUM", "keterangan": "Revisi data GDP AS kuartal 1. Penting untuk proyeksi pertumbuhan global."},
            ],
            "🇨🇳 CHINA": [
                {"tanggal": "11 Apr 2026", "event": "CPI Inflasi YoY",             "forecast": "0.3%",    "prev": "0.1%",    "dampak": "HIGH",   "keterangan": "Deflasi China mengkhawatirkan pasar. Pemulihan CPI = sinyal demand domestik membaik."},
                {"tanggal": "16 Apr 2026", "event": "GDP Q1 2026",                 "forecast": "5.0%",    "prev": "5.0%",    "dampak": "HIGH",   "keterangan": "Target pemerintah 5%. Miss di bawah target = sentiment negatif ke komoditas & saham RI."},
                {"tanggal": "16 Apr 2026", "event": "Industrial Output YoY",       "forecast": "5.6%",    "prev": "5.9%",    "dampak": "MEDIUM", "keterangan": "Output industri China berpengaruh langsung ke harga komoditas: nikel, batu bara, CPO."},
                {"tanggal": "20 Apr 2026", "event": "PBoC Loan Prime Rate (LPR)",  "forecast": "3.10%",   "prev": "3.10%",   "dampak": "MEDIUM", "keterangan": "Suku bunga pinjaman China. Pemotongan LPR = stimulus ekonomi = demand komoditas naik."},
                {"tanggal": "01 Mei 2026", "event": "PMI Manufaktur Caixin",       "forecast": "51.0",    "prev": "50.8",    "dampak": "MEDIUM", "keterangan": "PMI sektor swasta China. Lebih sensitif ke ekspor. Pengaruh besar ke saham komoditas RI."},
                {"tanggal": "20 Mei 2026", "event": "Foreign Direct Investment",   "forecast": "-8.5%",   "prev": "-10.8%",  "dampak": "LOW",    "keterangan": "Investasi asing langsung ke China. Tren perbaikan = confidence investor global ke Asia EM."},
            ],
            "🇯🇵 JAPAN": [
                {"tanggal": "09 Apr 2026", "event": "BoJ Rate Decision",           "forecast": "0.50%",   "prev": "0.50%",   "dampak": "HIGH",   "keterangan": "Bank of Japan. Kenaikan rate = Yen menguat = unwinding carry trade = tekanan ke aset EM."},
                {"tanggal": "11 Apr 2026", "event": "PPI Inflasi Produsen YoY",    "forecast": "3.5%",    "prev": "4.0%",    "dampak": "MEDIUM", "keterangan": "Leading indicator inflasi Jepang. Berpengaruh ke ekspektasi BoJ hike selanjutnya."},
                {"tanggal": "18 Apr 2026", "event": "CPI Core Inflasi YoY",        "forecast": "3.0%",    "prev": "3.0%",    "dampak": "HIGH",   "keterangan": "Inflasi inti Jepang. Terus tinggi = BoJ makin hawkish = Yen carry trade terancam."},
                {"tanggal": "30 Apr 2026", "event": "Industrial Production MoM",   "forecast": "+0.3%",   "prev": "-1.1%",   "dampak": "MEDIUM", "keterangan": "Output industri Jepang. Pemulihan = demand bahan baku Asia meningkat."},
                {"tanggal": "16 Mei 2026", "event": "GDP Q1 2026 (Flash)",         "forecast": "+0.3%",   "prev": "-0.1%",   "dampak": "HIGH",   "keterangan": "GDP Jepang. Resesi teknis (2 kuartal negatif) = BoJ lebih hati-hati naikkan bunga."},
                {"tanggal": "23 Mei 2026", "event": "PMI Manufaktur Flash",        "forecast": "49.5",    "prev": "48.7",    "dampak": "MEDIUM", "keterangan": "PMI flash Jepang. Masih di bawah 50 = kontraksi industri. Berpengaruh ke Nikkei & Yen."},
            ],
        }

        dampak_color = {"HIGH": "#f23645", "MEDIUM": "#F5C242", "LOW": "#4285F4"}
        dampak_bg    = {"HIGH": "rgba(242,54,69,0.12)", "MEDIUM": "rgba(245,194,66,0.10)", "LOW": "rgba(66,133,244,0.10)"}

        # CSS kalender — satu kali saja di luar loop
        st.markdown(f"""<style>
        .cal-wrap {{ background:{cal_bg}; border:1px solid {cal_border}; border-radius:12px;
            overflow:hidden; margin-bottom:20px; font-family:'IBM Plex Mono',monospace; }}
        .cal-hdr {{ padding:10px 16px; background:rgba(245,194,66,0.09);
            border-bottom:1px solid {cal_border}; font-size:0.72rem; font-weight:700;
            letter-spacing:0.12em; color:#F5C242; text-transform:uppercase; }}
        .cal-row {{ display:grid; grid-template-columns:92px 1fr 120px 56px;
            align-items:center; gap:8px; padding:9px 16px;
            border-bottom:1px solid {cal_border}; cursor:default;
            position:relative; transition:background 0.15s; }}
        .cal-row:last-child {{ border-bottom:none; }}
        .cal-row:hover {{ background:rgba(245,194,66,0.07); }}
        .cal-dt {{ font-size:0.65rem; color:{cal_sub_clr}; white-space:nowrap; }}
        .cal-ev {{ font-size:0.73rem; color:{cal_text}; font-weight:500; }}
        .cal-nums {{ display:flex; flex-direction:column; gap:2px; text-align:right; }}
        .cal-fc {{ font-size:0.71rem; color:#089981; font-weight:600; }}
        .cal-pv {{ font-size:0.62rem; color:{cal_sub_clr}; }}
        .cal-bdg {{ font-size:0.59rem; font-weight:700; letter-spacing:0.07em;
            padding:2px 5px; border-radius:4px; text-align:center; white-space:nowrap; }}
        .cal-tip {{ display:none; position:absolute; left:0; right:0;
            top:calc(100% + 4px); z-index:9999;
            background:{'#1a2035' if is_dark else '#ffffff'};
            border:1px solid {cal_border}; border-left:3px solid #F5C242;
            border-radius:0 6px 6px 0; padding:8px 12px;
            font-size:0.69rem; color:{cal_text}; line-height:1.5;
            pointer-events:none; box-shadow:0 6px 24px rgba(0,0,0,0.4); }}
        .cal-row:hover .cal-tip {{ display:block; }}
        @media (max-width: 768px) {{
            .cal-row {{
                grid-template-columns: 72px 1fr 82px 40px !important;
                gap: 4px !important;
                padding: 8px 10px !important;
            }}
            .cal-dt {{ font-size: 0.58rem !important; white-space: normal !important; line-height: 1.3 !important; }}
            .cal-ev {{ font-size: 0.64rem !important; line-height: 1.3 !important; }}
            .cal-fc {{ font-size: 0.62rem !important; }}
            .cal-pv {{ font-size: 0.55rem !important; }}
            .cal-bdg {{ font-size: 0.52rem !important; padding: 2px 3px !important; }}
            .cal-hdr {{ font-size: 0.65rem !important; padding: 8px 10px !important; letter-spacing: 0.08em !important; }}
        }}
        </style>""", unsafe_allow_html=True)

        # On mobile: use 1 column; on desktop: 2 columns
        is_mobile_cal = True  # Streamlit renders same width — we use CSS trick
        cal_cols = st.columns(2)
        country_list = list(calendar_data.items())

        for ci, (country, events) in enumerate(country_list):
            col_idx = ci % 2
            with cal_cols[col_idx]:
                rows_html = ""
                for ev in events:
                    dk    = ev["dampak"]
                    d_clr = dampak_color.get(dk, "#b2b5be")
                    d_bg  = dampak_bg.get(dk, "rgba(178,181,190,0.08)")
                    tip   = ev["keterangan"].replace("'", "&#39;").replace('"', "&quot;")
                    rows_html += (
                        f"<div class='cal-row'>"
                        f"<div class='cal-dt'>{ev['tanggal']}</div>"
                        f"<div class='cal-ev'>{ev['event']}</div>"
                        f"<div class='cal-nums'>"
                        f"<span class='cal-fc'>&#9654; {ev['forecast']}</span>"
                        f"<span class='cal-pv'>Prev: {ev['prev']}</span>"
                        f"</div>"
                        f"<div class='cal-bdg' style='background:{d_bg};color:{d_clr};border:1px solid {d_clr};'>{'MED' if dk == 'MEDIUM' else dk}</div>"
                        f"<div class='cal-tip'>{tip}</div>"
                        f"</div>"
                    )
                st.markdown(
                    f"<div class='cal-wrap'>"
                    f"<div class='cal-hdr'>{country} — Apr–Mei 2026</div>"
                    f"{rows_html}"
                    f"</div>",
                    unsafe_allow_html=True
                )

    # ── TAB: INDEX & SECTOR ROTATION ──────────────────────────────────
    with tab_rotation:

        def highlight_status(val):
            if val == 'NEW ENTRY': return 'background-color: rgba(46, 204, 113, 0.2); color: #2ecc71; font-weight: bold;'
            elif val == 'DOWNGRADED': return 'background-color: rgba(241, 196, 15, 0.2); color: #f1c40f;'
            elif 'OUT' in str(val): return 'background-color: rgba(231, 76, 60, 0.2); color: #e74c3c;'
            return ''
            
        def safe_style(df_style, func, subset):
            if hasattr(df_style, 'map'):
                return df_style.map(func, subset=subset)
            return df_style.applymap(func, subset=subset)

        st.markdown("<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'>SECTOR ROTATION &mdash; RRG CONCEPT</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)
        
        rotation_data = {
            "Sektor Utama": ["Energy (BREN, ADRO)", "Basic Materials (PTRO, TPIA)", "Finance (BBCA, BBRI)", "Infrastructure (TLKM, RAJA)", "Consumer (INDF, MYOR)"],
            "Fase Saat Ini": ["Leading", "Improving", "Weakening", "Lagging", "Lagging"],
            "Aksi Institusi": ["Hold / Profit Run", "Accumulation", "Distribution / Wait", "Avoid", "Avoid"]
        }
        st.dataframe(pd.DataFrame(rotation_data), use_container_width=True, hide_index=True)
        
        st.markdown(f"<div class='trm-insight'>&#127919; <b>SIGMA INSIGHT &mdash;</b> Dana asing (Big Money) saat ini merotasi portofolio dari perbankan (<i>Weakening</i>) menuju sektor energi dan material dasar (<i>Improving/Leading</i>). Pantau ketat emiten yang berada di fase Improving.</div>", unsafe_allow_html=True)

        st.markdown("<hr class='fancy-divider'>", unsafe_allow_html=True)

        st.markdown("<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'>MSCI INDONESIA INDEX TRACKER</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)
        st.markdown(f"""<div style='font-family:IBM Plex Mono,monospace;font-size:0.70rem;color:{text_sub};
            background:rgba(245,194,66,0.07);border-left:3px solid #F5C242;
            padding:8px 14px;margin-bottom:12px;border-radius:0 4px 4px 0;line-height:1.8;'>
        🗓️ <b style='color:#F5C242;'>Efektif sejak:</b> 28 Februari 2025 (MSCI Semi-Annual Review Feb 2025)&nbsp;&nbsp;|&nbsp;&nbsp;
        <b style='color:#F5C242;'>Review berikutnya:</b> Agustus 2025 (pengumuman ~13 Agu, efektif 29 Agu 2025)&nbsp;&nbsp;|&nbsp;&nbsp;
        <span style='color:{text_sub};'>Jadwal: 2× setahun — Februari &amp; Agustus. Sumber: <b>msci.com</b></span>
        </div>""", unsafe_allow_html=True)
        msci_data = {
            "Ticker": [
                "AMMN", "ASII", "BBCA", "BBNI", "BBRI", "BMRI", "BREN", "BRPT", "CPIN", "GOTO", 
                "ICBP", "INDF", "INKP", "INTP", "ISAT", "KLBF", "MDKA", "TPIA", "TLKM", "TOWR", 
                "UNTR", "UNVR",
                "ADRO", "BRMS", "BSDE", "CTRA", "MBMA", "MYOR", "PTRO", "RAJA", "ACES", "CLEO"
            ],
            "Kategori": [
                "Standard", "Standard", "Standard", "Standard", "Standard", "Standard", "Standard", "Standard", "Standard", "Standard",
                "Standard", "Standard", "Standard", "Standard", "Standard", "Standard", "Standard", "Standard", "Standard", "Standard",
                "Standard", "Standard",
                "Small Cap", "Small Cap", "Small Cap", "Small Cap", "Small Cap", "Small Cap", "Small Cap", "Small Cap", "Excluded", "Excluded"
            ],
            "Status": [
                "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing (Top 10)", "Existing", "Existing", "Existing",
                "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing",
                "Existing", "Existing",
                "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "NEW ENTRY", "Existing", "OUT", "OUT"
            ],
            "Sektor": [
                "Materials", "Industrials", "Finance", "Finance", "Finance", "Finance", "Energy", "Materials", "Consumer", "Technology",
                "Consumer", "Consumer", "Materials", "Materials", "Infrastructures", "Healthcare", "Materials", "Materials", "Infrastructures", "Infrastructures",
                "Industrials", "Consumer",
                "Energy", "Materials", "Properties", "Properties", "Materials", "Consumer", "Infrastructures", "Energy", "Retail", "Consumer"
            ]
        }
        df_msci = pd.DataFrame(msci_data)
        
        st.markdown("<p style='font-family:IBM Plex Mono,monospace;font-size:0.72rem;letter-spacing:0.1em;text-transform:uppercase;color:#F5C242;margin:12px 0 8px;font-weight:600;'>01 / MSCI Standard Index &mdash; The Giants</p>", unsafe_allow_html=True)
        st.dataframe(safe_style(df_msci[df_msci['Kategori'] == 'Standard'].drop(columns=['Kategori']).style, highlight_status, ['Status']), use_container_width=True, hide_index=True)

        st.markdown("<p style='font-family:IBM Plex Mono,monospace;font-size:0.72rem;letter-spacing:0.1em;text-transform:uppercase;color:#F5C242;margin:20px 0 8px;font-weight:600;'>02 / MSCI Small Cap Index &mdash; The Mid-Caps</p>", unsafe_allow_html=True)
        st.dataframe(safe_style(df_msci[df_msci['Kategori'] == 'Small Cap'].drop(columns=['Kategori']).style, highlight_status, ['Status']), use_container_width=True, hide_index=True)

        st.markdown("<p style='font-family:IBM Plex Mono,monospace;font-size:0.72rem;letter-spacing:0.1em;text-transform:uppercase;color:#f23645;margin:20px 0 8px;font-weight:600;'>03 / Excluded &mdash; Keluar dari Indeks</p>", unsafe_allow_html=True)
        st.dataframe(safe_style(df_msci[df_msci['Kategori'] == 'Excluded'].drop(columns=['Kategori']).style, highlight_status, ['Status']), use_container_width=True, hide_index=True)

        st.markdown("<hr class='fancy-divider'>", unsafe_allow_html=True)

        st.markdown("<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'>FTSE GLOBAL EQUITY INDEX &mdash; INDONESIA</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)
        st.markdown(f"""<div style='font-family:IBM Plex Mono,monospace;font-size:0.70rem;color:{text_sub};
            background:rgba(245,194,66,0.07);border-left:3px solid #F5C242;
            padding:8px 14px;margin-bottom:12px;border-radius:0 4px 4px 0;line-height:1.8;'>
        🗓️ <b style='color:#F5C242;'>Efektif sejak:</b> 24 Maret 2025 (FTSE Quarterly Review Q1 2025)&nbsp;&nbsp;|&nbsp;&nbsp;
        <b style='color:#F5C242;'>Review berikutnya:</b> Juni 2025 (pengumuman ~6 Jun, efektif 23 Jun 2025)&nbsp;&nbsp;|&nbsp;&nbsp;
        <span style='color:{text_sub};'>Jadwal: 4× setahun — Mar/Jun/Sep/Des. Sumber: <b>ftserussell.com</b></span>
        </div>""", unsafe_allow_html=True)
        
        ftse_data = {
            "Ticker": [
                "AMMN", "ASII", "BBCA", "BBNI", "BBRI", "BMRI", "BREN", "BRPT", "CPIN", "GOTO", "ICBP", "INDF", "KLBF", "MDKA", "TLKM", "UNTR",
                "ADRO", "AKRA", "BRIS", "INKP", "PGAS",
                "PTRO", "CUAN", "VKTR", "RAJA"
            ],
            "Kategori": [
                "Large Cap", "Large Cap", "Large Cap", "Large Cap", "Large Cap", "Large Cap", "Large Cap", "Large Cap", "Large Cap", "Large Cap", "Large Cap", "Large Cap", "Large Cap", "Large Cap", "Large Cap", "Large Cap",
                "Mid Cap", "Mid Cap", "Mid Cap", "Mid Cap", "Mid Cap",
                "Small Cap", "Small Cap", "Small Cap", "Small Cap"
            ],
            "Status": [
                "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "DOWNGRADED", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing",
                "Existing", "Existing", "Existing", "Existing", "Existing",
                "NEW ENTRY", "NEW ENTRY", "Existing", "Existing"
            ],
            "Sektor": [
                "Materials", "Industrials", "Finance", "Finance", "Finance", "Finance", "Energy", "Materials", "Consumer", "Technology", "Consumer", "Consumer", "Healthcare", "Materials", "Infrastructures", "Industrials",
                "Energy", "Energy", "Finance", "Materials", "Energy",
                "Infrastructures", "Energy", "Industrials", "Energy"
            ]
        }
        df_ftse = pd.DataFrame(ftse_data)

        st.markdown("<p style='font-family:IBM Plex Mono,monospace;font-size:0.72rem;letter-spacing:0.1em;text-transform:uppercase;color:#F5C242;margin:12px 0 8px;font-weight:600;'>01 / Large &amp; Mid Cap</p>", unsafe_allow_html=True)
        st.dataframe(safe_style(df_ftse[df_ftse['Kategori'].isin(['Large Cap', 'Mid Cap'])].style, highlight_status, ['Status']), use_container_width=True, hide_index=True)

        st.markdown("<p style='font-family:IBM Plex Mono,monospace;font-size:0.72rem;letter-spacing:0.1em;text-transform:uppercase;color:#F5C242;margin:20px 0 8px;font-weight:600;'>02 / Small Cap</p>", unsafe_allow_html=True)
        st.dataframe(safe_style(df_ftse[df_ftse['Kategori'] == 'Small Cap'].style, highlight_status, ['Status']), use_container_width=True, hide_index=True)

        st.markdown("<hr class='fancy-divider'>", unsafe_allow_html=True)

        st.markdown("<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'>LQ45 INDEX &mdash; 45 SAHAM AKTIF</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)
        st.markdown(f"""<div style='font-family:IBM Plex Mono,monospace;font-size:0.70rem;color:{text_sub};
            background:rgba(245,194,66,0.07);border-left:3px solid #F5C242;
            padding:8px 14px;margin-bottom:12px;border-radius:0 4px 4px 0;line-height:1.8;'>
        🗓️ <b style='color:#F5C242;'>Efektif sejak:</b> 03 Februari 2025 (Periode Feb–Jul 2025)&nbsp;&nbsp;|&nbsp;&nbsp;
        <b style='color:#F5C242;'>Rebalance berikutnya:</b> 01 Agustus 2025 (Periode Agu 2025–Jan 2026)&nbsp;&nbsp;|&nbsp;&nbsp;
        <span style='color:{text_sub};'>Jadwal: 2× setahun — Februari &amp; Agustus. Sumber: <b>idx.co.id</b></span>
        </div>""", unsafe_allow_html=True)
        
        lq45_data = {
            "Ticker": [
                "ACES", "ADRO", "AKRA", "AMMN", "AMRT", "ANTM", "ARTO", "ASII", "BBCA", "BBNI", 
                "BBRI", "BBTN", "BFIN", "BMRI", "BRIS", "BRPT", "BUKA", "CPIN", "CTRA", "ESSA", 
                "EXCL", "GOTO", "HRUM", "ICBP", "INCO", "INDF", "INKP", "INTP", "ISAT", "ITMG", 
                "KLBF", "MAPI", "MBMA", "MDKA", "MEDC", "MTEL", "PGAS", "PGEO", "PTBA", "PTPP", 
                "SIDO", "SMGR", "TLKM", "TOWR", "UNTR",
                "EMTK", "SCMA", "SRTG"
            ],
            "Kategori": [
                "Active", "Active", "Active", "Active", "Active", "Active", "Active", "Active", "Active", "Active", 
                "Active", "Active", "Active", "Active", "Active", "Active", "Active", "Active", "Active", "Active", 
                "Active", "Active", "Active", "Active", "Active", "Active", "Active", "Active", "Active", "Active", 
                "Active", "Active", "Active", "Active", "Active", "Active", "Active", "Active", "Active", "Active", 
                "Active", "Active", "Active", "Active", "Active",
                "Excluded", "Excluded", "Excluded"
            ],
            "Status": [
                "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", 
                "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", 
                "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", 
                "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", "Existing", 
                "Existing", "Existing", "Existing", "Existing", "Existing",
                "OUT", "OUT", "OUT"
            ],
            "Sektor": [
                "Cyclical", "Energy", "Energy", "Materials", "Consumer", "Materials", "Finance", "Industrials", "Finance", "Finance",
                "Finance", "Finance", "Finance", "Finance", "Finance", "Materials", "Technology", "Consumer", "Properties", "Materials",
                "Infrastructures", "Technology", "Energy", "Consumer", "Materials", "Consumer", "Materials", "Materials", "Infrastructures", "Energy",
                "Healthcare", "Cyclical", "Materials", "Materials", "Energy", "Infrastructures", "Energy", "Energy", "Energy", "Infrastructures",
                "Healthcare", "Materials", "Infrastructures", "Infrastructures", "Industrials",
                "Technology", "Consumer", "Financials"
            ]
        }
        df_lq45 = pd.DataFrame(lq45_data)

        st.markdown("<p style='font-family:IBM Plex Mono,monospace;font-size:0.72rem;letter-spacing:0.1em;text-transform:uppercase;color:#F5C242;margin:12px 0 8px;font-weight:600;'>01 / Daftar 45 Saham Aktif</p>", unsafe_allow_html=True)
        st.dataframe(safe_style(df_lq45[df_lq45['Kategori'] == 'Active'].drop(columns=['Kategori']).style, highlight_status, ['Status']), use_container_width=True, hide_index=True)

        st.markdown("<p style='font-family:IBM Plex Mono,monospace;font-size:0.72rem;letter-spacing:0.1em;text-transform:uppercase;color:#f23645;margin:20px 0 8px;font-weight:600;'>02 / Didepak dari LQ45</p>", unsafe_allow_html=True)
        st.dataframe(safe_style(df_lq45[df_lq45['Kategori'] == 'Excluded'].drop(columns=['Kategori']).style, highlight_status, ['Status']), use_container_width=True, hide_index=True)

        st.markdown("<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'>PETA KONGLOMERASI INDONESIA</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)
        st.markdown(f"<p style='font-family:IBM Plex Mono,monospace;font-size:0.7rem;letter-spacing:0.08em;color:{text_sub};margin-bottom:20px;text-transform:uppercase;'>Database emiten yang terafiliasi dengan grup konglomerasi raksasa penggerak IHSG</p>", unsafe_allow_html=True)
        
        conglo_data = [
            {"Grup": "Barito (Prajogo P.)", "Ticker": "BRPT", "Nama": "Barito Pacific", "Fokus Bisnis": "Holding Energi & Kimia"},
            {"Grup": "Barito (Prajogo P.)", "Ticker": "TPIA", "Nama": "Chandra Asri Pacific", "Fokus Bisnis": "Petrokimia"},
            {"Grup": "Barito (Prajogo P.)", "Ticker": "BREN", "Nama": "Barito Renewables", "Fokus Bisnis": "Panas Bumi (Geothermal)"},
            {"Grup": "Barito (Prajogo P.)", "Ticker": "CUAN", "Nama": "Petrindo Jaya Kreasi", "Fokus Bisnis": "Tambang Mineral"},
            {"Grup": "Barito (Prajogo P.)", "Ticker": "PTRO", "Nama": "Petrosea", "Fokus Bisnis": "Kontraktor Tambang"},
            {"Grup": "Barito (Prajogo P.)", "Ticker": "CDIA", "Nama": "Chandra Daya Investasi", "Fokus Bisnis": "Infrastruktur & Utilitas"},
            
            {"Grup": "Djarum (Budi & Michael H.)", "Ticker": "BBCA", "Nama": "Bank Central Asia", "Fokus Bisnis": "Perbankan"},
            {"Grup": "Djarum (Budi & Michael H.)", "Ticker": "TOWR", "Nama": "Sarana Menara Nusantara", "Fokus Bisnis": "Menara Telekomunikasi"},
            {"Grup": "Djarum (Budi & Michael H.)", "Ticker": "SUPR", "Nama": "Solusi Tunas Pratama", "Fokus Bisnis": "Menara Telekomunikasi"},
            {"Grup": "Djarum (Budi & Michael H.)", "Ticker": "BELI", "Nama": "Global Digital Niaga", "Fokus Bisnis": "E-Commerce (Blibli)"},
            
            {"Grup": "Salim (Anthoni S.)", "Ticker": "INDF", "Nama": "Indofood Sukses Makmur", "Fokus Bisnis": "Consumer Goods"},
            {"Grup": "Salim (Anthoni S.)", "Ticker": "ICBP", "Nama": "Indofood CBP", "Fokus Bisnis": "Consumer Goods"},
            {"Grup": "Salim (Anthoni S.)", "Ticker": "LSIP", "Nama": "PP London Sumatra", "Fokus Bisnis": "Perkebunan"},
            {"Grup": "Salim (Anthoni S.)", "Ticker": "SIMP", "Nama": "Salim Ivomas Pratama", "Fokus Bisnis": "Perkebunan"},
            {"Grup": "Salim (Anthoni S.)", "Ticker": "AMMN", "Nama": "Amman Mineral", "Fokus Bisnis": "Tambang Emas & Tembaga"},
            {"Grup": "Salim (Anthoni S.)", "Ticker": "DNET", "Nama": "Indoritel Makmur", "Fokus Bisnis": "Ritel (Indomaret)"},
            
            {"Grup": "Astra (Jardine Matheson)", "Ticker": "ASII", "Nama": "Astra International", "Fokus Bisnis": "Holding Otomotif"},
            {"Grup": "Astra (Jardine Matheson)", "Ticker": "UNTR", "Nama": "United Tractors", "Fokus Bisnis": "Alat Berat & Tambang"},
            {"Grup": "Astra (Jardine Matheson)", "Ticker": "AALI", "Nama": "Astra Agro Lestari", "Fokus Bisnis": "Kelapa Sawit"},
            {"Grup": "Astra (Jardine Matheson)", "Ticker": "AUTO", "Nama": "Astra Otoparts", "Fokus Bisnis": "Komponen Otomotif"},
            
            {"Grup": "Sinar Mas (Eka Tjipta W.)", "Ticker": "INKP", "Nama": "Indah Kiat Pulp & Paper", "Fokus Bisnis": "Pulp & Paper"},
            {"Grup": "Sinar Mas (Eka Tjipta W.)", "Ticker": "TKIM", "Nama": "Tjiwi Kimia", "Fokus Bisnis": "Pulp & Paper"},
            {"Grup": "Sinar Mas (Eka Tjipta W.)", "Ticker": "BSDE", "Nama": "Bumi Serpong Damai", "Fokus Bisnis": "Properti"},
            {"Grup": "Sinar Mas (Eka Tjipta W.)", "Ticker": "SMAR", "Nama": "Sinar Mas Agro", "Fokus Bisnis": "Agribisnis"},
            {"Grup": "Sinar Mas (Eka Tjipta W.)", "Ticker": "DSSA", "Nama": "Dian Swastatika", "Fokus Bisnis": "Energi"},
            
            {"Grup": "Bakrie (Aburizal B.)", "Ticker": "BUMI", "Nama": "Bumi Resources", "Fokus Bisnis": "Batu Bara"},
            {"Grup": "Bakrie (Aburizal B.)", "Ticker": "BRMS", "Nama": "Bumi Resources Minerals", "Fokus Bisnis": "Tambang Emas"},
            {"Grup": "Bakrie (Aburizal B.)", "Ticker": "ENRG", "Nama": "Energi Mega Persada", "Fokus Bisnis": "Migas"},
            {"Grup": "Bakrie (Aburizal B.)", "Ticker": "VKTR", "Nama": "VKTR Teknologi", "Fokus Bisnis": "Kendaraan Listrik"},
            
            {"Grup": "Adaro (Boy Thohir)", "Ticker": "ADRO", "Nama": "Adaro Energy", "Fokus Bisnis": "Batu Bara"},
            {"Grup": "Adaro (Boy Thohir)", "Ticker": "ADMR", "Nama": "Adaro Minerals", "Fokus Bisnis": "Batu Bara Metalurgi"},
            {"Grup": "Adaro (Boy Thohir)", "Ticker": "MBMA", "Nama": "Merdeka Battery", "Fokus Bisnis": "Nikel & Baterai"},
            {"Grup": "Adaro (Boy Thohir)", "Ticker": "ESSA", "Nama": "ESSA Industries", "Fokus Bisnis": "Amonia & LPG"},
            
            {"Grup": "MNC (Hary Tanoe)", "Ticker": "BHIT", "Nama": "MNC Asia Holding", "Fokus Bisnis": "Holding"},
            {"Grup": "MNC (Hary Tanoe)", "Ticker": "MNCN", "Nama": "Media Nusantara Citra", "Fokus Bisnis": "Media Televisi"},
            {"Grup": "MNC (Hary Tanoe)", "Ticker": "KPIG", "Nama": "MNC Land", "Fokus Bisnis": "Properti"},
            
            {"Grup": "Lippo (Mochtar Riady)", "Ticker": "LPKR", "Nama": "Lippo Karawaci", "Fokus Bisnis": "Properti"},
            {"Grup": "Lippo (Mochtar Riady)", "Ticker": "SILO", "Nama": "Siloam Hospitals", "Fokus Bisnis": "Kesehatan"},
            {"Grup": "Lippo (Mochtar Riady)", "Ticker": "MPPA", "Nama": "Matahari Putra Prima", "Fokus Bisnis": "Ritel"},
            
            {"Grup": "CT Corp (Chairul T.)", "Ticker": "MEGA", "Nama": "Bank Mega", "Fokus Bisnis": "Perbankan"},
            {"Grup": "CT Corp (Chairul T.)", "Ticker": "BBHI", "Nama": "Allo Bank", "Fokus Bisnis": "Bank Digital"}
        ]
        df_conglo = pd.DataFrame(conglo_data)
        
        grup_list = ["Semua Grup"] + list(df_conglo["Grup"].unique())
        selected_grup = st.selectbox("Pilih Grup Konglomerasi:", grup_list)
        
        if selected_grup != "Semua Grup":
            df_display = df_conglo[df_conglo["Grup"] == selected_grup]
        else:
            df_display = df_conglo
            
        st.dataframe(df_display, use_container_width=True, hide_index=True)
        
        st.markdown(f"""
        <div class="trm-card" style="margin-top: 16px;">
            <div class="trm-card-title">SIGMA INSIGHT &mdash; The Power of Conglomerates</div>
            <p style='color:{text_main}; font-size: 0.88rem; line-height: 1.7; margin:0;'>
            Di IHSG, sentimen yang terjadi pada <i>holding company</i> seringkali menjalar dengan cepat ke anak-anak usahanya.
            </p>
            <p style='color:{text_sub}; font-size: 0.85rem; line-height: 1.7; margin:10px 0 0;'>
            <span style='color:#F5C242;font-weight:600;'>Tips Trading:</span> Pantau <i>Leader</i> dari masing-masing grup. Jika sang <i>Leader</i> mulai <i>breakout</i>, saham <i>Laggard</i> (yang tertinggal) di grup tersebut bisa menjadi peluang <i>entry</i> yang profitabel.
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("<hr class='fancy-divider'>", unsafe_allow_html=True)



    # ── TAB: SHAREHOLDER ──────────────────────────────────────────────
    with tab_shareholder:
        st.markdown("<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'>SHAREHOLDER SCREENING</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)
        st.markdown(f"<p style='font-family:IBM Plex Mono,monospace;font-size:0.68rem;letter-spacing:0.06em;color:{text_sub};margin-bottom:14px;text-transform:uppercase;'>Deteksi akumulasi &amp; distribusi retail &middot; Naik/Turun 1 bulan &amp; 3 bulan berturut-turut &middot; Data IDX</p>", unsafe_allow_html=True)

        import datetime as _dt
        import pandas as pd

        # ── Definisikan DB di scope luar agar bisa dipakai dua kali ──────
        def get_manual_sh_db_outer():
            return {
                "BBCA": [
                    {"date": _dt.datetime(2025, 4, 30),  "shareholders": 320100},
                    {"date": _dt.datetime(2025, 5, 31),  "shareholders": 322500},
                    {"date": _dt.datetime(2025, 6, 30),  "shareholders": 321800},
                    {"date": _dt.datetime(2025, 7, 31),  "shareholders": 325400},
                    {"date": _dt.datetime(2025, 8, 31),  "shareholders": 328900},
                    {"date": _dt.datetime(2025, 9, 30),  "shareholders": 331200},
                    {"date": _dt.datetime(2025, 10, 31), "shareholders": 335500},
                    {"date": _dt.datetime(2025, 11, 30), "shareholders": 338100},
                    {"date": _dt.datetime(2025, 12, 31), "shareholders": 340200},
                    {"date": _dt.datetime(2026, 1, 31),  "shareholders": 345600},
                    {"date": _dt.datetime(2026, 2, 28),  "shareholders": 348200},
                    {"date": _dt.datetime(2026, 3, 31),  "shareholders": 351400},
                ],
                "BBRI": [
                    {"date": _dt.datetime(2025, 4, 30),  "shareholders": 930500},
                    {"date": _dt.datetime(2025, 5, 31),  "shareholders": 938200},
                    {"date": _dt.datetime(2025, 6, 30),  "shareholders": 948300},
                    {"date": _dt.datetime(2025, 7, 31),  "shareholders": 955100},
                    {"date": _dt.datetime(2025, 8, 31),  "shareholders": 962400},
                    {"date": _dt.datetime(2025, 9, 30),  "shareholders": 972100},
                    {"date": _dt.datetime(2025, 10, 31), "shareholders": 980500},
                    {"date": _dt.datetime(2025, 11, 30), "shareholders": 985200},
                    {"date": _dt.datetime(2025, 12, 31), "shareholders": 988500},
                    {"date": _dt.datetime(2026, 1, 31),  "shareholders": 995200},
                    {"date": _dt.datetime(2026, 2, 28),  "shareholders": 1002400},
                    {"date": _dt.datetime(2026, 3, 31),  "shareholders": 1015800},
                ],
                "BMRI": [
                    {"date": _dt.datetime(2025, 4, 30),  "shareholders": 489200},
                    {"date": _dt.datetime(2025, 5, 31),  "shareholders": 494500},
                    {"date": _dt.datetime(2025, 6, 30),  "shareholders": 498600},
                    {"date": _dt.datetime(2025, 7, 31),  "shareholders": 505400},
                    {"date": _dt.datetime(2025, 8, 31),  "shareholders": 509800},
                    {"date": _dt.datetime(2025, 9, 30),  "shareholders": 512300},
                    {"date": _dt.datetime(2025, 10, 31), "shareholders": 518700},
                    {"date": _dt.datetime(2025, 11, 30), "shareholders": 521400},
                    {"date": _dt.datetime(2025, 12, 31), "shareholders": 523700},
                    {"date": _dt.datetime(2026, 1, 31),  "shareholders": 528400},
                    {"date": _dt.datetime(2026, 2, 28),  "shareholders": 531200},
                    {"date": _dt.datetime(2026, 3, 31),  "shareholders": 535600},
                ],
                "TLKM": [
                    {"date": _dt.datetime(2025, 4, 30),  "shareholders": 365200},
                    {"date": _dt.datetime(2025, 5, 31),  "shareholders": 362100},
                    {"date": _dt.datetime(2025, 6, 30),  "shareholders": 358900},
                    {"date": _dt.datetime(2025, 7, 31),  "shareholders": 352400},
                    {"date": _dt.datetime(2025, 8, 31),  "shareholders": 348500},
                    {"date": _dt.datetime(2025, 9, 30),  "shareholders": 344200},
                    {"date": _dt.datetime(2025, 10, 31), "shareholders": 339800},
                    {"date": _dt.datetime(2025, 11, 30), "shareholders": 335400},
                    {"date": _dt.datetime(2025, 12, 31), "shareholders": 331600},
                    {"date": _dt.datetime(2026, 1, 31),  "shareholders": 325800},
                    {"date": _dt.datetime(2026, 2, 28),  "shareholders": 319400},
                    {"date": _dt.datetime(2026, 3, 31),  "shareholders": 314200},
                ],
                "ASII": [
                    {"date": _dt.datetime(2025, 4, 30),  "shareholders": 226500},
                    {"date": _dt.datetime(2025, 5, 31),  "shareholders": 228400},
                    {"date": _dt.datetime(2025, 6, 30),  "shareholders": 229100},
                    {"date": _dt.datetime(2025, 7, 31),  "shareholders": 223500},
                    {"date": _dt.datetime(2025, 8, 31),  "shareholders": 219800},
                    {"date": _dt.datetime(2025, 9, 30),  "shareholders": 215600},
                    {"date": _dt.datetime(2025, 10, 31), "shareholders": 212400},
                    {"date": _dt.datetime(2025, 11, 30), "shareholders": 209500},
                    {"date": _dt.datetime(2025, 12, 31), "shareholders": 208300},
                    {"date": _dt.datetime(2026, 1, 31),  "shareholders": 204100},
                    {"date": _dt.datetime(2026, 2, 28),  "shareholders": 201500},
                    {"date": _dt.datetime(2026, 3, 31),  "shareholders": 198200},
                ],
                "BREN": [
                    {"date": _dt.datetime(2025, 4, 30),  "shareholders": 142100},
                    {"date": _dt.datetime(2025, 5, 31),  "shareholders": 139500},
                    {"date": _dt.datetime(2025, 6, 30),  "shareholders": 138700},
                    {"date": _dt.datetime(2025, 7, 31),  "shareholders": 132400},
                    {"date": _dt.datetime(2025, 8, 31),  "shareholders": 128900},
                    {"date": _dt.datetime(2025, 9, 30),  "shareholders": 125400},
                    {"date": _dt.datetime(2025, 10, 31), "shareholders": 122100},
                    {"date": _dt.datetime(2025, 11, 30), "shareholders": 119500},
                    {"date": _dt.datetime(2025, 12, 31), "shareholders": 118200},
                    {"date": _dt.datetime(2026, 1, 31),  "shareholders": 112800},
                    {"date": _dt.datetime(2026, 2, 28),  "shareholders": 108500},
                    {"date": _dt.datetime(2026, 3, 31),  "shareholders": 105200},
                ]
            }

        # ── SCREENING TABLE ──────────────────────────────────────────────
        _sh_all = get_manual_sh_db_outer()
        _screen_rows = []
        for _tk, _records in _sh_all.items():
            _df_sc = pd.DataFrame(_records).sort_values("date").reset_index(drop=True)
            if len(_df_sc) < 2:
                continue
            _last  = int(_df_sc["shareholders"].iloc[-1])
            _prev1 = int(_df_sc["shareholders"].iloc[-2])
            _delta1 = _last - _prev1
            _pct1   = round(_delta1 / _prev1 * 100, 2) if _prev1 else 0

            # Trend 3 bulan: 3 entri terakhir, cek apakah konsisten naik/turun
            _trend3 = "—"
            if len(_df_sc) >= 4:
                _v3 = _df_sc["shareholders"].iloc[-4]
                _v2 = _df_sc["shareholders"].iloc[-3]
                _v1 = _df_sc["shareholders"].iloc[-2]
                _v0 = _df_sc["shareholders"].iloc[-1]
                if _v0 > _v1 > _v2 > _v3:
                    _trend3 = "🟢 Naik 3bln"
                elif _v0 < _v1 < _v2 < _v3:
                    _trend3 = "🔴 Turun 3bln"
                elif _v0 > _v1:
                    _trend3 = "🟡 Naik 1bln"
                elif _v0 < _v1:
                    _trend3 = "🔴 Turun 1bln"

            # Sinyal akumulasi/distribusi
            if "Naik 3bln" in _trend3:
                _signal = "🔥 Akumulasi Kuat"
            elif "Naik 1bln" in _trend3:
                _signal = "📈 Akumulasi"
            elif "Turun 3bln" in _trend3:
                _signal = "❄️ Distribusi Kuat"
            elif "Turun 1bln" in _trend3:
                _signal = "📉 Distribusi"
            else:
                _signal = "—"

            _screen_rows.append({
                "Ticker": _tk,
                "Pemegang Terakhir": f"{_last:,}",
                "Δ 1 Bulan": f"+{_delta1:,}" if _delta1 > 0 else f"{_delta1:,}",
                "Δ %": f"+{_pct1:.2f}%" if _pct1 > 0 else f"{_pct1:.2f}%",
                "Tren 3 Bln": _trend3,
                "Sinyal": _signal,
            })

        if _screen_rows:
            _df_screen = pd.DataFrame(_screen_rows)
            # Sort: akumulasi kuat dulu, lalu akumulasi, lalu distribusi
            _sort_key = {"🔥 Akumulasi Kuat": 0, "📈 Akumulasi": 1, "—": 2, "📉 Distribusi": 3, "❄️ Distribusi Kuat": 4}
            _df_screen["_sort"] = _df_screen["Sinyal"].map(_sort_key).fillna(5)
            _df_screen = _df_screen.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)

            # Custom HTML table — mobile-friendly
            _tbl_accent = "#F5C242"
            _tbl_bg     = "rgba(245,194,66,0.03)" if is_dark else "#fffdf7"
            _tbl_border = "rgba(245,194,66,0.12)" if is_dark else "#e8d99a"
            _tbl_head   = "rgba(245,194,66,0.10)" if is_dark else "#fef3c7"
            _tbl_text   = text_main
            _tbl_sub    = text_sub

            _tbl_html = f"""
<style>
.sh-screen-table {{ width:100%; border-collapse:collapse; font-family:'IBM Plex Mono',monospace; font-size:0.75rem; }}
.sh-screen-table th {{ background:{_tbl_head}; color:{_tbl_accent}; font-size:0.62rem; letter-spacing:0.1em; text-transform:uppercase; padding:8px 10px; border-bottom:1px solid {_tbl_border}; text-align:left; }}
.sh-screen-table td {{ padding:8px 10px; border-bottom:1px solid {_tbl_border}; color:{_tbl_text}; vertical-align:middle; }}
.sh-screen-table tr:last-child td {{ border-bottom:none; }}
.sh-screen-table tr:hover td {{ background:rgba(245,194,66,0.04); }}
.sh-ticker-badge {{ font-weight:700; color:{_tbl_accent}; font-size:0.78rem; }}
.sh-up {{ color:#26a69a; font-weight:600; }}
.sh-dn {{ color:#f23645; font-weight:600; }}
@media (max-width:768px) {{
  .sh-screen-table {{ font-size:0.68rem; }}
  .sh-screen-table th {{ font-size:0.56rem; padding:6px 6px; }}
  .sh-screen-table td {{ padding:6px 6px; }}
  .sh-ticker-badge {{ font-size:0.7rem; }}
}}
</style>
<div style="overflow-x:auto;width:100%;-webkit-overflow-scrolling:touch;">
<table class="sh-screen-table">
<thead><tr>
<th>Ticker</th><th>Pemegang</th><th>Δ 1 Bln</th><th>Δ %</th><th>Tren 3 Bln</th><th>Sinyal</th>
</tr></thead><tbody>"""

            for _, _r in _df_screen.iterrows():
                _up = "sh-up" if "+" in str(_r["Δ 1 Bulan"]) else "sh-dn"
                _tbl_html += f"""<tr>
<td><span class="sh-ticker-badge">{_r['Ticker']}</span></td>
<td>{_r['Pemegang Terakhir']}</td>
<td class="{_up}">{_r['Δ 1 Bulan']}</td>
<td class="{_up}">{_r['Δ %']}</td>
<td>{_r['Tren 3 Bln']}</td>
<td>{_r['Sinyal']}</td>
</tr>"""

            _tbl_html += "</tbody></table></div>"
            st.markdown(_tbl_html, unsafe_allow_html=True)

        st.markdown("<hr class='fancy-divider'>", unsafe_allow_html=True)

        # ── SHAREHOLDER TRACKER (per-ticker detail) ──────────────────────
        st.markdown("<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'>SHAREHOLDER TRACKER</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)
        st.markdown(f"<p style='font-family:IBM Plex Mono,monospace;font-size:0.7rem;letter-spacing:0.08em;color:{text_sub};margin-bottom:20px;text-transform:uppercase;'>Tren jumlah pemegang saham vs harga &middot; Deteksi akumulasi &amp; distribusi smart money &middot; Data IDX resmi</p>", unsafe_allow_html=True)

        col_sh_inp, col_sh_btn = st.columns([3, 1])
        with col_sh_inp:
            sh_ticker = st.text_input("KODE SAHAM:", "BBCA", key="sh_ticker_input").upper().strip()
        with col_sh_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            sh_run = st.button("▶ LOAD DATA", key="sh_run_btn", use_container_width=True)

        if sh_run or st.session_state.get("sh_last_ticker") == sh_ticker:
            st.session_state["sh_last_ticker"] = sh_ticker

            # ── Manual database (data publik IDX/Stockbit) ──────────────
            # ── Manual database (data publik IDX/Stockbit) ──────────────
            def get_manual_sh_db():
                # Data diupdate hingga MARET 2026 (rilis kisaran 10 April)
                return {
                    "BBCA": [
                        {"date": _dt.datetime(2025, 4, 30),  "shareholders": 320100},
                        {"date": _dt.datetime(2025, 5, 31),  "shareholders": 322500},
                        {"date": _dt.datetime(2025, 6, 30),  "shareholders": 321800},
                        {"date": _dt.datetime(2025, 7, 31),  "shareholders": 325400},
                        {"date": _dt.datetime(2025, 8, 31),  "shareholders": 328900},
                        {"date": _dt.datetime(2025, 9, 30),  "shareholders": 331200},
                        {"date": _dt.datetime(2025, 10, 31), "shareholders": 335500},
                        {"date": _dt.datetime(2025, 11, 30), "shareholders": 338100},
                        {"date": _dt.datetime(2025, 12, 31), "shareholders": 340200},
                        {"date": _dt.datetime(2026, 1, 31),  "shareholders": 345600},
                        {"date": _dt.datetime(2026, 2, 28),  "shareholders": 348200},
                        {"date": _dt.datetime(2026, 3, 31),  "shareholders": 351400},
                    ],
                    "BBRI": [
                        {"date": _dt.datetime(2025, 4, 30),  "shareholders": 930500},
                        {"date": _dt.datetime(2025, 5, 31),  "shareholders": 938200},
                        {"date": _dt.datetime(2025, 6, 30),  "shareholders": 948300},
                        {"date": _dt.datetime(2025, 7, 31),  "shareholders": 955100},
                        {"date": _dt.datetime(2025, 8, 31),  "shareholders": 962400},
                        {"date": _dt.datetime(2025, 9, 30),  "shareholders": 972100},
                        {"date": _dt.datetime(2025, 10, 31), "shareholders": 980500},
                        {"date": _dt.datetime(2025, 11, 30), "shareholders": 985200},
                        {"date": _dt.datetime(2025, 12, 31), "shareholders": 988500},
                        {"date": _dt.datetime(2026, 1, 31),  "shareholders": 995200},
                        {"date": _dt.datetime(2026, 2, 28),  "shareholders": 1002400},
                        {"date": _dt.datetime(2026, 3, 31),  "shareholders": 1015800},
                    ],
                    "BMRI": [
                        {"date": _dt.datetime(2025, 4, 30),  "shareholders": 489200},
                        {"date": _dt.datetime(2025, 5, 31),  "shareholders": 494500},
                        {"date": _dt.datetime(2025, 6, 30),  "shareholders": 498600},
                        {"date": _dt.datetime(2025, 7, 31),  "shareholders": 505400},
                        {"date": _dt.datetime(2025, 8, 31),  "shareholders": 509800},
                        {"date": _dt.datetime(2025, 9, 30),  "shareholders": 512300},
                        {"date": _dt.datetime(2025, 10, 31), "shareholders": 518700},
                        {"date": _dt.datetime(2025, 11, 30), "shareholders": 521400},
                        {"date": _dt.datetime(2025, 12, 31), "shareholders": 523700},
                        {"date": _dt.datetime(2026, 1, 31),  "shareholders": 528400},
                        {"date": _dt.datetime(2026, 2, 28),  "shareholders": 531200},
                        {"date": _dt.datetime(2026, 3, 31),  "shareholders": 535600},
                    ],
                    "TLKM": [
                        {"date": _dt.datetime(2025, 4, 30),  "shareholders": 365200},
                        {"date": _dt.datetime(2025, 5, 31),  "shareholders": 362100},
                        {"date": _dt.datetime(2025, 6, 30),  "shareholders": 358900},
                        {"date": _dt.datetime(2025, 7, 31),  "shareholders": 352400},
                        {"date": _dt.datetime(2025, 8, 31),  "shareholders": 348500},
                        {"date": _dt.datetime(2025, 9, 30),  "shareholders": 344200},
                        {"date": _dt.datetime(2025, 10, 31), "shareholders": 339800},
                        {"date": _dt.datetime(2025, 11, 30), "shareholders": 335400},
                        {"date": _dt.datetime(2025, 12, 31), "shareholders": 331600},
                        {"date": _dt.datetime(2026, 1, 31),  "shareholders": 325800},
                        {"date": _dt.datetime(2026, 2, 28),  "shareholders": 319400},
                        {"date": _dt.datetime(2026, 3, 31),  "shareholders": 314200},
                    ],
                    "ASII": [
                        {"date": _dt.datetime(2025, 4, 30),  "shareholders": 226500},
                        {"date": _dt.datetime(2025, 5, 31),  "shareholders": 228400},
                        {"date": _dt.datetime(2025, 6, 30),  "shareholders": 229100},
                        {"date": _dt.datetime(2025, 7, 31),  "shareholders": 223500},
                        {"date": _dt.datetime(2025, 8, 31),  "shareholders": 219800},
                        {"date": _dt.datetime(2025, 9, 30),  "shareholders": 215600},
                        {"date": _dt.datetime(2025, 10, 31), "shareholders": 212400},
                        {"date": _dt.datetime(2025, 11, 30), "shareholders": 209500},
                        {"date": _dt.datetime(2025, 12, 31), "shareholders": 208300},
                        {"date": _dt.datetime(2026, 1, 31),  "shareholders": 204100},
                        {"date": _dt.datetime(2026, 2, 28),  "shareholders": 201500},
                        {"date": _dt.datetime(2026, 3, 31),  "shareholders": 198200},
                    ],
                    "BREN": [
                        {"date": _dt.datetime(2025, 4, 30),  "shareholders": 142100},
                        {"date": _dt.datetime(2025, 5, 31),  "shareholders": 139500},
                        {"date": _dt.datetime(2025, 6, 30),  "shareholders": 138700},
                        {"date": _dt.datetime(2025, 7, 31),  "shareholders": 132400},
                        {"date": _dt.datetime(2025, 8, 31),  "shareholders": 128900},
                        {"date": _dt.datetime(2025, 9, 30),  "shareholders": 125400},
                        {"date": _dt.datetime(2025, 10, 31), "shareholders": 122100},
                        {"date": _dt.datetime(2025, 11, 30), "shareholders": 119500},
                        {"date": _dt.datetime(2025, 12, 31), "shareholders": 118200},
                        {"date": _dt.datetime(2026, 1, 31),  "shareholders": 112800},
                        {"date": _dt.datetime(2026, 2, 28),  "shareholders": 108500},
                        {"date": _dt.datetime(2026, 3, 31),  "shareholders": 105200},
                    ]
                }
                
            manual_db = get_manual_sh_db()
            sh_data = manual_db.get(sh_ticker, [])
            has_live_data = bool(sh_data)

            if not has_live_data:
                # ── COMING SOON STATE ──────────────────────────────────
                st.markdown(f"""
                <div style='
                    background: {met_bg};
                    border: 1px solid {met_border};
                    border-left: 4px solid #F5C242;
                    border-radius: 14px;
                    padding: 48px 40px;
                    text-align: center;
                    margin: 24px 0;
                    position: relative;
                    overflow: hidden;
                '>
                    <div style='
                        position: absolute; top: 0; left: 0; right: 0; height: 2px;
                        background: linear-gradient(90deg, transparent, #F5C242, transparent);
                        animation: shimmer 2s infinite;
                    '></div>
                    <div style='font-size: 2.5rem; margin-bottom: 12px;'>📡</div>
                    <div style='
                        font-family: IBM Plex Mono, monospace;
                        font-size: 1.1rem;
                        font-weight: 700;
                        letter-spacing: 0.15em;
                        color: #F5C242;
                        text-transform: uppercase;
                        margin-bottom: 8px;
                    '>DATA PIPELINE IN PROGRESS</div>
                    <div style='
                        font-family: IBM Plex Mono, monospace;
                        font-size: 0.8rem;
                        color: {text_sub};
                        max-width: 520px;
                        margin: 0 auto 24px;
                        line-height: 1.7;
                    '>
                        Integrasi data pemegang saham real-time untuk <b style="color:{text_main};">{sh_ticker}</b> sedang dalam proses pengembangan.
                        Sumber resmi IDX menerbitkan data ini setiap bulan (biasanya di atas tanggal 10).
                        Tim SIGMA sedang membangun pipeline scraping otomatis untuk menangkap data terbaru setiap emiten.
                    </div>
                    <div style='
                        display: inline-flex;
                        align-items: center;
                        gap: 10px;
                        background: rgba(245,194,66,0.08);
                        border: 1px solid rgba(245,194,66,0.25);
                        border-radius: 8px;
                        padding: 10px 20px;
                        font-family: IBM Plex Mono, monospace;
                        font-size: 0.72rem;
                        color: #F5C242;
                        letter-spacing: 0.1em;
                        text-transform: uppercase;
                    '>
                        <span style='width: 8px; height: 8px; background: #F5C242; border-radius: 50%; display: inline-block; animation: pulse 1.5s infinite;'></span>
                        Saham dengan data tersedia: BBCA &nbsp;·&nbsp; BBRI &nbsp;·&nbsp; BMRI &nbsp;·&nbsp; TLKM &nbsp;·&nbsp; ASII &nbsp;·&nbsp; BREN
                    </div>
                </div>
                <style>
                @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:0.3}} }}
                </style>
                """, unsafe_allow_html=True)

            else:
                # ── RENDER CHART & DATA ────────────────────────────────
                import plotly.graph_objects as go
                import numpy as np

                @st.cache_data(ttl=3600, show_spinner=False)
                def fetch_stock_price_2y(ticker):
                    try:
                        import yfinance as yf
                        t = yf.Ticker(f"{ticker}.JK")
                        hist = t.history(period="2y", auto_adjust=True)
                        if not hist.empty:
                            hist = hist[["Close"]].reset_index()
                            hist.columns = ["date", "price"]
                            hist["date"] = pd.to_datetime(hist["date"]).dt.tz_localize(None)
                            return hist
                    except: pass
                    return pd.DataFrame()

                with st.spinner(f"Mengambil data harga {sh_ticker}..."):
                    price_df = fetch_stock_price_2y(sh_ticker)

                df_sh = pd.DataFrame(sh_data)
                df_sh["date"] = pd.to_datetime(df_sh["date"])
                df_sh = df_sh.sort_values("date").reset_index(drop=True)
                df_sh["delta"] = df_sh["shareholders"].diff()
                df_sh["pct_change"] = df_sh["shareholders"].pct_change() * 100

                # Sinyal
                n_periods = min(6, len(df_sh) - 1)
                trend_6m = df_sh["shareholders"].iloc[-1] - df_sh["shareholders"].iloc[-1 - n_periods]
                pct_6m = (trend_6m / df_sh["shareholders"].iloc[-1 - n_periods]) * 100 if n_periods > 0 else 0

                if pct_6m < -15:
                    sinyal, sinyal_color = "DISTRIBUSI KUAT", "#f23645"
                    sinyal_desc = "Jumlah pemegang saham turun >15% dalam 6 bulan. Smart money kemungkinan besar sedang distribusi — menjual saham ke retail yang makin sedikit. Waspadai tekanan jual lanjutan."
                elif pct_6m < -5:
                    sinyal, sinyal_color = "DISTRIBUSI MODERAT", "#F5C242"
                    sinyal_desc = "Pemegang saham turun 5–15%. Perlu konfirmasi dari bandarmologi dan volume. Bisa konsolidasi atau awal distribusi."
                elif pct_6m > 15:
                    sinyal, sinyal_color = "RETAIL MASUK MASIF", "#F5C242"
                    sinyal_desc = "Pemegang saham naik >15% — retail masuk besar-besaran. Hati-hati: bisa berarti euphoria puncak. Konfirmasi dengan net broker apakah smart money sedang exit."
                elif pct_6m > 5:
                    sinyal, sinyal_color = "AKUMULASI BERTAHAP", "#089981"
                    sinyal_desc = "Pemegang saham naik 5–15% secara gradual. Sinyal positif — kemungkinan akumulasi terstruktur. Konfirmasi dengan tren harga dan net buy asing."
                else:
                    sinyal, sinyal_color = "KONSOLIDASI", "#4285F4"
                    sinyal_desc = "Perubahan pemegang saham minimal. Pasar dalam fase tunggu. Monitor breakout dari range ini."

                latest = df_sh.iloc[-1]
                delta_val = latest["delta"] if not pd.isna(latest["delta"]) else 0
                peak_idx  = df_sh["shareholders"].idxmax()
                peak_val  = df_sh.loc[peak_idx, "shareholders"]
                peak_date = df_sh.loc[peak_idx, "date"].strftime("%b %Y")
                total_chg = ((latest["shareholders"] - df_sh.iloc[0]["shareholders"]) / df_sh.iloc[0]["shareholders"] * 100)

                # Metrics
                m1, m2, m3, m4 = st.columns(4)
                for col, title, val, sub, sub_c in [
                    (m1, "Pemegang Saham Terkini", f"{int(latest['shareholders']):,}",
                     f"{'▲' if delta_val>=0 else '▼'} {abs(int(delta_val)):,} vs bulan lalu",
                     "#089981" if delta_val >= 0 else "#f23645"),
                    (m2, "Peak Pemegang Saham", f"{int(peak_val):,}", peak_date, text_sub),
                    (m3, "Perubahan 6 Bulan",
                     f"{'+'if pct_6m>=0 else ''}{pct_6m:.1f}%",
                     f"Sejak {df_sh.iloc[-1-n_periods]['date'].strftime('%b %Y')}",
                     "#089981" if pct_6m >= 0 else "#f23645"),
                    (m4, "Sinyal", sinyal, "Berdasarkan tren 6 bulan", sinyal_color),
                ]:
                    with col:
                        st.markdown(f"""
                        <div style='background:{met_bg};border:1px solid {met_border};border-radius:10px;padding:14px 16px;'>
                            <div style='font-size:0.6rem;letter-spacing:0.12em;color:{text_sub};text-transform:uppercase;font-weight:600;margin-bottom:4px;'>{title}</div>
                            <div style='font-size:{"1.0" if title=="Sinyal" else "1.35"}rem;font-weight:700;color:{sinyal_color if title=="Sinyal" else text_main};'>{val}</div>
                            <div style='font-size:0.65rem;color:{sub_c};margin-top:3px;'>{sub}</div>
                        </div>""", unsafe_allow_html=True)

                st.markdown(f"<div style='font-size:0.62rem;color:{text_sub};text-align:right;margin:6px 0 4px;font-family:IBM Plex Mono,monospace;'>Sumber: Database Manual (IDX Stockbit) &nbsp;|&nbsp; Update: {latest['date'].strftime('%d %b %Y')}</div>", unsafe_allow_html=True)
                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

                # ── Align price ke bulan shareholder ──
                if not price_df.empty:
                    price_df["ym"] = price_df["date"].dt.to_period("M")
                    price_monthly = price_df.groupby("ym")["price"].last().reset_index()
                    df_sh["ym"] = df_sh["date"].dt.to_period("M")
                    df_merged = df_sh.merge(price_monthly[["ym", "price"]], on="ym", how="left")
                else:
                    df_merged = df_sh.copy()
                    df_merged["price"] = float("nan")

                # ── Normalisasi min-max ──
                sh_vals = df_sh["shareholders"].values.astype(float)
                sh_norm = (sh_vals - sh_vals.min()) / max(sh_vals.max() - sh_vals.min(), 1) * 100

                pr_vals = df_merged["price"].values.astype(float)
                pr_valid = pr_vals[~np.isnan(pr_vals)]
                if len(pr_valid) > 0:
                    pr_norm = np.where(
                        np.isnan(pr_vals), np.nan,
                        (pr_vals - pr_valid.min()) / max(pr_valid.max() - pr_valid.min(), 1) * 100
                    )
                else:
                    pr_norm = np.full_like(pr_vals, np.nan)

                # --- MENAMPILKAN DATA 6 BULAN TERAKHIR DALAM BENTUK TABEL ---
                
                # Ambil 6 bulan terakhir dari dataframe df_sh
                df_sh_6m = df_sh.tail(6).copy()
                
                # Format tanggal menjadi nama bulan dan tahun (misal: "March 2026")
                df_sh_6m['Periode'] = df_sh_6m['date'].dt.strftime('%B %Y')
                
                # Pastikan kolom delta ada untuk melihat perubahan
                if 'delta' not in df_sh_6m.columns:
                    df_sh_6m['delta'] = df_sh_6m['shareholders'].diff().fillna(0)
                
                # Susun ulang kolom untuk ditampilkan
                df_display = df_sh_6m[['Periode', 'shareholders', 'delta']].copy()
                
                st.markdown("##### 📊 Rekap 6 Bulan Terakhir")
                
                # Tampilkan menggunakan dataframe bawaan Streamlit yang bersih
                st.dataframe(
                    df_display,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Periode": st.column_config.TextColumn("Bulan"),
                        "shareholders": st.column_config.NumberColumn(
                            "Total Pemegang Saham",
                            format="%d"
                        ),
                        "delta": st.column_config.NumberColumn(
                            "Perubahan (MoM)",
                            format="%+d" # Menampilkan tanda + atau - otomatis
                        )
                    }
                )

                st.markdown(f"""
                <div style='display:flex;gap:24px;font-family:IBM Plex Mono,monospace;font-size:0.7rem;color:{text_sub};margin:-6px 0 14px;flex-wrap:wrap;'>
                    <span style='color:#4285F4;'>━━ Pemegang Saham (skala kiri)</span>
                    <span style='color:#F5C242;'>┄┄ Harga Saham (ternormalisasi)</span>
                    <span>🟢🔴 Bar = Δ Bulan Ini</span>
                </div>""", unsafe_allow_html=True)

                # Interpretasi
                st.markdown(f"""
                <div class="trm-card" style="border-left:3px solid {sinyal_color};margin-bottom:16px;">
                    <div class="trm-card-title" style="color:{sinyal_color};">🔍 INTERPRETASI: {sinyal}</div>
                    <p style='color:{text_main};font-size:0.88rem;line-height:1.7;margin:0;'>{sinyal_desc}</p>
                    <p style='color:{text_sub};font-size:0.82rem;line-height:1.7;margin:10px 0 0;'>
                    <span style='color:#F5C242;font-weight:600;'>⚠️ Logika Bandarmologi IDX:</span>
                    Pemegang <b style='color:#f23645;'>turun</b> = distribusi (smart money jual, retail makin sedikit yang pegang).
                    Pemegang <b style='color:#089981;'>naik bertahap</b> = spread kepemilikan = bisa akumulasi awal.
                    Cross-check dengan net broker dan price action.
                    </p>
                </div>""", unsafe_allow_html=True)

                # Tabel historis
                st.markdown(f"<p style='font-family:IBM Plex Mono,monospace;font-size:0.7rem;letter-spacing:0.1em;text-transform:uppercase;color:{text_sub};margin-bottom:8px;'>DATA HISTORIS BULANAN</p>", unsafe_allow_html=True)
                df_disp = df_sh[["date", "shareholders", "delta", "pct_change"]].copy()
                df_disp = df_disp.iloc[::-1].reset_index(drop=True)
                df_disp["date"] = df_disp["date"].dt.strftime("%d %b %Y")
                df_disp["shareholders"] = df_disp["shareholders"].apply(lambda x: f"{int(x):,}")
                df_disp["delta"] = df_disp["delta"].apply(
                    lambda x: f"+{int(x):,}" if not pd.isna(x) and x > 0 else (f"{int(x):,}" if not pd.isna(x) else "-"))
                df_disp["pct_change"] = df_disp["pct_change"].apply(
                    lambda x: f"+{x:.2f}%" if not pd.isna(x) and x > 0 else (f"{x:.2f}%" if not pd.isna(x) else "-"))
                df_disp.columns = ["Tanggal", "Pemegang Saham", "Δ Bulan Ini", "Δ %"]
                st.dataframe(df_disp, use_container_width=True, hide_index=True)

        st.markdown("<hr class='fancy-divider'>", unsafe_allow_html=True)


    with tab_ai:
        st.markdown("<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'>SIGMA AI &mdash; AUTO TECHNICAL &amp; FUNDAMENTAL INSIGHT</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)
        st.markdown(f"<p style='font-family:IBM Plex Mono,monospace;font-size:0.7rem;letter-spacing:0.08em;color:{text_sub};margin-bottom:20px;text-transform:uppercase;'>Analisis instan &middot; Data Live IDX &middot; Auto-Drawing Trade Plan</p>", unsafe_allow_html=True)

        col_input, col_btn = st.columns([3, 1])
        with col_input:
            ticker_input = st.text_input("KODE SAHAM / TICKER IDX:", "BBCA").upper()
        with col_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            run_analysis = st.button("▶ ANALYZE", use_container_width=True)
        
        st.markdown("<hr class='fancy-divider'>", unsafe_allow_html=True)

        if ticker_input:
            df_chart = pd.DataFrame()
            ai_data = None
            ai_text_verdict = ""
            
            try:
                t = yf.Ticker(f"{ticker_input}.JK")
                df_chart = t.history(period="6mo")
            except Exception as e:
                pass

            if run_analysis:
                with st.spinner("SIGMA sedang mengumpulkan data, menganalisis, dan menggambar chart..."):
                    try:
                        fund_context = build_fundamental_from_text(f"fundamental {ticker_input}")
                        
                        live_price_str = "N/A"
                        if not df_chart.empty:
                            try: 
                                live_price_str = f"Rp {float(df_chart['Close'].iloc[-1]):,.0f}"
                            except Exception as e: 
                                pass

                        vol_context = ""
                        if not df_chart.empty and 'Volume' in df_chart.columns:
                            try:
                                avg_vol_20 = df_chart['Volume'].rolling(20).mean().iloc[-1]
                                avg_vol_5  = df_chart['Volume'].rolling(5).mean().iloc[-1]
                                last_vol   = df_chart['Volume'].iloc[-1]
                                last_close = df_chart['Close'].iloc[-1]
                                last_value = last_vol * last_close  

                                spike_ratio = last_vol / avg_vol_20 if avg_vol_20 > 0 else 1

                                price_chg_5d = (df_chart['Close'].iloc[-1] - df_chart['Close'].iloc[-6]) / df_chart['Close'].iloc[-6] * 100 if len(df_chart) >= 6 else 0
                                vol_chg_5d   = (avg_vol_5 - df_chart['Volume'].rolling(20).mean().iloc[-6]) / df_chart['Volume'].rolling(20).mean().iloc[-6] * 100 if len(df_chart) >= 6 else 0

                                dryup = avg_vol_5 < (avg_vol_20 * 0.5)

                                if spike_ratio >= 10:    vol_signal = "🔴 VOLUME EKSTREM"
                                elif spike_ratio >= 5:   vol_signal = "🟠 VOLUME SANGAT TINGGI"
                                elif spike_ratio >= 2:   vol_signal = "🟡 VOLUME SPIKE"
                                elif dryup:              vol_signal = "🔵 VOLUME DRY-UP"
                                else:                    vol_signal = "⚪ Volume normal"

                                if price_chg_5d > 2 and vol_chg_5d < -20:
                                    pvd_signal = "&#9888; DIVERGENSI: Harga naik tapi volume turun"
                                elif price_chg_5d < -2 and vol_chg_5d < -20:
                                    pvd_signal = "🔵 Volume turun saat harga turun"
                                elif price_chg_5d > 2 and vol_chg_5d > 20:
                                    pvd_signal = "✅ Harga naik + volume naik"
                                elif price_chg_5d < -2 and vol_chg_5d > 20:
                                    pvd_signal = "&#9888; Volume spike saat turun"
                                else:
                                    pvd_signal = "Volume dan harga konsisten"

                                vol_context = f"Volume Terakhir: {int(last_vol):,} | Spike Ratio: {spike_ratio:.1f}x | Sinyal: {vol_signal} | Divergensi: {pvd_signal}"
                            except Exception as e:
                                vol_context = ""

                        # ── Shareholder context untuk ticker ini ────────────
                        _sh_ctx = ""
                        try:
                            _sh_db_tp = get_manual_sh_db_outer() if 'get_manual_sh_db_outer' in dir() else {}
                            _sh_recs = _sh_db_tp.get(ticker_input, [])
                            if len(_sh_recs) >= 2:
                                _sh_df2 = pd.DataFrame(_sh_recs).sort_values("date").reset_index(drop=True)
                                _sh_last2 = int(_sh_df2["shareholders"].iloc[-1])
                                _sh_prev2 = int(_sh_df2["shareholders"].iloc[-2])
                                _sh_delta2 = _sh_last2 - _sh_prev2
                                _sh_pct2 = round(_sh_delta2 / _sh_prev2 * 100, 2)
                                _sh_trend2 = "NAIK (akumulasi retail)" if _sh_delta2 > 0 else "TURUN (distribusi retail)"
                                if len(_sh_df2) >= 4:
                                    _v3b = _sh_df2["shareholders"].iloc[-4]
                                    _v2b = _sh_df2["shareholders"].iloc[-3]
                                    _v1b = _sh_df2["shareholders"].iloc[-2]
                                    _v0b = _sh_df2["shareholders"].iloc[-1]
                                    if _v0b > _v1b > _v2b > _v3b:
                                        _sh_trend2 += " | Tren 3 bulan: NAIK KONSISTEN — sinyal akumulasi kuat"
                                    elif _v0b < _v1b < _v2b < _v3b:
                                        _sh_trend2 += " | Tren 3 bulan: TURUN KONSISTEN — sinyal distribusi kuat"
                                _sh_ctx = f"Data Pemegang Saham {ticker_input}: {_sh_last2:,} pemegang (Δ {_sh_delta2:+,} = {_sh_pct2:+.2f}%) | Tren: {_sh_trend2}"
                        except:
                            _sh_ctx = ""

                        dashboard_prompt = f"""Kamu adalah SIGMA AI, analis saham Indonesia profesional. Buat TRADE PLAN LENGKAP untuk saham {ticker_input}.

=== DATA HARGA & TEKNIKAL ===
Harga Terakhir: {live_price_str}
{vol_context}

=== DATA FUNDAMENTAL ===
{fund_context}

=== DATA PEMEGANG SAHAM ===
{_sh_ctx if _sh_ctx else "Data shareholder tidak tersedia untuk ticker ini."}

=== INSTRUKSI ANALISA ===
Buat analisa komprehensif dengan STRUKTUR WAJIB berikut (jangan disingkat):

1. 📊 KONDISI TEKNIKAL
   - Posisi harga vs support/resistance utama
   - Tren jangka pendek (1-2 minggu) dan menengah (1-3 bulan)
   - Momentum: apakah ada sinyal reversal atau continuation?
   - Volume: konfirmasi atau divergensi dari pergerakan harga?

2. 🏢 KONDISI FUNDAMENTAL
   - Valuasi saat ini (murah/wajar/mahal)?
   - Kinerja keuangan terbaru (EPS, revenue, margin)
   - Katalis positif atau negatif ke depan
   - Posisi vs kompetitor sektor

3. 👥 SINYAL PEMEGANG SAHAM
   - Analisa tren jumlah pemegang saham
   - Apakah ada akumulasi retail atau distribusi?
   - Implikasinya terhadap supply/demand saham

4. 📰 OUTLOOK SEKTOR & MAKRO
   - Kondisi sektor {ticker_input} saat ini
   - Faktor makro yang mempengaruhi (suku bunga, kurs, kebijakan)
   - Risiko utama yang perlu diwaspadai

5. ⚡ KESIMPULAN & BIAS
   - Bias: BULLISH / BEARISH / SIDEWAYS (pilih satu, jelaskan)
   - Level kunci yang harus diperhatikan

6. 🎯 TRADE PLAN EKSEKUSI
   - Skenario A (Optimis): Entry, SL, TP1, TP2
   - Skenario B (Konservatif): Entry, SL, TP1
   - Time horizon: berapa hari/minggu?
   - Risk/Reward ratio masing-masing skenario
   - Sizing rekomendasi (% portofolio)

Semua harga dalam Rupiah, mendekati harga saat ini ({live_price_str}).
Jawab dalam Bahasa Indonesia. Padat tapi detail. JANGAN ada kalimat pengantar JSON.

Di AKHIR JAWABAN, tambahkan JSON ini (setelah semua analisa selesai):
```json
{{"entry_low": 0, "entry_high": 0, "stop_loss": 0, "tp1": 0, "tp2": null, "tp3": null}}
```"""

                        try:
                            ai_raw_result, _ = _call_groq_primary(dashboard_prompt)
                        except Exception as e_groq:
                            try:
                                ai_raw_result, _ = _call_gemini_text([{"role": "user", "content": dashboard_prompt}])
                            except Exception as e_gem:
                                ai_raw_result = f"Gagal memanggil AI: {e_gem}"

                        try:
                            # Coba berbagai format: ```json block, { plain }, atau inline
                            json_match = re.search(r'```json\s*(.*?)\s*```', ai_raw_result, re.DOTALL)
                            if not json_match:
                                # Coba cari JSON object langsung (tanpa backtick)
                                json_match_plain = re.search(r'\{[^{}]*"entry_low"[^{}]*\}', ai_raw_result, re.DOTALL)
                                if json_match_plain:
                                    raw_json = json.loads(json_match_plain.group(0))
                                else:
                                    # Coba cari JSON object apapun di akhir teks
                                    json_match_any = re.search(r'\{[\s\S]*\}', ai_raw_result)
                                    raw_json = json.loads(json_match_any.group(0)) if json_match_any else {}
                            else:
                                raw_json = json.loads(json_match.group(1))

                            def _safe_float(v):
                                try: return float(v) if v is not None else None
                                except: return None

                            ai_data = {
                                "entry_low":  _safe_float(raw_json.get("entry_low")),
                                "entry_high": _safe_float(raw_json.get("entry_high")),
                                "stop_loss":  _safe_float(raw_json.get("stop_loss")),
                                "tp1": _safe_float(raw_json.get("tp1") or raw_json.get("target")),
                                "tp2": _safe_float(raw_json.get("tp2")),
                                "tp3": _safe_float(raw_json.get("tp3")),
                            }
                            # Validasi: semua harga harus > 0 dan masuk akal
                            last_price = float(df_chart['Close'].iloc[-1]) if not df_chart.empty else 0
                            if last_price > 0:
                                def _plausible(v, ref, pct=0.6):
                                    return v and v > 0 and abs(v - ref) / ref < pct
                                if not _plausible(ai_data['entry_low'], last_price): ai_data['entry_low'] = None
                                if not _plausible(ai_data['entry_high'], last_price): ai_data['entry_high'] = None
                                if not _plausible(ai_data['stop_loss'], last_price): ai_data['stop_loss'] = None
                                if not _plausible(ai_data['tp1'], last_price): ai_data['tp1'] = None
                                if not _plausible(ai_data['tp2'], last_price): ai_data['tp2'] = None
                                if not _plausible(ai_data['tp3'], last_price): ai_data['tp3'] = None
                            # Hanya simpan ai_data jika minimal entry_low atau stop_loss valid
                            if not (ai_data.get('entry_low') or ai_data.get('stop_loss')):
                                ai_data = None

                            # Bersihkan teks dari JSON block
                            ai_text_verdict = re.sub(r'```json\s*.*?\s*```', '', ai_raw_result, flags=re.DOTALL).strip()
                            ai_text_verdict = re.sub(r'\{[\s\S]*"entry_low"[\s\S]*\}', '', ai_text_verdict).strip()
                            # Hapus kalimat pengantar JSON yang tertinggal di akhir
                            ai_text_verdict = re.sub(r'\n*[^\n]*[Bb]erikut[^\n]*(JSON|json|blok|block)[^\n]*:?\s*$', '', ai_text_verdict).strip()
                            ai_text_verdict = re.sub(r'\n*[^\n]*(following|berikut)[^\n]*(JSON|blok|strategi)[^\n]*:?\s*$', '', ai_text_verdict, flags=re.IGNORECASE).strip()
                        except Exception as e:
                            ai_data = None
                            ai_text_verdict = ai_raw_result

                    except Exception as e:
                        st.error(f"Gagal memproses analisa AI: {e}")

            st.markdown(f"<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'>TECHNICAL PLAN CHART &mdash; {ticker_input}</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)

            if not df_chart.empty:
                try:
                    from plotly.subplots import make_subplots

                    inc_color     = '#089981'
                    dec_color     = '#f23645'
                    tv_bg_color   = "#131722" if is_dark else "#ffffff"
                    tv_text_color = "#b2b5be" if is_dark else "#1f2937"
                    tv_border     = "#2a2e39" if is_dark else "#e0e3eb"

                    # ── Bersihkan df: hanya trading days (buang weekend) ──
                    df_chart = df_chart.copy()
                    df_chart.index = pd.to_datetime(df_chart.index)
                    df_chart = df_chart[df_chart.index.dayofweek < 5].dropna(subset=['Open','High','Low','Close'])

                    # ── EMAs ──────────────────────────────────────────────
                    df_chart['EMA13']  = df_chart['Close'].ewm(span=13,  adjust=False).mean()
                    df_chart['EMA21']  = df_chart['Close'].ewm(span=21,  adjust=False).mean()
                    df_chart['EMA100'] = df_chart['Close'].ewm(span=100, adjust=False).mean()
                    df_chart['EMA200'] = df_chart['Close'].ewm(span=200, adjust=False).mean()

                    # ── RSI ───────────────────────────────────────────────
                    delta = df_chart['Close'].diff()
                    gain  = delta.clip(lower=0)
                    loss  = -delta.clip(upper=0)
                    avg_g = gain.ewm(com=13, adjust=False).mean()
                    avg_l = loss.ewm(com=13, adjust=False).mean()
                    rs    = avg_g / avg_l.replace(0, 1e-9)
                    df_chart['RSI'] = (100 - (100 / (1 + rs))).fillna(50)

                    # ── MACD ──────────────────────────────────────────────
                    ema12 = df_chart['Close'].ewm(span=12, adjust=False).mean()
                    ema26 = df_chart['Close'].ewm(span=26, adjust=False).mean()
                    df_chart['MACD']        = ema12 - ema26
                    df_chart['MACD_signal'] = df_chart['MACD'].ewm(span=9, adjust=False).mean()
                    df_chart['MACD_hist']   = df_chart['MACD'] - df_chart['MACD_signal']

                    # ── x-axis: string kategori (anti-gap weekend) ────────
                    x_str  = df_chart.index.strftime('%d %b %y').tolist()
                    n_bars = len(x_str)

                    # Padding kanan ~30 bar agar candle tidak mepet & ada ruang label
                    n_pad   = 30
                    pad_str = [f"_p{i}" for i in range(n_pad)]
                    x_all   = x_str + pad_str
                    n_total = len(x_all)

                    # ── Figure 4 rows: Price / Volume / RSI / MACD ────────
                    fig = make_subplots(
                        rows=4, cols=1,
                        shared_xaxes=True,
                        row_heights=[0.52, 0.16, 0.16, 0.16],
                        vertical_spacing=0.012,
                    )

                    # ── Candlestick ───────────────────────────────────────
                    fig.add_trace(go.Candlestick(
                        x=x_str,
                        open=df_chart['Open'],  high=df_chart['High'],
                        low=df_chart['Low'],    close=df_chart['Close'],
                        increasing_line_color=inc_color,
                        decreasing_line_color=dec_color,
                        name="Price", showlegend=False,
                    ), row=1, col=1)

                    # ── EMAs ──────────────────────────────────────────────
                    for col_n, clr, w in [
                        ('EMA13','#009dff',1.2), ('EMA21','#ff0000',1.2),
                        ('EMA100','#cc00ff',1.2), ('EMA200','#F5C242',1.5),
                    ]:
                        fig.add_trace(go.Scatter(
                            x=x_str, y=df_chart[col_n],
                            mode='lines', line=dict(color=clr, width=w),
                            showlegend=False,
                        ), row=1, col=1)

                    # ── Trade plan lines + labels style TradingView ────────
                    if ai_data:
                        try:
                            el  = ai_data.get('entry_low')
                            eh  = ai_data.get('entry_high')
                            sl  = ai_data.get('stop_loss')
                            tp1 = ai_data.get('tp1')
                            tp2 = ai_data.get('tp2')
                            tp3 = ai_data.get('tp3')

                            # Fungsi Final: Garis Full Layar & Label Rata Kanan Dalam (Untuk SL dan TP)
                            def _draw_tv_level(y_val, label_text, line_color, bg_color, text_color, dash_style='dash'):
                                if not y_val: return
                                y_val = float(y_val)

                                # 1. Garis absolut dari kiri (0) ke kanan (1) layar penuh
                                fig.add_shape(
                                    type="line", xref="paper", yref="y",
                                    x0=0, x1=1, y0=y_val, y1=y_val,
                                    line=dict(color=line_color, width=1.5, dash=dash_style),
                                    layer="below"
                                )

                                # 2. Label dikunci di x=1.0 (batas tembok kanan)
                                fig.add_annotation(
                                    xref='paper', yref='y',
                                    x=1.0, y=y_val,
                                    text=f"<b>{label_text} {y_val:,.0f}</b>",
                                    showarrow=False,
                                    xanchor='right', yanchor='middle',
                                    font=dict(color=text_color, size=10, family='IBM Plex Mono, monospace'),
                                    bgcolor=bg_color,
                                    bordercolor=line_color,
                                    borderwidth=1,
                                    borderpad=4
                                )

                            # Area BUY (Hanya kotak highlight & 1 Label gabungan di tengah)
                            if el and eh:
                                el_val = float(el)
                                eh_val = float(eh)
                                mid_y = (el_val + eh_val) / 2 # Mencari titik tengah untuk posisi label
                                
                                # Gambar kotak background hijau tanpa garis tepi
                                fig.add_shape(
                                    type="rect", xref="paper", yref="y",
                                    x0=0, x1=1, y0=el_val, y1=eh_val,
                                    fillcolor="rgba(8,153,129,0.15)", # Hijau transparan
                                    line=dict(width=0), # Garis tepi dihilangkan
                                    layer="below"
                                )

                                # Gambar satu label di tengah-tengah kotak
                                fig.add_annotation(
                                    xref='paper', yref='y',
                                    x=1.0, y=mid_y,
                                    text=f"<b>BUY {min(el_val, eh_val):,.0f} - {max(el_val, eh_val):,.0f}</b>",
                                    showarrow=False,
                                    xanchor='right', yanchor='middle',
                                    font=dict(color='#089981', size=10, family='IBM Plex Mono, monospace'),
                                    bgcolor=tv_bg_color,
                                    bordercolor='#089981',
                                    borderwidth=1,
                                    borderpad=4
                                )

                            # SL (Merah Solid)
                            if sl:
                                _draw_tv_level(sl, "SL", '#f23645', '#f23645', '#ffffff', 'solid')

                            # TP (Kuning Solid)
                            if tp1: _draw_tv_level(tp1, "TP1", '#F5C242', '#F5C242', '#000000', 'dot')
                            if tp2: _draw_tv_level(tp2, "TP2", '#F5C242', '#F5C242', '#000000', 'dot')
                            if tp3: _draw_tv_level(tp3, "TP3", '#F5C242', '#F5C242', '#000000', 'dot')

                        except Exception as e:
                            st.warning(f"AI gagal menggambar Trade Plan: {e}")

                    # ── Volume (split buy/sell power) ─────────────────────
                    hl_range = (df_chart['High'] - df_chart['Low']).replace(0, 1)
                    buy_vol  = (df_chart['Volume'] * (df_chart['Close'] - df_chart['Low'])  / hl_range).clip(lower=0)
                    sell_vol = (df_chart['Volume'] * (df_chart['High']  - df_chart['Close']) / hl_range).clip(lower=0)
                    # Bar bawah: sell (merah), bar atas: buy (hijau) — stacked
                    fig.add_trace(go.Bar(
                        x=x_str, y=sell_vol,
                        marker_color='rgba(242,54,69,0.75)',
                        name='Sell Power', showlegend=False,
                    ), row=2, col=1)
                    fig.add_trace(go.Bar(
                        x=x_str, y=buy_vol,
                        marker_color='rgba(8,153,129,0.85)',
                        name='Buy Power', showlegend=False,
                    ), row=2, col=1)

                    # ── RSI (level 70/30) ──────────────────────────────────
                    fig.add_trace(go.Scatter(
                        x=x_str, y=df_chart['RSI'],
                        mode='lines', line=dict(color='#F5C242', width=1.2),
                        showlegend=False,
                    ), row=3, col=1)
                    for lvl, clr in [(70,'rgba(242,54,69,0.55)'),(30,'rgba(8,153,129,0.55)')]:
                        fig.add_trace(go.Scatter(
                            x=[x_str[0], x_str[-1]], y=[lvl, lvl],
                            mode='lines', line=dict(color=clr, width=1, dash='dot'),
                            showlegend=False,
                        ), row=3, col=1)

                    # ── MACD ──────────────────────────────────────────────
                    macd_hist_clr = [inc_color if v >= 0 else dec_color
                                     for v in df_chart['MACD_hist']]
                    fig.add_trace(go.Bar(
                        x=x_str, y=df_chart['MACD_hist'],
                        marker_color=macd_hist_clr, showlegend=False,
                    ), row=4, col=1)
                    fig.add_trace(go.Scatter(
                        x=x_str, y=df_chart['MACD'],
                        mode='lines', line=dict(color='#2196f3', width=1.2),
                        showlegend=False,
                    ), row=4, col=1)
                    fig.add_trace(go.Scatter(
                        x=x_str, y=df_chart['MACD_signal'],
                        mode='lines', line=dict(color='#ff5252', width=1.2),
                        showlegend=False,
                    ), row=4, col=1)
                    fig.add_trace(go.Scatter(
                        x=[x_str[0], x_str[-1]], y=[0, 0],
                        mode='lines', line=dict(color=tv_border, width=1),
                        showlegend=False,
                    ), row=4, col=1)

                    # ── Tick labels: ambil ~8 titik merata ───────────────
                    step     = max(1, n_bars // 8)
                    tickvals = x_str[::step]

                    # ── Layout ────────────────────────────────────────────
                    ax_x = dict(
                        type='category',
                        showgrid=False,
                        showline=True, linecolor=tv_border, linewidth=1,
                        zeroline=False,
                        tickangle=-30,
                        tickfont=dict(size=10),
                        automargin=False,
                    )
                    ax_y_plain = dict(
                        showgrid=False,
                        showline=True, linecolor=tv_border, linewidth=1,
                        zeroline=False,
                        tickfont=dict(size=10),
                        type='linear',
                        side='right',
                        automargin=False,
                    )
                    ax_y_grid = dict(
                        showgrid=True, gridcolor=tv_border,
                        showline=True, linecolor=tv_border, linewidth=1,
                        zeroline=False,
                        tickfont=dict(size=10),
                        type='linear',
                        side='right',
                        automargin=False,
                    )
                    fig.update_layout(
                        template='plotly_dark' if is_dark else 'plotly_white',
                        plot_bgcolor=tv_bg_color,
                        paper_bgcolor=tv_bg_color,
                        font=dict(color=tv_text_color, size=11),
                        height=980,
                        showlegend=False,
                        barmode="stack",
                        margin=dict(l=0, r=120, t=10, b=40),
                        xaxis =dict(**ax_x, rangeslider=dict(visible=False),
                                    range=[-0.5, n_total-0.5], tickvals=tickvals),
                        xaxis2=dict(**ax_x, range=[-0.5, n_total-0.5], tickvals=tickvals, showticklabels=False),
                        xaxis3=dict(**ax_x, range=[-0.5, n_total-0.5], tickvals=tickvals, showticklabels=False),
                        xaxis4=dict(**ax_x, range=[-0.5, n_total-0.5], tickvals=tickvals),
                        yaxis =dict(**ax_y_plain, title=''),
                        yaxis2=dict(**ax_y_grid,  title='VOL'),
                        yaxis3=dict(**ax_y_grid,  title='RSI', range=[0, 100]),
                        yaxis4=dict(**ax_y_grid,  title='MACD'),
                    )

                    st.plotly_chart(fig, use_container_width=True)

                    # ── EMA Legend ────────────────────────────────────────
                    ema_items = [
                        ('#009dff','EMA 13 — Fast (Momentum)'),
                        ('#ff0000','EMA 21 — Signal'),
                        ('#cc00ff','EMA 100 — Mid Trend'),
                        ('#F5C242','EMA 200 — Major Trend'),
                    ]
                    leg = "<div style='display:flex;flex-wrap:wrap;gap:18px;padding:6px 4px;margin-top:-6px;'>"
                    for clr, lbl in ema_items:
                        leg += (f"<span style='display:flex;align-items:center;gap:6px;'>"
                                f"<span style='display:inline-block;width:28px;height:3px;"
                                f"background:{clr};border-radius:2px;'></span>"
                                f"<span style='font-family:IBM Plex Mono,monospace;font-size:0.72rem;"
                                f"color:{tv_text_color};'>{lbl}</span></span>")
                    leg += "</div>"
                    st.markdown(leg, unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Terjadi kesalahan saat menggambar chart: {e}")
            else:
                st.warning("Data grafik tidak ditemukan. Pastikan ticker valid di BEI dan jaringan internet stabil.")

# ── Executive Summary — di bawah chart, full width ───────────
            if run_analysis and ai_text_verdict:
                bg_card  = 'rgba(10,14,26,0.92)' if is_dark else '#f8fafc'
                bd_color = tv_border if not df_chart.empty else 'transparent'
                
                # Memastikan enter dari AI tidak terlalu lebar (maksimal 2 enter)
                verdict_clean = ai_text_verdict.replace('\n\n\n', '\n\n')
                
                # HTML ditulis rata kiri agar TIDAK dibaca sebagai code block oleh Streamlit
                html_str = f"""<div style="background:{bg_card}; border:1px solid {bd_color}; border-left:3px solid #F5C242; border-radius:0 8px 8px 0; padding:12px 16px; margin-top:14px; line-height:1.4; font-family:'IBM Plex Mono',monospace; overflow:visible; width:100%; box-sizing:border-box;">
<div style="font-size:0.65rem;letter-spacing:0.14em;color:#F5C242; font-weight:700;text-transform:uppercase;margin-bottom:6px; display:flex;align-items:center;gap:8px;">
📋 TRADE PLAN SIGMA
</div>
<div style="font-size:0.82rem;color:{'#c9d1d9' if is_dark else '#374151'}; white-space:pre-wrap;word-break:break-word;overflow-wrap:break-word;max-width:100%;">
{verdict_clean}
</div>
</div>"""

                st.markdown(html_str, unsafe_allow_html=True)
            elif not run_analysis:
                st.markdown(f"""
                <div class="trm-card" style="text-align:center; padding:40px 20px; margin-top:20px;">
                    <div style="font-family:'IBM Plex Mono',monospace;font-size:2rem;margin-bottom:12px;opacity:0.4;">&#9672;</div>
                    <p style="font-family:'IBM Plex Mono',monospace;font-size:0.72rem;letter-spacing:0.12em;text-transform:uppercase;color:{text_sub};margin:0;">
                        Masukkan kode saham dan klik <span style='color:#F5C242;'>Analyze with SIGMA</span> untuk memproses data teknikal, fundamental, dan volume &mdash; lalu menggambar Trade Plan otomatis di Chart.
                    </p>
                </div>
                """, unsafe_allow_html=True)

# ─────────────────────────────────────────────
# PART 11: AI REKOMENDASI (Daily / Weekly / BSJP)
# ─────────────────────────────────────────────
    with tab_reco:
        st.markdown("<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'>AI REKOMENDASI SIGMA</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)
        st.markdown(f"<p style='font-family:IBM Plex Mono,monospace;font-size:0.7rem;letter-spacing:0.08em;color:{text_sub};margin-bottom:20px;text-transform:uppercase;'>Rekomendasi AI otomatis &middot; Daily &middot; Weekly &middot; Beli Sore Jual Pagi &middot; Berbasis data live IDX</p>", unsafe_allow_html=True)

        reco_tab_daily, reco_tab_weekly, reco_tab_bsjp = st.tabs([
            "  📅 DAILY  ",
            "  📆 WEEKLY  ",
            "  🌙 BELI SORE JUAL PAGI  ",
        ])

        _WATCHLIST_RECO = [
            "BBCA","BBRI","BMRI","TLKM","ASII","BREN","GOTO","ANTM",
            "PGAS","KLBF","UNVR","ICBP","MDKA","INCO","ADRO","PTBA",
            "EXCL","SMGR","BSDE","CPIN","ITMG","TBIG","MTEL","ESSA"
        ]

        @st.cache_data(ttl=1800, show_spinner=False)
        def _reco_fetch_prices(tickers):
            result = {}
            for tk in tickers:
                try:
                    h = yf.Ticker(f"{tk}.JK").history(period="10d")
                    if len(h) >= 3:
                        closes = h["Close"].tolist()
                        vols   = h["Volume"].tolist()
                        result[tk] = {
                            "price":  round(closes[-1], 0),
                            "prev":   round(closes[-2], 0),
                            "high":   round(h["High"].iloc[-1], 0),
                            "low":    round(h["Low"].iloc[-1], 0),
                            "vol":    int(vols[-1]),
                            "vol5":   int(sum(vols[-5:]) / 5),
                            "chg":    round((closes[-1] - closes[-2]) / closes[-2] * 100, 2),
                            "chg2d":  round((closes[-1] - closes[-3]) / closes[-3] * 100, 2),
                        }
                except: pass
            return result

        def _call_ai_reco(prompt_text):
            try:
                result, _ = _call_groq_primary(prompt_text)
                return result
            except:
                try:
                    result, _ = _call_gemini_text([{"role":"user","content":prompt_text}])
                    return result
                except Exception as e:
                    return f"Gagal memanggil AI: {e}"

        def _render_reco_cards(reco_text, accent="#F5C242"):
            bg = "rgba(245,194,66,0.04)" if is_dark else "#fffbeb"
            border = "rgba(245,194,66,0.15)" if is_dark else "#f5c24240"
            st.markdown(f"""
            <div style="background:{bg};border:1px solid {border};border-left:3px solid {accent};
                        border-radius:0 8px 8px 0;padding:20px 20px;margin-top:12px;
                        font-size:0.88rem;color:{text_main};white-space:pre-wrap;
                        word-break:break-word;line-height:1.78;box-sizing:border-box;width:100%;overflow:visible;">
{reco_text}
            </div>""", unsafe_allow_html=True)

        # ── Shareholder summary untuk enrichment prompt ──────────────────
        def _sh_summary_for_reco():
            try:
                _db = get_manual_sh_db_outer()
                lines = []
                for tk, records in _db.items():
                    _df = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
                    if len(_df) >= 2:
                        last = int(_df["shareholders"].iloc[-1])
                        prev = int(_df["shareholders"].iloc[-2])
                        delta = last - prev
                        pct   = round(delta / prev * 100, 2)
                        trend = "naik" if delta > 0 else "turun"
                        lines.append(f"{tk}: {last:,} pemegang (Δ {delta:+,} = {pct:+.2f}% MoM — {trend})")
                return "\n".join(lines)
            except:
                return "Data shareholder tidak tersedia"

        # ─── TAB DAILY ────────────────────────────────────────────────────
        with reco_tab_daily:
            st.markdown("<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'>REKOMENDASI HARIAN</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)
            st.markdown(f"<p style='font-family:IBM Plex Mono,monospace;font-size:0.68rem;color:{text_sub};margin-bottom:16px;'>Top pick trading hari ini — berbasis momentum harga, volume spike, dan sinyal shareholder.</p>", unsafe_allow_html=True)

            col_d1, col_d2 = st.columns([3, 1])
            with col_d2:
                st.markdown("<br>", unsafe_allow_html=True)
                run_daily = st.button("▶ GENERATE DAILY", use_container_width=True, key="btn_daily")

            if run_daily:
                with st.spinner("SIGMA AI sedang menganalisis pasar untuk rekomendasi harian..."):
                    price_data = _reco_fetch_prices(_WATCHLIST_RECO)
                    sh_summary = _sh_summary_for_reco()
                    if price_data:
                        lines = []
                        for tk, d in price_data.items():
                            spike = d["vol"] / d["vol5"] if d["vol5"] > 0 else 1
                            lines.append(f"{tk}: Harga={d['price']:,.0f} | Chg={d['chg']:+.2f}% | Vol={d['vol']:,} | VolSpike={spike:.1f}x | High={d['high']:,.0f} | Low={d['low']:,.0f}")
                        market_snap = "\n".join(lines)
                        prompt = f"""Kamu adalah SIGMA AI, analis saham Indonesia profesional.

=== DATA HARGA & VOLUME (IDX Hari Ini) ===
{market_snap}

=== DATA PEMEGANG SAHAM (IDX Bulanan) ===
{sh_summary}

=== TUGAS ===
Pilih TOP 3-5 saham terbaik untuk trading HARIAN (intraday s/d 3 hari).

Kriteria pemilihan:
- Volume spike tinggi (tanda aksi institusi)
- Momentum positif atau potensi rebound teknikal
- Sinyal pemegang saham mendukung (naik = akumulasi retail)
- Risk/Reward minimal 1:2

Format output WAJIB per saham:
🎯 [TICKER] — Rp[Harga] | [Chg%]
📊 Alasan Teknikal: [volume, momentum, level kunci]
👥 Sinyal Pemegang: [naik/turun berapa, implikasinya]
⚡ Entry: Rp[harga] | SL: Rp[harga] | TP1: Rp[harga] | TP2: Rp[harga]
📐 R/R: [rasio] | Horizon: [X hari]
---
Bias pasar hari ini: [1 kalimat]
Jawab dalam Bahasa Indonesia. Jangan tambahkan JSON."""
                        _render_reco_cards(_call_ai_reco(prompt), "#F5C242")
                    else:
                        st.warning("Gagal mengambil data pasar. Coba lagi.")
            else:
                st.markdown(f"""<div class="trm-card" style="text-align:center;padding:32px 20px;">
                    <div style="font-size:2rem;opacity:0.3;margin-bottom:10px;">📅</div>
                    <p style="font-family:'IBM Plex Mono',monospace;font-size:0.72rem;letter-spacing:0.1em;text-transform:uppercase;color:{text_sub};margin:0;">
                        Klik <span style='color:#F5C242;'>Generate Daily</span> untuk top pick saham hari ini</p>
                </div>""", unsafe_allow_html=True)

        # ─── TAB WEEKLY ───────────────────────────────────────────────────
        with reco_tab_weekly:
            st.markdown("<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'>REKOMENDASI MINGGUAN</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)
            st.markdown(f"<p style='font-family:IBM Plex Mono,monospace;font-size:0.68rem;color:{text_sub};margin-bottom:16px;'>Swing trade 1-2 minggu — tren, katalis fundamental, dan tren pemegang saham.</p>", unsafe_allow_html=True)

            col_w1, col_w2 = st.columns([3, 1])
            with col_w2:
                st.markdown("<br>", unsafe_allow_html=True)
                run_weekly = st.button("▶ GENERATE WEEKLY", use_container_width=True, key="btn_weekly")

            if run_weekly:
                with st.spinner("SIGMA AI sedang menyusun rekomendasi mingguan..."):
                    price_data = _reco_fetch_prices(_WATCHLIST_RECO)
                    sh_summary = _sh_summary_for_reco()
                    if price_data:
                        lines = []
                        for tk, d in price_data.items():
                            lines.append(f"{tk}: Harga={d['price']:,.0f} | Chg2d={d['chg2d']:+.2f}% | Vol5avg={d['vol5']:,} | VolHari={d['vol']:,}")
                        market_snap = "\n".join(lines)
                        prompt = f"""Kamu adalah SIGMA AI, analis swing trading saham Indonesia.

=== DATA HARGA & VOLUME ===
{market_snap}

=== DATA PEMEGANG SAHAM (Tren Bulanan) ===
{sh_summary}

=== TUGAS ===
Pilih TOP 3-5 saham terbaik untuk SWING TRADE 1-2 minggu.

Kriteria:
- Tren harga konsisten (chg2d dan volume)
- Pemegang saham naik 1 atau 3 bulan = sinyal positif
- Fundamental sektor mendukung
- Ada potensi breakout atau rebound dari support

Format output per saham:
🎯 [TICKER] — Rp[Harga]
📊 Tesis Teknikal: [tren, support/resistance, pola]
🏢 Fundamental: [valuasi, katalis, posisi sektor]
👥 Tren Pemegang: [naik/turun, implikasi akumulasi/distribusi]
📈 Skenario: Entry Rp[harga] | SL Rp[harga] | TP1 Rp[harga] | TP2 Rp[harga]
📐 R/R: [rasio] | Horizon: [X minggu] | Sizing: [% portofolio]
---
Outlook pasar minggu ini: [2-3 kalimat]
Jawab dalam Bahasa Indonesia. Jangan tambahkan JSON."""
                        _render_reco_cards(_call_ai_reco(prompt), "#26a69a")
                    else:
                        st.warning("Gagal mengambil data pasar. Coba lagi.")
            else:
                st.markdown(f"""<div class="trm-card" style="text-align:center;padding:32px 20px;">
                    <div style="font-size:2rem;opacity:0.3;margin-bottom:10px;">📆</div>
                    <p style="font-family:'IBM Plex Mono',monospace;font-size:0.72rem;letter-spacing:0.1em;text-transform:uppercase;color:{text_sub};margin:0;">
                        Klik <span style='color:#26a69a;'>Generate Weekly</span> untuk top pick swing trade minggu ini</p>
                </div>""", unsafe_allow_html=True)

        # ─── TAB BSJP ─────────────────────────────────────────────────────
        with reco_tab_bsjp:
            st.markdown("<div class='trm-section'><div class='trm-section-line'></div><span class='trm-section-label'>BELI SORE JUAL PAGI (BSJP)</span><div class='trm-section-line'></div></div>", unsafe_allow_html=True)
            st.markdown(f"<p style='font-family:IBM Plex Mono,monospace;font-size:0.68rem;color:{text_sub};margin-bottom:8px;'>Strategi overnight — beli menjelang penutupan BEI (15:00–15:50 WIB), jual di pre-opening atau sesi 1 besok pagi.</p>", unsafe_allow_html=True)
            st.markdown(f"""<div class="trm-insight" style="margin-bottom:16px;">
⚠️ <b>Disclaimer BSJP:</b> Strategi ini memanfaatkan gap-up overnight dan momentum pembukaan.
Risiko utama: berita negatif semalam bisa sebabkan gap-down. Selalu pasang <b>SL ketat</b>
dan gunakan sizing kecil (maks 5–10% portofolio per posisi).
</div>""", unsafe_allow_html=True)

            col_b1, col_b2 = st.columns([3, 1])
            with col_b2:
                st.markdown("<br>", unsafe_allow_html=True)
                run_bsjp = st.button("▶ GENERATE BSJP", use_container_width=True, key="btn_bsjp")

            if run_bsjp:
                with st.spinner("SIGMA AI sedang mencari kandidat BSJP..."):
                    price_data = _reco_fetch_prices(_WATCHLIST_RECO)
                    sh_summary = _sh_summary_for_reco()
                    if price_data:
                        lines = []
                        for tk, d in price_data.items():
                            spike = d["vol"] / d["vol5"] if d["vol5"] > 0 else 1
                            lines.append(f"{tk}: Harga={d['price']:,.0f} | Chg={d['chg']:+.2f}% | VolSpike={spike:.1f}x | High={d['high']:,.0f} | Low={d['low']:,.0f}")
                        market_snap = "\n".join(lines)
                        prompt = f"""Kamu adalah SIGMA AI, spesialis strategi overnight trading IDX (BSJP).

=== DATA SNAPSHOT PASAR SORE INI ===
{market_snap}

=== DATA PEMEGANG SAHAM ===
{sh_summary}

=== TUGAS ===
Pilih TOP 2-3 saham terbaik untuk strategi BSJP (beli sore ini, jual pagi besok).

Kriteria BSJP ideal:
- Volume spike sore (tanda akumulasi institusi menjelang closing)
- Harga menutup di atas high beberapa hari sebelumnya
- Pemegang saham naik = sinyal positif tambahan
- Likuid (bisa exit cepat pagi hari)
- Tidak sedang dalam tren turun kuat

Format output per saham:
🌙 [TICKER] — Beli ~Rp[harga] sore ini
📊 Sinyal Teknikal: [volume spike, posisi harga, momentum]
👥 Konfirmasi Pemegang: [naik/turun, sinyal]
⚡ Eksekusi: Beli di Rp[range] menjelang closing | SL pagi jika buka di bawah Rp[harga]
🎯 Target pagi: Rp[harga] | Potensi: +[X]% overnight
---
Kondisi BSJP malam ini: [KONDUSIF / WAIT] — [1 kalimat alasan]
Jawab dalam Bahasa Indonesia. Jangan tambahkan JSON."""
                        _render_reco_cards(_call_ai_reco(prompt), "#7c3aed")
                    else:
                        st.warning("Gagal mengambil data pasar. Coba lagi.")
            else:
                st.markdown(f"""<div class="trm-card" style="text-align:center;padding:32px 20px;">
                    <div style="font-size:2rem;opacity:0.3;margin-bottom:10px;">🌙</div>
                    <p style="font-family:'IBM Plex Mono',monospace;font-size:0.72rem;letter-spacing:0.1em;text-transform:uppercase;color:{text_sub};margin:0;">
                        Klik <span style='color:#7c3aed;'>Generate BSJP</span> untuk kandidat overnight trade malam ini</p>
                </div>""", unsafe_allow_html=True)

        st.markdown("<hr class='fancy-divider'>", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# PART 10: RUANG CHAT AI 
# ─────────────────────────────────────────────
else:
    if not active["messages"][1:]:
        uname = user.get("name", "").split()[0] if user.get("name") else "Trader"
        st.markdown(f"""
        <div style="text-align:center;padding:10vh 0 2rem;">
            <h1 style="margin:0;font-size:1.8rem;font-weight:700;color:{C['text']};">Halo, {uname} &#128075;</h1>
            <p style="margin:8px 0 0;color:{C['text_muted']};font-size:0.9rem;">Halo! Saya SIGMA, asisten cerdas KIPM Universitas Pancasila. Ada yang bisa saya bantu hari ini?
            Jika Anda ingin menganalisa saham atau topik tertentu, Anda bisa ketik "7 Alpha" untuk melihat menu panduan saya.&#128522;</p>
        </div>
        """, unsafe_allow_html=True)

    if st.session_state.get("last_error"):
        st.error(f"[!] {st.session_state['last_error']}")
        st.session_state["last_error"] = None

    for i, msg in enumerate(active["messages"][1:]):
        with st.chat_message(msg["role"]):
            display = msg.get("display") or msg["content"]
            if "Pertanyaan:" in display: display = display.split("Pertanyaan:")[-1].strip()
            for tag in ["[/DATA GLOBAL]", "[/DATA PASAR IDX]", "[/DATA PASAR]"]:
                if tag in display: display = display.split(tag)[-1].strip()
            
            display_clean = re.sub(r'\n\n\*\([✨⚡].*?\)\*', '', display)
            display_clean = re.sub(r'\n\n\([✨⚡].*?\)', '', display_clean)
            
            if msg["role"] == "user":
                imgs_in_msg = msg.get("images", [])
                if imgs_in_msg:
                    if len(imgs_in_msg) == 1: st.markdown(f'<img src="data:{imgs_in_msg[0][1]};base64,{imgs_in_msg[0][0]}" style="max-width:100%;max-height:240px;border-radius:10px;margin-bottom:6px;display:block;">', unsafe_allow_html=True)
                    else:
                        imgs_html = ''.join([f'<img src="data:{imime};base64,{ib64}" style="height:160px;max-width:calc(100%/{len(imgs_in_msg)});object-fit:cover;border-radius:8px;flex:1;">' for ib64, imime in imgs_in_msg])
                        st.markdown(f'<div style="display:flex;gap:4px;margin-bottom:6px;">{imgs_html}</div>', unsafe_allow_html=True)
                elif msg.get("img_b64"): st.markdown(f'<img src="data:{msg.get("img_mime","image/jpeg")};base64,{msg["img_b64"]}" style="max-width:100%;max-height:240px;border-radius:10px;margin-bottom:6px;display:block;">', unsafe_allow_html=True)
            st.markdown(display_clean)

    try: result = st.chat_input("Tanya SIGMA... DYOR - bukan financial advice.", accept_file="multiple")
    except TypeError: result = st.chat_input("Tanya SIGMA...")

    prompt = None; file_obj = None; multi_images = []

    if result is not None:
        st.session_state.img_data = None; st.session_state.pdf_data = None
        if hasattr(result, 'text'):
            prompt = (result.text or "").strip()
            files = getattr(result, 'files', None) or []
            img_files = [f for f in files if f.type != "application/pdf"]
            pdf_files = [f for f in files if f.type == "application/pdf"]
            if img_files:
                for _mf in img_files[:5]:
                    try: 
                        b64_img, mime_img = _compress_image_file(_mf)
                        multi_images.append((b64_img, mime_img, _mf.name))
                    except: pass
                if multi_images: st.session_state.img_data = (multi_images[0][0], multi_images[0][1], multi_images[0][2])
            if pdf_files: file_obj = pdf_files[0]
        elif isinstance(result, str): prompt = result.strip()

        if not prompt and (file_obj or st.session_state.img_data or st.session_state.pdf_data):
            if file_obj or st.session_state.pdf_data:
                prompt = "Tolong analisa file yang saya kirim"
            else:
                prompt = "5. Teknikal saham di gambar ini"

        if prompt and prompt.strip().lower() in ["7 alpha", "tujuh alpha", "7alpha", "7 logic", "tujuh sila", "7sila", "5 logic", "lima sila", "5sila"]:
            active = next((s for s in st.session_state.sessions if s["id"] == st.session_state.active_id), None)
            if active:
                menu_text = """**&#127775; 7 ALPHA SIGMA &mdash; PANDUAN & MENU UTAMA &#127775;**\n\n**1. Kesimpulan Dampak Makro [topik/berita]**\n&#8627; *Sistem otomatis melacak info & sentimen global/domestik terupdate. Menilai dampaknya ke ekonomi RI, IHSG, dan masyarakat. (Tidak butuh data dari user).*\n\n**2. Kesimpulan Dampak [emiten]**\n&#8627; *Sistem otomatis melacak korelasi sentimen/berita spesifik terhadap kinerja dan harga saham emiten yang direquest. (Tidak butuh data dari user).*\n\n**3. Bandarmologi [emiten]**\n&#8627; &#9888; *WAJIB LAMPIRKAN: Screenshot Broker Summary (Brosum), Price Table/Frekuensi, dan Volume. Sistem akan membedah jejak akumulasi/distribusi bandar.*\n\n**4. Fundamental [emiten]**\n&#8627; *Sistem otomatis menarik data keuangan & valuasi emiten dari sumber terpercaya secara real-time. (Tidak butuh data dari user).*\n\n**5. Teknikal [emiten]**\n&#8627; &#9888; *WAJIB LAMPIRKAN: Screenshot Chart (disarankan pakai indikator MnM Strategy+). Pastikan terlihat indikator Volume & Momentum (Stochastic/RSI/MACD bebas pilih). Disarankan Timeframe besar (Daily/Weekly) agar sinyal kuat & minim false breakout.*\n\n**6. Analisa Lengkap [emiten] (Quad Confluence)**\n&#8627; &#9888; *WAJIB LAMPIRKAN: Screenshot Chart Teknikal + SS Broker Summary. Sistem akan menggabungkan data user dengan data Fundamental & Makro otomatis untuk mencari "Triple/Quad Confluence".*\n\n**7. Analisa IPO [emiten]**\n&#8627; &#9888; *WAJIB LAMPIRKAN: File PDF Prospektus e-IPO emiten terkait. Sistem akan membedah tujuan dana, valuasi, dan track record underwriter.*\n\n&#128161; **Cara Pakai:** Ketik angkanya atau perintahnya. \nContoh: **"6. Analisa Lengkap BRMS"** (sambil upload/paste SS Chart dan SS Brosum bersamaan)."""
                
                active["messages"].append({"role": "user", "content": "7 Alpha", "display": "7 Alpha"})
                active["messages"].append({"role": "assistant", "content": menu_text})
                with st.chat_message("user"): st.markdown("7 Alpha")
                with st.chat_message("assistant"): st.markdown(menu_text)
                st.rerun()

        if file_obj:
            raw = file_obj.read()
            if file_obj.type == "application/pdf":
                try:
                    import fitz
                    doc = fitz.open(stream=raw, filetype="pdf")
                    txt = "".join(p.get_text() for p in doc)
                    pdf_content = f"[PDF: {file_obj.name}]\n{txt[:12000]}"
                    st.session_state.pdf_data = (pdf_content, file_obj.name)
                    st.session_state.img_data = None
                except Exception as pdf_e:
                    st.error(f"[!] Gagal membaca PDF: {str(pdf_e)}")
                    st.session_state.pdf_data = None
            else:
                if not multi_images: st.session_state.img_data = (base64.b64encode(raw).decode(), "image/png" if file_obj.name.endswith(".png") else "image/jpeg", file_obj.name)
                st.session_state.pdf_data = None

        if not prompt and (file_obj or st.session_state.img_data or st.session_state.pdf_data): prompt = "Tolong analisa file yang saya kirim"

    if prompt:
        img_data = st.session_state.img_data; pdf_data = st.session_state.pdf_data
        st.session_state.img_data = None; st.session_state.pdf_data = None
        full_prompt = prompt

        prompt_lower = prompt.lower()
        
        emiten_match = re.search(r'\b[A-Z]{4}\b', prompt.upper())

        is_dampak_makro  = prompt_lower.startswith("1.") or "dampak makro" in prompt_lower or ("kesimpulan dampak" in prompt_lower and not emiten_match)
        is_dampak_emiten = prompt_lower.startswith("2.") or ("kesimpulan dampak" in prompt_lower and bool(emiten_match))
        is_bandarmologi  = prompt_lower.startswith("3.") or "bandarmologi" in prompt_lower or ("broker summary" in prompt_lower)
        is_fundamental   = prompt_lower.startswith("4.") or "fundamental" in prompt_lower
        is_teknikal      = prompt_lower.startswith("5.") or "teknikal" in prompt_lower
        is_lengkap       = prompt_lower.startswith("6.") or "analisa lengkap" in prompt_lower or (prompt_lower.startswith("7 alpha ") and len(prompt_lower.split()) > 2)
        is_ipo           = prompt_lower.startswith("7.") or "analisa ipo" in prompt_lower
        
        if is_dampak_makro:
            with st.spinner("Menganalisa sentimen makro global/domestik..."):
                try:
                    ctx = build_global_context(prompt)
                    if ctx: full_prompt = f"[BERITA GLOBAL/EKONOMI]:\n{ctx}\n\n"
                    else: full_prompt = ""
                except: full_prompt = ""
                full_prompt += TEMPLATE_DAMPAK_MAKRO
                full_prompt += f"\n\nPertanyaan Asli User (Topik yang dibahas): {prompt}"

        elif is_dampak_emiten and emiten_match:
            emiten_target = emiten_match.group(0).upper()
            with st.spinner(f"Menganalisa korelasi berita ke emiten {emiten_target}..."):
                try:
                    ctx = build_combined_context(prompt)
                    if ctx: full_prompt = f"[DATA BERITA DAN PASAR]:\n{ctx}\n\n"
                    else: full_prompt = ""
                except: full_prompt = ""
                full_prompt += TEMPLATE_DAMPAK_EMITEN.format(emiten=emiten_target)
                full_prompt += f"\n\nPertanyaan Asli User: {prompt}"

        elif is_bandarmologi:
            emiten_target = emiten_match.group(0).upper() if emiten_match else "SAHAM INI"
            with st.spinner(f"Melacak Jejak Uang & Aliran Dana Bandar di {emiten_target}..."):
                full_prompt = TEMPLATE_BANDARMOLOGI.format(emiten=emiten_target)
                full_prompt += f"\n\n[PENTING: Fokus 100% pada data Broker Summary, Average Price, dan Volume. JANGAN bahas indikator teknikal (RSI/MACD) atau Fundamental!]\nPertanyaan Asli User: {prompt}"

        elif is_fundamental and emiten_match:
            emiten_target = emiten_match.group(0).upper()
            is_bank = emiten_target in BANK_TICKERS
            chosen_template = TEMPLATE_BANK if is_bank else TEMPLATE_NON_BANK
            tahun_sekarang = datetime.now().year
            
            with st.spinner(f"Kalkulasi & Tarik Data Multi-Sumber {emiten_target}..."):
                try:
                    fund_text = build_fundamental_from_text(f"fundamental {emiten_target}")
                except:
                    fund_text = "Data gagal ditarik."
                
                full_prompt = chosen_template.format(emiten=emiten_target, sumber="Multi-Source + Kalkulasi Manual", data_raw=fund_text, tahun=tahun_sekarang)
                full_prompt += f"\n\nPertanyaan Tambahan User: {prompt}"

        elif is_teknikal:
            emiten_target = emiten_match.group(0).upper() if emiten_match else "SAHAM INI"
            if img_data or multi_images:
                with st.spinner(f"Membaca Chart & Merancang 3 Skenario Trade Plan..."):
                    full_prompt = TEMPLATE_TEKNIKAL.format(emiten=emiten_target)
            else:
                full_prompt = TEMPLATE_TEKNIKAL.format(emiten=emiten_target)
                full_prompt += f"\n\n[PENTING: User TIDAK mengirimkan gambar chart. Lakukan estimasi level support/resistance dan plan trading menggunakan data harga yang kamu punya.]"

        elif is_lengkap and emiten_match:
            emiten_target = emiten_match.group(0).upper()
            with st.spinner(f"Memproses Quad Confluence (Bandar + Teknikal + Funda + Makro) untuk {emiten_target}..."):
                try:
                    fund_text = build_fundamental_from_text(f"fundamental {emiten_target}")
                except:
                    fund_text = "Data fundamental gagal ditarik secara live, gunakan estimasi dari knowledge base."
                
                full_prompt = TEMPLATE_LENGKAP.format(emiten=emiten_target, data_raw=fund_text)
                full_prompt += f"\n\n[PENTING: Gunakan gambar chart & data Broker Summary yang dilampirkan user! Cari Divergence!]\nPertanyaan Asli User: {prompt}"

        elif is_ipo:
            if pdf_data:
                emiten_target = emiten_match.group(0).upper() if emiten_match else "CALON EMITEN BARU"
                with st.spinner("Membongkar & Membaca Ratusan Halaman Prospektus IPO..."):
                    full_prompt = TEMPLATE_IPO.format(emiten=emiten_target, pdf_content=pdf_data[0])
            else:
                full_prompt = "[INSTRUKSI SYSTEM]: Beritahu user dengan ramah bahwa untuk melakukan Analisa IPO, mereka WAJIB meng-upload atau melampirkan file PDF Prospektus e-IPO terlebih dahulu ke dalam kolom chat."

        elif pdf_data and (img_data or multi_images): full_prompt = f"{pdf_data[0]}\n\nPertanyaan: {prompt}"
        elif pdf_data: full_prompt = f"{pdf_data[0]}\n\nPertanyaan: {prompt}"
        elif img_data: full_prompt = f"[Gambar: {img_data[2]}]\n\nPertanyaan: {prompt}"
        else:
            full_prompt = prompt
            try:
                ctx = build_combined_context(prompt)
                if ctx: full_prompt = f"{ctx}\n\n{prompt}"
            except: pass

        if active["title"] == "Obrolan Baru": active["title"] = prompt[:40] + ("..." if len(prompt) > 40 else "")

        user_msg = {"role": "user", "content": full_prompt, "display": prompt}
        if multi_images:
            user_msg["images"] = [(b64, mime) for b64, mime, name in multi_images[:5]]
            user_msg["img_b64"] = multi_images[0][0]; user_msg["img_mime"] = multi_images[0][1]
        elif img_data:
            user_msg["img_b64"] = img_data[0]; user_msg["img_mime"] = img_data[1]

        active["messages"].append(user_msg)

        with st.chat_message("user"):
            imgs_to_show = multi_images[:5] if multi_images else ([(img_data[0], img_data[1], img_data[2])] if img_data else [])
            if imgs_to_show:
                if len(imgs_to_show) == 1: st.markdown(f'<img src="data:{imgs_to_show[0][1]};base64,{imgs_to_show[0][0]}" style="max-width:100%;max-height:240px;border-radius:10px;margin-bottom:6px;display:block;">', unsafe_allow_html=True)
                else:
                    imgs_html = ''.join([f'<img src="data:{_imime};base64,{_ib64}" style="height:160px;max-width:calc(100%/{len(imgs_to_show)});object-fit:cover;border-radius:8px;flex:1;">' for _ib64, _imime, _iname in imgs_to_show])
                    st.markdown(f'<div style="display:flex;gap:4px;margin-bottom:6px;">{imgs_html}</div>', unsafe_allow_html=True)
            if pdf_data: st.markdown(f'&#128196; **{pdf_data[1]}**', unsafe_allow_html=False)
            
            display_prompt = prompt if prompt != "5. Teknikal saham di gambar ini" else "Tolong buatkan Trade Plan dari chart ini."
            st.markdown(display_prompt)

        try:
            with st.chat_message("assistant"):
                with st.spinner("SIGMA menganalisis..."):

                    _history_msgs = [
                        {"role": m["role"], "content": m.get("content") or ""}
                        for m in active["messages"]
                        if m.get("role") in ("user", "assistant")
                    ]

                    ans_bersih = None
                    simbol_ai  = ""
                    has_image  = bool(multi_images or img_data)
                    has_pdf    = bool(pdf_data)
                    debug_info = []

                    if has_image:
                        try:
                            _img_b64  = user_msg.get("img_b64")
                            _img_mime = user_msg.get("img_mime")
                            ans_bersih, _ = _call_gemini_vision(prompt, _img_b64, _img_mime, multi_images)
                            simbol_ai = "\n\n*(&#10024; Gemini Vision)*"
                        except Exception as e_vision:
                            debug_info.append(f"Gemini Vision: {str(e_vision)}")
                            ans_bersih = (
                                "[!] Sistem analisa gambar sedang tidak merespons. "
                                "Silakan upload ulang gambarnya atau coba lagi dalam beberapa saat."
                                f"\n\n`Debug: {str(e_vision)[:200]}`"
                            )

                    elif has_pdf and not has_image:
                        try:
                            ans_bersih, _ = _call_gemini_text(
                                _history_msgs[-6:] + [{"role": "user", "content": full_prompt}]
                            )
                            simbol_ai = "\n\n*(&#10024; Gemini - PDF Mode)*"
                        except Exception as e_pdf:
                            debug_info.append(f"Gemini PDF: {str(e_pdf)}")
                            try:
                                ans_bersih, _ = _call_groq_primary(full_prompt, _history_msgs)
                                simbol_ai = "\n\n*(&#9889; Groq - PDF Fallback)*"
                            except Exception as e_groq_pdf:
                                debug_info.append(f"Groq PDF fallback: {str(e_groq_pdf)}")

                    else:
                        try:
                            ans_bersih, _ = _call_groq_primary(full_prompt, _history_msgs)
                            simbol_ai = "\n\n*(&#9889; Groq/Llama)*"
                        except Exception as e_groq70:
                            debug_info.append(f"Groq 70B: {str(e_groq70)}")

                            try:
                                ans_bersih, _ = _call_gemini_text(_history_msgs[-6:])
                                simbol_ai = "\n\n*(&#10024; Gemini)*"
                            except Exception as e_gemini:
                                debug_info.append(f"Gemini Text: {str(e_gemini)}")

                                try:
                                    ans_bersih, _ = _call_groq_fallback(full_prompt)
                                    simbol_ai = "\n\n*(&#9889; Groq/Mini)*"
                                except Exception as e_groq8:
                                    debug_info.append(f"Groq 8B: {str(e_groq8)}")

                    if not ans_bersih:
                        err_summary = " | ".join(debug_info)
                        ans_bersih = (
                            "[!] Semua sistem AI sedang sibuk atau mengalami gangguan. "
                            "Mohon coba lagi dalam 1-2 menit.\n\n"
                            f"`Log: {err_summary}`"
                        )
                        simbol_ai = ""

                    st.markdown(ans_bersih + simbol_ai)

            active["messages"].append({"role": "assistant", "content": ans_bersih + simbol_ai})
        except Exception as e:
            st.session_state["last_error"] = str(e)
            st.error(f"[!] {str(e)}")
        st.rerun()

if user:
    sessions_to_save = [{"id": s["id"], "title": s["title"], "created": s["created"], "messages": [dict(m) for m in s["messages"] if m["role"] != "system"]} for s in st.session_state.sessions]
    
    save_user(user["email"], {
        "theme": st.session_state.get("theme", "dark"), 
        "sessions": sessions_to_save, 
        "active_id": st.session_state.active_id,
        "current_view": st.session_state.get("current_view", "chat"), "selected_system": st.session_state.get("selected_system", "chat")
    })

_new_token = st.session_state.pop("new_token", None)
if _new_token: components.html(f"<script>try {{ localStorage.setItem('sigma_token', '{_new_token}'); }} catch(e) {{}}</script>", height=0)
if st.session_state.user is None: components.html("<script>(function() { try { var token = localStorage.getItem('sigma_token'); if (token) { var url = window.parent.location.href.split('?')[0]; window.parent.location.replace(url + '?sigma_token=' + token); } } catch(e) {} })();</script>", height=0)

components.html(f"""
<script>
(function(){{
var pd=window.parent.document;
var kipmLogo = pd.getElementById('kipm-mobile-logo'); if (kipmLogo) kipmLogo.style.display = 'none !important';
var kipmStyle = pd.getElementById('kipm-mobile-logo-style'); if (kipmStyle) kipmStyle.remove();
['spbtn','spmenu','sphist','spui','sigma-mobile-css'].forEach(function(id){{ var el=pd.getElementById(id); if(el) el.remove(); }});
var s=pd.createElement('style'); s.id='sigma-mobile-css';
s.textContent=`
#spbtn{{position:fixed;bottom:20px;left:20px;width:50px;height:50px;border-radius:50%; background:{C["sidebar_bg"]};color:{C["text"]};border:1px solid {C["border"]}; cursor:pointer;z-index:999999; display:flex;align-items:center;justify-content:center; box-shadow:0 6px 20px rgba(0,0,0,0.5);padding:0;transition:transform 0.2s, background 0.2s;}} 
#spbtn:hover{{transform:scale(1.08); background:{C["hover"]};}}
#spmenu,#sphist{{position:fixed;left:20px;bottom:85px; background:{C["sidebar_bg"]};border:1px solid {C["border"]}; border-radius:16px;box-shadow:0 -4px 24px rgba(0,0,0,0.5); z-index:999998;display:none;overflow:hidden;min-width:260px;}} 
#sphist{{max-height:55vh;overflow-y:auto;}}
.smi{{display:flex;align-items:center;gap:14px;padding:13px 18px; font-size:1rem;color:{C["text"]};cursor:pointer;border:none; background:transparent;width:100%;text-align:left;text-decoration:none;transition:background 0.2s;}} .smi:hover{{background:{C["hover"]}}}
.smico{{width:32px;height:32px;border-radius:8px;display:flex; align-items:center;justify-content:center;font-size:16px; background:{C["hover"]};flex-shrink:0;}}
.smsp{{border:none;border-top:1px solid {C["border"]};margin:4px 0;}} .smhd{{padding:8px 18px 4px;font-size:0.68rem;color:{C["text_muted"]}; font-weight:600;letter-spacing:1px;}} .smred{{color:#f55!important}}
`; pd.head.appendChild(s);
var btn=pd.createElement('button'); btn.id='spbtn'; btn.innerHTML='<svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2.5"/><circle cx="12" cy="12" r="2.5"/><circle cx="12" cy="19" r="2.5"/></svg>'; pd.body.appendChild(btn);
var m=pd.createElement('div');m.id='spmenu';
m.innerHTML=`
    <a class="smi" id="smi-new"><span class="smico">&#9998;</span>Percakapan Baru</a>
    <button class="smi" id="smi-hist"><span class="smico">&#9776;</span>History</button>
    <div class="smsp"></div><div class="smhd">NAVIGASI</div>
    <a class="smi" id="smi-home"><span class="smico">&#127968;</span>Kembali ke Home</a>
    <div class="smsp"></div><div class="smhd">PENAMPILAN</div>
    <a class="smi" id="smi-dark"><span class="smico">&#127183;</span>Dark Mode {'✓' if st.session_state.theme=='dark' else ''}</a>
    <a class="smi" id="smi-light"><span class="smico">&#9728;</span>Light Mode {'✓' if st.session_state.theme=='light' else ''}</a>
    <div class="smsp"></div><a class="smi smred" id="smi-out"><span class="smico">&#128682;</span>Sign Out</a>
`; pd.body.appendChild(m);
var h=pd.createElement('div');h.id='sphist'; h.innerHTML='<div class="smhd">RIWAYAT OBROLAN</div>';
{_hist_items} pd.body.appendChild(h);
btn.onclick=function(e){{ e.preventDefault(); e.stopPropagation(); m.style.display = (m.style.display === 'block') ? 'none' : 'block'; h.style.display = 'none'; }};
(function(){{
    var u; u=new URL(window.parent.location.href); u.searchParams.set('do','newchat'); pd.getElementById('smi-new').href=u.toString();
    pd.getElementById('smi-hist').onclick=function(){{m.style.display='none';h.style.display='block';}};
    u=new URL(window.parent.location.href); u.searchParams.set('do','go_home'); pd.getElementById('smi-home').href=u.toString();
    u=new URL(window.parent.location.href); u.searchParams.set('do','theme_dark'); pd.getElementById('smi-dark').href=u.toString();
    u=new URL(window.parent.location.href); u.searchParams.set('do','theme_light'); pd.getElementById('smi-light').href=u.toString();
    u=new URL(window.parent.location.href); u.searchParams.delete('sigma_token'); u.searchParams.set('do','logout'); pd.getElementById('smi-out').href=u.toString();
}})();
pd.addEventListener('click',function(e){{ if(!btn.contains(e.target) && !m.contains(e.target)) m.style.display='none'; if(!btn.contains(e.target) && !h.contains(e.target) && !m.contains(e.target)) h.style.display='none'; }});
}})();
</script>
""", height=0)

components.html("""
<script>
(function() {
    function injectPastePolyfill() {
        var doc = window.parent.document;
        var textarea = doc.querySelector('textarea[data-testid="stChatInputTextArea"]');
        var fileInput = doc.querySelector('[data-testid="stChatInput"] input[type="file"]');
        
        if (textarea && fileInput && !textarea.dataset.pastePolyfill) {
            textarea.dataset.pastePolyfill = "true";
            
            textarea.addEventListener('paste', function(e) {
                if (e.clipboardData && e.clipboardData.items) {
                    var items = e.clipboardData.items;
                    var dt = new DataTransfer();
                    var hasNewImage = false;
                    
                    if (fileInput.files) {
                        for (var i=0; i<fileInput.files.length; i++) {
                            dt.items.add(fileInput.files[i]);
                        }
                    }
                    
                    for (var i=0; i<items.length; i++) {
                        if (items[i].type.indexOf('image') !== -1) {
                            var file = items[i].getAsFile();
                            var newFile = new File([file], "image_paste_" + Date.now() + ".png", {type: "image/png"});
                            dt.items.add(newFile);
                            hasNewImage = true;
                        }
                    }
                    
                    if (hasNewImage) {
                        e.preventDefault();
                        fileInput.files = dt.files;
                        fileInput.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            });
        }
    }
    setInterval(injectPastePolyfill, 1000);
})();
</script>
""", height=0)

sig_color = C.get("text", "#ffffff")
js_code = """
<script>
(function() {
    var pd = window.parent.document;
    if (pd.getElementById('sigma-desktop-brand')) return;
    
    var brand = pd.createElement('div');
    brand.id = 'sigma-desktop-brand';
    
    brand.innerHTML = 'SIGMA';
    brand.style.cssText = 'position:fixed; top:24px; left:28px; z-index:999999; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; font-weight: 600; font-size: 1.25rem; color: """ + sig_color + """; letter-spacing: 0.2px; user-select: none; cursor: default;';
    
    var style = pd.createElement('style');
    style.innerHTML = '@media (max-width: 768px) { #sigma-desktop-brand { top: 16px !important; left: 20px !important; font-size: 1.15rem !important; } }';
    pd.head.appendChild(style);
    
    pd.body.appendChild(brand);
})();
</script>
"""
components.html(js_code, height=0)
