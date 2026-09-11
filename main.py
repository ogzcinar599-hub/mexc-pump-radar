import os
import json
import time
import threading
import requests

from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PUMP RADAR 24.0
#
# AMAÇ:
# PUMP BAŞLAMADAN ÖNCE YAKALAMAK
#
# 728 FUTURES
#       ↓
# TOPLU TICKER
#       ↓
# HIZLI ÖN ELEME
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
#       ↓
# QUALITY SCORE
#       ↓
# EN İYİ LONG'LAR
#       ↓
# TELEGRAM
#
# ============================================================


# ============================================================
# AYARLAR
# ============================================================

BASE = "https://api.mexc.com"

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID"
)

HISTORY_FILE = "signal_history.json"


# ============================================================
# RATE LIMIT KORUMASI
# ============================================================

MAX_WORKERS = 3

REQUEST_TIMEOUT = 12

RETRIES = 4

RETRY_BASE = 2.0

REQUEST_GAP = 0.15


# ============================================================
# RADAR AYARLARI
# ============================================================

KLINE_LIMIT = 100

MAX_DEEP_SCAN = 160

MAX_TELEGRAM = 8

MIN_SCORE = 55

COOLDOWN_HOURS = 6


# ============================================================
# PREFILTER
# ============================================================

TOP_VOLUME = 120

TOP_GAINERS = 100

MAX_24H_DROP = -20.0


# ============================================================
# GLOBAL
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
# DEBUG
# ============================================================

def add_debug_error(text):

    with debug_lock:

        if text in debug_errors:
            return

        if len(debug_errors) < 12:

            debug_errors.append(text)


# ============================================================
# HTTP
# ============================================================

