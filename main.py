import os
import time
import threading
import requests
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PRE-PUMP RADAR V5.0
#
# 4H  = ANA YAPI / SIKIŞMA
# 1H  = GÜÇ / HACİM
# 15M = TETİK / BREAKOUT ÖNCESİ
#
# SADECE MEXC USDT FUTURES
# SADECE TEKNİK RADAR
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

MIN_SCORE = 62

CANDLE_COUNT = 90

REQUEST_INTERVAL = 0.12

TIMEOUT = 12

FOUR_H_MAX = 220

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

        wait = REQUEST_INTERVAL - (now - last_request_time)

        if wait > 0:
            time.sleep(wait)

        last_request_time = time.time()


# ============================================================
# MEXC GET
# ============================================================

def mexc_get(path, params=None, retry=3):

    for attempt in range(retry):

        try:

            rate_limit()

            url = BASE + path

            r = requests.get(
                url,
                params=params,
                timeout=TIMEOUT
            )

            if r.status_code != 200:

                print(
                    f"⚠️ HTTP {r.status_code} "
                    f"{path}",
                    flush=True
                )

                time.sleep(1)

                continue

            data = r.json()

            return data

        except Exception as e:

            print(
                f"⚠️ API hata: {type(e).__name__} "
                f"{str(e)[:120]}",
                flush=True
            )

            time.sleep(1)

    return None


# ============================================================
# FUTURES SYMBOLLER
# ============================================================

def get_symbols():

    print(
        "\n🔎 MEXC Futures sembolleri alınıyor...",
        flush=True
    )

    data = mexc_get(
        "/api/v1/contract/detail"
    )

    if not data:

        print(
            "❌ Contract detail boş",
            flush=True
        )

        return []

    rows = data.get("data", [])

    if not isinstance(rows, list):

        print(
            "❌ Contract detail formatı beklenmiyor",
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

            # MEXC aktif kontrat filtresi
            state = item.get("state")

            if state is not None:

                try:
                    if int(state) != 0:
                        continue
                except:
                    pass

            symbols.append(symbol)

        except:
            continue

    symbols = sorted(set(symbols))

    print(
        f"✅ Futures sembol sayısı: {len(symbols)}",
        flush=True
    )

    return symbols


# ============================================================
# KLINE
# ============================================================

def get_klines(symbol, interval, count=CANDLE_COUNT):

    try:

        interval_seconds = {
            "Min15": 15 * 60,
            "Min60": 60 * 60,
            "Hour4": 4 * 60 * 60
        }

        seconds = interval_seconds[interval]

        end = int(time.time())

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

        if n < 40:
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

        if len(closes) < 40:
            return None

        return {
            "close": closes,
            "high": highs,
            "low": lows,
            "volume": volumes
        }

    except Exception:

        return None


# ============================================================
# MATEMATİK
# ============================================================

def sma(values, period):

    if len(values) < period:
        return None

    return sum(
        values[-period:]
    ) / period


def rsi(values, period=14):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(
        len(values) - period,
        len(values)
    ):

        change = (
            values[i] -
            values[i - 1]
        )

        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


def pct_change(a, b):

    if b == 0:
        return 0

    return (
        (a - b) / b
    ) * 100


def volume_ratio(volumes, period=20):

    if len(volumes) < period + 1:
        return 1.0

    avg = sum(
        volumes[-period-1:-1]
    ) / period

    if avg <= 0:
        return 1.0

    return (
        volumes[-1] / avg
    )


def recent_volume_ratio(volumes):

    if len(volumes) < 25:
        return 1.0

    recent = sum(
        volumes[-5:]
    ) / 5

    previous = sum(
        volumes[-25:-5]
    ) / 20

    if previous <= 0:
        return 1.0

    return recent / previous


def compression_score(highs, lows):

    if len(highs) < 30:
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
        recent_high - recent_low
    )

    old_range = (
        old_high - old_low
    )

    if old_range <= 0:
        return 0

    ratio = (
        recent_range / old_range
    )

    if ratio <= 0.45:
        return 20

    if ratio <= 0.60:
        return 15

    if ratio <= 0.75:
        return 10

    if ratio <= 0.90:
        return 5

    return 0


def higher_low_score(lows):

    if len(lows) < 30:
        return 0

    a = min(lows[-30:-20])
    b = min(lows[-20:-10])
    c = min(lows[-10:])

    score = 0

    if b > a:
        score += 5

    if c > b:
        score += 10

    return score


