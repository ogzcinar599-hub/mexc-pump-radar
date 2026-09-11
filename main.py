import os
import json
import time
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PUMP RADAR 25.2
#
# AMAÇ:
# AZ AMA KALİTELİ SİNYAL
#
# TELEGRAM SADECE:
# - COIN
# - GÜÇ
# - GİRİŞ
# - STOP
# - TP1
# - TP2
# - TP3
# - RSI
#
# ============================================================


# ============================================================
# AYARLAR
# ============================================================

BASE = "https://contract.mexc.com"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HISTORY_FILE = "signal_history.json"

MAX_WORKERS = 4

REQUEST_TIMEOUT = 12
RETRIES = 4
RETRY_BASE = 1.5

# Global API hız kontrolü
MIN_API_INTERVAL = 0.12

# Daha geniş tarama
MAX_CANDIDATES = 350

# Telegram'da maksimum sinyal
MAX_TELEGRAM = 3

# Güçlü aday eşiği
MIN_SCORE = 75

# Aynı coin tekrar gönderilmesin
COOLDOWN_HOURS = 12


# ============================================================
# GLOBAL DEĞİŞKENLER
# ============================================================

api_lock = threading.Lock()
last_api_request = 0.0

stats_lock = threading.Lock()

stats = {
    "total": 0,
    "data_error": 0,
    "rsi": 0,
    "pump": 0,
    "selling": 0,
    "trend": 0,
    "volume": 0,
    "prempump": 0,
    "structure": 0,
    "momentum": 0,
    "btc": 0,
    "score": 0,
    "strong": 0
}


# ============================================================
# İSTATİSTİK
# ============================================================

def stat_add(key):

    with stats_lock:

        if key in stats:
            stats[key] += 1


# ============================================================
# API RATE LIMIT
# ============================================================

def api_wait():

    global last_api_request

    with api_lock:

        now = time.time()

        wait_time = (
            MIN_API_INTERVAL
            - (now - last_api_request)
        )

        if wait_time > 0:
            time.sleep(wait_time)

        last_api_request = time.time()


# ============================================================
# HTTP
# ============================================================

session = requests.Session()


def request_json(url, params=None):

    for attempt in range(RETRIES):

        try:

            api_wait()

            response = session.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            # ------------------------------------------------
            # RATE LIMIT
            # ------------------------------------------------

            if response.status_code == 429:

                time.sleep(
                    RETRY_BASE * (attempt + 1)
                )

                continue

            # ------------------------------------------------
            # SERVER HATASI
            # ------------------------------------------------

            if response.status_code >= 500:

                time.sleep(
                    RETRY_BASE * (attempt + 1)
                )

                continue

            # ------------------------------------------------
            # DİĞER HTTP HATALARI
            # ------------------------------------------------

            if response.status_code != 200:

                time.sleep(RETRY_BASE)

                continue

            data = response.json()

            # ------------------------------------------------
            # MEXC API HATASI
            # ------------------------------------------------

            if isinstance(data, dict):

                success = data.get(
                    "success",
                    True
                )

                code = str(
                    data.get(
                        "code",
                        ""
                    )
                )

                if success is False:

                    if code in {
                        "510",
                        "511",
                        "502",
                        "503",
                        "504"
                    }:

                        time.sleep(
                            RETRY_BASE
                            * (attempt + 1)
                        )

                        continue

                    return None

            return data

        except requests.exceptions.Timeout:

            time.sleep(
                RETRY_BASE
                * (attempt + 1)
            )

        except requests.exceptions.RequestException:

            time.sleep(
                RETRY_BASE
                * (attempt + 1)
            )

        except Exception:

            time.sleep(RETRY_BASE)

    return None


# ============================================================
# HISTORY
# ============================================================

def load_history():

    try:

        if not os.path.exists(
            HISTORY_FILE
        ):
            return {}

        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

            if isinstance(data, dict):
                return data

    except Exception:
        pass

    return {}


def save_history(history):

    try:

        with open(
            HISTORY_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                history,
                f,
                indent=2,
                ensure_ascii=False
            )

    except Exception as e:

        print(
            "History kayıt hatası:",
            e
        )


def is_cooldown(
    symbol,
    history
):

    last = history.get(symbol)

    if not last:
        return False

    try:

        elapsed = (
            time.time()
            - float(last)
        )

        return (
            elapsed
            < COOLDOWN_HOURS * 3600
        )

    except Exception:

        return False


# ============================================================
# FUTURES SYMBOLS
# ============================================================

