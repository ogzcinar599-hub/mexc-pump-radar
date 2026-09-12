import os
import time
import math
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PUMP RADAR V4
#
# AMAÇ:
# LSK gibi büyük hareketlerden ÖNCE oluşan yapıları bulmak
#
# 4H = ANA YAPI
# 1H = GÜÇ TEYİDİ
# 15M = GİRİŞ HAZIRLIĞI
#
# SADECE MEXC USDT FUTURES
# SADECE TELEGRAM SİNYALİ
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

MIN_SCORE = 68

CANDLE_COUNT = 80

REQUEST_TIMEOUT = 10

# MEXC resmi limit:
# 20 istek / 2 saniye
# Güvenli tarafta kalmak için yaklaşık 10 istek/sn
RATE_INTERVAL = 0.105


# ============================================================
# GLOBAL RATE LIMITER
# ============================================================

_rate_lock = threading.Lock()
_last_request = 0.0


def rate_limit():

    global _last_request

    with _rate_lock:

        now = time.time()

        wait = RATE_INTERVAL - (now - _last_request)

        if wait > 0:
            time.sleep(wait)

        _last_request = time.time()


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "MEXC-Pump-Radar/4.0",
    "Accept": "application/json"
})


# ============================================================
# İSTATİSTİK
# ============================================================

stats = {
    "api_ok": 0,
    "api_error": 0,
    "data_ok": 0,
    "four_h_pass": 0,
    "one_h_pass": 0,
    "fifteen_m_pass": 0,
    "final": 0
}

stats_lock = threading.Lock()


# ============================================================
# MEXC GET
# ============================================================

def mexc_get(path, params=None, retries=3):

    global session

    for attempt in range(retries):

        try:

            rate_limit()

            url = BASE + path

            response = session.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 429:

                time.sleep(1.5 * (attempt + 1))

                continue

            if response.status_code != 200:

                time.sleep(0.5)

                continue

            data = response.json()

            if isinstance(data, dict):

                if data.get("success") is False:

                    time.sleep(0.5)

                    continue

                with stats_lock:
                    stats["api_ok"] += 1

                return data

        except Exception:

            time.sleep(0.5)

    with stats_lock:
        stats["api_error"] += 1

    return None


# ============================================================
# FUTURES SEMBOLLER
# ============================================================

def get_symbols():

    print("📡 MEXC FUTURES SEMBOLLERİ ALINIYOR")

    data = mexc_get("/api/v1/contract/detail")

    if not data:

        print("❌ Contract detail alınamadı")

        return []

    rows = data.get("data", [])

    symbols = []

    for item in rows:

        symbol = item.get("symbol", "")

        if not symbol.endswith("_USDT"):
            continue

        # Aktiflik kontrolü
        if "state" in item:

            state = item.get("state")

            if state not in (0, 1, None):
                continue

        symbols.append(symbol)

    symbols = list(dict.fromkeys(symbols))

    print(f"✅ Futures sembol sayısı: {len(symbols)}")

    return symbols


# ============================================================
# KLINE
#
# ÖNEMLİ:
# MEXC FUTURES API'de LIMIT KULLANMIYORUZ.
# START / END kullanıyoruz.
# ============================================================

INTERVAL_SECONDS = {
    "Min15": 15 * 60,
    "Min60": 60 * 60,
    "Hour4": 4 * 60 * 60
}


def get_klines(symbol, interval, count=CANDLE_COUNT):

    seconds = INTERVAL_SECONDS[interval]

    end = int(time.time())

    start = end - (seconds * count)

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

    raw = data.get("data")

    if not isinstance(raw, dict):
        return None

    try:

        times = raw.get("time", [])
        opens = raw.get("open", [])
        closes = raw.get("close", [])
        highs = raw.get("high", [])
        lows = raw.get("low", [])
        vols = raw.get("vol", [])

        length = min(
            len(times),
            len(opens),
            len(closes),
            len(highs),
            len(lows),
            len(vols)
        )

        if length < 30:
            return None

        candles = []

        for i in range(length):

            candles.append({
                "time": float(times[i]),
                "open": float(opens[i]),
                "close": float(closes[i]),
                "high": float(highs[i]),
                "low": float(lows[i]),
                "vol": float(vols[i])
            })

        candles.sort(key=lambda x: x["time"])

        with stats_lock:
            stats["data_ok"] += 1

        return candles

    except Exception:

        return None


