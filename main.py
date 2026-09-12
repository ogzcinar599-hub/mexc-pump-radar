import os
import time
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PUMP RADAR V4.2
#
# AMAÇ:
# LSK gibi büyük pump'lardan ÖNCE oluşan yapıları bulmak.
#
# 4H  = ANA YAPI
# 1H  = GÜÇ TEYİDİ
# 15M = TETİK / GİRİŞ HAZIRLIĞI
#
# SADECE MEXC USDT FUTURES
# SADECE SİNYAL
# OTOMATİK İŞLEM AÇMAZ
# ============================================================


BASE = "https://api.mexc.com"

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# AYARLAR
# ============================================================

MAX_WORKERS = 5

MAX_ALERTS = 6

MIN_SCORE = 70

CANDLE_COUNT = 80

REQUEST_TIMEOUT = 12

# MEXC API'yi gereksiz zorlamamak için
REQUEST_INTERVAL = 0.11


INTERVAL_SECONDS = {
    "Min15": 15 * 60,
    "Min60": 60 * 60,
    "Hour4": 4 * 60 * 60
}


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 MEXC-Pump-Radar",
    "Accept": "application/json"
})


# ============================================================
# RATE LIMIT
# ============================================================

rate_lock = threading.Lock()
last_request = 0.0


def wait_rate():

    global last_request

    with rate_lock:

        now = time.time()

        wait = REQUEST_INTERVAL - (
            now - last_request
        )

        if wait > 0:
            time.sleep(wait)

        last_request = time.time()


# ============================================================
# İSTATİSTİK
# ============================================================

stats = {
    "api_ok": 0,
    "api_error": 0,
    "kline_ok": 0,
    "four_h": 0,
    "one_h": 0,
    "fifteen_m": 0,
    "final": 0
}

stats_lock = threading.Lock()


# ============================================================
# MEXC REQUEST
# ============================================================

def mexc_get(path, params=None, retries=3):

    for attempt in range(retries):

        try:

            wait_rate()

            url = BASE + path

            response = session.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            # ------------------------------------------------
            # RATE LIMIT
            # ------------------------------------------------

            if response.status_code == 429:

                print(
                    "⚠️ Rate limit - bekleniyor..."
                )

                time.sleep(
                    1.5 * (attempt + 1)
                )

                continue

            # ------------------------------------------------
            # HTTP HATA
            # ------------------------------------------------

            if response.status_code != 200:

                if attempt == retries - 1:

                    print(
                        f"❌ HTTP {response.status_code} "
                        f"{path}"
                    )

                time.sleep(0.5)

                continue

            # ------------------------------------------------
            # JSON
            # ------------------------------------------------

            data = response.json()

            if not isinstance(data, dict):

                continue

            # ------------------------------------------------
            # MEXC SUCCESS
            # ------------------------------------------------

            if data.get("success") is False:

                if attempt == retries - 1:

                    print(
                        f"❌ MEXC API: "
                        f"{data}"
                    )

                continue

            with stats_lock:

                stats["api_ok"] += 1

            return data

        except Exception as e:

            if attempt == retries - 1:

                print(
                    f"❌ Request hatası: {e}"
                )

            time.sleep(0.5)

    with stats_lock:

        stats["api_error"] += 1

    return None


# ============================================================
# FUTURES SEMBOLLERİ
# ============================================================

def get_symbols():

    print()
    print("📡 MEXC FUTURES SEMBOLLERİ ALINIYOR")

    data = mexc_get(
        "/api/v1/contract/detail"
    )

    if not data:

        print(
            "❌ Futures sembolleri alınamadı"
        )

        return []

    rows = data.get(
        "data",
        []
    )

    symbols = []

    for item in rows:

        symbol = item.get(
            "symbol",
            ""
        )

        if not symbol.endswith("_USDT"):
            continue

        # Sadece aktif kontratlar
        state = item.get("state")

        if state is not None:

            try:

                if int(state) != 0:
                    continue

            except Exception:

                pass

        symbols.append(symbol)

    symbols = list(
        dict.fromkeys(symbols)
    )

    print(
        f"✅ Futures sembol sayısı: "
        f"{len(symbols)}"
    )

    return symbols


# ============================================================
# KLINE
# ============================================================