def get_futures_symbols():

    url = (
        f"{BASE}"
        "/api/v1/contract/detail"
    )

    data = request_json(url)

    if not data:
        return []

    raw = data.get(
        "data",
        []
    )

    if isinstance(raw, dict):
        raw = list(
            raw.values()
        )

    symbols = []

    for item in raw:

        try:

            symbol = str(
                item.get(
                    "symbol",
                    ""
                )
            ).upper()

            state = item.get(
                "state",
                0
            )

            quote_coin = str(
                item.get(
                    "quoteCoin",
                    "USDT"
                )
            ).upper()

            if state != 0:
                continue

            if quote_coin != "USDT":
                continue

            if not symbol.endswith(
                "_USDT"
            ):
                continue

            bad_words = [
                "ETF",
                "STOCK",
                "INDEX",
                "SHARE",
                "3L",
                "3S",
                "5L",
                "5S"
            ]

            if any(
                word in symbol
                for word in bad_words
            ):
                continue

            symbols.append(symbol)

        except Exception:
            continue

    return sorted(
        set(symbols)
    )


# ============================================================
# TICKER
# ============================================================

def get_all_tickers():

    url = (
        f"{BASE}"
        "/api/v1/contract/ticker"
    )

    data = request_json(url)

    if not data:
        return []

    raw = data.get(
        "data",
        []
    )

    if isinstance(raw, dict):

        if "symbol" in raw:
            raw = [raw]

        else:
            raw = list(
                raw.values()
            )

    if not isinstance(
        raw,
        list
    ):
        return []

    return raw


# ============================================================
# KLINE
# ============================================================

def get_klines(
    symbol,
    interval,
    limit=80
):

    interval_minutes = {
        "Min15": 15,
        "Min60": 60,
        "Hour4": 240
    }

    minutes = interval_minutes.get(
        interval
    )

    if not minutes:
        return None

    now_ms = int(
        time.time() * 1000
    )

    start_ms = (
        now_ms
        - (
            minutes
            * 60
            * 1000
            * (limit + 10)
        )
    )

    url = (
        f"{BASE}"
        f"/api/v1/contract/kline/{symbol}"
    )

    params = {
        "interval": interval,
        "start": start_ms,
        "end": now_ms
    }

    data = request_json(
        url,
        params
    )

    if not data:
        return None

    raw = data.get(
        "data"
    )

    if not raw:
        return None

    # ========================================================
    # DICT
    # ========================================================

    if isinstance(
        raw,
        dict
    ):

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

            vols = raw.get(
                "vol",
                []
            )

            n = min(
                len(times),
                len(opens),
                len(closes),
                len(highs),
                len(lows),
                len(vols)
            )

            candles = []

            for i in range(n):

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
                        vols[i]
                    )
                })

            return candles[-limit:]

        except Exception:

            return None

    # ========================================================
    # LIST
    # ========================================================

    if isinstance(
        raw,
        list
    ):

        candles = []

        for x in raw:

            try:

                if isinstance(
                    x,
                    dict
                ):

                    candles.append({
                        "time": float(
                            x.get(
                                "time",
                                0
                            )
                        ),
                        "open": float(
                            x.get(
                                "open",
                                0
                            )
                        ),
                        "close": float(
                            x.get(
                                "close",
                                0
                            )
                        ),
                        "high": float(
                            x.get(
                                "high",
                                0
                            )
                        ),
                        "low": float(
                            x.get(
                                "low",
                                0
                            )
                        ),
                        "vol": float(
                            x.get(
                                "vol",
                                x.get(
                                    "volume",
                                    0
                                )
                            )
                        )
                    })

                elif (
                    isinstance(
                        x,
                        list
                    )
                    and len(x) >= 6
                ):

                    candles.append({
                        "time": float(
                            x[0]
                        ),
                        "open": float(
                            x[1]
                        ),
                        "close": float(
                            x[2]
                        ),
                        "high": float(
                            x[3]
                        ),
                        "low": float(
                            x[4]
                        ),
                        "vol": float(
                            x[5]
                        )
                    })

            except Exception:
                continue

        return candles[-limit:]

    return None


# ============================================================
# RSI
# ============================================================

def calculate_rsi(
    closes,
    period=14
):

    if (
        not closes
        or len(closes)
        < period + 1
    ):
        return None

    gains = []
    losses = []

    for i in range(
        1,
        len(closes)
    ):

        change = (
            closes[i]
            - closes[i - 1]
        )

        if change >= 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(change)
            )

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
        return 100.0

    rs = (
        avg_gain
        / avg_loss
    )

    return 100 - (
        100
        / (1 + rs)
    )