def request_json(url, params=None):

    headers = {

        "User-Agent":
            "Mozilla/5.0 MEXC-PUMP-RADAR/24.0",

        "Accept":
            "application/json"

    }


    last_error = None


    for attempt in range(RETRIES):

        try:

            r = requests.get(

                url,

                params=params,

                headers=headers,

                timeout=REQUEST_TIMEOUT

            )


            # ------------------------------------------------
            # RATE LIMIT
            # ------------------------------------------------

            if r.status_code == 429:

                last_error = (
                    f"HTTP 429 RATE LIMIT: {url}"
                )

                time.sleep(
                    RETRY_BASE * (attempt + 1)
                )

                continue


            # ------------------------------------------------
            # SERVER ERROR
            # ------------------------------------------------

            if r.status_code >= 500:

                last_error = (
                    f"HTTP {r.status_code}: {url}"
                )

                time.sleep(
                    RETRY_BASE * (attempt + 1)
                )

                continue


            # ------------------------------------------------
            # HTTP ERROR
            # ------------------------------------------------

            if r.status_code != 200:

                last_error = (
                    f"HTTP {r.status_code}: "
                    f"{r.text[:180]}"
                )

                break


            data = r.json()


            if not isinstance(data, dict):

                last_error = (
                    f"JSON FORMAT ERROR: {url}"
                )

                break


            # ------------------------------------------------
            # MEXC ERROR
            # ------------------------------------------------

            if data.get("success") is False:

                code = data.get("code")

                message = data.get("message")


                if str(code) == "510":

                    last_error = (
                        f"MEXC 510 RATE LIMIT: {url}"
                    )

                    time.sleep(
                        RETRY_BASE * (attempt + 1)
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
                f"TIMEOUT: {url}"
            )

            time.sleep(
                RETRY_BASE * (attempt + 1)
            )


        except requests.exceptions.RequestException as e:

            last_error = (
                f"REQUEST ERROR: "
                f"{str(e)[:150]}"
            )

            time.sleep(
                RETRY_BASE * (attempt + 1)
            )


        except Exception as e:

            last_error = (
                f"UNKNOWN ERROR: "
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


    except:

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

        add_debug_error(
            f"HISTORY ERROR: {str(e)[:120]}"
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


        return r.status_code == 200


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


    rows = data.get("data")


    if not isinstance(
        rows,
        list
    ):

        add_debug_error(
            "CONTRACT DETAIL LIST DEĞİL"
        )

        return []


    symbols = []


    for item in rows:

        try:

            symbol = item.get(
                "symbol"
            )


            if not symbol:
                continue


            if not symbol.endswith(
                "_USDT"
            ):

                continue


            state = item.get(
                "state"
            )


            if state is not None:

                try:

                    if int(state) != 0:

                        continue

                except:

                    pass


            base = symbol.replace(
                "_USDT",
                ""
            ).upper()


            # TOKENIZED STOCK / ETF / INDEX
            bad_words = [

                "STOCK",

                "ETF",

                "INDEX"

            ]


            if any(

                word in base

                for word in bad_words

            ):

                continue


            symbols.append(
                symbol
            )


        except:

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


    rows = data.get("data")


    if not isinstance(
        rows,
        list
    ):

        add_debug_error(
            "TICKER DATA LIST DEĞİL"
        )

        return {}


    result = {}


    for item in rows:

        try:

            symbol = item.get(
                "symbol"
            )


            if not symbol:
                continue


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


            amount = float(
                item.get(
                    "amount",
                    0
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


        except:

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


        change = t["change"]

        amount = t["amount"]


        # Çok sert düşenleri çıkar
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


    # --------------------------------------------------------
    # HACME GÖRE
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # YÜKSELENLERE GÖRE
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # BİRLEŞTİR
    # --------------------------------------------------------

    candidates = []


    for x in valid:

        symbol = x["symbol"]


        if (

            symbol in volume_symbols

            or

            symbol in gain_symbols

        ):

            candidates.append(x)


    # --------------------------------------------------------
    # ÖNCE MAKUL HAREKETLİLER
    # --------------------------------------------------------

    candidates.sort(

        key=lambda x:

            (

                min(
                    max(
                        x["change"],
                        -5
                    ),
                    12
                )
                * 0.5

                +

                (
                    x["amount"]
                    /
                    max(
                        by_volume[0]["amount"],
                        1
                    )
                )
                * 100

            ),

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


    sec = interval_seconds[
        interval
    ]


    now = int(
        time.time()
    )


    start = (

        now

        -

        sec * (limit + 10)

    )


    end = now


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
            end

    }


    data = request_json(

        url,

        params=params

    )


    if not data:

        return None


    raw = data.get(
        "data"
    )


    if not raw:

        add_debug_error(

            f"{symbol} {interval}: "
            f"DATA YOK"

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

        if len(raw) < 40:

            return None


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


            except:

                continue


        if len(parsed) < 40:

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

    if len(values) < period + 2:

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

        return 0


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

        return 0


    return (

        sum(values)
        /
        len(values)

    )


# ============================================================
# RSI SCORE
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

    if 45 <= r15 <= 60:

        score += 7

    elif 60 < r15 <= 70:

        score += 6

    elif 70 < r15 <= 75:

        score += 2


    # RSI yükseliyor mu?
    if len(c15) >= 4:

        old_rsi = rsi(
            c15[:-2]
        )


        if old_rsi is not None:

            if r15 > old_rsi:

                score += 6


    # ========================================================
    # 1H
    # ========================================================

    if 45 <= r1h <= 60:

        score += 7

    elif 60 < r1h <= 68:

        score += 6

    elif 68 < r1h <= 73:

        score += 2


    if len(c1h) >= 4:

        old_rsi = rsi(
            c1h[:-2]
        )


        if old_rsi is not None:

            if r1h > old_rsi:

                score += 5


    # ========================================================
    # 4H
    # ========================================================

    if 42 <= r4h <= 55:

        score += 8

    elif 55 < r4h <= 63:

        score += 6

    elif 63 < r4h <= 68:

        score += 2


    if len(c4h) >= 4:

        old_rsi = rsi(
            c4h[:-2]
        )


        if old_rsi is not None:

            if r4h > old_rsi:

                score += 5


    # Aşırı RSI
    if r15 > 80:

        score -= 10


    if r1h > 78:

        score -= 8


    if r4h > 72:

        score -= 6


    return score


# ============================================================
# HACİM
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


    # --------------------------------------------------------
    # HACİM YÖNÜ
    # --------------------------------------------------------

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


    # Hacim henüz patlamamış ama artıyor
    if ratio >= 1.15:

        score += 4


    if ratio >= 1.40:

        score += 5


    if ratio >= 1.80:

        score += 6


    if ratio >= 2.50:

        score += 5


    if ratio >= 4.0:

        score += 3


    if buying:

        score += 9


    # Yeşil mum + yüksek hacim
    if (

        price_move > 0.5

        and

        ratio >= 1.5

    ):

        score += 5


    # Büyük hacim + düşüş
    if (

        ratio >= 2

        and

        price_move < -1

    ):

        score -= 12


    return (

        ratio,

        score,

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
            max(o, c)

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


    # Üstüne çıkıp geri düştü
    if (

        previous > resistance

        and

        current < resistance

    ):

        return True


    # Uzun fake fitil
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

        return None, False, False, 0


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

        -2.5
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


    if (

        current
        >
        resistance

    ):

        if (

            previous_low
            <=
            resistance * 1.015

        ):

            return True


    return False


# ============================================================
# PUMP ZATEN YAPILMIŞ MI?
# ============================================================

def pump_already(
    c15,
    c1h
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


    # --------------------------------------------------------
    # Çok hızlı pump
    # --------------------------------------------------------

    if move6 >= 10:

        return True


    if move12 >= 18:

        return True


    if move1h >= 12:

        return True


    return False


# ============================================================
# PUMP ÖNCESİ SCORE
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


    # --------------------------------------------------------
    # 15M
    # --------------------------------------------------------

    if 0.2 <= move15 <= 3:

        score += 7


    elif move15 > 3:

        score += 3


    # --------------------------------------------------------
    # 1H
    # --------------------------------------------------------

    if 0.3 <= move1h <= 5:

        score += 8


    elif move1h > 5:

        score += 3


    # --------------------------------------------------------
    # 4H
    # --------------------------------------------------------

    if move4h > 0:

        score += 6


    # --------------------------------------------------------
    # Erken RSI dönüşü
    # --------------------------------------------------------

    if 45 <= r4h <= 58:

        score += 7


    if 48 <= r1h <= 65:

        score += 5


    if 48 <= r15 <= 70:

        score += 4


    return (

        score,

        move15,

        move1h,

        move4h

    )


# ============================================================
# BTC SCORE
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


    # ========================================================
    # GÜÇLÜ BULLISH
    # ========================================================

    if c15 > 0.10:

        score += 3


    if c1h > 0.20:

        score += 4


    if c4h > 0.30:

        score += 4


    # ========================================================
    # HAFİF POZİTİF
    # ========================================================

    if c15 > 0:

        score += 1


    if c1h > 0:

        score += 1


    if c4h > 0:

        score += 1


    # ========================================================
    # HAFİF NEGATİF
    # ========================================================

    if c15 < -0.20:

        score -= 2


    if c1h < -0.50:

        score -= 3


    if c4h < -1.0:

        score -= 4


    return max(
        -8,
        min(
            12,
            score
        )
    )


# ============================================================
# BTC STATE
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


        closes = data["close"]


        if len(closes) < 10:

            result[interval] = 0

            continue


        result[interval] = pct_change(

            closes[-5],

            closes[-1]

        )


        time.sleep(
            0.15
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


    # Sadece güçlü negatiflikte BEARISH
    if (

        negative >= 2

        and

        (
            result.get(
                "Min60",
                0
            )
            <
            -0.50

            or

            result.get(
                "Hour4",
                0
            )
            <
            -1.0
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
# ANALYZE COIN
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


        time.sleep(
            REQUEST_GAP
        )


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


        time.sleep(
            REQUEST_GAP
        )


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


        if r1h > 80:

            return None, "RSI"


        if r4h > 75:

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
        # HACİM
        # ====================================================

        volume_ratio, volume_points, buying = (

            volume_analysis(

                v15,

                c15

            )

        )


        # Artık düşük hacmi direkt eleme
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
        # PUMP ZATEN YAPILDI MI?
        # ====================================================

        if pump_already(

            c15,

            c1h

        ):

            return None, "OVEREXTENDED"


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
        # SCORE
        # ====================================================

        score = 0


        # ====================================================
        # TREND
        # ====================================================

        trend_points = 0


        # 15M
        if c15[-1] > ema20_15:

            trend_points += 4


        if ema20_15 > ema50_15:

            trend_points += 4


        # 1H
        if c1h[-1] > ema20_1h:

            trend_points += 7


        if ema20_1h > ema50_1h:

            trend_points += 8


        # 4H
        if c4h[-1] > ema20_4h:

            trend_points += 5


        if ema20_4h > ema50_4h:

            trend_points += 7


        score += trend_points


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


        score += rsi_points


        # ====================================================
        # HACİM
        # ====================================================

        score += volume_points


        # ====================================================
        # PUMP ÖNCESİ
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


        score += pre_score


        # ====================================================
        # HACİM YÖNÜ
        # ====================================================

        if buying:

            score += 6


        # ====================================================
        # BREAKOUT
        # ====================================================

        breakout_points = 0


        if breakout:

            breakout_points += 10


        elif near:

            breakout_points += 7


        # ====================================================
        # RETEST
        # ====================================================

        retest = retest_signal(

            h1h,

            l1h,

            c1h

        )


        if retest:

            breakout_points += 12


        score += breakout_points


        # ====================================================
        # BTC
        # ====================================================

        bscore = btc_score(

            btc_changes

        )


        score += bscore


        # ====================================================
        # BTC GÜÇLÜ BEARISH
        # ====================================================

        if btc_state == "BEARISH":

            # Tamamen yasaklamıyoruz
            # ama ciddi puan kırıyoruz
            score -= 8


        # ====================================================
        # MOMENTUM UYUMLULUĞU
        # ====================================================

        if (

            move15 > 0

            and

            move1h > 0

        ):

            score += 7


        elif (

            move15 > 0

            and

            move1h > -0.5

        ):

            score += 3


        # ====================================================
        # NEGATİF MOMENTUM
        # ====================================================

        if move15 < -2:

            score -= 8


        if move1h < -3:

            score -= 8


        if move4h < -5:

            score -= 8


        # ====================================================
        # NORMALİZASYON
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


        # Stop çok yakın
        if risk_percent < 1:

            stop = (

                entry
                *
                0.985

            )


        # Stop çok uzak
        elif risk_percent > 4:

            stop = (

                entry
                *
                0.975

            )


        # ====================================================
        # TP
        # ====================================================

        risk = (

            entry
            -
            stop

        )


        if risk <= 0:

            return None, "QUALITY"


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

            "breakout_points":
                breakout_points

        }


        return result, "SIGNAL"


    except Exception as e:

        add_debug_error(

            f"{symbol}: "
            f"{str(e)[:180]}"

        )

        return None, "ERROR"


# ============================================================
# TELEGRAM
# ============================================================

def format_signal(x):

    symbol = x[
        "symbol"
    ].replace(
        "_USDT",
        "/USDT"
    )


    if x["buying"]:

        volume_direction = "🟢 ALIM"

    else:

        volume_direction = "🟡 GELİŞİYOR"


    return f"""
🚀 <b>PUMP RADAR 24.0</b>

🟢 <b>LONG ADAYI</b>

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

━━━━━━━━━━━━━━

₿ BTC:
<b>{x['btc']}</b>

━━━━━━━━━━━━━━

⚠️ Otomatik teknik taramadır.
"""


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print("=" * 65)
    print("🚀 MEXC PUMP RADAR 24.0")
    print("=" * 65)
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
    # REPORT
    # ========================================================

    print("")
    print("=" * 65)
    print("📊 24.0 ELEME RAPORU")
    print("=" * 65)


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
    # TOP ADAYLAR
    # ========================================================

    print("")
    print("=" * 65)
    print("🔥 EN GÜÇLÜ ADAYLAR")
    print("=" * 65)


    for x in results[:15]:

        print(

            f"{x['symbol']:18} "

            f"{x['score']:5.1f}/100 "

            f"VOL {x['volume']:5.2f}x "

            f"RSI4H {x['rsi4h']:5.1f} "

            f"15M {x['move15']:+5.2f}% "

            f"1H {x['move1h']:+5.2f}%"

        )


    # ========================================================
    # DEBUG
    # ========================================================

    print("")
    print("=" * 65)
    print("🛠 API DEBUG")
    print("=" * 65)


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
    print("=" * 65)
    print("✅ RADAR 24.0 TAMAMLANDI")
    print("=" * 65)
    print("")


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
