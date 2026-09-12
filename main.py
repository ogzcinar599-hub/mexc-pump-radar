import os
import json
import math
import time
import threading
import requests


# ============================================================
# 🚀 MEXC PRE-PUMP RADAR V16.1
#
# KADEMELİ TARAMA:
#
# 1059 FUTURES
#       ↓
# 15M → 120
#       ↓
# 1H → 40
#       ↓
# 4H → 20
#       ↓
# PARA AKIŞI → 10
#       ↓
# FINAL SCORE
#       ↓
# TELEGRAM
#
# SADECE LONG / PRE-PUMP ADAYLARI
# OTOMATİK İŞLEM AÇMAZ
#
# V16.1
# - recent_move düzeltildi
# - MEXC 510 rate-limit koruması
# - 15M / 1H / 4H kademeli tarama
# - Para akışı son aşamada
# ============================================================


# ============================================================
# MEXC
# ============================================================

BASE = "https://api.mexc.com"


# ============================================================
# TELEGRAM
# ============================================================

TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)


# ============================================================
# TARAMA AYARLARI
# ============================================================

MAX_SYMBOLS = 120

STAGE_15M = 120
STAGE_1H = 40
STAGE_4H = 20
STAGE_FLOW = 10

MAX_ALERTS = 5

MIN_ALERT_SCORE = 58


# ============================================================
# LİKİDİTE
# ============================================================

MIN_24H_AMOUNT = 100_000


# ============================================================
# RATE LIMIT
#
# MEXC 510 hatasını önlemek için bütün API istekleri
# tek bir global limiter üzerinden geçiyor.
# ============================================================

REQUEST_INTERVAL = 0.13

MAX_510_RETRY = 4

BACKOFF_BASE = 1.0

rate_lock = threading.Lock()

last_request_time = 0.0


# ============================================================
# STATE
# ============================================================

STATE_FILE = "signal_state_v16.json"

STATE_TTL = 1800


# ============================================================
# KLINE
# ============================================================

KLINE_COUNT = 90


# ============================================================
# DEALS
# ============================================================

DEALS_LIMIT = 100


# ============================================================
# İSTENMEYEN ENSTRÜMANLAR
# ============================================================

BAD_NAMES = {

    "SPY",
    "SPX500",

    "USOIL",
    "UKOIL",

    "XAU",
    "XAG",
    "XPT",
    "XPD",

    "GOLD",
    "SILVER",
    "COPPER",

    "NGAS",
    "NATGAS",

    "NVDA",
    "TSLA",
    "AAPL",
    "AMZN",
    "MSFT",
    "GOOGL",
    "META",
    "COIN",
    "MSTR",
    "QQQ"

}


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({

    "User-Agent":
        "Mozilla/5.0 MEXC-PRE-PUMP-RADAR/16.1",

    "Accept":
        "application/json"

})


# ============================================================
# İSTATİSTİK
# ============================================================

stats = {

    "futures": 0,

    "stage15": 0,

    "stage1h": 0,

    "stage4h": 0,

    "stageflow": 0,

    "kline15": 0,

    "kline1h": 0,

    "kline4h": 0,

    "money_ok": 0,

    "volume_ok": 0,

    "trend_ok": 0,

    "rsi_ok": 0,

    "setup_ok": 0,

    "final": 0,

    "alerts": 0,

    "rate_510": 0,

    "api_error": 0

}


# ============================================================
# SAYI
# ============================================================

def fnum(
    value,
    default=0.0
):

    try:

        return float(value)

    except Exception:

        return default


# ============================================================
# CLAMP
# ============================================================

def clamp(
    value,
    low,
    high
):

    return max(

        low,

        min(
            high,
            value
        )

    )


# ============================================================
# PARA FORMAT
# ============================================================

def money(
    value
):

    value = fnum(value)

    if value >= 1_000_000:

        return (
            f"${value / 1_000_000:.2f}M"
        )

    if value >= 1000:

        return (
            f"${value / 1000:.1f}K"
        )

    return (
        f"${value:.0f}"
    )


# ============================================================
# FİYAT FORMAT
# ============================================================

def price(
    value
):

    value = fnum(value)

    if value >= 1000:

        return f"{value:,.2f}"

    if value >= 1:

        return f"{value:.4f}"

    if value >= 0.01:

        return f"{value:.6f}"

    if value >= 0.0001:

        return f"{value:.8f}"

    return f"{value:.10f}"


# ============================================================
# RATE LIMIT
# ============================================================

def rate_wait():

    global last_request_time

    with rate_lock:

        now = time.time()

        elapsed = (

            now
            -
            last_request_time

        )

        if elapsed < REQUEST_INTERVAL:

            time.sleep(

                REQUEST_INTERVAL
                -
                elapsed

            )

        last_request_time = time.time()


# ============================================================
# API GET
# ============================================================