# ============================================================
# EMA
# ============================================================

def ema(
    values,
    period
):

    if (
        not values
        or len(values) < period
    ):
        return None

    multiplier = (
        2 / (period + 1)
    )

    result = (
        sum(values[:period])
        / period
    )

    for price in values[period:]:

        result = (
            (
                price
                - result
            )
            * multiplier
            + result
        )

    return result


# ============================================================
# PERCENT CHANGE
# ============================================================

def pct_change(
    values,
    candles
):

    if (
        not values
        or len(values)
        <= candles
    ):
        return 0.0

    old = values[
        -candles - 1
    ]

    new = values[-1]

    if old == 0:
        return 0.0

    return (
        (new - old)
        / old
        * 100
    )


# ============================================================
# VOLUME RATIO
# ============================================================

def volume_ratio(
    candles
):

    if (
        not candles
        or len(candles) < 22
    ):
        return 0.0

    current = candles[-1]["vol"]

    previous = [
        x["vol"]
        for x in candles[-21:-1]
    ]

    if not previous:
        return 0.0

    avg = (
        sum(previous)
        / len(previous)
    )

    if avg <= 0:
        return 0.0

    return current / avg


# ============================================================
# VOLUME GROWTH
# ============================================================

def volume_growth(
    candles
):

    if (
        not candles
        or len(candles) < 15
    ):
        return 0.0

    recent = [
        x["vol"]
        for x in candles[-3:]
    ]

    old = [
        x["vol"]
        for x in candles[-13:-3]
    ]

    if not old:
        return 0.0

    recent_avg = (
        sum(recent)
        / len(recent)
    )

    old_avg = (
        sum(old)
        / len(old)
    )

    if old_avg <= 0:
        return 0.0

    return (
        recent_avg
        / old_avg
    )


# ============================================================
# SELLING PRESSURE
# ============================================================

def selling_pressure(
    candles
):

    if not candles:
        return 1.0

    c = candles[-1]

    high = c["high"]
    low = c["low"]
    op = c["open"]
    close = c["close"]

    rng = high - low

    if rng <= 0:
        return 0.0

    upper_wick = (
        high
        - max(op, close)
    )

    body = abs(
        close - op
    )

    # Büyük üst fitil
    if upper_wick > body * 2.5:
        return 1.0

    # Büyük kırmızı mum
    if close < op:

        red_body = (
            op - close
        )

        if red_body > rng * 0.60:
            return 1.0

    return 0.0


# ============================================================
# PUMP ALREADY
# ============================================================

def pump_already(
    candles15,
    candles1h,
    rsi15,
    rsi1h,
    rsi4h
):

    if (
        not candles15
        or not candles1h
    ):
        return True

    close15 = [
        x["close"]
        for x in candles15
    ]

    close1h = [
        x["close"]
        for x in candles1h
    ]

    move15_6 = pct_change(
        close15,
        6
    )

    move15_12 = pct_change(
        close15,
        12
    )

    move1h_4 = pct_change(
        close1h,
        4
    )

    # --------------------------------------------------------
    # PUMP ÇOK İLERLEDİYSE
    # --------------------------------------------------------

    if move15_6 >= 7.5:
        return True

    if move15_12 >= 12:
        return True

    if move1h_4 >= 8:
        return True

    # --------------------------------------------------------
    # RSI ŞİŞMİŞSE
    # --------------------------------------------------------

    if (
        rsi15 is not None
        and rsi15 >= 78
    ):
        return True

    if (
        rsi1h is not None
        and rsi1h >= 72
    ):
        return True

    if (
        rsi4h is not None
        and rsi4h >= 70
    ):
        return True

    return False


# ============================================================
# STRUCTURE
# ============================================================

def structure_score(
    candles
):

    if (
        not candles
        or len(candles) < 30
    ):
        return (
            0,
            False,
            False,
            0.0
        )

    highs = [
        x["high"]
        for x in candles
    ]

    lows = [
        x["low"]
        for x in candles
    ]

    closes = [
        x["close"]
        for x in candles
    ]

    price = closes[-1]

    resistance = max(
        highs[-25:-3]
    )

    if resistance <= 0:
        return (
            0,
            False,
            False,
            0.0
        )

    distance = (
        (price - resistance)
        / resistance
        * 100
    )

    breakout = (
        price
        > resistance * 1.002
    )

    retest = False

    recent_low = min(
        lows[-3:]
    )

    if (
        recent_low
        <= resistance * 1.012
        and price > resistance
    ):
        retest = True

    if retest:

        score = 15

    elif breakout:

        score = 13

    elif price >= resistance * 0.97:

        score = 10

    elif price >= resistance * 0.94:

        score = 7

    else:

        score = 3

    return (
        score,
        breakout,
        retest,
        resistance
    )


