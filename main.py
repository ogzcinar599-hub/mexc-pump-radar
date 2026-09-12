import os
import json
import math
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PRE-PUMP RADAR V15.0
#
# VERİ + TEKNİK + PARA AKIŞI
#
# 15M + 1H + 4H
# RSI
# HACİM
# MOMENTUM
# EMA
# HIGHER LOW
# PARA AKIŞI
# DESTEK / DİRENÇ
#
# V15:
# ✅ KLINE DIAGNOSTIC
# ✅ MS / SEC FALLBACK
# ✅ TIMEFRAME DURUMU
# ✅ API HATA RAPORU
# ✅ SESSİZ ELEME YOK
# ============================================================


BASE = "https://api.mexc.com"


TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)


# ============================================================
# AYARLAR
# ============================================================

MAX_SYMBOLS = 120

MAX_WORKERS = 6

DEALS_LIMIT = 100

KLINE_COUNT = 90

MAX_ALERTS = 5

MIN_ALERT_SCORE = 60

MIN_24H_AMOUNT = 100_000

MIN_OPEN_NOTIONAL = 10_000

STATE_FILE = "signal_state_v15.json"

STATE_TTL = 1800


# ============================================================
# TIMEFRAMES
# ============================================================

TIMEFRAMES = {

    "15M": "Min15",

    "1H": "Min60",

    "4H": "Hour4"

}


# ============================================================
# BAD ENSTRÜMANLAR
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
        "Mozilla/5.0 MEXC-PRE-PUMP-RADAR/15.0",

    "Accept":
        "application/json"

})


# ============================================================
# İSTATİSTİK
# ============================================================

stats = {

    "analyzed": 0,

    "kline15_ok": 0,

    "kline1h_ok": 0,

    "kline4h_ok": 0,

    "all_kline_ok": 0,

    "money_ok": 0,

    "volume_ok": 0,

    "trend_ok": 0,

    "rsi_ok": 0,

    "setup_ok": 0,

    "near_resistance": 0,

    "overheated": 0,

    "breakout": 0,

    "final": 0,

    "kline_error": 0,

    "flow_error": 0

}


# ============================================================
# KLINE HATA SAYACI
# ============================================================

kline_errors = {}


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
# MONEY
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
# PRICE
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
# API
# ============================================================

def api_get(
    url,
    params=None
):

    try:

        response = session.get(

            url,

            params=params,

            timeout=15

        )

        if not response.ok:

            print(

                "API HTTP:",
                response.status_code,
                url

            )

            return None

        try:

            return response.json()

        except Exception:

            print(
                "JSON HATASI:",
                url
            )

            return None

    except Exception as e:

        print(
            "API HATASI:",
            e
        )

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
            * k

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
# 🔥 KLINE V15
#
# Önce saniye dener.
# Sonuç yoksa milisaniye dener.
#
# Böylece timestamp problemi varsa
# direkt yakalıyoruz.
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

    start_sec = (

        now
        -
        (
            KLINE_COUNT
            *
            candle_seconds
        )

    )

    end_sec = now

    attempts = [

        (
            "SECONDS",
            start_sec,
            end_sec
        ),

        (
            "MILLISECONDS",
            start_sec * 1000,
            end_sec * 1000
        )

    ]

    for mode, start, end in attempts:

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

            continue

        # ====================================================
        # API ERROR
        # ====================================================

        if data.get(
            "success"
        ) is False:

            error_code = str(

                data.get(
                    "code",
                    data.get(
                        "errorCode",
                        "UNKNOWN"
                    )
                )

            )

            key = (

                f"{interval}:"
                f"{error_code}"

            )

            kline_errors[key] = (

                kline_errors.get(
                    key,
                    0
                )
                +
                1

            )

            continue

        # ====================================================
        # DATA
        # ====================================================

        raw = data.get(
            "data"
        )

        if not isinstance(
            raw,
            dict
        ):

            continue

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

            continue

        try:

            count = min(

                len(
                    raw[key]
                )

                for key in required

            )

        except Exception:

            continue

        if count < 60:

            continue

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

        if len(candles) >= 60:

            return candles

    # ========================================================
    # TAMAMEN BAŞARISIZ
    # ========================================================

    stats[
        "kline_error"
    ] += 1

    return []


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
        20.0

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
    # BREAKOUT
    # ========================================================

    breakout = (

        current
        >
        resistance

    )

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

    if net > 0:

        direction = "LONG"

    elif net < 0:

        direction = "SHORT"

    else:

        direction = "NEUTRAL"

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
            sell_count,

        "direction":
            direction

    }