# ============================================================
# RSI
# ============================================================

def rsi(closes, period=14):

    if len(closes) < period + 1:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(closes)):

        diff = closes[i] - closes[i - 1]

        if diff > 0:

            gains.append(diff)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(abs(diff))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# ============================================================
# SMA
# ============================================================

def sma(values, period):

    if len(values) < period:
        return sum(values) / len(values)

    return sum(values[-period:]) / period


# ============================================================
# PERCENT CHANGE
# ============================================================

def pct_change(values, candles_back):

    if len(values) <= candles_back:
        return 0

    old = values[-candles_back - 1]

    if old == 0:
        return 0

    return ((values[-1] / old) - 1) * 100


# ============================================================
# VOLUME RATIO
# ============================================================

def volume_ratio(volumes, recent=5, base=30):

    if len(volumes) < base + recent:
        return 1.0

    recent_avg = sum(volumes[-recent:]) / recent

    base_values = volumes[-(base + recent):-recent]

    if not base_values:
        return 1.0

    base_avg = sum(base_values) / len(base_values)

    if base_avg <= 0:
        return 1.0

    return recent_avg / base_avg


# ============================================================
# COMPRESSION
# ============================================================

def compression_score(candles):

    if len(candles) < 40:
        return 0, 0

    recent = candles[-20:]
    previous = candles[-40:-20]

    recent_high = max(x["high"] for x in recent)
    recent_low = min(x["low"] for x in recent)

    previous_high = max(x["high"] for x in previous)
    previous_low = min(x["low"] for x in previous)

    recent_mid = (recent_high + recent_low) / 2
    previous_mid = (previous_high + previous_low) / 2

    if recent_mid <= 0 or previous_mid <= 0:
        return 0, 0

    recent_width = (
        (recent_high - recent_low)
        / recent_mid
    ) * 100

    previous_width = (
        (previous_high - previous_low)
        / previous_mid
    ) * 100

    if previous_width <= 0:
        return 0, recent_width

    contraction = 1 - (
        recent_width / previous_width
    )

    # %40+ daralma = güçlü
    if contraction >= 0.40:
        score = 20

    elif contraction >= 0.30:
        score = 17

    elif contraction >= 0.20:
        score = 14

    elif contraction >= 0.10:
        score = 9

    else:
        score = 0

    return score, recent_width


# ============================================================
# HIGHER LOW
# ============================================================

def higher_low_score(candles):

    if len(candles) < 30:
        return 0

    lows = [
        x["low"]
        for x in candles[-30:]
    ]

    first = min(lows[:15])

    second = min(lows[15:])

    if second > first * 1.015:
        return 15

    if second > first * 1.008:
        return 11

    if second > first:
        return 7

    return 0


# ============================================================
# MA YAPISI
# ============================================================

def ma_structure(candles):

    closes = [
        x["close"]
        for x in candles
    ]

    ma5 = sma(closes, 5)
    ma10 = sma(closes, 10)
    ma20 = sma(closes, 20)
    ma30 = sma(closes, 30)

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
# RESISTANCE
# ============================================================

def resistance_info(candles):

    if len(candles) < 30:
        return 0, 99

    closes = [
        x["close"]
        for x in candles
    ]

    price = closes[-1]

    # Son 24 mumun mevcut mumdan önceki en yüksek noktası
    highs = [
        x["high"]
        for x in candles[-25:-1]
    ]

    if not highs:
        return 0, 99

    resistance = max(highs)

    if price <= 0:
        return 0, 99

    distance = (
        (resistance - price)
        / price
    ) * 100

    # Direnç üstündeyse breakout olmuş olabilir.
    if distance <= 0:

        return 4, 0

    # Tam direnç altında
    if distance <= 2:
        return 20, distance

    if distance <= 4:
        return 18, distance

    if distance <= 6:
        return 15, distance

    if distance <= 9:
        return 10, distance

    if distance <= 13:
        return 5, distance

    return 0, distance


# ============================================================
# 4H ANALİZ
# ============================================================