# ============================================================
# TREND
# ============================================================

def timeframe_trend(
    candles
):

    if (
        not candles
        or len(candles) < 55
    ):
        return 0

    closes = [
        x["close"]
        for x in candles
    ]

    price = closes[-1]

    ema20 = ema(
        closes,
        20
    )

    ema50 = ema(
        closes,
        50
    )

    if (
        ema20 is None
        or ema50 is None
    ):
        return 0

    score = 0

    if price > ema20:
        score += 3

    if price > ema50:
        score += 3

    if ema20 > ema50:
        score += 2

    if pct_change(
        closes,
        5
    ) > 0:
        score += 1

    return min(
        score,
        9
    )


def trend_score(
    candles15,
    candles1h,
    candles4h
):

    s15 = timeframe_trend(
        candles15
    )

    s1h = timeframe_trend(
        candles1h
    )

    s4h = timeframe_trend(
        candles4h
    )

    total = (
        s15
        + s1h
        + s4h
    )

    return min(
        20,
        int(
            total
            / 27
            * 20
        )
    )


# ============================================================
# RSI QUALITY
# ============================================================

def rsi_quality_score(
    rsi15,
    rsi1h,
    rsi4h
):

    score = 0

    # 15M
    if 54 <= rsi15 <= 65:
        score += 7

    elif 50 <= rsi15 < 54:
        score += 5

    elif 65 < rsi15 <= 70:
        score += 5

    elif 48 <= rsi15 < 50:
        score += 3

    # 1H
    if 55 <= rsi1h <= 65:
        score += 7

    elif 52 <= rsi1h < 55:
        score += 5

    elif 65 < rsi1h <= 68:
        score += 5

    elif 50 <= rsi1h < 52:
        score += 3

    # 4H
    if 50 <= rsi4h <= 62:
        score += 6

    elif 48 <= rsi4h < 50:
        score += 4

    elif 62 < rsi4h <= 67:
        score += 4

    return min(
        score,
        20
    )


# ============================================================
# VOLUME SCORE
# ============================================================

def volume_score(
    candles15,
    candles1h
):

    vr15 = volume_ratio(
        candles15
    )

    vr1h = volume_ratio(
        candles1h
    )

    growth15 = volume_growth(
        candles15
    )

    score = 0

    # 15M
    if vr15 >= 2.5:
        score += 8

    elif vr15 >= 1.8:
        score += 6

    elif vr15 >= 1.5:
        score += 5

    elif vr15 >= 1.25:
        score += 3

    # 1H
    if vr1h >= 2.0:
        score += 5

    elif vr1h >= 1.5:
        score += 4

    elif vr1h >= 1.25:
        score += 2

    # Hacim gelişimi
    if growth15 >= 1.20:
        score += 2

    return min(
        score,
        15
    )


# ============================================================
# MOMENTUM
# ============================================================

def momentum_score(
    candles15,
    candles1h,
    candles4h
):

    c15 = [
        x["close"]
        for x in candles15
    ]

    c1h = [
        x["close"]
        for x in candles1h
    ]

    c4h = [
        x["close"]
        for x in candles4h
    ]

    m15 = pct_change(
        c15,
        4
    )

    m1h = pct_change(
        c1h,
        3
    )

    m4h = pct_change(
        c4h,
        3
    )

    score = 0

    # 15M
    if 0.4 <= m15 <= 4:
        score += 4

    elif m15 > 0:
        score += 2

    # 1H
    if 0.5 <= m1h <= 6:
        score += 4

    elif m1h > 0:
        score += 2

    # 4H
    if m4h > 0:
        score += 2

    return (
        min(score, 10),
        m15,
        m1h,
        m4h
    )


# ============================================================
# PRE-PUMP
# ============================================================