def api_get(
    url,
    params=None
):

    for attempt in range(
        MAX_510_RETRY + 1
    ):

        rate_wait()

        try:

            response = session.get(

                url,

                params=params,

                timeout=15

            )

            # ==================================================
            # HTTP 510
            # ==================================================

            if response.status_code == 510:

                stats[
                    "rate_510"
                ] += 1

                wait_time = (

                    BACKOFF_BASE
                    *
                    (
                        2 ** attempt
                    )

                )

                print(

                    f"⚠️ 510 RATE LIMIT | "
                    f"{wait_time:.1f}s bekleniyor"

                )

                time.sleep(
                    wait_time
                )

                continue

            # ==================================================
            # HTTP ERROR
            # ==================================================

            if not response.ok:

                stats[
                    "api_error"
                ] += 1

                print(

                    "API HTTP:",
                    response.status_code

                )

                return None

            # ==================================================
            # JSON
            # ==================================================

            try:

                data = response.json()

            except Exception:

                stats[
                    "api_error"
                ] += 1

                return None

            # ==================================================
            # API CODE 510
            # ==================================================

            if isinstance(
                data,
                dict
            ):

                code = str(

                    data.get(
                        "code",
                        ""
                    )

                )

                if code == "510":

                    stats[
                        "rate_510"
                    ] += 1

                    wait_time = (

                        BACKOFF_BASE
                        *
                        (
                            2 ** attempt
                        )

                    )

                    print(

                        f"⚠️ API 510 | "
                        f"{wait_time:.1f}s bekleniyor"

                    )

                    time.sleep(
                        wait_time
                    )

                    continue

            return data

        except Exception as e:

            stats[
                "api_error"
            ] += 1

            print(
                "API HATASI:",
                e
            )

            time.sleep(
                0.5
            )

            return None

    return None


# ============================================================
# EMA
# ============================================================

def ema(
    values,
    period
):

    if not values:

        return []

    k = (

        2.0
        /
        (period + 1.0)

    )

    result = [

        values[0]

    ]

    current = values[0]

    for value in values[1:]:

        current = (

            current
            +
            (
                value
                -
                current
            )
            *
            k

        )

        result.append(
            current
        )

    return result


# ============================================================
# RSI
# ============================================================

def rsi(
    values,
    period=14
):

    if len(values) < period + 1:

        return 50.0

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

        100.0
        -
        (
            100.0
            /
            (1.0 + rs)
        )

    )


# ============================================================
# CONTRACTS
# ============================================================

def get_contracts():

    data = api_get(

        f"{BASE}/api/v1/contract/detail"

    )

    if not isinstance(
        data,
        dict
    ):

        return {}

    rows = data.get(
        "data",
        []
    )

    if not isinstance(
        rows,
        list
    ):

        return {}

    contracts = {}

    for item in rows:

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

        base_coin = str(

            item.get(
                "baseCoin",
                ""
            )

        ).upper()

        clean_name = symbol[:-5]

        if (

            base_coin in BAD_NAMES

            or

            clean_name in BAD_NAMES

        ):

            continue

        contract_size = fnum(

            item.get(
                "contractSize",
                1
            ),

            1

        )

        if contract_size <= 0:

            contract_size = 1.0

        contracts[
            symbol
        ] = contract_size

    return contracts


# ============================================================
# TICKERS
# ============================================================

def get_tickers():

    data = api_get(

        f"{BASE}/api/v1/contract/ticker"

    )

    if not isinstance(
        data,
        dict
    ):

        return []

    rows = data.get(
        "data",
        []
    )

    if not isinstance(
        rows,
        list
    ):

        return []

    return rows


# ============================================================
# KLINE
# ============================================================

def get_kline(
    symbol,
    interval
):

    seconds_map = {

        "Min15":
            15 * 60,

        "Min60":
            60 * 60,

        "Hour4":
            4 * 60 * 60

    }

    candle_seconds = seconds_map[
        interval
    ]

    now = int(
        time.time()
    )

    start = (

        now
        -
        (
            KLINE_COUNT
            *
            candle_seconds
        )

    )

    end = now

    data = api_get(

        f"{BASE}/api/v1/contract/kline/{symbol}",

        {

            "interval":
                interval,

            "start":
                start,

            "end":
                end

        }

    )

    if not isinstance(
        data,
        dict
    ):

        return []

    raw = data.get(
        "data"
    )

    if not isinstance(
        raw,
        dict
    ):

        return []

    required = [

        "open",
        "close",
        "high",
        "low",
        "vol"

    ]

    if any(

        key not in raw

        for key in required

    ):

        return []

    try:

        count = min(

            len(
                raw[key]
            )

            for key in required

        )

    except Exception:

        return []

    if count < 60:

        return []

    candles = []

    for i in range(
        count
    ):

        o = fnum(
            raw["open"][i]
        )

        c = fnum(
            raw["close"][i]
        )

        h = fnum(
            raw["high"][i]
        )

        l = fnum(
            raw["low"][i]
        )

        v = fnum(
            raw["vol"][i]
        )

        if (

            c <= 0
            or
            h <= 0
            or
            l <= 0

        ):

            continue

        candles.append({

            "open": o,

            "close": c,

            "high": h,

            "low": l,

            "vol": v

        })

    return candles


# ============================================================
# TIMEFRAME ANALİZ
# ============================================================