def analyze_4h(symbol):

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

    rsi4 = rsi(closes)

    change_24h = pct_change(
        closes,
        6
    )

    change_4h = pct_change(
        closes,
        1
    )

    # --------------------------------------------------------
    # AŞIRI PUMP FİLTRESİ
    # --------------------------------------------------------

    if change_24h >= 30:
        return None

    if change_4h >= 18:
        return None

    if rsi4 >= 76:
        return None

    # --------------------------------------------------------
    # COMPRESSION
    # --------------------------------------------------------

    comp_score, width = compression_score(
        candles
    )

    # LSK tipi hareket için sıkışma önemli.
    if comp_score < 9:
        return None

    # --------------------------------------------------------
    # HIGHER LOW
    # --------------------------------------------------------

    hl_score = higher_low_score(
        candles
    )

    if hl_score < 7:
        return None

    # --------------------------------------------------------
    # MA
    # --------------------------------------------------------

    ma_score = ma_structure(
        candles
    )

    # --------------------------------------------------------
    # RESISTANCE
    # --------------------------------------------------------

    resistance_score, resistance_distance = resistance_info(
        candles
    )

    if resistance_distance > 13:
        return None

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    vol4 = volume_ratio(
        volumes
    )

    volume_score = 0

    if vol4 >= 2.5:
        volume_score = 15

    elif vol4 >= 2.0:
        volume_score = 12

    elif vol4 >= 1.6:
        volume_score = 9

    elif vol4 >= 1.3:
        volume_score = 6

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = (
        comp_score
        + hl_score
        + ma_score
        + resistance_score
        + volume_score
    )

    # RSI bonus
    if 52 <= rsi4 <= 68:
        score += 7

    elif 48 <= rsi4 <= 72:
        score += 4

    # --------------------------------------------------------
    # 4H MIN SCORE
    # --------------------------------------------------------

    if score < 38:
        return None

    with stats_lock:
        stats["four_h_pass"] += 1

    return {
        "symbol": symbol,
        "price": price,
        "rsi4": rsi4,
        "change24": change_24h,
        "change4": change_4h,
        "compression": width,
        "comp_score": comp_score,
        "higher_low": hl_score,
        "ma_score": ma_score,
        "resistance_score": resistance_score,
        "resistance_distance": resistance_distance,
        "vol4": vol4,
        "score4": score
    }


# ============================================================
# 1H ANALİZ
# ============================================================

def analyze_1h(candidate):

    symbol = candidate["symbol"]

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

    rsi1 = rsi(closes)

    change1h = pct_change(
        closes,
        1
    )

    vol1 = volume_ratio(
        volumes
    )

    hl1 = higher_low_score(
        candles
    )

    score = candidate["score4"]

    # --------------------------------------------------------
    # 1H RSI
    # --------------------------------------------------------

    if 50 <= rsi1 <= 68:
        score += 7

    elif 45 <= rsi1 <= 72:
        score += 4

    else:
        score -= 4

    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    if vol1 >= 3.0:
        score += 15

    elif vol1 >= 2.3:
        score += 12

    elif vol1 >= 1.8:
        score += 9

    elif vol1 >= 1.4:
        score += 5

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if 0.5 <= change1h <= 7:
        score += 10

    elif 0 <= change1h < 0.5:
        score += 5

    elif change1h > 10:
        score -= 8

    # --------------------------------------------------------
    # HIGHER LOW
    # --------------------------------------------------------

    if hl1 >= 11:
        score += 8

    elif hl1 >= 7:
        score += 5

    # --------------------------------------------------------
    # PUMP FİLTRESİ
    # --------------------------------------------------------

    if change1h >= 15:
        return None

    if rsi1 >= 75:
        return None

    # --------------------------------------------------------
    # 1H SCORE
    # --------------------------------------------------------

    if score < 52:
        return None

    candidate.update({
        "price": price,
        "rsi1": rsi1,
        "change1h": change1h,
        "vol1": vol1,
        "hl1": hl1,
        "score1": score
    })

    with stats_lock:
        stats["one_h_pass"] += 1

    return candidate


# ============================================================
# 15M ANALİZ
# ============================================================

