import os
import json
import math
import time
import threading
import requests


# ============================================================
# 🚀 MEXC PRE-PUMP RADAR V16.2
#
# SADECE KRİPTO FUTURES
#
# 1059+
#    ↓
# 15M → 60
#    ↓
# 1H → 30
#    ↓
# 4H → 15
#    ↓
# PARA AKIŞI → 12
#    ↓
# FINAL
#    ↓
# 3-10 GÜÇLÜ ADAY
#
# PARA AKIŞI = BONUS
# TEK BAŞINA SİNYAL DEĞİL
#
# OTOMATİK İŞLEM AÇMAZ
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
# TARAMA
# ============================================================

MAX_SYMBOLS = 120

STAGE_15M = 60

STAGE_1H = 30

STAGE_4H = 15

STAGE_FLOW = 12

MAX_ALERTS = 7


# ============================================================
# FINAL SKOR
# ============================================================

MIN_ALERT_SCORE = 52

FALLBACK_SCORE = 48


# ============================================================
# LİKİDİTE
# ============================================================

MIN_24H_AMOUNT = 100_000


# ============================================================
# RATE LIMIT
# ============================================================

REQUEST_INTERVAL = 0.13

MAX_510_RETRY = 4

BACKOFF_BASE = 1.0

rate_lock = threading.Lock()

last_request_time = 0.0


# ============================================================
# STATE
# ============================================================

STATE_FILE = "signal_state_v162.json"

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
# ============================================================
# HİSSE / EMTİA / ENDEKS / FOREX KONTRATLARI
# ============================================================
#
# MEXC bazı platformlarda bunları da USDT kontratı olarak
# gösterebilir.
#
# Biz sadece kripto istiyoruz.
# ============================================================

NON_CRYPTO = {

    # --------------------------------------------------------
    # ABD HİSSELERİ
    # --------------------------------------------------------

    "TSLA",
    "TESLA",

    "AAPL",
    "APPLE",

    "NVDA",
    "NVIDIA",

    "MSFT",
    "MICROSOFT",

    "AMZN",
    "AMAZON",

    "GOOGL",
    "GOOG",
    "GOOGLE",

    "META",

    "MSTR",
    "MICROSTRATEGY",

    "COIN",
    "COINBASE",

    "AMD",

    "INTC",

    "NFLX",

    "PLTR",

    "BABA",

    "JPM",

    "BAC",

    "WMT",

    "DIS",

    "NKE",

    "PFE",

    "XOM",

    "CVX",

    "BA",

    "ORCL",

    "CRM",

    "AVGO",

    "QCOM",

    "UBER",

    "PYPL",

    "SHOP",

    "T",

    "V",

    "MA",

    # --------------------------------------------------------
    # ENDEKSLER
    # --------------------------------------------------------

    "SPX",
    "SPX500",
    "US500",

    "NAS100",
    "NASDAQ",
    "NDX",

    "US30",
    "DJI",
    "DOW",

    "DAX",
    "GER40",

    "UK100",
    "FTSE",

    "JPN225",
    "JP225",

    # --------------------------------------------------------
    # EMTİA
    # --------------------------------------------------------

    "XAU",
    "XAG",
    "XPT",
    "XPD",

    "GOLD",
    "SILVER",
    "PLATINUM",

    "COPPER",

    "WTI",
    "USOIL",
    "OIL",

    "BRENT",
    "UKOIL",

    "NGAS",
    "NATGAS",

    # --------------------------------------------------------
    # FOREX
    # --------------------------------------------------------

    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "AUDUSD",
    "USDCAD",
    "NZDUSD",

    "EURGBP",
    "EURJPY",
    "GBPJPY"

}


# ============================================================
# HİSSE İSİMLERİ İÇİN EK KONTROL
# ============================================================