# ============================================================
# MONEY SCORE
# MAX 30
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

        score += 3

    if net_pct >= 15:

        score += 3

    if net_pct >= 25:

        score += 3

    if buy_share >= 52:

        score += 1

    if buy_share >= 56:

        score += 1

    if buy_share >= 62:

        score += 1

    if buy_share >= 70:

        score += 1

    ratio = (

        total
        /
        max(
            amount24,
            1
        )

    )

    if ratio >= 0.0002:

        score += 1

    if ratio >= 0.0005:

        score += 1

    if ratio >= 0.001:

        score += 1

    return min(
        score,
        30
    )


# ============================================================
# TECHNICAL SCORE
# MAX 40
# ============================================================

def technical_score(
    t15,
    t1,
    t4
):

    score = 0

    if t4[
        "trend"
    ] == "BULL":

        score += 8

    elif t4[
        "trend"
    ] == "MIXED":

        score += 5

    if t1[
        "trend"
    ] == "BULL":

        score += 8

    elif t1[
        "trend"
    ] == "MIXED":

        score += 5

    if t15[
        "trend"
    ] == "BULL":

        score += 6

    elif t15[
        "trend"
    ] == "MIXED":

        score += 4

    if (

        43
        <=
        t15["rsi"]
        <=
        68

    ):

        score += 6

    elif (

        68
        <
        t15["rsi"]
        <=
        75

    ):

        score += 3

    if (

        t15["rsi"]
        >
        t15["rsi_prev"]

    ):

        score += 3

    if t15[
        "higher_low"
    ]:

        score += 3

    if t1[
        "higher_low"
    ]:

        score += 2

    if t15[
        "higher_high"
    ]:

        score += 1

    if t15[
        "momentum"
    ]:

        score += 2

    return min(
        score,
        40
    )


# ============================================================
# VOLUME SCORE
# MAX 15
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
# SETUP SCORE
# MAX 15
# ============================================================

def setup_score(
    t15,
    t1,
    t4
):

    score = 0

    distance = min(

        t15["dist_res"],

        t1["dist_res"]

    )

    if (

        0
        <=
        distance
        <=
        2

    ):

        score += 5

    elif (

        2
        <
        distance
        <=
        5

    ):

        score += 4

    elif (

        5
        <
        distance
        <=
        8

    ):

        score += 2

    if t15[
        "higher_low"
    ]:

        score += 3

    if t1[
        "higher_low"
    ]:

        score += 2

    if t15[
        "higher_high"
    ]:

        score += 1

    if t15[
        "momentum"
    ]:

        score += 2

    if (

        t4["trend"]
        ==
        "MIXED"

        and

        t1["higher_low"]

    ):

        score += 2

    return min(
        score,
        15
    )


# ============================================================
# PLAN
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
            min(
                entry_low,
                entry_high
            ),

        "entry_high":
            max(
                entry_low,
                entry_high
            ),

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
# ANALİZ
# ============================================================

