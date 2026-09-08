import os
import time
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PUMP RADAR 12.0
#
# BTC YÖNÜ + COIN YÖNÜ
#
# 🟢 BTC BULLISH  -> SADECE LONG
# 🔴 BTC BEARISH  -> SADECE SHORT
# ⚪ BTC NEUTRAL  -> İŞLEM YOK
#
# TELEGRAM:
# SADECE GÜÇLÜ LONG / SHORT
# ============================================================


BASE = "https://contract.mexc.com"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

STATE_FILE = "signal_history.json"


# ============================================================
# AYARLAR
# ============================================================

MAX_WORKERS = 12

MIN_SCORE = 82

SIGNAL_COOLDOWN = 6 * 60 * 60

MIN_24H_VOLUME = 100000

# LONG için aşırı yükselmiş coin filtresi
MAX_24H_LONG = 12.0
MAX_1H_LONG = 5.0
MAX_15M_LONG = 3.5

# SHORT için aşırı düşmüş coin filtresi
MAX_24H_SHORT = -12.0
MAX_1H_SHORT = -5.0
MAX_15M_SHORT = -3.5

MIN_VOLUME_RATIO = 1.25


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
})


# ============================================================
# HTTP
# ============================================================

def get_json(url, params=None, timeout=15):

    try:

        r = session.get(
            url,
            params=params,
            timeout=timeout
        )

        if r.status_code != 200:
            return None

        return r.json()

    except Exception:
        return None


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(text):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram bilgileri yok.")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:

        r = session.post(
            url,
            data=payload,
            timeout=15
        )

        if r.status_code == 200:
            return True

        print("Telegram hata:", r.text[:300])

    except Exception as e:

        print("Telegram bağlantı hatası:", e)

    return False


# ============================================================
# STATE
# ============================================================

def load_state():

    try:

        if not os.path.exists(STATE_FILE):
            return {}

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:
        return {}


def save_state(state):

    try:

        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                state,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print("State kayıt hatası:", e)


# ============================================================
# CONTRACTS
# ============================================================

def get_contracts():

    data = get_json(
        f"{BASE}/api/v1/contract/detail"
    )

    if not data:
        return []

    rows = data.get("data", [])

    result = []

    for x in rows:

        try:

            symbol = str(
                x.get("symbol", "")
            ).upper()

            quote = str(
                x.get("quoteCoin", "")
            ).upper()

            settle = str(
                x.get("settleCoin", "")
            ).upper()

            state = x.get("state", 0)

            if quote != "USDT":
                continue

            if settle != "USDT":
                continue

            if not symbol.endswith("_USDT"):
                continue

            if state not in [0, 1, None]:
                continue

            result.append(symbol)

        except Exception:
            continue

    return result


# ============================================================
# TICKER
# ============================================================

def get_ticker(symbol):

    data = get_json(
        f"{BASE}/api/v1/contract/ticker",
        params={
            "symbol": symbol
        }
    )

    if not data:
        return None

    d = data.get("data")

    if not isinstance(d, dict):
        return None

    try:

        price = float(
            d.get("lastPrice", 0)
        )

        rise = float(
            d.get("riseRate", 0)
        )

        volume = float(
            d.get("volume24", 0)
        )

        if price <= 0:
            return None

        if abs(rise) < 1:
            rise *= 100

        return {
            "price": price,
            "change24": rise,
            "volume24": volume
        }

    except Exception:
        return None


# ============================================================
# KLINE
# ============================================================

def get_klines(
    symbol,
    interval="Min15",
    limit=120
):

    data = get_json(
        f"{BASE}/api/v1/contract/kline/{symbol}",
        params={
            "interval": interval
        }
    )

    if not data:
        return []

    d = data.get("data")

    if not isinstance(d, dict):
        return []

    try:

        times = d.get("time", [])
        opens = d.get("open", [])
        highs = d.get("high", [])
        lows = d.get("low", [])
        closes = d.get("close", [])
        vols = d.get("vol", [])

        rows = []

        n = min(
            len(times),
            len(opens),
            len(highs),
            len(lows),
            len(closes),
            len(vols)
        )

        for i in range(
            max(0, n - limit),
            n
        ):

            rows.append({
                "time": float(times[i]),
                "open": float(opens[i]),
                "high": float(highs[i]),
                "low": float(lows[i]),
                "close": float(closes[i]),
                "volume": float(vols[i])
            })

        return rows

    except Exception:
        return []


