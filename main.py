import os
import json
import math
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PRE-PUMP RADAR V14.0
#
# AMAÇ:
# 🚀 PUMP BAŞLAMADAN ÖNCE GÜÇLENEN COİNLERİ BULMAK
#
# 15M + 1H + 4H
# RSI
# HACİM
# MOMENTUM
# EMA TREND
# HIGHER LOW
# PARA AKIŞI
# DESTEK / DİRENÇ
#
# PARA AKIŞI ARTIK ZORUNLU TEK FİLTRE DEĞİL.
# SKOR SİSTEMİ İLE ÇALIŞIR.
#
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


# 🔥 ESKİ: 68
# 🔥 YENİ: 60
MIN_ALERT_SCORE = 60


# ============================================================
# LİKİDİTE
# ============================================================

MIN_24H_AMOUNT = 100_000

MIN_OPEN_NOTIONAL = 10_000


# ============================================================
# STATE
# ============================================================

STATE_FILE = "signal_state_v14.json"

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

    "breakout": 0,

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
                    "MEXC-PRE-PUMP-RADAR/14.0"

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
# TIMEFRAME ANALİZİ
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

    current_price = closes[-1]

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

    # ========================================================
    # TREND
    # ========================================================

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
    # SON HAREKET
    # ========================================================

    recent_move = (

        (
            closes[-1]
            /
            closes[-5]
        )
        -
        1.0

    ) * 100.0

    # ========================================================
    # KIRILIM
    # ========================================================

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
# PARA AKIŞ PUANI
#
# SADECE POZİTİF PARA AKIŞI PUAN ALIR.
# MAX 30
# ============================================================

