import os
import time
import threading
import requests
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PRE-PUMP RADAR V6.0
#
# AMAÇ:
# Pump başlamış coinleri değil,
# pump öncesi hacim toplamaya başlayan coinleri bulmak.
#
# 4H  = YAPI / SIKIŞMA
# 1H  = HACİM + GÜÇ
# 15M = HACİM İVME + TETİK
#
# SADECE MEXC USDT FUTURES
# OTOMATİK İŞLEM YOK
# ============================================================


BASE = "https://api.mexc.com"

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# AYARLAR
# ============================================================

MAX_WORKERS = 6

MAX_ALERTS = 6

# V5'te 62 idi.
# V6'da hacim filtresi sıkı olduğu için 60 yaptık.
MIN_SCORE = 60

CANDLE_COUNT = 90

TIMEOUT = 12

REQUEST_INTERVAL = 0.12

# 4H'den sonra en fazla bu kadar coin 1H'ye gider
FOUR_H_MAX = 250

# 1H'den sonra en fazla bu kadar coin 15M'ye gider
ONE_H_MAX = 100


# ============================================================
# RATE LIMIT
# ============================================================

rate_lock = threading.Lock()
last_request_time = 0.0


def rate_limit():

    global last_request_time

    with rate_lock:

        now = time.time()

        wait = REQUEST_INTERVAL - (
            now - last_request_time
        )

        if wait > 0:
            time.sleep(wait)

        last_request_time = time.time()


# ============================================================
# MEXC API
# ============================================================

def mexc_get(path, params=None, retry=3):

    for attempt in range(retry):

        try:

            rate_limit()

            response = requests.get(
                BASE + path,
                params=params,
                timeout=TIMEOUT
            )

            if response.status_code != 200:

                print(
                    f"⚠️ HTTP {response.status_code} "
                    f"{path}",
                    flush=True
                )

                time.sleep(1)

                continue

            return response.json()

        except Exception as e:

            print(
                f"⚠️ API hata: "
                f"{type(e).__name__} "
                f"{str(e)[:100]}",
                flush=True
            )

            time.sleep(1)

    return None


# ============================================================
# FUTURES COINLER
# ============================================================