# ============================================================
# RSI
# ============================================================

def calculate_rsi(
    values,
    period=14
):

    if len(values) < period + 2:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        diff = (
            values[i]
            - values[i - 1]
        )

        if diff > 0:

            gains.append(diff)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(abs(diff))

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            (
                avg_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (
        period + 1
    )

    result = (
        sum(values[:period])
        / period
    )

    for price in values[period:]:

        result = (
            (
                price - result
            )
            * multiplier
        ) + result

    return result


# ============================================================
# ATR
# ============================================================

def calculate_atr(
    klines,
    period=14
):

    if len(klines) < period + 2:
        return None

    trs = []

    for i in range(
        1,
        len(klines)
    ):

        high = klines[i]["high"]
        low = klines[i]["low"]
        prev = klines[i - 1]["close"]

        tr = max(
            high - low,
            abs(high - prev),
            abs(low - prev)
        )

        trs.append(tr)

    if len(trs) < period:
        return None

    return (
        sum(trs[-period:])
        / period
    )


# ============================================================
# DEĞİŞİM
# ============================================================

def percent_change(
    klines,
    candles
):

    if len(klines) < candles + 1:
        return 0

    old = klines[
        -candles - 1
    ]["close"]

    new = klines[-1]["close"]

    if old <= 0:
        return 0

    return (
        (new - old)
        / old
    ) * 100


# ============================================================
# HACİM ORANI
# ============================================================

def volume_ratio(klines):

    if len(klines) < 25:
        return 0

    current = klines[-1]["volume"]

    previous = [
        x["volume"]
        for x in klines[-21:-1]
    ]

    if not previous:
        return 0

    avg = (
        sum(previous)
        / len(previous)
    )

    if avg <= 0:
        return 0

    return current / avg


# ============================================================
# HIGHER LOW
# ============================================================

def higher_low(klines):

    if len(klines) < 15:
        return False

    lows = [
        x["low"]
        for x in klines[-12:]
    ]

    recent = min(
        lows[-5:]
    )

    previous = min(
        lows[:7]
    )

    return recent > previous


# ============================================================
# LOWER HIGH
# ============================================================

def lower_high(klines):

    if len(klines) < 15:
        return False

    highs = [
        x["high"]
        for x in klines[-12:]
    ]

    recent = max(
        highs[-5:]
    )

    previous = max(
        highs[:7]
    )

    return recent < previous


# ============================================================
# DİRENÇ
# ============================================================

def resistance_level(klines):

    if len(klines) < 25:
        return None

    highs = [
        x["high"]
        for x in klines[-21:-1]
    ]

    if not highs:
        return None

    return max(highs)


# ============================================================
# DESTEK
# ============================================================

def support_level(klines):

    if len(klines) < 25:
        return None

    lows = [
        x["low"]
        for x in klines[-21:-1]
    ]

    if not lows:
        return None

    return min(lows)


# ============================================================
# LONG BREAKOUT
# ============================================================

def long_breakout(klines):

    resistance = resistance_level(
        klines
    )

    if resistance is None:
        return False, None

    close = klines[-1]["close"]

    return (
        close > resistance * 1.0015,
        resistance
    )


# ============================================================
# SHORT BREAKDOWN
# ============================================================

def short_breakdown(klines):

    support = support_level(
        klines
    )

    if support is None:
        return False, None

    close = klines[-1]["close"]

    return (
        close < support * 0.9985,
        support
    )


# ============================================================
# SIKIŞMA
# ============================================================

def compression(klines):

    if len(klines) < 25:
        return False

    ranges = []

    for x in klines[-20:]:

        if x["close"] <= 0:
            continue

        ranges.append(
            (
                x["high"]
                - x["low"]
            )
            / x["close"]
            * 100
        )

    if len(ranges) < 10:
        return False

    avg = (
        sum(ranges)
        / len(ranges)
    )

    recent = (
        sum(ranges[-5:])
        / 5
    )

    return recent < avg * 0.80


# ============================================================
# BTC YÖN ANALİZİ
# ============================================================

def analyze_btc():

    print()
    print("🌐 BTC yönü analiz ediliyor...")
    print("=" * 32)

    ticker = get_ticker(
        "BTC_USDT"
    )

    k15 = get_klines(
        "BTC_USDT",
        "Min15",
        100
    )

    k1h = get_klines(
        "BTC_USDT",
        "Min60",
        100
    )

    k4h = get_klines(
        "BTC_USDT",
        "Hour4",
        100
    )

    if (
        not ticker
        or len(k15) < 40
        or len(k1h) < 40
        or len(k4h) < 30
    ):

        print(
            "❌ BTC analizi alınamadı."
        )

        return {
            "direction": "NEUTRAL",
            "score": 0
        }

    c15 = [
        x["close"]
        for x in k15
    ]

    c1h = [
        x["close"]
        for x in k1h
    ]

    c4h = [
        x["close"]
        for x in k4h
    ]

    price = ticker["price"]

    change15 = percent_change(
        k15,
        1
    )

    change1h = percent_change(
        k1h,
        1
    )

    change4h = percent_change(
        k4h,
        1
    )

    rsi15 = calculate_rsi(c15)
    rsi1h = calculate_rsi(c1h)
    rsi4h = calculate_rsi(c4h)

    ema20_15 = ema(c15, 20)
    ema50_15 = ema(c15, 50)

    ema20_1h = ema(c1h, 20)
    ema50_1h = ema(c1h, 50)

    ema20_4h = ema(c4h, 20)
    ema50_4h = ema(c4h, 50)

    bullish = 0
    bearish = 0

    # --------------------------------------------------------
    # 15M
    # --------------------------------------------------------

    if (
        ema20_15
        and ema50_15
        and price > ema20_15
        and ema20_15 > ema50_15
    ):
        bullish += 1

    if (
        ema20_15
        and ema50_15
        and price < ema20_15
        and ema20_15 < ema50_15
    ):
        bearish += 1

    if change15 > 0:
        bullish += 1

    if change15 < 0:
        bearish += 1

    if rsi15 >= 50:
        bullish += 1

    if rsi15 <= 45:
        bearish += 1

    # --------------------------------------------------------
    # 1H
    # --------------------------------------------------------

    if (
        ema20_1h
        and ema50_1h
        and price > ema20_1h
        and ema20_1h > ema50_1h
    ):
        bullish += 2

    if (
        ema20_1h
        and ema50_1h
        and price < ema20_1h
        and ema20_1h < ema50_1h
    ):
        bearish += 2

    if change1h > 0:
        bullish += 1

    if change1h < 0:
        bearish += 1

    if rsi1h >= 50:
        bullish += 1

    if rsi1h <= 45:
        bearish += 1

    # --------------------------------------------------------
    # 4H
    # --------------------------------------------------------

    if (
        ema20_4h
        and ema50_4h
        and price > ema20_4h
        and ema20_4h > ema50_4h
    ):
        bullish += 2

    if (
        ema20_4h
        and ema50_4h
        and price < ema20_4h
        and ema20_4h < ema50_4h
    ):
        bearish += 2

    if change4h > 0:
        bullish += 1

    if change4h < 0:
        bearish += 1

    if rsi4h >= 50:
        bullish += 1

    if rsi4h <= 45:
        bearish += 1

    # --------------------------------------------------------
    # BTC YÖNÜ
    # --------------------------------------------------------

    difference = bullish - bearish

    if difference >= 3:

        direction = "BULLISH"

    elif difference <= -3:

        direction = "BEARISH"

    else:

        direction = "NEUTRAL"

    print(
        f"🌐 BTC YÖNÜ: {direction}"
    )

    print(
        f"15M: {change15:+.2f}%"
    )

    print(
        f"1H: {change1h:+.2f}%"
    )

    print(
        f"4H: {change4h:+.2f}%"
    )

    print(
        f"RSI 15M: {rsi15:.1f}"
    )

    print(
        f"RSI 1H: {rsi1h:.1f}"
    )

    print(
        f"RSI 4H: {rsi4h:.1f}"
    )

    print(
        f"Bullish skor: {bullish}"
    )

    print(
        f"Bearish skor: {bearish}"
    )

    print("=" * 32)

    return {
        "direction": direction,
        "score": difference,
        "change15": change15,
        "change1h": change1h,
        "change4h": change4h,
        "rsi15": rsi15,
        "rsi1h": rsi1h,
        "rsi4h": rsi4h
    }


# ============================================================
# COIN ANALİZİ
# ============================================================

def analyze_symbol(
    symbol,
    btc_direction
):

    ticker = get_ticker(symbol)

    if not ticker:
        return None

    price = ticker["price"]
    change24 = ticker["change24"]
    volume24 = ticker["volume24"]

    if volume24 < MIN_24H_VOLUME:
        return None

    # ========================================================
    # BTC NEUTRAL İSE İŞLEM YOK
    # ========================================================

    if btc_direction == "NEUTRAL":
        return None

    # ========================================================
    # KLINE
    # ========================================================

    k15 = get_klines(
        symbol,
        "Min15",
        100
    )

    k1h = get_klines(
        symbol,
        "Min60",
        100
    )

    k4h = get_klines(
        symbol,
        "Hour4",
        80
    )

    if (
        len(k15) < 40
        or len(k1h) < 40
        or len(k4h) < 30
    ):
        return None

    # ========================================================
    # DEĞİŞİMLER
    # ========================================================

    change15 = percent_change(
        k15,
        1
    )

    change1h = percent_change(
        k1h,
        1
    )

    # ========================================================
    # RSI
    # ========================================================

    closes15 = [
        x["close"]
        for x in k15
    ]

    closes1h = [
        x["close"]
        for x in k1h
    ]

    closes4h = [
        x["close"]
        for x in k4h
    ]

    rsi15 = calculate_rsi(
        closes15
    )

    rsi1h = calculate_rsi(
        closes1h
    )

    rsi4h = calculate_rsi(
        closes4h
    )

    if (
        rsi15 is None
        or rsi1h is None
        or rsi4h is None
    ):
        return None

    # ========================================================
    # HACİM
    # ========================================================

    vr = volume_ratio(k15)

    if vr < MIN_VOLUME_RATIO:
        return None

    # ========================================================
    # EMA
    # ========================================================

    ema20_1h = ema(
        closes1h,
        20
    )

    ema50_1h = ema(
        closes1h,
        50
    )

    ema20_4h = ema(
        closes4h,
        20
    )

    ema50_4h = ema(
        closes4h,
        50
    )

    # ========================================================
    # YAPILAR
    # ========================================================

    hl15 = higher_low(k15)
    hl1h = higher_low(k1h)

    lh15 = lower_high(k15)
    lh1h = lower_high(k1h)

    long_break, resistance = (
        long_breakout(k15)
    )

    short_break, support = (
        short_breakdown(k15)
    )

    squeeze = compression(k15)

    # ========================================================
    # LONG
    # ========================================================

    if btc_direction == "BULLISH":

        # Coin aşırı pump yaptıysa geç kalmış olabilir
        if change24 > MAX_24H_LONG:
            return None

        if change1h > MAX_1H_LONG:
            return None

        if change15 > MAX_15M_LONG:
            return None

        score = 0
        reasons = []

        # 15M pozitif momentum
        if change15 > 0:
            score += 8
            reasons.append(
                "15M MOMENTUM"
            )

        # 1H trend
        if (
            ema20_1h
            and ema50_1h
            and price > ema20_1h
            and ema20_1h > ema50_1h
        ):
            score += 18
            reasons.append(
                "1H BULL TREND"
            )

        # 4H trend
        if (
            ema20_4h
            and ema50_4h
            and price > ema20_4h
            and ema20_4h > ema50_4h
        ):
            score += 14
            reasons.append(
                "4H BULL TREND"
            )

        # Higher Low
        if hl15:
            score += 12
            reasons.append(
                "15M HIGHER LOW"
            )

        if hl1h:
            score += 10
            reasons.append(
                "1H HIGHER LOW"
            )

        # Hacim
        if vr >= 1.25:
            score += 12
            reasons.append(
                "HACİM"
            )

        if vr >= 1.60:
            score += 5

        # Breakout
        if long_break:
            score += 16
            reasons.append(
                "DİRENÇ KIRILIMI"
            )

        # RSI
        if (
            50 <= rsi15 <= 68
            and 48 <= rsi1h <= 68
        ):
            score += 8
            reasons.append(
                "RSI TEYİDİ"
            )

        # Sıkışma
        if squeeze:
            score += 7
            reasons.append(
                "SIKIŞMA"
            )

        # En az 2 yapı
        structure_count = sum([
            hl15,
            hl1h,
            long_break,
            (
                ema20_1h is not None
                and ema50_1h is not None
                and price > ema20_1h
                and ema20_1h > ema50_1h
            )
        ])

        if score < MIN_SCORE:
            return None

        if structure_count < 2:
            return None

        atr = calculate_atr(
            k15,
            14
        )

        if not atr or atr <= 0:
            return None

        stop = price - (
            atr * 1.35
        )

        risk = price - stop

        if risk <= 0:
            return None

        tp1 = price + (
            risk * 1.0
        )

        tp2 = price + (
            risk * 1.8
        )

        tp3 = price + (
            risk * 2.6
        )

        if long_break:

            signal_type = (
                "🔥 BTC DESTEKLİ LONG "
                "DİRENÇ KIRILIMI"
            )

        elif hl15 and hl1h:

            signal_type = (
                "🚀 BTC DESTEKLİ "
                "LONG PUMP ÖNCESİ"
            )

        else:

            signal_type = (
                "⚡ BTC DESTEKLİ "
                "LONG MOMENTUM"
            )

        return {
            "symbol": symbol,
            "direction": "LONG",
            "score": score,
            "price": price,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "stop": stop,
            "change24": change24,
            "change1h": change1h,
            "change15": change15,
            "volume_ratio": vr,
            "rsi15": rsi15,
            "rsi1h": rsi1h,
            "rsi4h": rsi4h,
            "resistance": resistance,
            "support": support,
            "higher_low": hl15,
            "higher_low_1h": hl1h,
            "lower_high": lh15,
            "lower_high_1h": lh1h,
            "breakout": long_break,
            "breakdown": False,
            "squeeze": squeeze,
            "signal_type": signal_type,
            "reasons": reasons
        }

    # ========================================================
    # SHORT
    # ========================================================

    if btc_direction == "BEARISH":

        # Çok fazla düşmüş coin geç kalınmış olabilir
        if change24 < MAX_24H_SHORT:
            return None

        if change1h < MAX_1H_SHORT:
            return None

        if change15 < MAX_15M_SHORT:
            return None

        score = 0
        reasons = []

        # 15M negatif momentum
        if change15 < 0:
            score += 8
            reasons.append(
                "15M NEGATİF MOMENTUM"
            )

        # 1H bearish trend
        if (
            ema20_1h
            and ema50_1h
            and price < ema20_1h
            and ema20_1h < ema50_1h
        ):
            score += 18
            reasons.append(
                "1H BEAR TREND"
            )

        # 4H bearish trend
        if (
            ema20_4h
            and ema50_4h
            and price < ema20_4h
            and ema20_4h < ema50_4h
        ):
            score += 14
            reasons.append(
                "4H BEAR TREND"
            )

        # Lower High
        if lh15:
            score += 12
            reasons.append(
                "15M LOWER HIGH"
            )

        if lh1h:
            score += 10
            reasons.append(
                "1H LOWER HIGH"
            )

        # Hacim
        if vr >= 1.25:
            score += 12
            reasons.append(
                "HACİM"
            )

        if vr >= 1.60:
            score += 5

        # Destek kırılımı
        if short_break:
            score += 16
            reasons.append(
                "DESTEK KIRILIMI"
            )

        # RSI bearish
        if (
            32 <= rsi15 <= 50
            and 32 <= rsi1h <= 52
        ):
            score += 8
            reasons.append(
                "RSI BEAR TEYİDİ"
            )

        # Sıkışma
        if squeeze:
            score += 7
            reasons.append(
                "SIKIŞMA"
            )

        structure_count = sum([
            lh15,
            lh1h,
            short_break,
            (
                ema20_1h is not None
                and ema50_1h is not None
                and price < ema20_1h
                and ema20_1h < ema50_1h
            )
        ])

        if score < MIN_SCORE:
            return None

        if structure_count < 2:
            return None

        atr = calculate_atr(
            k15,
            14
        )

        if not atr or atr <= 0:
            return None

        # ====================================================
        # SHORT STOP / TP
        # ====================================================

        stop = price + (
            atr * 1.35
        )

        risk = stop - price

        if risk <= 0:
            return None

        tp1 = price - (
            risk * 1.0
        )

        tp2 = price - (
            risk * 1.8
        )

        tp3 = price - (
            risk * 2.6
        )

        if short_break:

            signal_type = (
                "🔻 BTC DESTEKLİ SHORT "
                "DESTEK KIRILIMI"
            )

        elif lh15 and lh1h:

            signal_type = (
                "💥 BTC DESTEKLİ "
                "SHORT DÜŞÜŞ ÖNCESİ"
            )

        else:

            signal_type = (
                "⚡ BTC DESTEKLİ "
                "SHORT MOMENTUM"
            )

        return {
            "symbol": symbol,
            "direction": "SHORT",
            "score": score,
            "price": price,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "stop": stop,
            "change24": change24,
            "change1h": change1h,
            "change15": change15,
            "volume_ratio": vr,
            "rsi15": rsi15,
            "rsi1h": rsi1h,
            "rsi4h": rsi4h,
            "resistance": resistance,
            "support": support,
            "higher_low": False,
            "higher_low_1h": False,
            "lower_high": lh15,
            "lower_high_1h": lh1h,
            "breakout": False,
            "breakdown": short_break,
            "squeeze": squeeze,
            "signal_type": signal_type,
            "reasons": reasons
        }

    return None


# ============================================================
# FİYAT FORMAT
# ============================================================

def format_price(price):

    if price >= 100:
        return f"{price:.2f}"

    if price >= 1:
        return f"{price:.5f}"

    if price >= 0.01:
        return f"{price:.6f}"

    if price >= 0.0001:
        return f"{price:.8f}"

    return f"{price:.10f}"


# ============================================================
# TELEGRAM MESAJ
# ============================================================

def build_message(x, btc):

    direction = x["direction"]

    if direction == "LONG":

        header = "🟢 <b>BTC DESTEKLİ LONG</b>"

    else:

        header = "🔴 <b>BTC DESTEKLİ SHORT</b>"

    return f"""
{header}

💎 <b>{x["symbol"]}</b>
⭐ <b>Skor: {x["score"]}/100</b>

📌 <b>{x["signal_type"]}</b>

🌐 BTC Yönü:
<b>{btc["direction"]}</b>

🟢 Giriş:
<b>{format_price(x["price"])}</b>

🎯 TP1:
<b>{format_price(x["tp1"])}</b>

🎯 TP2:
<b>{format_price(x["tp2"])}</b>

🎯 TP3:
<b>{format_price(x["tp3"])}</b>

🛑 Stop:
<b>{format_price(x["stop"])}</b>

📊 24H:
{x["change24"]:+.2f}%

⚡ 1H:
{x["change1h"]:+.2f}%

🔥 15M:
{x["change15"]:+.2f}%

💥 Hacim:
<b>{x["volume_ratio"]:.2f}x</b>

📈 RSI 15M:
{x["rsi15"]:.1f}

📈 RSI 1H:
{x["rsi1h"]:.1f}

📊 RSI 4H:
{x["rsi4h"]:.1f}

📌 Yapı:

Higher Low:
{"✅" if x["higher_low"] else "❌"}

1H Higher Low:
{"✅" if x["higher_low_1h"] else "❌"}

Lower High:
{"✅" if x["lower_high"] else "❌"}

1H Lower High:
{"✅" if x["lower_high_1h"] else "❌"}

Hacim:
{"✅" if x["volume_ratio"] >= 1.25 else "❌"}

Direnç kırılımı:
{"✅" if x["breakout"] else "❌"}

Destek kırılımı:
{"✅" if x["breakdown"] else "❌"}

🌐 BTC 15M:
{btc["change15"]:+.2f}%

🌐 BTC 1H:
{btc["change1h"]:+.2f}%

🌐 BTC 4H:
{btc["change4h"]:+.2f}%

💎 <b>MEXC USDT FUTURES</b>

⚠️ <i>BTC yönü ve coin yapısı aynı yönde olan güçlü sinyal.</i>
"""


# ============================================================
# COOLDOWN
# ============================================================

def can_send(
    symbol,
    direction,
    state
):

    key = (
        f"{symbol}_{direction}"
    )

    now = time.time()

    old = state.get(key)

    if old is None:
        return True

    try:

        last_time = float(old)

        if (
            now - last_time
            >= SIGNAL_COOLDOWN
        ):
            return True

    except Exception:
        return True

    return False


# ============================================================
# ANA RADAR
# ============================================================

def main():

    print()
    print(
        "🚀 MEXC PUMP RADAR 12.0"
    )

    print(
        "🌐 BTC YÖNÜ + LONG / SHORT"
    )

    print(
        "🟢 BULLISH = LONG"
    )

    print(
        "🔴 BEARISH = SHORT"
    )

    print(
        "⚪ NEUTRAL = İŞLEM YOK"
    )

    print()

    # ========================================================
    # BTC
    # ========================================================

    btc = analyze_btc()

    btc_direction = btc[
        "direction"
    ]

    # ========================================================
    # BTC NEUTRAL
    # ========================================================

    if btc_direction == "NEUTRAL":

        print()
        print(
            "⚪ BTC NEUTRAL"
        )

        print(
            "🚫 Coin işlemi yapılmayacak."
        )

        return

    # ========================================================
    # CONTRACTS
    # ========================================================

    symbols = get_contracts()

    print()
    print(
        f"Futures kontrat: "
        f"{len(symbols)}"
    )

    if not symbols:

        print(
            "❌ Futures listesi alınamadı."
        )

        return

    # ========================================================
    # STATE
    # ========================================================

    state = load_state()

    candidates = []

    # ========================================================
    # TARAMA
    # ========================================================

    total = len(symbols)

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_symbol,
                symbol,
                btc_direction
            ): symbol

            for symbol in symbols
        }

        completed = 0

        for future in as_completed(
            futures
        ):

            completed += 1

            symbol = futures[
                future
            ]

            try:

                result = future.result()

                if result:

                    candidates.append(
                        result
                    )

                    print(
                        f"🔥 "
                        f"{result['direction']} "
                        f"{symbol} "
                        f"{result['score']}"
                    )

            except Exception as e:

                print(
                    f"Hata "
                    f"{symbol}: {e}"
                )

            if (
                completed % 25 == 0
                or completed == total
            ):

                print(
                    f"İlerleme: "
                    f"{completed}/{total}"
                )

    # ========================================================
    # SIRALAMA
    # ========================================================

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    print()
    print(
        f"🎯 Güçlü sinyal: "
        f"{len(candidates)}"
    )

    # ========================================================
    # TELEGRAM
    # ========================================================

    sent = 0

    for candidate in candidates:

        symbol = candidate[
            "symbol"
        ]

        direction = candidate[
            "direction"
        ]

        if not can_send(
            symbol,
            direction,
            state
        ):

            print(
                f"⏳ Cooldown: "
                f"{direction} "
                f"{symbol}"
            )

            continue

        message = build_message(
            candidate,
            btc
        )

        ok = telegram_send(
            message
        )

        if ok:

            sent += 1

            key = (
                f"{symbol}_{direction}"
            )

            state[key] = time.time()

            save_state(state)

            print(
                f"✅ GÖNDERİLDİ: "
                f"{direction} "
                f"{symbol} "
                f"{candidate['score']}"
            )

    # ========================================================
    # GITHUB LOGU
    # ========================================================

    print()
    print(
        f"📨 Telegram gönderilen: "
        f"{sent}"
    )

    print(
        "🏁 Tarama tamamlandı."
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