def analyze_15m(candidate):

    symbol = candidate["symbol"]

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

    rsi15 = rsi(closes)

    change15 = pct_change(
        closes,
        1
    )

    change1h_15 = pct_change(
        closes,
        4
    )

    vol15 = volume_ratio(
        volumes,
        recent=3,
        base=30
    )

    score = candidate["score1"]

    # --------------------------------------------------------
    # 15M RSI
    # --------------------------------------------------------

    if 52 <= rsi15 <= 68:
        score += 8

    elif 48 <= rsi15 <= 72:
        score += 4

    else:
        score -= 3

    # --------------------------------------------------------
    # HACİM PATLAMASI
    # --------------------------------------------------------

    if vol15 >= 4.0:
        score += 20

    elif vol15 >= 3.0:
        score += 16

    elif vol15 >= 2.3:
        score += 12

    elif vol15 >= 1.7:
        score += 8

    elif vol15 >= 1.3:
        score += 4

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if 0.3 <= change15 <= 4:
        score += 8

    elif 0 <= change15 < 0.3:
        score += 3

    elif change15 > 7:
        score -= 8

    # Son 1 saatte aşırı yükseldiyse alma
    if change1h_15 >= 10:
        return None

    # --------------------------------------------------------
    # 15M DIRenç
    # --------------------------------------------------------

    recent_high = max(
        highs[-12:-1]
    )

    distance = (
        (recent_high - price)
        / price
    ) * 100 if price > 0 else 99

    if distance <= 1:
        score += 10

    elif distance <= 2.5:
        score += 7

    elif distance <= 5:
        score += 4

    # --------------------------------------------------------
    # RSI AŞIRI İSE ALMA
    # --------------------------------------------------------

    if rsi15 >= 78:
        return None

    # --------------------------------------------------------
    # FINAL
    # --------------------------------------------------------

    if score < MIN_SCORE:
        return None

    candidate.update({
        "price": price,
        "rsi15": rsi15,
        "change15": change15,
        "change1h_15": change1h_15,
        "vol15": vol15,
        "res15_distance": distance,
        "score": score
    })

    with stats_lock:
        stats["fifteen_m_pass"] += 1

    return candidate


# ============================================================
# TP / STOP
# ============================================================

def calculate_levels(price):

    stop = price * 0.982

    tp1 = price * 1.04

    tp2 = price * 1.07

    tp3 = price * 1.11

    return stop, tp1, tp2, tp3


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(text):

    if not TOKEN or not CHAT_ID:
        print("⚠️ Telegram bilgileri yok")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": text
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=15
        )

        if response.status_code == 200:

            print("📨 Telegram gönderildi")

            return True

        print(
            "❌ Telegram hata:",
            response.text[:300]
        )

    except Exception as e:

        print(
            "❌ Telegram bağlantı hatası:",
            e
        )

    return False


# ============================================================
# MESAJ
# ============================================================

def format_alert(c):

    price = c["price"]

    stop, tp1, tp2, tp3 = calculate_levels(
        price
    )

    reasons = []

    if c["comp_score"] >= 14:
        reasons.append("4H sıkışma")

    if c["higher_low"] >= 11:
        reasons.append("Higher-Low")

    if c["vol4"] >= 1.6:
        reasons.append("4H hacim")

    if c["vol1"] >= 2:
        reasons.append("1H hacim")

    if c["vol15"] >= 2:
        reasons.append("15M hacim")

    if c["resistance_distance"] <= 6:
        reasons.append("Direnç yakın")

    if not reasons:
        reasons.append("Erken momentum")

    reason_text = " • ".join(reasons)

    return f"""
🚨 LSK TİPİ PRE-PUMP ADAYI

🪙 {c['symbol']}

⭐ GÜÇ: {c['score']}/100

💰 Fiyat:
{price:.10g}

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
1H  : {c['change1h']:+.2f}%
4H  : {c['change4']:+.2f}%
24H : {c['change24']:+.2f}%

📦 4H SIKIŞMA
Alan : {c['compression']:.2f}%

🎯 DİRENÇ
4H : %{c['resistance_distance']:.2f} uzaklık
15M: %{c['res15_distance']:.2f} uzaklık

🔥 NEDEN:
{reason_text}

━━━━━━━━━━━━━━

🎯 REFERANS SEVİYELER

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

⚠️ Bu sinyal otomatik işlem açmaz.
Erken hareket / teknik radar sinyalidir.
"""


# ============================================================
# PARALEL YARDIMCI
# ============================================================