def analyze_tf(
    candles
):

    if not candles:

        return None

    if len(candles) < 60:

        return None

    closes = [

        x["close"]
        for x in candles

    ]

    highs = [

        x["high"]
        for x in candles

    ]

    lows = [

        x["low"]
        for x in candles

    ]

    volumes = [

        x["vol"]
        for x in candles

    ]

    current = closes[-1]

    ema9 = ema(
        closes,
        9
    )[-1]

    ema21 = ema(
        closes,
        21
    )[-1]

    ema50 = ema(
        closes,
        50
    )[-1]

    current_rsi = rsi(
        closes
    )

    previous_rsi = rsi(
        closes[:-1]
    )

    resistance = max(
        highs[-21:-1]
    )

    support = min(
        lows[-21:-1]
    )

    avg_volume = (

        sum(
            volumes[-21:-1]
        )
        /
        20

    )

    if avg_volume > 0:

        volume_ratio = (

            volumes[-1]
            /
            avg_volume

        )

    else:

        volume_ratio = 0

    if current > 0:

        dist_res = (

            (
                resistance
                /
                current
            )
            -
            1

        ) * 100

    else:

        dist_res = 999

    if support > 0:

        dist_sup = (

            (
                current
                /
                support
            )
            -
            1

        ) * 100

    else:

        dist_sup = 999

    # ========================================================
    # TREND
    # ========================================================

    if (

        current
        >
        ema9
        >
        ema21
        >
        ema50

    ):

        trend = "BULL"

    elif (

        current
        <
        ema9
        <
        ema21
        <
        ema50

    ):

        trend = "BEAR"

    else:

        trend = "MIXED"

    # ========================================================
    # HIGHER LOW
    # ========================================================

    recent_low = min(
        lows[-8:-2]
    )

    previous_low = min(
        lows[-16:-8]
    )

    higher_low = (

        recent_low
        >
        previous_low

    )

    # ========================================================
    # HIGHER HIGH
    # ========================================================

    recent_high = max(
        highs[-8:-2]
    )

    previous_high = max(
        highs[-16:-8]
    )

    higher_high = (

        recent_high
        >
        previous_high

    )

    # ========================================================
    # MOMENTUM
    # ========================================================

    momentum = (

        closes[-1]
        >
        closes[-2]
        >
        closes[-3]

    )

    # ========================================================
    # SON 6 MUM HAREKETİ
    #
    # V16.0'da eksikti.
    # KeyError: recent_move buradan düzeltildi.
    # ========================================================

    if (

        len(closes) >= 7

        and

        closes[-7] > 0

    ):

        recent_move = (

            (
                closes[-1]
                /
                closes[-7]
            )
            -
            1

        ) * 100

    else:

        recent_move = 0.0

    # ========================================================
    # BREAKOUT
    # ========================================================

    breakout = (

        current
        >
        resistance

    )

    # ========================================================
    # RETURN
    # ========================================================

    return {

        "price":
            current,

        "ema9":
            ema9,

        "ema21":
            ema21,

        "ema50":
            ema50,

        "rsi":
            current_rsi,

        "rsi_prev":
            previous_rsi,

        "volume":
            volume_ratio,

        "support":
            support,

        "resistance":
            resistance,

        "dist_res":
            dist_res,

        "dist_sup":
            dist_sup,

        "trend":
            trend,

        "higher_low":
            higher_low,

        "higher_high":
            higher_high,

        "momentum":
            momentum,

        "recent_move":
            recent_move,

        "breakout":
            breakout

    }


# ============================================================
# PARA AKIŞI
# ============================================================

def get_open_flow(
    symbol,
    contract_size
):

    data = api_get(

        f"{BASE}/api/v1/contract/deals/{symbol}",

        {

            "limit":
                DEALS_LIMIT

        }

    )

    if not isinstance(
        data,
        dict
    ):

        return None

    rows = data.get(
        "data",
        []
    )

    if not isinstance(
        rows,
        list
    ):

        return None

    buy_open = 0

    sell_open = 0

    buy_count = 0

    sell_count = 0

    for trade in rows:

        p = fnum(
            trade.get("p")
        )

        v = fnum(
            trade.get("v")
        )

        T = int(

            fnum(

                trade.get(
                    "T",
                    0
                )

            )

        )

        O = int(

            fnum(

                trade.get(
                    "O",
                    0
                )

            )

        )

        if (

            p <= 0
            or
            v <= 0
            or
            O != 1

        ):

            continue

        notional = (

            p
            *
            v
            *
            contract_size

        )

        if T == 1:

            buy_open += notional

            buy_count += 1

        elif T == 2:

            sell_open += notional

            sell_count += 1

    total = (

        buy_open
        +
        sell_open

    )

    if total <= 0:

        return None

    net = (

        buy_open
        -
        sell_open

    )

    net_pct = (

        net
        /
        total

    ) * 100

    buy_share = (

        buy_open
        /
        total

    ) * 100

    return {

        "buy":
            buy_open,

        "sell":
            sell_open,

        "total":
            total,

        "net":
            net,

        "net_pct":
            net_pct,

        "buy_share":
            buy_share,

        "buy_count":
            buy_count,

        "sell_count":
            sell_count

    }


# ============================================================
# MONEY SCORE
# ============================================================

def money_score(
    flow,
    amount24
):

    if not flow:

        return 0

    net_pct = flow[
        "net_pct"
    ]

    buy_share = flow[
        "buy_share"
    ]

    total = flow[
        "total"
    ]

    if net_pct <= 0:

        return 0

    score = 0

    if total >= 10_000:

        score += 4

    if total >= 25_000:

        score += 4

    if total >= 50_000:

        score += 4

    if total >= 100_000:

        score += 3

    if net_pct >= 3:

        score += 2

    if net_pct >= 8:

        score += 2

    if net_pct >= 15:

        score += 2

    if net_pct >= 25:

        score += 2

    if buy_share >= 52:

        score += 1

    if buy_share >= 58:

        score += 1

    ratio = (

        total
        /
        max(
            amount24,
            1
        )

    )

    if ratio >= 0.0003:

        score += 1

    return min(
        score,
        25
    )


# ============================================================
# 15M SCORE
# ============================================================