NON_CRYPTO_KEYWORDS = {

    "STOCK",
    "SHARE",
    "INDEX",
    "NASDAQ",
    "NYSE",
    "FOREX",
    "GOLD",
    "SILVER",
    "OIL",
    "CRUDE",
    "COPPER",
    "TESLA",
    "APPLE",
    "NVIDIA",
    "MICROSOFT",
    "AMAZON",
    "META",
    "GOOGLE"

}


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({

    "User-Agent":
        "Mozilla/5.0 MEXC-PRE-PUMP-RADAR/16.2",

    "Accept":
        "application/json"

})


# ============================================================
# STATS
# ============================================================

stats = {

    "futures": 0,

    "crypto": 0,

    "non_crypto": 0,

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

    "not_pumped": 0,

    "near_resistance": 0,

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
# PARA
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
# FİYAT
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
# API
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
            # 510
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
                    f"{wait_time:.1f}s"

                )

                time.sleep(
                    wait_time
                )

                continue

            # ==================================================
            # HTTP
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
            # BODY 510
            # ==================================================

            if isinstance(
                data,
                dict
            ):

                if str(

                    data.get(
                        "code",
                        ""
                    )

                ) == "510":

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
        (
            period
            +
            1.0
        )

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
            (
                1.0
                +
                rs
            )
        )

    )


# ============================================================
# KRİPTO KONTROL
# ============================================================