def money_score(
    flow,
    amount24
):

    if not flow:

        return 0

    total = flow[
        "total"
    ]

    net_pct = flow[
        "net_pct"
    ]

    buy_share = flow[
        "buy_share"
    ]

    # SHORT AKIŞA PUAN YOK
    if net_pct <= 0:

        return 0

    score = 0

    # --------------------------------------------------------
    # AKIŞ BÜYÜKLÜĞÜ
    # --------------------------------------------------------

    if total >= 10_000:

        score += 4

    if total >= 25_000:

        score += 4

    if total >= 50_000:

        score += 4

    if total >= 100_000:

        score += 3

    # --------------------------------------------------------
    # NET PARA
    # --------------------------------------------------------

    if net_pct >= 3:

        score += 2

    if net_pct >= 8:

        score += 3

    if net_pct >= 15:

        score += 3

    if net_pct >= 25:

        score += 3

    # --------------------------------------------------------
    # ALIŞ BASKISI
    # --------------------------------------------------------

    if buy_share >= 52:

        score += 1

    if buy_share >= 56:

        score += 1

    if buy_share >= 62:

        score += 1

    if buy_share >= 70:

        score += 1

    # --------------------------------------------------------
    # 24H HACME GÖRE AKIŞ
    # --------------------------------------------------------

    ratio = (

        total
        /
        max(
            amount24,
            1.0
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
# TEKNİK PUAN
#
# MAX 40
# ============================================================

def technical_score(
    t15,
    t1,
    t4
):

    score = 0

    # ========================================================
    # 4H
    # ========================================================

    if t4[
        "trend"
    ] == "BULL":

        score += 8

    elif t4[
        "trend"
    ] == "MIXED":

        score += 5

    # ========================================================
    # 1H
    # ========================================================

    if t1[
        "trend"
    ] == "BULL":

        score += 8

    elif t1[
        "trend"
    ] == "MIXED":

        score += 5

    # ========================================================
    # 15M
    # ========================================================

    if t15[
        "trend"
    ] == "BULL":

        score += 6

    elif t15[
        "trend"
    ] == "MIXED":

        score += 4

    # ========================================================
    # RSI
    # ========================================================

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

    # ========================================================
    # RSI YÜKSELİYOR
    # ========================================================

    if (

        t15["rsi"]
        >
        t15["rsi_prev"]

    ):

        score += 3

    # ========================================================
    # HIGHER LOW
    # ========================================================

    if t15[
        "higher_low"
    ]:

        score += 3

    if t1[
        "higher_low"
    ]:

        score += 2

    # ========================================================
    # HIGHER HIGH
    # ========================================================

    if t15[
        "higher_high"
    ]:

        score += 1

    # ========================================================
    # MOMENTUM
    # ========================================================

    if t15[
        "momentum"
    ]:

        score += 2

    return min(
        score,
        40
    )


# ============================================================
# HACİM PUANI
#
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

        return 7

    if best >= 0.8:

        return 5

    if best >= 0.7:

        return 3

    return 0


# ============================================================
# SETUP PUANI
#
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

    # ========================================================
    # DİRENCİNE YAKLAŞAN
    # ========================================================

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

    # ========================================================
    # HIGHER LOW
    # ========================================================

    if t15[
        "higher_low"
    ]:

        score += 3

    if t1[
        "higher_low"
    ]:

        score += 2

    # ========================================================
    # HIGHER HIGH
    # ========================================================

    if t15[
        "higher_high"
    ]:

        score += 1

    # ========================================================
    # MOMENTUM
    # ========================================================

    if t15[
        "momentum"
    ]:

        score += 2

    # ========================================================
    # 4H MIXED BİLE OLSA YAPI OLUMLUYSA
    # ========================================================

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

    # ========================================================
    # GİRİŞ
    # ========================================================

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

    # ========================================================
    # KIRILIM
    # ========================================================

    breakout = (

        resistance
        *
        1.002

    )

    # ========================================================
    # STOP
    # ========================================================

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

    # ========================================================
    # TP
    # ========================================================

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
        # PARA AKIŞI
        # ====================================================

        flow = get_open_flow(

            symbol,

            contract_size

        )

        # Para akışı yoksa coin tamamen elenmez.
        # 0 puanla devam eder.

        if flow:

            trade_count = (

                flow["buy_count"]
                +
                flow["sell_count"]

            )

            if trade_count < 3:

                flow = None

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

        change24 = (

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
        # KIRILIM
        # ========================================================

        breakout = (

            t15["breakout"]

            or

            t1["breakout"]

        )

        # ====================================================
        # PUMP SONRASI CEZA
        # ====================================================

        penalty = 0

        # Çoktan hareket etmişse ceza.
        if change24 >= 15:

            penalty += 3

        if change24 >= 25:

            penalty += 5

        if change24 >= 40:

            penalty += 8

        if change24 >= 60:

            penalty += 10

        # RSI aşırı sıcak
        if overheated:

            penalty += 15

        # Direnç kırılmışsa pre-pump değildir.
        if breakout:

            penalty += 8

        # ====================================================
        # TOPLAM
        #
        # PARA       30
        # TEKNİK     40
        # HACİM      15
        # SETUP      15
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
        # PARA KONTROLÜ
        #
        # ARTIK ZORUNLU DEĞİL.
        # SADECE POZİTİFSE OK.
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

        # Daha da gevşek:
        # 4H bear ama 1H + 15M güçleniyorsa
        # tamamen çöpe atma.

        if not trend_ok:

            trend_recovery = (

                t1["trend"]
                ==
                "BULL"

                and

                t15["trend"]
                !=
                "BEAR"

            )

            if trend_recovery:

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
        # HACİM
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
        # DİRENÇ
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
        # YAPI
        # ====================================================

        setup_ok = (

            t15["higher_low"]

            or

            t1["higher_low"]

            or

            t15["higher_high"]

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

        if breakout:

            stats[
                "breakout"
            ] += 1

        # ====================================================
        # 🔥 YENİ FINAL FİLTRE
        #
        # ARTIK PARA AKIŞI TEK BAŞINA ŞART DEĞİL.
        #
        # Güçlü teknik yapı + hacim = aday
        #
        # veya
        #
        # Para akışı + teknik yapı = aday
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

        # ====================================================
        # FLOW VERİSİ
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

            buy_open = flow[
                "buy"
            ]

            sell_open = flow[
                "sell"
            ]

            buy_count = flow[
                "buy_count"
            ]

            sell_count = flow[
                "sell_count"
            ]

        else:

            flow_pct = 0

            buy_share = 50

            open_total = 0

            buy_open = 0

            sell_open = 0

            buy_count = 0

            sell_count = 0

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

            "buy_open":
                buy_open,

            "sell_open":
                sell_open,

            "buy_count":
                buy_count,

            "sell_count":
                sell_count,

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
# TELEGRAM ALARM
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

        "🚨 PRE-PUMP V14\n\n"

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

        "🛰 MEXC PRE-PUMP RADAR V14",

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
                f"Hacim "
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
        "=" * 60
    )

    print(
        "🚀 MEXC PRE-PUMP RADAR V14.0"
    )

    print(
        "💰 PARA AKIŞI + TEKNİK SKOR"
    )

    print(
        "🟢 LONG / PRE-PUMP"
    )

    print(
        "📊 15M + 1H + 4H"
    )

    print(
        "⭐ MIN SCORE:",
        MIN_ALERT_SCORE
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

        change24 = (

            fnum(

                ticker.get(
                    "riseFallRate"
                )

            )
            *
            100.0

        )

        # ====================================================
        # PUMP SONRASI COINLERE HAFİF CEZA
        # ====================================================

        pump_penalty = max(

            change24 - 12.0,

            0.0

        ) * 0.5

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
    # SIRALAMA
    # ========================================================

    results.sort(

        key=lambda x: (

            x["score"],

            x["technical_score"],

            x["money_score"],

            x["volume_score"],

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

                f"Tech "
                f"{item['technical_score']} | "

                f"Money "
                f"{item['money_score']} | "

                f"Para "
                f"{item['flow_pct']:+.1f}% | "

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

        if len(alerts) >= MAX_ALERTS:

            break

    save_state(
        state
    )

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
    # SÜRE
    # ========================================================

    duration = (

        time.time()
        -
        started

    )

    # ========================================================
    # FİLTRE RAPORU
    # ========================================================

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

        "🚀 Kırılmış:",

        stats["breakout"]

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
