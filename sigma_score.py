# ═══════════════════════════════════════════════════════════════════════════════
# SIGMA SCORE ENGINE v1.0
# Multi-Factor Scoring System untuk IDX — by MnM Strategy+ / KIPM-UP
#
# Komponen:
#   1. TEKNIKAL SCORE   (25%) — MnM Strategy+ confluence: EMA, momentum, struktur
#   2. VOLUME SCORE     (25%) — Spike anomali, divergence, absorpsi
#   3. BANDAR SCORE     (30%) — Deteksi akumulasi/distribusi dari volume behavior
#   4. FUNDAMENTAL      (10%) — ROE, DER, PBV, EPS growth
#   5. MOMENTUM (RS)    (10%) — Relative Strength vs IHSG
#
# Output:
#   sigma_score(ticker, price_data, fundamental_data) → SigmaScoreResult
#   - score: int 0–100
#   - grade: "STRONG BUY" / "BUY" / "WATCH" / "AVOID" / "DANGER"
#   - badge_color: hex color
#   - breakdown: dict per komponen
#   - signals: list sinyal penting yang ditemukan
#   - entry_zone, sl_zone, tp1, tp2, tp3: level harga
# ═══════════════════════════════════════════════════════════════════════════════

from dataclasses import dataclass, field
from typing import Optional
import math


# ─────────────────────────────────────────────
# KONFIGURASI BOBOT
# ─────────────────────────────────────────────
WEIGHTS = {
    "teknikal":    0.22,   # MnM Strategy+ confluence
    "volume":      0.25,   # Volume anomali & divergence
    "bandar":      0.35,   # DOMINAN — IDX is bandar-driven
    "fundamental": 0.10,   # Buffett criteria
    "momentum_rs": 0.08,   # Relative strength vs IHSG
}

# Grade thresholds
GRADE_THRESHOLDS = [
    (82, "STRONG BUY",  "#00c853"),  # hijau terang
    (65, "BUY",         "#69f0ae"),  # hijau muda
    (48, "WATCH",       "#ffd740"),  # kuning
    (30, "AVOID",       "#ff6d00"),  # oranye
    (0,  "DANGER",      "#ff1744"),  # merah
]

# IDX Tick rules (BEI fraksi harga)
def _tick(price: float) -> float:
    if price < 200:   return 1
    if price < 500:   return 2
    if price < 2000:  return 5
    if price < 5000:  return 10
    return 25

def _round_tick(price: float) -> float:
    t = _tick(price)
    return round(price / t) * t


# ─────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────
@dataclass
class PriceData:
    """
    Data OHLCV dari yfinance (minimal 20 hari).
    closes, volumes, highs, lows → list float, urutan LAMA ke BARU (index -1 = hari ini).
    """
    closes:  list
    volumes: list
    highs:   list
    lows:    list
    ihsg_closes: list = field(default_factory=list)  # untuk RS calculation

@dataclass
class FundamentalData:
    """Data fundamental dari _fetch_multi_fundamental()."""
    roe:         Optional[float] = None   # 0–1 (misal 0.15 = 15%)
    der:         Optional[float] = None   # debt/equity ratio
    pbv:         Optional[float] = None   # price to book
    eps_growth:  Optional[float] = None   # YoY EPS growth 0–1
    net_margin:  Optional[float] = None   # 0–1
    current_ratio: Optional[float] = None

@dataclass
class SigmaScoreResult:
    score:       int
    grade:       str
    badge_color: str
    breakdown:   dict          # {"teknikal": 70, "volume": 65, ...}
    signals:     list          # list string sinyal penting
    confidence:  str           # "HIGH" / "MEDIUM" / "LOW"
    # Trade levels (None jika tidak ada data cukup)
    entry_zone:  Optional[tuple] = None   # (low, high) dalam Rp
    sl_zone:     Optional[float] = None
    tp1:         Optional[float] = None
    tp2:         Optional[float] = None
    tp3:         Optional[float] = None
    rr_ratio:    Optional[float] = None


# ─────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────
def _ema(values: list, period: int) -> float:
    """EMA sederhana."""
    if len(values) < period:
        return sum(values) / len(values)
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema

def _atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
    """Average True Range — ukuran volatilitas."""
    if len(closes) < period + 1:
        return (max(highs[-5:]) - min(lows[-5:])) / 2 if highs else 0
    trs = []
    for i in range(1, min(period + 1, len(closes))):
        tr = max(
            highs[-i] - lows[-i],
            abs(highs[-i] - closes[-i - 1]),
            abs(lows[-i]  - closes[-i - 1]),
        )
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0

def _swing_lows(lows: list, window: int = 3) -> list:
    """Cari swing low dari data harga."""
    result = []
    for i in range(window, len(lows) - window):
        if lows[i] == min(lows[i - window: i + window + 1]):
            result.append((i, lows[i]))
    return result

def _swing_highs(highs: list, window: int = 3) -> list:
    """Cari swing high dari data harga."""
    result = []
    for i in range(window, len(highs) - window):
        if highs[i] == max(highs[i - window: i + window + 1]):
            result.append((i, highs[i]))
    return result

def _clamp(val, lo=0, hi=100) -> int:
    return int(max(lo, min(hi, val)))


