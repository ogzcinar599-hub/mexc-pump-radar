import os
import time
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PUMP RADAR 9.1
#
# BTC YÖN FİLTRELİ LONG / SHORT
#
# 🟢 BTC BULLISH  -> LONG
# 🔴 BTC BEARISH  -> SHORT
# ⚪ BTC NEUTRAL  -> İŞLEM YOK
#
# SADECE MEXC USDT FUTURES
# ============================================================


BASE = "https://contract.mexc.com"

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)

STATE_FILE = "signal_history.json"


# ============================================================
# AYARLAR
# ============================================================

MAX_WORKERS = 12

MIN_SCORE = 85

SIGNAL_COOLDOWN = 6 * 60 * 60

MIN_24H_VOLUME = 100000

# LONG aşırı pump filtresi
MAX_LONG_24H = 12.0
MAX_LONG_1H = 5.0
MAX_LONG_15M = 3.5

# SHORT aşırı dump filtresi
MAX_SHORT_24H = 12.0
MAX_SHORT_1H = 5.0
MAX_SHORT_15M = 3.5

# Hacim
MIN_VOLUME_RATIO = 1.25

# RSI
LONG_MIN_RSI_15 = 42
LONG_MIN_RSI_1H = 42

LONG_MAX_RSI_15 = 72
LONG_MAX_RSI_1H = 72

SHORT_MIN_RSI_15 = 28
SHORT_MIN_RSI_1H = 30

SHORT_MAX_RSI_15 = 65
SHORT_MAX_RSI_1H = 65

# BTC
BTC_SYMBOL = "BTC_USDT"

BTC_MIN_15M = 0.20
BTC_MIN_1H = 0.40

# BTC yön kararlılığı
BTC_BULL_THRESHOLD = 6
BTC_BEAR_THRESHOLD = 6


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

