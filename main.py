import os
import time
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PUMP RADAR 11.0
#
# BTC YÖN FİLTRESİ + LONG / SHORT MOTORU
#
# 🟢 BTC BULLISH  -> SADECE LONG
# 🔴 BTC BEARISH  -> SADECE SHORT
# ⚪ BTC NEUTRAL  -> İŞLEM YOK
#
# SADECE MEXC USDT FUTURES
#
# TELEGRAM:
# ❌ Sistem mesajı yok
# ❌ İzleme adayı yok
# ❌ Ters trend mesajı yok
# ❌ Tarama tamamlandı yok
# ✅ Sadece güçlü LONG / SHORT
# ============================================================


BASE = "https://contract.mexc.com"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

STATE_FILE = "signal_history.json"


# ============================================================
# AYARLAR
# ============================================================

MAX_WORKERS = 16

LONG_MIN_SCORE = 85
SHORT_MIN_SCORE = 82

SIGNAL_COOLDOWN = 6 * 60 * 60


# ------------------------------------------------------------
# LONG FİLTRELERİ
# ------------------------------------------------------------

MAX_24H_LONG = 12.0
MAX_1H_LONG = 5.0
MAX_15M_LONG = 3.5

MIN_LONG_VOLUME = 1.25

LONG_RSI15_MIN = 45
LONG_RSI15_MAX = 72

LONG_RSI1H_MIN = 45
LONG_RSI1H_MAX = 72


# ------------------------------------------------------------
# SHORT FİLTRELERİ
# ------------------------------------------------------------

# Çoktan çökmüş coinleri SHORT yapma
MAX_24H_SHORT_DROP = -12.0
MAX_1H_SHORT_DROP = -5.0
MAX_15M_SHORT_DROP = -3.5

MIN_SHORT_VOLUME = 1.20

SHORT_RSI15_MIN = 28
SHORT_RSI15_MAX = 60

SHORT_RSI1H_MIN = 28
SHORT_RSI1H_MAX = 60


# ------------------------------------------------------------
# LİKİDİTE
# ------------------------------------------------------------

MIN_24H_VOLUME = 100000


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

def get_json(url, params=None, timeout=12):

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

        print(
            "Telegram hata:",
            r.text[:300]
        )

    except Exception as e:

        print(
            "Telegram bağlantı hatası:",
            e
        )

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

        print(
            "State kayıt hatası:",
            e
        )


# ============================================================
# FUTURES KONTRATLARI
# ============================================================

def get_contracts():

    data = get_json(
        f"{BASE}/api/v1/contract/detail"
    )

    if not data:
        return []

    rows = data.get(
        "data",
        []
    )

    result = []

    for x in rows:

        try:

            symbol = str(
                x.get(
                    "symbol",
                    ""
                )
            ).upper()

            quote = str(
                x.get(
                    "quoteCoin",
                    ""
                )
            ).upper()

            settle = str(
                x.get(
                    "settleCoin",
                    ""
                )
            ).upper()

            state = x.get(
                "state",
                0
            )

            # SADECE USDT FUTURES
            if quote != "USDT":
                continue

            if settle != "USDT":
                continue

            if not symbol.endswith("_USDT"):
                continue

            if state not in [
                0,
                1,
                None
            ]:
                continue

            result.append(
                symbol
            )

        except Exception:
            continue

    return result


# ============================================================
# TICKER
# ============================================================

def get_ticker(symbol):

    data = get_json(
        f"{BASE}/api/v1/contract/ticker",
        {
            "symbol": symbol
        }
    )

    if not data:
        return None

    d = data.get(
        "data"
    )

    if not isinstance(
        d,
        dict
    ):
        return None

    try:

        price = float(
            d.get(
                "lastPrice",
                0
            )
        )

        change = float(
            d.get(
                "riseRate",
                0
            )
        )

        volume = float(
            d.get(
                "volume24",
                0
            )
        )

        if price <= 0:
            return None

        if abs(change) < 1:
            change *= 100

        return {
            "price": price,
            "change24": change,
            "volume24": volume
        }

    except Exception:
        return None


# ============================================================
# KLINE
# ============================================================