def analyze_symbol(
    symbol,
    contract_size,
    ticker
):

    try:

        amount24 = fnum(

            ticker.get(
                "amount24"
            )

        )

        last_price = fnum(

            ticker.get(
                "lastPrice"
            )

        )

        if (

            amount24
            <
            MIN_24H_AMOUNT

            or

            last_price
            <=
            0

        ):

            return None

        # ====================================================
        # KLINE
        # ====================================================

        c15 = get_kline(
            symbol,
            "Min15"
        )

        c1 = get_kline(
            symbol,
            "Min60"
        )

        c4 = get_kline(
            symbol,
            "Hour4"
        )

        if c15:

            stats[
                "kline15_ok"
            ] += 1

        if c1:

            stats[
                "kline1h_ok"
            ] += 1

        if c4:

            stats[
                "kline4h_ok"
            ] += 1

        if not c15:

            return None

        if not c1:

            return None

        if not c4:

            return None

        stats[
            "all_kline_ok"
        ] += 1

        t15 = analyze_tf(
            c15
        )

        t1 = analyze_tf(
            c1
        )

        t4 = analyze_tf(
            c4
        )

        if not t15:

            return None

        if not t1:

            return None

        if not t4:

            return None

        # ====================================================
        # PARA AKIŞI
        # ====================================================

        flow = get_open_flow(

            symbol,

            contract_size

        )

        if not flow:

            stats[
                "flow_error"
            ] += 1

        # ====================================================
        # SCORE
        # ====================================================

        money_points = money_score(

            flow,

            amount24

        )

        technical_points = technical_score(

            t15,
            t1,
            t4

        )

        volume_points = volume_score(

            t15,
            t1

        )

        setup_points = setup_score(

            t15,
            t1,
            t4

        )

        # ====================================================
        # 24H
        # ====================================================

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
        # OVERHEATED
        # ====================================================

        overheated = (

            t15["rsi"] > 78

            or

            t1["rsi"] > 78

        )

        # ====================================================
        # BREAKOUT
        # ====================================================

        breakout = (

            t15["breakout"]

            or

            t1["breakout"]

        )

        # ====================================================
        # PENALTY
        # ====================================================

        penalty = 0

        if change24 >= 15:

            penalty += 3

        if change24 >= 25:

            penalty += 5

        if change24 >= 40:

            penalty += 8

        if change24 >= 60:

            penalty += 10

        if overheated:

            penalty += 15

        if breakout:

            penalty += 8

        # ====================================================
        # TOTAL
        # ====================================================

        raw_score = (

            money_points
            +
            technical_points
            +
            volume_points
            +
            setup_points

        )

        final_score = int(

            clamp(

                round(
                    raw_score
                    -
                    penalty
                ),

                0,

                100

            )

        )

        # ====================================================
        # MONEY OK
        # ====================================================

        money_ok = False

        if flow:

            money_ok = (

                flow["total"]
                >=
                MIN_OPEN_NOTIONAL

                and

                flow["net_pct"]
                >=
                2

                and

                flow["buy_share"]
                >=
                51

            )

        # ====================================================
        # TREND
        # ====================================================

        trend_ok = (

            t4["trend"]
            in (
                "BULL",
                "MIXED"
            )

            and

            t1["trend"]
            in (
                "BULL",
                "MIXED"
            )

        )

        # ====================================================
        # RECOVERY
        # ====================================================

        if not trend_ok:

            if (

                t1["trend"]
                ==
                "BULL"

                and

                t15["trend"]
                !=
                "BEAR"

            ):

                trend_ok = True

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

        # ====================================================
        # RESISTANCE
        # ====================================================

        res_distance = min(

            t15["dist_res"],

            t1["dist_res"]

        )

        near_resistance = (

            res_distance
            <=
            8

        )

        # ====================================================
        # STRUCTURE
        # ====================================================

        setup_ok = (

            t15["higher_low"]

            or

            t1["higher_low"]

            or

            t15["higher_high"]

        )

        # ====================================================
        # STATS
        # ====================================================

        if money_ok:

            stats[
                "money_ok"
            ] += 1

        if volume_ok:

            stats[
                "volume_ok"
            ] += 1

        if trend_ok:

            stats[
                "trend_ok"
            ] += 1

        if rsi_ok:

            stats[
                "rsi_ok"
            ] += 1

        if setup_ok:

            stats[
                "setup_ok"
            ] += 1

        if near_resistance:

            stats[
                "near_resistance"
            ] += 1

        if overheated:

            stats[
                "overheated"
            ] += 1

        if breakout:

            stats[
                "breakout"
            ] += 1

        # ====================================================
        # FINAL
        # ====================================================

        technical_ready = (

            technical_points
            >=
            24

            and

            volume_ok

            and

            rsi_ok

        )

        money_ready = (

            money_ok

            and

            technical_points
            >=
            18

            and

            volume_ok

        )

        structure_ready = (

            setup_ok

            and

            volume_ok

            and

            rsi_ok

            and

            trend_ok

            and

            final_score
            >=
            MIN_ALERT_SCORE

        )

        candidate = (

            final_score
            >=
            MIN_ALERT_SCORE

            and

            not overheated

            and

            not breakout

            and

            volume_ok

            and

            (

                technical_ready

                or

                money_ready

                or

                structure_ready

            )

        )

        if not candidate:

            return None

        # ====================================================
        # PLAN
        # ====================================================

        plan = build_plan(

            t15,
            t1,
            t4

        )

        stats[
            "final"
        ] += 1

        # ====================================================
        # FLOW DATA
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

        return {

            "symbol":
                symbol,

            "score":
                final_score,

            "money_score":
                money_points,

            "technical_score":
                technical_points,

            "volume_score":
                volume_points,

            "setup_score":
                setup_points,

            "flow_pct":
                flow_pct,

            "buy_share":
                buy_share,

            "open_total":
                open_total,

            "amount24":
                amount24,

            "change24":
                change24,

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

            "res_distance":
                res_distance,

            **plan

        }

    except Exception as e:

        print(
            symbol,
            "ANALİZ HATASI:",
            e
        )

        return None

    finally:

        stats[
            "analyzed"
        ] += 1