def resistance_distance(closes, highs):

    if len(closes) < 30:
        return 999

    current = closes[-1]

    resistance = max(
        highs[-30:]
    )

    if resistance <= 0:
        return 999

    return (
        (resistance - current)
        / resistance
    ) * 100


def momentum(closes, candles):

    if len(closes) < candles + 1:
        return 0

    return pct_change(
        closes[-1],
        closes[-candles-1]
    )


# ============================================================
# PUMP FİLTRESİ
# ============================================================

def already_pumped(closes):

    if len(closes) < 30:
        return True

    move_5 = pct_change(
        closes[-1],
        closes[-6]
    )

    move_10 = pct_change(
        closes[-1],
        closes[-11]
    )

    move_20 = pct_change(
        closes[-1],
        closes[-21]
    )

    # Son 5 mumda çok sert hareket
    if move_5 > 18:
        return True

    # Son 10 mumda aşırı hareket
    if move_10 > 28:
        return True

    # Son 20 mumda zaten büyük pump
    if move_20 > 45:
        return True

    return False


# ============================================================
# 4H ANALİZ
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

    current = closes[-1]

    r = rsi(closes)

    ma20 = sma(closes, 20)
    ma50 = sma(closes, 50)

    vr = volume_ratio(
        volumes,
        20
    )

    recent_vr = recent_volume_ratio(
        volumes
    )

    comp = compression_score(
        highs,
        lows
    )

    hl = higher_low_score(
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

    # Zaten pump olmuşları çıkar
    if already_pumped(closes):

        return None

    score = 0
    reasons = []

    # RSI
    if r is not None:

        if 45 <= r <= 62:
            score += 12
            reasons.append(
                "RSI dengeli"
            )

        elif 40 <= r < 45:
            score += 7

        elif 62 < r <= 68:
            score += 8

    # MA
    if ma20 and ma50:

        if current > ma20:
            score += 7
            reasons.append(
                "MA20 üstü"
            )

        if ma20 >= ma50:
            score += 8
            reasons.append(
                "MA trendi pozitif"
            )

    # Sıkışma
    score += comp

    if comp >= 15:
        reasons.append(
            "4H sıkışma"
        )

    # Higher low
    score += hl

    if hl >= 10:
        reasons.append(
            "Higher Low"
        )

    # Dirence yakınlık
    if 0 <= distance <= 3:
        score += 15
        reasons.append(
            "Dirence çok yakın"
        )

    elif 3 < distance <= 6:
        score += 11
        reasons.append(
            "Dirence yakın"
        )

    elif 6 < distance <= 10:
        score += 6

    # Momentum
    if 0 < mom10 < 12:
        score += 7

    elif mom10 >= 12:
        score += 3

    # Hacim
    if 0.8 <= vr <= 1.8:
        score += 5

    if recent_vr >= 1.15:
        score += 5
        reasons.append(
            "Hacim canlanıyor"
        )

    # Çok aşağıda olan coinleri azalt
    if mom10 < -15:
        score -= 8

    return {
        "score": score,
        "rsi": r,
        "volume_ratio": vr,
        "recent_volume": recent_vr,
        "distance": distance,
        "momentum": mom10,
        "reasons": reasons,
        "price": current
    }


# ============================================================
# 1H ANALİZ
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

    ma20 = sma(closes, 20)
    ma50 = sma(closes, 50)

    vr = volume_ratio(
        volumes,
        20
    )

    recent_vr = recent_volume_ratio(
        volumes
    )

    hl = higher_low_score(
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

    score = 0
    reasons = []

    # RSI
    if r is not None:

        if 50 <= r <= 67:
            score += 12
            reasons.append(
                "1H RSI güçlü"
            )

        elif 45 <= r < 50:
            score += 6

        elif r > 72:
            score -= 10

    # MA
    if ma20 and ma50:

        if current > ma20:
            score += 8
            reasons.append(
                "1H MA20 üstü"
            )

        if ma20 > ma50:
            score += 7

    # Hacim
    if vr >= 1.20:
        score += 12
        reasons.append(
            "1H hacim artışı"
        )

    elif vr >= 1.05:
        score += 7

    # Son hacim
    if recent_vr >= 1.20:
        score += 7
        reasons.append(
            "Hacim hızlanıyor"
        )

    # Higher low
    score += min(
        hl,
        12
    )

    # Momentum
    if 0 < mom5 < 8:
        score += 8
        reasons.append(
            "Kontrollü momentum"
        )

    elif 8 <= mom5 <= 15:
        score += 5

    elif mom5 > 18:
        score -= 5

    if 0 < mom10 < 18:
        score += 5

    # Dirence yakın
    if 0 <= distance <= 5:
        score += 8
        reasons.append(
            "Breakout bölgesinde"
        )

    return {
        "score": score,
        "rsi": r,
        "volume_ratio": vr,
        "recent_volume": recent_vr,
        "distance": distance,
        "momentum": mom5,
        "reasons": reasons,
        "price": current
    }


# ============================================================
# 15M TETİK
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

    recent_vr = recent_volume_ratio(
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

    score = 0
    reasons = []

    # RSI
    if r is not None:

        if 50 <= r <= 70:
            score += 10
            reasons.append(
                "15M RSI uygun"
            )

        elif 45 <= r < 50:
            score += 5

        elif r > 75:
            score -= 8

    # Hacim
    if vr >= 1.40:
        score += 15
        reasons.append(
            "15M hacim patlıyor"
        )

    elif vr >= 1.15:
        score += 9
        reasons.append(
            "15M hacim artıyor"
        )

    elif vr >= 1.0:
        score += 4

    # Son 5 mum hacmi
    if recent_vr >= 1.25:
        score += 8
        reasons.append(
            "Kısa vadeli hacim artışı"
        )

    # Momentum
    if 0 < mom3 < 6:
        score += 7

    elif 6 <= mom3 <= 12:
        score += 5

    elif mom3 > 15:
        score -= 5

    if 0 < mom5 < 12:
        score += 6

    # Direnç
    if 0 <= distance <= 3:
        score += 12
        reasons.append(
            "15M direnç yakınında"
        )

    elif 3 < distance <= 6:
        score += 7

    return {
        "score": score,
        "rsi": r,
        "volume_ratio": vr,
        "recent_volume": recent_vr,
        "distance": distance,
        "momentum": mom3,
        "reasons": reasons,
        "price": current
    }


# ============================================================
# COIN TARAMA
# ============================================================

def scan_symbol(symbol):

    try:

        # ----------------------------------------------------
        # 4H
        # ----------------------------------------------------

        data4 = get_klines(
            symbol,
            "Hour4",
            CANDLE_COUNT
        )

        a4 = analyze_4h(data4)

        if not a4:
            return None

        # 4H ana filtre
        if a4["score"] < 35:
            return None

        # ----------------------------------------------------
        # 1H
        # ----------------------------------------------------

        data1 = get_klines(
            symbol,
            "Min60",
            CANDLE_COUNT
        )

        a1 = analyze_1h(data1)

        if not a1:
            return None

        if a1["score"] < 22:
            return None

        # ----------------------------------------------------
        # 15M
        # ----------------------------------------------------

        data15 = get_klines(
            symbol,
            "Min15",
            CANDLE_COUNT
        )

        a15 = analyze_15m(data15)

        if not a15:
            return None

        total = (
            a4["score"] * 0.45
            +
            a1["score"] * 0.35
            +
            a15["score"] * 0.20
        )

        total = round(
            total,
            1
        )

        if total < MIN_SCORE:
            return None

        reasons = []

        reasons.extend(
            a4["reasons"][:4]
        )

        reasons.extend(
            a1["reasons"][:4]
        )

        reasons.extend(
            a15["reasons"][:3]
        )

        # tekrarları temizle
        unique_reasons = []

        for r in reasons:

            if r not in unique_reasons:
                unique_reasons.append(r)

        return {
            "symbol": symbol,
            "score": total,
            "price": a15["price"],

            "rsi4": a4["rsi"],
            "rsi1": a1["rsi"],
            "rsi15": a15["rsi"],

            "vol4": a4["volume_ratio"],
            "vol1": a1["volume_ratio"],
            "vol15": a15["volume_ratio"],

            "dist4": a4["distance"],
            "dist1": a1["distance"],
            "dist15": a15["distance"],

            "mom1": a1["momentum"],
            "mom15": a15["momentum"],

            "reasons": unique_reasons
        }

    except Exception as e:

        print(
            f"⚠️ {symbol} tarama hatası: "
            f"{str(e)[:100]}",
            flush=True
        )

        return None


# ============================================================
# API TEST
# ============================================================

def api_test():

    print(
        "\n🧪 KLINE API TESTİ",
        flush=True
    )

    test = get_klines(
        "BTC_USDT",
        "Min15",
        50
    )

    if test:

        print(
            f"✅ Kline API ÇALIŞIYOR | "
            f"{len(test['close'])} mum",
            flush=True
        )

        print(
            f"BTC fiyat: "
            f"{test['close'][-1]}",
            flush=True
        )

        return True

    print(
        "❌ Kline API başarısız",
        flush=True
    )

    return False


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(text):

    if not TOKEN or not CHAT_ID:

        print(
            "⚠️ Telegram TOKEN veya CHAT_ID yok",
            flush=True
        )

        return False

    try:

        url = (
            "https://api.telegram.org/bot"
            f"{TOKEN}/sendMessage"
        )

        payload = {
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }

        r = requests.post(
            url,
            json=payload,
            timeout=15
        )

        if r.status_code == 200:

            print(
                "📨 Telegram gönderildi",
                flush=True
            )

            return True

        print(
            f"❌ Telegram HTTP {r.status_code}",
            flush=True
        )

        print(
            r.text[:300],
            flush=True
        )

    except Exception as e:

        print(
            f"❌ Telegram hata: {e}",
            flush=True
        )

    return False


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def format_alert(x):

    symbol = x["symbol"]

    score = x["score"]

    price = x["price"]

    r4 = x["rsi4"]
    r1 = x["rsi1"]
    r15 = x["rsi15"]

    v1 = x["vol1"]
    v15 = x["vol15"]

    d4 = x["dist4"]

    m1 = x["mom1"]
    m15 = x["mom15"]

    reasons = x["reasons"]

    reason_text = "\n".join(
        f"• {r}"
        for r in reasons[:8]
    )

    return (
        "🚨 <b>PRE-PUMP RADAR</b>\n"
        "\n"
        f"🪙 <b>{symbol}</b>\n"
        f"⭐ Güç Skoru: <b>{score}/100</b>\n"
        f"💰 Fiyat: <b>{price:.8g}</b>\n"
        "\n"
        "📊 <b>RSI</b>\n"
        f"4H: {r4:.1f if r4 is not None else 'N/A'}\n"
        f"1H: {r1:.1f if r1 is not None else 'N/A'}\n"
        f"15M: {r15:.1f if r15 is not None else 'N/A'}\n"
        "\n"
        "🔥 <b>HACİM</b>\n"
        f"1H: {v1:.2f}x\n"
        f"15M: {v15:.2f}x\n"
        "\n"
        "📈 <b>MOMENTUM</b>\n"
        f"1H: {m1:.2f}%\n"
        f"15M: {m15:.2f}%\n"
        "\n"
        f"🎯 Direnç mesafesi: %{d4:.2f}\n"
        "\n"
        "🔎 <b>NEDEN ADAY?</b>\n"
        f"{reason_text}\n"
        "\n"
        "⚠️ Teknik radar sinyalidir. "
        "Kesin pump garantisi değildir."
    )


# ============================================================
# GÜVENLİ FORMAT
# ============================================================

def safe_float(value, digits=2):

    if value is None:
        return "N/A"

    try:
        return f"{float(value):.{digits}f}"
    except:
        return "N/A"


def format_alert(x):

    reasons = x["reasons"]

    reason_text = "\n".join(
        f"• {r}"
        for r in reasons[:8]
    )

    return (
        "🚨 <b>PRE-PUMP RADAR</b>\n"
        "\n"
        f"🪙 <b>{x['symbol']}</b>\n"
        f"⭐ Güç Skoru: <b>{x['score']}/100</b>\n"
        f"💰 Fiyat: <b>{x['price']:.8g}</b>\n"
        "\n"
        "📊 <b>RSI</b>\n"
        f"4H: {safe_float(x['rsi4'], 1)}\n"
        f"1H: {safe_float(x['rsi1'], 1)}\n"
        f"15M: {safe_float(x['rsi15'], 1)}\n"
        "\n"
        "🔥 <b>HACİM</b>\n"
        f"1H: {safe_float(x['vol1'], 2)}x\n"
        f"15M: {safe_float(x['vol15'], 2)}x\n"
        "\n"
        "📈 <b>MOMENTUM</b>\n"
        f"1H: {safe_float(x['mom1'], 2)}%\n"
        f"15M: {safe_float(x['mom15'], 2)}%\n"
        "\n"
        f"🎯 4H direnç mesafesi: "
        f"%{safe_float(x['dist4'], 2)}\n"
        "\n"
        "🔎 <b>NEDEN ADAY?</b>\n"
        f"{reason_text}\n"
        "\n"
        "⚠️ Teknik radar sinyalidir; "
        "kesin pump garantisi değildir."
    )


# ============================================================
# ANA PROGRAM
# ============================================================

def main():

    start_time = time.time()

    print(
        "\n"
        "====================================================\n"
        "🚀 MEXC PRE-PUMP RADAR V5.0\n"
        "====================================================",
        flush=True
    )

    print(
        "📡 MEXC Futures taraması başlıyor...",
        flush=True
    )

    print(
        f"⚙️ MIN SCORE: {MIN_SCORE}",
        flush=True
    )

    print(
        f"⚙️ MAX ALERT: {MAX_ALERTS}",
        flush=True
    )

    # --------------------------------------------------------
    # API TEST
    # --------------------------------------------------------

    if not api_test():

        print(
            "❌ API testi başarısız. Program durduruldu.",
            flush=True
        )

        return

    # --------------------------------------------------------
    # SYMBOLS
    # --------------------------------------------------------

    symbols = get_symbols()

    if not symbols:

        print(
            "❌ Futures sembol bulunamadı.",
            flush=True
        )

        return

    print(
        f"\n🔍 {len(symbols)} coin taranacak...",
        flush=True
    )

    # --------------------------------------------------------
    # 4H TARAMA
    # --------------------------------------------------------

    four_h_candidates = []

    completed = 0

    print(
        "\n🟣 4H ANA YAPI TARAMASI...",
        flush=True
    )

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                lambda s: (
                    s,
                    get_klines(
                        s,
                        "Hour4",
                        CANDLE_COUNT
                    )
                ),
                symbol
            ): symbol
            for symbol in symbols
        }

        for future in as_completed(futures):

            completed += 1

            symbol = futures[future]

            try:

                s, data = future.result()

                a = analyze_4h(data)

                if a and a["score"] >= 35:

                    four_h_candidates.append(
                        {
                            "symbol": s,
                            "data4": data,
                            "a4": a
                        }
                    )

            except Exception as e:

                print(
                    f"⚠️ {symbol}: {str(e)[:80]}",
                    flush=True
                )

            if (
                completed % 100 == 0
                or completed == len(symbols)
            ):

                print(
                    f"4H ilerleme: "
                    f"{completed}/{len(symbols)} | "
                    f"Aday: "
                    f"{len(four_h_candidates)}",
                    flush=True
                )

    four_h_candidates.sort(
        key=lambda x: x["a4"]["score"],
        reverse=True
    )

    four_h_candidates = (
        four_h_candidates[:FOUR_H_MAX]
    )

    print(
        f"\n✅ 4H güçlü aday: "
        f"{len(four_h_candidates)}",
        flush=True
    )

    # --------------------------------------------------------
    # 1H
    # --------------------------------------------------------

    one_h_candidates = []

    print(
        "\n🟢 1H GÜÇ TEYİDİ...",
        flush=True
    )

    def scan_1h_item(item):

        symbol = item["symbol"]

        data1 = get_klines(
            symbol,
            "Min60",
            CANDLE_COUNT
        )

        a1 = analyze_1h(data1)

        if not a1:
            return None

        if a1["score"] < 22:
            return None

        return {
            **item,
            "data1": data1,
            "a1": a1
        }

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                scan_1h_item,
                item
            )
            for item in four_h_candidates
        ]

        for future in as_completed(futures):

            try:

                result = future.result()

                if result:

                    one_h_candidates.append(
                        result
                    )

            except Exception as e:

                print(
                    f"⚠️ 1H hata: "
                    f"{str(e)[:100]}",
                    flush=True
                )

    one_h_candidates.sort(
        key=lambda x: (
            x["a4"]["score"]
            +
            x["a1"]["score"]
        ),
        reverse=True
    )

    one_h_candidates = (
        one_h_candidates[:ONE_H_MAX]
    )

    print(
        f"✅ 1H güçlü aday: "
        f"{len(one_h_candidates)}",
        flush=True
    )

    # --------------------------------------------------------
    # 15M
    # --------------------------------------------------------

    final_candidates = []

    print(
        "\n🟠 15M TETİK TARAMASI...",
        flush=True
    )

    def scan_15m_item(item):

        symbol = item["symbol"]

        data15 = get_klines(
            symbol,
            "Min15",
            CANDLE_COUNT
        )

        a15 = analyze_15m(data15)

        if not a15:
            return None

        total = (
            item["a4"]["score"] * 0.45
            +
            item["a1"]["score"] * 0.35
            +
            a15["score"] * 0.20
        )

        total = round(
            total,
            1
        )

        if total < MIN_SCORE:
            return None

        reasons = []

        reasons.extend(
            item["a4"]["reasons"][:4]
        )

        reasons.extend(
            item["a1"]["reasons"][:4]
        )

        reasons.extend(
            a15["reasons"][:4]
        )

        unique_reasons = []

        for reason in reasons:

            if reason not in unique_reasons:

                unique_reasons.append(
                    reason
                )

        return {
            "symbol": symbol,
            "score": total,

            "price": a15["price"],

            "rsi4": item["a4"]["rsi"],
            "rsi1": item["a1"]["rsi"],
            "rsi15": a15["rsi"],

            "vol4": item["a4"]["volume_ratio"],
            "vol1": item["a1"]["volume_ratio"],
            "vol15": a15["volume_ratio"],

            "dist4": item["a4"]["distance"],
            "dist1": item["a1"]["distance"],
            "dist15": a15["distance"],

            "mom1": item["a1"]["momentum"],
            "mom15": a15["momentum"],

            "reasons": unique_reasons
        }

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                scan_15m_item,
                item
            )
            for item in one_h_candidates
        ]

        for future in as_completed(futures):

            try:

                result = future.result()

                if result:

                    final_candidates.append(
                        result
                    )

            except Exception as e:

                print(
                    f"⚠️ 15M hata: "
                    f"{str(e)[:100]}",
                    flush=True
                )

    # --------------------------------------------------------
    # SIRALAMA
    # --------------------------------------------------------

    final_candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    print(
        "\n====================================================",
        flush=True
    )

    print(
        f"🏆 FİNAL ADAY SAYISI: "
        f"{len(final_candidates)}",
        flush=True
    )

    print(
        "====================================================",
        flush=True
    )

    for i, x in enumerate(
        final_candidates[:15],
        1
    ):

        print(
            f"{i:02d}. "
            f"{x['symbol']} "
            f"| SCORE {x['score']} "
            f"| RSI15 {safe_float(x['rsi15'],1)} "
            f"| VOL15 {safe_float(x['vol15'],2)}x "
            f"| DIR %{safe_float(x['dist4'],2)}",
            flush=True
        )

    # --------------------------------------------------------
    # TELEGRAM MAX 6
    # --------------------------------------------------------

    alerts = final_candidates[
        :MAX_ALERTS
    ]

    if not alerts:

        print(
            "\n📭 Bu taramada güçlü pre-pump adayı yok.",
            flush=True
        )

    else:

        print(
            f"\n📨 Telegram'a "
            f"{len(alerts)} aday gönderiliyor...",
            flush=True
        )

        for x in alerts:

            message = format_alert(x)

            send_telegram(
                message
            )

            time.sleep(0.5)

    # --------------------------------------------------------
    # ÖZET
    # --------------------------------------------------------

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
        f"🟣 4H aday: "
        f"{len(four_h_candidates)}",
        flush=True
    )

    print(
        f"🟢 1H aday: "
        f"{len(one_h_candidates)}",
        flush=True
    )

    print(
        f"🏆 Final: "
        f"{len(final_candidates)}",
        flush=True
    )

    print(
        f"📨 Telegram: "
        f"{len(alerts)}",
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
        "### MAIN.PY GERÇEKTEN ÇALIŞIYOR ###",
        flush=True
    )

    try:

        main()

    except Exception as e:

        print(
            "\n❌ ANA PROGRAM HATASI:",
            flush=True
        )

        print(
            str(e),
            flush=True
        )

        traceback.print_exc()

        raise