def get_klines(
    symbol,
    interval,
    limit=100
):

    data = get_json(
        f"{BASE}/api/v1/contract/kline/{symbol}",
        {
            "interval": interval
        }
    )

    if not data:
        return []

    d = data.get(
        "data"
    )

    if not isinstance(
        d,
        dict
    ):
        return []

    try:

        times = d.get(
            "time",
            []
        )

        opens = d.get(
            "open",
            []
        )

        highs = d.get(
            "high",
            []
        )

        lows = d.get(
            "low",
            []
        )

        closes = d.get(
            "close",
            []
        )

        volumes = d.get(
            "vol",
            []
        )

        n = min(
            len(times),
            len(opens),
            len(highs),
            len(lows),
            len(closes),
            len(volumes)
        )

        rows = []

        for i in range(
            max(
                0,
                n - limit
            ),
            n
        ):

            rows.append({
                "time": float(
                    times[i]
                ),
                "open": float(
                    opens[i]
                ),
                "high": float(
                    highs[i]
                ),
                "low": float(
                    lows[i]
                ),
                "close": float(
                    closes[i]
                ),
                "volume": float(
                    volumes[i]
                )
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

    for i in range(
        1,
        len(values)
    ):

        diff = (
            values[i]
            -
            values[i - 1]
        )

        if diff > 0:

            gains.append(
                diff
            )

            losses.append(
                0
            )

        else:

            gains.append(
                0
            )

            losses.append(
                abs(diff)
            )

    avg_gain = (
        sum(
            gains[:period]
        )
        /
        period
    )

    avg_loss = (
        sum(
            losses[:period]
        )
        /
        period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            (
                avg_gain
                *
                (period - 1)
            )
            +
            gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                *
                (period - 1)
            )
            +
            losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = (
        avg_gain
        /
        avg_loss
    )

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# EMA
# ============================================================

def ema(
    values,
    period
):

    if len(values) < period:
        return None

    multiplier = (
        2
        /
        (period + 1)
    )

    result = (
        sum(
            values[:period]
        )
        /
        period
    )

    for price in values[period:]:

        result = (
            (
                price
                -
                result
            )
            *
            multiplier
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
            abs(
                high - prev
            ),
            abs(
                low - prev
            )
        )

        trs.append(
            tr
        )

    if len(trs) < period:
        return None

    return (
        sum(
            trs[-period:]
        )
        /
        period
    )


# ============================================================
# CHANGE
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

    new = klines[
        -1
    ]["close"]

    if old <= 0:
        return 0

    return (
        (
            new - old
        )
        /
        old
    ) * 100


# ============================================================
# HACİM
# ============================================================

def volume_ratio(
    klines
):

    if len(klines) < 25:
        return 0

    current = klines[
        -1
    ]["volume"]

    previous = [
        x["volume"]
        for x in klines[
            -21:-1
        ]
    ]

    if not previous:
        return 0

    avg = (
        sum(previous)
        /
        len(previous)
    )

    if avg <= 0:
        return 0

    return (
        current
        /
        avg
    )


# ============================================================
# HIGHER LOW
# ============================================================

def higher_low(
    klines
):

    if len(klines) < 15:
        return False

    lows = [
        x["low"]
        for x in klines[
            -12:
        ]
    ]

    recent = min(
        lows[-5:]
    )

    previous = min(
        lows[:7]
    )

    return (
        recent
        >
        previous
    )


# ============================================================
# LOWER HIGH
# ============================================================

def lower_high(
    klines
):

    if len(klines) < 15:
        return False

    highs = [
        x["high"]
        for x in klines[
            -12:
        ]
    ]

    recent = max(
        highs[-5:]
    )

    previous = max(
        highs[:7]
    )

    return (
        recent
        <
        previous
    )


# ============================================================
# DİRENÇ
# ============================================================

def resistance_level(
    klines
):

    if len(klines) < 25:
        return None

    highs = [
        x["high"]
        for x in klines[
            -21:-1
        ]
    ]

    if not highs:
        return None

    return max(
        highs
    )


# ============================================================
# DESTEK
# ============================================================

def support_level(
    klines
):

    if len(klines) < 25:
        return None

    lows = [
        x["low"]
        for x in klines[
            -21:-1
        ]
    ]

    if not lows:
        return None

    return min(
        lows
    )


# ============================================================
# LONG BREAKOUT
# ============================================================

def long_breakout(
    klines
):

    resistance = (
        resistance_level(
            klines
        )
    )

    if resistance is None:
        return False, None

    close = klines[
        -1
    ]["close"]

    broken = (
        close
        >
        resistance * 1.001
    )

    return (
        broken,
        resistance
    )


# ============================================================
# SHORT DİRENÇ REDDİ
# ============================================================

def resistance_rejection(
    klines
):

    if len(klines) < 25:
        return False, None

    resistance = (
        resistance_level(
            klines
        )
    )

    if resistance is None:
        return False, None

    last = klines[-1]

    # Dirence temas etmiş
    touched = (
        last["high"]
        >=
        resistance * 0.997
    )

    # Fiyat direncin altında kapanmış
    rejected = (
        last["close"]
        <
        resistance * 0.998
    )

    # Üst fitil
    candle_range = (
        last["high"]
        -
        last["low"]
    )

    if candle_range <= 0:
        return False, resistance

    upper_wick = (
        last["high"]
        -
        max(
            last["open"],
            last["close"]
        )
    )

    wick_ratio = (
        upper_wick
        /
        candle_range
    )

    strong_rejection = (
        wick_ratio >= 0.30
    )

    return (
        touched
        and rejected
        and strong_rejection,
        resistance
    )


# ============================================================
# SHORT BREAKDOWN
# ============================================================

def short_breakdown(
    klines
):

    support = (
        support_level(
            klines
        )
    )

    if support is None:
        return False, None

    close = klines[
        -1
    ]["close"]

    broken = (
        close
        <
        support * 0.999
    )

    return (
        broken,
        support
    )


# ============================================================
# SIKIŞMA
# ============================================================

def compression(
    klines
):

    if len(klines) < 25:
        return False

    ranges = []

    for x in klines[
        -20:
    ]:

        if x["close"] <= 0:
            continue

        ranges.append(
            (
                (
                    x["high"]
                    -
                    x["low"]
                )
                /
                x["close"]
            )
            * 100
        )

    if len(ranges) < 10:
        return False

    avg = (
        sum(ranges)
        /
        len(ranges)
    )

    recent = (
        sum(
            ranges[-5:]
        )
        /
        5
    )

    return (
        recent
        <
        avg * 0.80
    )


# ============================================================
# BTC YÖN ANALİZİ
# ============================================================

def analyze_btc():

    print(
        "🌐 BTC yönü analiz ediliyor..."
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
        80
    )

    if (
        len(k15) < 40
        or len(k1h) < 40
        or len(k4h) < 30
    ):

        print(
            "⚪ BTC verisi yetersiz."
        )

        return "NEUTRAL", {}

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

    rsi15 = calculate_rsi(
        c15
    )

    rsi1h = calculate_rsi(
        c1h
    )

    rsi4h = calculate_rsi(
        c4h
    )

    ema20_1h = ema(
        c1h,
        20
    )

    ema50_1h = ema(
        c1h,
        50
    )

    ema20_4h = ema(
        c4h,
        20
    )

    ema50_4h = ema(
        c4h,
        50
    )

    price = c1h[-1]

    bullish = 0
    bearish = 0

    # --------------------------------------------------------
    # 15M
    # --------------------------------------------------------

    if change15 > 0:
        bullish += 1
    else:
        bearish += 1

    # --------------------------------------------------------
    # 1H
    # --------------------------------------------------------

    if change1h > 0:
        bullish += 1
    else:
        bearish += 1

    # --------------------------------------------------------
    # 4H
    # --------------------------------------------------------

    if change4h > 0:
        bullish += 2
    else:
        bearish += 2

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if rsi15 >= 50:
        bullish += 1
    else:
        bearish += 1

    if rsi1h >= 50:
        bullish += 1
    else:
        bearish += 1

    if rsi4h >= 50:
        bullish += 2
    else:
        bearish += 2

    # --------------------------------------------------------
    # EMA 1H
    # --------------------------------------------------------

    if (
        ema20_1h
        and ema50_1h
    ):

        if (
            price > ema20_1h
            and
            ema20_1h > ema50_1h
        ):
            bullish += 2

        elif (
            price < ema20_1h
            and
            ema20_1h < ema50_1h
        ):
            bearish += 2

    # --------------------------------------------------------
    # EMA 4H
    # --------------------------------------------------------

    if (
        ema20_4h
        and ema50_4h
    ):

        if (
            price > ema20_4h
            and
            ema20_4h > ema50_4h
        ):
            bullish += 3

        elif (
            price < ema20_4h
            and
            ema20_4h < ema50_4h
        ):
            bearish += 3

    # --------------------------------------------------------
    # BTC YÖNÜ
    # --------------------------------------------------------

    if (
        bullish >= 6
        and
        bullish > bearish
    ):

        direction = "BULLISH"

    elif (
        bearish >= 6
        and
        bearish > bullish
    ):

        direction = "BEARISH"

    else:

        direction = "NEUTRAL"

    print()
    print(
        "=============================="
    )

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

    print(
        "=============================="
    )

    return direction, {
        "change15": change15,
        "change1h": change1h,
        "change4h": change4h,
        "rsi15": rsi15,
        "rsi1h": rsi1h,
        "rsi4h": rsi4h,
        "bullish_score": bullish,
        "bearish_score": bearish
    }


# ============================================================
# LONG ANALİZİ
# ============================================================

def analyze_long(
    symbol,
    ticker,
    k15,
    k1h,
    k4h
):

    price = ticker["price"]

    change24 = ticker["change24"]

    volume24 = ticker["volume24"]

    # --------------------------------------------------------
    # PUMP SONRASI ENGELLE
    # --------------------------------------------------------

    if change24 > MAX_24H_LONG:
        return None

    change15 = percent_change(
        k15,
        1
    )

    change1h = percent_change(
        k1h,
        1
    )

    if change1h > MAX_1H_LONG:
        return None

    if change15 > MAX_15M_LONG:
        return None

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

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
        or
        rsi1h is None
        or
        rsi4h is None
    ):
        return None

    if not (
        LONG_RSI15_MIN
        <= rsi15
        <= LONG_RSI15_MAX
    ):
        return None

    if not (
        LONG_RSI1H_MIN
        <= rsi1h
        <= LONG_RSI1H_MAX
    ):
        return None

    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    vr = volume_ratio(
        k15
    )

    if vr < MIN_LONG_VOLUME:
        return None

    # --------------------------------------------------------
    # YAPILAR
    # --------------------------------------------------------

    hl15 = higher_low(
        k15
    )

    hl1h = higher_low(
        k1h
    )

    is_breakout, resistance = (
        long_breakout(
            k15
        )
    )

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

    trend1h = (
        ema20_1h
        and
        ema50_1h
        and
        price > ema20_1h
        and
        ema20_1h > ema50_1h
    )

    trend4h = (
        ema20_4h
        and
        price > ema20_4h
    )

    squeeze = compression(
        k15
    )

    # --------------------------------------------------------
    # SKOR
    # --------------------------------------------------------

    score = 0
    reasons = []

    if change15 > 0:
        score += 10
        reasons.append(
            "15M MOMENTUM"
        )

    if trend1h:
        score += 15
        reasons.append(
            "1H BULL TREND"
        )

    if trend4h:
        score += 10
        reasons.append(
            "4H TREND"
        )

    if hl15:
        score += 12
        reasons.append(
            "HIGHER LOW"
        )

    if hl1h:
        score += 10
        reasons.append(
            "1H HIGHER LOW"
        )

    if vr >= 1.25:
        score += 15
        reasons.append(
            "HACİM"
        )

    if vr >= 1.70:
        score += 5

    if is_breakout:
        score += 18
        reasons.append(
            "DİRENÇ KIRILIMI"
        )

    if squeeze:
        score += 8
        reasons.append(
            "SIKIŞMA"
        )

    if (
        52 <= rsi15 <= 68
        and
        50 <= rsi1h <= 68
    ):

        score += 7

        reasons.append(
            "RSI TEYİDİ"
        )

    if (
        0 < change15 <= 2.5
    ):

        score += 5

    score = min(
        score,
        100
    )

    if score < LONG_MIN_SCORE:
        return None

    structure_count = sum([
        hl15,
        hl1h,
        trend1h,
        is_breakout
    ])

    if structure_count < 2:
        return None

    # --------------------------------------------------------
    # ATR
    # --------------------------------------------------------

    atr = calculate_atr(
        k15
    )

    if not atr or atr <= 0:
        return None

    stop = (
        price
        -
        atr * 1.35
    )

    risk = (
        price
        -
        stop
    )

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

    # --------------------------------------------------------
    # SİNYAL TİPİ
    # --------------------------------------------------------

    if is_breakout:

        signal_type = (
            "🔥 DİRENÇ KIRILIMI"
        )

    elif hl15 and hl1h:

        signal_type = (
            "🚀 PUMP ÖNCESİ GÜÇLENME"
        )

    else:

        signal_type = (
            "⚡ ERKEN LONG"
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
        "higher_low": hl15,
        "higher_low_1h": hl1h,
        "breakout": is_breakout,
        "squeeze": squeeze,
        "signal_type": signal_type,
        "reasons": reasons
    }


# ============================================================
# SHORT ANALİZİ
# ============================================================

def analyze_short(
    symbol,
    ticker,
    k15,
    k1h,
    k4h
):

    price = ticker["price"]

    change24 = ticker["change24"]

    # --------------------------------------------------------
    # ZATEN ÇÖKMÜŞ COİNİ SHORTLAMA
    # --------------------------------------------------------

    if change24 < MAX_24H_SHORT_DROP:
        return None

    change15 = percent_change(
        k15,
        1
    )

    change1h = percent_change(
        k1h,
        1
    )

    if change1h < MAX_1H_SHORT_DROP:
        return None

    if change15 < MAX_15M_SHORT_DROP:
        return None

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

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
        or
        rsi1h is None
        or
        rsi4h is None
    ):
        return None

    if not (
        SHORT_RSI15_MIN
        <= rsi15
        <= SHORT_RSI15_MAX
    ):
        return None

    if not (
        SHORT_RSI1H_MIN
        <= rsi1h
        <= SHORT_RSI1H_MAX
    ):
        return None

    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    vr = volume_ratio(
        k15
    )

    if vr < MIN_SHORT_VOLUME:
        return None

    # --------------------------------------------------------
    # YAPILAR
    # --------------------------------------------------------

    lh15 = lower_high(
        k15
    )

    lh1h = lower_high(
        k1h
    )

    rejection, resistance = (
        resistance_rejection(
            k15
        )
    )

    breakdown, support = (
        short_breakdown(
            k15
        )
    )

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

    trend1h = (
        ema20_1h
        and
        ema50_1h
        and
        price < ema20_1h
        and
        ema20_1h < ema50_1h
    )

    trend4h = (
        ema20_4h
        and
        ema50_4h
        and
        price < ema20_4h
        and
        ema20_4h < ema50_4h
    )

    squeeze = compression(
        k15
    )

    # --------------------------------------------------------
    # SKOR
    # --------------------------------------------------------

    score = 0
    reasons = []

    # Negatif 15M momentum
    if change15 < 0:
        score += 10
        reasons.append(
            "15M DÜŞÜŞ MOMENTUMU"
        )

    # 1H bearish trend
    if trend1h:
        score += 15
        reasons.append(
            "1H BEAR TREND"
        )

    # 4H bearish trend
    if trend4h:
        score += 10
        reasons.append(
            "4H BEAR TREND"
        )

    # Lower High
    if lh15:
        score += 12
        reasons.append(
            "LOWER HIGH"
        )

    if lh1h:
        score += 10
        reasons.append(
            "1H LOWER HIGH"
        )

    # Hacim
    if vr >= 1.20:
        score += 15
        reasons.append(
            "HACİM"
        )

    if vr >= 1.70:
        score += 5

    # Direnç reddi
    if rejection:
        score += 18
        reasons.append(
            "DİRENÇ REDDİ"
        )

    # Destek kırılımı
    if breakdown:
        score += 18
        reasons.append(
            "DESTEK KIRILIMI"
        )

    # Sıkışma
    if squeeze:
        score += 8
        reasons.append(
            "SIKIŞMA"
        )

    # RSI
    if (
        35 <= rsi15 <= 55
        and
        35 <= rsi1h <= 55
    ):

        score += 7

        reasons.append(
            "RSI SHORT TEYİDİ"
        )

    # Hafif düşüş
    if (
        -2.5 <= change15 < 0
    ):

        score += 5

    score = min(
        score,
        100
    )

    if score < SHORT_MIN_SCORE:
        return None

    structure_count = sum([
        lh15,
        lh1h,
        trend1h,
        trend4h,
        rejection,
        breakdown
    ])

    if structure_count < 2:
        return None

    # --------------------------------------------------------
    # ATR
    # --------------------------------------------------------

    atr = calculate_atr(
        k15
    )

    if not atr or atr <= 0:
        return None

    # SHORT STOP YUKARIDA
    stop = (
        price
        +
        atr * 1.35
    )

    risk = (
        stop
        -
        price
    )

    if risk <= 0:
        return None

    # SHORT TP AŞAĞIDA
    tp1 = price - (
        risk * 1.0
    )

    tp2 = price - (
        risk * 1.8
    )

    tp3 = price - (
        risk * 2.6
    )

    # --------------------------------------------------------
    # SİNYAL TİPİ
    # --------------------------------------------------------

    if breakdown:

        signal_type = (
            "🔻 DESTEK KIRILIMI"
        )

    elif rejection:

        signal_type = (
            "🔴 DİRENÇ REDDİ"
        )

    elif lh15 and lh1h:

        signal_type = (
            "📉 DÜŞÜŞ ÖNCESİ ZAYIFLAMA"
        )

    else:

        signal_type = (
            "⚡ ERKEN SHORT"
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
        "lower_high": lh15,
        "lower_high_1h": lh1h,
        "rejection": rejection,
        "breakdown": breakdown,
        "squeeze": squeeze,
        "signal_type": signal_type,
        "reasons": reasons
    }


