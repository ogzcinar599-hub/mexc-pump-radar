import os
import json
import time
import threading
import requests

from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PUMP RADAR 25.0
#
# AMAÇ:
# PUMP BAŞLAMADAN HEMEN ÖNCE YAKALAMAK
#
# 728 FUTURES
#       ↓
# TOPLU TICKER
#       ↓
# PREFILTER
#       ↓
# 160 COIN
#       ↓
# 15M + 1H + 4H
#       ↓
# RSI
# EMA
# HACİM YÖNÜ
# MOMENTUM
# BREAKOUT
# RETEST
# FAKE BREAKOUT
# SATIŞ BASKISI
# PUMP ÖNCESİ
# BTC
# GEÇ PUMP FİLTRESİ
#       ↓
# 0-100 GERÇEK SCORE
#       ↓
# TELEGRAM
#
# 25.0 DEĞİŞİKLİKLER:
#
# ✅ Futures API = contract.mexc.com
# ✅ Global rate-limit
# ✅ Retry
# ✅ 429 / 510 koruması
# ✅ KLINE teşhisi
# ✅ 15M / 1H / 4H veri ayrımı
# ✅ Geç pump filtresi
# ✅ 1H RSI > 72 koruması
# ✅ 4H RSI > 70 koruması
# ✅ EMA aşırı uzaklık filtresi
# ✅ Breakout sonrası aşırı kaçmış coinleri eleme
# ✅ Hacim yönü
# ✅ Dağıtım / satış baskısı
# ✅ Gerçek 0-100 skor
# ============================================================


# ============================================================
# API
# ============================================================

BASE = "https://contract.mexc.com"


TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID"
)


HISTORY_FILE = "signal_history.json"


# ============================================================
# RATE LIMIT
# ============================================================

MAX_WORKERS = 4

REQUEST_TIMEOUT = 15

RETRIES = 3

RETRY_BASE = 1.5

# MEXC genel Futures market API:
# 20 istek / 2 saniye ≈ 0.10 sn
# Güvenlik payı bırakıyoruz.
MIN_API_INTERVAL = 0.12


api_lock = threading.Lock()

last_api_call = 0.0


# ============================================================
# RADAR
# ============================================================

KLINE_LIMIT = 100

MAX_DEEP_SCAN = 160

MAX_TELEGRAM = 8

MIN_SCORE = 62

COOLDOWN_HOURS = 6


# ============================================================
# PREFILTER
# ============================================================

TOP_VOLUME = 120

TOP_GAINERS = 100

MAX_24H_DROP = -20.0


# ============================================================
# DEBUG
# ============================================================

debug_errors = []

debug_lock = threading.Lock()

stats_lock = threading.Lock()


stats = {

    "TOTAL": 0,

    "PREFILTER": 0,

    "DATA15": 0,

    "DATA1H": 0,

    "DATA4H": 0,

    "RSI": 0,

    "VOLUME": 0,

    "RESISTANCE": 0,

    "FAKE": 0,

    "OVEREXTENDED": 0,

    "BTC": 0,

    "QUALITY": 0,

    "SIGNAL": 0,

    "ERROR": 0

}


# ============================================================
# DEBUG ERROR
# ============================================================

def add_debug_error(text):

    with debug_lock:

        if text in debug_errors:
            return

        if len(debug_errors) < 20:

            debug_errors.append(text)


# ============================================================
# GLOBAL API WAIT
# ============================================================

def api_wait():

    global last_api_call

    with api_lock:

        now = time.monotonic()

        wait = (
            MIN_API_INTERVAL
            -
            (now - last_api_call)
        )

        if wait > 0:

            time.sleep(wait)

        last_api_call = time.monotonic()


# ============================================================
# HTTP JSON
# ============================================================

def request_json(url, params=None):

    headers = {

        "User-Agent":
            "Mozilla/5.0 MEXC-PUMP-RADAR/25.0",

        "Accept":
            "application/json"

    }


    last_error = None


    for attempt in range(RETRIES):

        try:

            api_wait()


            response = requests.get(

                url,

                params=params,

                headers=headers,

                timeout=REQUEST_TIMEOUT

            )


            # =================================================
            # RATE LIMIT
            # =================================================

            if response.status_code == 429:

                last_error = (

                    "HTTP 429 RATE LIMIT | "
                    f"{url}"
                )

                time.sleep(

                    RETRY_BASE
                    *
                    (attempt + 1)

                )

                continue


            # =================================================
            # SERVER
            # =================================================

            if response.status_code >= 500:

                last_error = (

                    f"HTTP "
                    f"{response.status_code} | "
                    f"{url}"
                )

                time.sleep(

                    RETRY_BASE
                    *
                    (attempt + 1)

                )

                continue


            # =================================================
            # HTTP ERROR
            # =================================================

            if response.status_code != 200:

                last_error = (

                    f"HTTP "
                    f"{response.status_code} | "
                    f"{response.text[:150]}"
                )

                break


            data = response.json()


            if not isinstance(data, dict):

                last_error = (

                    f"JSON FORMAT ERROR | "
                    f"{url}"
                )

                break


            # =================================================
            # MEXC ERROR
            # =================================================

            if data.get("success") is False:

                code = data.get("code")

                message = data.get(
                    "message",
                    ""
                )


                if str(code) == "510":

                    last_error = (

                        "MEXC 510 RATE LIMIT | "
                        f"{url}"
                    )

                    time.sleep(

                        RETRY_BASE
                        *
                        (attempt + 1)

                    )

                    continue


                last_error = (

                    f"MEXC ERROR "
                    f"code={code} "
                    f"message={message}"
                )

                break


            return data


        except requests.exceptions.Timeout:

            last_error = (

                "TIMEOUT | "
                f"{url}"
            )

            time.sleep(

                RETRY_BASE
                *
                (attempt + 1)

            )


        except requests.exceptions.RequestException as e:

            last_error = (

                "REQUEST ERROR | "
                f"{str(e)[:150]}"
            )

            time.sleep(

                RETRY_BASE
                *
                (attempt + 1)

            )


        except Exception as e:

            last_error = (

                "UNKNOWN ERROR | "
                f"{str(e)[:150]}"
            )

            break


    if last_error:

        add_debug_error(last_error)


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

            return json.load(f)


    except Exception:

        return {}