def stage15_score(
    t
):

    if not t:

        return 0

    score = 0

    # ========================================================
    # RSI
    # ========================================================

    if 42 <= t["rsi"] <= 68:

        score += 25

    elif 68 < t["rsi"] <= 75:

        score += 15

    elif 38 <= t["rsi"] < 42:

        score += 10

    # ========================================================
    # TREND
    # ========================================================

    if t["trend"] == "BULL":

        score += 25

    elif t["trend"] == "MIXED":

        score += 15

    # ========================================================
    # RSI YÜKSELİYOR
    # ========================================================

    if t["rsi"] > t["rsi_prev"]:

        score += 15

    # ========================================================
    # HIGHER LOW
    # ========================================================

    if t["higher_low"]:

        score += 15

    # ========================================================
    # MOMENTUM
    # ========================================================

    if t["momentum"]:

        score += 10

    # ========================================================
    # ZATEN PUMP OLMUŞSA PUAN KIR
    # ========================================================

    if t["recent_move"] > 8:

        score -= 10

    if t["recent_move"] > 12:

        score -= 15

    return int(

        clamp(

            score,

            0,

            100

        )

    )


# ============================================================
# 1H SCORE
# ============================================================

def stage1h_score(
    t15,
    t1
):

    score = 0

    # 1H trend

    if t1["trend"] == "BULL":

        score += 25

    elif t1["trend"] == "MIXED":

        score += 17

    # 15M trend

    if t15["trend"] == "BULL":

        score += 15

    elif t15["trend"] == "MIXED":

        score += 10

    # RSI

    if 43 <= t15["rsi"] <= 68:

        score += 20

    elif 68 < t15["rsi"] <= 76:

        score += 12

    # Higher low

    if t15["higher_low"]:

        score += 15

    if t1["higher_low"]:

        score += 15

    # Momentum

    if t15["momentum"]:

        score += 10

    return int(

        clamp(

            score,

            0,

            100

        )

    )


# ============================================================
# 4H SCORE
# ============================================================

def stage4h_score(
    t15,
    t1,
    t4
):

    score = 0

    # 4H

    if t4["trend"] == "BULL":

        score += 30

    elif t4["trend"] == "MIXED":

        score += 20

    # 1H

    if t1["trend"] == "BULL":

        score += 20

    elif t1["trend"] == "MIXED":

        score += 12

    # 15M

    if t15["trend"] == "BULL":

        score += 10

    elif t15["trend"] == "MIXED":

        score += 7

    # Higher low

    if t15["higher_low"]:

        score += 10

    if t1["higher_low"]:

        score += 10

    if t4["higher_low"]:

        score += 10

    return int(

        clamp(

            score,

            0,

            100

        )

    )


# ============================================================
# VOLUME SCORE
# ============================================================

def volume_score(
    t15,
    t1
):

    best = max(

        t15["volume"],

        t1["volume"]

    )

    if best >= 3:

        return 15

    if best >= 2:

        return 13

    if best >= 1.5:

        return 11

    if best >= 1.2:

        return 9

    if best >= 1:

        return 7

    if best >= 0.8:

        return 5

    if best >= 0.7:

        return 3

    return 0


# ============================================================
# FINAL SCORE
# ============================================================

def final_score(
    t15,
    t1,
    t4,
    flow,
    amount24,
    change24
):

    # ========================================================
    # PARA
    # ========================================================

    m = money_score(

        flow,

        amount24

    )

    # ========================================================
    # TEKNİK
    # ========================================================

    tech = 0

    if t15["trend"] == "BULL":

        tech += 8

    elif t15["trend"] == "MIXED":

        tech += 5

    if t1["trend"] == "BULL":

        tech += 10

    elif t1["trend"] == "MIXED":

        tech += 6

    if 43 <= t15["rsi"] <= 68:

        tech += 8

    elif 68 < t15["rsi"] <= 76:

        tech += 4

    if t15["rsi"] > t15["rsi_prev"]:

        tech += 4

    if t15["higher_low"]:

        tech += 3

    if t1["higher_low"]:

        tech += 2

    if t15["momentum"]:

        tech += 3

    tech = min(
        tech,
        35
    )

    # ========================================================
    # VOLUME
    # ========================================================

    vol = volume_score(

        t15,
        t1

    )

    # ========================================================
    # SETUP
    # ========================================================

    setup = 0

    distance = min(

        t15["dist_res"],

        t1["dist_res"]

    )

    if 0 <= distance <= 3:

        setup += 7

    elif 3 < distance <= 6:

        setup += 5

    elif 6 < distance <= 10:

        setup += 2

    if t15["higher_low"]:

        setup += 3

    if t1["higher_low"]:

        setup += 3

    if t15["momentum"]:

        setup += 2

    setup = min(
        setup,
        15
    )

    # ========================================================
    # 4H
    # ========================================================

    h4 = 0

    if t4["trend"] == "BULL":

        h4 += 7

    elif t4["trend"] == "MIXED":

        h4 += 4

    if t4["higher_low"]:

        h4 += 3

    h4 = min(
        h4,
        10
    )

    # ========================================================
    # TOTAL
    # ========================================================

    total = (

        m
        +
        tech
        +
        vol
        +
        setup
        +
        h4

    )

    # ========================================================
    # CEZALAR
    # ========================================================

    if change24 >= 15:

        total -= 3

    if change24 >= 25:

        total -= 5

    if change24 >= 40:

        total -= 8

    if t15["rsi"] > 78:

        total -= 15

    if t1["rsi"] > 78:

        total -= 10

    if (

        t15["breakout"]
        or
        t1["breakout"]

    ):

        total -= 10

    return int(

        clamp(

            round(total),

            0,

            100

        )

    )