# ============================================================
# COIN ANALİZİ
# ============================================================

def analyze_symbol(
    symbol,
    btc_direction
):

    ticker = get_ticker(
        symbol
    )

    if not ticker:
        return None

    if ticker[
        "volume24"
    ] < MIN_24H_VOLUME:

        return None

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
        or
        len(k1h) < 40
        or
        len(k4h) < 30
    ):

        return None

    # ========================================================
    # BTC BULLISH = SADECE LONG
    # ========================================================

    if btc_direction == "BULLISH":

        return analyze_long(
            symbol,
            ticker,
            k15,
            k1h,
            k4h
        )

    # ========================================================
    # BTC BEARISH = SADECE SHORT
    # ========================================================

    if btc_direction == "BEARISH":

        return analyze_short(
            symbol,
            ticker,
            k15,
            k1h,
            k4h
        )

    # ========================================================
    # BTC NEUTRAL = İŞLEM YOK
    # ========================================================

    return None


# ============================================================
# FİYAT FORMAT
# ============================================================

def format_price(
    price
):

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
# TELEGRAM MESAJI
# ============================================================

def build_message(
    x,
    btc_direction,
    btc_data
):

    if x["direction"] == "LONG":

        title = (
            "🟢 <b>LONG SİNYALİ</b>"
        )

        direction_icon = "🟢"

        structure = (
            f'📈 Higher Low: '
            f'{"✅" if x["higher_low"] else "❌"}\n'
            f'📈 1H Higher Low: '
            f'{"✅" if x["higher_low_1h"] else "❌"}\n'
            f'🔥 Hacim teyidi: '
            f'{"✅" if x["volume_ratio"] >= 1.25 else "❌"}\n'
            f'💥 Direnç kırılımı: '
            f'{"✅" if x["breakout"] else "❌"}'
        )

    else:

        title = (
            "🔴 <b>SHORT SİNYALİ</b>"
        )

        direction_icon = "🔴"

        structure = (
            f'📉 Lower High: '
            f'{"✅" if x["lower_high"] else "❌"}\n'
            f'📉 1H Lower High: '
            f'{"✅" if x["lower_high_1h"] else "❌"}\n'
            f'🔥 Hacim teyidi: '
            f'{"✅" if x["volume_ratio"] >= 1.20 else "❌"}\n'
            f'🔻 Direnç reddi: '
            f'{"✅" if x["rejection"] else "❌"}\n'
            f'💥 Destek kırılımı: '
            f'{"✅" if x["breakdown"] else "❌"}'
        )

    return f"""
{title}

💎 <b>{x["symbol"]}</b>
⭐ <b>Skor: {x["score"]}/100</b>

{direction_icon} <b>{x["signal_type"]}</b>

🌐 BTC Yönü:
<b>{btc_direction}</b>

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

📊 24H: {x["change24"]:+.2f}%
⚡ 1H: {x["change1h"]:+.2f}%
🔥 15M: {x["change15"]:+.2f}%

💥 Hacim:
<b>{x["volume_ratio"]:.2f}x</b>

📈 RSI 15M:
{x["rsi15"]:.1f}

📈 RSI 1H:
{x["rsi1h"]:.1f}

📊 RSI 4H:
{x["rsi4h"]:.1f}

{structure}

🌐 BTC:
15M {btc_data["change15"]:+.2f}%
1H {btc_data["change1h"]:+.2f}%
4H {btc_data["change4h"]:+.2f}%

💎 <b>MEXC USDT FUTURES</b>

⚠️ <i>BTC yönü + coin teknik yapısı birlikte teyit edilmiştir.</i>
"""