# ============================================================

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

        add_debug_error(

            f"HISTORY ERROR: "
            f"{str(e)[:120]}"

        )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(text):

    if not TELEGRAM_BOT_TOKEN:

        print(
            "❌ TELEGRAM_BOT_TOKEN yok"
        )

        return False


    if not TELEGRAM_CHAT_ID:

        print(
            "❌ TELEGRAM_CHAT_ID yok"
        )

        return False


    url = (

        "https://api.telegram.org/bot"

        f"{TELEGRAM_BOT_TOKEN}"

        "/sendMessage"

    )


    payload = {

        "chat_id":
            TELEGRAM_CHAT_ID,

        "text":
            text,

        "parse_mode":
            "HTML",

        "disable_web_page_preview":
            True

    }


    try:

        r = requests.post(

            url,

            json=payload,

            timeout=15

        )


        if r.status_code == 200:

            return True


        print(
            "Telegram HTTP:",
            r.status_code,
            r.text[:150]
        )

        return False


    except Exception as e:

        print(
            "Telegram hata:",
            e
        )

        return False


# ============================================================
# FUTURES
# ============================================================

def get_futures_symbols():

    url = (
        f"{BASE}/api/v1/contract/detail"
    )


    data = request_json(url)


    if not data:

        return []


    rows = data.get(
        "data"
    )


    if not isinstance(
        rows,
        list
    ):

        add_debug_error(
            "CONTRACT DETAIL DATA LIST DEĞİL"
        )

        return []


    symbols = []


    for item in rows:

        try:

            symbol = str(
                item.get(
                    "symbol",
                    ""
                )
            ).upper()


            if not symbol.endswith(
                "_USDT"
            ):

                continue


            # =================================================
            # SADECE AKTİF
            # =================================================

            state = item.get(
                "state"
            )


            if state is not None:

                try:

                    if int(state) != 0:

                        continue

                except Exception:

                    pass


            base_coin = str(

                item.get(
                    "baseCoin",
                    ""
                )

            ).upper()


            # =================================================
            # STOCK / ETF / INDEX
            # =================================================

            bad_words = [

                "STOCK",

                "ETF",

                "INDEX",

                "SPX",

                "SPY",

                "QQQ",

                "NVDA",

                "TSLA",

                "AAPL",

                "MSFT",

                "AMZN",

                "META",

                "GOOG",

                "GOLD",

                "SILVER",

                "XAU",

                "XAG"

            ]


            if any(

                word in base_coin

                for word in bad_words

            ):

                continue


            if any(

                word in symbol

                for word in bad_words

            ):

                continue


            symbols.append(
                symbol
            )


        except Exception:

            continue


    return list(
        dict.fromkeys(
            symbols
        )
    )


# ============================================================
# TOPLU TICKER
# ============================================================

def get_all_tickers():

    url = (
        f"{BASE}/api/v1/contract/ticker"
    )


    data = request_json(url)


    if not data:

        return {}


    raw = data.get(
        "data"
    )


    result = {}


    # ========================================================
    # MEXC bazen dict
    # ========================================================

    if isinstance(
        raw,
        dict
    ):

        rows = [raw]


    # ========================================================
    # Liste gelirse
    # ========================================================

    elif isinstance(
        raw,
        list
    ):

        rows = raw


    else:

        add_debug_error(
            "TICKER DATA FORMAT TANIMSIZ"
        )

        return {}


    for item in rows:

        try:

            symbol = str(

                item.get(
                    "symbol",
                    ""
                )

            ).upper()


            if not symbol.endswith(
                "_USDT"
            ):

                continue


            price = float(

                item.get(
                    "lastPrice",
                    0
                )

            )


            change = float(

                item.get(
                    "riseFallRate",
                    0
                )

            ) * 100


            # MEXC Futures:
            # amount24 kullanılır.
            amount = float(

                item.get(
                    "amount24",
                    item.get(
                        "amount",
                        0
                    )
                )

            )


            if price <= 0:

                continue


            result[symbol] = {

                "price":
                    price,

                "change":
                    change,

                "amount":
                    amount

            }


        except Exception:

            continue


    return result


# ============================================================
# PREFILTER
# ============================================================