# ─────────────────────────────────────────────
# KOMPONEN 1 — TEKNIKAL SCORE (0–100)
# ─────────────────────────────────────────────
def _score_teknikal(pd: PriceData) -> tuple:
    """
    Scoring berbasis MnM Strategy+:
    - EMA alignment (13/21/50/200)
    - Price vs EMA positions
    - Struktur HH/HL atau LL/LH
    - Candle momentum
    Returns (score 0–100, signals list)
    """
    c = pd.closes
    h = pd.highs
    l = pd.lows
    signals = []
    score = 50  # baseline netral

    if len(c) < 5:
        return 50, ["Data teknikal tidak cukup"]

    price = c[-1]

    # ── EMA Calculation ──
    ema13  = _ema(c, 13)  if len(c) >= 13  else _ema(c, len(c))
    ema21  = _ema(c, 21)  if len(c) >= 21  else _ema(c, len(c))
    ema50  = _ema(c, 50)  if len(c) >= 50  else _ema(c, len(c))
    ema200 = _ema(c, 200) if len(c) >= 200 else _ema(c, len(c))

    # ── EMA Alignment Score ──
    bullish_ema = 0
    if price > ema13:  bullish_ema += 1
    if price > ema21:  bullish_ema += 1
    if price > ema50:  bullish_ema += 1
    if price > ema200: bullish_ema += 1
    if ema13 > ema21:  bullish_ema += 1
    if ema21 > ema50:  bullish_ema += 1

    # EMA alignment: 0–6 → mapped ke -20 to +30
    ema_contribution = (bullish_ema / 6) * 50 - 15
    score += ema_contribution

    if bullish_ema >= 5:
        signals.append("✅ EMA bullish alignment penuh (price > EMA13/21/50/200)")
    elif bullish_ema >= 3:
        signals.append("🟡 EMA alignment parsial")
    else:
        signals.append("🔴 EMA bearish — harga di bawah EMA kunci")

    # ── Struktur HH/HL vs LL/LH ──
    if len(c) >= 10:
        recent_highs = h[-10:]
        recent_lows  = l[-10:]
        # HH: high terbaru > high 5 hari lalu
        if recent_highs[-1] > recent_highs[-6] and recent_lows[-1] > recent_lows[-6]:
            score += 10
            signals.append("✅ Struktur HH/HL — uptrend valid")
        elif recent_highs[-1] < recent_highs[-6] and recent_lows[-1] < recent_lows[-6]:
            score -= 10
            signals.append("🔴 Struktur LL/LH — downtrend aktif")

    # ── Golden/Death Cross ──
    if len(c) >= 55:
        ema50_prev = _ema(c[:-1], 50)
        ema200_prev = _ema(c[:-5], 200) if len(c) >= 205 else ema200
        if ema50 > ema200 and ema50_prev <= ema200_prev:
            score += 15
            signals.append("🌟 GOLDEN CROSS EMA50/200 — sinyal bullish mayor")
        elif ema50 < ema200 and ema50_prev >= ema200_prev:
            score -= 15
            signals.append("💀 DEATH CROSS EMA50/200 — sinyal bearish mayor")

    # ── Candle Momentum (3 hari terakhir) ──
    if len(c) >= 4:
        bodies = [abs(c[-i] - c[-i-1]) for i in range(1, 4)]
        avg_body = sum(bodies) / 3
        last_body = abs(c[-1] - c[-2])
        # Candle besar = momentum kuat
        if last_body > avg_body * 1.5 and c[-1] > c[-2]:
            score += 8
            signals.append("⚡ Candle momentum bullish kuat")
        elif last_body > avg_body * 1.5 and c[-1] < c[-2]:
            score -= 8
            signals.append("⚡ Candle momentum bearish kuat")

    # ── Proximity ke EMA21 (area entry ideal MnM) ──
    dist_ema21 = abs(price - ema21) / ema21 * 100
    if dist_ema21 <= 1.5 and price >= ema21:
        score += 7
        signals.append("🎯 Harga di atas EMA21 (zona entry MnM)")
    elif dist_ema21 <= 3.0 and price >= ema21 * 0.98:
        score += 4
        signals.append("🟡 Harga mendekati EMA21")

    return _clamp(score), signals


