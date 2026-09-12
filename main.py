import os
import json
import math
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 🚀 MEXC PRE-PUMP RADAR V13.0
#
# LONG / PUMP ODAKLI
#
# 💰 PARA AKIŞI
# 📊 HACİM
# 📉 RSI
# 📈 15M + 1H + 4H
# 🎯 DESTEK / DİRENÇ
# 📍 GİRİŞ BÖLGESİ
# 🚀 KIRILIM
# 🛑 STOP
# 🎯 TP1 / TP2 / TP3
#
# SADECE SİNYAL ÜRETİR.
# OTOMATİK İŞLEM AÇMAZ.
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

MAX_WORKERS = 8

DEALS_LIMIT = 100

KLINE_COUNT = 90

MAX_ALERTS = 5

MIN_ALERT_SCORE = 68

MIN_24H_AMOUNT = 100_000

MIN_OPEN_NOTIONAL = 15_000

STATE_FILE = "signal_state_v13.json"

STATE_TTL = 3600


TIMEFRAMES = {

    "15M": "Min15",

    "1H": "Min60",

    "4H": "Hour4"

}


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


# ============================================================
# İSTATİSTİK
# ============================================================

stats = {

    "analyzed": 0,

    "money_ok": 0,

    "volume_ok": 0,

    "trend_ok": 0,

    "rsi_ok": 0,

    "setup_ok": 0,

    "near_resistance": 0,

    "overheated": 0,

    "final": 0

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
# SINIRLA
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

    value = fnum(
        value
    )

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

    value = fnum(
        value
    )

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

            timeout=20,

            headers={

                "User-Agent":
                    "MEXC-PRE-PUMP-RADAR/13.0"

            }

        )

        response.raise_for_status()

        return response.json()

    except Exception as e:

        print(
            "API HATASI:",
            url,
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
                0.0
            )
        )

        losses.append(
            max(
                -change,
                0.0
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
# FUTURES KONTRATLARI
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
# TICKER
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

    seconds = {

        "Min15":
            15 * 60,

        "Min60":
            60 * 60,

        "Hour4":
            4 * 60 * 60

    }[interval]

    end = int(
        time.time()
    )

    start = (

        end
        -
        (
            KLINE_COUNT
            *
            seconds
        )

    )

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

    required = [

        "open",
        "close",
        "high",
        "low",
        "vol"

    ]

    if any(

        key not in data

        for key in required

    ):

        return []

    try:

        count = min(

            len(
                data[key]
            )

            for key in required

        )

        candles = []

        for i in range(
            count
        ):

            candles.append({

                "open":
                    fnum(
                        data["open"][i]
                    ),

                "close":
                    fnum(
                        data["close"][i]
                    ),

                "high":
                    fnum(
                        data["high"][i]
                    ),

                "low":
                    fnum(
                        data["low"][i]
                    ),

                "vol":
                    fnum(
                        data["vol"][i]
                    )

            })

        return candles

    except Exception:

        return []


# ============================================================
# TIMEFRAME ANALİZ
# ============================================================

def analyze_tf(
    candles
):

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

    current_price = (
        closes[-1]
    )

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

        volume_ratio = 0.0

    if current_price > 0:

        resistance_distance = (

            (
                resistance
                /
                current_price
            )
            -
            1.0

        ) * 100.0

    else:

        resistance_distance = 999.0

    if support > 0:

        support_distance = (

            (
                current_price
                /
                support
            )
            -
            1.0

        ) * 100.0

    else:

        support_distance = 999.0

    if (

        current_price
        >
        ema9
        >
        ema21
        >
        ema50

    ):

        trend = "BULL"

    elif (

        current_price
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

    momentum = (

        closes[-1]
        >
        closes[-2]
        >
        closes[-3]

    )

    recent_move = (

        (
            closes[-1]
            /
            closes[-5]
        )
        -
        1.0

    ) * 100.0

    breakout = (

        current_price
        >
        resistance

    )

    return {

        "price":
            current_price,

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
            resistance_distance,

        "dist_sup":
            support_distance,

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
# AÇILIŞ PARA AKIŞI
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

    buy_open = 0.0

    sell_open = 0.0

    buy_count = 0

    sell_count = 0

    for trade in rows:

        trade_price = fnum(

            trade.get(
                "p"
            )

        )

        volume = fnum(

            trade.get(
                "v"
            )

        )

        trade_type = int(

            fnum(

                trade.get(
                    "T",
                    0
                )

            )

        )

        open_type = int(

            fnum(

                trade.get(
                    "O",
                    0
                )

            )

        )

        if (

            trade_price <= 0

            or

            volume <= 0

            or

            open_type != 1

        ):

            continue

        notional = (

            trade_price
            *
            volume
            *
            contract_size

        )

        if trade_type == 1:

            buy_open += notional

            buy_count += 1

        elif trade_type == 2:

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

    ) * 100.0

    buy_share = (

        buy_open
        /
        total

    ) * 100.0

    direction = (

        "LONG"

        if net >= 0

        else

        "SHORT"

    )

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
# PARA AKIŞ PUANI
# MAX 40
# ============================================================

def money_score(
    flow,
    amount24
):

    total = flow[
        "total"
    ]

    strength = abs(

        flow[
            "net_pct"
        ]

    )

    dominant = max(

        flow[
            "buy_share"
        ],

        100.0
        -
        flow[
            "buy_share"
        ]

    )

    ratio = (

        total
        /
        max(
            amount24,
            1.0
        )

    )

    score = 0

    if total >= 15_000:

        score += 6

    if total >= 30_000:

        score += 5

    if total >= 60_000:

        score += 5

    if total >= 120_000:

        score += 4

    if strength >= 10:

        score += 3

    if strength >= 20:

        score += 3

    if strength >= 35:

        score += 3

    if strength >= 50:

        score += 2

    if dominant >= 60:

        score += 2

    if dominant >= 70:

        score += 2

    if dominant >= 85:

        score += 2

    if ratio >= 0.0003:

        score += 1

    if ratio >= 0.0007:

        score += 1

    if ratio >= 0.0015:

        score += 1

    return min(
        score,
        40
    )


# ============================================================
# TEKNİK PUAN
# MAX 35
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

        score += 5

    elif t15[
        "trend"
    ] == "MIXED":

        score += 3

    if (

        48
        <=
        t15["rsi"]
        <=
        68

    ):

        score += 5

    elif (

        68
        <
        t15["rsi"]
        <=
        73

    ):

        score += 2

    if (

        t15["rsi"]
        >
        t15["rsi_prev"]

    ):

        score += 2

    if t15[
        "higher_low"
    ]:

        score += 2

    if t1[
        "higher_low"
    ]:

        score += 1

    if t15[
        "momentum"
    ]:

        score += 2

    return min(
        score,
        35
    )


# ============================================================
# HACİM PUANI
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

    if best >= 1.0:

        return 6

    if best >= 0.8:

        return 3

    return 0


# ============================================================
# SETUP PUANI
# MAX 10
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
        3

    ):

        score += 5

    elif (

        3
        <
        distance
        <=
        7

    ):

        score += 3

    elif distance < 0:

        score += 1

    if t15[
        "higher_low"
    ]:

        score += 2

    if t1[
        "higher_low"
    ]:

        score += 1

    if t15[
        "momentum"
    ]:

        score += 1

    return min(
        score,
        10
    )


# ============================================================
# GİRİŞ PLANI
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

    # --------------------------------------------------------
    # GİRİŞ BÖLGESİ
    # --------------------------------------------------------

    entry_low = max(

        support,

        current * 0.985

    )

    entry_high = min(

        current * 1.002,

        resistance * 0.998

    )

    if entry_high <= entry_low:

        entry_low = (
            current * 0.995
        )

        entry_high = (
            current * 1.002
        )

    # --------------------------------------------------------
    # KIRILIM
    # --------------------------------------------------------

    breakout = (

        resistance
        *
        1.002

    )

    # --------------------------------------------------------
    # STOP
    # --------------------------------------------------------

    risk = max(

        current - support,

        current * 0.012

    )

    stop = (

        current
        -
        (
            risk
            *
            0.80
        )

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

    ) * 100.0

    risk_pct = clamp(

        risk_pct,

        0.8,

        4.0

    )

    # --------------------------------------------------------
    # TP
    # --------------------------------------------------------

    tp1 = (

        current
        *
        (
            1.0
            +
            (
                risk_pct
                *
                1.5
                /
                100.0
            )
        )

    )

    tp2 = (

        current
        *
        (
            1.0
            +
            (
                risk_pct
                *
                2.5
                /
                100.0
            )
        )

    )

    tp3 = (

        current
        *
        (
            1.0
            +
            (
                risk_pct
                *
                4.0
                /
                100.0
            )
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
# COİN ANALİZİ
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
        # TIMEFRAME
        # ====================================================

        t15 = analyze_tf(

            get_kline(
                symbol,
                "Min15"
            )

        )

        t1 = analyze_tf(

            get_kline(
                symbol,
                "Min60"
            )

        )

        t4 = analyze_tf(

            get_kline(
                symbol,
                "Hour4"
            )

        )

        if not t15 or not t1 or not t4:

            return None

        # ====================================================
        # PARA
        # ====================================================

        flow = get_open_flow(

            symbol,

            contract_size

        )

        if not flow:

            return None

        trade_count = (

            flow["buy_count"]
            +
            flow["sell_count"]

        )

        if trade_count < 3:

            return None

        # ====================================================
        # SADECE LONG / PUMP
        # ====================================================

        if flow[
            "direction"
        ] != "LONG":

            return None

        # ====================================================
        # PUANLAR
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
        # 24H DEĞİŞİM
        # ====================================================

        change24 = abs(

            fnum(

                ticker.get(
                    "riseFallRate"
                )

            )
            *
            100.0

        )

        # ====================================================
        # AŞIRI ISINMA
        # ====================================================

        overheated = (

            t15["rsi"] > 78

            or

            t1["rsi"] > 78

        )

        # ====================================================
        # KIRILMIŞ MI?
        # ====================================================

        breakout = (

            t15["breakout"]

            or

            t1["breakout"]

        )

        # ====================================================
        # PUMP SONRASI CEZA
        # ====================================================

        penalty = 0

        if change24 >= 20:

            penalty += 5

        if change24 >= 35:

            penalty += 8

        if change24 >= 50:

            penalty += 10

        if overheated:

            penalty += 15

        if breakout:

            penalty += 7

        # ====================================================
        # TOPLAM
        #
        # PARA       40
        # TEKNİK     35
        # HACİM      15
        # SETUP      10
        #
        # = 100
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
        # KONTROLLER
        # ====================================================

        money_ok = (

            flow["total"]
            >=
            MIN_OPEN_NOTIONAL

            and

            flow["net_pct"]
            >=
            8

            and

            flow["buy_share"]
            >=
            56

        )

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

        rsi_ok = (

            45
            <=
            t15["rsi"]
            <=
            75

        )

        volume_ok = (

            max(

                t15["volume"],

                t1["volume"]

            )
            >=
            0.8

        )

        near_resistance = (

            min(

                t15["dist_res"],

                t1["dist_res"]

            )
            <=
            7

        )

        setup_ok = (

            t15["higher_low"]

            or

            t1["higher_low"]

        )

        # ====================================================
        # İSTATİSTİK
        # ====================================================

        if money_ok:

            stats[
                "money_ok"
            ] += 1

        if trend_ok:

            stats[
                "trend_ok"
            ] += 1

        if rsi_ok:

            stats[
                "rsi_ok"
            ] += 1

        if volume_ok:

            stats[
                "volume_ok"
            ] += 1

        if near_resistance:

            stats[
                "near_resistance"
            ] += 1

        if setup_ok:

            stats[
                "setup_ok"
            ] += 1

        if overheated:

            stats[
                "overheated"
            ] += 1

        # ====================================================
        # SON FİLTRE
        #
        # Para kesinlikle güçlü olacak.
        # Diğerleri beraber çalışacak.
        # ====================================================

        candidate = (

            money_ok

            and

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

            trend_ok

        )

        if not candidate:

            return None

        # ====================================================
        # GİRİŞ PLANI
        # ====================================================

        plan = build_plan(

            t15,
            t1,
            t4

        )

        stats[
            "final"
        ] += 1

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
                flow["net_pct"],

            "buy_share":
                flow["buy_share"],

            "open_total":
                flow["total"],

            "buy_open":
                flow["buy"],

            "sell_open":
                flow["sell"],

            "buy_count":
                flow["buy_count"],

            "sell_count":
                flow["sell_count"],

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
                min(

                    t15["dist_res"],

                    t1["dist_res"]

                ),

            "status":
                "PRE-PUMP",

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


# ============================================================
# STATE KAYDET
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
# ALARM KONTROL
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

    state[
        symbol
    ] = {

        "score":
            item["score"],

        "time":
            now

    }

    if not old:

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

        return True

    if (

        now
        -
        old_time
        >=
        STATE_TTL

    ):

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
# TELEGRAM ALARM
# ============================================================

def alert_text(
    x
):

    flow = x[
        "flow_pct"
    ]

    if flow >= 60:

        fire = (
            "🔥🔥🔥"
        )

    elif flow >= 35:

        fire = (
            "🔥🔥"
        )

    elif flow >= 15:

        fire = (
            "🔥"
        )

    else:

        fire = (
            "⚡"
        )

    return (

        "🚨 PRE-PUMP\n\n"

        f"🪙 {x['symbol']}\n"

        f"⭐ {x['score']}/100\n\n"

        f"💰 Para Girişi: "
        f"{fire} "
        f"+{flow:.1f}%\n"

        f"💵 Açılış Akışı: "
        f"{money(x['open_total'])}\n"

        f"📈 Alış Baskısı: "
        f"{x['buy_share']:.0f}%\n"

        f"📊 Hacim 15M: "
        f"{x['volume15']:.1f}x\n"

        f"📊 Hacim 1H: "
        f"{x['volume1h']:.1f}x\n"

        f"📉 RSI 15M: "
        f"{x['rsi15']:.1f}\n\n"

        "📍 GİRİŞ BÖLGESİ\n"

        f"{price(x['entry_low'])}"
        f" – "
        f"{price(x['entry_high'])}\n\n"

        "🚀 KIRILIM GİRİŞİ\n"

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
# TELEGRAM ÖZET
# ============================================================

def summary_text(
    futures_count,
    candidates,
    alerts,
    duration
):

    lines = [

        "🛰 MEXC PRE-PUMP RADAR V13.0",

        "",

        f"📊 Futures: "
        f"{futures_count}",

        f"🔎 Analiz: "
        f"{stats['analyzed']}",

        "",

        f"💰 Para akışı OK: "
        f"{stats['money_ok']}",

        f"📊 Hacim OK: "
        f"{stats['volume_ok']}",

        f"📈 Trend OK: "
        f"{stats['trend_ok']}",

        f"📉 RSI OK: "
        f"{stats['rsi_ok']}",

        f"🎯 Direnç yakın: "
        f"{stats['near_resistance']}",

        f"📍 Yapı OK: "
        f"{stats['setup_ok']}",

        f"🔥 Aşırı sıcak: "
        f"{stats['overheated']}",

        "",

        f"🟢 Uygun aday: "
        f"{len(candidates)}",

        f"🚨 Yeni alarm: "
        f"{len(alerts)}",

        f"⏱ Süre: "
        f"{duration:.1f} sn"

    ]

    if candidates:

        lines += [

            "",

            "⭐ EN İYİLER"

        ]

        for i, item in enumerate(

            candidates[:10],

            1

        ):

            lines.append(

                f"{i}. "
                f"{item['symbol']} | "
                f"{item['score']}/100 | "
                f"Para "
                f"+{item['flow_pct']:.0f}% | "
                f"{money(item['open_total'])}"

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
        "=" * 60
    )

    print(
        "🚀 MEXC PRE-PUMP RADAR V13.0"
    )

    print(
        "💰 PARA AKIŞI ODAKLI"
    )

    print(
        "🟢 LONG / PUMP"
    )

    print(
        "📊 15M + 1H + 4H"
    )

    print(
        "=" * 60
    )

    print()

    # ========================================================
    # CONTRACT
    # ========================================================

    contracts = get_contracts()

    if not contracts:

        raise RuntimeError(

            "Futures kontratları alınamadı."

        )

    # ========================================================
    # TICKER
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
    # ÖN ELEME
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

        change24 = abs(

            fnum(

                ticker.get(
                    "riseFallRate"
                )

            )
            *
            100.0

        )

        # Likidite öncelikli.
        # Çoktan dikey gidenlere hafif ceza.

        rank = (

            math.log10(

                max(
                    amount24,
                    1.0
                )

            )
            *
            10.0

            -

            max(
                change24 - 15.0,
                0.0
            )
            *
            0.7

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

        f"🔎 Detaylı analiz: "
        f"{len(pre_candidates)}"

    )

    print()

    # ========================================================
    # ANALİZ
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

                result = (
                    future.result()
                )

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
    # SIRALAMA
    # ========================================================

    results.sort(

        key=lambda x: (

            x["score"],

            x["money_score"],

            x["open_total"]

        ),

        reverse=True

    )

    # ========================================================
    # EN İYİ ADAYLAR
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

                f"Money "
                f"{item['money_score']} | "

                f"Para "
                f"+{item['flow_pct']:.1f}% | "

                f"Open "
                f"{money(item['open_total'])} | "

                f"RSI "
                f"{item['rsi15']:.1f} | "

                f"Hacim "
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

    save_state(
        state
    )

    alerts = alerts[
        :MAX_ALERTS
    ]

    # ========================================================
    # ALARMLAR
    # ========================================================

    for item in alerts:

        print(

            "🚨 ALARM:",

            item["symbol"],

            item["score"]

        )

        telegram(

            alert_text(
                item
            )

        )

    # ========================================================
    # FİLTRE RAPORU
    # ========================================================

    duration = (

        time.time()
        -
        started

    )

    print()

    print(
        "========== FİLTRE RAPORU =========="
    )

    print(

        "💰 Para akışı OK:",

        stats["money_ok"]

    )

    print(

        "📊 Hacim OK:",

        stats["volume_ok"]

    )

    print(

        "📈 Trend OK:",

        stats["trend_ok"]

    )

    print(

        "📉 RSI OK:",

        stats["rsi_ok"]

    )

    print(

        "🎯 Direnç yakın:",

        stats["near_resistance"]

    )

    print(

        "📍 Yapı OK:",

        stats["setup_ok"]

    )

    print(

        "🔥 Aşırı sıcak:",

        stats["overheated"]

    )

    print(

        "🟢 Final aday:",

        len(results)

    )

    print(

        "🚨 Yeni alarm:",

        len(alerts)

    )

    print(
        "==================================="
    )

    # ========================================================
    # ÖZET
    # ========================================================

    if alerts:

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

        f"✅ RADAR BİTTİ | "
        f"{duration:.1f} sn"

    )


# ============================================================
# BAŞLAT
# ============================================================

if __name__ == "__main__":

    main()