def prefilter_symbols(
    symbols,
    tickers
):

    valid = []


    for symbol in symbols:

        t = tickers.get(
            symbol
        )


        if not t:

            continue


        change = t[
            "change"
        ]

        amount = t[
            "amount"
        ]


        # Çok sert düşenleri ele
        if change <= MAX_24H_DROP:

            continue


        valid.append({

            "symbol":
                symbol,

            "change":
                change,

            "amount":
                amount

        })


    if not valid:

        return []


    # ========================================================
    # HACİM
    # ========================================================

    by_volume = sorted(

        valid,

        key=lambda x:
            x["amount"],

        reverse=True

    )


    volume_symbols = {

        x["symbol"]

        for x in by_volume[
            :TOP_VOLUME
        ]

    }


    # ========================================================
    # GAINERS
    # ========================================================

    by_gain = sorted(

        valid,

        key=lambda x:
            x["change"],

        reverse=True

    )


    gain_symbols = {

        x["symbol"]

        for x in by_gain[
            :TOP_GAINERS
        ]

    }


    # ========================================================
    # BİRLEŞTİR
    # ========================================================

    candidates = []


    for x in valid:

        symbol = x[
            "symbol"
        ]


        if (

            symbol in volume_symbols

            or

            symbol in gain_symbols

        ):

            candidates.append(x)


    # ========================================================
    # RANK
    # ========================================================

    max_amount = max(

        x["amount"]

        for x in by_volume

    )


    def rank(x):

        gain_part = (

            min(
                max(
                    x["change"],
                    -5
                ),
                12
            )
            * 0.5

        )


        volume_part = (

            (
                x["amount"]
                /
                max(
                    max_amount,
                    1
                )
            )
            * 100

        )


        return (

            gain_part
            +
            volume_part

        )


    candidates.sort(

        key=rank,

        reverse=True

    )


    candidates = candidates[
        :MAX_DEEP_SCAN
    ]


    return [

        x["symbol"]

        for x in candidates

    ]


# ============================================================
# KLINE
# ============================================================

def get_klines(
    symbol,
    interval,
    limit=100
):

    interval_seconds = {

        "Min15":
            15 * 60,

        "Min60":
            60 * 60,

        "Hour4":
            4 * 60 * 60

    }


    sec = interval_seconds.get(
        interval
    )


    if not sec:

        return None


    now = int(
        time.time()
    )


    start = (

        now
        -
        sec * (limit + 10)

    )


    url = (

        f"{BASE}/api/v1/contract/kline/"

        f"{symbol}"

    )


    params = {

        "interval":
            interval,

        "start":
            start,

        "end":
            now

    }


    data = request_json(

        url,

        params=params

    )


    if not data:

        add_debug_error(

            f"{symbol} {interval}: "
            f"API DATA YOK"

        )

        return None


    raw = data.get(
        "data"
    )


    if not raw:

        add_debug_error(

            f"{symbol} {interval}: "
            f"DATA BOŞ"

        )

        return None


    # ========================================================
    # DICT FORMAT
    # ========================================================

    if isinstance(
        raw,
        dict
    ):

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


        n = min(

            len(times),

            len(opens),

            len(closes),

            len(highs),

            len(lows),

            len(volumes)

        )


        if n < 40:

            add_debug_error(

                f"{symbol} {interval}: "
                f"YETERSİZ MUM={n}"

            )

            return None


        times = times[-limit:]

        opens = opens[-limit:]

        closes = closes[-limit:]

        highs = highs[-limit:]

        lows = lows[-limit:]

        volumes = volumes[-limit:]


        try:

            return {

                "time":
                    [
                        float(x)
                        for x in times
                    ],

                "open":
                    [
                        float(x)
                        for x in opens
                    ],

                "close":
                    [
                        float(x)
                        for x in closes
                    ],

                "high":
                    [
                        float(x)
                        for x in highs
                    ],

                "low":
                    [
                        float(x)
                        for x in lows
                    ],

                "volume":
                    [
                        float(x)
                        for x in volumes
                    ]

            }


        except Exception as e:

            add_debug_error(

                f"{symbol} {interval}: "
                f"NUMERIC ERROR "
                f"{str(e)[:100]}"

            )

            return None


    # ========================================================
    # LIST FORMAT
    # ========================================================

    if isinstance(
        raw,
        list
    ):

        parsed = []


        for row in raw:

            if not isinstance(
                row,
                (list, tuple)
            ):

                continue


            if len(row) < 6:

                continue


            try:

                parsed.append({

                    "time":
                        float(row[0]),

                    "open":
                        float(row[1]),

                    "high":
                        float(row[2]),

                    "low":
                        float(row[3]),

                    "close":
                        float(row[4]),

                    "volume":
                        float(row[5])

                })


            except Exception:

                continue


        if len(parsed) < 40:

            add_debug_error(

                f"{symbol} {interval}: "
                f"LIST MUM={len(parsed)}"

            )

            return None


        parsed = parsed[-limit:]


        return {

            "time":
                [
                    x["time"]
                    for x in parsed
                ],

            "open":
                [
                    x["open"]
                    for x in parsed
                ],

            "close":
                [
                    x["close"]
                    for x in parsed
                ],

            "high":
                [
                    x["high"]
                    for x in parsed
                ],

            "low":
                [
                    x["low"]
                    for x in parsed
                ],

            "volume":
                [
                    x["volume"]
                    for x in parsed
                ]

        }


    return None


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

            +

            result

        )


    return result


# ============================================================
# RSI
# ============================================================