# ============================================================
# TRADE PLAN
# ============================================================

def build_plan(
    t15,
    t1,
    t4
):

    current = t15[
        "price"
    ]

    support = max(

        t15["support"],

        t1["support"],

        t4["support"]

    )

    resistance = min(

        t15["resistance"],

        t1["resistance"],

        t4["resistance"]

    )

    entry_low = max(

        support,

        current * 0.985

    )

    entry_high = min(

        current * 1.003,

        resistance * 0.998

    )

    if entry_high <= entry_low:

        entry_low = current * 0.995

        entry_high = current * 1.003

    breakout = (

        resistance
        *
        1.002

    )

    risk = max(

        current - support,

        current * 0.012

    )

    stop = (

        current
        -
        risk
        *
        0.80

    )

    stop = max(

        stop,

        current * 0.96

    )

    risk_pct = (

        (
            current
            -
            stop
        )
        /
        current

    ) * 100

    risk_pct = clamp(

        risk_pct,

        0.8,

        4

    )

    tp1 = (

        current
        *
        (
            1
            +
            risk_pct
            *
            1.5
            /
            100
        )

    )

    tp2 = (

        current
        *
        (
            1
            +
            risk_pct
            *
            2.5
            /
            100
        )

    )

    tp3 = (

        current
        *
        (
            1
            +
            risk_pct
            *
            4
            /
            100
        )

    )

    return {

        "entry_low":
            entry_low,

        "entry_high":
            entry_high,

        "breakout":
            breakout,

        "support":
            support,

        "resistance":
            resistance,

        "stop":
            stop,

        "tp1":
            tp1,

        "tp2":
            tp2,

        "tp3":
            tp3

    }


# ============================================================
# STAGE 1 — 15M
# ============================================================

def scan_15m(
    candidates
):

    print()

    print(
        "🟢 AŞAMA 1 | 15M TARAMA"
    )

    results = []

    for index, item in enumerate(

        candidates,

        1

    ):

        symbol = item[
            "symbol"
        ]

        candles = get_kline(

            symbol,

            "Min15"

        )

        if not candles:

            continue

        stats[
            "kline15"
        ] += 1

        t15 = analyze_tf(
            candles
        )

        if not t15:

            continue

        score = stage15_score(
            t15
        )

        results.append({

            **item,

            "t15":
                t15,

            "stage_score":
                score

        })

        if index % 20 == 0:

            print(

                f"15M: "
                f"{index}/"
                f"{len(candidates)}"

            )

    results.sort(

        key=lambda x:
            x["stage_score"],

        reverse=True

    )

    results = results[
        :STAGE_1H
    ]

    stats[
        "stage15"
    ] = len(results)

    print(

        f"✅ 15M → "
        f"{len(results)} coin"

    )

    return results


# ============================================================
# STAGE 2 — 1H
# ============================================================

def scan_1h(
    candidates
):

    print()

    print(
        "🟡 AŞAMA 2 | 1H TARAMA"
    )

    results = []

    for item in candidates:

        symbol = item[
            "symbol"
        ]

        candles = get_kline(

            symbol,

            "Min60"

        )

        if not candles:

            continue

        stats[
            "kline1h"
        ] += 1

        t1 = analyze_tf(
            candles
        )

        if not t1:

            continue

        t15 = item[
            "t15"
        ]

        score = stage1h_score(

            t15,
            t1

        )

        results.append({

            **item,

            "t1":
                t1,

            "stage_score":
                score

        })

    results.sort(

        key=lambda x:
            x["stage_score"],

        reverse=True

    )

    results = results[
        :STAGE_4H
    ]

    stats[
        "stage1h"
    ] = len(results)

    print(

        f"✅ 1H → "
        f"{len(results)} coin"

    )

    return results


# ============================================================
# STAGE 3 — 4H
# ============================================================

def scan_4h(
    candidates
):

    print()

    print(
        "🟠 AŞAMA 3 | 4H TARAMA"
    )

    results = []

    for item in candidates:

        symbol = item[
            "symbol"
        ]

        candles = get_kline(

            symbol,

            "Hour4"

        )

        if not candles:

            continue

        stats[
            "kline4h"
        ] += 1

        t4 = analyze_tf(
            candles
        )

        if not t4:

            continue

        t15 = item[
            "t15"
        ]

        t1 = item[
            "t1"
        ]

        score = stage4h_score(

            t15,
            t1,
            t4

        )

        results.append({

            **item,

            "t4":
                t4,

            "stage_score":
                score

        })

    results.sort(

        key=lambda x:
            x["stage_score"],

        reverse=True

    )

    results = results[
        :STAGE_FLOW
    ]

    stats[
        "stage4h"
    ] = len(results)

    print(

        f"✅ 4H → "
        f"{len(results)} coin"

    )

    return results


# ============================================================
# STAGE 4 — PARA AKIŞI
# ============================================================

