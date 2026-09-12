import os
import json
import time
import math
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 🚀 MEXC LSK-PRE-PUMP RADAR V1
#
# AMAÇ:
# LSK gibi büyük hareketleri PUMP başlamadan önce yakalamak
#
# SADECE:
# ✅ MEXC USDT FUTURES
# ✅ 15M
# ✅ 1H
# ✅ 4H
# ✅ RSI
# ✅ HACİM
# ✅ MOMENTUM
# ✅ MA YAPISI
# ✅ SIKIŞMA
# ✅ BREAKOUT
#
# ❌ SPOT YOK
# ❌ STOCK YOK
# ❌ ZATEN PUMP YAPMIŞ COINLER YOK
#
# TELEGRAM:
# TELEGRAM_BOT_TOKEN
# TELEGRAM_CHAT_ID
# ============================================================


# ============================================================
# AYARLAR
# ============================================================

BASE = "https://api.mexc.com"

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SCAN_SECONDS = 60

MAX_WORKERS = 12

# Aynı coin tekrar tekrar Telegram'a düşmesin
COOLDOWN_MINUTES = 30

# Minimum skor
MIN_SCORE = 72

# Telegram'a maksimum coin
MAX_ALERTS = 8


# ============================================================
# HTTP SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
})


# ============================================================
# CACHE
# ============================================================

last_alert = {}

symbol_cache = None


# ============================================================
# SAFE GET
# ============================================================

def get(url, params=None, timeout=10):

    try:

        r = SESSION.get(
            url,
            params=params,
            timeout=timeout
        )

        if r.status_code != 200:
            return None

        data = r.json()

        return data

    except Exception:
        return None


# ============================================================
# TELEGRAM
# ============================================================

def telegram(text):

    if not TOKEN or not CHAT_ID:
        print(text)
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:

        SESSION.post(
            url,
            json=payload,
            timeout=10
        )

    except Exception as e:

        print("Telegram error:", e)


# ============================================================
# FUTURES SYMBOLLER
# ============================================================

def get_symbols():

    global symbol_cache

    # Cache kullan
    if symbol_cache:
        return symbol_cache

    data = get(
        f"{BASE}/api/v1/contract/detail"
    )

    if not data:
        return []

    result = []

    rows = data.get("data", [])

    for x in rows:

        symbol = x.get("symbol", "")

        # ----------------------------------------------------
        # SADECE USDT
        # ----------------------------------------------------

        if not symbol.endswith("_USDT"):
            continue

        # ----------------------------------------------------
        # ENABLED / OPEN
        # ----------------------------------------------------

        state = x.get("state")

        if state is not None:

            try:

                if int(state) != 0:
                    continue

            except:
                pass

        # ----------------------------------------------------
        # STOCK / AKTİF OLMAYAN / SADECE TEST VB.
        # ----------------------------------------------------

        if not symbol:
            continue

        result.append(symbol)

    symbol_cache = result

    print(
        f"📡 Futures sembol sayısı: {len(result)}"
    )

    return result


# ============================================================
# KLINE
# ============================================================

def get_klines(symbol, interval, limit=120):

    data = get(
        f"{BASE}/api/v1/contract/kline/{symbol}",
        params={
            "interval": interval,
            "limit": limit
        }
    )

    if not data:
        return []

    rows = data.get("data")

    if not rows:
        return []

    # MEXC response formatı bazı sürümlerde dict
    if isinstance(rows, dict):

        times = rows.get("time", [])
        opens = rows.get("open", [])
        highs = rows.get("high", [])
        lows = rows.get("low", [])
        closes = rows.get("close", [])
        vols = rows.get("vol", [])

        candles = []

        for i in range(
            min(
                len(times),
                len(opens),
                len(highs),
                len(lows),
                len(closes),
                len(vols)
            )
        ):

            candles.append({
                "time": float(times[i]),
                "open": float(opens[i]),
                "high": float(highs[i]),
                "low": float(lows[i]),
                "close": float(closes[i]),
                "volume": float(vols[i])
            })

        return candles

    # Liste formatı
    if isinstance(rows, list):

        candles = []

        for row in rows:

            try:

                if len(row) < 6:
                    continue

                candles.append({
                    "time": float(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5])
                })

            except:
                continue

        return candles

    return []