def get_json(
    url,
    params=None,
    timeout=15
):

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

    if (
        not TELEGRAM_TOKEN
        or not TELEGRAM_CHAT_ID
    ):

        print(
            "⚠️ Telegram bilgileri yok."
        )

        return False

    url = (
        "https://api.telegram.org/bot"
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

        if not os.path.exists(
            STATE_FILE
        ):
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
# MEXC FUTURES
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

            if quote != "USDT":
                continue

            if settle != "USDT":
                continue

            if not symbol.endswith(
                "_USDT"
            ):
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
        params={
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

        vols = d.get(
            "vol",
            []
        )

        n = min(
            len(times),
            len(opens),
            len(highs),
            len(lows),
            len(closes),
            len(vols)
        )

        rows = []

        start = max(
            0,
            n - limit
        )

        for i in range(
            start,
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
                    vols[i]
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

    return (
        100
        -
        (
            100
            /
            (1 + rs)
        )
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
        prev = klines[
            i - 1
        ]["close"]

        tr = max(
            high - low,
            abs(high - prev),
            abs(low - prev)
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
# PERCENT CHANGE
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
# VOLUME RATIO
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
        for x in klines[-21:-1]
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
        for x in klines[-12:]
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
        for x in klines[-12:]
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
# RESISTANCE
# ============================================================

def resistance_level(
    klines
):

    if len(klines) < 25:
        return None

    highs = [
        x["high"]
        for x in klines[-21:-1]
    ]

    return max(
        highs
    )


# ============================================================
# SUPPORT
# ============================================================

def support_level(
    klines
):

    if len(klines) < 25:
        return None

    lows = [
        x["low"]
        for x in klines[-21:-1]
    ]

    return min(
        lows
    )


# ============================================================
# LONG BREAKOUT
# ============================================================

def long_breakout(
    klines
):

    resistance = resistance_level(
        klines
    )

    if resistance is None:
        return False, None

    close = klines[
        -1
    ]["close"]

    return (
        close
        >
        resistance * 1.0015,
        resistance
    )


# ============================================================
# SHORT BREAKDOWN
# ============================================================

def short_breakdown(
    klines
):

    support = support_level(
        klines
    )

    if support is None:
        return False, None

    close = klines[
        -1
    ]["close"]

    return (
        close
        <
        support * 0.9985,
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

    for x in klines[-20:]:

        close = x["close"]

        if close <= 0:
            continue

        ranges.append(
            (
                (
                    x["high"]
                    -
                    x["low"]
                )
                /
                close
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
        sum(ranges[-5:])
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

    k15 = get_klines(
        BTC_SYMBOL,
        "Min15",
        100
    )

    k1h = get_klines(
        BTC_SYMBOL,
        "Min60",
        100
    )

    k4h = get_klines(
        BTC_SYMBOL,
        "Hour4",
        80
    )

    if (
        len(k15) < 50
        or
        len(k1h) < 50
        or
        len(k4h) < 30
    ):

        return {
            "direction": "NEUTRAL",
            "bull_score": 0,
            "bear_score": 0,
            "change15": 0,
            "change1h": 0,
            "change4h": 0,
            "rsi15": 50,
            "rsi1h": 50,
            "rsi4h": 50
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

    price = c15[-1]

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

    ema20_15 = ema(
        c15,
        20
    )

    ema50_15 = ema(
        c15,
        50
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

    bull = 0
    bear = 0

    # ========================================================
    # BTC 15M
    # ========================================================

    if change15 >= BTC_MIN_15M:
        bull += 1

    elif change15 <= -BTC_MIN_15M:
        bear += 1

    if (
        ema20_15
        and ema50_15
    ):

        if (
            price > ema20_15
            and
            ema20_15 > ema50_15
        ):

            bull += 1

        elif (
            price < ema20_15
            and
            ema20_15 < ema50_15
        ):

            bear += 1

    # ========================================================
    # BTC 1H
    # ========================================================

    if change1h >= BTC_MIN_1H:
        bull += 2

    elif change1h <= -BTC_MIN_1H:
        bear += 2

    if (
        ema20_1h
        and ema50_1h
    ):

        if (
            price > ema20_1h
            and
            ema20_1h > ema50_1h
        ):

            bull += 2

        elif (
            price < ema20_1h
            and
            ema20_1h < ema50_1h
        ):

            bear += 2

    # ========================================================
    # BTC 4H
    # ========================================================

    if ema20_4h:

        if price > ema20_4h:
            bull += 2

        elif price < ema20_4h:
            bear += 2

    # 4H momentum
    if change4h > 0.30:
        bull += 2

    elif change4h < -0.30:
        bear += 2

    # ========================================================
    # RSI
    # ========================================================

    if rsi15 is not None:

        if rsi15 >= 52:
            bull += 1

        elif rsi15 <= 48:
            bear += 1

    if rsi1h is not None:

        if rsi1h >= 52:
            bull += 1

        elif rsi1h <= 48:
            bear += 1

    if rsi4h is not None:

        if rsi4h >= 52:
            bull += 1

        elif rsi4h <= 48:
            bear += 1

    # ========================================================
    # BTC YÖNÜ
    # ========================================================

    if (
        bear >= BTC_BEAR_THRESHOLD
        and
        bear > bull
    ):

        direction = "BEARISH"

    elif (
        bull >= BTC_BULL_THRESHOLD
        and
        bull > bear
    ):

        direction = "BULLISH"

    else:

        direction = "NEUTRAL"

    return {
        "direction": direction,
        "bull_score": bull,
        "bear_score": bear,
        "change15": change15,
        "change1h": change1h,
        "change4h": change4h,
        "rsi15": rsi15 or 50,
        "rsi1h": rsi1h or 50,
        "rsi4h": rsi4h or 50
    }


# ============================================================
# LONG ANALİZ
# ============================================================

def analyze_long(
    symbol,
    ticker,
    k15,
    k1h,
    k4h,
    btc
):

    if btc["direction"] != "BULLISH":
        return None

    price = ticker["price"]
    change24 = ticker["change24"]

    change15 = percent_change(
        k15,
        1
    )

    change1h = percent_change(
        k1h,
        1
    )

    # --------------------------------------------------------
    # PUMP SONRASI ELEME
    # --------------------------------------------------------

    if change24 > MAX_LONG_24H:
        return None

    if change1h > MAX_LONG_1H:
        return None

    if change15 > MAX_LONG_15M:
        return None

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

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

    rsi15 = calculate_rsi(
        c15
    )

    rsi1h = calculate_rsi(
        c1h
    )

    rsi4h = calculate_rsi(
        c4h
    )

    if (
        rsi15 is None
        or
        rsi1h is None
        or
        rsi4h is None
    ):
        return None

    if rsi15 < LONG_MIN_RSI_15:
        return None

    if rsi1h < LONG_MIN_RSI_1H:
        return None

    if rsi15 > LONG_MAX_RSI_15:
        return None

    if rsi1h > LONG_MAX_RSI_1H:
        return None

    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    vr = volume_ratio(
        k15
    )

    if vr < MIN_VOLUME_RATIO:
        return None

    # --------------------------------------------------------
    # STRUCTURE
    # --------------------------------------------------------

    hl15 = higher_low(
        k15
    )

    hl1h = higher_low(
        k1h
    )

    breakout, resistance = long_breakout(
        k15
    )

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    ema20_1h = ema(
        c1h,
        20
    )

    ema50_1h = ema(
        c1h,
        50
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

    ema20_4h = ema(
        c4h,
        20
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

    score = 15

    reasons = [
        "BTC LONG YÖNÜ"
    ]

    if change15 > 0:

        score += 8

        reasons.append(
            "15M MOMENTUM"
        )

    if trend1h:

        score += 15

        reasons.append(
            "1H TREND"
        )

    if trend4h:

        score += 8

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

        score += 10

        reasons.append(
            "HACİM"
        )

    if vr >= 1.70:

        score += 5

    if breakout:

        score += 15

        reasons.append(
            "DİRENÇ KIRILIMI"
        )

    if (
        52 <= rsi15 <= 68
        and
        52 <= rsi1h <= 68
    ):

        score += 7

        reasons.append(
            "RSI TEYİDİ"
        )

    if squeeze:

        score += 5

        reasons.append(
            "SIKIŞMA"
        )

    score = min(
        score,
        100
    )

    structure_count = sum([
        hl15,
        hl1h,
        trend1h,
        breakout
    ])

    if score < MIN_SCORE:
        return None

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

    tp1 = price + risk
    tp2 = price + risk * 1.8
    tp3 = price + risk * 2.6

    if breakout:

        signal_type = (
            "🔥 DİRENÇ KIRILIMI LONG"
        )

    elif hl15 and hl1h:

        signal_type = (
            "🚀 PUMP ÖNCESİ LONG"
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
        "support": None,
        "higher_low": hl15,
        "higher_low_1h": hl1h,
        "lower_high": False,
        "lower_high_1h": False,
        "breakout": breakout,
        "breakdown": False,
        "signal_type": signal_type,
        "btc_direction": btc["direction"]
    }


# ============================================================
# SHORT ANALİZ
# ============================================================

def analyze_short(
    symbol,
    ticker,
    k15,
    k1h,
    k4h,
    btc
):

    if btc["direction"] != "BEARISH":
        return None

    price = ticker["price"]
    change24 = ticker["change24"]

    change15 = percent_change(
        k15,
        1
    )

    change1h = percent_change(
        k1h,
        1
    )

    # --------------------------------------------------------
    # ÇOKTAN ÇÖKMÜŞ COINLERİ ELE
    # --------------------------------------------------------

    if change24 < -MAX_SHORT_24H:
        return None

    if change1h < -MAX_SHORT_1H:
        return None

    if change15 < -MAX_SHORT_15M:
        return None

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

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

    rsi15 = calculate_rsi(
        c15
    )

    rsi1h = calculate_rsi(
        c1h
    )

    rsi4h = calculate_rsi(
        c4h
    )

    if (
        rsi15 is None
        or
        rsi1h is None
        or
        rsi4h is None
    ):
        return None

    # Aşırı satılmış coinleri kovalamıyoruz
    if rsi15 < SHORT_MIN_RSI_15:
        return None

    if rsi1h < SHORT_MIN_RSI_1H:
        return None

    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    vr = volume_ratio(
        k15
    )

    if vr < MIN_VOLUME_RATIO:
        return None

    # --------------------------------------------------------
    # STRUCTURE
    # --------------------------------------------------------

    lh15 = lower_high(
        k15
    )

    lh1h = lower_high(
        k1h
    )

    breakdown, support = short_breakdown(
        k15
    )

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    ema20_1h = ema(
        c1h,
        20
    )

    ema50_1h = ema(
        c1h,
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

    ema20_4h = ema(
        c4h,
        20
    )

    trend4h = (
        ema20_4h
        and
        price < ema20_4h
    )

    squeeze = compression(
        k15
    )

    # --------------------------------------------------------
    # SATIŞ MOMENTUMU
    # --------------------------------------------------------

    negative_momentum = (
        change15 < 0
        or
        change1h < 0
    )

    # --------------------------------------------------------
    # RSI SHORT TEYİDİ
    # --------------------------------------------------------

    rsi_bearish = (
        rsi15 < 50
        and
        rsi1h < 50
    )

    # --------------------------------------------------------
    # SKOR
    # --------------------------------------------------------

    score = 15

    reasons = [
        "BTC SHORT YÖNÜ"
    ]

    if negative_momentum:

        score += 10

        reasons.append(
            "NEGATİF MOMENTUM"
        )

    if trend1h:

        score += 15

        reasons.append(
            "1H DÜŞÜŞ TRENDİ"
        )

    if trend4h:

        score += 8

        reasons.append(
            "4H DÜŞÜŞ TRENDİ"
        )

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

    if vr >= 1.25:

        score += 10

        reasons.append(
            "SATIŞ HACMİ"
        )

    if vr >= 1.70:

        score += 5

    if breakdown:

        score += 15

        reasons.append(
            "DESTEK KIRILIMI"
        )

    if rsi_bearish:

        score += 7

        reasons.append(
            "RSI SHORT TEYİDİ"
        )

    if squeeze:

        score += 5

        reasons.append(
            "SIKIŞMA"
        )

    score = min(
        score,
        100
    )

    # --------------------------------------------------------
    # STRUCTURE
    # --------------------------------------------------------

    structure_count = sum([
        lh15,
        lh1h,
        trend1h,
        breakdown
    ])

    if score < MIN_SCORE:
        return None

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

    tp1 = price - risk
    tp2 = price - risk * 1.8
    tp3 = price - risk * 2.6

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    if breakdown:

        signal_type = (
            "🔻 DESTEK KIRILIMI SHORT"
        )

    elif lh15 and lh1h:

        signal_type = (
            "📉 DÜŞÜŞ ÖNCESİ SHORT"
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
        "resistance": None,
        "support": support,
        "higher_low": False,
        "higher_low_1h": False,
        "lower_high": lh15,
        "lower_high_1h": lh1h,
        "breakout": False,
        "breakdown": breakdown,
        "signal_type": signal_type,
        "btc_direction": btc["direction"]
    }


# ============================================================
# COIN ANALİZ
# ============================================================

def analyze_symbol(
    symbol,
    btc
):

    if symbol == BTC_SYMBOL:
        return None

    ticker = get_ticker(
        symbol
    )

    if not ticker:
        return None

    if (
        ticker["volume24"]
        <
        MIN_24H_VOLUME
    ):
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

    if btc["direction"] == "BULLISH":

        return analyze_long(
            symbol,
            ticker,
            k15,
            k1h,
            k4h,
            btc
        )

    if btc["direction"] == "BEARISH":

        return analyze_short(
            symbol,
            ticker,
            k15,
            k1h,
            k4h,
            btc
        )

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
# TELEGRAM MESAJ
# ============================================================

def build_message(
    x,
    btc
):

    direction = x[
        "direction"
    ]

    if direction == "LONG":

        title = (
            "🟢 <b>LONG SİNYAL</b>"
        )

        s1 = (
            f'📈 Higher Low: '
            f'{"✅" if x["higher_low"] else "❌"}'
        )

        s2 = (
            f'📈 1H Higher Low: '
            f'{"✅" if x["higher_low_1h"] else "❌"}'
        )

        s3 = (
            f'💥 Direnç kırılımı: '
            f'{"✅" if x["breakout"] else "❌"}'
        )

        level_title = "🔑 Direnç:"

        level = x[
            "resistance"
        ]

    else:

        title = (
            "🔴 <b>SHORT SİNYAL</b>"
        )

        s1 = (
            f'📉 Lower High: '
            f'{"✅" if x["lower_high"] else "❌"}'
        )

        s2 = (
            f'📉 1H Lower High: '
            f'{"✅" if x["lower_high_1h"] else "❌"}'
        )

        s3 = (
            f'🔻 Destek kırılımı: '
            f'{"✅" if x["breakdown"] else "❌"}'
        )

        level_title = "🔑 Destek:"

        level = x[
            "support"
        ]

    return f"""
{title}

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

{level_title}
<b>{format_price(level) if level else "-"}</b>

{s1}

{s2}

🔥 Hacim teyidi:
{"✅" if x["volume_ratio"] >= MIN_VOLUME_RATIO else "❌"}

{s3}

━━━━━━━━━━━━━━

🌐 BTC 15M:
{btc["change15"]:+.2f}%

🌐 BTC 1H:
{btc["change1h"]:+.2f}%

🌐 BTC 4H:
{btc["change4h"]:+.2f}%

🌐 BTC RSI 15M:
{btc["rsi15"]:.1f}

🌐 BTC RSI 1H:
{btc["rsi1h"]:.1f}

🌐 BTC RSI 4H:
{btc["rsi4h"]:.1f}

💎 <b>MEXC USDT FUTURES</b>

⚠️ <i>BTC yönü + coin teknik yapısı birlikte değerlendirilmiştir.</i>
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

    old = state.get(
        key
    )

    if old is None:
        return True

    try:

        return (
            time.time()
            -
            float(old)
            >=
            SIGNAL_COOLDOWN
        )

    except Exception:

        return True


# ============================================================
# ANA
# ============================================================

def main():

    print()
    print(
        "🚀 MEXC PUMP RADAR 9.1"
    )

    print(
        "🌐 BTC YÖN FİLTRESİ AKTİF"
    )

    print(
        "🟢 BTC BULLISH = LONG"
    )

    print(
        "🔴 BTC BEARISH = SHORT"
    )

    print(
        "⚪ BTC NEUTRAL = İŞLEM YOK"
    )

    print()

    # ========================================================
    # BTC
    # ========================================================

    print(
        "🌐 BTC analiz ediliyor..."
    )

   
