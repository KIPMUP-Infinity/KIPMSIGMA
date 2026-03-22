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

def build_fundamental_from_text(prompt):
    """
    Untuk perintah teks seperti 'analisa fundamental BBNI' tanpa PDF.
    Deteksi ticker → fetch yfinance → hitung CAGR → proyeksi 3 tahun.
    """
    ticker = detect_ticker_from_prompt(prompt)
    if not ticker:
        return ""
    import threading
    result = [""]
    def fetch():
        try:
            import yfinance as yf
            t = yf.Ticker(f"{ticker}.JK")
            info = t.info
            hist_price = t.history(period="5d")
            current_year = datetime.now().year
            lines = [f"=== DATA FUNDAMENTAL {ticker} ===",
                     f"Tahun sekarang: {current_year}"]

            # ── Harga & valuasi live ──
            price = round(hist_price.iloc[-1]["Close"], 0) if not hist_price.empty else None
            eps_yf = info.get("trailingEps")
            bv_yf  = info.get("bookValue")
            pe_yf  = info.get("trailingPE")
            pbv_yf = info.get("priceToBook")
            shares = info.get("sharesOutstanding")
            div_yield = info.get("dividendYield")

            if price:
                lines.append(f"Harga Saham    : Rp{price:,.0f}")
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
            try:
                inc = t.income_stmt
                if inc is None or inc.empty:
                    inc = t.financials
                if inc is not None and not inc.empty:
                    lines.append("\n── Historis Keuangan ──")
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
                    if "Total Revenue" in inc.index:
                        row = inc.loc["Total Revenue"].dropna()
                        cols = sorted(row.index, reverse=True)[:4]
                        vals_str = [f"{str(col)[:4]}: Rp{row[col]/1e12:.1f}T" for col in cols]
                        lines.append("Pendapatan     : " + " | ".join(vals_str))
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
                lines.append(f"\nProyeksi (basis growth {growth*100:.1f}%/tahun):")
                for i in range(1, 4):
                    yr = current_year + i
                    proj_eps = base_eps * (1 + growth) ** i
                    proj_ni  = (base_ni * (1 + growth) ** i / 1e12) if base_ni else None
                    # Target harga: konservatif (PER-20%), moderat (PER), optimis (PER+20%)
                    t_konservatif = proj_eps * per_base * 0.8
                    t_moderat     = proj_eps * per_base
                    t_optimis     = proj_eps * per_base * 1.2
                    ni_str = f" | Laba ~Rp{proj_ni:.1f}T" if proj_ni else ""
                    lines.append(f"  {yr}: EPS ~Rp{proj_eps:,.0f}{ni_str}")
                    lines.append(f"        Target: Konservatif Rp{t_konservatif:,.0f} | Moderat Rp{t_moderat:,.0f} | Optimis Rp{t_optimis:,.0f}")

            lines.append(f"\nCATATAN: Data yfinance IDX sering hanya sampai 2022-2023.")
            lines.append(f"Estimasi {current_year-1}→{current_year} dari knowledge model.")
            lines.append(f"Buat analisa FORMAT ANALISA FUNDAMENTAL lengkap untuk {ticker}.")
            lines.append(f"Tren 3 tahun aktual: {current_year-2}→{current_year-1}→{current_year}")
            lines.append("=== AKHIR DATA ===")
            result[0] = "\n".join(lines)
        except Exception as e:
            result[0] = f"[Gagal fetch {ticker}: {e}] Gunakan knowledge model untuk {ticker}."
    th = threading.Thread(target=fetch, daemon=True)
    th.start()
    th.join(timeout=15)
    return result[0]

# ─── PDF ENRICHMENT — deteksi emiten & lengkapi data dari yfinance ───
EMITEN_MAP = {
    # Bank
    "bank central asia": "BBCA", "bca": "BBCA", "bbca": "BBCA",
    "bank rakyat indonesia": "BBRI", "bri": "BBRI", "bbri": "BBRI",
    "bank mandiri": "BMRI", "mandiri": "BMRI", "bmri": "BMRI",
    "bank negara indonesia": "BBNI", "bni": "BBNI", "bbni": "BBNI",
    "bank tabungan negara": "BBTN", "btn": "BBTN", "bbtn": "BBTN",
    "bank syariah indonesia": "BRIS", "bsi": "BRIS", "bris": "BRIS",
    "bank cimb niaga": "BNGA", "cimb": "BNGA", "bnga": "BNGA",
    "bank danamon": "BDMN", "danamon": "BDMN", "bdmn": "BDMN",
    "bank permata": "BNLI", "permata": "BNLI",
    "bank panin": "PNBN", "panin": "PNBN",
    # Telko & Tech
    "telkom": "TLKM", "tlkm": "TLKM",
    "xl axiata": "EXCL", "xl": "EXCL", "excl": "EXCL",
    "indosat": "ISAT", "isat": "ISAT",
    "goto": "GOTO", "gojek": "GOTO", "tokopedia": "GOTO",
    "bukalapak": "BUKA", "buka": "BUKA",
    # Consumer & Industri
    "astra": "ASII", "asii": "ASII",
    "unilever": "UNVR", "unvr": "UNVR",
    "indofood": "INDF", "indf": "INDF",
    "indofood cbp": "ICBP", "icbp": "ICBP",
    "mayora": "MYOR", "myor": "MYOR",
    "kalbe": "KLBF", "klbf": "KLBF",
    "sido muncul": "SIDO", "sido": "SIDO",
    # Energi & Tambang
    "adaro": "ADRO", "adro": "ADRO",
    "antam": "ANTM", "antm": "ANTM",
    "ptba": "PTBA", "bukit asam": "PTBA",
    "pgas": "PGAS", "perusahaan gas": "PGAS",
    "medc": "MEDC", "medco": "MEDC",
    # Properti & Semen
    "semen indonesia": "SMGR", "smgr": "SMGR",
    "indocement": "INTP", "intp": "INTP",
}

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
    # Cek EMITEN_MAP — nama dan kode
    for name, ticker in EMITEN_MAP.items():
        if name in prompt_lower:
            return ticker
    # Cari 4 huruf kapital
    skip = {"YANG","ATAU","DARI","PADA","UNTUK","SAYA","TOLONG","ANALISA",
            "SAHAM","MOHON","BISA","FUNDAMENTAL","DENGAN","MINTA","ANALISIS",
            "APAKAH","BAGAIMANA","KENAPA","TOLONG","COBA","MINTA"}
    matches = re.findall(r'\b([A-Z]{4})\b', prompt_upper)
    for m in matches:
        if m not in skip:
            return m
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