def is_crypto_contract(
    item
):

    symbol = str(

        item.get(
            "symbol",
            ""
        )

    ).upper()

    base_coin = str(

        item.get(
            "baseCoin",
            ""
        )

    ).upper()

    quote_coin = str(

        item.get(
            "quoteCoin",
            ""
        )

    ).upper()

    settle_coin = str(

        item.get(
            "settleCoin",
            ""
        )

    ).upper()

    text = (

        symbol
        +
        " "
        +
        base_coin

    ).upper()

    # ========================================================
    # USDT SETTLE / QUOTE
    # ========================================================

    if (

        settle_coin
        and
        settle_coin != "USDT"

        and

        quote_coin
        and
        quote_coin != "USDT"

    ):

        return False

    # ========================================================
    # BİLİNEN NON-CRYPTO
    # ========================================================

    if base_coin in NON_CRYPTO:

        return False

    # ========================================================
    # SEMBOL KONTROL
    # ========================================================

    clean_symbol = symbol.replace(
        "_USDT",
        ""
    )

    if clean_symbol in NON_CRYPTO:

        return False

    # ========================================================
    # KEYWORD
    # ========================================================

    for keyword in NON_CRYPTO_KEYWORDS:

        if keyword in text:

            return False

    return True


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

        if not is_crypto_contract(
            item
        ):

            stats[
                "non_crypto"
            ] += 1

            continue

        base_coin = str(

            item.get(
                "baseCoin",
                ""
            )

        ).upper()

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
        ] = {

            "contract_size":
                contract_size,

            "base_coin":
                base_coin

        }

    stats[
        "crypto"
    ] = len(contracts)

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

    data = api_get(

        f"{BASE}/api/v1/contract/kline/{symbol}",

        {

            "interval":
                interval,

            "start":
                start,

            "end":
                now

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
    # SON 6 MUM HAREKET
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
    # SON 3 MUM HAREKET
    # ========================================================

    if (

        len(closes) >= 4

        and

        closes[-4] > 0

    ):

        short_move = (

            (
                closes[-1]
                /
                closes[-4]
            )
            -
            1

        ) * 100

    else:

        short_move = 0.0

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

        "recent_move":
            recent_move,

        "short_move":
            short_move,

        "breakout":
            breakout

    }


# ============================================================
# 15M ÖN SKOR
# ============================================================

def stage15_score(
    t
):

    score = 0

    # ========================================================
    # RSI
    # ========================================================

    if 45 <= t["rsi"] <= 65:

        score += 25

    elif 40 <= t["rsi"] < 45:

        score += 18

    elif 65 < t["rsi"] <= 72:

        score += 18

    elif 72 < t["rsi"] <= 74:

        score += 10

    # ========================================================
    # TREND
    # ========================================================

    if t["trend"] == "BULL":

        score += 25

    elif t["trend"] == "MIXED":

        score += 17

    # ========================================================
    # RSI MOMENTUM
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
    # ZATEN PUMP OLMUŞSA CEZA
    # ========================================================

    if t["recent_move"] > 8:

        score -= 8

    if t["recent_move"] > 12:

        score -= 15

    if t["recent_move"] > 18:

        score -= 20

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

    # 1H TREND

    if t1["trend"] == "BULL":

        score += 28

    elif t1["trend"] == "MIXED":

        score += 20

    # 15M TREND

    if t15["trend"] == "BULL":

        score += 15

    elif t15["trend"] == "MIXED":

        score += 10

    # RSI

    if 42 <= t15["rsi"] <= 70:

        score += 17

    elif 38 <= t15["rsi"] < 42:

        score += 10

    # RSI yükseliyor

    if t15["rsi"] > t15["rsi_prev"]:

        score += 10

    # Higher low

    if t15["higher_low"]:

        score += 10

    if t1["higher_low"]:

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

        score += 22

    # 1H

    if t1["trend"] == "BULL":

        score += 20

    elif t1["trend"] == "MIXED":

        score += 14

    # 15M

    if t15["trend"] == "BULL":

        score += 10

    elif t15["trend"] == "MIXED":

        score += 7

    # Yapı

    if t15["higher_low"]:

        score += 8

    if t1["higher_low"]:

        score += 8

    if t4["higher_low"]:

        score += 8

    # Higher high

    if t4["higher_high"]:

        score += 5

    return int(

        clamp(

            score,

            0,

            100

        )

    )


# ============================================================
# HACİM SCORE
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

        return 14

    if best >= 1.5:

        return 12

    if best >= 1.2:

        return 10

    if best >= 1:

        return 8

    if best >= 0.8:

        return 6

    if best >= 0.55:

        return 4

    return 0


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
# PARA SCORE
#
# Para akışı sadece BONUS.
# ============================================================

def money_score(
    flow
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

    score = 0

    # ========================================================
    # POZİTİF AKIŞ
    # ========================================================

    if net_pct > 0:

        score += 5

    if net_pct >= 5:

        score += 3

    if net_pct >= 10:

        score += 3

    if net_pct >= 20:

        score += 3

    if net_pct >= 35:

        score += 3

    if net_pct >= 50:

        score += 2

    # ========================================================
    # ALIŞ ORANI
    # ========================================================

    if buy_share >= 52:

        score += 1

    if buy_share >= 60:

        score += 1

    if buy_share >= 70:

        score += 1

    # ========================================================
    # AKIŞ HACMİ
    # ========================================================

    if total >= 10_000:

        score += 1

    if total >= 25_000:

        score += 1

    return min(

        score,

        25

    )


# ============================================================
# FINAL SCORE
# ============================================================

def calculate_final_score(
    t15,
    t1,
    t4,
    flow,
    amount24,
    change24
):

    # ========================================================
    # MONEY
    # ========================================================

    money = money_score(
        flow
    )

    # ========================================================
    # TECH
    # ========================================================

    tech = 0

    # 15M

    if t15["trend"] == "BULL":

        tech += 7

    elif t15["trend"] == "MIXED":

        tech += 5

    # 1H

    if t1["trend"] == "BULL":

        tech += 10

    elif t1["trend"] == "MIXED":

        tech += 7

    # RSI

    if 43 <= t15["rsi"] <= 68:

        tech += 8

    elif 38 <= t15["rsi"] < 43:

        tech += 5

    elif 68 < t15["rsi"] <= 74:

        tech += 5

    # RSI momentum

    if t15["rsi"] > t15["rsi_prev"]:

        tech += 4

    # Higher low

    if t15["higher_low"]:

        tech += 3

    if t1["higher_low"]:

        tech += 2

    # Momentum

    if t15["momentum"]:

        tech += 3

    tech = min(

        tech,

        35

    )

    # ========================================================
    # VOLUME
    # ========================================================

    volume = volume_score(

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

    # Dirence yakın

    if 0 <= distance <= 2:

        setup += 8

    elif 2 < distance <= 4:

        setup += 7

    elif 4 < distance <= 7:

        setup += 5

    elif 7 < distance <= 12:

        setup += 2

    # Higher low

    if t15["higher_low"]:

        setup += 3

    if t1["higher_low"]:

        setup += 3

    # Momentum

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

        h4 += 5

    if t4["higher_low"]:

        h4 += 2

    if t4["higher_high"]:

        h4 += 1

    h4 = min(

        h4,

        10

    )

    # ========================================================
    # TOTAL
    # ========================================================

    total = (

        money
        +
        tech
        +
        volume
        +
        setup
        +
        h4

    )

    # ========================================================
    # 24H PUMP CEZASI
    # ========================================================

    if change24 >= 10:

        total -= 2

    if change24 >= 15:

        total -= 3

    if change24 >= 25:

        total -= 5

    if change24 >= 40:

        total -= 10

    # ========================================================
    # RSI CEZASI
    # ========================================================

    if t15["rsi"] > 74:

        total -= 5

    if t15["rsi"] > 78:

        total -= 15

    if t1["rsi"] > 78:

        total -= 10

    # ========================================================
    # ALREADY BREAKOUT
    # ========================================================

    if t15["breakout"]:

        total -= 8

    if t1["breakout"]:

        total -= 8

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
    # BREAKOUT
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

    # ========================================================
    # TP
    # ========================================================

    tp1 = (

        current
        *
        (
            1
            +
            (
                risk_pct
                *
                1.5
                /
                100
            )

        )

    )

    tp2 = (

        current
        *
        (
            1
            +
            (
                risk_pct
                *
                2.5
                /
                100
            )

        )

    )

    tp3 = (

        current
        *
        (
            1
            +
            (
                risk_pct
                *
                4
                /
                100
            )

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
# STAGE 1
# ============================================================

def scan_15m(
    candidates
):

    print()

    print(
        "🟢 AŞAMA 1 | 15M"
    )

    results = []

    for item in candidates:

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

        # ====================================================
        # ÇOK ISINMIŞ COINLERİ BURADA ELEYELİM
        # ====================================================

        if t15["rsi"] > 76:

            continue

        if t15["recent_move"] > 20:

            continue

        results.append({

            **item,

            "t15":
                t15,

            "stage_score":
                score

        })

    results.sort(

        key=lambda x:
            x["stage_score"],

        reverse=True

    )

    results = results[
        :STAGE_15M
    ]

    stats[
        "stage15"
    ] = len(results)

    print(

        f"✅ 15M → "
        f"{len(results)}"

    )

    return results


# ============================================================
# STAGE 2
# ============================================================

def scan_1h(
    candidates
):

    print()

    print(
        "🟡 AŞAMA 2 | 1H"
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

        # ====================================================
        # 1H AŞIRI SICAKSA ELLE
        # ====================================================

        if t1["rsi"] > 80:

            continue

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
        :STAGE_1H
    ]

    stats[
        "stage1h"
    ] = len(results)

    print(

        f"✅ 1H → "
        f"{len(results)}"

    )

    return results


# ============================================================
# STAGE 3
# ============================================================

def scan_4h(
    candidates
):

    print()

    print(
        "🟠 AŞAMA 3 | 4H"
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

        if t4["rsi"] > 82:

            continue

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
        :STAGE_4H
    ]

    stats[
        "stage4h"
    ] = len(results)

    print(

        f"✅ 4H → "
        f"{len(results)}"

    )

    return results


# ============================================================
# STAGE 4
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

        score = calculate_final_score(

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

            40
            <=
            t15["rsi"]
            <=
            74

        )

        if rsi_ok:

            stats[
                "rsi_ok"
            ] += 1

        if not rsi_ok:

            continue

        # ====================================================
        # HACİM
        # ====================================================

        volume_ratio = max(

            t15["volume"],

            t1["volume"]

        )

        volume_ok = (

            volume_ratio
            >=
            0.55

        )

        if volume_ok:

            stats[
                "volume_ok"
            ] += 1

        if not volume_ok:

            continue

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

        # 15M güçlü ise 1H biraz zayıf olabilir

        if (

            not trend_ok

            and

            t15["trend"]
            ==
            "BULL"

            and

            t15["higher_low"]

        ):

            trend_ok = True

        if trend_ok:

            stats[
                "trend_ok"
            ] += 1

        if not trend_ok:

            continue

        # ====================================================
        # SETUP
        # ====================================================

        setup_ok = (

            t15["higher_low"]

            or

            t1["higher_low"]

            or

            t4["higher_low"]

            or

            t15["higher_high"]

        )

        if setup_ok:

            stats[
                "setup_ok"
            ] += 1

        if not setup_ok:

            continue

        # ====================================================
        # ZATEN PUMP
        # ====================================================

        not_pumped = (

            t15["recent_move"]
            <
            15

            and

            change24
            <
            35

        )

        if not_pumped:

            stats[
                "not_pumped"
            ] += 1

        if not not_pumped:

            continue

        # ====================================================
        # BREAKOUT
        # ====================================================

        if t15["breakout"]:

            continue

        if t1["breakout"]:

            continue

        # ====================================================
        # DİRENÇ
        # ====================================================

        distance = min(

            t15["dist_res"],

            t1["dist_res"]

        )

        if 0 <= distance <= 8:

            stats[
                "near_resistance"
            ] += 1

        # Çok uzakta olan coinleri tamamen eleme.
        # Ancak puan düşükse zaten geçemez.

        # ====================================================
        # FINAL SCORE
        # ====================================================

        if score < MIN_ALERT_SCORE:

            continue

        # ====================================================
        # PARA AKIŞI
        #
        # Para yoksa coin otomatik elenmiyor.
        # ========================================================

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

            if (

                flow_pct >= 2
                and
                buy_share >= 51

            ):

                stats[
                    "money_ok"
                ] += 1

        else:

            flow_pct = 0

            buy_share = 50

            open_total = 0

        # ====================================================
        # PLAN
        # ====================================================

        plan = build_plan(

            t15,
            t1,
            t4

        )

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

            "rsi4h":
                t4["rsi"],

            "volume15":
                t15["volume"],

            "volume1h":
                t1["volume"],

            "trend15":
                t15["trend"],

            "trend1h":
                t1["trend"],

            "trend4h":
                t4["trend"],

            "higher_low15":
                t15["higher_low"],

            "higher_low1h":
                t1["higher_low"],

            "higher_low4h":
                t4["higher_low"],

            "recent_move":
                t15["recent_move"],

            "change24":
                change24,

            "res_distance":
                distance,

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
    # SKOR 5 ARTTI
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
    # 30 DAKİKA
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
# ALARM
# ============================================================

def alert_text(
    x
):

    flow = x[
        "flow_pct"
    ]

    if flow >= 50:

        fire = "🔥🔥🔥"

    elif flow >= 25:

        fire = "🔥🔥"

    elif flow >= 10:

        fire = "🔥"

    elif flow > 0:

        fire = "⚡"

    else:

        fire = "📊"

    return (

        "🚨 PRE-PUMP V16.2\n\n"

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
        f"{x['rsi15']:.1f}\n"

        f"📉 RSI 1H: "
        f"{x['rsi1h']:.1f}\n\n"

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

        f"📈 15M: "
        f"{x['trend15']}\n"

        f"📈 1H: "
        f"{x['trend1h']}\n"

        f"📈 4H: "
        f"{x['trend4h']}\n\n"

        f"📊 24H: "
        f"{x['change24']:+.1f}%\n"

        f"📐 Dirence uzaklık: "
        f"{x['res_distance']:.1f}%\n\n"

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

        "🛰 MEXC PRE-PUMP RADAR V16.2",

        "",

        f"📊 MEXC Futures: "
        f"{futures_count}",

        f"🪙 Kripto Futures: "
        f"{stats['crypto']}",

        f"🚫 Kripto olmayan: "
        f"{stats['non_crypto']}",

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

        f"🚀 Pump olmamış: "
        f"{stats['not_pumped']}",

        f"🎯 Direnç yakın: "
        f"{stats['near_resistance']}",

        "",

        f"⚠️ 510: "
        f"{stats['rate_510']}",

        f"❌ API Hata: "
        f"{stats['api_error']}",

        "",

        f"🟢 FINAL ADAY: "
        f"{len(candidates)}",

        f"🚨 YENİ ALARM: "
        f"{len(alerts)}",

        f"⏱ SÜRE: "
        f"{duration:.1f} sn"

    ]

    # ========================================================
    # EN İYİLER
    # ========================================================

    if candidates:

        lines += [

            "",

            "⭐ EN GÜÇLÜLER"

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
        "🚀 MEXC PRE-PUMP RADAR V16.2"
    )

    print(
        "🪙 SADECE KRİPTO FUTURES"
    )

    print(
        "120 → 60 → 30 → 15 → 12"
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
    # İLK SIRALAMA
    # ========================================================

    candidates = []

    for symbol, info in contracts.items():

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
        # ÇOK PUMP OLANLARA PENALTY
        # ====================================================

        pump_penalty = max(

            change24 - 8,

            0

        ) * 0.8

        # ====================================================
        # HACİM SIRALAMASI
        # ====================================================

        liquidity_score = (

            math.log10(

                max(
                    amount24,
                    1
                )

            )
            *
            10

        )

        rank = (

            liquidity_score
            -
            pump_penalty

        )

        candidates.append({

            "symbol":
                symbol,

            "contract_size":
                info[
                    "contract_size"
                ],

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

        f"📊 MEXC Futures: "
        f"{len(contracts)}"

    )

    print(

        f"🪙 Kripto: "
        f"{stats['crypto']}"

    )

    print(

        f"🔎 15M taranacak: "
        f"{len(candidates)}"

    )

    # ========================================================
    # 15M
    # ========================================================

    stage15 = scan_15m(
        candidates
    )

    if not stage15:

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
    # 1H
    # ========================================================

    stage1h = scan_1h(
        stage15
    )

    if not stage1h:

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
    # 4H
    # ========================================================

    stage4h = scan_4h(
        stage1h
    )

    if not stage4h:

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
    # PARA
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
    # FALLBACK
    #
    # Eğer çok az sinyal çıkarsa, sadece çok iyi yapıya
    # sahip olanları biraz daha gevşek eşikle değerlendir.
    # ========================================================

    if len(results) < 3:

        fallback = []

        for item in stageflow:

            t15 = item[
                "t15"
            ]

            t1 = item[
                "t1"
            ]

            t4 = item[
                "t4"
            ]

            score = item[
                "final_score"
            ]

            if score < FALLBACK_SCORE:

                continue

            if t15["rsi"] > 75:

                continue

            if t15["recent_move"] > 18:

                continue

            if item["change24"] > 40:

                continue

            if (

                t15["breakout"]
                or
                t1["breakout"]

            ):

                continue

            structure = (

                t15["higher_low"]
                or
                t1["higher_low"]
                or
                t4["higher_low"]

            )

            if not structure:

                continue

            if item not in fallback:

                fallback.append(
                    item
                )

        fallback.sort(

            key=lambda x:
                x["final_score"],

            reverse=True

        )

        # Sadece final liste azsa fallback ekle

        existing = {

            x["symbol"]

            for x in results

        }

        for item in fallback:

            if (

                item["symbol"]
                not in existing

            ):

                results.append(
                    item
                )

        results.sort(

            key=lambda x:
                x["score"],

            reverse=True

        )

    # ========================================================
    # MAKSİMUM 10
    # ========================================================

    results = results[
        :10
    ]

    stats[
        "final"
    ] = len(results)

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
    # SUMMARY
    # ========================================================

    duration = (

        time.time()
        -
        started

    )

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

        f"✅ V16.2 TAMAMLANDI | "
        f"{duration:.1f} sn"

    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
