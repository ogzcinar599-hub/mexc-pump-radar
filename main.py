import os
import json
import time
import threading
import requests

from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PUMP RADAR 23.0
#
# PUMP ÖNCESİ RADAR
#
# 728 COIN
#      ↓
# TOPLU TICKER
#      ↓
# HIZLI ÖN ELEME
#      ↓
# 120-160 COIN
#      ↓
# 15M + 1H + 4H
#      ↓
# RSI + EMA + HACİM + MOMENTUM
#      ↓
# BREAKOUT + RETEST
#      ↓
# FAKE BREAKOUT
#      ↓
# BTC
#      ↓
# QUALITY SCORE
#      ↓
# TELEGRAM
#
# ============================================================


# ============================================================
# AYARLAR
# ============================================================

BASE = "https://api.mexc.com"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HISTORY_FILE = "signal_history.json"


# ------------------------------------------------------------
# RATE LIMIT KORUMASI
# ------------------------------------------------------------

MAX_WORKERS = 3

REQUEST_TIMEOUT = 12

RETRIES = 4

RETRY_BASE = 2.0


# ------------------------------------------------------------
# RADAR
# ------------------------------------------------------------

KLINE_LIMIT = 100

MAX_DEEP_SCAN = 160

MAX_TELEGRAM = 8

MIN_SCORE = 65

MIN_RSI_4H = 47.0

MIN_VOLUME_RATIO = 2.20

COOLDOWN_HOURS = 6


# ------------------------------------------------------------
# ÖN ELEME
# ------------------------------------------------------------

# 24H hacimde ilk kaç coin?
TOP_VOLUME = 100

# 24H yükselişte ilk kaç coin?
TOP_GAINERS = 80

# 24H düşüşte çok sert düşenleri ele
MAX_24H_DROP = -18.0


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
            "Mozilla/5.0 MEXC-PUMP-RADAR/23.0",

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


            # =================================================
            # RATE LIMIT
            # =================================================

            if r.status_code == 429:

                last_error = (
                    f"HTTP 429 RATE LIMIT: {url}"
                )

                time.sleep(
                    RETRY_BASE * (attempt + 1)
                )

                continue


            # =================================================
            # SERVER ERROR
            # =================================================

            if r.status_code >= 500:

                last_error = (
                    f"HTTP {r.status_code}: {url}"
                )

                time.sleep(
                    RETRY_BASE * (attempt + 1)
                )

                continue


            # =================================================
            # OTHER HTTP ERROR
            # =================================================

            if r.status_code != 200:

                last_error = (
                    f"HTTP {r.status_code}: "
                    f"{url} "
                    f"{r.text[:150]}"
                )

                break


            data = r.json()


            if not isinstance(data, dict):

                last_error = (
                    f"JSON FORMAT ERROR: {url}"
                )

                break


            # =================================================
            # MEXC ERROR
            # =================================================

            if data.get("success") is False:

                code = data.get("code")

                message = data.get("message")


                # 510 = requests too frequent
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
                    f"message={message} "
                    f"url={url}"
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

        if not os.path.exists(HISTORY_FILE):

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

        print("❌ TELEGRAM_BOT_TOKEN yok")

        return False


    if not TELEGRAM_CHAT_ID:

        print("❌ TELEGRAM_CHAT_ID yok")

        return False


    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
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
# FUTURES SYMBOLS
# ============================================================