def pre_pump_score(
    candles15,
    candles1h,
    rsi15,
    rsi1h
):

    c15 = [
        x["close"]
        for x in candles15
    ]

    c1h = [
        x["close"]
        for x in candles1h
    ]

    m15 = pct_change(
        c15,
        6
    )

    m1h = pct_change(
        c1h,
        4
    )

    score = 0

    # 15M
    if 0.5 <= m15 <= 5:
        score += 6

    elif 0 < m15 <= 7:
        score += 4

    # 1H
    if 0.5 <= m1h <= 7:
        score += 5

    elif m1h > 0:
        score += 3

    # RSI uygun bölge
    if (
        52 <= rsi15 <= 68
    ):
        score += 2

    if (
        53 <= rsi1h <= 68
    ):
        score += 2

    return min(
        score,
        15
    )


# ============================================================
# BTC DURUMU
#
# ÖNEMLİ:
# ARTIK HER COIN İÇİN ÇAĞRILMIYOR.
# SADECE BİR KEZ ÇALIŞIYOR.
# ============================================================

def get_btc_state():

    try:

        c15 = get_klines(
            "BTC_USDT",
            "Min15",
            60
        )

        c1h = get_klines(
            "BTC_USDT",
            "Min60",
            60
        )

        if (
            not c15
            or not c1h
        ):
            return 3

        close15 = [
            x["close"]
            for x in c15
        ]

        close1h = [
            x["close"]
            for x in c1h
        ]

        m15 = pct_change(
            close15,
            4
        )

        m1h = pct_change(
            close1h,
            3
        )

        # Çok kötü BTC
        if (
            m15 < -1.2
            and m1h < -2.0
        ):
            return 0

        # Negatif
        if (
            m15 < -0.5
            or m1h < -1.0
        ):
            return 2

        # İyi BTC
        if (
            m15 >= 0
            and m1h >= 0
        ):
            return 5

        return 3

    except Exception:

        return 3


# ============================================================
# ANA ANALİZ
# ============================================================