def get_klines(
    symbol,
    interval,
    count=CANDLE_COUNT
):

    seconds = INTERVAL_SECONDS[
        interval
    ]

    end = int(
        time.time()
    )

    start = end - (
        seconds * count
    )

    params = {
        "interval": interval,
        "start": start,
        "end": end
    }

    data = mexc_get(
        f"/api/v1/contract/kline/{symbol}",
        params
    )

    if not data:
        return None

    raw = data.get(
        "data"
    )

    if not isinstance(raw, dict):
        return None

    try:

        times = raw.get(
            "time",
            []
        )

        opens = raw.get(
            "open",
            []
        )

        closes = raw.get(
            "close",
            []
        )

        highs = raw.get(
            "high",
            []
        )

        lows = raw.get(
            "low",
            []
        )

        volumes = raw.get(
            "vol",
            []
        )

        length = min(
            len(times),
            len(opens),
            len(closes),
            len(highs),
            len(lows),
            len(volumes)
        )

        if length < 35:

            return None

        candles = []

        for i in range(length):

            candles.append({

                "time": float(
                    times[i]
                ),

                "open": float(
                    opens[i]
                ),

                "close": float(
                    closes[i]
                ),

                "high": float(
                    highs[i]
                ),

                "low": float(
                    lows[i]
                ),

                "vol": float(
                    volumes[i]
                )

            })

        candles.sort(
            key=lambda x: x["time"]
        )

        with stats_lock:

            stats["kline_ok"] += 1

        return candles

    except Exception:

        return None


# ============================================================
# RSI
# ============================================================

def calculate_rsi(
    closes,
    period=14
):

    if len(closes) < period + 1:

        return 50.0

    gains = []
    losses = []

    for i in range(
        1,
        len(closes)
    ):

        diff = (
            closes[i]
            - closes[i - 1]
        )

        if diff > 0:

            gains.append(diff)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(diff)
            )

    avg_gain = (
        sum(gains[-period:])
        / period
    )

    avg_loss = (
        sum(losses[-period:])
        / period
    )

    if avg_loss == 0:

        return 100.0

    rs = (
        avg_gain
        / avg_loss
    )

    return (
        100
        - (
            100
            / (1 + rs)
        )
    )


# ============================================================
# SMA
# ============================================================

def sma(
    values,
    period
):

    if len(values) < period:

        return (
            sum(values)
            / len(values)
        )

    return (
        sum(values[-period:])
        / period
    )


# ============================================================
# DEĞİŞİM
# ============================================================

def change_pct(
    values,
    bars
):

    if len(values) <= bars:

        return 0.0

    old = values[
        -bars - 1
    ]

    if old == 0:

        return 0.0

    return (
        (
            values[-1]
            / old
        ) - 1
    ) * 100


# ============================================================
# HACİM ORANI
# ============================================================

def volume_ratio(
    volumes,
    recent=5,
    base=30
):

    if len(volumes) < (
        recent + base
    ):

        return 1.0

    recent_avg = (
        sum(volumes[-recent:])
        / recent
    )

    base_values = volumes[
        -(base + recent):-recent
    ]

    if not base_values:

        return 1.0

    base_avg = (
        sum(base_values)
        / len(base_values)
    )

    if base_avg <= 0:

        return 1.0

    return (
        recent_avg
        / base_avg
    )


# ============================================================
# COMPRESSION
# ============================================================

def compression(
    candles
):

    if len(candles) < 40:

        return 0, 0

    recent = candles[-20:]

    previous = candles[-40:-20]

    recent_high = max(
        x["high"]
        for x in recent
    )

    recent_low = min(
        x["low"]
        for x in recent
    )

    previous_high = max(
        x["high"]
        for x in previous
    )

    previous_low = min(
        x["low"]
        for x in previous
    )

    recent_mid = (
        recent_high
        + recent_low
    ) / 2

    previous_mid = (
        previous_high
        + previous_low
    ) / 2

    if (
        recent_mid <= 0
        or previous_mid <= 0
    ):

        return 0, 0

    recent_width = (
        (
            recent_high
            - recent_low
        )
        / recent_mid
    ) * 100

    previous_width = (
        (
            previous_high
            - previous_low
        )
        / previous_mid
    ) * 100

    if previous_width <= 0:

        return 0, recent_width

    contraction = (
        1
        - (
            recent_width
            / previous_width
        )
    )

    if contraction >= 0.45:

        score = 20

    elif contraction >= 0.35:

        score = 18

    elif contraction >= 0.25:

        score = 15

    elif contraction >= 0.15:

        score = 11

    elif contraction >= 0.08:

        score = 7

    else:

        score = 0

    return score, recent_width