# ============================================================
# STATE
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
# ALERT STATE
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

        if not response.ok:

            print(
                "TELEGRAM HATASI:",
                response.text
            )

            return False

        return True

    except Exception as e:

        print(
            "TELEGRAM HATASI:",
            e
        )

        return False


# ============================================================
# ALERT TEXT
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

        "🚨 PRE-PUMP V15\n\n"

        f"🪙 {x['symbol']}\n"

        f"⭐ Güç: {x['score']}/100\n\n"

        f"💰 Para Girişi: "
        f"{fire} "
        f"{flow:+.1f}%\n"

        f"💵 Açılış Akışı: "
        f"{money(x['open_total'])}\n"

        f"🟢 Alış Baskısı: "
        f"{x['buy_share']:.0f}%\n\n"

        f"📊 Hacim 15M: "
        f"{x['volume15']:.1f}x\n"

        f"📊 Hacim 1H: "
        f"{x['volume1h']:.1f}x\n"

        f"📉 RSI 15M: "
        f"{x['rsi15']:.1f}\n\n"

        "📍 GİRİŞ\n"

        f"{price(x['entry_low'])}"
        f" – "
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

        f"📌 Destek: "
        f"{price(x['support'])}\n"

        f"🎯 Direnç: "
        f"{price(x['resistance'])}\n\n"

        f"📈 1H: "
        f"{x['trend1h']} | "

        f"4H: "
        f"{x['trend4h']}\n\n"

        "⚠️ Teknik sinyaldir.\n"
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

        "🛰 MEXC PRE-PUMP RADAR V15",

        "",

        f"📊 Futures: "
        f"{futures_count}",

        f"🔎 Analiz: "
        f"{stats['analyzed']}",

        "",

        "🧪 VERİ KONTROLÜ",

        f"🕐 15M OK: "
        f"{stats['kline15_ok']}",

        f"🕐 1H OK: "
        f"{stats['kline1h_ok']}",

        f"🕐 4H OK: "
        f"{stats['kline4h_ok']}",

        f"🟢 3 TF OK: "
        f"{stats['all_kline_ok']}",

        f"❌ Kline hata: "
        f"{stats['kline_error']}",

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

        f"🎯 Direnç yakın: "
        f"{stats['near_resistance']}",

        f"🔥 Aşırı sıcak: "
        f"{stats['overheated']}",

        f"🚀 Kırılmış: "
        f"{stats['breakout']}",

        "",

        f"🟢 Uygun aday: "
        f"{len(candidates)}",

        f"🚨 Yeni alarm: "
        f"{len(alerts)}",

        f"⏱ Süre: "
        f"{duration:.1f} sn"

    ]

    # ========================================================
    # KLINE HATALARI
    # ========================================================

    if kline_errors:

        lines += [

            "",

            "⚠️ KLINE HATALARI"

        ]

        for key, count in list(

            kline_errors.items()
        )[:5]:

            lines.append(

                f"{key}: {count}"

            )

    # ========================================================
    # ADAYLAR
    # ========================================================

    if candidates:

        lines += [

            "",

            "⭐ EN İYİ ADAYLAR"

        ]

        for i, item in enumerate(

            candidates[:10],

            1

        ):

            lines.append(

                f"{i}. "
                f"{item['symbol']} | "
                f"{item['score']}/100 | "
                f"RSI "
                f"{item['rsi15']:.0f} | "
                f"Vol "
                f"{item['volume15']:.1f}x | "
                f"Para "
                f"{item['flow_pct']:+.0f}%"

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
        "🚀 MEXC PRE-PUMP RADAR V15.0"
    )

    print(
        "🧪 KLINE DIAGNOSTIC AKTİF"
    )

    print(
        "📊 15M + 1H + 4H"
    )

    print(
        "⭐ MIN SCORE:",
        MIN_ALERT_SCORE
    )

    print(
        "=" * 65
    )

    print()

    # ========================================================
    # CONTRACTS
    # ========================================================

    contracts = get_contracts()

    if not contracts:

        raise RuntimeError(
            "Futures kontratları alınamadı."
        )

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
    # PRE FILTER
    # ========================================================

    pre_candidates = []

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

        pump_penalty = max(

            change24 - 12,

            0

        ) * 0.5

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

        pre_candidates.append(

            (
                rank,

                symbol,

                contract_size,

                ticker

            )

        )

    pre_candidates.sort(
        reverse=True
    )

    pre_candidates = pre_candidates[
        :MAX_SYMBOLS
    ]

    print(

        f"📊 Futures: "
        f"{len(contracts)}"

    )

    print(

        f"📡 Ticker: "
        f"{len(tickers)}"

    )

    print(

        f"🔎 Analiz: "
        f"{len(pre_candidates)}"

    )

    print()

    # ========================================================
    # ANALYSIS
    # ========================================================

    results = []

    with ThreadPoolExecutor(

        max_workers=MAX_WORKERS

    ) as executor:

        jobs = {

            executor.submit(

                analyze_symbol,

                symbol,

                contract_size,

                ticker

            ): symbol

            for
            _rank,
            symbol,
            contract_size,
            ticker

            in pre_candidates

        }

        for future in as_completed(
            jobs
        ):

            try:

                result = future.result()

                if result:

                    results.append(
                        result
                    )

            except Exception as e:

                print(

                    jobs[future],
                    "HATA:",
                    e

                )

    # ========================================================
    # SORT
    # ========================================================

    results.sort(

        key=lambda x: (

            x["score"],

            x["technical_score"],

            x["money_score"],

            x["volume_score"]

        ),

        reverse=True

    )

    # ========================================================
    # PRINT RESULTS
    # ========================================================

    print()

    print(
        "========== EN İYİ ADAYLAR =========="
    )

    if not results:

        print(
            "❌ Uygun aday yok."
        )

    else:

        for i, item in enumerate(

            results[:15],

            1

        ):

            print(

                f"{i}. "
                f"{item['symbol']} | "
                f"{item['score']}/100 | "
                f"Tech "
                f"{item['technical_score']} | "
                f"Money "
                f"{item['money_score']} | "
                f"RSI "
                f"{item['rsi15']:.1f} | "
                f"Vol "
                f"{item['volume15']:.1f}x"

            )

    print(
        "===================================="
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

    # ========================================================
    # SEND ALERTS
    # ========================================================

    for item in alerts:

        telegram(

            alert_text(
                item
            )

        )

    # ========================================================
    # DURATION
    # ========================================================

    duration = (

        time.time()
        -
        started

    )

    # ========================================================
    # CONSOLE
    # ========================================================

    print()

    print(
        "========== V15 RAPOR =========="
    )

    print(
        "15M OK:",
        stats["kline15_ok"]
    )

    print(
        "1H OK:",
        stats["kline1h_ok"]
    )

    print(
        "4H OK:",
        stats["kline4h_ok"]
    )

    print(
        "3 TF OK:",
        stats["all_kline_ok"]
    )

    print(
        "Kline hata:",
        stats["kline_error"]
    )

    print(
        "Para OK:",
        stats["money_ok"]
    )

    print(
        "Hacim OK:",
        stats["volume_ok"]
    )

    print(
        "Trend OK:",
        stats["trend_ok"]
    )

    print(
        "RSI OK:",
        stats["rsi_ok"]
    )

    print(
        "Yapı OK:",
        stats["setup_ok"]
    )

    print(
        "Final:",
        len(results)
    )

    print(
        "Alarm:",
        len(alerts)
    )

    print(
        "==============================="
    )

    # ========================================================
    # TELEGRAM SUMMARY
    # ========================================================

    telegram(

        summary_text(

            len(contracts),

            results,

            alerts,

            duration

        )

    )

    print()

    print(

        f"✅ V15 TAMAMLANDI | "
        f"{duration:.1f} sn"

    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