def parallel_scan(items, function):

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(function, item)
            for item in items
        ]

        for future in as_completed(futures):

            try:

                result = future.result()

                if result:
                    results.append(result)

            except Exception:
                pass

    return results


# ============================================================
# API TEST
# ============================================================

def api_smoke_test(symbol):

    print(f"🧪 API TEST: {symbol}")

    candles = get_klines(
        symbol,
        "Min15",
        20
    )

    if not candles:

        print(
            "❌ Kline API testi başarısız."
        )

        return False

    print(
        f"✅ Kline API çalışıyor: "
        f"{len(candles)} mum"
    )

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 60)
    print("🚀 MEXC LSK PRE-PUMP RADAR V4")
    print("=" * 60)

    if TOKEN:
        print("✅ TELEGRAM_BOT_TOKEN bulundu")
    else:
        print("❌ TELEGRAM_BOT_TOKEN YOK")

    if CHAT_ID:
        print("✅ TELEGRAM_CHAT_ID bulundu")
    else:
        print("❌ TELEGRAM_CHAT_ID YOK")

    # --------------------------------------------------------
    # SEMBOLLER
    # --------------------------------------------------------

    symbols = get_symbols()

    if not symbols:

        print("❌ Futures sembolü bulunamadı")

        return

    # --------------------------------------------------------
    # API TEST
    # --------------------------------------------------------

    test_symbol = "BTC_USDT"

    if test_symbol not in symbols:

        test_symbol = symbols[0]

    if not api_smoke_test(test_symbol):

        print()
        print(
            "❌ MEXC Kline API cevap vermiyor."
        )

        print(
            "Radar durduruldu."
        )

        return

    # --------------------------------------------------------
    # 4H
    # --------------------------------------------------------

    print()
    print(
        f"🔎 4H ANA YAPI TARAMASI: "
        f"{len(symbols)} coin"
    )

    start_time = time.time()

    four_h = parallel_scan(
        symbols,
        analyze_4h
    )

    print(
        f"✅ 4H uygun aday: "
        f"{len(four_h)}"
    )

    if not four_h:

        print(
            "⚪ 4H yapısında aday yok."
        )

        return

    # --------------------------------------------------------
    # 1H
    # --------------------------------------------------------

    print()
    print(
        f"🔎 1H GÜÇ TEYİDİ: "
        f"{len(four_h)} coin"
    )

    one_h = parallel_scan(
        four_h,
        analyze_1h
    )

    print(
        f"✅ 1H uygun aday: "
        f"{len(one_h)}"
    )

    if not one_h:

        print(
            "⚪ 1H teyidi veren aday yok."
        )

        return

    # --------------------------------------------------------
    # 15M
    # --------------------------------------------------------

    print()
    print(
        f"🔎 15M GİRİŞ HAZIRLIĞI: "
        f"{len(one_h)} coin"
    )

    final_candidates = parallel_scan(
        one_h,
        analyze_15m
    )

    # --------------------------------------------------------
    # SIRALA
    # --------------------------------------------------------

    final_candidates.sort(
        key=lambda x: (
            x["score"],
            x["vol15"],
            x["vol1"]
        ),
        reverse=True
    )

    final_candidates = final_candidates[
        :MAX_ALERTS
    ]

    stats["final"] = len(
        final_candidates
    )

    # --------------------------------------------------------
    # SONUÇ
    # --------------------------------------------------------

    elapsed = time.time() - start_time

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
        f"15M uygun      : {stats['fifteen_m_pass']}"
    )

    print(
        f"Final aday     : {len(final_candidates)}"
    )

    print(
        f"API başarılı   : {stats['api_ok']}"
    )

    print(
        f"API hata       : {stats['api_error']}"
    )

    print(
        f"Süre           : {elapsed:.1f} saniye"
    )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    if not final_candidates:

        print()
        print(
            "⚪ Bu taramada güçlü "
            "LSK tipi aday yok."
        )

        return

    print()
    print("🚨 GÜÇLÜ ADAYLAR:")

    for candidate in final_candidates:

        print(
            candidate["symbol"],
            candidate["score"]
        )

        message = format_alert(
            candidate
        )

        send_telegram(message)

        time.sleep(0.3)

    print()
    print(
        "✅ RADAR TAMAMLANDI"
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