# ============================================================
# HIGHER LOW
# ============================================================

def higher_low(
    candles
):

    if len(candles) < 30:

        return 0

    lows = [
        x["low"]
        for x in candles[-30:]
    ]

    first_low = min(
        lows[:15]
    )

    second_low = min(
        lows[15:]
    )

    if second_low > first_low * 1.02:

        return 15

    if second_low > first_low * 1.012:

        return 12

    if second_low > first_low * 1.005:

        return 8

    if second_low > first_low:

        return 5

    return 0


# ============================================================
# MA YAPISI
# ============================================================

def ma_score(
    candles
):

    closes = [
        x["close"]
        for x in candles
    ]

    ma5 = sma(
        closes,
        5
    )

    ma10 = sma(
        closes,
        10
    )

    ma20 = sma(
        closes,
        20
    )

    ma30 = sma(
        closes,
        30
    )

    score = 0

    if ma5 > ma10:

        score += 3

    if ma10 > ma20:

        score += 3

    if ma20 > ma30:

        score += 4

    if closes[-1] > ma20:

        score += 3

    return score


# ============================================================
# DİRENÇ
# ============================================================

def resistance(
    candles
):

    if len(candles) < 30:

        return 0, 99

    price = candles[-1][
        "close"
    ]

    previous_highs = [
        x["high"]
        for x in candles[-25:-1]
    ]

    if not previous_highs:

        return 0, 99

    level = max(
        previous_highs
    )

    if price <= 0:

        return 0, 99

    distance = (
        (
            level
            - price
        )
        / price
    ) * 100

    if distance <= 0:

        return 5, 0

    if distance <= 1.5:

        return 20, distance

    if distance <= 3:

        return 18, distance

    if distance <= 5:

        return 15, distance

    if distance <= 8:

        return 10, distance

    if distance <= 12:

        return 5, distance

    return 0, distance


# ============================================================
# 4H ANALİZ
# ============================================================

def analyze_4h(
    symbol
):

    candles = get_klines(
        symbol,
        "Hour4"
    )

    if not candles:

        return None

    closes = [
        x["close"]
        for x in candles
    ]

    volumes = [
        x["vol"]
        for x in candles
    ]

    price = closes[-1]

    rsi4 = calculate_rsi(
        closes
    )

    change24 = change_pct(
        closes,
        6
    )

    change4 = change_pct(
        closes,
        1
    )

    # --------------------------------------------------------
    # ZATEN PUMP YAPMIŞ COINLERİ ELE
    # --------------------------------------------------------

    if change24 >= 28:

        return None

    if change4 >= 18:

        return None

    if rsi4 >= 76:

        return None

    # --------------------------------------------------------
    # SIKIŞMA
    # --------------------------------------------------------

    comp_score, width = compression(
        candles
    )

    if comp_score < 7:

        return None

    # --------------------------------------------------------
    # HIGHER LOW
    # --------------------------------------------------------

    hl = higher_low(
        candles
    )

    if hl < 5:

        return None

    # --------------------------------------------------------
    # MA
    # --------------------------------------------------------

    ma = ma_score(
        candles
    )

    # --------------------------------------------------------
    # DİRENÇ
    # --------------------------------------------------------

    resistance_score, resistance_distance = resistance(
        candles
    )

    if resistance_distance > 12:

        return None

    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    vol4 = volume_ratio(
        volumes,
        5,
        30
    )

    vol_score = 0

    if vol4 >= 2.5:

        vol_score = 15

    elif vol4 >= 2:

        vol_score = 12

    elif vol4 >= 1.6:

        vol_score = 9

    elif vol4 >= 1.3:

        vol_score = 6

    # --------------------------------------------------------
    # PUAN
    # --------------------------------------------------------

    score = (
        comp_score
        + hl
        + ma
        + resistance_score
        + vol_score
    )

    # RSI sadece küçük bonus
    if 50 <= rsi4 <= 68:

        score += 7

    elif 45 <= rsi4 <= 72:

        score += 4

    if score < 35:

        return None

    with stats_lock:

        stats["four_h"] += 1

    return {

        "symbol": symbol,

        "price": price,

        "rsi4": rsi4,

        "change24": change24,

        "change4": change4,

        "compression": width,

        "comp_score": comp_score,

        "higher_low": hl,

        "ma_score": ma,

        "resistance_score": resistance_score,

        "resistance_distance": resistance_distance,

        "vol4": vol4,

        "score4": score

    }