# ─────────────────────────────────────────────
# KOMPONEN 2 — VOLUME SCORE (0–100)
# ─────────────────────────────────────────────
def _score_volume(pd: PriceData) -> tuple:
    """
    Volume Intelligence (sesuai GROQ_SYSTEM_PROMPT SIGMA):
    - Spike detection vs avg 20 hari
    - Price-Volume Divergence
    - Dry-up detection (akumulasi stealth)
    - Absorpsi di zona supply/demand
    """
    c = pd.closes
    v = pd.volumes
    h = pd.highs
    l = pd.lows
    signals = []
    score = 50

    if len(v) < 5:
        return 50, ["Data volume tidak cukup"]

    avg20 = sum(v[-20:]) / min(len(v), 20)
    avg5  = sum(v[-5:])  / min(len(v), 5)
    last_vol  = v[-1]
    last_price = c[-1]
    prev_price = c[-2] if len(c) >= 2 else last_price

    spike_ratio = last_vol / avg20 if avg20 > 0 else 1

    # ── Volume Spike Classification ──
    if spike_ratio >= 10:
        signals.append(f"🔴 VOLUME EKSTREM {spike_ratio:.1f}x avg — event besar, cek berita!")
        # Ekstrem: bisa reversal atau katalis besar — netral dulu, tunggu konfirmasi
        score += 0
    elif spike_ratio >= 5:
        signals.append(f"🟠 Volume sangat tinggi {spike_ratio:.1f}x avg — institusi aktif")
        score += 15 if last_price > prev_price else -5
    elif spike_ratio >= 2:
        signals.append(f"🟡 Volume spike {spike_ratio:.1f}x avg")
        score += 10 if last_price > prev_price else -3

    # ── Price-Volume Divergence (5 hari) ──
    if len(c) >= 6 and len(v) >= 6:
        price_chg_5d = (c[-1] - c[-6]) / c[-6] * 100 if c[-6] > 0 else 0
        vol_avg_5d_old = sum(v[-11:-6]) / 5 if len(v) >= 11 else avg20
        vol_avg_5d_new = sum(v[-5:])    / 5
        vol_chg_pct = (vol_avg_5d_new - vol_avg_5d_old) / vol_avg_5d_old * 100 if vol_avg_5d_old > 0 else 0

        if price_chg_5d > 2 and vol_chg_pct < -20:
            score -= 15
            signals.append("⚠️ DIVERGENSI: Harga naik tapi volume TURUN — momentum lemah")
        elif price_chg_5d > 2 and vol_chg_pct > 20:
            score += 18
            signals.append("✅ Harga naik + volume naik — momentum KUAT")
        elif price_chg_5d < -2 and vol_chg_pct < -20:
            score += 8
            signals.append("🔵 Seller exhaustion — volume turun saat harga turun")
        elif price_chg_5d < -2 and vol_chg_pct > 20:
            score -= 12
            signals.append("🔴 Distribusi massal — harga turun + volume spike")

    # ── Volume Dry-Up Detection (akumulasi stealth) ──
    dry_up = avg5 < (avg20 * 0.45)
    if dry_up:
        score += 12
        signals.append("🔵 Volume DRY-UP — potensi akumulasi stealth sebelum breakout")

    # ── Candle-Body vs Volume Konviksi ──
    if len(c) >= 3 and len(h) >= 3 and len(l) >= 3:
        candle_body = abs(c[-1] - c[-2])
        candle_range = h[-1] - l[-1]
        body_ratio = candle_body / candle_range if candle_range > 0 else 0.5

        if body_ratio > 0.7 and spike_ratio >= 1.5 and last_price > prev_price:
            score += 12
            signals.append("✅ Candle besar + volume tinggi — konviksi KUAT bullish")
        elif body_ratio < 0.3 and spike_ratio >= 2:
            score -= 5
            signals.append("⚠️ Candle kecil + volume tinggi — pertempuran BUY/SELL, tunggu resolusi")
        elif body_ratio > 0.7 and spike_ratio < 0.5:
            score -= 8
            signals.append("⚠️ Candle besar tapi volume rendah — potensi TRAP/manipulasi")

    return _clamp(score), signals


# ─────────────────────────────────────────────
# KOMPONEN 3 — BANDAR SCORE (0–100)
# ─────────────────────────────────────────────
def _score_bandar(pd: PriceData) -> tuple:
    """
    Deteksi akumulasi/distribusi bandar dari price & volume behavior.
    Tanpa broker data real-time → gunakan proxy: clustering volume di price levels,
    quiet accumulation pattern, dan distribusi di resistance.

    IDX Rule (counter-intuitive):
    - Volume spike kecil tapi sustained di low = AKUMULASI
    - Volume spike besar di high = DISTRIBUSI
    """
    c = pd.closes
    v = pd.volumes
    h = pd.highs
    l = pd.lows
    signals = []
    score = 50

    if len(c) < 10:
        return 50, ["Data tidak cukup untuk deteksi bandar"]

    avg_vol_20 = sum(v[-20:]) / min(len(v), 20)

    # ── Pattern 1: Stealth Accumulation (quiet buying at lows) ──
    # Ciri: harga sideways/turun perlahan + volume di bawah rata-rata tapi konsisten
    price_range_10d = (max(c[-10:]) - min(c[-10:])) / c[-10] * 100 if c[-10] > 0 else 0
    vol_consistency = min(v[-10:]) / avg_vol_20 if avg_vol_20 > 0 else 0

    if price_range_10d < 5 and vol_consistency > 0.3:  # sideways + volume konsisten
        score += 15
        signals.append("🟢 Pola AKUMULASI STEALTH: sideways + volume konsisten — bandar mengumpulkan")

    # ── Pattern 2: High-Volume Reversal at Bottom ──
    # Volume spike besar di harga rendah = bandar absorb supply dari retail panik
    price_at_low = c[-1] <= min(c[-20:]) * 1.05  # dalam 5% dari low 20 hari
    if price_at_low and v[-1] > avg_vol_20 * 2:
        score += 20
        signals.append("🟢 ABSORPSI di LOW: volume spike di zona bawah — potensial reversal bandar")

    # ── Pattern 3: Distribution Pattern ──
    # Volume spike besar di high = bandar distribusi ke retail FOMO
    price_at_high = c[-1] >= max(c[-20:]) * 0.97  # dalam 3% dari high 20 hari
    if price_at_high and v[-1] > avg_vol_20 * 2.5:
        score -= 25
        signals.append("🔴 DISTRIBUSI di HIGH: volume ekstrem di zona atas — potensi bandar jual ke retail")

    # ── Pattern 4: Institutional Buildup (volume naik bertahap saat harga naik) ──
    if len(c) >= 15:
        vol_trend_early = sum(v[-15:-10]) / 5
        vol_trend_late  = sum(v[-5:]) / 5
        price_trend     = (c[-1] - c[-15]) / c[-15] * 100 if c[-15] > 0 else 0

        if price_trend > 5 and vol_trend_late > vol_trend_early * 1.3:
            score += 18
            signals.append("✅ INSTITUTIONAL BUILDUP: harga naik + volume bertahap meningkat")
        elif price_trend > 5 and vol_trend_late < vol_trend_early * 0.7:
            score -= 10
            signals.append("⚠️ Harga naik tapi volume trend TURUN — distribusi mungkin dimulai")

    # ── Pattern 5: Shakeout Detection ──
    # Penurunan tajam 1 hari dengan volume tinggi tapi close kembali ke atas
    if len(c) >= 3 and len(h) >= 3 and len(l) >= 3:
        intraday_drop = (l[-2] - c[-3]) / c[-3] * 100 if c[-3] > 0 else 0  # low kemarin vs close 2 hari lalu
        recovery      = (c[-1] - l[-2]) / l[-2] * 100 if l[-2] > 0 else 0    # recovery hari ini dari low kemarin
        if intraday_drop < -3 and recovery > 2 and v[-2] > avg_vol_20 * 1.5:
            score += 14
            signals.append("🟡 SHAKEOUT PATTERN: penurunan tajam diikuti recovery — bandar kumpulin di panic sell")

    # ── Pattern 6: Stop Hunt ──
    # Wick panjang ke bawah dengan body kecil = test stop loss lalu reversal
    if len(l) >= 2 and len(c) >= 2:
        wick_down = c[-2] - l[-2]  # lower wick
        body      = abs(c[-2] - c[-3]) if len(c) >= 3 else 1
        if body > 0 and wick_down > body * 2 and c[-1] > c[-2]:
            score += 10
            signals.append("🟡 STOP HUNT: wick panjang ke bawah + recovery — bandar test supply")

    return _clamp(score), signals


