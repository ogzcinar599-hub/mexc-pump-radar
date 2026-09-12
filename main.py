import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 🚀 MEXC PUMP RADAR V2
#
# AMAÇ:
# LSK gibi büyük hareketleri başlamadan ÖNCE yakalamak
#
# ANA MANTIK:
# 4H SIKIŞMA
# + HACİM GİRİŞİ
# + DİRENÇ YAKINLIĞI
# + HIGHER LOW
# + MOMENTUM
# + RSI TEYİDİ
#
# SADECE MEXC USDT FUTURES
# ============================================================

BASE = "https://api.mexc.com"

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SCAN_SECONDS = 60
MAX_WORKERS = 12

MIN_SCORE = 70
MAX_ALERTS = 6

COOLDOWN_MINUTES = 45

last_alert = {}

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
})


# ============================================================
# HTTP
# ============================================================

def get(url, params=None):

    try:

        r = session.get(
            url,
            params=params,
            timeout=10
        )

        if r.status_code != 200:
            return None

        return r.json()

    except Exception:
        return None


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):

    if not TOKEN or not CHAT_ID:
        print(message)
        return

    url = (
        f"https://api.telegram.org/"
        f"bot{TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        session.post(
            url,
            json=payload,
            timeout=10
        )

    except Exception as e:
        print("Telegram:", e)


# ============================================================
# FUTURES SYMBOLLER
# ============================================================

def get_symbols():

    data = get(
        f"{BASE}/api/v1/contract/detail"
    )

    if not data:
        return []

    symbols = []

    for item in data.get("data", []):

        symbol = item.get("symbol", "")

        if not symbol.endswith("_USDT"):
            continue

        state = item.get("state")

        try:

            if state is not None and int(state) != 0:
                continue

        except:
            pass

        symbols.append(symbol)

    return symbols


# ============================================================
# KLINE
# ============================================================

def klines(symbol, interval, limit=120):

    data = get(
        f"{BASE}/api/v1/contract/kline/{symbol}",
        {
            "interval": interval,
            "limit": limit
        }
    )

    if not data:
        return []

    d = data.get("data")

    if not d:
        return []

    # --------------------------------------------------------
    # DICT FORMAT
    # --------------------------------------------------------

    if isinstance(d, dict):

        t = d.get("time", [])
        o = d.get("open", [])
        h = d.get("high", [])
        l = d.get("low", [])
        c = d.get("close", [])
        v = d.get("vol", [])

        result = []

        n = min(
            len(t),
            len(o),
            len(h),
            len(l),
            len(c),
            len(v)
        )

        for i in range(n):

            try:

                result.append({
                    "time": float(t[i]),
                    "open": float(o[i]),
                    "high": float(h[i]),
                    "low": float(l[i]),
                    "close": float(c[i]),
                    "volume": float(v[i])
                })

            except:
                pass

        return result

    # --------------------------------------------------------
    # LIST FORMAT
    # --------------------------------------------------------

    if isinstance(d, list):

        result = []

        for x in d:

            try:

                if len(x) < 6:
                    continue

                result.append({
                    "time": float(x[0]),
                    "open": float(x[1]),
                    "high": float(x[2]),
                    "low": float(x[3]),
                    "close": float(x[4]),
                    "volume": float(x[5])
                })

            except:
                pass

        return result

    return []


# ============================================================
# RSI
# ============================================================

def RSI(values, period=14):

    if len(values) < period + 2:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        diff = values[i] - values[i - 1]

        if diff > 0:
            gains.append(diff)
            losses.append(0)

        else:
            gains.append(0)
            losses.append(abs(diff))

    avg_gain = sum(
        gains[:period]
    ) / period

    avg_loss = sum(
        losses[:period]
    ) / period

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            avg_gain * (period - 1)
            + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1)
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# SMA
# ============================================================

def SMA(values, period):

    if len(values) < period:
        return None

    return sum(
        values[-period:]
    ) / period


# ============================================================
# HACİM ORANI
# ============================================================