# ============================================================
# RSI
# ============================================================

def rsi(closes, period=14):

    if len(closes) < period + 2:
        return None

    gains = []
    losses = []

    for i in range(1, len(closes)):

        diff = closes[i] - closes[i - 1]

        gains.append(
            max(diff, 0)
        )

        losses.append(
            max(-diff, 0)
        )

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

def sma(values, period):

    if len(values) < period:
        return None

    return sum(
        values[-period:]
    ) / period


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (
        period + 1
    )

    result = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        result = (
            price - result
        ) * multiplier + result

    return result


# ============================================================
# VOLUME RATIO
# ============================================================

def volume_ratio(candles, lookback=20):

    if len(candles) < lookback + 1:
        return 0

    current = candles[-1]["volume"]

    previous = [
        x["volume"]
        for x in candles[-lookback-1:-1]
    ]

    avg = sum(previous) / len(previous)

    if avg <= 0:
        return 0

    return current / avg


# ============================================================
# PRICE CHANGE
# ============================================================

def change_percent(candles, bars):

    if len(candles) <= bars:
        return 0

    old = candles[-bars-1]["close"]

    new = candles[-1]["close"]

    if old <= 0:
        return 0

    return (
        (new - old) / old
    ) * 100


# ============================================================
# ATR
# ============================================================

def atr(candles, period=14):

    if len(candles) < period + 2:
        return None

    trs = []

    for i in range(1, len(candles)):

        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i - 1]["close"]

        tr = max(
            h - l,
            abs(h - pc),
            abs(l - pc)
        )

        trs.append(tr)

    return sum(
        trs[-period:]
    ) / period


# ============================================================
# SIKIŞMA
# ============================================================

def compression(candles, lookback=20):

    if len(candles) < lookback:
        return False, 0

    recent = candles[-lookback:]

    highs = [
        x["high"]
        for x in recent
    ]

    lows = [
        x["low"]
        for x in recent
    ]

    highest = max(highs)

    lowest = min(lows)

    if lowest <= 0:
        return False, 0

    width = (
        (highest - lowest)
        / lowest
    ) * 100

    # Dar bant
    compressed = width <= 18

    return compressed, width


# ============================================================
# BREAKOUT
# ============================================================

def breakout(candles):

    if len(candles) < 25:
        return False, 0

    current = candles[-1]

    previous = candles[-21:-1]

    resistance = max(
        x["high"]
        for x in previous
    )

    price = current["close"]

    if resistance <= 0:
        return False, 0

    distance = (
        (price - resistance)
        / resistance
    ) * 100

    return (
        price >= resistance * 0.995,
        distance
    )


# ============================================================
# HIGHER LOW
# ============================================================

def higher_low(candles):

    if len(candles) < 12:
        return False

    a = candles[-12:-6]
    b = candles[-6:]

    low_a = min(
        x["low"]
        for x in a
    )

    low_b = min(
        x["low"]
        for x in b
    )

    return low_b > low_a


# ============================================================
# TEKNİK ANALİZ
# ============================================================