# ─────────────────────────────────────────────
# KOMPONEN 4 — FUNDAMENTAL SCORE (0–100)
# ─────────────────────────────────────────────
def _score_fundamental(fd: Optional[FundamentalData]) -> tuple:
    """
    Warren Buffett criteria + IDX context.
    Score tinggi = fundamental kuat, undervalue, profitable.
    """
    if fd is None:
        return 50, ["Data fundamental tidak tersedia — skor netral"]

    signals = []
    score = 50

    # ── ROE (target: >15%) ──
    if fd.roe is not None:
        roe_pct = fd.roe * 100 if fd.roe < 5 else fd.roe  # handle persen vs desimal
        if roe_pct > 20:
            score += 15
            signals.append(f"✅ ROE {roe_pct:.1f}% — sangat baik (>20%)")
        elif roe_pct > 15:
            score += 8
            signals.append(f"✅ ROE {roe_pct:.1f}% — baik (>15%)")
        elif roe_pct < 8:
            score -= 12
            signals.append(f"🔴 ROE {roe_pct:.1f}% — lemah (<8%)")

    # ── DER (target: <1x untuk non-bank) ──
    if fd.der is not None:
        if fd.der < 0.5:
            score += 10
            signals.append(f"✅ DER {fd.der:.2f}x — konservatif (rendah utang)")
        elif fd.der > 2.0:
            score -= 15
            signals.append(f"🔴 DER {fd.der:.2f}x — utang tinggi, risiko keuangan")
        elif fd.der > 1.5:
            score -= 7
            signals.append(f"⚠️ DER {fd.der:.2f}x — utang perlu diperhatikan")

    # ── PBV (target: 1x–3x ideal untuk IDX) ──
    if fd.pbv is not None:
        if 0.5 <= fd.pbv <= 2.0:
            score += 12
            signals.append(f"✅ PBV {fd.pbv:.2f}x — valuasi menarik")
        elif fd.pbv < 0.5:
            score += 6
            signals.append(f"🟡 PBV {fd.pbv:.2f}x — sangat murah (cek apakah ada masalah)")
        elif fd.pbv > 5.0:
            score -= 12
            signals.append(f"🔴 PBV {fd.pbv:.2f}x — sudah mahal")
        elif fd.pbv > 3.0:
            score -= 5
            signals.append(f"⚠️ PBV {fd.pbv:.2f}x — premium, butuh katalis kuat")

    # ── EPS Growth ──
    if fd.eps_growth is not None:
        eg_pct = fd.eps_growth * 100 if fd.eps_growth < 5 else fd.eps_growth
        if eg_pct > 20:
            score += 10
            signals.append(f"✅ EPS growth {eg_pct:.1f}% YoY — pertumbuhan kuat")
        elif eg_pct > 10:
            score += 5
        elif eg_pct < 0:
            score -= 12
            signals.append(f"🔴 EPS turun {eg_pct:.1f}% YoY — laba menyusut")

    # ── Net Margin ──
    if fd.net_margin is not None:
        nm_pct = fd.net_margin * 100 if fd.net_margin < 5 else fd.net_margin
        if nm_pct > 15:
            score += 8
            signals.append(f"✅ Net margin {nm_pct:.1f}% — profitabilitas solid")
        elif nm_pct < 3:
            score -= 8
            signals.append(f"⚠️ Net margin {nm_pct:.1f}% — sangat tipis")

    # ── Current Ratio ──
    if fd.current_ratio is not None:
        if fd.current_ratio >= 2.0:
            score += 5
        elif fd.current_ratio < 1.0:
            score -= 10
            signals.append(f"🔴 Current ratio {fd.current_ratio:.2f}x — likuiditas ketat")

    return _clamp(score), signals