def rsi(
    values,
    period=14
):

    if len(values) < (
        period + 2
    ):

        return None


    gains = []

    losses = []


    for i in range(
        1,
        len(values)
    ):

        change = (

            values[i]
            -
            values[i - 1]

        )


        gains.append(
            max(
                change,
                0
            )
        )


        losses.append(
            max(
                -change,
                0
            )
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

        return 100.0


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
# PERCENT
# ============================================================

def pct_change(
    old,
    new
):

    if old == 0:

        return 0.0


    return (

        (
            new
            -
            old
        )
        /
        old

    ) * 100


# ============================================================
# AVERAGE
# ============================================================

def average(values):

    if not values:

        return 0.0


    return (

        sum(values)
        /
        len(values)

    )


# ============================================================
# RSI PUANI
#
# MAX = 20
# ============================================================

def rsi_score(
    r15,
    r1h,
    r4h,
    c15,
    c1h,
    c4h
):

    score = 0


    # ========================================================
    # 15M
    # ========================================================

    if 48 <= r15 <= 62:

        score += 5

    elif 62 < r15 <= 70:

        score += 4

    elif 70 < r15 <= 76:

        score += 2


    old15 = rsi(
        c15[:-2]
    )


    if (

        old15 is not None
        and
        r15 > old15

    ):

        score += 1


    # ========================================================
    # 1H
    # ========================================================

    if 48 <= r1h <= 60:

        score += 7

    elif 60 < r1h <= 67:

        score += 6

    elif 67 < r1h <= 71:

        score += 3


    old1h = rsi(
        c1h[:-2]
    )


    if (

        old1h is not None
        and
        r1h > old1h

    ):

        score += 1


    # ========================================================
    # 4H
    # ========================================================

    if 43 <= r4h <= 55:

        score += 7

    elif 55 < r4h <= 63:

        score += 6

    elif 63 < r4h <= 68:

        score += 3


    old4h = rsi(
        c4h[:-2]
    )


    if (

        old4h is not None
        and
        r4h > old4h

    ):

        score += 1


    return min(
        20,
        score
    )


# ============================================================
# HACİM
#
# MAX ≈ 15
# ============================================================

def volume_analysis(
    volumes,
    closes
):

    if len(volumes) < 25:

        return 0, 0, False


    avg_volume = average(

        volumes[-21:-1]

    )


    if avg_volume <= 0:

        return 0, 0, False


    current = volumes[-1]

    previous = volumes[-2]

    two_back = volumes[-3]


    ratio = (

        current
        /
        avg_volume

    )


    price_move = pct_change(

        closes[-2],
        closes[-1]

    )


    # ========================================================
    # HACİM YÖNÜ
    # ========================================================

    volume_rising = (

        current > previous
        or
        previous > two_back

    )


    buying = (

        price_move > 0
        and
        volume_rising

    )


    score = 0


    # Erken hacim artışı
    if 1.10 <= ratio < 1.40:

        score += 3


    elif 1.40 <= ratio < 2.0:

        score += 5


    elif 2.0 <= ratio < 3.0:

        score += 6


    elif 3.0 <= ratio < 4.0:

        score += 4


    elif ratio >= 4.0:

        # Çok büyük hacim = pump başlamış olabilir
        score += 2


    if buying:

        score += 5


    # Güçlü yeşil mum + hacim
    if (

        price_move > 0.4
        and
        ratio >= 1.4

    ):

        score += 2


    # Büyük hacim + kırmızı mum
    if (

        ratio >= 2.0
        and
        price_move < -1.0

    ):

        score -= 8


    return (

        ratio,
        max(
            -8,
            min(
                15,
                score
            )
        ),
        buying

    )


# ============================================================
# SATIŞ BASKISI
# ============================================================

def selling_pressure(
    opens,
    closes,
    highs,
    lows
):

    if len(closes) < 6:

        return False


    bad = 0


    for i in range(
        -6,
        0
    ):

        o = opens[i]

        c = closes[i]

        h = highs[i]

        l = lows[i]


        candle_range = (
            h - l
        )


        if candle_range <= 0:

            continue


        body = abs(
            c - o
        )


        upper_wick = (

            h
            -
            max(
                o,
                c
            )

        )


        if (

            upper_wick
            >
            body * 1.8

        ):

            bad += 1


        if c < o:

            drop = pct_change(
                o,
                c
            )


            if drop < -1.5:

                bad += 1


    return bad >= 4


# ============================================================
# FAKE BREAKOUT
# ============================================================

def fake_breakout(
    highs,
    closes
):

    if len(highs) < 30:

        return False


    resistance = max(

        highs[-25:-3]

    )


    previous = closes[-2]

    current = closes[-1]


    if (

        previous > resistance
        and
        current < resistance

    ):

        return True


    if (

        highs[-1]
        >
        resistance * 1.003

        and

        current
        <
        resistance * 0.995

    ):

        return True


    return False


# ============================================================
# RESISTANCE
# ============================================================

def resistance_info(
    highs,
    closes
):

    if len(highs) < 35:

        return (
            None,
            False,
            False,
            0
        )


    resistance = max(

        highs[-30:-3]

    )


    current = closes[-1]


    distance = pct_change(

        resistance,
        current

    )


    breakout = (

        current
        >
        resistance * 1.002

    )


    near = (

        -2.0
        <=
        distance
        <=
        1.5

    )


    return (

        resistance,

        breakout,

        near,

        distance

    )


# ============================================================
# RETEST
# ============================================================

def retest_signal(
    highs,
    lows,
    closes
):

    if len(closes) < 35:

        return False


    resistance = max(

        highs[-35:-7]

    )


    current = closes[-1]

    previous_low = lows[-2]


    if current > resistance:

        if (

            previous_low
            <=
            resistance * 1.015

        ):

            return True


    return False


# ============================================================
# PUMP ZATEN BAŞLAMIŞ MI?
# ============================================================

def pump_already(
    c15,
    c1h,
    ema20_15,
    ema20_1h,
    r15,
    r1h,
    r4h
):

    move6 = pct_change(

        c15[-7],
        c15[-1]

    )


    move12 = pct_change(

        c15[-13],
        c15[-1]

    )


    move1h = pct_change(

        c1h[-5],
        c1h[-1]

    )


    # ========================================================
    # HIZLI PUMP
    # ========================================================

    if move6 >= 8:

        return True


    if move12 >= 14:

        return True


    if move1h >= 9:

        return True


    # ========================================================
    # RSI ÇOK ISINMIŞ
    # ========================================================

    if r15 >= 80:

        return True


    if r1h >= 72:

        return True


    if r4h >= 70:

        return True


    # ========================================================
    # EMA'DAN ÇOK UZAK
    # ========================================================

    if ema20_15:

        distance15 = abs(

            pct_change(
                ema20_15,
                c15[-1]
            )

        )


        if distance15 >= 4.0:

            return True


    if ema20_1h:

        distance1h = abs(

            pct_change(
                ema20_1h,
                c1h[-1]
            )

        )


        if distance1h >= 6.0:

            return True


    return False


# ============================================================
# PUMP ÖNCESİ SCORE
#
# MAX = 10
# ============================================================

def pre_pump_score(
    c15,
    c1h,
    c4h,
    r15,
    r1h,
    r4h
):

    score = 0


    move15 = pct_change(

        c15[-5],
        c15[-1]

    )


    move1h = pct_change(

        c1h[-4],
        c1h[-1]

    )


    move4h = pct_change(

        c4h[-3],
        c4h[-1]

    )


    # ========================================================
    # 15M
    # ========================================================

    if 0.2 <= move15 <= 2.5:

        score += 3


    elif 2.5 < move15 <= 4:

        score += 1


    # ========================================================
    # 1H
    # ========================================================

    if 0.3 <= move1h <= 4:

        score += 3


    elif 4 < move1h <= 6:

        score += 1


    # ========================================================
    # 4H
    # ========================================================

    if 0 <= move4h <= 6:

        score += 2


    # ========================================================
    # RSI ERKEN DÖNÜŞ
    # ========================================================

    if 45 <= r4h <= 58:

        score += 1


    if 48 <= r1h <= 65:

        score += 1


    return (

        min(
            10,
            score
        ),

        move15,

        move1h,

        move4h

    )


# ============================================================
# BTC
#
# MAX = 5
# ============================================================

def btc_score(
    btc_changes
):

    c15 = btc_changes.get(
        "Min15",
        0
    )

    c1h = btc_changes.get(
        "Min60",
        0
    )

    c4h = btc_changes.get(
        "Hour4",
        0
    )


    score = 0


    if c15 > 0:

        score += 1


    if c1h > 0:

        score += 1


    if c4h > 0:

        score += 1


    if c1h > 0.20:

        score += 1


    if c4h > 0.50:

        score += 1


    if c15 < -0.30:

        score -= 1


    if c1h < -0.70:

        score -= 2


    if c4h < -1.20:

        score -= 2


    return max(
        -5,
        min(
            5,
            score
        )
    )


# ============================================================
# BTC DATA
# ============================================================

def get_btc_data():

    result = {}


    for interval in [

        "Min15",

        "Min60",

        "Hour4"

    ]:

        data = get_klines(

            "BTC_USDT",

            interval,

            60

        )


        if not data:

            result[interval] = 0

            continue


        closes = data[
            "close"
        ]


        if len(closes) < 10:

            result[interval] = 0

            continue


        result[interval] = pct_change(

            closes[-5],
            closes[-1]

        )


    positive = sum(

        1

        for x in result.values()

        if x > 0

    )


    negative = sum(

        1

        for x in result.values()

        if x < 0

    )


    if (

        negative >= 2

        and

        (

            result.get(
                "Min60",
                0
            ) < -0.50

            or

            result.get(
                "Hour4",
                0
            ) < -1.0

        )

    ):

        state = "BEARISH"


    elif positive >= 2:

        state = "BULLISH"


    else:

        state = "NEUTRAL"


    return (

        state,

        result

    )


# ============================================================
# ANALYZE
# ============================================================

def analyze_coin(
    symbol,
    btc_state,
    btc_changes
):

    try:

        # ====================================================
        # 15M
        # ====================================================

        d15 = get_klines(

            symbol,

            "Min15",

            KLINE_LIMIT

        )


        if not d15:

            return None, "DATA15"


        # ====================================================
        # 1H
        # ====================================================

        d1h = get_klines(

            symbol,

            "Min60",

            KLINE_LIMIT

        )


        if not d1h:

            return None, "DATA1H"


        # ====================================================
        # 4H
        # ====================================================

        d4h = get_klines(

            symbol,

            "Hour4",

            KLINE_LIMIT

        )


        if not d4h:

            return None, "DATA4H"


        # ====================================================
        # ARRAYS
        # ====================================================

        c15 = d15["close"]

        o15 = d15["open"]

        h15 = d15["high"]

        l15 = d15["low"]

        v15 = d15["volume"]


        c1h = d1h["close"]

        h1h = d1h["high"]

        l1h = d1h["low"]


        c4h = d4h["close"]


        # ====================================================
        # RSI
        # ====================================================

        r15 = rsi(c15)

        r1h = rsi(c1h)

        r4h = rsi(c4h)


        if not all([

            r15 is not None,

            r1h is not None,

            r4h is not None

        ]):

            return None, "RSI"


        # ====================================================
        # AŞIRI RSI
        # ====================================================

        if r15 > 82:

            return None, "RSI"


        if r1h > 76:

            return None, "RSI"


        if r4h > 73:

            return None, "RSI"


        # ====================================================
        # EMA
        # ====================================================

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

        ema50_4h = ema(
            c4h,
            50
        )


        if not all([

            ema20_15,

            ema50_15,

            ema20_1h,

            ema50_1h,

            ema20_4h,

            ema50_4h

        ]):

            return None, "DATA4H"


        # ====================================================
        # PUMP ZATEN BAŞLADI MI?
        # ====================================================

        if pump_already(

            c15,

            c1h,

            ema20_15,

            ema20_1h,

            r15,

            r1h,

            r4h

        ):

            return None, "OVEREXTENDED"


        # ====================================================
        # HACİM
        # ====================================================

        volume_ratio, volume_points, buying = (

            volume_analysis(

                v15,

                c15

            )

        )


        if volume_ratio < 0.70:

            return None, "VOLUME"


        # ====================================================
        # SATIŞ BASKISI
        # ====================================================

        if selling_pressure(

            o15,

            c15,

            h15,

            l15

        ):

            return None, "FAKE"


        # ====================================================
        # FAKE BREAKOUT
        # ====================================================

        if fake_breakout(

            h15,

            c15

        ):

            return None, "FAKE"


        # ====================================================
        # RESISTANCE
        # ====================================================

        resistance, breakout, near, distance = (

            resistance_info(

                h1h,

                c1h

            )

        )


        if resistance is None:

            return None, "RESISTANCE"


        # ====================================================
        # BREAKOUT ÇOK UZAKSA
        #
        # ÖNCE PUMP YAPMIŞ OLMA İHTİMALİ
        # ====================================================

        if breakout and distance > 2.5:

            return None, "OVEREXTENDED"


        # ====================================================
        # RETEST
        # ====================================================

        retest = retest_signal(

            h1h,

            l1h,

            c1h

        )


        # ====================================================
        # TREND SCORE
        #
        # MAX = 20
        # ====================================================

        trend_points = 0


        # 15M
        if c15[-1] > ema20_15:

            trend_points += 2


        if ema20_15 > ema50_15:

            trend_points += 2


        # 1H
        if c1h[-1] > ema20_1h:

            trend_points += 4


        if ema20_1h > ema50_1h:

            trend_points += 5


        # 4H
        if c4h[-1] > ema20_4h:

            trend_points += 3


        if ema20_4h > ema50_4h:

            trend_points += 4


        trend_points = min(
            20,
            trend_points
        )


        # ====================================================
        # RSI
        # ====================================================

        rsi_points = rsi_score(

            r15,

            r1h,

            r4h,

            c15,

            c1h,

            c4h

        )


        # ====================================================
        # PRE-PUMP
        # ====================================================

        pre_score, move15, move1h, move4h = (

            pre_pump_score(

                c15,

                c1h,

                c4h,

                r15,

                r1h,

                r4h

            )

        )


        # ====================================================
        # STRUCTURE
        #
        # MAX = 15
        # ====================================================

        structure_points = 0


        if near:

            structure_points += 5


        if breakout:

            structure_points += 4


        if retest:

            structure_points += 6


        structure_points = min(
            15,
            structure_points
        )


        # ====================================================
        # MOMENTUM
        #
        # MAX = 10
        # ====================================================

        momentum_points = 0


        if (

            0 < move15 <= 2.5

        ):

            momentum_points += 3


        if (

            0 < move1h <= 4

        ):

            momentum_points += 3


        if (

            0 < move4h <= 6

        ):

            momentum_points += 2


        if (

            move15 > 0

            and

            move1h > 0

        ):

            momentum_points += 2


        # ====================================================
        # BTC
        # MAX = 5
        # ====================================================

        bscore = btc_score(

            btc_changes

        )


        # ====================================================
        # SCORE
        #
        # TREND       20
        # RSI         20
        # VOLUME      15
        # PRE-PUMP    10
        # STRUCTURE   15
        # MOMENTUM    10
        # BTC          5
        #
        # TOPLAM      95
        #
        # BONUS        5
        # ====================================================

        score = (

            trend_points

            +

            rsi_points

            +

            volume_points

            +

            pre_score

            +

            structure_points

            +

            momentum_points

            +

            bscore

        )


        # ====================================================
        # ERKEN ALIM BONUSU
        # ====================================================

        if (

            48 <= r15 <= 68

            and

            48 <= r1h <= 68

            and

            r4h <= 65

        ):

            score += 5


        # ====================================================
        # NEGATİF MOMENTUM CEZASI
        # ====================================================

        if move15 < -1.5:

            score -= 5


        if move1h < -3:

            score -= 5


        if move4h < -5:

            score -= 5


        # ====================================================
        # BTC BEARISH
        # ====================================================

        if btc_state == "BEARISH":

            score -= 8


        # ====================================================
        # ÇOK SICAK RSI CEZASI
        # ====================================================

        if r15 > 75:

            score -= 5


        if r1h > 68:

            score -= 3


        if r4h > 65:

            score -= 3


        # ====================================================
        # NORMALİZE
        # ====================================================

        score = max(

            0,

            min(

                100,

                score

            )

        )


        # ====================================================
        # MIN SCORE
        # ====================================================

        if score < MIN_SCORE:

            return None, "QUALITY"


        # ====================================================
        # ENTRY
        # ====================================================

        entry = c15[-1]


        # ====================================================
        # STOP
        # ====================================================

        swing_low = min(

            l15[-10:]

        )


        stop = (

            swing_low
            *
            0.997

        )


        risk_percent = abs(

            pct_change(

                stop,
                entry

            )

        )


        if risk_percent < 1:

            stop = (

                entry
                *
                0.985

            )


        elif risk_percent > 4:

            stop = (

                entry
                *
                0.975

            )


        risk = (

            entry
            -
            stop

        )


        if risk <= 0:

            return None, "QUALITY"


        # ====================================================
        # TP
        # ====================================================

        tp1 = (

            entry
            +
            risk * 1.5

        )


        tp2 = (

            entry
            +
            risk * 2.3

        )


        tp3 = (

            entry
            +
            risk * 3.2

        )


        # ====================================================
        # RESULT
        # ====================================================

        result = {

            "symbol":
                symbol,

            "score":
                round(
                    score,
                    1
                ),

            "entry":
                entry,

            "stop":
                stop,

            "tp1":
                tp1,

            "tp2":
                tp2,

            "tp3":
                tp3,

            "rsi15":
                r15,

            "rsi1h":
                r1h,

            "rsi4h":
                r4h,

            "volume":
                volume_ratio,

            "btc":
                btc_state,

            "btc_score":
                bscore,

            "move15":
                move15,

            "move1h":
                move1h,

            "move4h":
                move4h,

            "resistance":
                resistance,

            "distance":
                distance,

            "breakout":
                breakout,

            "retest":
                retest,

            "buying":
                buying,

            "trend_points":
                trend_points,

            "rsi_points":
                rsi_points,

            "volume_points":
                volume_points,

            "pre_score":
                pre_score,

            "structure_points":
                structure_points,

            "momentum_points":
                momentum_points

        }


        return result, "SIGNAL"


    except Exception as e:

        add_debug_error(

            f"{symbol}: "
            f"{str(e)[:180]}"

        )

        return None, "ERROR"


# ============================================================
# TELEGRAM FORMAT
# ============================================================

def format_signal(x):

    symbol = x[
        "symbol"
    ].replace(
        "_USDT",
        "/USDT"
    )


    if x["buying"]:

        volume_direction = (
            "🟢 ALIM BASKISI"
        )

    else:

        volume_direction = (
            "🟡 HACİM GELİŞİYOR"
        )


    return f"""
🚀 <b>PUMP RADAR 25.0</b>

🟢 <b>PUMP ÖNCESİ LONG</b>

<b>{symbol}</b>

⭐ Güç: <b>{x['score']}/100</b>

━━━━━━━━━━━━━━

🎯 GİRİŞ
<b>{x['entry']:.8g}</b>

🛑 STOP
<b>{x['stop']:.8g}</b>

🥇 TP1
<b>{x['tp1']:.8g}</b>

🥈 TP2
<b>{x['tp2']:.8g}</b>

🥉 TP3
<b>{x['tp3']:.8g}</b>

━━━━━━━━━━━━━━

📊 <b>RSI</b>

15M: <b>{x['rsi15']:.1f}</b>
1H : <b>{x['rsi1h']:.1f}</b>
4H : <b>{x['rsi4h']:.1f}</b>

🔥 Hacim:
<b>{x['volume']:.2f}x</b>

Hacim yönü:
<b>{volume_direction}</b>

━━━━━━━━━━━━━━

📈 <b>MOMENTUM</b>

15M: <b>{x['move15']:+.2f}%</b>
1H : <b>{x['move1h']:+.2f}%</b>
4H : <b>{x['move4h']:+.2f}%</b>

━━━━━━━━━━━━━━

📐 <b>YAPI</b>

Breakout:
<b>{'EVET' if x['breakout'] else 'HAYIR'}</b>

Retest:
<b>{'EVET' if x['retest'] else 'HAYIR'}</b>

Direnç:
<b>{x['resistance']:.8g}</b>

Mesafe:
<b>{x['distance']:+.2f}%</b>

━━━━━━━━━━━━━━

📊 <b>SCORE DAĞILIMI</b>

Trend: <b>{x['trend_points']}/20</b>
RSI: <b>{x['rsi_points']}/20</b>
Hacim: <b>{x['volume_points']}/15</b>
Pre-Pump: <b>{x['pre_score']}/10</b>
Yapı: <b>{x['structure_points']}/15</b>
Momentum: <b>{x['momentum_points']}/10</b>
BTC: <b>{x['btc_score']}/5</b>

━━━━━━━━━━━━━━

₿ BTC:
<b>{x['btc']}</b>

⚠️ Otomatik teknik taramadır.
"""


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print("=" * 70)
    print("🚀 MEXC PUMP RADAR 25.0")
    print("=" * 70)
    print("")


    # ========================================================
    # FUTURES
    # ========================================================

    symbols = get_futures_symbols()


    if not symbols:

        print(
            "❌ Futures listesi alınamadı."
        )

        return


    stats["TOTAL"] = len(
        symbols
    )


    print(
        f"📊 Toplam Futures: "
        f"{len(symbols)}"
    )


    # ========================================================
    # TICKER
    # ========================================================

    print("")
    print(
        "⚡ Toplu ticker alınıyor..."
    )


    tickers = get_all_tickers()


    print(
        f"📡 Ticker: "
        f"{len(tickers)}"
    )


    if not tickers:

        print(
            "❌ Ticker alınamadı."
        )

        return


    # ========================================================
    # PREFILTER
    # ========================================================

    candidates = prefilter_symbols(

        symbols,

        tickers

    )


    stats["PREFILTER"] = len(
        candidates
    )


    print("")
    print(
        f"🎯 Derin tarama: "
        f"{len(candidates)} coin"
    )


    # ========================================================
    # BTC
    # ========================================================

    print("")
    print(
        "₿ BTC analiz ediliyor..."
    )


    btc_state, btc_changes = (
        get_btc_data()
    )


    print(
        f"₿ BTC: {btc_state}"
    )


    print(
        f"   15M: "
        f"{btc_changes.get('Min15', 0):+.2f}%"
    )


    print(
        f"   1H : "
        f"{btc_changes.get('Min60', 0):+.2f}%"
    )


    print(
        f"   4H : "
        f"{btc_changes.get('Hour4', 0):+.2f}%"
    )


    # ========================================================
    # HISTORY
    # ========================================================

    history = load_history()

    now = time.time()


    # ========================================================
    # DEEP SCAN
    # ========================================================

    print("")
    print(
        "🔍 Derin tarama başlıyor..."
    )
    print("")


    results = []


    with ThreadPoolExecutor(

        max_workers=MAX_WORKERS

    ) as executor:


        futures = {

            executor.submit(

                analyze_coin,

                symbol,

                btc_state,

                btc_changes

            ):
                symbol

            for symbol in candidates

        }


        for future in as_completed(
            futures
        ):

            symbol = futures[
                future
            ]


            try:

                result, reason = (
                    future.result()
                )


            except Exception as e:

                result = None

                reason = "ERROR"


                add_debug_error(

                    f"{symbol}: "
                    f"FUTURE ERROR "
                    f"{str(e)[:120]}"

                )


            with stats_lock:

                if reason in stats:

                    stats[reason] += 1


            if result:

                old = history.get(
                    symbol
                )


                # =================================================
                # COOLDOWN
                # =================================================

                if old:

                    elapsed = (

                        now
                        -
                        old.get(
                            "time",
                            0
                        )

                    )


                    if elapsed < (

                        COOLDOWN_HOURS
                        *
                        3600

                    ):

                        continue


                results.append(
                    result
                )


    # ========================================================
    # SORT
    # ========================================================

    results.sort(

        key=lambda x:
            x["score"],

        reverse=True

    )


    # ========================================================
    # TELEGRAM
    # ========================================================

    sent = 0


    for result in results:

        if sent >= MAX_TELEGRAM:

            break


        ok = send_telegram(

            format_signal(
                result
            )

        )


        if ok:

            symbol = result[
                "symbol"
            ]


            history[symbol] = {

                "time":
                    now,

                "score":
                    result["score"],

                "entry":
                    result["entry"],

                "stop":
                    result["stop"]

            }


            sent += 1


            print(

                f"📨 Telegram: "
                f"{symbol} "
                f"{result['score']}/100"

            )


    save_history(
        history
    )


    # ========================================================
    # RAPOR
    # ========================================================

    print("")
    print("=" * 70)
    print("📊 25.0 ELEME RAPORU")
    print("=" * 70)


    print(
        f"Toplam Futures     : "
        f"{stats['TOTAL']}"
    )


    print(
        f"Ön taramadan geçen : "
        f"{stats['PREFILTER']}"
    )


    print(
        f"15M veri hatası    : "
        f"{stats['DATA15']}"
    )


    print(
        f"1H veri hatası     : "
        f"{stats['DATA1H']}"
    )


    print(
        f"4H veri hatası     : "
        f"{stats['DATA4H']}"
    )


    print(
        f"RSI                : "
        f"{stats['RSI']}"
    )


    print(
        f"Hacim              : "
        f"{stats['VOLUME']}"
    )


    print(
        f"Direnç             : "
        f"{stats['RESISTANCE']}"
    )


    print(
        f"Fake breakout      : "
        f"{stats['FAKE']}"
    )


    print(
        f"Aşırı yükselmiş    : "
        f"{stats['OVEREXTENDED']}"
    )


    print(
        f"BTC filtresi       : "
        f"{stats['BTC']}"
    )


    print(
        f"Kalite düşük       : "
        f"{stats['QUALITY']}"
    )


    print(
        f"Teknik hata        : "
        f"{stats['ERROR']}"
    )


    print(
        f"Uygun aday         : "
        f"{len(results)}"
    )


    print(
        f"Telegram gönderim  : "
        f"{sent}"
    )


    # ========================================================
    # TOP 15
    # ========================================================

    print("")
    print("=" * 70)
    print("🔥 EN GÜÇLÜ ADAYLAR")
    print("=" * 70)


    for x in results[:15]:

        print(

            f"{x['symbol']:18} "

            f"{x['score']:5.1f}/100 "

            f"VOL {x['volume']:5.2f}x "

            f"RSI1H {x['rsi1h']:5.1f} "

            f"RSI4H {x['rsi4h']:5.1f} "

            f"15M {x['move15']:+5.2f}% "

            f"1H {x['move1h']:+5.2f}%"

        )


    # ========================================================
    # DEBUG
    # ========================================================

    print("")
    print("=" * 70)
    print("🛠 API DEBUG")
    print("=" * 70)


    if debug_errors:

        for error in debug_errors:

            print(
                "⚠️",
                error
            )


    else:

        print(
            "✅ API hatası yok."
        )


    print("")
    print("=" * 70)
    print("✅ RADAR 25.0 TAMAMLANDI")
    print("=" * 70)
    print("")


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