def volume_ratio(candles, lookback=20):

    if len(candles) < lookback + 1:
        return 0

    current = candles[-1]["volume"]

    old = [
        x["volume"]
        for x in candles[
            -lookback-1:-1
        ]
    ]

    avg = sum(old) / len(old)

    if avg <= 0:
        return 0

    return current / avg


# ============================================================
# DEĞİŞİM
# ============================================================

def change(candles, bars):

    if len(candles) <= bars:
        return 0

    old = candles[-bars-1]["close"]

    now = candles[-1]["close"]

    if old <= 0:
        return 0

    return (
        (now - old)
        / old
    ) * 100


# ============================================================
# 4H SIKIŞMA
# ============================================================

def compression(candles):

    if len(candles) < 25:
        return False, 999

    recent = candles[-20:]

    high = max(
        x["high"]
        for x in recent
    )

    low = min(
        x["low"]
        for x in recent
    )

    if low <= 0:
        return False, 999

    width = (
        (high - low)
        / low
    ) * 100

    # LSK benzeri sıkışma
    if width <= 15:
        return True, width

    # Biraz gevşek
    if width <= 22:
        return True, width

    return False, width


# ============================================================
# HIGHER LOW
# ============================================================

def higher_low(candles):

    if len(candles) < 12:
        return False

    left = candles[-12:-6]
    right = candles[-6:]

    low1 = min(
        x["low"]
        for x in left
    )

    low2 = min(
        x["low"]
        for x in right
    )

    return low2 > low1


# ============================================================
# DİRENÇ
# ============================================================

def resistance_info(candles):

    if len(candles) < 25:
        return None, 999

    previous = candles[-21:-1]

    resistance = max(
        x["high"]
        for x in previous
    )

    price = candles[-1]["close"]

    if resistance <= 0:
        return resistance, 999

    distance = (
        (resistance - price)
        / resistance
    ) * 100

    return resistance, distance


# ============================================================
# MOMENTUM
# ============================================================

def momentum_score(c15, c1):

    m15_now = change(c15, 4)
    m15_old = change(c15[:-4], 4)

    m1_now = change(c1, 4)
    m1_old = change(c1[:-4], 4)

    score = 0
    reasons = []

    if m15_now > m15_old:

        score += 8

        reasons.append(
            "15M momentum↑"
        )

    if m1_now > m1_old:

        score += 7

        reasons.append(
            "1H momentum↑"
        )

    return score, reasons


# ============================================================
# ANA ANALİZ
# ============================================================

