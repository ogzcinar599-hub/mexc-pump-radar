import os
import json
import time
import math
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PRE-PUMP RADAR V12.3
#
# ANA MANTIK:
# 💰 PARA AKIŞI
# 📍 GİRİŞ BÖLGESİ
# 📈 TREND
# 📊 HACİM
# RSI
# 🎯 DİRENÇ YAKINLIĞI
#
# AMAÇ:
# PUMP BAŞLADIKTAN SONRA DEĞİL,
# PUMP ÖNCESİ YAPIDA OLAN COİNLERİ BULMAK.
#
# SADECE MEXC USDT FUTURES
# OTOMATİK İŞLEM AÇMAZ
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

MAX_CANDIDATES = 120
MAX_WORKERS = 8
DEALS_LIMIT = 100

MIN_24H_AMOUNT = 100_000

# Para akışı artık tek başına coin elemez.
# Fakat çok küçük açılış akışı puanı ciddi düşürür.
MIN_OPEN_NOTIONAL = 10_000

# Genel alarm skoru
MIN_ALERT_SCORE = 58

# En fazla Telegram alarmı
MAX_ALERTS = 6

# Aynı coini tekrar tekrar göndermemek için
STATE_FILE = "signal_state_v12_3.json"

STATE_EXPIRY = 3600


TIMEFRAMES = {

    "15M": "Min15",

    "1H": "Min60",

    "4H": "Hour4"

}


# ============================================================
# KRİPTO DIŞI / İSTENMEYENLER
# ============================================================

NON_CRYPTO = {

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

    "NVIDIA",
    "NVDA",
    "TSLA",
    "AAPL",
    "AMZN",
    "MSFT",
    "GOOGL",
    "META",
    "COIN",
    "MSTR",
    "QQQ",
    "DOW",
    "NDX",
    "DJI"

}


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

rate_lock = threading.Lock()

last_request = 0.0


# ============================================================
# İSTATİSTİKLER
# ============================================================

stats = {

    "analyzed": 0,

    "money_good": 0,

    "volume_good": 0,

    "trend_good": 0,

    "rsi_good": 0,

    "resistance_good": 0,

    "entry_good": 0,

    "overheated": 0,

    "weak_money": 0,

    "final_candidates": 0

}

stats_lock = threading.Lock()


# ============================================================
# API
# ============================================================

def api_get(
    url,
    params=None
):

    global last_request

    try:

        with rate_lock:

            wait = (
                0.11
                - (
                    time.time()
                    - last_request
                )
            )

            if wait > 0:

                time.sleep(wait)

            last_request = time.time()

        response = session.get(

            url,

            params=params,

            timeout=20,

            headers={
                "User-Agent":
                    "MEXC-PUMP-RADAR-V12.3"
            }

        )

        response.raise_for_status()

        return response.json()

    except Exception as e:

        print(
            "API HATASI:",
            e
        )

        return None


# ============================================================
# YARDIMCI
# ============================================================

def num(
    value,
    default=0.0
):

    try:

        return float(value)

    except Exception:

        return default


def average(values):

    if not values:

        return 0.0

    return sum(values) / len(
        values
    )


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
# EMA
# ============================================================

def ema(
    values,
    period
):

    if not values:

        return []

    multiplier = (
        2
        / (
            period
            + 1
        )
    )

    result = [
        values[0]
    ]

    current = values[0]

    for value in values[1:]:

        current += (

            value
            - current

        ) * multiplier

        result.append(
            current
        )

    return result


# ============================================================
# RSI
# ============================================================