def analyze_coin(
    symbol,
    btc_score
):

    stat_add("total")

    try:

        # ----------------------------------------------------
        # KLINE
        # ----------------------------------------------------

        candles15 = get_klines(
            symbol,
            "Min15",
            80
        )

        candles1h = get_klines(
            symbol,
            "Min60",
            80
        )

        candles4h = get_klines(
            symbol,
            "Hour4",
            80
        )

        if (
            not candles15
            or not candles1h
            or not candles4h
        ):

            stat_add(
                "data_error"
            )

            return None

        if (
            len(candles15) < 55
            or len(candles1h) < 55
            or len(candles4h) < 55
        ):

            stat_add(
                "data_error"
            )

            return None

        # ----------------------------------------------------
        # CLOSES
        # ----------------------------------------------------

        close15 = [
            x["close"]
            for x in candles15
        ]

        close1h = [
            x["close"]
            for x in candles1h
        ]

        close4h = [
            x["close"]
            for x in candles4h
        ]

        price = close15[-1]

        if price <= 0:

            stat_add(
                "data_error"
            )

            return None

        # ----------------------------------------------------
        # RSI
        # ----------------------------------------------------

        rsi15 = calculate_rsi(
            close15
        )

        rsi1h = calculate_rsi(
            close1h
        )

        rsi4h = calculate_rsi(
            close4h
        )

        if (
            rsi15 is None
            or rsi1h is None
            or rsi4h is None
        ):

            stat_add(
                "data_error"
            )

            return None

        # ----------------------------------------------------
        # RSI HARD FILTER
        # ----------------------------------------------------

        if (
            rsi15 < 50
            or rsi1h < 52
            or rsi4h < 48
            or rsi15 > 72
            or rsi1h > 70
            or rsi4h > 68
        ):

            stat_add(
                "rsi"
            )

            return None

        # ----------------------------------------------------
        # PUMP ALREADY
        # ----------------------------------------------------

        if pump_already(
            candles15,
            candles1h,
            rsi15,
            rsi1h,
            rsi4h
        ):

            stat_add(
                "pump"
            )

            return None

        # ----------------------------------------------------
        # SATIŞ BASKISI
        # ----------------------------------------------------

        if selling_pressure(
            candles15
        ):

            stat_add(
                "selling"
            )

            return None

        # ----------------------------------------------------
        # TREND
        # ----------------------------------------------------

        tr_score = trend_score(
            candles15,
            candles1h,
            candles4h
        )

        if tr_score < 12:

            stat_add(
                "trend"
            )

            return None

        # ----------------------------------------------------
        # RSI SCORE
        # ----------------------------------------------------

        rs_score = rsi_quality_score(
            rsi15,
            rsi1h,
            rsi4h
        )

        if rs_score < 13:

            stat_add(
                "rsi"
            )

            return None

        # ----------------------------------------------------
        # HACİM
        # ----------------------------------------------------

        vol_score = volume_score(
            candles15,
            candles1h
        )

        if vol_score < 5:

            stat_add(
                "volume"
            )

            return None

        # ----------------------------------------------------
        # PRE-PUMP
        # ----------------------------------------------------

        pp_score = pre_pump_score(
            candles15,
            candles1h,
            rsi15,
            rsi1h
        )

        if pp_score < 8:

            stat_add(
                "prempump"
            )

            return None

        # ----------------------------------------------------
        # STRUCTURE
        # ----------------------------------------------------

        (
            st_score,
            breakout,
            retest,
            resistance
        ) = structure_score(
            candles1h
        )

        if resistance <= 0:

            stat_add(
                "structure"
            )

            return None

        distance = (
            (price - resistance)
            / resistance
            * 100
        )

        # Direnci fazla aşmışsa kovalamaca
        if distance > 2.5:

            stat_add(
                "structure"
            )

            return None

        # Çok kötü yapı
        if st_score < 5:

            stat_add(
                "structure"
            )

            return None

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------

        (
            mom_score,
            m15,
            m1h,
            m4h
        ) = momentum_score(
            candles15,
            candles1h,
            candles4h
        )

        if mom_score < 6:

            stat_add(
                "momentum"
            )

            return None

        # ----------------------------------------------------
        # BTC
        # ----------------------------------------------------

        if btc_score < 2:

            stat_add(
                "btc"
            )

            return None

        # ----------------------------------------------------
        # TOPLAM SCORE
        # ----------------------------------------------------

        score = (
            tr_score
            + rs_score
            + vol_score
            + pp_score
            + st_score
            + mom_score
            + btc_score
        )

        # ----------------------------------------------------
        # ERKEN GİRİŞ BONUSU
        # ----------------------------------------------------

        early_bonus = 0

        if (
            52 <= rsi15 <= 65
            and 53 <= rsi1h <= 65
            and 48 <= rsi4h <= 62
            and 0 < m15 < 4
            and 0 < m1h < 6
        ):

            early_bonus = 5

        score += early_bonus

        score = min(
            100,
            max(0, score)
        )

        # ----------------------------------------------------
        # SON FİLTRE
        # ----------------------------------------------------

        if score < MIN_SCORE:

            stat_add(
                "score"
            )

            return None

        if m15 <= 0:

            stat_add(
                "momentum"
            )

            return None

        if m1h <= 0:

            stat_add(
                "momentum"
            )

            return None

        if m4h < -1.0:

            stat_add(
                "momentum"
            )

            return None

        # ----------------------------------------------------
        # VOLATİLİTE
        # ----------------------------------------------------

        ranges = []

        for c in candles15[-14:]:

            if c["close"] <= 0:
                continue

            ranges.append(
                (
                    c["high"]
                    - c["low"]
                )
                / c["close"]
            )

        if ranges:

            avg_range = (
                sum(ranges)
                / len(ranges)
            )

        else:

            avg_range = 0.015

        # ----------------------------------------------------
        # STOP
        # ----------------------------------------------------

        stop_pct = max(
            0.018,
            min(
                0.028,
                avg_range * 1.8
            )
        )

        entry = price

        stop = (
            entry
            * (1 - stop_pct)
        )

        # ----------------------------------------------------
        # TP
        # ----------------------------------------------------

        tp1 = entry * 1.040
        tp2 = entry * 1.065
        tp3 = entry * 1.095

        stat_add(
            "strong"
        )

        return {

            "symbol": symbol,

            "score": score,

            "entry": entry,
            "stop": stop,

            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,

            "rsi15": rsi15,
            "rsi1h": rsi1h,
            "rsi4h": rsi4h,

            "volume15": volume_ratio(
                candles15
            ),

            "volume1h": volume_ratio(
                candles1h
            ),

            "momentum15": m15,
            "momentum1h": m1h,
            "momentum4h": m4h,

            "breakout": breakout,
            "retest": retest,

            "btc_score": btc_score
        }

    except Exception as e:

        print(
            f"ANALİZ HATASI "
            f"{symbol}: {e}"
        )

        stat_add(
            "data_error"
        )

        return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(
    text
):

    if not TELEGRAM_BOT_TOKEN:

        print(
            "TELEGRAM_BOT_TOKEN yok"
        )

        return False

    if not TELEGRAM_CHAT_ID:

        print(
            "TELEGRAM_CHAT_ID yok"
        )

        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=15
        )

        if response.status_code == 200:

            data = response.json()

            if data.get("ok"):

                return True

        print(
            "Telegram hata:",
            response.text[:500]
        )

    except Exception as e:

        print(
            "Telegram bağlantı hatası:",
            e
        )

    return False


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def format_signal(
    result
):

    symbol = (
        result["symbol"]
        .replace(
            "_USDT",
            "/USDT"
        )
    )

    score = result["score"]

    if score >= 90:

        title = (
            "🔥 ÇOK YÜKSEK POTANSİYEL"
        )

    elif score >= 84:

        title = (
            "🚀 YÜKSEK POTANSİYEL"
        )

    else:

        title = (
            "🟢 GÜÇLÜ LONG"
        )

    return f"""🚀 PUMP RADAR 25.2

{title}

{symbol}

⭐ GÜÇ: {score}/100

🎯 GİRİŞ
{result["entry"]:.8f}

🛑 STOP
{result["stop"]:.8f}

🥇 TP1
{result["tp1"]:.8f}

🥈 TP2
{result["tp2"]:.8f}

🥉 TP3
{result["tp3"]:.8f}

📊 RSI

15M: {result["rsi15"]:.1f}
1H: {result["rsi1h"]:.1f}
4H: {result["rsi4h"]:.1f}

⚠️ Otomatik teknik taramadır."""