# ─────────────────────────────────────────────
# KOMPONEN 5 — MOMENTUM RS SCORE (0–100)
# ─────────────────────────────────────────────
def _score_momentum_rs(pd: PriceData) -> tuple:
    """
    Relative Strength vs IHSG.
    RS > 1 = outperform → bullish kandidat
    RS < 1 = underperform → lemah vs market
    """
    c = pd.closes
    ihsg = pd.ihsg_closes
    signals = []

    if len(c) < 10:
        return 50, ["Data tidak cukup untuk RS"]

    # Internal momentum (tanpa IHSG)
    ret_5d  = (c[-1] - c[-6])  / c[-6]  * 100 if len(c) >= 6  and c[-6]  > 0 else 0
    ret_20d = (c[-1] - c[-21]) / c[-21] * 100 if len(c) >= 21 and c[-21] > 0 else 0

    score = 50
    score += ret_5d * 1.5    # 1% naik 5 hari = +1.5 poin
    score += ret_20d * 0.8   # 1% naik 20 hari = +0.8 poin

    if ret_5d > 5:
        signals.append(f"⚡ Momentum kuat: +{ret_5d:.1f}% dalam 5 hari terakhir")
    elif ret_5d < -5:
        signals.append(f"🔴 Momentum lemah: {ret_5d:.1f}% dalam 5 hari terakhir")

    # RS vs IHSG jika data tersedia
    if len(ihsg) >= 10:
        ihsg_ret_20d = (ihsg[-1] - ihsg[-21]) / ihsg[-21] * 100 if len(ihsg) >= 21 and ihsg[-21] > 0 else 0
        rs = ret_20d / ihsg_ret_20d if ihsg_ret_20d != 0 else 1.0

        if rs > 1.5:
            score += 15
            signals.append(f"✅ RS {rs:.2f}x — OUTPERFORM IHSG signifikan")
        elif rs > 1.1:
            score += 8
            signals.append(f"✅ RS {rs:.2f}x — outperform IHSG")
        elif rs < 0.7:
            score -= 15
            signals.append(f"🔴 RS {rs:.2f}x — underperform IHSG — hindari saat ini")
        elif rs < 0.9:
            score -= 7
            signals.append(f"⚠️ RS {rs:.2f}x — lebih lemah dari IHSG")

    return _clamp(score), signals


# ─────────────────────────────────────────────
# TRADE LEVEL CALCULATOR
# ─────────────────────────────────────────────
def _calc_trade_levels(pd: PriceData) -> dict:
    """
    Auto-hitung entry zone, SL, TP1/2/3 dari struktur teknikal.
    Mengikuti MnM Strategy+: TP dari resistance, bukan rasio matematika.
    """
    c = pd.closes
    h = pd.highs
    l = pd.lows

    if len(c) < 20:
        return {}

    price = c[-1]
    atr = _atr(h, l, c, 14)

    # ── Support & Resistance dari Swing ──
    s_lows  = _swing_lows(l[-30:],  window=3)
    s_highs = _swing_highs(h[-30:], window=3)

    supports    = sorted([x[1] for x in s_lows  if x[1] < price], reverse=True)
    resistances = sorted([x[1] for x in s_highs if x[1] > price])

    # ── Entry Zone ──
    nearest_support = supports[0] if supports else price - atr * 1.5
    entry_lo = _round_tick(max(nearest_support, price - atr * 0.8))
    entry_hi = _round_tick(price)

    # ── Stop Loss ──
    second_support = supports[1] if len(supports) > 1 else nearest_support - atr
    sl = _round_tick(second_support - atr * 0.5)
    sl = min(sl, entry_lo - atr)  # SL minimal 1 ATR di bawah entry

    # ── Take Profits dari resistance structure ──
    tp1 = _round_tick(resistances[0]) if resistances else _round_tick(price + atr * 2)
    tp2 = _round_tick(resistances[1]) if len(resistances) > 1 else _round_tick(tp1 + atr * 1.5)
    tp3 = _round_tick(resistances[2]) if len(resistances) > 2 else None

    # ── R/R Ratio ──
    mid_entry = (entry_lo + entry_hi) / 2
    risk      = max(mid_entry - sl, atr * 0.5)
    reward    = tp1 - mid_entry
    rr        = round(reward / risk, 2) if risk > 0 else 0

    return {
        "entry_zone": (entry_lo, entry_hi),
        "sl":         sl,
        "tp1":        tp1,
        "tp2":        tp2,
        "tp3":        tp3,
        "rr_ratio":   rr,
    }