def get_futures_symbols():

    url = (
        f"{BASE}/api/v1/contract/detail"
    )


    data = request_json(url)


    if not data:

        return []


    rows = data.get("data")


    if not isinstance(rows, list):

        add_debug_error(
            "CONTRACT DETAIL LIST DEĞİL"
        )

        return []


    symbols = []


    for item in rows:

        try:

            symbol = item.get("symbol")


            if not symbol:
                continue


            if not symbol.endswith("_USDT"):
                continue


            state = item.get("state")


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


            # =================================================
            # TOKENIZED STOCK / ETF / INDEX
            # =================================================

            bad_words = [

                "STOCK",

                "ETF",

                "INDEX"

            ]


            if any(
                x in base
                for x in bad_words
            ):

                continue


            symbols.append(symbol)


        except:

            continue


    return list(
        dict.fromkeys(symbols)
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


    if not isinstance(rows, list):

        add_debug_error(
            "TICKER DATA LIST DEĞİL"
        )

        return {}


    result = {}


    for item in rows:

        try:

            symbol = item.get("symbol")


            if not symbol:
                continue


            if not symbol.endswith("_USDT"):
                continue


            last_price = float(
                item.get("lastPrice", 0)
            )


            rise_fall = float(
                item.get("riseFallRate", 0)
            )


            volume = float(
                item.get("volume", 0)
            )


            amount = float(
                item.get("amount", 0)
            )


            result[symbol] = {

                "price":
                    last_price,

                "change":
                    rise_fall * 100,

                "volume":
                    volume,

                "amount":
                    amount

            }


        except:

            continue


    return result


# ============================================================
# HIZLI ÖN ELEME
# ============================================================

def prefilter_symbols(
    symbols,
    tickers
):

    valid = []


    for symbol in symbols:

        t = tickers.get(symbol)


        if not t:
            continue


        price = t["price"]

        change = t["change"]

        amount = t["amount"]


        if price <= 0:
            continue


        # Çok sert düşmüş coinleri çıkar
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


    # ========================================================
    # HACME GÖRE
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
    # YÜKSELENLERE GÖRE
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

        symbol = x["symbol"]


        if (
            symbol in volume_symbols
            or symbol in gain_symbols
        ):

            candidates.append(x)


    # ========================================================
    # MAX 160
    # ========================================================

    candidates.sort(

        key=lambda x:
            (
                x["change"] * 0.35
                +
                (
                    x["amount"] /
                    max(
                        by_volume[0]["amount"],
                        1
                    )
                )
                * 65
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


    end = now


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
            end

    }


    data = request_json(

        url,

        params=params

    )


    if not data:

        return None


    raw = data.get("data")


    if not raw:

        add_debug_error(
            f"{symbol} {interval}: DATA YOK"
        )

        return None


    # ========================================================
    # DICT FORMAT
    # ========================================================

    if isinstance(raw, dict):

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
                    [float(x) for x in times],

                "open":
                    [float(x) for x in opens],

                "close":
                    [float(x) for x in closes],

                "high":
                    [float(x) for x in highs],

                "low":
                    [float(x) for x in lows],

                "volume":
                    [float(x) for x in volumes]

            }


        except Exception as e:

            add_debug_error(

                f"{symbol} {interval}: "
                f"NUMERIC {str(e)[:100]}"

            )

            return None


    # ========================================================
    # LIST FORMAT
    # ========================================================

    if isinstance(raw, list):

        rows = raw


        if len(rows) < 40:

            return None


        parsed = []


        for row in rows:

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
                [x["time"] for x in parsed],

            "open":
                [x["open"] for x in parsed],

            "close":
                [x["close"] for x in parsed],

            "high":
                [x["high"] for x in parsed],

            "low":
                [x["low"] for x in parsed],

            "volume":
                [x["volume"] for x in parsed]

        }


    return None


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if len(values) < period:

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

            (price - result)
            * multiplier
            + result

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
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
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
            +
            gains[i]

        ) / period


        avg_loss = (

            (
                avg_loss
                * (period - 1)
            )
            +
            losses[i]

        ) / period


    if avg_loss == 0:

        return 100.0


    rs = (
        avg_gain
        / avg_loss
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
        (new - old)
        / old
    ) * 100


# ============================================================
# AVERAGE
# ============================================================

def average(values):

    if not values:

        return 0


    return (
        sum(values)
        / len(values)
    )


# ============================================================
# VOLUME ANALYSIS
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


    current_volume = volumes[-1]

    previous_volume = volumes[-2]


    current_ratio = (
        current_volume
        /
        avg_volume
    )


    peak_ratio = (

        max(volumes[-3:])
        /
        avg_volume

    )


    price_move = pct_change(

        closes[-2],

        closes[-1]

    )


    buying_volume = (

        price_move > 0

        and

        current_volume
        >=
        previous_volume * 0.75

    )


    score = 0


    if current_ratio >= 2:

        score += 8


    if current_ratio >= 3:

        score += 8


    if current_ratio >= 5:

        score += 7


    if peak_ratio >= 5:

        score += 4


    if buying_volume:

        score += 10


    # Hacim artıyor ama fiyat düşüyor
    if (
        current_ratio >= 3
        and price_move < -1
    ):

        score -= 12


    return (

        current_ratio,

        score,

        buying_volume

    )


# ============================================================
# SELLING PRESSURE
# ============================================================

def selling_pressure(
    opens,
    closes,
    highs,
    lows
):

    if len(closes) < 5:

        return False


    bad = 0


    for i in range(
        -5,
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
            h - max(o, c)
        )


        if upper_wick > body * 1.8:

            bad += 1


        if c < o:

            drop = pct_change(
                o,
                c
            )


            if drop < -1.5:

                bad += 1


    return bad >= 3


# ============================================================
# FAKE BREAKOUT
# ============================================================