# ============================================================
# 1H ANALİZ
# ============================================================

def analyze_1h(
    candidate
):

    symbol = candidate[
        "symbol"
    ]

    candles = get_klines(
        symbol,
        "Min60"
    )

    if not candles:

        return None

    closes = [
        x["close"]
        for x in candles
    ]

    volumes = [
        x["vol"]
        for x in candles
    ]

    price = closes[-1]

    rsi1 = calculate_rsi(
        closes
    )

    change1 = change_pct(
        closes,
        1
    )

    change4bars = change_pct(
        closes,
        4
    )

    vol1 = volume_ratio(
        volumes,
        4,
        30
    )

    hl1 = higher_low(
        candles
    )

    score = candidate[
        "score4"
    ]

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if 50 <= rsi1 <= 68:

        score += 8

    elif 45 <= rsi1 <= 72:

        score += 4

    else:

        score -= 4

    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    if vol1 >= 3:

        score += 16

    elif vol1 >= 2.3:

        score += 13

    elif vol1 >= 1.8:

        score += 10

    elif vol1 >= 1.4:

        score += 6

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if 0.2 <= change1 <= 6:

        score += 10

    elif 0 <= change1 < 0.2:

        score += 5

    elif change1 > 9:

        score -= 8

    # --------------------------------------------------------
    # SON 4 SAAT
    # --------------------------------------------------------

    if 0 <= change4bars <= 8:

        score += 5

    elif change4bars > 12:

        score -= 8

    # --------------------------------------------------------
    # HIGHER LOW
    # --------------------------------------------------------

    if hl1 >= 12:

        score += 8

    elif hl1 >= 7:

        score += 5

    # --------------------------------------------------------
    # AŞIRI PUMP
    # --------------------------------------------------------

    if change1 >= 15:

        return None

    if rsi1 >= 75:

        return None

    if score < 50:

        return None

    candidate.update({

        "price": price,

        "rsi1": rsi1,

        "change1": change1,

        "change4bars": change4bars,

        "vol1": vol1,

        "hl1": hl1,

        "score1": score

    })

    with stats_lock:

        stats["one_h"] += 1

    return candidate


# ============================================================
# 15M ANALİZ
# ============================================================

def analyze_15m(
    candidate
):

    symbol = candidate[
        "symbol"
    ]

    candles = get_klines(
        symbol,
        "Min15"
    )

    if not candles:

        return None

    closes = [
        x["close"]
        for x in candles
    ]

    highs = [
        x["high"]
        for x in candles
    ]

    volumes = [
        x["vol"]
        for x in candles
    ]

    price = closes[-1]

    rsi15 = calculate_rsi(
        closes
    )

    change15 = change_pct(
        closes,
        1
    )

    change1h = change_pct(
        closes,
        4
    )

    vol15 = volume_ratio(
        volumes,
        3,
        30
    )

    score = candidate[
        "score1"
    ]

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if 52 <= rsi15 <= 68:

        score += 8

    elif 48 <= rsi15 <= 72:

        score += 4

    else:

        score -= 3

    # --------------------------------------------------------
    # 15M HACİM
    # --------------------------------------------------------

    if vol15 >= 4:

        score += 20

    elif vol15 >= 3:

        score += 17

    elif vol15 >= 2.3:

        score += 13

    elif vol15 >= 1.7:

        score += 9

    elif vol15 >= 1.3:

        score += 4

    # --------------------------------------------------------
    # 15M MOMENTUM
    # --------------------------------------------------------

    if 0.2 <= change15 <= 4:

        score += 9

    elif 0 <= change15 < 0.2:

        score += 3

    elif change15 > 7:

        score -= 10

    # --------------------------------------------------------
    # SON 1 SAATTE PUMP
    # --------------------------------------------------------

    if change1h >= 10:

        return None

    # --------------------------------------------------------
    # 15M DİRENÇ
    # --------------------------------------------------------

    previous_highs = highs[
        -13:-1
    ]

    if previous_highs:

        resistance15 = max(
            previous_highs
        )

        distance15 = (
            (
                resistance15
                - price
            )
            / price
        ) * 100

    else:

        distance15 = 99

    if distance15 <= 1:

        score += 10

    elif distance15 <= 2.5:

        score += 8

    elif distance15 <= 5:

        score += 4

    # --------------------------------------------------------
    # AŞIRI RSI
    # --------------------------------------------------------

    if rsi15 >= 78:

        return None

    # --------------------------------------------------------
    # FINAL PUAN
    # --------------------------------------------------------

    score = min(
        int(score),
        100
    )

    if score < MIN_SCORE:

        return None

    candidate.update({

        "price": price,

        "rsi15": rsi15,

        "change15": change15,

        "change1h15": change1h,

        "vol15": vol15,

        "distance15": distance15,

        "score": score

    })

    with stats_lock:

        stats["fifteen_m"] += 1

    return candidate