def analyze(symbol):

    try:

        c15 = get_klines(
            symbol,
            "Min15",
            100
        )

        c1h = get_klines(
            symbol,
            "Hour1",
            100
        )

        c4h = get_klines(
            symbol,
            "Hour4",
            100
        )

        if (
            len(c15) < 40
            or len(c1h) < 40
            or len(c4h) < 40
        ):
            return None

        # ====================================================
        # FİYAT
        # ====================================================

        price = c15[-1]["close"]

        # ====================================================
        # RSI
        # ====================================================

        rsi15 = rsi([
            x["close"]
            for x in c15
        ])

        rsi1h = rsi([
            x["close"]
            for x in c1h
        ])

        rsi4h = rsi([
            x["close"]
            for x in c4h
        ])

        if (
            rsi15 is None
            or rsi1h is None
            or rsi4h is None
        ):
            return None

        # ====================================================
        # HACİM
        # ====================================================

        vol15 = volume_ratio(
            c15,
            20
        )

        vol1h = volume_ratio(
            c1h,
            20
        )

        vol4h = volume_ratio(
            c4h,
            20
        )

        # ====================================================
        # 4H MA
        # ====================================================

        close4 = [
            x["close"]
            for x in c4h
        ]

        ma5 = sma(
            close4,
            5
        )

        ma10 = sma(
            close4,
            10
        )

        ma30 = sma(
            close4,
            30
        )

        ma60 = sma(
            close4,
            60
        )

        if None in (
            ma5,
            ma10,
            ma30,
            ma60
        ):
            return None

        # ====================================================
        # 4H SIKIŞMA
        # ====================================================

        is_compressed, width = compression(
            c4h,
            20
        )

        # ====================================================
        # HIGHER LOW
        # ====================================================

        hl4 = higher_low(c4h)

        hl1 = higher_low(c1h)

        # ====================================================
        # BREAKOUT
        # ====================================================

        br15, br15_distance = breakout(
            c15
        )

        br1h, br1h_distance = breakout(
            c1h
        )

        # ====================================================
        # SON HAREKET
        # ====================================================

        move15 = change_percent(
            c15,
            4
        )

        move1h = change_percent(
            c1h,
            4
        )

        move4h = change_percent(
            c4h,
            4
        )

        move24 = change_percent(
            c15,
            96
        )

        # ====================================================
        # ÇOK GEÇ KALMIŞ COINLERİ ELE
        # ====================================================

        if move24 > 45:
            return None

        if move4h > 30:
            return None

        if move1h > 20:
            return None

        # ====================================================
        # SCORE
        # ====================================================

        score = 0

        reasons = []

        # ----------------------------------------------------
        # 4H SIKIŞMA
        # ----------------------------------------------------

        if is_compressed:

            score += 16

            reasons.append(
                "4H sıkışma"
            )

        elif width <= 25:

            score += 8

            reasons.append(
                "4H dar bant"
            )

        # ----------------------------------------------------
        # MA YAPISI
        # ----------------------------------------------------

        if ma5 > ma10:

            score += 10

            reasons.append(
                "MA5>MA10"
            )

        if ma10 > ma30:

            score += 7

            reasons.append(
                "MA10>MA30"
            )

        if price > ma30:

            score += 6

            reasons.append(
                "MA30 üstü"
            )

        # ----------------------------------------------------
        # HIGHER LOW
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
        # HACİM
        # ----------------------------------------------------

        if vol15 >= 1.8:

            score += 8

            reasons.append(
                f"15M hacim {vol15:.1f}x"
            )

        if vol15 >= 2.5:

            score += 4

        if vol1h >= 1.8:

            score += 10

            reasons.append(
                f"1H hacim {vol1h:.1f}x"
            )

        if vol4h >= 1.4:

            score += 5

        # ----------------------------------------------------
        # RSI
        # ----------------------------------------------------

        if 52 <= rsi15 <= 75:

            score += 8

            reasons.append(
                f"15M RSI {rsi15:.0f}"
            )

        if 50 <= rsi1h <= 70:

            score += 8

            reasons.append(
                f"1H RSI {rsi1h:.0f}"
            )

        if 45 <= rsi4h <= 68:

            score += 5

        # ----------------------------------------------------
        # BREAKOUT
        # ----------------------------------------------------

        if br15:

            score += 10

            reasons.append(
                "15M kırılım"
            )

        if br1h:

            score += 8

            reasons.append(
                "1H kırılım"
            )

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------

        if 1 <= move15 <= 10:

            score += 5

            reasons.append(
                "15M momentum"
            )

        if 2 <= move1h <= 15:

            score += 5

            reasons.append(
                "1H momentum"
            )

        # ----------------------------------------------------
        # AŞIRI DÜŞÜŞÜ ENGELLE
        # ----------------------------------------------------

        if rsi15 < 35:
            score -= 10

        if rsi1h < 40:
            score -= 5

        # ====================================================
        # SONUÇ
        # ====================================================

        if score < MIN_SCORE:
            return None

        # ====================================================
        # GİRİŞ / TP
        # ====================================================

        atr15 = atr(
            c15,
            14
        )

        if atr15 is None:
            atr15 = price * 0.01

        entry_low = price

        entry_high = price * 1.008

        tp1 = price * 1.06
        tp2 = price * 1.12
        tp3 = price * 1.20

        stop = price - (
            atr15 * 1.5
        )

        # ====================================================
        # PUMP STAGE
        # ====================================================

        if score >= 90:
            stage = "🔥 ÇOK GÜÇLÜ"

        elif score >= 82:
            stage = "🚀 GÜÇLÜ"

        else:
            stage = "⚡ ERKEN"

        return {
            "symbol": symbol,
            "price": price,
            "score": score,
            "stage": stage,

            "rsi15": rsi15,
            "rsi1h": rsi1h,
            "rsi4h": rsi4h,

            "vol15": vol15,
            "vol1h": vol1h,
            "vol4h": vol4h,

            "move15": move15,
            "move1h": move1h,
            "move4h": move4h,
            "move24": move24,

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

    last = last_alert.get(
        symbol,
        0
    )

    if (
        now - last
        < COOLDOWN_MINUTES * 60
    ):
        return False

    return True


# ============================================================
# ALERT
# ============================================================

def send_alert(x):

    symbol = x["symbol"]

    if not can_alert(symbol):
        return

    last_alert[
        symbol
    ] = time.time()

    reasons = " • ".join(
        x["reasons"][:6]
    )

    message = f"""
<b>🚨 LSK TİPİ ERKEN PUMP RADAR</b>

<b>{symbol}</b>

<b>{x["stage"]}</b>
Skor: <b>{x["score"]}/100</b>

💰 Fiyat:
<b>{x["price"]:.8g}</b>

📊 RSI
15M: <b>{x["rsi15"]:.1f}</b>
1H: <b>{x["rsi1h"]:.1f}</b>
4H: <b>{x["rsi4h"]:.1f}</b>

📈 HACİM
15M: <b>{x["vol15"]:.1f}x</b>
1H: <b>{x["vol1h"]:.1f}x</b>

🚀 Hareket
15M: {x["move15"]:+.1f}%
1H: {x["move1h"]:+.1f}%
4H: {x["move4h"]:+.1f}%
24H: {x["move24"]:+.1f}%

🎯 GİRİŞ
{x["entry_low"]:.8g}
→
{x["entry_high"]:.8g}

🎯 TP1
{x["tp1"]:.8g}

🎯 TP2
{x["tp2"]:.8g}

🎯 TP3
{x["tp3"]:.8g}

🛑 Teknik stop:
{x["stop"]:.8g}

🔎 Yapı:
{reasons}

⚠️ Bu sinyal pump garantisi değildir.
Amaç: hareketin erken aşamasını yakalamaktır.
"""

    telegram(
        message
    )


# ============================================================
# SCAN
# ============================================================

def scan():

    symbols = get_symbols()

    if not symbols:

        print(
            "❌ Futures sembolleri alınamadı."
        )

        return

    results = []

    print(
        f"\n🔍 {len(symbols)} Futures taranıyor..."
    )

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze,
                symbol
            ): symbol

            for symbol in symbols
        }

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                if result:
                    results.append(result)

            except Exception:
                pass

    # ========================================================
    # SCORE SIRALAMA
    # ========================================================

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    # ========================================================
    # SADECE EN İYİLER
    # ========================================================

    selected = results[
        :MAX_ALERTS
    ]

    print(
        f"🔥 Uygun aday: {len(results)}"
    )

    for x in selected:

        print(
            x["symbol"],
            x["score"],
            x["price"]
        )

        send_alert(
            x
        )


# ============================================================
# MAIN LOOP
# ============================================================

def main():

    print(
        """
=========================================
🚀 MEXC LSK-PRE-PUMP RADAR V1
=========================================

15M + 1H + 4H
RSI + HACİM + MA + MOMENTUM
SIKIŞMA + BREAKOUT
EARLY PUMP DETECTION

Sadece USDT Futures

=========================================
"""
    )

    while True:

        try:

            scan()

        except Exception as e:

            print(
                "SCAN ERROR:",
                e
            )

        print(
            f"\n⏳ {SCAN_SECONDS} saniye bekleniyor..."
        )

        time.sleep(
            SCAN_SECONDS
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
