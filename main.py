import os
import time
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PUMP RADAR 9.0
#
# BTC YÖN FİLTRELİ LONG / SHORT SİSTEMİ
#
# 🟢 BTC BULLISH  -> LONG
# 🔴 BTC BEARISH  -> SHORT
# ⚪ BTC NEUTRAL  -> SİNYAL YOK
#
# SADECE MEXC USDT FUTURES
# ============================================================


BASE = "https://contract.mexc.com"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

STATE_FILE = "signal_history.json"


# ============================================================
# AYARLAR
# ============================================================

MAX_WORKERS = 12

MIN_SCORE = 85

SIGNAL_COOLDOWN = 6 * 60 * 60

MIN_24H_VOLUME = 100000

# Aşırı pump / dump filtresi
MAX_24H_MOVE = 12.0

MAX_1H_MOVE = 5.0
MAX_15M_MOVE = 3.5

# Hacim
MIN_VOLUME_RATIO = 1.35

# RSI
MIN_RSI = 38
MAX_RSI = 72

# BTC
BTC_SYMBOL = "BTC_USDT"

BTC_MIN_15M_MOVE = 0.15
BTC_MIN_1H_MOVE = 0.25

# BTC yön teyidi için EMA
BTC_EMA_FAST = 20
BTC_EMA_SLOW = 50


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
# CONTRACTS
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

            if not symbol.endswith(
                "_USDT"
            ):
                continue

            # Aktif kontrat
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

        last = float(
            d.get(
                "lastPrice",
                0
            )
        )

        rise = float(
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

        if last <= 0:
            return None

        # MEXC bazen 0.05
        # bazen 5 şeklinde döndürebilir
        if abs(rise) < 1:
            rise *= 100

        return {
            "price": last,
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
        sum(gains[:period])
        /
        period
    )

    avg_loss = (
        sum(losses[:period])
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
        100
        /
        (1 + rs)
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
        sum(values[:period])
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
            abs(high - prev),
            abs(low - prev)
        )

        trs.append(
            tr
        )

    if len(trs) < period:
        return None

    return (
        sum(trs[-period:])
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

    recent_low = min(
        lows[-5:]
    )

    previous_low = min(
        lows[:7]
    )

    return (
        recent_low
        >
        previous_low
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

    recent_high = max(
        highs[-5:]
    )

    previous_high = max(
        highs[:7]
    )

    return (
        recent_high
        <
        previous_high
    )


# ============================================================
# 1H HIGHER LOW
# ============================================================

def one_hour_higher_low(
    klines
):

    return higher_low(
        klines
    )


# ============================================================
# 1H LOWER HIGH
# ============================================================

def one_hour_lower_high(
    klines
):

    return lower_high(
        klines
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
        for x in klines[-21:-1]
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
        for x in klines[-21:-1]
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

    resistance = resistance_level(
        klines
    )

    if resistance is None:
        return False, None

    close = klines[
        -1
    ]["close"]

    broken = (
        close
        >
        resistance * 1.0015
    )

    return (
        broken,
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

    broken = (
        close
        <
        support * 0.9985
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

    for x in klines[-20:]:

        if x["close"] <= 0:
            continue

        ranges.append(
            (
                x["high"]
                -
                x["low"]
            )
            /
            x["close"]
            *
            100
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
            "score": 0,
            "change15": 0,
            "change1h": 0,
            "change4h": 0,
            "rsi15": 50,
            "rsi1h": 50,
            "rsi4h": 50
        }

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

    price = closes15[-1]

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
        closes15
    )

    rsi1h = calculate_rsi(
        closes1h
    )

    rsi4h = calculate_rsi(
        closes4h
    )

    ema20_15 = ema(
        closes15,
        20
    )

    ema50_15 = ema(
        closes15,
        50
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

    bullish = 0
    bearish = 0

    # --------------------------------------------------------
    # 15M
    # --------------------------------------------------------

    if change15 > BTC_MIN_15M_MOVE:
        bullish += 1

    if change15 < -BTC_MIN_15M_MOVE:
        bearish += 1

    if (
        ema20_15
        and ema50_15
        and ema20_15 > ema50_15
        and price > ema20_15
    ):
        bullish += 1

    if (
        ema20_15
        and ema50_15
        and ema20_15 < ema50_15
        and price < ema20_15
    ):
        bearish += 1

    # --------------------------------------------------------
    # 1H
    # --------------------------------------------------------

    if change1h > BTC_MIN_1H_MOVE:
        bullish += 2

    if change1h < -BTC_MIN_1H_MOVE:
        bearish += 2

    if (
        ema20_1h
        and ema50_1h
        and ema20_1h > ema50_1h
        and price > ema20_1h
    ):
        bullish += 2

    if (
        ema20_1h
        and ema50_1h
        and ema20_1h < ema50_1h
        and price < ema20_1h
    ):
        bearish += 2

    # --------------------------------------------------------
    # 4H
    # --------------------------------------------------------

    if (
        ema20_4h
        and price > ema20_4h
    ):
        bullish += 2

    if (
        ema20_4h
        and price < ema20_4h
    ):
        bearish += 2

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if rsi15 is not None:

        if rsi15 > 52:
            bullish += 1

        if rsi15 < 48:
            bearish += 1

    if rsi1h is not None:

        if rsi1h > 52:
            bullish += 1

        if rsi1h < 48:
            bearish += 1

    # --------------------------------------------------------
    # YÖN
    # --------------------------------------------------------

    if bullish >= 6 and bullish >= bearish + 2:

        direction = "BULLISH"

    elif bearish >= 6 and bearish >= bullish + 2:

        direction = "BEARISH"

    else:

        direction = "NEUTRAL"

    total = max(
        bullish,
        bearish
    )

    return {
        "direction": direction,
        "score": total,
        "bullish": bullish,
        "bearish": bearish,
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
    # AŞIRI PUMP FİLTRESİ
    # --------------------------------------------------------

    if change24 > MAX_24H_MOVE:
        return None

    if change1h > MAX_1H_MOVE:
        return None

    if change15 > MAX_15M_MOVE:
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

    if rsi15 < MIN_RSI:
        return None

    if rsi1h < MIN_RSI:
        return None

    if rsi15 > MAX_RSI:
        return None

    if rsi1h > MAX_RSI:
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

    hl1h = one_hour_higher_low(
        k1h
    )

    breakout, resistance = long_breakout(
        k15
    )

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    ema20_1h = ema(
        closes1h,
        20
    )

    ema50_1h = ema(
        closes1h,
        50
    )

    trend1h = False

    if (
        ema20_1h
        and
        ema50_1h
        and
        price > ema20_1h
        and
        ema20_1h > ema50_1h
    ):
        trend1h = True

    ema20_4h = ema(
        closes4h,
        20
    )

    trend4h = False

    if (
        ema20_4h
        and
        price > ema20_4h
    ):
        trend4h = True

    squeeze = compression(
        k15
    )

    # --------------------------------------------------------
    # SKOR
    # --------------------------------------------------------

    score = 0
    reasons = []

    # BTC yön teyidi
    if btc["direction"] == "BULLISH":

        score += 15

        reasons.append(
            "BTC LONG YÖNÜ"
        )

    else:

        return None

    # 15M momentum
    if change15 > 0:

        score += 10

        reasons.append(
            "15M MOMENTUM"
        )

    # 1H trend
    if trend1h:

        score += 15

        reasons.append(
            "1H TREND"
        )

    # 4H trend
    if trend4h:

        score += 10

        reasons.append(
            "4H TREND"
        )

    # Higher low
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

    # Hacim
    if vr >= 1.35:

        score += 10

        reasons.append(
            "HACİM"
        )

    if vr >= 1.70:

        score += 5

    # Breakout
    if breakout:

        score += 15

        reasons.append(
            "DİRENÇ KIRILIMI"
        )

    # RSI
    if (
        52 <= rsi15 <= 68
        and
        52 <= rsi1h <= 68
    ):

        score += 8

        reasons.append(
            "RSI TEYİDİ"
        )

    # Sıkışma
    if squeeze:

        score += 5

        reasons.append(
            "SIKIŞMA"
        )

    # --------------------------------------------------------
    # SKOR SINIRI
    # --------------------------------------------------------

    score = min(
        score,
        100
    )

    if score < MIN_SCORE:
        return None

    structure_count = sum([
        hl15,
        hl1h,
        trend1h,
        breakout
    ])

    if structure_count < 2:
        return None

    # --------------------------------------------------------
    # ATR
    # --------------------------------------------------------

    atr = calculate_atr(
        k15,
        14
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

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

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
        "squeeze": squeeze,
        "signal_type": signal_type,
        "reasons": reasons,
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
    # BTC BEARISH OLMALI
    # --------------------------------------------------------

    if btc["direction"] != "BEARISH":
        return None

    # --------------------------------------------------------
    # AŞIRI DUMP FİLTRESİ
    #
    # Çoktan çökmüş coin'i kovalamıyoruz
    # --------------------------------------------------------

    if change24 < -MAX_24H_MOVE:
        return None

    if change1h < -MAX_1H_MOVE:
        return None

    if change15 < -MAX_15M_MOVE:
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

    # SHORT için aşırı oversold coin alma
    if rsi15 < 28:
        return None

    if rsi1h < 30:
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

    lh1h = one_hour_lower_high(
        k1h
    )

    breakdown, support = short_breakdown(
        k15
    )

    # --------------------------------------------------------
    # EMA TREND
    # --------------------------------------------------------

    ema20_1h = ema(
        closes1h,
        20
    )

    ema50_1h = ema(
        closes1h,
        50
    )

    trend1h = False

    if (
        ema20_1h
        and
        ema50_1h
        and
        price < ema20_1h
        and
        ema20_1h < ema50_1h
    ):
        trend1h = True

    ema20_4h = ema(
        closes4h,
        20
    )

    trend4h = False

    if (
        ema20_4h
        and
        price < ema20_4h
    ):
        trend4h = True

    squeeze = compression(
        k15
    )

    # --------------------------------------------------------
    # SKOR
    # --------------------------------------------------------

    score = 0
    reasons = []

    # BTC yönü
    score += 15

    reasons.append(
        "BTC SHORT YÖNÜ"
    )

    # 15M momentum
    if change15 < 0:

        score += 10

        reasons.append(
            "15M NEGATİF MOMENTUM"
        )

    # 1H trend
    if trend1h:

        score += 15

        reasons.append(
            "1H DÜŞÜŞ TRENDİ"
        )

    # 4H trend
    if trend4h:

        score += 10

        reasons.append(
            "4H DÜŞÜŞ TRENDİ"
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
    if vr >= 1.35:

        score += 10

        reasons.append(
            "HACİM"
        )

    if vr >= 1.70:

        score += 5

    # Destek kırılımı
    if breakdown:

        score += 15

        reasons.append(
            "DESTEK KIRILIMI"
        )

    # RSI
    if (
        32 <= rsi15 <= 48
        and
        32 <= rsi1h <= 48
    ):

        score += 8

        reasons.append(
            "RSI SHORT TEYİDİ"
        )

    # Sıkışma
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
    # MIN SCORE
    # --------------------------------------------------------

    if score < MIN_SCORE:
        return None

    structure_count = sum([
        lh15,
        lh1h,
        trend1h,
        breakdown
    ])

    if structure_count < 2:
        return None

    # --------------------------------------------------------
    # ATR STOP / TP
    # --------------------------------------------------------

    atr = calculate_atr(
        k15,
        14
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
    # SIGNAL TYPE
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
        "squeeze": squeeze,
        "signal_type": signal_type,
        "reasons": reasons,
        "btc_direction": btc["direction"]
    }


# ============================================================
# TEK COIN ANALİZİ
# ============================================================

def analyze_symbol(
    symbol,
    btc
):

    # BTC'nin kendisini altcoin gibi tarama
    if symbol == BTC_SYMBOL:
        return None

    ticker = get_ticker(
        symbol
    )

    if not ticker:
        return None

    price = ticker["price"]
    volume24 = ticker["volume24"]

    if volume24 < MIN_24H_VOLUME:
        return None

    # --------------------------------------------------------
    # KLINE
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # BTC BULLISH
    # SADECE LONG
    # --------------------------------------------------------

    if btc["direction"] == "BULLISH":

        return analyze_long(
            symbol,
            ticker,
            k15,
            k1h,
            k4h,
            btc
        )

    # --------------------------------------------------------
    # BTC BEARISH
    # SADECE SHORT
    # --------------------------------------------------------

    if btc["direction"] == "BEARISH":

        return analyze_short(
            symbol,
            ticker,
            k15,
            k1h,
            k4h,
            btc
        )

    # --------------------------------------------------------
    # BTC NEUTRAL
    # İŞLEM YOK
    # --------------------------------------------------------

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
    btc
):

    symbol = x["symbol"]

    direction = x["direction"]

    score = x["score"]

    price = x["price"]

    tp1 = x["tp1"]

    tp2 = x["tp2"]

    tp3 = x["tp3"]

    stop = x["stop"]

    if direction == "LONG":

        title = "🟢 <b>LONG SİNYAL</b>"

        structure1 = (
            f'📈 Higher Low: '
            f'{"✅" if x["higher_low"] else "❌"}'
        )

        structure2 = (
            f'📈 1H Higher Low: '
            f'{"✅" if x["higher_low_1h"] else "❌"}'
        )

        structure3 = (
            f'🔥 Direnç kırılımı: '
            f'{"✅" if x["breakout"] else "❌"}'
        )

        level_name = "🔑 Direnç:"

        level = x["resistance"]

    else:

        title = "🔴 <b>SHORT SİNYAL</b>"

        structure1 = (
            f'📉 Lower High: '
            f'{"✅" if x["lower_high"] else "❌"}'
        )

        structure2 = (
            f'📉 1H Lower High: '
            f'{"✅" if x["lower_high_1h"] else "❌"}'
        )

        structure3 = (
            f'🔻 Destek kırılımı: '
            f'{"✅" if x["breakdown"] else "❌"}'
        )

        level_name = "🔑 Destek:"

        level = x["support"]

    return f"""
{title}

💎 <b>{symbol}</b>
⭐ <b>Skor: {score}/100</b>

📌 <b>{x["signal_type"]}</b>

🌐 BTC Yönü:
<b>{btc["direction"]}</b>

🟢 Giriş:
<b>{format_price(price)}</b>

🎯 TP1:
<b>{format_price(tp1)}</b>

🎯 TP2:
<b>{format_price(tp2)}</b>

🎯 TP3:
<b>{format_price(tp3)}</b>

🛑 Stop:
<b>{format_price(stop)}</b>

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

{level_name}
<b>{format_price(level) if level else "-"}</b>

{structure1}
{structure2}

🔥 Hacim teyidi:
{"✅" if x["volume_ratio"] >= 1.35 else "❌"}

{structure3}

🌐 BTC 15M:
{btc["change15"]:+.2f}%

🌐 BTC 1H:
{btc["change1h"]:+.2f}%

🌐 BTC 4H:
{btc["change4h"]:+.2f}%

💎 <b>MEXC USDT FUTURES</b>

⚠️ <i>BTC yönü ve teknik filtreler birlikte değerlendirilmiştir.</i>
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
        "🚀 MEXC PUMP RADAR 9.0"
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

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    if not TELEGRAM_TOKEN:

        print(
            "⚠️ TELEGRAM_BOT_TOKEN yok."
        )

    if not TELEGRAM_CHAT_ID:

        print(
            "⚠️ TELEGRAM_CHAT_ID yok."
        )

    # --------------------------------------------------------
    # BTC ANALİZİ
    # --------------------------------------------------------

    print(
        "🌐 BTC yönü analiz ediliyor..."
    )

    btc = analyze_btc()

    print()

    print(
        "================================"
    )

    print(
        f"🌐 BTC YÖNÜ: "
        f"{btc['direction']}"
    )

    print(
        f"15M: "
        f"{btc['change15']:+.2f}%"
    )

    print(
        f"1H: "
        f"{btc['change1h']:+.2f}%"
    )

    print(
        f"4H: "
        f"{btc['change4h']:+.2f}%"
    )

    print(
        f"RSI 15M: "
        f"{btc['rsi15']:.1f}"
    )

    print(
        f"RSI 1H: "
        f"{btc['rsi1h']:.1f}"
    )

    print(
        f"RSI 4H: "
        f"{btc['rsi4h']:.1f}"
    )

    print(
        "================================"
    )

    # BTC kararsızsa işlem yok
    if btc["direction"] == "NEUTRAL":

        print(
            "⚪ BTC kararsız."
        )

        print(
            "⛔ Bu taramada işlem gönderilmeyecek."
        )

        return

    # --------------------------------------------------------
    # CONTRACTS
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

    total = len(symbols)

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_symbol,
                symbol,
                btc
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
                        f"🔥 {result['direction']} "
                        f"{symbol} "
                        f"SKOR={result['score']}"
                    )

            except Exception as e:

                print(
                    f"Hata {symbol}: {e}"
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
    # SIRALAMA
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: x["score"],
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