# ============================================================
# COOLDOWN
# ============================================================

def can_send(
    symbol,
    direction,
    state
):

    now = time.time()

    key = (
        f"{symbol}_{direction}"
    )

    old = state.get(
        key
    )

    if old is None:
        return True

    try:

        last_time = float(
            old
        )

        return (
            now - last_time
            >= SIGNAL_COOLDOWN
        )

    except Exception:

        return True


# ============================================================
# ANA RADAR
# ============================================================

def main():

    print()
    print(
        "🚀 MEXC PUMP RADAR 11.0"
    )

    print(
        "🌐 BTC YÖN FİLTRESİ AKTİF"
    )

    print(
        "🟢 BTC BULLISH = SADECE LONG"
    )

    print(
        "🔴 BTC BEARISH = SADECE SHORT"
    )

    print(
        "⚪ BTC NEUTRAL = İŞLEM YOK"
    )

    print()

    # --------------------------------------------------------
    # BTC
    # --------------------------------------------------------

    btc_direction, btc_data = (
        analyze_btc()
    )

    # BTC nötrse hiç coin tarama
    if btc_direction == "NEUTRAL":

        print(
            "⚪ BTC NEUTRAL."
        )

        print(
            "🚫 İşlem gönderilmeyecek."
        )

        return

    # --------------------------------------------------------
    # FUTURES
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # STATE
    # --------------------------------------------------------

    state = load_state()

    candidates = []

    # --------------------------------------------------------
    # TARAMA
    # --------------------------------------------------------

    total = len(
        symbols
    )

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

                result = (
                    future.result()
                )

                if result:

                    candidates.append(
                        result
                    )

                    print(
                        f"🔥 "
                        f"{result['direction']} "
                        f"{symbol} "
                        f"SKOR={result['score']}"
                    )

            except Exception as e:

                print(
                    f"Hata "
                    f"{symbol}: {e}"
                )

            if (
                completed % 25 == 0
                or
                completed == total
            ):

                print(
                    f"İlerleme: "
                    f"{completed}/{total}"
                )

    # --------------------------------------------------------
    # SKOR
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x:
        x["score"],
        reverse=True
    )

    print()

    print(
        f"🎯 Güçlü sinyal: "
        f"{len(candidates)}"
    )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

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
                f"{symbol} "
                f"{direction}"
            )

            continue

        message = build_message(
            candidate,
            btc_direction,
            btc_data
        )

        ok = telegram_send(
            message
        )

        if ok:

            sent += 1

            key = (
                f"{symbol}_{direction}"
            )

            state[
                key
            ] = time.time()

            save_state(
                state
            )

            print(
                f"✅ GÖNDERİLDİ: "
                f"{direction} "
                f"{symbol} "
                f"{candidate['score']}"
            )

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