def fake_breakout(
    highs,
    closes
):

    if len(highs) < 25:

        return False


    resistance = max(
        highs[-21:-2]
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

        highs[-1] > resistance

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

    if len(highs) < 30:

        return None, False, False


    resistance = max(
        highs[-25:-2]
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
        abs(distance)
        <=
        2
    )


    return (

        resistance,

        breakout,

        near

    )


# ============================================================
# RETEST
# ============================================================

def retest_signal(
    highs,
    lows,
    closes
):

    if len(closes) < 30:

        return False


    resistance = max(
        highs[-30:-5]
    )


    current = closes[-1]

    previous_low = lows[-2]


    if current > resistance:

        if (
            previous_low
            <=
            resistance * 1.01
        ):

            return True


    return False


# ============================================================
# PUMP ALREADY HAPPENED
# ============================================================

def pump_before(
    closes
):

    if len(closes) < 30:

        return False


    move6 = pct_change(

        closes[-7],

        closes[-1]

    )


    move12 = pct_change(

        closes[-13],

        closes[-1]

    )


    if move6 >= 10:

        return True


    if move12 >= 18:

        return True


    return False


# ============================================================
# BTC
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


    if positive >= 2:

        state = "BULLISH"


    elif negative >= 2:

        state = "BEARISH"


    else:

        state = "NEUTRAL"


    return state, result


# ============================================================
# ANALYZE
# ============================================================

def analyze_coin(
    symbol,
    btc_state
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


        # Küçük gecikme
        time.sleep(0.10)


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


        time.sleep(0.10)


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
        # DATA
        # ====================================================

        c15 = d15["close"]

        h15 = d15["high"]

        l15 = d15["low"]

        o15 = d15["open"]

        v15 = d15["volume"]


        c1h = d1h["close"]

        h1h = d1h["high"]

        l1h = d1h["low"]


        c4h = d4h["close"]


        # ====================================================
        # RSI
        # ====================================================

        rsi15 = rsi(c15)

        rsi1h = rsi(c1h)

        rsi4h = rsi(c4h)


        if not all([

            rsi15 is not None,

            rsi1h is not None,

            rsi4h is not None

        ]):

            return None, "DATA4H"


        # ====================================================
        # 4H RSI
        # ====================================================

        if rsi4h < MIN_RSI_4H:

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
        # VOLUME
        # ====================================================

        volume_ratio, volume_score, buying_volume = (

            volume_analysis(

                v15,

                c15

            )

        )


        if volume_ratio < MIN_VOLUME_RATIO:

            return None, "VOLUME"


        # ====================================================
        # SELLING PRESSURE
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

        resistance, breakout, near_resistance = (

            resistance_info(

                h1h,

                c1h

            )

        )


        if resistance is None:

            return None, "RESISTANCE"


        # ====================================================
        # PUMP ÖNCEDEN YAPILMIŞ MI?
        # ====================================================

        if pump_before(c15):

            return None, "OVEREXTENDED"


        # ====================================================
        # TREND SCORE
        # ====================================================

        trend_score = 0


        # 15M

        if c15[-1] > ema20_15:

            trend_score += 5


        if ema20_15 > ema50_15:

            trend_score += 5


        # 1H

        if c1h[-1] > ema20_1h:

            trend_score += 7


        if ema20_1h > ema50_1h:

            trend_score += 8


        # 4H

        if c4h[-1] > ema20_4h:

            trend_score += 7


        if ema20_4h > ema50_4h:

            trend_score += 8


        # ====================================================
        # RSI SCORE
        # ====================================================

        rsi_score = 0


        if 50 <= rsi15 <= 72:

            rsi_score += 7


        if 50 <= rsi1h <= 68:

            rsi_score += 7


        if 47 <= rsi4h <= 65:

            rsi_score += 8


        if rsi15 > 78:

            rsi_score -= 10


        if rsi1h > 75:

            rsi_score -= 8


        # ====================================================
        # MOMENTUM
        # ====================================================

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


        momentum_score = 0


        if move15 > 0:

            momentum_score += 5


        if move1h > 0:

            momentum_score += 6


        if move4h > 0:

            momentum_score += 6


        if move15 > 2:

            momentum_score += 3


        # ====================================================
        # BREAKOUT / RETEST
        # ====================================================

        breakout_score = 0


        if breakout:

            breakout_score += 10


        retest = retest_signal(

            h1h,

            l1h,

            c1h

        )


        if retest:

            breakout_score += 12


        if (
            near_resistance
            and
            not breakout
        ):

            breakout_score -= 3


        # ====================================================
        # BTC
        # ====================================================

        if btc_state == "BULLISH":

            btc_score = 8


        elif btc_state == "NEUTRAL":

            btc_score = 3


        else:

            btc_score = -10


        # ====================================================
        # BTC BEARISH
        # ====================================================

        if btc_state == "BEARISH":

            return None, "BTC"


        # ====================================================
        # TOTAL
        # ====================================================

        score = (

            trend_score

            +

            rsi_score

            +

            volume_score

            +

            momentum_score

            +

            breakout_score

            +

            btc_score

        )


        score = max(

            0,

            min(

                100,

                score

            )

        )


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

            l15[-8:]

        )


        stop = (

            swing_low
            * 0.997

        )


        risk_percent = (

            abs(
                pct_change(
                    stop,
                    entry
                )
            )

        )


        if risk_percent < 1:

            stop = (
                entry
                * 0.985
            )


        elif risk_percent > 4:

            stop = (
                entry
                * 0.975
            )


        # ====================================================
        # TP
        # ====================================================

        risk_amount = (

            entry
            -
            stop

        )


        if risk_amount <= 0:

            return None, "QUALITY"


        tp1 = (

            entry
            +
            risk_amount * 1.5

        )


        tp2 = (

            entry
            +
            risk_amount * 2.3

        )


        tp3 = (

            entry
            +
            risk_amount * 3.2

        )


        # ====================================================
        # RESULT
        # ====================================================

        result = {

            "symbol":
                symbol,

            "side":
                "LONG",

            "score":
                round(score, 1),

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
                rsi15,

            "rsi1h":
                rsi1h,

            "rsi4h":
                rsi4h,

            "volume":
                volume_ratio,

            "btc":
                btc_state,

            "move15":
                move15,

            "move1h":
                move1h,

            "move4h":
                move4h,

            "resistance":
                resistance,

            "breakout":
                breakout,

            "retest":
                retest,

            "trend_score":
                trend_score,

            "rsi_score":
                rsi_score,

            "volume_score":
                volume_score,

            "momentum_score":
                momentum_score,

            "breakout_score":
                breakout_score,

            "btc_score":
                btc_score

        }


        return result, "SIGNAL"


    except Exception as e:

        add_debug_error(

            f"{symbol}: "
            f"ANALYZE ERROR "
            f"{str(e)[:160]}"

        )

        return None, "ERROR"


# ============================================================
# TELEGRAM FORMAT
# ============================================================

def format_signal(x):

    symbol = x["symbol"].replace(

        "_USDT",

        "/USDT"

    )


    return f"""
🚀 <b>PUMP RADAR 23.0</b>

🟢 <b>LONG ADAYI</b>

<b>{symbol}</b>

⭐ Güç: <b>{x['score']}/100</b>

━━━━━━━━━━━━━━

🎯 Giriş:
<b>{x['entry']:.8g}</b>

🛑 Stop:
<b>{x['stop']:.8g}</b>

🥇 TP1:
<b>{x['tp1']:.8g}</b>

🥈 TP2:
<b>{x['tp2']:.8g}</b>

🥉 TP3:
<b>{x['tp3']:.8g}</b>

━━━━━━━━━━━━━━

📊 RSI

15M: <b>{x['rsi15']:.1f}</b>
1H : <b>{x['rsi1h']:.1f}</b>
4H : <b>{x['rsi4h']:.1f}</b>

🔥 Hacim:
<b>{x['volume']:.2f}x</b>

📈 Momentum

15M: <b>{x['move15']:+.2f}%</b>
1H : <b>{x['move1h']:+.2f}%</b>
4H : <b>{x['move4h']:+.2f}%</b>

━━━━━━━━━━━━━━

₿ BTC:
<b>{x['btc']}</b>

Breakout:
<b>{'EVET' if x['breakout'] else 'HAYIR'}</b>

Retest:
<b>{'EVET' if x['retest'] else 'HAYIR'}</b>

━━━━━━━━━━━━━━

⚠️ Otomatik teknik tarama.
"""


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print("=" * 65)
    print("🚀 MEXC PUMP RADAR 23.0")
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


    stats["TOTAL"] = len(symbols)


    print(
        f"📊 Toplam Futures: "
        f"{len(symbols)}"
    )


    # ========================================================
    # TOPLU TICKER
    # ========================================================

    print("")
    print(
        "⚡ Toplu ticker alınıyor..."
    )


    tickers = get_all_tickers()


    print(
        f"📡 Ticker alınan coin: "
        f"{len(tickers)}"
    )


    if not tickers:

        print(
            "❌ Ticker verisi alınamadı."
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
        f"🎯 Derin tarama adayı: "
        f"{len(candidates)}"
    )


    print(
        "   15M + 1H + 4H taranacak."
    )


    # ========================================================
    # BTC
    # ========================================================

    print("")
    print(
        "₿ BTC yönü hesaplanıyor..."
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

                btc_state

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
                    f"FUTURE "
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
    print("📊 23.0 ELEME RAPORU")
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
        f"RSI düşük          : "
        f"{stats['RSI']}"
    )

    print(
        f"Hacim düşük        : "
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
    # EN İYİLER
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

            f"15M {x['move15']:+5.2f}%"

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
    print("✅ RADAR 23.0 TAMAMLANDI")
    print("=" * 65)
    print("")


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