def scan_flow(
    candidates
):

    print()

    print(
        "🔴 AŞAMA 4 | PARA AKIŞI"
    )

    results = []

    for item in candidates:

        symbol = item[
            "symbol"
        ]

        contract_size = item[
            "contract_size"
        ]

        ticker = item[
            "ticker"
        ]

        flow = get_open_flow(

            symbol,

            contract_size

        )

        amount24 = fnum(

            ticker.get(
                "amount24"
            )

        )

        change24 = (

            fnum(

                ticker.get(
                    "riseFallRate"
                )

            )
            *
            100

        )

        score = final_score(

            item["t15"],

            item["t1"],

            item["t4"],

            flow,

            amount24,

            change24

        )

        results.append({

            **item,

            "flow":
                flow,

            "final_score":
                score,

            "change24":
                change24

        })

    results.sort(

        key=lambda x:
            x["final_score"],

        reverse=True

    )

    stats[
        "stageflow"
    ] = len(results)

    return results


# ============================================================
# FINAL FILTER
# ============================================================

def final_filter(
    items
):

    results = []

    for item in items:

        t15 = item[
            "t15"
        ]

        t1 = item[
            "t1"
        ]

        t4 = item[
            "t4"
        ]

        flow = item[
            "flow"
        ]

        score = item[
            "final_score"
        ]

        change24 = item[
            "change24"
        ]

        # ====================================================
        # RSI
        # ====================================================

        rsi_ok = (

            43
            <=
            t15["rsi"]
            <=
            76

        )

        if rsi_ok:

            stats[
                "rsi_ok"
            ] += 1

        # ====================================================
        # VOLUME
        # ====================================================

        volume_ok = (

            max(

                t15["volume"],

                t1["volume"]

            )
            >=
            0.7

        )

        if volume_ok:

            stats[
                "volume_ok"
            ] += 1

        # ====================================================
        # TREND
        # ====================================================

        trend_ok = (

            t1["trend"]
            in (
                "BULL",
                "MIXED"
            )

        )

        if (

            not trend_ok

            and

            t1["trend"]
            ==
            "BEAR"

            and

            t15["trend"]
            ==
            "BULL"

        ):

            trend_ok = True

        if trend_ok:

            stats[
                "trend_ok"
            ] += 1

        # ====================================================
        # SETUP
        # ====================================================

        setup_ok = (

            t15["higher_low"]

            or

            t1["higher_low"]

            or

            t15["higher_high"]

        )

        if setup_ok:

            stats[
                "setup_ok"
            ] += 1

        # ====================================================
        # MONEY
        # ====================================================

        money_ok = False

        if flow:

            money_ok = (

                flow["net_pct"]
                >=
                2

                and

                flow["buy_share"]
                >=
                51

            )

        if money_ok:

            stats[
                "money_ok"
            ] += 1

        # ====================================================
        # OVERHEATED
        # ====================================================

        overheated = (

            t15["rsi"] > 78

            or

            t1["rsi"] > 78

        )

        if overheated:

            continue

        # ====================================================
        # BREAKOUT
        # ====================================================

        breakout = (

            t15["breakout"]

            or

            t1["breakout"]

        )

        if breakout:

            continue

        # ====================================================
        # VOLUME
        # ====================================================

        if not volume_ok:

            continue

        # ====================================================
        # RSI
        # ====================================================

        if not rsi_ok:

            continue

        # ====================================================
        # SCORE
        # ====================================================

        if score < MIN_ALERT_SCORE:

            continue

        # ====================================================
        # SETUP
        # ====================================================

        if not setup_ok:

            continue

        # ====================================================
        # 24H PUMP
        # ====================================================

        if change24 >= 50:

            continue

        # ====================================================
        # PLAN
        # ====================================================

        plan = build_plan(

            t15,
            t1,
            t4

        )

        # ====================================================
        # FLOW
        # ====================================================

        if flow:

            flow_pct = flow[
                "net_pct"
            ]

            buy_share = flow[
                "buy_share"
            ]

            open_total = flow[
                "total"
            ]

        else:

            flow_pct = 0

            buy_share = 50

            open_total = 0

        # ====================================================
        # RESULT
        # ====================================================

        result = {

            "symbol":
                item["symbol"],

            "score":
                score,

            "flow_pct":
                flow_pct,

            "buy_share":
                buy_share,

            "open_total":
                open_total,

            "rsi15":
                t15["rsi"],

            "rsi1h":
                t1["rsi"],

            "volume15":
                t15["volume"],

            "volume1h":
                t1["volume"],

            "trend1h":
                t1["trend"],

            "trend4h":
                t4["trend"],

            "change24":
                change24,

            "res_distance":
                min(

                    t15["dist_res"],

                    t1["dist_res"]

                ),

            **plan

        }

        results.append(
            result
        )

    results.sort(

        key=lambda x:
            x["score"],

        reverse=True

    )

    stats[
        "final"
    ] = len(results)

    return results


# ============================================================
# STATE LOAD
# ============================================================

def load_state():

    try:

        with open(

            STATE_FILE,

            "r",

            encoding="utf-8"

        ) as f:

            data = json.load(f)

        if isinstance(
            data,
            dict
        ):

            return data

    except Exception:

        pass

    return {}


# ============================================================
# STATE SAVE
# ============================================================

def save_state(
    state
):

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
            "STATE HATASI:",
            e
        )


# ============================================================
# ALERT CONTROL
# ============================================================