# ─────────────────────────────────────────────
# KOMPONEN 3B — BANDAR SCORE FROM BROKER SUMMARY (user input)
# ─────────────────────────────────────────────
def score_bandar_from_broker_summary(broker_text: str) -> tuple:
    """
    Parse broker summary yang diinput user (copy-paste dari RTI/Stockbit/IPOT).
    Menerapkan logika IDX yang counter-intuitive:
      - Banyak buyer broker + sedikit seller broker = DISTRIBUSI
      - Sedikit buyer broker + banyak seller broker = AKUMULASI

    Format yang didukung:
      "Net Foreign: +Rp 50M | Top Buy: BNI, MNC | Top Sell: UBS, CGS"
      atau teks bebas yang mengandung keyword.

    Returns (score 0–100, signals list)
    """
    if not broker_text or len(broker_text.strip()) < 10:
        return 50, ["Tidak ada data broker summary"]

    text = broker_text.lower()
    signals = []
    score = 50

    # ── Net Foreign Flow ──
    import re as _re
    # Cari net foreign: "+Rp 50M", "-50 miliar", "net buy 100", dsb
    nf_match = _re.search(
        r'(?:net\s*foreign|asing\s*net|foreign\s*net)[^\d\-+]*([+\-]?[\d,.]+)\s*(m|jt|miliar|b|rb|ribu)?',
        text
    )
    if nf_match:
        val_str = nf_match.group(1).replace(',', '').replace('.', '')
        unit    = (nf_match.group(2) or '').lower()
        try:
            val = float(val_str)
            # Normalise ke miliar
            if unit in ('m', 'jt'):     val /= 1000
            elif unit in ('rb', 'ribu'): val /= 1_000_000
            if val > 0:
                score += min(20, val * 0.5)
                signals.append(f"✅ Net Foreign BUY Rp{val:.1f}M — asing akumulasi")
            elif val < 0:
                score -= min(20, abs(val) * 0.5)
                signals.append(f"🔴 Net Foreign SELL Rp{abs(val):.1f}M — asing distribusi")
        except:
            pass

    # ── Keyword detection: akumulasi vs distribusi ──
    AKUMULASI_KW = [
        "akumulasi", "accumulation", "net buy", "net beli",
        "foreign buy", "asing beli", "big buyer", "institutional buy",
        "bandar masuk", "smart money buy", "stealth buy"
    ]
    DISTRIBUSI_KW = [
        "distribusi", "distribution", "net sell", "net jual",
        "foreign sell", "asing jual", "big seller", "institutional sell",
        "bandar keluar", "offloading", "take profit besar"
    ]

    akum_hits = sum(1 for kw in AKUMULASI_KW if kw in text)
    dist_hits = sum(1 for kw in DISTRIBUSI_KW if kw in text)

    if akum_hits > dist_hits and akum_hits >= 2:
        score += 18
        signals.append(f"🟢 Broker summary: sinyal AKUMULASI ({akum_hits} indikator)")
    elif akum_hits > dist_hits and akum_hits == 1:
        score += 8
        signals.append("🟡 Broker summary: sedikit sinyal akumulasi")
    elif dist_hits > akum_hits and dist_hits >= 2:
        score -= 18
        signals.append(f"🔴 Broker summary: sinyal DISTRIBUSI ({dist_hits} indikator)")
    elif dist_hits > akum_hits and dist_hits == 1:
        score -= 8
        signals.append("⚠️ Broker summary: sedikit sinyal distribusi")

    # ── IDX Counter-intuitive Logic ──
    # Buyer broker banyak + seller sedikit → distribusi (smart money jual ke retail FOMO)
    buyer_heavy = any(kw in text for kw in [
        "banyak buyer", "buyer mendominasi", "buyer > seller",
        "lebih banyak buyer", "buyer broker banyak"
    ])
    seller_heavy = any(kw in text for kw in [
        "banyak seller", "seller mendominasi", "seller > buyer",
        "lebih banyak seller", "seller broker banyak"
    ])

    if buyer_heavy:
        # Counter-intuitive: banyak buyer broker = DISTRIBUSI di IDX
        score -= 12
        signals.append("⚠️ IDX Counter-intuitive: banyak buyer broker → potensi DISTRIBUSI")
    if seller_heavy:
        # Counter-intuitive: banyak seller broker = AKUMULASI di IDX
        score += 12
        signals.append("🟢 IDX Counter-intuitive: banyak seller broker → potensi AKUMULASI smart money")

    # ── Specific broker tiers (asing premium = smart money) ──
    FOREIGN_SMART = ["ubs", "cgs", "clsa", "macquarie", "jp morgan", "jpmorgan",
                     "deutsche", "dbs", "cimb", "nomura", "merrill", "morgan stanley"]
    LOCAL_RETAIL  = ["mnc", "bni", "ipot", "sinarmas", "trimegah", "henan", "phillip",
                     "phintraco", "panin", "maybank", "kgs", "samuel"]

    foreign_buy  = sum(1 for b in FOREIGN_SMART if b in text and
                       any(f"{b}" in seg and ("buy" in seg or "beli" in seg)
                           for seg in text.split(',')))
    foreign_sell = sum(1 for b in FOREIGN_SMART if b in text and
                       any(f"{b}" in seg and ("sell" in seg or "jual" in seg)
                           for seg in text.split(',')))

    if foreign_buy >= 2:
        score += 15
        signals.append(f"✅ {foreign_buy} broker asing premium di sisi BUY — institusi masuk")
    if foreign_sell >= 2:
        score -= 12
        signals.append(f"🔴 {foreign_sell} broker asing premium di sisi SELL — smart money keluar")

    return _clamp(score), signals