# ============================================================
# MAIN
# ============================================================

def main():

    global stats

    stats = {
        "total": 0,
        "data_error": 0,
        "rsi": 0,
        "pump": 0,
        "selling": 0,
        "trend": 0,
        "volume": 0,
        "prempump": 0,
        "structure": 0,
        "momentum": 0,
        "btc": 0,
        "score": 0,
        "strong": 0
    }

    print()
    print("=" * 60)
    print(
        "🚀 MEXC PUMP RADAR 25.2"
    )
    print(
        "🎯 AZ SİNYAL / YÜKSEK POTANSİYEL"
    )
    print("=" * 60)

    history = load_history()

    # ========================================================
    # FUTURES
    # ========================================================

    symbols = get_futures_symbols()

    print(
        f"Futures coin sayısı: "
        f"{len(symbols)}"
    )

    if not symbols:

        print(
            "❌ Futures sembol alınamadı."
        )

        return

    # ========================================================
    # TICKERS
    # ========================================================

    tickers = get_all_tickers()

    print(
        f"Ticker sayısı: "
        f"{len(tickers)}"
    )

    if not tickers:

        print(
            "❌ Ticker alınamadı."
        )

        return

    ticker_map = {}

    # ========================================================
    # TICKER MAP
    # ========================================================

    for t in tickers:

        try:

            symbol = str(
                t.get(
                    "symbol",
                    ""
                )
            ).upper()

            if symbol not in symbols:
                continue

            price = float(
                t.get(
                    "lastPrice",
                    0
                )
            )

            rise = float(
                t.get(
                    "riseFallRate",
                    0
                )
            )

            amount = float(
                t.get(
                    "amount24",
                    t.get(
                        "amount",
                        0
                    )
                )
                or 0
            )

            # Decimal oran
            rise_pct = rise * 100

            ticker_map[symbol] = {
                "price": price,
                "rise": rise_pct,
                "amount": amount
            }

        except Exception:
            continue

    # ========================================================
    # VALID
    # ========================================================

    valid = []

    for symbol in symbols:

        t = ticker_map.get(
            symbol
        )

        if not t:
            continue

        if t["price"] <= 0:
            continue

        # Aşırı düşenleri ele
        if t["rise"] < -20:
            continue

        valid.append(symbol)

    print(
        f"Geçerli coin: "
        f"{len(valid)}"
    )

    # ========================================================
    # DAHA GENİŞ ADAY HAVUZU
    # ========================================================

    # En yüksek hacimli 220
    top_volume = sorted(
        valid,
        key=lambda x:
        ticker_map[x]["amount"],
        reverse=True
    )[:220]

    # En çok yükselen 180
    top_gainers = sorted(
        valid,
        key=lambda x:
        ticker_map[x]["rise"],
        reverse=True
    )[:180]

    candidate_set = set(
        top_volume
    )

    candidate_set.update(
        top_gainers
    )

    candidates = list(
        candidate_set
    )

    # ========================================================
    # COOLDOWN
    # ========================================================

    before_cooldown = len(
        candidates
    )

    candidates = [
        x
        for x in candidates
        if not is_cooldown(
            x,
            history
        )
    ]

    cooldown_removed = (
        before_cooldown
        - len(candidates)
    )

    print(
        f"Cooldown elenen: "
        f"{cooldown_removed}"
    )

    # ========================================================
    # MAX 350
    # ========================================================

    candidates = candidates[
        :MAX_CANDIDATES
    ]

    print(
        f"Taranacak aday: "
        f"{len(candidates)}"
    )

    if not candidates:

        print(
            "❌ Tarama adayı yok."
        )

        return

    # ========================================================
    # BTC
    # ========================================================

    print(
        "₿ BTC durumu hesaplanıyor..."
    )

    btc_score = get_btc_state()

    print(
        f"₿ BTC skoru: "
        f"{btc_score}/5"
    )

    # ========================================================
    # DEEP SCAN
    # ========================================================

    results = []

    completed = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {

            executor.submit(
                analyze_coin,
                symbol,
                btc_score
            ): symbol

            for symbol in candidates

        }

        for future in as_completed(
            futures
        ):

            symbol = futures[
                future
            ]

            try:

                result = future.result()

                completed += 1

                if result:

                    results.append(
                        result
                    )

            except Exception as e:

                print(
                    f"{symbol} hata: "
                    f"{e}"
                )

    print()
    print(
        f"Tarama tamamlandı: "
        f"{completed}"
    )

    # ========================================================
    # SCORE SIRALA
    # ========================================================

    results.sort(
        key=lambda x:
        x["score"],
        reverse=True
    )

    # ========================================================
    # STRONG
    # ========================================================

    strong = [
        x
        for x in results
        if x["score"] >= MIN_SCORE
    ]

    strong = strong[
        :MAX_TELEGRAM
    ]

    # ========================================================
    # RAPOR
    # ========================================================

    print()
    print("=" * 60)
    print(
        "📊 ELEME RAPORU"
    )
    print("=" * 60)

    print(
        f"Toplam analiz: "
        f"{stats['total']}"
    )

    print(
        f"Veri hatası: "
        f"{stats['data_error']}"
    )

    print(
        f"RSI filtresi: "
        f"{stats['rsi']}"
    )

    print(
        f"Pump olmuş: "
        f"{stats['pump']}"
    )

    print(
        f"Satış baskısı: "
        f"{stats['selling']}"
    )

    print(
        f"Trend düşük: "
        f"{stats['trend']}"
    )

    print(
        f"Hacim düşük: "
        f"{stats['volume']}"
    )

    print(
        f"Pre-pump düşük: "
        f"{stats['prempump']}"
    )

    print(
        f"Yapı düşük: "
        f"{stats['structure']}"
    )

    print(
        f"Momentum düşük: "
        f"{stats['momentum']}"
    )

    print(
        f"BTC filtresi: "
        f"{stats['btc']}"
    )

    print(
        f"Skor 75 altı: "
        f"{stats['score']}"
    )

    print(
        f"🔥 Güçlü aday: "
        f"{len(strong)}"
    )

    print("=" * 60)

    # ========================================================
    # GÜÇLÜ ADAY YOK
    # ========================================================

    if not strong:

        print()
        print(
            "❌ Yeterince güçlü coin yok."
        )

        print(
            "Zayıf coinler Telegram'a gönderilmedi."
        )

        return

    # ========================================================
    # EN GÜÇLÜ ADAYLARI GÖSTER
    # ========================================================

    print()
    print(
        "🔥 EN GÜÇLÜ ADAYLAR:"
    )

    for result in strong:

        print(
            f"{result['symbol']} "
            f"→ "
            f"{result['score']}/100"
        )

    # ========================================================
    # TELEGRAM
    # ========================================================

    sent_count = 0

    for result in strong:

        text = format_signal(
            result
        )

        success = send_telegram(
            text
        )

        if success:

            history[
                result["symbol"]
            ] = time.time()

            sent_count += 1

            print(
                f"✅ Telegram: "
                f"{result['symbol']}"
            )

            time.sleep(1)

        else:

            print(
                f"❌ Telegram gönderilemedi: "
                f"{result['symbol']}"
            )

    # ========================================================
    # HISTORY
    # ========================================================

    save_history(
        history
    )

    print()
    print("=" * 60)
    print(
        f"📨 Telegram gönderilen: "
        f"{sent_count}"
    )
    print("=" * 60)
    print()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