def analyze(symbol):

    try:

        c15 = klines(
            symbol,
            "Min15",
            120
        )

        c1 = klines(
            symbol,
            "Hour1",
            120
        )

        c4 = klines(
            symbol,
            "Hour4",
            120
        )

        if (
            len(c15) < 60
            or len(c1) < 60
            or len(c4) < 60
        ):
            return None

        close15 = [
            x["close"]
            for x in c15
        ]

        close1 = [
            x["close"]
            for x in c1
        ]

        close4 = [
            x["close"]
            for x in c4
        ]

        price = close15[-1]

        # ====================================================
        # RSI
        # ====================================================

        r15 = RSI(close15)
        r1 = RSI(close1)
        r4 = RSI(close4)

        if None in (r15, r1, r4):
            return None

        # ====================================================
        # HACİM
        # ====================================================

        v15 = volume_ratio(c15)
        v1 = volume_ratio(c1)
        v4 = volume_ratio(c4)

        # ====================================================
        # HAREKET
        # ====================================================

        p15 = change(c15, 4)
        p1 = change(c1, 4)
        p4 = change(c4, 4)
        p24 = change(c15, 96)

        # ====================================================
        # GEÇ KALANLARI ELE
        # ====================================================

        if p24 >= 30:
            return None

        if p4 >= 20:
            return None

        if p1 >= 15:
            return None

        if r15 >= 76:
            return None

        # ====================================================
        # SIKIŞMA
        # ====================================================

        compressed, width = compression(c4)

        # ====================================================
        # DİRENÇ
        # ====================================================

        resistance, resistance_distance = (
            resistance_info(c15)
        )

        # ====================================================
        # HIGHER LOW
        # ====================================================

        hl4 = higher_low(c4)
        hl1 = higher_low(c1)

        # ====================================================
        # MA
        # ====================================================

        ma5 = SMA(close4, 5)
        ma10 = SMA(close4, 10)
        ma30 = SMA(close4, 30)

        if None in (
            ma5,
            ma10,
            ma30
        ):
            return None

        # ====================================================
        # SKOR
        # ====================================================

        score = 0
        reasons = []

        # ----------------------------------------------------
        # 1 — SIKIŞMA
        # MAX 20
        # ----------------------------------------------------

        if compressed:

            if width <= 15:

                score += 20

                reasons.append(
                    "4H güçlü sıkışma"
                )

            else:

                score += 14

                reasons.append(
                    "4H sıkışma"
                )

        # ----------------------------------------------------
        # 2 — HACİM
        # MAX 20
        # ----------------------------------------------------

        if v15 >= 2.0:

            score += 10

            reasons.append(
                f"15M hacim {v15:.1f}x"
            )

        elif v15 >= 1.5:

            score += 5

        if v1 >= 1.8:

            score += 10

            reasons.append(
                f"1H hacim {v1:.1f}x"
            )

        elif v1 >= 1.4:

            score += 5

        # ----------------------------------------------------
        # 3 — DİRENÇ
        # MAX 20
        # ----------------------------------------------------

        if (
            0 <= resistance_distance <= 2
        ):

            score += 20

            reasons.append(
                "Direnç çok yakın"
            )

        elif (
            2 < resistance_distance <= 5
        ):

            score += 15

            reasons.append(
                "Direnç yakın"
            )

        elif (
            5 < resistance_distance <= 10
        ):

            score += 8

            reasons.append(
                "Dirence yaklaşıyor"
            )

        # ----------------------------------------------------
        # 4 — HIGHER LOW
        # MAX 15
        # ----------------------------------------------------

        if hl4:

            score += 8

            reasons.append(
                "4H higher-low"
            )

        if hl1:

            score += 7

            reasons.append(
                "1H higher-low"
            )

        # ----------------------------------------------------
        # 5 — MOMENTUM
        # MAX 15
        # ----------------------------------------------------

        ms, mr = momentum_score(
            c15,
            c1
        )

        score += ms

        reasons.extend(mr)

        # ----------------------------------------------------
        # 6 — RSI
        # MAX 10
        # ----------------------------------------------------

        # RSI sadece teyit
        if (
            52 <= r15 <= 68
            and 50 <= r1 <= 68
            and r4 >= 45
        ):

            score += 10

            reasons.append(
                "RSI üçlü uyum"
            )

        elif (
            50 <= r15 <= 70
            and 48 <= r1 <= 70
        ):

            score += 5

        # ====================================================
        # KRİTİK FİLTRELER
        # ====================================================

        # Sıkışma yoksa 75 üstü olamaz
        if not compressed:

            score = min(
                score,
                69
            )

        # Hacim yoksa sinyal yok
        if (
            v15 < 1.3
            and v1 < 1.3
        ):

            return None

        # RSI aşırı düşükse
        if r15 < 42:
            return None

        # Fiyat zaten çok hızlandıysa
        if p15 > 12:
            return None

        # ====================================================
        # MİN SKOR
        # ====================================================

        if score < MIN_SCORE:
            return None

        # ====================================================
        # STAGE
        # ====================================================

        if score >= 88:

            stage = "🔥 ÇOK GÜÇLÜ ERKEN"

        elif score >= 80:

            stage = "🚀 GÜÇLÜ ERKEN"

        else:

            stage = "⚡ ERKEN ADAY"

        # ====================================================
        # GİRİŞ
        # ====================================================

        entry_low = price * 0.997
        entry_high = price * 1.008

        # ====================================================
        # TP
        # ====================================================

        tp1 = price * 1.05
        tp2 = price * 1.10
        tp3 = price * 1.18

        # ====================================================
        # STOP
        # ====================================================

        stop = price * 0.975

        return {

            "symbol": symbol,

            "score": score,

            "stage": stage,

            "price": price,

            "r15": r15,
            "r1": r1,
            "r4": r4,

            "v15": v15,
            "v1": v1,

            "p15": p15,
            "p1": p1,
            "p4": p4,
            "p24": p24,

            "width": width,

            "resistance": resistance,
            "resistance_distance": resistance_distance,

            "entry_low": entry_low,
            "entry_high": entry_high,

            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,

            "stop": stop,

            "reasons": reasons
        }

    except Exception as e:

        return None