def calculate_rsi(
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
            - values[i - 1]

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

    gain = average(
        gains[:period]
    )

    loss = average(
        losses[:period]
    )

    for i in range(
        period,
        len(gains)
    ):

        gain = (

            gain * (period - 1)
            + gains[i]

        ) / period

        loss = (

            loss * (period - 1)
            + losses[i]

        ) / period

    if loss == 0:

        return 100.0

    rs = gain / loss

    return (
        100
        - (
            100
            / (
                1 + rs
            )
        )
    )


# ============================================================
# CONTRACTLAR
# ============================================================

def get_contracts():

    data = api_get(

        f"{BASE}/api/v1/contract/detail"

    )

    if not data:

        return {}, []

    rows = data.get(
        "data",
        []
    )

    if not isinstance(
        rows,
        list
    ):

        return {}, []

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

        clean = symbol[:-5]

        if (

            base_coin
            in NON_CRYPTO

            or

            clean
            in NON_CRYPTO

        ):

            continue

        contract_size = num(

            item.get(
                "contractSize",
                1
            ),

            1

        )

        if contract_size <= 0:

            contract_size = 1

        contracts[
            symbol
        ] = contract_size

    return (
        contracts,
        sorted(
            contracts
        )
    )


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
    interval,
    count=90
):

    seconds = {

        "Min15":
            15 * 60,

        "Min60":
            60 * 60,

        "Hour4":
            4 * 60 * 60

    }.get(

        interval,

        15 * 60

    )

    end = int(
        time.time()
    )

    start = (

        end
        - seconds * count

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

        return None

    required = [

        "time",
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

        return None

    try:

        length = min(

            len(
                data[key]
            )

            for key in required

        )

        candles = []

        for i in range(
            length
        ):

            candles.append({

                "time":
                    num(
                        data["time"][i]
                    ),

                "open":
                    num(
                        data["open"][i]
                    ),

                "close":
                    num(
                        data["close"][i]
                    ),

                "high":
                    num(
                        data["high"][i]
                    ),

                "low":
                    num(
                        data["low"][i]
                    ),

                "vol":
                    num(
                        data["vol"][i]
                    )

            })

        return candles

    except Exception:

        return None


# ============================================================
# SON DEAL / PARA AKIŞI
# ============================================================

def get_deals(
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

        price = num(

            trade.get(
                "p",
                0
            )

        )

        volume = num(

            trade.get(
                "v",
                0
            )

        )

        trade_type = int(

            num(

                trade.get(
                    "T",
                    0
                )

            )

        )

        open_type = int(

            num(

                trade.get(
                    "O",
                    0
                )

            )

        )

        if (

            price <= 0

            or

            volume <= 0

            or

            open_type != 1

        ):

            continue

        notional = (

            price
            * volume
            * contract_size

        )

        if trade_type == 1:

            buy_open += notional

            buy_count += 1

        elif trade_type == 2:

            sell_open += notional

            sell_count += 1

    total = (

        buy_open
        + sell_open

    )

    net = (

        buy_open
        - sell_open

    )

    if total > 0:

        net_pct = (

            net
            / total
            * 100

        )

        buy_share = (

            buy_open
            / total
            * 100

        )

    else:

        net_pct = 0

        buy_share = 50

    return {

        "buy_open":
            buy_open,

        "sell_open":
            sell_open,

        "open_total":
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
# TIMEFRAME ANALİZİ
# ============================================================

def analyze_tf(
    candles
):

    if (

        not candles

        or

        len(candles) < 60

    ):

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

    price = closes[-1]

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

    rsi = calculate_rsi(
        closes
    )

    rsi_prev = calculate_rsi(
        closes[:-1]
    )

    # ========================================================
    # DESTEK / DİRENÇ
    # ========================================================

    resistance = max(
        highs[-21:-1]
    )

    support = min(
        lows[-21:-1]
    )

    # ========================================================
    # HACİM
    # ========================================================

    avg_volume = average(

        volumes[-21:-1]

    )

    if avg_volume > 0:

        volume_ratio = (

            volumes[-1]
            / avg_volume

        )

    else:

        volume_ratio = 0

    # ========================================================
    # DİRENÇ MESAFESİ
    # ========================================================

    if resistance > 0:

        resistance_distance = (

            price
            / resistance
            - 1

        ) * 100

    else:

        resistance_distance = -100

    if support > 0:

        support_distance = (

            1
            - price / support

        ) * 100

    else:

        support_distance = -100

    # ========================================================
    # TREND
    # ========================================================

    if (

        price > ema9
        and ema9 > ema21
        and ema21 > ema50

    ):

        trend = "BULL"

    elif (

        price < ema9
        and ema9 < ema21
        and ema21 < ema50

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
        > previous_low

    )

    # ========================================================
    # LOWER HIGH
    # ========================================================

    recent_high = max(
        highs[-8:-2]
    )

    previous_high = max(
        highs[-16:-8]
    )

    lower_high = (

        recent_high
        < previous_high

    )

    # ========================================================
    # MOMENTUM
    # ========================================================

    momentum_up = (

        closes[-3]
        < closes[-2]
        < closes[-1]

    )

    momentum_down = (

        closes[-3]
        > closes[-2]
        > closes[-1]

    )

    # ========================================================
    # SIKIŞMA
    # ========================================================

    ranges = []

    for candle in candles[-10:-1]:

        if candle["close"] > 0:

            ranges.append(

                (
                    candle["high"]
                    - candle["low"]
                )
                / candle["close"]
                * 100

            )

    compression = False

    if len(ranges) >= 6:

        old_range = average(
            ranges[:5]
        )

        new_range = average(
            ranges[-3:]
        )

        if old_range > 0:

            compression = (

                new_range
                < old_range * 0.80

            )

    # ========================================================
    # BREAKOUT
    # ========================================================

    long_break = (
        price > resistance
    )

    short_break = (
        price < support
    )

    return {

        "price":
            price,

        "ema9":
            ema9,

        "ema21":
            ema21,

        "ema50":
            ema50,

        "rsi":
            rsi,

        "rsi_prev":
            rsi_prev,

        "volume":
            volume_ratio,

        "support":
            support,

        "resistance":
            resistance,

        "resistance_distance":
            resistance_distance,

        "support_distance":
            support_distance,

        "trend":
            trend,

        "higher_low":
            higher_low,

        "lower_high":
            lower_high,

        "momentum_up":
            momentum_up,

        "momentum_down":
            momentum_down,

        "compression":
            compression,

        "long_break":
            long_break,

        "short_break":
            short_break

    }


# ============================================================
# PARA PUAN
# 0 - 35
# ============================================================

def money_score(
    flow,
    amount24
):

    total = flow[
        "open_total"
    ]

    if total <= 0:

        return 0

    net_pct = abs(
        flow["net_pct"]
    )

    buy_pressure = max(

        flow["buy_share"],

        100
        - flow["buy_share"]

    )

    ratio = (

        total
        / max(
            amount24,
            1
        )

    )

    score = 0

    # Mutlak açılış akışı
    if total >= 10_000:

        score += 5

    if total >= 25_000:

        score += 4

    if total >= 50_000:

        score += 4

    if total >= 100_000:

        score += 3

    # Net yön
    if net_pct >= 10:

        score += 3

    if net_pct >= 25:

        score += 3

    if net_pct >= 40:

        score += 3

    # Alış / satış baskısı
    if buy_pressure >= 60:

        score += 2

    if buy_pressure >= 70:

        score += 2

    if buy_pressure >= 85:

        score += 2

    # 24H hacme oran
    if ratio >= 0.0003:

        score += 1

    if ratio >= 0.0007:

        score += 1

    if ratio >= 0.0015:

        score += 1

    return int(
        clamp(
            score,
            0,
            35
        )
    )


# ============================================================
# TEKNİK PUAN
# 0 - 45
# ============================================================

def technical_score(
    t15,
    t1,
    t4,
    direction
):

    score = 0

    if direction == "LONG":

        # 4H
        if t4["trend"] == "BULL":

            score += 8

        elif t4["trend"] == "MIXED":

            score += 4

        # 1H
        if t1["trend"] == "BULL":

            score += 8

        elif t1["trend"] == "MIXED":

            score += 4

        # 15M
        if t15["trend"] == "BULL":

            score += 5

        elif t15["trend"] == "MIXED":

            score += 3

        # RSI
        if 50 <= t15["rsi"] <= 68:

            score += 6

        elif 68 < t15["rsi"] <= 73:

            score += 3

        # RSI yukarı
        if t15["rsi"] > t15["rsi_prev"]:

            score += 3

        # Higher low
        if t15["higher_low"]:

            score += 4

        if t1["higher_low"]:

            score += 3

        # Momentum
        if t15["momentum_up"]:

            score += 3

        # Compression
        if t15["compression"]:

            score += 3

    else:

        if t4["trend"] == "BEAR":

            score += 8

        elif t4["trend"] == "MIXED":

            score += 4

        if t1["trend"] == "BEAR":

            score += 8

        elif t1["trend"] == "MIXED":

            score += 4

        if t15["trend"] == "BEAR":

            score += 5

        elif t15["trend"] == "MIXED":

            score += 3

        if 32 <= t15["rsi"] <= 50:

            score += 6

        elif 27 <= t15["rsi"] < 32:

            score += 3

        if t15["rsi"] < t15["rsi_prev"]:

            score += 3

        if t15["lower_high"]:

            score += 4

        if t1["lower_high"]:

            score += 3

        if t15["momentum_down"]:

            score += 3

        if t15["compression"]:

            score += 3

    return int(
        clamp(
            score,
            0,
            45
        )
    )


# ============================================================
# GİRİŞ PUANI
# 0 - 20
# ============================================================

def entry_score(
    t15,
    t1,
    direction
):

    score = 0

    if direction == "LONG":

        distance = max(

            t15["resistance_distance"],
            t1["resistance_distance"]

        )

        if -1.0 <= distance <= 3.0:

            score += 10

        elif -3.0 <= distance < -1.0:

            score += 7

        elif distance > 3:

            score += 2

        if t15["higher_low"]:

            score += 4

        if t1["higher_low"]:

            score += 3

        if (
            t15["rsi"] < 74
        ):

            score += 3

    else:

        distance = max(

            t15["support_distance"],
            t1["support_distance"]

        )

        if -1.0 <= distance <= 3.0:

            score += 10

        elif -3.0 <= distance < -1.0:

            score += 7

        elif distance > 3:

            score += 2

        if t15["lower_high"]:

            score += 4

        if t1["lower_high"]:

            score += 3

        if (
            t15["rsi"] > 26
        ):

            score += 3

    return int(
        clamp(
            score,
            0,
            20
        )
    )


# ============================================================
# HACİM PUANI
# 0 - 15
# ============================================================

def volume_score(
    t15,
    t1
):

    v15 = t15[
        "volume"
    ]

    v1 = t1[
        "volume"
    ]

    best = max(
        v15,
        v1
    )

    if best >= 3:

        return 15

    if best >= 2:

        return 13

    if best >= 1.5:

        return 11

    if best >= 1.2:

        return 8

    if best >= 1.0:

        return 5

    if best >= 0.85:

        return 3

    return 0


# ============================================================
# GİRİŞ PLANI
# ============================================================

def build_entry_plan(
    direction,
    t15,
    t1,
    t4
):

    price = t15[
        "price"
    ]

    if direction == "LONG":

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

        # ----------------------------------------------------
        # PRE-PUMP GİRİŞ
        # ----------------------------------------------------

        if not (

            t15["long_break"]
            or
            t1["long_break"]

        ):

            entry_low = max(

                support,

                price * 0.985

            )

            entry_high = min(

                price * 1.002,

                resistance * 0.998

            )

            if entry_high <= entry_low:

                entry_low = (
                    price * 0.995
                )

                entry_high = (
                    price * 1.002
                )

            breakout = (
                resistance * 1.002
            )

        # ----------------------------------------------------
        # BREAKOUT
        # ----------------------------------------------------

        else:

            entry_low = (
                price * 0.997
            )

            entry_high = (
                price * 1.002
            )

            breakout = price

        # ----------------------------------------------------
        # STOP
        # ----------------------------------------------------

        risk = max(

            price - support,

            price * 0.012

        )

        stop = price - (
            risk * 0.80
        )

        stop = max(

            stop,

            price * 0.96

        )

        risk_pct = (

            (
                price - stop
            )
            / price

        ) * 100

        risk_pct = clamp(

            risk_pct,

            0.8,

            4.0

        )

        tp1 = price * (

            1
            + risk_pct * 1.5 / 100

        )

        tp2 = price * (

            1
            + risk_pct * 2.5 / 100

        )

        tp3 = price * (

            1
            + risk_pct * 4.0 / 100

        )

    else:

        support = min(

            t15["support"],
            t1["support"],
            t4["support"]

        )

        resistance = max(

            t15["resistance"],
            t1["resistance"],
            t4["resistance"]

        )

        if not (

            t15["short_break"]
            or
            t1["short_break"]

        ):

            entry_low = max(

                price * 0.998,

                support * 1.002

            )

            entry_high = min(

                price * 1.015,

                resistance

            )

            if entry_high <= entry_low:

                entry_low = (
                    price * 0.998
                )

                entry_high = (
                    price * 1.003
                )

            breakout = (
                support * 0.998
            )

        else:

            entry_low = (
                price * 0.998
            )

            entry_high = (
                price * 1.002
            )

            breakout = price

        risk = max(

            resistance - price,

            price * 0.012

        )

        stop = price + (
            risk * 0.80
        )

        stop = min(

            stop,

            price * 1.04

        )

        risk_pct = (

            (
                stop - price
            )
            / price

        ) * 100

        risk_pct = clamp(

            risk_pct,

            0.8,

            4.0

        )

        tp1 = price * (

            1
            - risk_pct * 1.5 / 100

        )

        tp2 = price * (

            1
            - risk_pct * 2.5 / 100

        )

        tp3 = price * (

            1
            - risk_pct * 4.0 / 100

        )

    return {

        "price":
            price,

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
# TEK COİN ANALİZİ
# ============================================================

def analyze_symbol(
    symbol,
    contract_size,
    ticker
):

    with stats_lock:

        stats["analyzed"] += 1

    try:

        amount24 = num(

            ticker.get(
                "amount24",
                0
            )

        )

        if amount24 <= 0:

            return None

        # ====================================================
        # TIMEFRAME
        # ====================================================

        tf = {}

        for name, interval in TIMEFRAMES.items():

            candles = get_kline(

                symbol,

                interval,

                90

            )

            result = analyze_tf(
                candles
            )

            if not result:

                return None

            tf[name] = result

        t15 = tf["15M"]
        t1 = tf["1H"]
        t4 = tf["4H"]

        # ====================================================
        # PARA AKIŞI
        # ====================================================

        flow = get_deals(

            symbol,

            contract_size

        )

        if not flow:

            return None

        if (

            flow["buy_open"]
            >=
            flow["sell_open"]

        ):

            direction = "LONG"

            directional_flow = (
                flow["buy_open"]
            )

            flow_pct = (
                flow["net_pct"]
            )

            buy_pressure = (
                flow["buy_share"]
            )

        else:

            direction = "SHORT"

            directional_flow = (
                flow["sell_open"]
            )

            flow_pct = (
                -flow["net_pct"]
            )

            buy_pressure = (

                100
                - flow["buy_share"]

            )

        open_total = (
            flow["open_total"]
        )

        # ====================================================
        # PARA PUANI
        # ====================================================

        m_score = money_score(

            flow,

            amount24

        )

        if m_score >= 15:

            with stats_lock:

                stats[
                    "money_good"
                ] += 1

        else:

            with stats_lock:

                stats[
                    "weak_money"
                ] += 1

        # ====================================================
        # TEKNİK
        # ====================================================

        t_score = technical_score(

            t15,
            t1,
            t4,
            direction

        )

        # Trend
        if direction == "LONG":

            trend_good = (

                t1["trend"]
                in (
                    "BULL",
                    "MIXED"
                )

                or

                t4["trend"]
                == "BULL"

            )

        else:

            trend_good = (

                t1["trend"]
                in (
                    "BEAR",
                    "MIXED"
                )

                or

                t4["trend"]
                == "BEAR"

            )

        if trend_good:

            with stats_lock:

                stats[
                    "trend_good"
                ] += 1

        # ====================================================
        # RSI
        # ====================================================

        if direction == "LONG":

            rsi_good = (

                45
                <= t15["rsi"]
                <= 73

            )

        else:

            rsi_good = (

                27
                <= t15["rsi"]
                <= 55

            )

        if rsi_good:

            with stats_lock:

                stats[
                    "rsi_good"
                ] += 1

        # ====================================================
        # HACİM
        # ====================================================

        v_score = volume_score(

            t15,
            t1

        )

        if v_score >= 5:

            with stats_lock:

                stats[
                    "volume_good"
                ] += 1

        # ====================================================
        # GİRİŞ PUANI
        # ====================================================

        e_score = entry_score(

            t15,
            t1,
            direction

        )

        if e_score >= 8:

            with stats_lock:

                stats[
                    "entry_good"
                ] += 1

        # ====================================================
        # DİRENÇ
        # ====================================================

        if direction == "LONG":

            distance = max(

                t15[
                    "resistance_distance"
                ],

                t1[
                    "resistance_distance"
                ]

            )

        else:

            distance = max(

                t15[
                    "support_distance"
                ],

                t1[
                    "support_distance"
                ]

            )

        resistance_good = (

            distance >= -4
            and
            distance <= 8

        )

        if resistance_good:

            with stats_lock:

                stats[
                    "resistance_good"
                ] += 1

        # ====================================================
        # AŞIRI ISINMA
        # ====================================================

        if direction == "LONG":

            overheated = (

                t15["rsi"] > 78
                or
                t1["rsi"] > 78

            )

        else:

            overheated = (

                t15["rsi"] < 22
                or
                t1["rsi"] < 22

            )

        if overheated:

            with stats_lock:

                stats[
                    "overheated"
                ] += 1

        # ====================================================
        # PUMP ÇOKTAN BAŞLAMIŞ MI?
        # ====================================================

        change24 = abs(

            num(

                ticker.get(
                    "riseFallRate",
                    0
                )

            ) * 100

        )

        # Çok yüksek günlük hareketi tamamen
        # silmiyoruz; fakat puan kırıyoruz.
        pump_penalty = 0

        if change24 >= 20:

            pump_penalty += 5

        if change24 >= 35:

            pump_penalty += 10

        if change24 >= 50:

            pump_penalty += 15

        # ====================================================
        # ANA SKOR
        #
        # PARA AKIŞI EN ÖNEMLİ BÖLÜM
        #
        # Money 35
        # Technical 45
        # Volume 15
        # Entry bonus 20
        #
        # Toplam ham skor 115'e kadar çıkabilir.
        # Sonra 100'e normalize edilir.
        # ====================================================

        raw_score = (

            m_score

            +

            t_score

            +

            v_score

            +

            e_score

        )

        final_score = (

            raw_score
            * 100
            / 115

        )

        # Para akışı çok zayıfsa ekstra kır.
        if m_score < 8:

            final_score -= 15

        elif m_score < 12:

            final_score -= 7

        # Aşırı sıcak
        if overheated:

            final_score -= 15

        # Pump zaten çok ilerlediyse
        final_score -= pump_penalty

        # Hacim çok düşükse
        if v_score == 0:

            final_score -= 8

        # Trend tamamen tersse
        if not trend_good:

            final_score -= 6

        final_score = int(

            clamp(
                round(
                    final_score
                ),
                0,
                100
            )

        )

        # ====================================================
        # GİRİŞ DURUMU
        # ====================================================

        if direction == "LONG":

            pre_pump_structure = (

                (
                    t15["higher_low"]
                    or
                    t1["higher_low"]
                )

                and

                t15["rsi"] < 75

                and

                not overheated

            )

        else:

            pre_pump_structure = (

                (
                    t15["lower_high"]
                    or
                    t1["lower_high"]
                )

                and

                t15["rsi"] > 25

                and

                not overheated

            )

        # ====================================================
        # SON ADAY FİLTRESİ
        #
        # Burada artık aşırı sert davranmıyoruz.
        # ====================================================

        candidate = (

            final_score
            >=
            MIN_ALERT_SCORE

            and

            m_score
            >= 8

            and

            e_score
            >= 6

            and

            resistance_good

        )

        if not candidate:

            return None

        # ====================================================
        # DURUM
        # ====================================================

        if direction == "LONG":

            breakout = (

                t15["long_break"]
                or
                t1["long_break"]

            )

        else:

            breakout = (

                t15["short_break"]
                or
                t1["short_break"]

            )

        if breakout:

            status = (
                "BREAKOUT ENTRY"
            )

        elif pre_pump_structure:

            status = (
                "PRE-PUMP"
            )

        else:

            status = (
                "EARLY ENTRY"
            )

        # ====================================================
        # GİRİŞ PLANI
        # ====================================================

        plan = build_entry_plan(

            direction,

            t15,
            t1,
            t4

        )

        plan.update({

            "symbol":
                symbol,

            "direction":
                direction,

            "status":
                status,

            "score":
                final_score,

            "money_score":
                m_score,

            "technical_score":
                t_score,

            "volume_score":
                v_score,

            "entry_score":
                e_score,

            "flow_pct":
                flow_pct,

            "buy_pressure":
                buy_pressure,

            "open_total":
                open_total,

            "directional_flow":
                directional_flow,

            "amount24":
                amount24,

            "volume15":
                t15["volume"],

            "volume1h":
                t1["volume"],

            "rsi15":
                t15["rsi"],

            "rsi1h":
                t1["rsi"],

            "trend1h":
                t1["trend"],

            "change24":
                change24,

            "distance":
                distance

        })

        with stats_lock:

            stats[
                "final_candidates"
            ] += 1

        return plan

    except Exception as e:

        print(

            symbol,
            "ANALİZ HATASI:",
            e

        )

        return None


# ============================================================
# FİYAT FORMAT
# ============================================================

def format_price(
    value
):

    value = num(value)

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
# PARA FORMAT
# ============================================================

def format_money(
    value
):

    value = num(value)

    if value >= 1_000_000:

        return (
            f"${value / 1_000_000:.2f}M"
        )

    if value >= 1000:

        return (
            f"${value / 1000:.0f}K"
        )

    return f"${value:.0f}"


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def build_message(
    x
):

    if x["direction"] == "LONG":

        direction = "🟢 LONG"

    else:

        direction = "🔴 SHORT"

    flow = x[
        "flow_pct"
    ]

    if flow >= 60:

        fire = "🔥🔥🔥"

    elif flow >= 35:

        fire = "🔥🔥"

    elif flow >= 15:

        fire = "🔥"

    else:

        fire = "⚡"

    if x["status"] == "BREAKOUT ENTRY":

        trigger_name = (
            "🚀 KIRILIM ONAYI"
        )

    else:

        trigger_name = (
            "🚀 KIRILIM GİRİŞİ"
        )

    return (

        f"🚨 {x['status']}\n"

        f"{direction}\n\n"

        f"🪙 {x['symbol']}\n"

        f"⭐ Skor: "
        f"{x['score']}/100\n\n"

        f"💰 Para Akışı: "
        f"{fire} +{flow:.1f}%\n"

        f"💵 Açılış Akışı: "
        f"{format_money(x['open_total'])}\n"

        f"📈 Alış Baskısı: "
        f"{x['buy_pressure']:.0f}%\n"

        f"📊 15M Hacim: "
        f"{x['volume15']:.1f}x\n"

        f"📊 1H Hacim: "
        f"{x['volume1h']:.1f}x\n"

        f"📉 RSI 15M: "
        f"{x['rsi15']:.1f}\n\n"

        f"📍 GİRİŞ BÖLGESİ\n"

        f"{format_price(x['entry_low'])}"
        f" – "
        f"{format_price(x['entry_high'])}\n\n"

        f"{trigger_name}\n"

        f"{format_price(x['breakout'])}\n\n"

        f"🛑 STOP\n"

        f"{format_price(x['stop'])}\n\n"

        f"🎯 TP1: "
        f"{format_price(x['tp1'])}\n"

        f"🎯 TP2: "
        f"{format_price(x['tp2'])}\n"

        f"🎯 TP3: "
        f"{format_price(x['tp3'])}\n\n"

        f"📌 Destek: "
        f"{format_price(x['support'])}\n"

        f"🎯 Direnç: "
        f"{format_price(x['resistance'])}\n\n"

        f"📈 1H Trend: "
        f"{x['trend1h']}\n"

        f"⚠️ Teknik sinyaldir. "
        f"Otomatik işlem açmaz."

    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(
    message
):

    if not TOKEN or not CHAT_ID:

        print(
            "Telegram TOKEN/CHAT_ID eksik."
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
                    message,

                "disable_web_page_preview":
                    True

            },

            timeout=15

        )

        if response.ok:

            print(
                "Telegram gönderildi."
            )

            return True

        print(
            "Telegram HATASI:",
            response.text
        )

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

                indent=2,

                ensure_ascii=False

            )

    except Exception as e:

        print(
            "State kayıt hatası:",
            e
        )


# ============================================================
# TEKRAR ALARM
# ============================================================

def should_alert(
    item,
    state
):

    symbol = item[
        "symbol"
    ]

    now = int(
        time.time()
    )

    old = state.get(
        symbol
    )

    if not old:

        state[symbol] = {

            "score":
                item["score"],

            "status":
                item["status"],

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

    old_status = old.get(
        "status",
        ""
    )

    old_time = int(

        old.get(
            "time",
            0
        )

    )

    levels = {

        "PRE-PUMP":
            1,

        "EARLY ENTRY":
            2,

        "BREAKOUT ENTRY":
            3

    }

    old_level = levels.get(
        old_status,
        0
    )

    new_level = levels.get(

        item["status"],
        0

    )

    alert = (

        new_level > old_level

        or

        item["score"]
        >= old_score + 5

        or

        now - old_time
        >= STATE_EXPIRY

    )

    state[symbol] = {

        "score":
            item["score"],

        "status":
            item["status"],

        "time":
            now

    }

    return alert


# ============================================================
# TELEGRAM ÖZET
# ============================================================

def send_summary(
    total_symbols,
    analyzed,
    results,
    alerts,
    duration
):

    message = (

        "🛰 MEXC PRE-PUMP RADAR V12.3\n\n"

        f"📊 Futures: "
        f"{total_symbols:,}\n"

        f"🔎 Analiz: "
        f"{analyzed}\n\n"

        f"💰 Para akışı geçti: "
        f"{stats['money_good']}\n"

        f"📊 Hacim geçti: "
        f"{stats['volume_good']}\n"

        f"📈 Trend geçti: "
        f"{stats['trend_good']}\n"

        f"📉 RSI uygun: "
        f"{stats['rsi_good']}\n"

        f"🎯 Direnç uygun: "
        f"{stats['resistance_good']}\n"

        f"📍 Giriş uygun: "
        f"{stats['entry_good']}\n\n"

        f"🔥 Aşırı sıcak: "
        f"{stats['overheated']}\n"

        f"❌ Zayıf para akışı: "
        f"{stats['weak_money']}\n\n"

        f"🟢 Uygun aday: "
        f"{len(results)}\n"

        f"🚨 Yeni alarm: "
        f"{len(alerts)}\n"

        f"⏱ Süre: "
        f"{duration:.1f} sn"

    )

    send_telegram(
        message
    )


# ============================================================
# ANA
# ============================================================

def main():

    started = time.time()

    print()
    print("=" * 60)

    print(
        "🚀 MEXC PRE-PUMP RADAR V12.3"
    )

    print(
        "💰 PARA AKIŞI + GİRİŞ BÖLGESİ"
    )

    print(
        "📊 15M + 1H + 4H"
    )

    print(
        "🎯 ERKEN PUMP ADAYI"
    )

    print("=" * 60)
    print()

    # ========================================================
    # CONTRACT
    # ========================================================

    contracts, symbols = (
        get_contracts()
    )

    if not contracts:

        raise RuntimeError(
            "Futures kontratları alınamadı."
        )

    # ========================================================
    # TICKER
    # ========================================================

    tickers = get_tickers()

    if not tickers:

        raise RuntimeError(
            "Ticker verisi alınamadı."
        )

    ticker_map = {

        str(
            x.get(
                "symbol",
                ""
            )
        ).upper():

        x

        for x in tickers

    }

    # ========================================================
    # ÖN ELEME
    # ========================================================

    candidates = []

    for symbol in symbols:

        ticker = ticker_map.get(
            symbol
        )

        if not ticker:

            continue

        amount24 = num(

            ticker.get(
                "amount24",
                0
            )

        )

        price = num(

            ticker.get(
                "lastPrice",
                0
            )

        )

        if (

            amount24
            < MIN_24H_AMOUNT

        ):

            continue

        if price <= 0:

            continue

        change24 = abs(

            num(

                ticker.get(
                    "riseFallRate",
                    0
                )

            ) * 100

        )

        high = num(

            ticker.get(
                "high24Price",
                0
            )

        )

        low = num(

            ticker.get(
                "lower24Price",
                0
            )

        )

        if high > low:

            position = (

                price - low

            ) / (

                high - low

            )

        else:

            position = 0.5

        # Hacimli coinleri öne al,
        # fakat aşırı pump yapanları aşağı at.
        rank = (

            math.log10(
                max(
                    amount24,
                    1
                )
            ) * 10

            +

            position * 5

            -

            max(
                change24 - 20,
                0
            ) * 0.5

        )

        candidates.append(

            (
                rank,
                symbol,
                ticker

            )

        )

    candidates.sort(
        reverse=True
    )

    candidates = candidates[
        :MAX_CANDIDATES
    ]

    print(
        f"📊 Futures: {len(symbols)}"
    )

    print(
        f"📡 Ticker: {len(tickers)}"
    )

    print(
        f"🎯 Detaylı analiz: "
        f"{len(candidates)}"
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

                contracts[symbol],

                ticker

            ): symbol

            for
            _,
            symbol,
            ticker
            in candidates

        }

        for future in as_completed(
            jobs
        ):

            symbol = jobs[
                future
            ]

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
                    symbol,
                    "HATA:",
                    e
                )

    # ========================================================
    # SIRALA
    # ========================================================

    results.sort(

        key=lambda x: (

            x["score"],

            x["money_score"],

            x["entry_score"],

            x["open_total"]

        ),

        reverse=True

    )

    # ========================================================
    # EN İYİLER
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

                f"{item['direction']} | "

                f"{item['status']} | "

                f"{item['score']}/100 | "

                f"Money "
                f"{item['money_score']} | "

                f"Entry "
                f"{item['entry_score']} | "

                f"Open "
                f"{format_money("
                    item["open_total"]
                )}"

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
    # TELEGRAM
    # ========================================================

    for item in alerts:

        print(

            "🚨 ALARM:",

            item["symbol"],

            item["score"]

        )

        send_telegram(

            build_message(
                item
            )

        )

    # ========================================================
    # ÖZET
    # ========================================================

    duration = (

        time.time()
        - started

    )

    print()
    print(
        "========== FİLTRE RAPORU =========="
    )

    print(
        "💰 Para akışı geçti:",
        stats["money_good"]
    )

    print(
        "📊 Hacim geçti:",
        stats["volume_good"]
    )

    print(
        "📈 Trend geçti:",
        stats["trend_good"]
    )

    print(
        "📉 RSI uygun:",
        stats["rsi_good"]
    )

    print(
        "🎯 Direnç uygun:",
        stats["resistance_good"]
    )

    print(
        "📍 Giriş uygun:",
        stats["entry_good"]
    )

    print(
        "🔥 Aşırı sıcak:",
        stats["overheated"]
    )

    print(
        "❌ Zayıf para:",
        stats["weak_money"]
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

    # Sadece yeni alarm varsa
    # Telegram'a özet gönder.
    if alerts:

        send_summary(

            len(symbols),

            len(candidates),

            results,

            alerts,

            duration

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

    try:

        main()

    except Exception as e:

        print()
        print(
            "🔴 KRİTİK HATA:",
            e
        )

        if TOKEN and CHAT_ID:

            send_telegram(

                "🔴 MEXC RADAR V12.3\n\n"
                "❌ Sistem hatası:\n"
                f"{e}"

            )

        raise