# ============================================================
# PARALEL TARAMA
# ============================================================

def parallel_scan(
    items,
    function
):

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                function,
                item
            )
            for item in items
        ]

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                if result:

                    results.append(
                        result
                    )

            except Exception:

                pass

    return results


# ============================================================
# TP / STOP
# ============================================================

def levels(price):

    stop = price * 0.982

    tp1 = price * 1.04

    tp2 = price * 1.07

    tp3 = price * 1.11

    return (
        stop,
        tp1,
        tp2,
        tp3
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(
    message
):

    if not TOKEN or not CHAT_ID:

        print(
            "⚠️ Telegram secrets yok"
        )

        return False

    url = (
        "https://api.telegram.org/bot"
        + TOKEN
        + "/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=15
        )

        if response.status_code == 200:

            print(
                "📨 Telegram gönderildi"
            )

            return True

        print(
            "❌ Telegram:",
            response.text[:300]
        )

    except Exception as e:

        print(
            "❌ Telegram hatası:",
            e
        )

    return False


# ============================================================
# TELEGRAM MESAJ
# ============================================================

def make_message(
    c
):

    price = c["price"]

    stop, tp1, tp2, tp3 = levels(
        price
    )

    reasons = []

    if c["comp_score"] >= 14:

        reasons.append(
            "4H sıkışma"
        )

    if c["higher_low"] >= 10:

        reasons.append(
            "Higher-Low"
        )

    if c["ma_score"] >= 9:

        reasons.append(
            "MA yapı"
        )

    if c["vol4"] >= 1.6:

        reasons.append(
            "4H hacim"
        )

    if c["vol1"] >= 2:

        reasons.append(
            "1H hacim"
        )

    if c["vol15"] >= 2:

        reasons.append(
            "15M hacim"
        )

    if c["distance15"] <= 3:

        reasons.append(
            "15M direnç yakın"
        )

    reason_text = (
        " • ".join(reasons)
        if reasons
        else "Erken yapı"
    )

    return f"""
🚨 LSK TİPİ PRE-PUMP

🪙 {c['symbol']}

⭐ GÜÇ: {c['score']}/100

💰 Fiyat:
{price:.10g}

━━━━━━━━━━━━━━

📊 RSI

15M : {c['rsi15']:.1f}
1H  : {c['rsi1']:.1f}
4H  : {c['rsi4']:.1f}

📈 HACİM

15M : {c['vol15']:.2f}x
1H  : {c['vol1']:.2f}x
4H  : {c['vol4']:.2f}x

📈 HAREKET

15M : {c['change15']:+.2f}%
1H  : {c['change1']:+.2f}%
4H  : {c['change4']:+.2f}%
24H : {c['change24']:+.2f}%

━━━━━━━━━━━━━━

📦 4H SIKIŞMA

Alan:
{c['compression']:.2f}%

🎯 DİRENÇ

4H:
%{c['resistance_distance']:.2f}

15M:
%{c['distance15']:.2f}

━━━━━━━━━━━━━━

🔥 NEDEN?

{reason_text}

━━━━━━━━━━━━━━

🎯 REFERANS

Giriş:
{price:.10g}

TP1:
{tp1:.10g}

TP2:
{tp2:.10g}

TP3:
{tp3:.10g}

Stop:
{stop:.10g}

━━━━━━━━━━━━━━

⚠️ Teknik radar sinyalidir.
Otomatik işlem açmaz.
"""


# ============================================================
# MAIN
# ============================================================

def main():

    start_time = time.time()

    print()
    print("=" * 60)
    print("🚀 MEXC LSK PRE-PUMP RADAR V4.2")
    print("=" * 60)

    if TOKEN:

        print(
            "✅ TELEGRAM_BOT_TOKEN bulundu"
        )

    else:

        print(
            "❌ TELEGRAM_BOT_TOKEN YOK"
        )

    if CHAT_ID:

        print(
            "✅ TELEGRAM_CHAT_ID bulundu"
        )

    else:

        print(
            "❌ TELEGRAM_CHAT_ID YOK"
        )

    # ========================================================
    # SEMBOLLER
    # ========================================================

    symbols = get_symbols()

    if not symbols:

        print(
            "❌ Futures coin bulunamadı"
        )

        return

    # ========================================================
    # API TEST
    # ========================================================

    print()
    print("🧪 KLINE API TESTİ")

    test = get_klines(
        "BTC_USDT",
        "Min15",
        20
    )

    if not test:

        print(
            "❌ Kline API başarısız"
        )

        return

    print(
        f"✅ Kline çalışıyor: "
        f"{len(test)} mum"
    )

    # ========================================================
    # 4H
    # ========================================================

    print()
    print(
        f"🔎 4H ANA YAPI: "
        f"{len(symbols)} coin"
    )

    four_h = parallel_scan(
        symbols,
        analyze_4h
    )

    print()
    print(
        f"✅ 4H uygun: "
        f"{len(four_h)}"
    )

    if not four_h:

        print(
            "⚪ 4H aday yok."
        )

        return

    # ========================================================
    # 1H
    # ========================================================

    print()
    print(
        f"🔎 1H GÜÇ TEYİDİ: "
        f"{len(four_h)} coin"
    )

    one_h = parallel_scan(
        four_h,
        analyze_1h
    )

    print()
    print(
        f"✅ 1H uygun: "
        f"{len(one_h)}"
    )

    if not one_h:

        print(
            "⚪ 1H teyidi yok."
        )

        return

    # ========================================================
    # 15M
    # ========================================================

    print()
    print(
        f"🔎 15M TETİK: "
        f"{len(one_h)} coin"
    )

    final = parallel_scan(
        one_h,
        analyze_15m
    )

    # ========================================================
    # SIRALA
    # ========================================================

    final.sort(
        key=lambda x: (
            x["score"],
            x["vol15"],
            x["vol1"],
            x["vol4"]
        ),
        reverse=True
    )

    final = final[
        :MAX_ALERTS
    ]

    stats["final"] = len(
        final
    )

    # ========================================================
    # SONUÇ
    # ========================================================

    elapsed = (
        time.time()
        - start_time
    )

    print()
    print("=" * 60)
    print("📊 TARAMA TAMAMLANDI")
    print("=" * 60)

    print(
        f"Toplam Futures : {len(symbols)}"
    )

    print(
        f"4H uygun       : {len(four_h)}"
    )

    print(
        f"1H uygun       : {len(one_h)}"
    )

    print(
        f"15M uygun      : {stats['fifteen_m']}"
    )

    print(
        f"Final aday     : {len(final)}"
    )

    print(
        f"Kline başarılı  : {stats['kline_ok']}"
    )

    print(
        f"API hata       : {stats['api_error']}"
    )

    print(
        f"Süre           : {elapsed:.1f} saniye"
    )

    # ========================================================
    # TELEGRAM
    # ========================================================

    if not final:

        print()
        print(
            "⚪ Bu taramada güçlü "
            "LSK tipi aday bulunamadı."
        )

        return

    print()
    print(
        "🚨 TELEGRAM'A GİDECEKLER:"
    )

    for c in final:

        print(
            f"  {c['symbol']} "
            f"→ {c['score']}/100"
        )

        message = make_message(
            c
        )

        send_telegram(
            message
        )

        time.sleep(0.4)

    print()
    print(
        "✅ RADAR TAMAMLANDI"
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