KEMAMPUAN:
1. Trading & Pasar Modal — teknikal, fundamental, bandarmologi, berita pasar
2. Ekonomi & Bisnis — makro, mikro, geopolitik, akuntansi, manajemen, investasi
3. Pendidikan — bantu tugas, jelaskan konsep, essay, laporan, matematika
4. Umum — jawab pertanyaan apapun, berikan solusi praktis

════════════════════════════════════
FRAMEWORK TEKNIKAL (MnM Strategy+)
════════════════════════════════════
IFVG, FVG, Order Block, Supply & Demand, EMA 13/21/50, Bandarmologi, Volume Profile

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
- Kekuatan : [poin positif utama]
- Risiko   : [poin negatif utama]
- Valuasi  : [Undervalue/Fairvalue/Overvalue]
- Kesimpulan: [2-3 kalimat: kondisi bisnis, posisi valuasi, saran akumulasi/wait]
⚠️ DYOR — bukan rekomendasi investasi

ATURAN OUTPUT WAJIB:
- Setiap metrik di BARIS TERPISAH — DILARANG digabung horizontal
- Isi angka AKTUAL dari data — jika tidak ada, hitung dari rumus atau knowledge
- Jika ada [DATA PASAR] atau [DATA LIVE] → gunakan harga dan rasio dari sana
- TAHUN di judul: isi dengan tahun AKTUAL laporan atau tahun sekarang (2026)
- Tren 3 tahun: gunakan 2024→2025→2026, BUKAN 2020/2021/2022
- Jika yfinance hanya punya data sampai 2022: pakai sebagai historis lama,
  estimasi 2023-2026 dari knowledge model dan sebutkan itu estimasi
- Proyeksi dihitung dari CAGR aktual, bukan angka karang
- Jawab Bahasa Indonesia. Gambar/PDF → analisa langsung."""
}

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
            st.session_state.current_token = token  # simpan token di session
            saved = load_user(user_info["email"])
            if saved:
                st.session_state.theme = saved.get("theme", "dark")
                if saved.get("sessions"):
                    st.session_state.sessions = saved["sessions"]
                    st.session_state.active_id = saved.get("active_id")
            st.session_state.data_loaded = True
            restore_images_from_messages()
            # JANGAN clear query params — biarkan token tetap di URL
            st.rerun()
        except: pass

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
    # Pakai <a href> langsung — tidak perlu JS event listener
    _hist_items += f"""
(function(){{
    var a=pd.createElement('a');
    a.textContent='{_td}';
    var u=new URL(window.parent.location.href);
    u.searchParams.set('do','sel_{_sid}');
    a.href=u.toString();
    a.style.cssText='display:block;width:100%;padding:12px 18px;font-size:1rem;color:{C["text"]};background:{_bg};font-weight:{_fw};border:none;text-align:left;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-decoration:none;';
    a.onmouseenter=function(){{this.style.background='{C["hover"]}'}};
    a.onmouseleave=function(){{this.style.background='{_bg}'}};
    h.appendChild(a);
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
            try:
                fund_data = build_fundamental_from_text(prompt)
                if fund_data:
                    full_prompt = (
                        f"{fund_data}\n\n"
                        f"Perintah: Buat ANALISA FUNDAMENTAL lengkap untuk {_ticker_found} "
                        f"menggunakan FORMAT ANALISA FUNDAMENTAL yang sudah ditentukan. "
                        f"Gunakan framework yang sesuai (Buffett, Graham, Lynch, CAN SLIM, atau Perbankan). "
                        f"JANGAN meminta maaf atau merujuk percakapan sebelumnya. "
                        f"Langsung mulai dengan 📋 ANALISA FUNDAMENTAL."
                    )
                    # Flag untuk Groq — kirim tanpa history
                    st.session_state["fund_no_history"] = True
            except: pass
        else:
            try:
                ctx = build_context(prompt)
                if ctx:
                    full_prompt = f"[DATA PASAR]\n{ctx}\n[/DATA PASAR]\n\n{prompt}"
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
                    res = groq_client.chat.completions.create(
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
                             "content": _last_content[:5000]}
                        ]
                    else:
                        # Chat biasa — kirim history normal (max 5 pesan terakhir)
                        _msgs = [_all_msgs[0]] + _all_msgs[-4:]

                    res = groq_client.chat.completions.create(
                        model="llama-3.1-8b-instant",
                        messages=_msgs,
                        temperature=0.7,
                        max_tokens=1500
                    )
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