# ============================================================
# COOLDOWN
# ============================================================

def can_alert(symbol):

    now = time.time()

    old = last_alert.get(
        symbol,
        0
    )

    return (
        now - old
        >= COOLDOWN_MINUTES * 60
    )


# ============================================================
# TELEGRAM ALERT
# ============================================================

def send_alert(x):

    symbol = x["symbol"]

    if not can_alert(symbol):
        return

    last_alert[
        symbol
    ] = time.time()

    reason_text = "\n".join(
        [
            f"• {r}"
            for r in x["reasons"][:7]
        ]
    )

    message = f"""
<b>🚀 LSK-TİPİ ERKEN PUMP</b>

<b>{symbol}</b>

{x["stage"]}

⭐ GÜÇ: <b>{x["score"]}/100</b>

💰 Fiyat:
<b>{x["price"]:.8g}</b>

📊 RSI
15M: {x["r15"]:.1f}
1H: {x["r1"]:.1f}
4H: {x["r4"]:.1f}

📈 HACİM
15M: <b>{x["v15"]:.1f}x</b>
1H: <b>{x["v1"]:.1f}x</b>

📉 HAREKET
15M: {x["p15"]:+.1f}%
1H: {x["p1"]:+.1f}%
4H: {x["p4"]:+.1f}%
24H: {x["p24"]:+.1f}%

📦 4H SIKIŞMA
{x["width"]:.1f}%

🎯 DİRENÇ MESAFESİ
{x["resistance_distance"]:.1f}%

🎯 GİRİŞ
{x["entry_low"]:.8g}
→
{x["entry_high"]:.8g}

🥇 TP1
{x["tp1"]:.8g}

🥈 TP2
{x["tp2"]:.8g}

🥉 TP3
{x["tp3"]:.8g}

🛑 STOP
{x["stop"]:.8g}

<b>🔎 NEDEN?</b>
{reason_text}

⚠️ Otomatik teknik taramadır.
Pump garantisi değildir.
"""

    telegram(message)


# ============================================================
# SCAN
# ============================================================

def scan():

    symbols = get_symbols()

    if not symbols:

        print(
            "❌ Futures listesi alınamadı."
        )

        return

    print(
        f"🔎 {len(symbols)} Futures taranıyor..."
    )

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        jobs = {
            executor.submit(
                analyze,
                symbol
            ): symbol

            for symbol in symbols
        }

        for job in as_completed(jobs):

            try:

                result = job.result()

                if result:
                    results.append(result)

            except:
                pass

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    print(
        f"🔥 Uygun aday: {len(results)}"
    )

    for x in results[:MAX_ALERTS]:

        print(
            x["symbol"],
            x["score"]
        )

        send_alert(x)


# ============================================================
# MAIN
# ============================================================

def main():

    print("""
=========================================
🚀 MEXC PUMP RADAR V2
=========================================

LSK ÖNCESİ HAREKET RADARI

4H SIKIŞMA
+
HACİM GİRİŞİ
+
DİRENÇ
+
HIGHER LOW
+
MOMENTUM
+
RSI TEYİDİ

SADECE USDT FUTURES
=========================================
""")

    while True:

        try:

            scan()

        except Exception as e:

            print(
                "MAIN ERROR:",
                e
            )

        print(
            f"⏳ {SCAN_SECONDS} saniye..."
        )

        time.sleep(
            SCAN_SECONDS
        )


if __name__ == "__main__":
    main()