# ─────────────────────────────────────────────
# MAIN SCORING ENGINE
# ─────────────────────────────────────────────
def sigma_score(
    ticker: str,
    price_data: PriceData,
    fundamental_data: Optional[FundamentalData] = None,
    broker_summary: Optional[str] = None,
) -> SigmaScoreResult:
    """
    Hitung SIGMA Score untuk satu saham.

    Parameters:
        ticker          : kode saham IDX (4 huruf)
        price_data      : PriceData dengan OHLCV minimal 20 hari
        fundamental_data: FundamentalData (opsional)
        broker_summary  : teks broker summary dari user (opsional, meningkatkan akurasi bandar score)

    Returns:
        SigmaScoreResult
    """
    # ── Hitung semua komponen ──
    t_score, t_signals = _score_teknikal(price_data)
    v_score, v_signals = _score_volume(price_data)

    # Bandar score: blend volume-based + broker summary jika ada
    b_score_vol, b_signals_vol = _score_bandar(price_data)
    if broker_summary:
        b_score_broker, b_signals_broker = score_bandar_from_broker_summary(broker_summary)
        # Jika broker summary tersedia → bobot 60% broker, 40% volume behavior
        b_score   = int(b_score_broker * 0.60 + b_score_vol * 0.40)
        b_signals = b_signals_broker + b_signals_vol
    else:
        b_score   = b_score_vol
        b_signals = b_signals_vol

    f_score, f_signals = _score_fundamental(fundamental_data)
    m_score, m_signals = _score_momentum_rs(price_data)

    # ── Weighted Final Score ──
    raw = (
        t_score * WEIGHTS["teknikal"]    +
        v_score * WEIGHTS["volume"]      +
        b_score * WEIGHTS["bandar"]      +
        f_score * WEIGHTS["fundamental"] +
        m_score * WEIGHTS["momentum_rs"]
    )
    final_score = _clamp(raw)

    # ── Grade ──
    grade = "DANGER"
    badge_color = "#ff1744"
    for threshold, g, color in GRADE_THRESHOLDS:
        if final_score >= threshold:
            grade = g
            badge_color = color
            break

    # ── Confidence Level ──
    data_len = len(price_data.closes)
    has_fundamental = fundamental_data is not None and any([
        fundamental_data.roe, fundamental_data.der,
        fundamental_data.pbv, fundamental_data.eps_growth
    ])
    has_ihsg = len(price_data.ihsg_closes) >= 20

    conf_points = 0
    if data_len >= 60:  conf_points += 2
    elif data_len >= 20: conf_points += 1
    if has_fundamental:  conf_points += 1
    if has_ihsg:         conf_points += 1
    if broker_summary:   conf_points += 1  # broker data meningkatkan confidence

    confidence = "HIGH" if conf_points >= 3 else ("MEDIUM" if conf_points >= 2 else "LOW")

    # ── Trade Levels ──
    levels = _calc_trade_levels(price_data)

    # ── Aggregate Top Signals (max 6, prioritaskan yang relevan) ──
    all_signals = t_signals + v_signals + b_signals + f_signals + m_signals
    # Prioritaskan sinyal dengan emoji ✅🟢 (bullish) dan 🔴 (bearish), batasi 6
    top_signals = [s for s in all_signals if any(e in s for e in ["✅","🟢","🌟","⚡"])][:3]
    top_signals += [s for s in all_signals if any(e in s for e in ["🔴","💀","⛔"])][:2]
    top_signals += [s for s in all_signals if any(e in s for e in ["⚠️","🟡"])][:1]

    breakdown = {
        "teknikal":    t_score,
        "volume":      v_score,
        "bandar":      b_score,
        "fundamental": f_score,
        "momentum_rs": m_score,
    }

    return SigmaScoreResult(
        score       = final_score,
        grade       = grade,
        badge_color = badge_color,
        breakdown   = breakdown,
        signals     = top_signals if top_signals else all_signals[:4],
        confidence  = confidence,
        entry_zone  = levels.get("entry_zone"),
        sl_zone     = levels.get("sl"),
        tp1         = levels.get("tp1"),
        tp2         = levels.get("tp2"),
        tp3         = levels.get("tp3"),
        rr_ratio    = levels.get("rr_ratio"),
    )


# ─────────────────────────────────────────────
# BATCH SCORER — untuk Alpha Screener
# ─────────────────────────────────────────────
def batch_sigma_score(ticker_price_dict: dict, ihsg_closes: list = None) -> dict:
    """
    Score banyak saham sekaligus dari data yang sudah di-fetch.

    ticker_price_dict format (dari _reco_fetch_prices):
    {
        "BBCA": {
            "closes": [...], "volumes": [...], "highs": [...], "lows": [...],
            "fundamental": FundamentalData (opsional)
        }
    }

    Returns: { "BBCA": SigmaScoreResult, ... } — sorted by score descending
    """
    results = {}
    ihsg = ihsg_closes or []

    for ticker, data in ticker_price_dict.items():
        try:
            pd_obj = PriceData(
                closes        = data.get("closes", []),
                volumes       = data.get("volumes", []),
                highs         = data.get("highs", []),
                lows          = data.get("lows", []),
                ihsg_closes   = ihsg,
            )
            fd_obj = data.get("fundamental", None)
            results[ticker] = sigma_score(ticker, pd_obj, fd_obj)
        except Exception as e:
            # Jangan crash batch karena satu saham gagal
            results[ticker] = SigmaScoreResult(
                score=0, grade="N/A", badge_color="#555555",
                breakdown={}, signals=[f"Error: {str(e)[:60]}"],
                confidence="LOW"
            )

    # Sort by score descending
    return dict(sorted(results.items(), key=lambda x: x[1].score, reverse=True))