def get_symbols():

    print(
        "\n🔎 MEXC Futures coinleri alınıyor...",
        flush=True
    )

    data = mexc_get(
        "/api/v1/contract/detail"
    )

    if not data:

        print(
            "❌ Contract API boş döndü",
            flush=True
        )

        return []

    rows = data.get("data", [])

    if not isinstance(rows, list):

        print(
            "❌ Contract API format hatası",
            flush=True
        )

        return []

    symbols = []

    for item in rows:

        try:

            symbol = str(
                item.get("symbol", "")
            ).upper()

            if not symbol.endswith("_USDT"):
                continue

            # MEXC state = 0 aktif
            state = item.get("state")

            if state is not None:

                try:

                    if int(state) != 0:
                        continue

                except Exception:
                    pass

            symbols.append(symbol)

        except Exception:
            continue

    symbols = sorted(
        set(symbols)
    )

    print(
        f"✅ Futures sembol sayısı: "
        f"{len(symbols)}",
        flush=True
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

    try:

        seconds_map = {

            "Min15": 15 * 60,

            "Min60": 60 * 60,

            "Hour4": 4 * 60 * 60
        }

        seconds = seconds_map[interval]

        end = int(
            time.time()
        )

        start = end - (
            seconds * (count + 5)
        )

        data = mexc_get(
            f"/api/v1/contract/kline/{symbol}",
            {
                "interval": interval,
                "start": start,
                "end": end
            }
        )

        if not data:
            return None

        if data.get("success") is not True:
            return None

        raw = data.get("data")

        if not isinstance(raw, dict):
            return None

        closes = raw.get("close", [])
        highs = raw.get("high", [])
        lows = raw.get("low", [])
        volumes = raw.get("vol", [])

        if not closes:
            return None

        n = min(
            len(closes),
            len(highs),
            len(lows),
            len(volumes)
        )

        if n < 50:
            return None

        closes = [
            float(x)
            for x in closes[-count:]
        ]

        highs = [
            float(x)
            for x in highs[-count:]
        ]

        lows = [
            float(x)
            for x in lows[-count:]
        ]

        volumes = [
            float(x)
            for x in volumes[-count:]
        ]

        return {
            "close": closes,
            "high": highs,
            "low": lows,
            "volume": volumes
        }

    except Exception:

        return None


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
# RSI
# ============================================================

def rsi(values, period=14):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    start = len(values) - period

    for i in range(
        start,
        len(values)
    ):

        change = (
            values[i]
            -
            values[i - 1]
        )

        if change > 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# YÜZDE DEĞİŞİM
# ============================================================

def pct_change(new, old):

    if old == 0:
        return 0.0

    return (
        (new - old)
        /
        old
    ) * 100


# ============================================================
# HACİM ORANI
# ============================================================

def volume_ratio(
    volumes,
    period=20
):

    if len(volumes) < period + 1:
        return 0.0

    average = sum(
        volumes[-period-1:-1]
    ) / period

    if average <= 0:
        return 0.0

    return (
        volumes[-1]
        /
        average
    )


# ============================================================
# HACİM İVME
#
# Son 5 mum hacmi
# önceki 20 mum ortalamasına göre ne kadar arttı?
# ============================================================

def volume_acceleration(volumes):

    if len(volumes) < 30:
        return 0.0

    recent = sum(
        volumes[-5:]
    ) / 5

    previous = sum(
        volumes[-25:-5]
    ) / 20

    if previous <= 0:
        return 0.0

    return recent / previous


# ============================================================
# HACİM TRENDİ
#
# Son mumların hacmi giderek yükseliyor mu?
# ============================================================

def volume_trend(volumes):

    if len(volumes) < 15:
        return 0.0

    a = sum(
        volumes[-15:-10]
    ) / 5

    b = sum(
        volumes[-10:-5]
    ) / 5

    c = sum(
        volumes[-5:]
    ) / 5

    if a <= 0:
        return 0.0

    return (
        c / a
    )


# ============================================================
# SIKIŞMA
# ============================================================

def compression_score(
    highs,
    lows
):

    if len(highs) < 40:
        return 0

    recent_high = max(
        highs[-10:]
    )

    recent_low = min(
        lows[-10:]
    )

    old_high = max(
        highs[-30:-10]
    )

    old_low = min(
        lows[-30:-10]
    )

    recent_range = (
        recent_high
        -
        recent_low
    )

    old_range = (
        old_high
        -
        old_low
    )

    if old_range <= 0:
        return 0

    ratio = (
        recent_range
        /
        old_range
    )

    if ratio <= 0.45:
        return 18

    if ratio <= 0.60:
        return 14

    if ratio <= 0.75:
        return 9

    if ratio <= 0.90:
        return 4

    return 0


# ============================================================
# HIGHER LOW
# ============================================================

def higher_low_score(lows):

    if len(lows) < 40:
        return 0

    a = min(
        lows[-30:-20]
    )

    b = min(
        lows[-20:-10]
    )

    c = min(
        lows[-10:]
    )

    score = 0

    if b > a:
        score += 7

    if c > b:
        score += 10

    return score


# ============================================================
# DİRENÇ MESAFESİ
# ============================================================

def resistance_distance(
    closes,
    highs
):

    if len(closes) < 40:
        return 999

    current = closes[-1]

    resistance = max(
        highs[-30:]
    )

    if resistance <= 0:
        return 999

    return (
        (
            resistance
            -
            current
        )
        /
        resistance
    ) * 100


# ============================================================
# MOMENTUM
# ============================================================

def momentum(
    closes,
    candles
):

    if len(closes) < candles + 1:
        return 0.0

    return pct_change(
        closes[-1],
        closes[-candles-1]
    )


# ============================================================
# ZATEN PUMP YAPMIŞ MI?
# ============================================================

def already_pumped(closes):

    if len(closes) < 40:
        return True

    move_3 = momentum(
        closes,
        3
    )

    move_5 = momentum(
        closes,
        5
    )

    move_10 = momentum(
        closes,
        10
    )

    move_20 = momentum(
        closes,
        20
    )

    # Çok kısa sürede pump
    if move_3 > 10:
        return True

    if move_5 > 16:
        return True

    if move_10 > 25:
        return True

    if move_20 > 40:
        return True

    return False


# ============================================================
# 4H ANALİZ
#
# Burada amaç:
# "Coin hazırlanıyor mu?"
# ============================================================

def analyze_4h(data):

    if not data:
        return None

    closes = data["close"]
    highs = data["high"]
    lows = data["low"]
    volumes = data["volume"]

    if len(closes) < 50:
        return None

    if already_pumped(closes):
        return None

    current = closes[-1]

    r = rsi(closes)

    ma20 = sma(
        closes,
        20
    )

    ma50 = sma(
        closes,
        50
    )

    compression = compression_score(
        highs,
        lows
    )

    higher_low = higher_low_score(
        lows
    )

    distance = resistance_distance(
        closes,
        highs
    )

    mom10 = momentum(
        closes,
        10
    )

    vr = volume_ratio(
        volumes,
        20
    )

    score = 0

    reasons = []

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if r is not None:

        if 45 <= r <= 62:

            score += 10

            reasons.append(
                "RSI dengeli"
            )

        elif 62 < r <= 68:

            score += 6

        elif 40 <= r < 45:

            score += 4

    # --------------------------------------------------------
    # MA
    # --------------------------------------------------------

    if ma20 and ma50:

        if current > ma20:

            score += 7

            reasons.append(
                "MA20 üstü"
            )

        if ma20 >= ma50:

            score += 7

            reasons.append(
                "MA trendi pozitif"
            )

    # --------------------------------------------------------
    # SIKIŞMA
    # --------------------------------------------------------

    score += compression

    if compression >= 14:

        reasons.append(
            "4H sıkışma"
        )

    # --------------------------------------------------------
    # HIGHER LOW
    # --------------------------------------------------------

    score += higher_low

    if higher_low >= 10:

        reasons.append(
            "Higher Low"
        )

    # --------------------------------------------------------
    # DİRENÇ
    # --------------------------------------------------------

    if 0 <= distance <= 3:

        score += 14

        reasons.append(
            "Dirence çok yakın"
        )

    elif 3 < distance <= 6:

        score += 10

        reasons.append(
            "Dirence yakın"
        )

    elif 6 < distance <= 10:

        score += 5

    # --------------------------------------------------------
    # KONTROLLÜ MOMENTUM
    # --------------------------------------------------------

    if 0 < mom10 < 10:

        score += 6

        reasons.append(
            "Kontrollü yükseliş"
        )

    elif mom10 < -15:

        score -= 8

    # --------------------------------------------------------
    # HACİM
    #
    # 4H'de henüz patlamamış ama tamamen ölü de olmayacak
    # --------------------------------------------------------

    if vr >= 0.80:

        score += 4

    return {
        "score": score,
        "rsi": r,
        "volume": vr,
        "compression": compression,
        "higher_low": higher_low,
        "distance": distance,
        "momentum": mom10,
        "reasons": reasons,
        "price": current
    }


# ============================================================
# 1H ANALİZ
#
# BURASI EN ÖNEMLİ KATMAN
# ============================================================

def analyze_1h(data):

    if not data:
        return None

    closes = data["close"]
    highs = data["high"]
    lows = data["low"]
    volumes = data["volume"]

    if len(closes) < 50:
        return None

    current = closes[-1]

    r = rsi(closes)

    ma20 = sma(
        closes,
        20
    )

    ma50 = sma(
        closes,
        50
    )

    vr = volume_ratio(
        volumes,
        20
    )

    acceleration = volume_acceleration(
        volumes
    )

    trend = volume_trend(
        volumes
    )

    higher_low = higher_low_score(
        lows
    )

    distance = resistance_distance(
        closes,
        highs
    )

    mom5 = momentum(
        closes,
        5
    )

    mom10 = momentum(
        closes,
        10
    )

    # ========================================================
    # ÖLÜ HACİM FİLTRESİ
    #
    # NEO gibi:
    # 0.31x / 0.14x
    #
    # ARTIK GEÇEMEZ
    # ========================================================

    if vr < 0.80:

        return None

    score = 0

    reasons = []

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if r is not None:

        if 50 <= r <= 67:

            score += 10

            reasons.append(
                "1H RSI güçlü"
            )

        elif 45 <= r < 50:

            score += 4

        elif r > 72:

            score -= 10

    # --------------------------------------------------------
    # MA
    # --------------------------------------------------------

    if ma20 and ma50:

        if current > ma20:

            score += 8

            reasons.append(
                "1H MA20 üstü"
            )

        if ma20 > ma50:

            score += 7

            reasons.append(
                "1H trend pozitif"
            )

    # --------------------------------------------------------
    # TEMEL HACİM
    # --------------------------------------------------------

    if vr >= 1.30:

        score += 15

        reasons.append(
            "1H güçlü hacim"
        )

    elif vr >= 1.10:

        score += 11

        reasons.append(
            "1H hacim artıyor"
        )

    elif vr >= 0.90:

        score += 6

    else:

        score += 2

    # --------------------------------------------------------
    # HACİM İVME
    # --------------------------------------------------------

    if acceleration >= 1.50:

        score += 15

        reasons.append(
            "1H hacim ivmesi"
        )

    elif acceleration >= 1.25:

        score += 10

        reasons.append(
            "1H hacim canlanıyor"
        )

    elif acceleration >= 1.10:

        score += 5

    # --------------------------------------------------------
    # HACİM TRENDİ
    # --------------------------------------------------------

    if trend >= 1.50:

        score += 8

        reasons.append(
            "Hacim giderek yükseliyor"
        )

    elif trend >= 1.20:

        score += 5

    # --------------------------------------------------------
    # HIGHER LOW
    # --------------------------------------------------------

    if higher_low >= 12:

        score += 10

        reasons.append(
            "1H Higher Low"
        )

    elif higher_low >= 7:

        score += 5

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if 0.5 <= mom5 <= 8:

        score += 8

        reasons.append(
            "Pozitif momentum"
        )

    elif 8 < mom5 <= 14:

        score += 5

    elif mom5 > 16:

        score -= 5

    elif mom5 < -8:

        score -= 5

    if 0 < mom10 < 18:

        score += 4

    # --------------------------------------------------------
    # DİRENÇ
    # --------------------------------------------------------

    if 0 <= distance <= 3:

        score += 10

        reasons.append(
            "1H breakout bölgesi"
        )

    elif 3 < distance <= 6:

        score += 7

    elif 6 < distance <= 10:

        score += 3

    return {
        "score": score,
        "rsi": r,
        "volume": vr,
        "acceleration": acceleration,
        "trend": trend,
        "higher_low": higher_low,
        "distance": distance,
        "momentum": mom5,
        "momentum10": mom10,
        "reasons": reasons,
        "price": current
    }


# ============================================================
# 15M ANALİZ
#
# Pump başlamadan hemen önceki hareket
# ============================================================

def analyze_15m(data):

    if not data:
        return None

    closes = data["close"]
    highs = data["high"]
    lows = data["low"]
    volumes = data["volume"]

    if len(closes) < 50:
        return None

    current = closes[-1]

    r = rsi(closes)

    vr = volume_ratio(
        volumes,
        20
    )

    acceleration = volume_acceleration(
        volumes
    )

    trend = volume_trend(
        volumes
    )

    distance = resistance_distance(
        closes,
        highs
    )

    mom3 = momentum(
        closes,
        3
    )

    mom5 = momentum(
        closes,
        5
    )

    # ========================================================
    # ÖLÜ 15M HACİMİ ELE
    # ========================================================

    if vr < 0.70:

        return None

    score = 0

    reasons = []

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if r is not None:

        if 50 <= r <= 70:

            score += 9

            reasons.append(
                "15M RSI uygun"
            )

        elif 45 <= r < 50:

            score += 4

        elif r > 75:

            score -= 8

    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    if vr >= 1.50:

        score += 15

        reasons.append(
            "15M hacim güçlü"
        )

    elif vr >= 1.20:

        score += 12

        reasons.append(
            "15M hacim artıyor"
        )

    elif vr >= 0.90:

        score += 7

    elif vr >= 0.70:

        score += 3

    # --------------------------------------------------------
    # HACİM İVME
    # --------------------------------------------------------

    if acceleration >= 1.60:

        score += 16

        reasons.append(
            "15M hacim ivmesi"
        )

    elif acceleration >= 1.30:

        score += 11

        reasons.append(
            "15M hacim canlanıyor"
        )

    elif acceleration >= 1.10:

        score += 5

    # --------------------------------------------------------
    # HACİM TRENDİ
    # --------------------------------------------------------

    if trend >= 1.50:

        score += 8

        reasons.append(
            "Kısa vadeli hacim yükseliyor"
        )

    elif trend >= 1.20:

        score += 5

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if 0.3 <= mom3 <= 5:

        score += 8

        reasons.append(
            "Yeni momentum"
        )

    elif 5 < mom3 <= 10:

        score += 5

    elif mom3 > 12:

        score -= 6

    if 0 < mom5 < 12:

        score += 5

    elif mom5 > 15:

        score -= 5

    # --------------------------------------------------------
    # DİRENÇ
    # --------------------------------------------------------

    if 0 <= distance <= 2:

        score += 12

        reasons.append(
            "Direnç hemen üstünde"
        )

    elif 2 < distance <= 4:

        score += 9

        reasons.append(
            "Dirence çok yakın"
        )

    elif 4 < distance <= 7:

        score += 5

    return {
        "score": score,
        "rsi": r,
        "volume": vr,
        "acceleration": acceleration,
        "trend": trend,
        "distance": distance,
        "momentum": mom3,
        "momentum5": mom5,
        "reasons": reasons,
        "price": current
    }


# ============================================================
# TP HESAPLAMA
# ============================================================

def calculate_tp(price):

    return {
        "tp1": price * 1.03,
        "tp2": price * 1.06,
        "tp3": price * 1.10
    }


# ============================================================
# GÜVENLİ SAYI
# ============================================================

def sf(value, digits=2):

    if value is None:
        return "N/A"

    try:
        return f"{float(value):.{digits}f}"

    except Exception:

        return "N/A"


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def format_alert(x):

    price = x["price"]

    tp = calculate_tp(
        price
    )

    reasons = x["reasons"]

    reasons = list(
        dict.fromkeys(reasons)
    )

    reason_text = "\n".join(
        f"• {r}"
        for r in reasons[:7]
    )

    return (
        "🚨 <b>PRE-PUMP RADAR</b>\n"
        "\n"
        f"🪙 <b>{x['symbol']}</b>\n"
        f"⭐ Skor: <b>{x['score']}/100</b>\n"
        f"💰 Fiyat: <b>{price:.8g}</b>\n"
        "\n"
        "📊 <b>RSI</b>\n"
        f"4H {sf(x['rsi4'],1)}"
        f" | 1H {sf(x['rsi1'],1)}"
        f" | 15M {sf(x['rsi15'],1)}\n"
        "\n"
        "🔥 <b>HACİM</b>\n"
        f"1H {sf(x['vol1'],2)}x"
        f" | 15M {sf(x['vol15'],2)}x\n"
        f"İvme: 1H {sf(x['acc1'],2)}x"
        f" | 15M {sf(x['acc15'],2)}x\n"
        "\n"
        "📈 <b>MOMENTUM</b>\n"
        f"1H {sf(x['mom1'],2)}%"
        f" | 15M {sf(x['mom15'],2)}%\n"
        "\n"
        f"🎯 Direnç: %{sf(x['dist4'],2)}\n"
        "\n"
        "💰 <b>TP</b>\n"
        f"TP1: {tp['tp1']:.8g}  (+3%)\n"
        f"TP2: {tp['tp2']:.8g}  (+6%)\n"
        f"TP3: {tp['tp3']:.8g}  (+10%)\n"
        "\n"
        "🔎 <b>NEDEN ADAY?</b>\n"
        f"{reason_text}\n"
        "\n"
        "⚠️ Teknik radar sinyalidir."
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TOKEN or not CHAT_ID:

        print(
            "⚠️ Telegram secret bulunamadı",
            flush=True
        )

        return False

    try:

        url = (
            "https://api.telegram.org/bot"
            f"{TOKEN}/sendMessage"
        )

        response = requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=15
        )

        if response.status_code == 200:

            print(
                "📨 Telegram gönderildi",
                flush=True
            )

            return True

        print(
            f"❌ Telegram HTTP "
            f"{response.status_code}",
            flush=True
        )

        print(
            response.text[:300],
            flush=True
        )

    except Exception as e:

        print(
            f"❌ Telegram hata: {e}",
            flush=True
        )

    return False


# ============================================================
# API TEST
# ============================================================

def api_test():

    print(
        "\n🧪 KLINE API TESTİ",
        flush=True
    )

    data = get_klines(
        "BTC_USDT",
        "Min15",
        50
    )

    if not data:

        print(
            "❌ Kline API başarısız",
            flush=True
        )

        return False

    print(
        f"✅ Kline API ÇALIŞIYOR "
        f"| {len(data['close'])} mum",
        flush=True
    )

    print(
        f"BTC fiyat: "
        f"{data['close'][-1]}",
        flush=True
    )

    return True


# ============================================================
# 4H TARAMA
# ============================================================

def scan_4h(symbol):

    data = get_klines(
        symbol,
        "Hour4",
        CANDLE_COUNT
    )

    result = analyze_4h(
        data
    )

    if not result:
        return None

    # 4H temel kalite
    if result["score"] < 32:
        return None

    return {
        "symbol": symbol,
        "data4": data,
        "a4": result
    }


# ============================================================
# 1H TARAMA
# ============================================================

def scan_1h(item):

    symbol = item["symbol"]

    data = get_klines(
        symbol,
        "Min60",
        CANDLE_COUNT
    )

    result = analyze_1h(
        data
    )

    if not result:
        return None

    if result["score"] < 28:
        return None

    return {
        **item,
        "data1": data,
        "a1": result
    }


# ============================================================
# 15M TARAMA
# ============================================================

def scan_15m(item):

    symbol = item["symbol"]

    data = get_klines(
        symbol,
        "Min15",
        CANDLE_COUNT
    )

    result = analyze_15m(
        data
    )

    if not result:
        return None

    # ========================================================
    # SON FİLTRE
    # ========================================================

    total = (
        item["a4"]["score"] * 0.35
        +
        item["a1"]["score"] * 0.40
        +
        result["score"] * 0.25
    )

    total = round(
        total,
        1
    )

    if total < MIN_SCORE:
        return None

    # --------------------------------------------------------
    # EK HACİM KONTROLÜ
    #
    # Burada NEO gibi ölü hacim kesinlikle geçemez.
    # --------------------------------------------------------

    if item["a1"]["volume"] < 0.80:
        return None

    if result["volume"] < 0.70:
        return None

    # --------------------------------------------------------
    # En az bir zaman diliminde hacim ivmesi
    # --------------------------------------------------------

    if (
        item["a1"]["acceleration"] < 1.10
        and
        result["acceleration"] < 1.10
    ):

        return None

    reasons = []

    reasons.extend(
        item["a4"]["reasons"][:4]
    )

    reasons.extend(
        item["a1"]["reasons"][:5]
    )

    reasons.extend(
        result["reasons"][:5]
    )

    reasons = list(
        dict.fromkeys(reasons)
    )

    return {

        "symbol": symbol,

        "score": total,

        "price": result["price"],

        "rsi4": item["a4"]["rsi"],
        "rsi1": item["a1"]["rsi"],
        "rsi15": result["rsi"],

        "vol4": item["a4"]["volume"],
        "vol1": item["a1"]["volume"],
        "vol15": result["volume"],

        "acc1": item["a1"]["acceleration"],
        "acc15": result["acceleration"],

        "trend1": item["a1"]["trend"],
        "trend15": result["trend"],

        "dist4": item["a4"]["distance"],
        "dist1": item["a1"]["distance"],
        "dist15": result["distance"],

        "mom1": item["a1"]["momentum"],
        "mom15": result["momentum"],

        "reasons": reasons
    }


# ============================================================
# ANA PROGRAM
# ============================================================

def main():

    start_time = time.time()

    print(
        "\n"
        "====================================================\n"
        "🚀 MEXC PRE-PUMP RADAR V6.0\n"
        "====================================================",
        flush=True
    )

    print(
        "🎯 AMAÇ: PUMP ÖNCESİ HACİM İVMESİ",
        flush=True
    )

    print(
        f"⚙️ Minimum skor: {MIN_SCORE}",
        flush=True
    )

    print(
        f"⚙️ Maksimum Telegram: {MAX_ALERTS}",
        flush=True
    )

    # ========================================================
    # API TEST
    # ========================================================

    if not api_test():

        print(
            "❌ API çalışmıyor. Program durduruldu.",
            flush=True
        )

        return

    # ========================================================
    # SYMBOLS
    # ========================================================

    symbols = get_symbols()

    if not symbols:

        print(
            "❌ Futures coin bulunamadı.",
            flush=True
        )

        return

    # ========================================================
    # 4H
    # ========================================================

    print(
        "\n🟣 4H YAPI TARAMASI BAŞLADI...",
        flush=True
    )

    four_h = []

    completed = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                scan_4h,
                symbol
            ): symbol

            for symbol in symbols
        }

        for future in as_completed(
            futures
        ):

            completed += 1

            try:

                result = future.result()

                if result:

                    four_h.append(
                        result
                    )

            except Exception:
                pass

            if (
                completed % 100 == 0
                or
                completed == len(symbols)
            ):

                print(
                    f"4H: "
                    f"{completed}/{len(symbols)} "
                    f"| Aday: {len(four_h)}",
                    flush=True
                )

    four_h.sort(
        key=lambda x:
        x["a4"]["score"],
        reverse=True
    )

    four_h = four_h[
        :FOUR_H_MAX
    ]

    print(
        f"✅ 4H güçlü yapı: "
        f"{len(four_h)}",
        flush=True
    )

    # ========================================================
    # 1H
    # ========================================================

    print(
        "\n🟢 1H HACİM + GÜÇ TARAMASI...",
        flush=True
    )

    one_h = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                scan_1h,
                item
            )

            for item in four_h
        ]

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                if result:

                    one_h.append(
                        result
                    )

            except Exception:
                pass

    one_h.sort(
        key=lambda x: (
            x["a4"]["score"]
            +
            x["a1"]["score"]
        ),
        reverse=True
    )

    one_h = one_h[
        :ONE_H_MAX
    ]

    print(
        f"✅ 1H güçlü aday: "
        f"{len(one_h)}",
        flush=True
    )

    # ========================================================
    # 15M
    # ========================================================

    print(
        "\n🟠 15M HACİM İVMESİ + TETİK...",
        flush=True
    )

    final = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                scan_15m,
                item
            )

            for item in one_h
        ]

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                if result:

                    final.append(
                        result
                    )

            except Exception:
                pass

    # ========================================================
    # SIRALAMA
    # ========================================================

    final.sort(
        key=lambda x:
        x["score"],
        reverse=True
    )

    print(
        "\n====================================================",
        flush=True
    )

    print(
        f"🏆 FİNAL PRE-PUMP ADAYLARI: "
        f"{len(final)}",
        flush=True
    )

    print(
        "====================================================",
        flush=True
    )

    for i, x in enumerate(
        final[:15],
        1
    ):

        print(
            f"{i:02d}. "
            f"{x['symbol']} "
            f"| {x['score']}/100 "
            f"| RSI15 {sf(x['rsi15'],1)} "
            f"| V1H {sf(x['vol1'],2)}x "
            f"| V15 {sf(x['vol15'],2)}x "
            f"| İVME1H {sf(x['acc1'],2)}x "
            f"| İVME15 {sf(x['acc15'],2)}x "
            f"| DIR %{sf(x['dist4'],2)}",
            flush=True
        )

    # ========================================================
    # TELEGRAM
    # ========================================================

    alerts = final[
        :MAX_ALERTS
    ]

    if not alerts:

        print(
            "\n📭 Bu taramada "
            "LSK tipi güçlü pre-pump adayı yok.",
            flush=True
        )

    else:

        print(
            f"\n📨 Telegram'a "
            f"{len(alerts)} güçlü aday gönderiliyor...",
            flush=True
        )

        for x in alerts:

            message = format_alert(
                x
            )

            send_telegram(
                message
            )

            time.sleep(0.5)

    # ========================================================
    # SONUÇ
    # ========================================================

    elapsed = (
        time.time()
        -
        start_time
    )

    print(
        "\n====================================================",
        flush=True
    )

    print(
        "✅ RADAR TAMAMLANDI",
        flush=True
    )

    print(
        f"⏱️ Süre: {elapsed:.1f} saniye",
        flush=True
    )

    print(
        f"🪙 Futures: {len(symbols)}",
        flush=True
    )

    print(
        f"🟣 4H: {len(four_h)}",
        flush=True
    )

    print(
        f"🟢 1H: {len(one_h)}",
        flush=True
    )

    print(
        f"🏆 Final: {len(final)}",
        flush=True
    )

    print(
        f"📨 Telegram: {len(alerts)}",
        flush=True
    )

    print(
        "====================================================",
        flush=True
    )


# ============================================================
# PROGRAMI BAŞLAT
# ============================================================

if __name__ == "__main__":

    print(
        "### MAIN.PY V6.0 BAŞLADI ###",
        flush=True
    )

    try:

        main()

    except Exception as e:

        print(
            "\n❌ ANA PROGRAM HATASI",
            flush=True
        )

        print(
            str(e),
            flush=True
        )

        traceback.print_exc()

        raise