def should_alert(
    item,
    state
):

    now = int(
        time.time()
    )

    symbol = item[
        "symbol"
    ]

    old = state.get(
        symbol
    )

    if not old:

        state[
            symbol
        ] = {

            "score":
                item["score"],

            "time":
                now

        }

        return True

    old_score = int(

        old.get(
            "score",
            0
        )

    )

    old_time = int(

        old.get(
            "time",
            0
        )

    )

    # ========================================================
    # SKOR 5 PUAN ARTMIŞSA TEKRAR ALARM
    # ========================================================

    if (

        item["score"]
        >=
        old_score + 5

    ):

        state[
            symbol
        ] = {

            "score":
                item["score"],

            "time":
                now

        }

        return True

    # ========================================================
    # 30 DAKİKA GEÇMİŞSE
    # ========================================================

    if (

        now
        -
        old_time
        >=
        STATE_TTL

    ):

        state[
            symbol
        ] = {

            "score":
                item["score"],

            "time":
                now

        }

        return True

    return False


# ============================================================
# TELEGRAM
# ============================================================

def telegram(
    text
):

    if not TOKEN or not CHAT_ID:

        print(
            "Telegram TOKEN / CHAT_ID eksik."
        )

        return False

    try:

        response = session.post(

            f"https://api.telegram.org/"
            f"bot{TOKEN}/sendMessage",

            json={

                "chat_id":
                    CHAT_ID,

                "text":
                    text,

                "disable_web_page_preview":
                    True

            },

            timeout=15

        )

        return response.ok

    except Exception as e:

        print(
            "TELEGRAM HATASI:",
            e
        )

        return False


# ============================================================
# ALARM MESAJI
# ============================================================

def alert_text(
    x
):

    flow = x[
        "flow_pct"
    ]

    if flow >= 60:

        fire = "🔥🔥🔥"

    elif flow >= 35:

        fire = "🔥🔥"

    elif flow >= 15:

        fire = "🔥"

    elif flow > 0:

        fire = "⚡"

    else:

        fire = "📊"

    return (

        "🚨 PRE-PUMP V16.1\n\n"

        f"🪙 {x['symbol']}\n"

        f"⭐ GÜÇ: "
        f"{x['score']}/100\n\n"

        f"💰 PARA GİRİŞİ: "
        f"{fire} "
        f"{flow:+.1f}%\n"

        f"💵 AÇILIŞ AKIŞI: "
        f"{money(x['open_total'])}\n"

        f"🟢 ALIŞ BASKISI: "
        f"{x['buy_share']:.0f}%\n\n"

        f"📊 HACİM 15M: "
        f"{x['volume15']:.1f}x\n"

        f"📊 HACİM 1H: "
        f"{x['volume1h']:.1f}x\n"

        f"📉 RSI 15M: "
        f"{x['rsi15']:.1f}\n\n"

        "📍 GİRİŞ BÖLGESİ\n"

        f"{price(x['entry_low'])}"
        f" - "
        f"{price(x['entry_high'])}\n\n"

        "🚀 KIRILIM\n"

        f"{price(x['breakout'])}\n\n"

        "🛑 STOP\n"

        f"{price(x['stop'])}\n\n"

        f"🎯 TP1: "
        f"{price(x['tp1'])}\n"

        f"🎯 TP2: "
        f"{price(x['tp2'])}\n"

        f"🎯 TP3: "
        f"{price(x['tp3'])}\n\n"

        f"📌 DESTEK: "
        f"{price(x['support'])}\n"

        f"🎯 DİRENÇ: "
        f"{price(x['resistance'])}\n\n"

        f"📈 1H: "
        f"{x['trend1h']}\n"

        f"📈 4H: "
        f"{x['trend4h']}\n\n"

        f"📊 24H: "
        f"{x['change24']:+.1f}%\n\n"

        "⚠️ TEKNİK SİNYALDİR.\n"
        "Otomatik işlem açmaz."

    )


# ============================================================
# SUMMARY
# ============================================================

def summary_text(
    futures_count,
    candidates,
    alerts,
    duration
):

    lines = [

        "🛰 MEXC PRE-PUMP RADAR V16.1",

        "",

        f"📊 Futures: "
        f"{futures_count}",

        "",

        "🔎 KADEMELİ TARAMA",

        f"🟢 15M: "
        f"{stats['stage15']}",

        f"🟡 1H: "
        f"{stats['stage1h']}",

        f"🟠 4H: "
        f"{stats['stage4h']}",

        f"🔴 Para: "
        f"{stats['stageflow']}",

        "",

        "📡 KLINE",

        f"15M OK: "
        f"{stats['kline15']}",

        f"1H OK: "
        f"{stats['kline1h']}",

        f"4H OK: "
        f"{stats['kline4h']}",

        "",

        "📊 FİLTRE",

        f"💰 Para OK: "
        f"{stats['money_ok']}",

        f"📊 Hacim OK: "
        f"{stats['volume_ok']}",

        f"📈 Trend OK: "
        f"{stats['trend_ok']}",

        f"📉 RSI OK: "
        f"{stats['rsi_ok']}",

        f"📍 Yapı OK: "
        f"{stats['setup_ok']}",

        "",

        f"⚠️ 510: "
        f"{stats['rate_510']}",

        f"❌ API Hata: "
        f"{stats['api_error']}",

        "",

        f"🟢 UYGUN ADAY: "
        f"{len(candidates)}",

        f"🚨 YENİ ALARM: "
        f"{len(alerts)}",

        f"⏱ SÜRE: "
        f"{duration:.1f} sn"

    ]

    # ========================================================
    # EN İYİ COINLER
    # ========================================================

    if candidates:

        lines += [

            "",

            "⭐ EN İYİLER"

        ]

        for i, x in enumerate(

            candidates[:10],

            1

        ):

            lines.append(

                f"{i}. "
                f"{x['symbol']} | "
                f"{x['score']}/100 | "
                f"RSI "
                f"{x['rsi15']:.0f} | "
                f"Vol "
                f"{x['volume15']:.1f}x | "
                f"Para "
                f"{x['flow_pct']:+.0f}%"

            )

    return "\n".join(
        lines
    )