# ─────────────────────────────────────────────
# STREAMLIT RENDERER — Badge & Breakdown Card
# ─────────────────────────────────────────────
def render_sigma_score_badge(result: SigmaScoreResult, ticker: str = "", compact: bool = False) -> str:
    """
    Return HTML string untuk badge SIGMA Score.
    compact=True → hanya angka + grade (untuk tabel/card kecil)
    compact=False → full breakdown dengan progress bars
    """
    c = result.badge_color
    score = result.score
    grade = result.grade

    if compact:
        return f"""
<div style="display:inline-flex;align-items:center;gap:8px;background:rgba(0,0,0,0.25);
border:1px solid {c}44;border-radius:8px;padding:6px 12px;">
  <span style="font-family:'IBM Plex Mono',monospace;font-size:1.4rem;font-weight:700;color:{c};">{score}</span>
  <div>
    <div style="font-family:'IBM Plex Mono',monospace;font-size:0.6rem;color:{c};font-weight:600;letter-spacing:0.1em;">{grade}</div>
    <div style="font-family:'IBM Plex Mono',monospace;font-size:0.55rem;color:#888;letter-spacing:0.05em;">SIGMA SCORE</div>
  </div>
</div>"""

    # Full card
    bars = ""
    labels = {"teknikal":"Teknikal","volume":"Volume","bandar":"Bandar","fundamental":"Fundamental","momentum_rs":"RS Momentum"}
    bar_colors = {"teknikal":"#009dff","volume":"#a78bfa","bandar":"#ff6d00","fundamental":"#69f0ae","momentum_rs":"#ffd740"}

    for key, label in labels.items():
        val = result.breakdown.get(key, 50)
        bc  = bar_colors.get(key, "#888")
        wt  = int(WEIGHTS.get(key, 0.2) * 100)
        bars += f"""
<div style="margin-bottom:6px;">
  <div style="display:flex;justify-content:space-between;font-family:'IBM Plex Mono',monospace;font-size:0.6rem;color:#aaa;margin-bottom:2px;">
    <span>{label} <span style="color:#666;">({wt}%)</span></span>
    <span style="color:{bc};font-weight:600;">{val}</span>
  </div>
  <div style="background:rgba(255,255,255,0.07);border-radius:3px;height:4px;overflow:hidden;">
    <div style="width:{val}%;height:100%;background:{bc};border-radius:3px;transition:width 0.4s;"></div>
  </div>
</div>"""

    signals_html = "".join(f"<div style='font-size:0.72rem;color:#ccc;margin-bottom:3px;'>{s}</div>" for s in result.signals[:5])

    conf_color = {"HIGH":"#69f0ae","MEDIUM":"#ffd740","LOW":"#ff6d00"}.get(result.confidence, "#888")
    ticker_display = f" — {ticker}" if ticker else ""

    # Entry/SL/TP summary
    levels_html = ""
    if result.entry_zone:
        lo, hi = result.entry_zone
        levels_html += f"<div style='font-size:0.7rem;margin-top:8px;border-top:1px solid rgba(255,255,255,0.07);padding-top:8px;'>"
        levels_html += f"<span style='color:#ffd740;font-family:IBM Plex Mono,monospace;'>🎯 Entry</span> <span style='color:#eee;'>Rp{lo:,.0f} – Rp{hi:,.0f}</span> &nbsp;"
        if result.sl_zone:
            levels_html += f"<span style='color:#ff5555;font-family:IBM Plex Mono,monospace;'>🛑 SL</span> <span style='color:#eee;'>Rp{result.sl_zone:,.0f}</span> &nbsp;"
        if result.tp1:
            levels_html += f"<span style='color:#69f0ae;font-family:IBM Plex Mono,monospace;'>✅ TP1</span> <span style='color:#eee;'>Rp{result.tp1:,.0f}</span>"
        if result.rr_ratio:
            levels_html += f" &nbsp;<span style='color:#a78bfa;font-family:IBM Plex Mono,monospace;'>R/R {result.rr_ratio:.1f}x</span>"
        levels_html += "</div>"

    return f"""
<div style="background:rgba(20,23,35,0.85);border:1px solid {c}55;border-left:4px solid {c};
border-radius:0 10px 10px 0;padding:16px 18px;margin:8px 0;box-sizing:border-box;">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
    <div style="display:flex;align-items:center;gap:12px;">
      <div style="font-family:'IBM Plex Mono',monospace;font-size:2.2rem;font-weight:700;color:{c};line-height:1;">{score}</div>
      <div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.75rem;color:{c};font-weight:700;letter-spacing:0.12em;">{grade}</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.6rem;color:#666;letter-spacing:0.08em;">SIGMA SCORE{ticker_display}</div>
      </div>
    </div>
    <div style="text-align:right;">
      <div style="font-family:'IBM Plex Mono',monospace;font-size:0.55rem;color:{conf_color};letter-spacing:0.1em;">CONFIDENCE: {result.confidence}</div>
    </div>
  </div>
  {bars}
  <div style="margin-top:10px;border-top:1px solid rgba(255,255,255,0.07);padding-top:8px;">
    {signals_html}
  </div>
  {levels_html}
</div>"""


# ─────────────────────────────────────────────
# HELPER: build PriceData from yfinance history df
# ─────────────────────────────────────────────
def price_data_from_yf(history_df, ihsg_df=None) -> PriceData:
    """
    Konversi yfinance history DataFrame → PriceData.
    history_df = yf.Ticker('BBCA.JK').history(period='3mo')
    """
    return PriceData(
        closes  = history_df["Close"].tolist(),
        volumes = history_df["Volume"].tolist(),
        highs   = history_df["High"].tolist(),
        lows    = history_df["Low"].tolist(),
        ihsg_closes = ihsg_df["Close"].tolist() if ihsg_df is not None and not ihsg_df.empty else [],
    )


def fundamental_data_from_dict(d: dict) -> FundamentalData:
    """
    Konversi output _fetch_multi_fundamental() → FundamentalData.
    """
    def _pct(val):
        """Handle both decimal (0.15) and percent (15.0) format."""
        if val is None: return None
        return val if val > 5 else val * 100  # balikin dalam persen

    roe = d.get("roe")
    roe_pct = _pct(roe) if roe is not None else None

    eps_now  = d.get("eps")
    eps_prev = d.get("eps_last_year")
    eps_growth = None
    if eps_now and eps_prev and eps_prev != 0:
        eps_growth = (eps_now - eps_prev) / abs(eps_prev) * 100

    return FundamentalData(
        roe           = roe_pct,
        der           = d.get("der"),
        pbv           = d.get("pbv"),
        eps_growth    = eps_growth,
        net_margin    = _pct(d.get("net_margin")),
        current_ratio = d.get("current_ratio"),
    )