# ============================================================
# MAIN
# ============================================================

def main():

    started = time.time()

    print()

    print(
        "=" * 65
    )

    print(
        "🚀 MEXC PRE-PUMP RADAR V16.1"
    )

    print(
        "🟢 KADEMELİ TARAMA"
    )

    print(
        "120 → 40 → 20 → 10"
    )

    print(
        "🛡 RATE LIMIT KORUMALI"
    )

    print(
        "=" * 65
    )

    # ========================================================
    # CONTRACTS
    # ========================================================

    contracts = get_contracts()

    if not contracts:

        raise RuntimeError(
            "Futures alınamadı."
        )

    stats[
        "futures"
    ] = len(contracts)

    # ========================================================
    # TICKERS
    # ========================================================

    tickers = get_tickers()

    ticker_map = {

        str(

            x.get(
                "symbol",
                ""
            )

        ).upper():

        x

        for x in tickers

        if x.get(
            "symbol"
        )

    }

    # ========================================================
    # İLK SEÇİM
    # ========================================================

    candidates = []

    for symbol, contract_size in contracts.items():

        ticker = ticker_map.get(
            symbol
        )

        if not ticker:

            continue

        amount24 = fnum(

            ticker.get(
                "amount24"
            )

        )

        last = fnum(

            ticker.get(
                "lastPrice"
            )

        )

        if (

            amount24
            <
            MIN_24H_AMOUNT

            or

            last
            <=
            0

        ):

            continue

        change24 = (

            fnum(

                ticker.get(
                    "riseFallRate"
                )

            )
            *
            100

        )

        # ====================================================
        # PUMP PENALTY
        #
        # Çoktan uçmuş coinleri ilk sırada tutmuyoruz.
        # ====================================================

        pump_penalty = max(

            change24 - 10,

            0

        ) * 0.7

        rank = (

            math.log10(

                max(
                    amount24,
                    1
                )

            )
            *
            10

            -
            pump_penalty

        )

        candidates.append({

            "symbol":
                symbol,

            "contract_size":
                contract_size,

            "ticker":
                ticker,

            "rank":
                rank

        })

    candidates.sort(

        key=lambda x:
            x["rank"],

        reverse=True

    )

    candidates = candidates[
        :MAX_SYMBOLS
    ]

    print()

    print(

        f"📊 Futures: "
        f"{len(contracts)}"

    )

    print(

        f"🔎 15M taranacak: "
        f"{len(candidates)}"

    )

    # ========================================================
    # STAGE 1
    # ========================================================

    stage15 = scan_15m(
        candidates
    )

    if not stage15:

        print(
            "❌ 15M aday yok."
        )

        duration = (

            time.time()
            -
            started

        )

        telegram(

            summary_text(

                len(contracts),

                [],

                [],

                duration

            )

        )

        return

    # ========================================================
    # STAGE 2
    # ========================================================

    stage1h = scan_1h(
        stage15
    )

    if not stage1h:

        print(
            "❌ 1H aday yok."
        )

        duration = (

            time.time()
            -
            started

        )

        telegram(

            summary_text(

                len(contracts),

                [],

                [],

                duration

            )

        )

        return

    # ========================================================
    # STAGE 3
    # ========================================================

    stage4h = scan_4h(
        stage1h
    )

    if not stage4h:

        print(
            "❌ 4H aday yok."
        )

        duration = (

            time.time()
            -
            started

        )

        telegram(

            summary_text(

                len(contracts),

                [],

                [],

                duration

            )

        )

        return

    # ========================================================
    # STAGE 4
    # ========================================================

    stageflow = scan_flow(
        stage4h
    )

    # ========================================================
    # FINAL
    # ========================================================

    results = final_filter(
        stageflow
    )

    # ========================================================
    # CONSOLE
    # ========================================================

    print()

    print(
        "========== FINAL =========="
    )

    if not results:

        print(
            "❌ Final aday yok."
        )

    else:

        for i, x in enumerate(

            results,

            1

        ):

            print(

                f"{i}. "
                f"{x['symbol']} | "
                f"{x['score']}/100 | "
                f"RSI "
                f"{x['rsi15']:.1f} | "
                f"Vol "
                f"{x['volume15']:.1f}x | "
                f"Para "
                f"{x['flow_pct']:+.1f}%"

            )

    print(
        "==========================="
    )

    # ========================================================
    # STATE
    # ========================================================

    state = load_state()

    alerts = []

    for item in results:

        if should_alert(

            item,
            state

        ):

            alerts.append(
                item
            )

        if len(alerts) >= MAX_ALERTS:

            break

    save_state(
        state
    )

    stats[
        "alerts"
    ] = len(alerts)

    # ========================================================
    # TELEGRAM ALARMLARI
    # ========================================================

    for item in alerts:

        telegram(

            alert_text(
                item
            )

        )

    # ========================================================
    # SÜRE
    # ========================================================

    duration = (

        time.time()
        -
        started

    )

    # ========================================================
    # SUMMARY
    # ========================================================

    summary = summary_text(

        len(contracts),

        results,

        alerts,

        duration

    )

    telegram(
        summary
    )

    print()

    print(
        summary
    )

    print()

    print(

        f"✅ V16.1 TAMAMLANDI | "
        f"{duration:.1f} sn"

    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
