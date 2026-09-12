import os
import json
import time
import math
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 🚀 MEXC PRE-PUMP RADAR V12.1
#
# PARA AKIŞI
# + GİRİŞ BÖLGESİ
# + KIRILIM GİRİŞİ
# + STOP
# + TP1 / TP2 / TP3
#
# SADECE MEXC USDT FUTURES
# OTOMATİK İŞLEM AÇMAZ
# ============================================================

BASE = "https://api.mexc.com"

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ============================================================
# AYARLAR
# ============================================================

MAX_CANDIDATES = 100
MAX_WORKERS = 8

DEALS_LIMIT = 100

STATE_FILE = "signal_state.json"
STATE_EXPIRY = 3600

# 24 saatlik minimum hacim
MIN_24H_AMOUNT = 100_000

# Gerçek açılış akışı minimumu
MIN_OPEN_NOTIONAL = 25_000

# Açılış akışı / 24H hacim oranı
MIN_OPEN_RATIO = 0.001

# Para akışı minimum skoru
MIN_MONEY_SCORE = 18

# Final minimum skor
MIN_FINAL_SCORE = 58

# ============================================================
# TIMEFRAME
# ============================================================

TIMEFRAMES = {
    "15M": "Min15",
    "1H": "Min60",
    "4H": "Hour4",
}

# ============================================================
# KRİPTO DIŞI ÜRÜNLER
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
    "DJI",
}

# ============================================================
# SESSION
# ============================================================

session = requests.Session()

rate_lock = threading.Lock()
last_request = 0.0


# ============================================================
# API
# ============================================================

def api_get(url, params=None):

    global last_request

    try:

        with rate_lock:

            wait = 0.11 - (time.time() - last_request)

            if wait > 0:
                time.sleep(wait)

            last_request = time.time()

        response = session.get(
            url,
            params=params,
            timeout=20,
            headers={
                "User-Agent": "MEXC-PUMP-RADAR-V12.1"
            },
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
# YARDIMCI
# ============================================================

def f(value, default=0.0):

    try:
        return float(value)

    except Exception:
        return default


def avg(values):

    if not values:
        return 0.0

    return sum(values) / len(values)


def clamp(value, low, high):

    return max(
        low,
        min(high, value)
    )


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if not values:
        return []

    k = 2 / (period + 1)

    output = [
        values[0]
    ]

    current = values[0]

    for value in values[1:]:

        current += k * (
            value - current
        )

        output.append(current)

    return output


# ============================================================
# RSI
# ============================================================

def rsi(values, period=14):

    if len(values) < period + 1:

        return 50.0

    gains = []
    losses = []

    for i in range(1, len(values)):

        difference = (
            values[i]
            - values[i - 1]
        )

        gains.append(
            max(difference, 0)
        )

        losses.append(
            max(-difference, 0)
        )

    average_gain = avg(
        gains[:period]
    )

    average_loss = avg(
        losses[:period]
    )

    for i in range(
        period,
        len(gains)
    ):

        average_gain = (
            (
                average_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        average_loss = (
            (
                average_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if average_loss == 0:

        return 100.0

    rs = (
        average_gain
        / average_loss
    )

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# FUTURES CONTRACTLAR
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

        clean_symbol = symbol[:-5]

        if (
            base_coin in NON_CRYPTO
            or clean_symbol in NON_CRYPTO
        ):

            continue

        contract_size = f(
            item.get(
                "contractSize",
                1
            ),
            1.0
        )

        if contract_size <= 0:

            contract_size = 1.0

        contracts[
            symbol
        ] = contract_size

    return (
        contracts,
        sorted(contracts)
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

    return (
        rows
        if isinstance(rows, list)
        else []
    )


# ============================================================
# KLINE
# ============================================================

def get_kline(
    symbol,
    interval,
    count=90
):

    seconds_per_candle = {

        "Min15":
            15 * 60,

        "Min60":
            60 * 60,

        "Hour4":
            4 * 60 * 60,

    }.get(
        interval,
        15 * 60
    )

    end = int(
        time.time()
    )

    start = (
        end
        - seconds_per_candle
        * count
    )

    data = api_get(

        f"{BASE}/api/v1/contract/kline/{symbol}",

        {
            "interval": interval,
            "start": start,
            "end": end,
        }
    )

    if not isinstance(
        data,
        dict
    ):

        return None

    keys = (
        "time",
        "open",
        "close",
        "high",
        "low",
        "vol",
    )

    if any(
        key not in data
        for key in keys
    ):

        return None

    try:

        length = min(
            len(data[key])
            for key in keys
        )

        candles = []

        for i in range(length):

            candles.append({

                "time":
                    f(data["time"][i]),

                "open":
                    f(data["open"][i]),

                "close":
                    f(data["close"][i]),

                "high":
                    f(data["high"][i]),

                "low":
                    f(data["low"][i]),

                "vol":
                    f(data["vol"][i]),

            })

        return candles

    except Exception:

        return None


# ============================================================
# SON İŞLEMLER / PARA AKIŞI
# ============================================================

def get_deals(
    symbol,
    contract_size
):

    data = api_get(

        f"{BASE}/api/v1/contract/deals/{symbol}",

        {
            "limit": DEALS_LIMIT
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

        price = f(
            trade.get(
                "p",
                0
            )
        )

        volume = f(
            trade.get(
                "v",
                0
            )
        )

        trade_type = int(
            f(
                trade.get(
                    "T",
                    0
                )
            )
        )

        open_type = int(
            f(
                trade.get(
                    "O",
                    0
                )
            )
        )

        if (
            price <= 0
            or volume <= 0
            or open_type != 1
        ):

            continue

        notional = (
            price
            * volume
            * contract_size
        )

        # T=1 BUY
        if trade_type == 1:

            buy_open += notional
            buy_count += 1

        # T=2 SELL
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

        net_pct = 0.0
        buy_share = 0.0

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
            sell_count,

    }


# ============================================================
# TIMEFRAME ANALİZİ
# ============================================================

def analyze_tf(candles):

    if (
        not candles
        or len(candles) < 60
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

    e9 = ema(
        closes,
        9
    )[-1]

    e21 = ema(
        closes,
        21
    )[-1]

    e50 = ema(
        closes,
        50
    )[-1]

    current_rsi = rsi(
        closes
    )

    previous_rsi = rsi(
        closes[:-1]
    )

    # --------------------------------------------------------
    # DESTEK / DİRENÇ
    # --------------------------------------------------------

    resistance = max(
        highs[-21:-1]
    )

    support = min(
        lows[-21:-1]
    )

    previous_resistance = max(
        highs[-22:-2]
    )

    previous_support = min(
        lows[-22:-2]
    )

    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    volume_average = avg(
        volumes[-21:-1]
    )

    volume_ratio = (
        volumes[-1]
        / volume_average
        if volume_average > 0
        else 0
    )

    # --------------------------------------------------------
    # DİRENÇ MESAFESİ
    # --------------------------------------------------------

    long_break = (
        price > resistance
    )

    short_break = (
        price < support
    )

    long_distance = (

        (
            price
            / resistance
        ) - 1

    ) * 100 if resistance > 0 else 0

    short_distance = (

        1
        - price / support

    ) * 100 if support > 0 else 0

    # --------------------------------------------------------
    # SIKIŞMA
    # --------------------------------------------------------

    ranges = []

    for candle in candles[-7:-1]:

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

    if ranges:

        recent_average = avg(
            ranges[-3:]
        )

        full_average = avg(
            ranges
        )

        if full_average > 0:

            compression = (
                recent_average
                < full_average * 0.85
            )

    # --------------------------------------------------------
    # TREND
    # --------------------------------------------------------

    if (
        price > e9
        and e9 > e21
        and e21 > e50
    ):

        trend = "BULL"

    elif (
        price < e9
        and e9 < e21
        and e21 < e50
    ):

        trend = "BEAR"

    else:

        trend = "MIXED"

    # --------------------------------------------------------
    # HIGHER LOW / LOWER HIGH
    # --------------------------------------------------------

    higher_low = (
        lows[-1]
        >= min(
            lows[-8:-2]
        )
    )

    lower_high = (
        highs[-1]
        <= max(
            highs[-8:-2]
        )
    )

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    momentum_long = (
        closes[-3]
        < closes[-2]
        < closes[-1]
    )

    momentum_short = (
        closes[-3]
        > closes[-2]
        > closes[-1]
    )

    # ========================================================
    # SCORE
    # ========================================================

    long_score = 0
    short_score = 0

    # Trend
    if trend == "BULL":

        long_score += 20

    elif price > e21:

        long_score += 8

    elif price > e50:

        long_score += 4

    if trend == "BEAR":

        short_score += 20

    elif price < e21:

        short_score += 8

    elif price < e50:

        short_score += 4

    # RSI
    if 52 <= current_rsi <= 68:

        long_score += 15

    elif 68 < current_rsi <= 72:

        long_score += 7

    if 32 <= current_rsi <= 48:

        short_score += 15

    elif 28 <= current_rsi < 32:

        short_score += 7

    # RSI yönü
    if current_rsi > previous_rsi:

        long_score += 6

    if current_rsi < previous_rsi:

        short_score += 6

    # Hacim
    if 1.15 <= volume_ratio <= 2.5:

        long_score += 10
        short_score += 10

    elif volume_ratio > 2.5:

        long_score += 4
        short_score += 4

    # Long direnç
    if long_break:

        long_score += 12

    elif long_distance >= -1.0:

        long_score += 10

    elif long_distance >= -2.5:

        long_score += 5

    # Short destek
    if short_break:

        short_score += 12

    elif short_distance >= -1.0:

        short_score += 10

    elif short_distance >= -2.5:

        short_score += 5

    # Yapı
    if higher_low:

        long_score += 8

    if lower_high:

        short_score += 8

    # Sıkışma
    if compression:

        long_score += 7
        short_score += 7

    # Momentum
    if momentum_long:

        long_score += 5

    if momentum_short:

        short_score += 5

    return {

        "close":
            price,

        "support":
            support,

        "resistance":
            resistance,

        "prev_support":
            previous_support,

        "prev_resistance":
            previous_resistance,

        "rsi":
            current_rsi,

        "volume":
            volume_ratio,

        "trend":
            trend,

        "long_break":
            long_break,

        "short_break":
            short_break,

        "long_dist":
            long_distance,

        "short_dist":
            short_distance,

        "higher_low":
            higher_low,

        "lower_high":
            lower_high,

        "compression":
            compression,

        "momentum_long":
            momentum_long,

        "momentum_short":
            momentum_short,

        "long_score":
            int(
                clamp(
                    long_score,
                    0,
                    100
                )
            ),

        "short_score":
            int(
                clamp(
                    short_score,
                    0,
                    100
                )
            ),

    }


# ============================================================
# PARA AKIŞ SKORU
# ============================================================

def money_score(
    flow,
    amount24
):

    if (
        not flow
        or flow["open_total"] <= 0
    ):

        return 0

    total = flow[
        "open_total"
    ]

    ratio = (
        total
        / max(
            amount24,
            1
        )
    )

    net = abs(
        flow["net_pct"]
    )

    share = max(
        flow["buy_share"],
        100 - flow["buy_share"]
    )

    score = 0

    if total >= 25_000:

        score += 10

    if total >= 50_000:

        score += 5

    if total >= 100_000:

        score += 5

    if ratio >= 0.001:

        score += 5

    if ratio >= 0.003:

        score += 5

    if net >= 20:

        score += 5

    if net >= 40:

        score += 5

    if share >= 70:

        score += 5

    if share >= 85:

        score += 5

    return int(
        clamp(
            score,
            0,
            50
        )
    )


# ============================================================
# GİRİŞ PLANI
# ============================================================

def entry_plan(
    direction,
    t15,
    t1,
    t4
):

    price = t15[
        "close"
    ]

    supports = [

        x["support"]

        for x in (
            t15,
            t1,
            t4
        )

        if x["support"] > 0

    ]

    resistances = [

        x["resistance"]

        for x in (
            t15,
            t1,
            t4
        )

        if x["resistance"] > 0

    ]

    if supports:

        support = max(
            supports
        )

    else:

        support = price * 0.97

    if resistances:

        resistance = min(
            resistances
        )

    else:

        resistance = price * 1.03

    # ========================================================
    # LONG
    # ========================================================

    if direction == "LONG":

        # Eğer kırılım başlamışsa
        if (
            t15["long_break"]
            or t1["long_break"]
        ):

            breakout = max(
                t15["resistance"],
                t1["resistance"]
            )

            entry_low = (
                price * 0.997
            )

            entry_high = (
                price * 1.002
            )

        else:

            # Kırılım öncesi giriş
            breakout = (
                resistance
                * 1.002
            )

            zone_low = max(

                support,

                price * 0.985

            )

            zone_high = min(

                price * 1.002,

                resistance * 0.995

            )

            if zone_high <= zone_low:

                zone_low = (
                    price * 0.997
                )

                zone_high = (
                    price * 1.001
                )

            entry_low = zone_low
            entry_high = zone_high

        # Stop
        risk = max(

            price - support,

            price * 0.012

        )

        stop = min(

            price - risk * 0.65,

            support * 0.995

        )

        stop = min(

            stop,

            price * 0.985

        )

        risk_pct = max(

            (
                price - stop
            )
            / price
            * 100,

            0.8

        )

        tp1 = price * (

            1
            + risk_pct
            * 1.5
            / 100

        )

        tp2 = price * (

            1
            + risk_pct
            * 2.5
            / 100

        )

        tp3 = price * (

            1
            + risk_pct
            * 4.0
            / 100

        )

    # ========================================================
    # SHORT
    # ========================================================

    else:

        if (
            t15["short_break"]
            or t1["short_break"]
        ):

            breakout = min(

                t15["support"],
                t1["support"]

            )

            entry_low = (
                price * 0.998
            )

            entry_high = (
                price * 1.003
            )

        else:

            breakout = (
                support
                * 0.998
            )

            zone_low = max(

                price * 0.998,

                support * 1.005

            )

            zone_high = min(

                resistance,

                price * 1.015

            )

            if zone_high <= zone_low:

                zone_low = (
                    price * 0.999
                )

                zone_high = (
                    price * 1.003
                )

            entry_low = zone_low
            entry_high = zone_high

        risk = max(

            support - price,

            price * 0.012

        )

        stop = max(

            price + risk * 0.65,

            resistance * 1.005

        )

        stop = max(

            stop,

            price * 1.015

        )

        risk_pct = max(

            (
                stop - price
            )
            / price
            * 100,

            0.8

        )

        tp1 = price * (

            1
            - risk_pct
            * 1.5
            / 100

        )

        tp2 = price * (

            1
            - risk_pct
            * 2.5
            / 100

        )

        tp3 = price * (

            1
            - risk_pct
            * 4.0
            / 100

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

        "breakout_price":
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
            tp3,

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

        amount24 = f(
            ticker.get(
                "amount24",
                0
            )
        )

        if (
            amount24
            < MIN_24H_AMOUNT
        ):

            return None

        # ----------------------------------------------------
        # 15M / 1H / 4H
        # ----------------------------------------------------

        tf = {}

        for name, interval in TIMEFRAMES.items():

            candles = get_kline(

                symbol,

                interval,

                90

            )

            analysis = analyze_tf(
                candles
            )

            if not analysis:

                return None

            tf[name] = analysis

        t15 = tf["15M"]
        t1 = tf["1H"]
        t4 = tf["4H"]

        # ----------------------------------------------------
        # PARA AKIŞI
        # ----------------------------------------------------

        flow = get_deals(

            symbol,

            contract_size

        )

        if not flow:

            return None

        # ----------------------------------------------------
        # YÖN
        # ----------------------------------------------------

        if (
            flow["buy_open"]
            >= flow["sell_open"]
        ):

            direction = "LONG"

            flow_pct = (
                flow["net_pct"]
            )

            buy_share = (
                flow["buy_share"]
            )

        else:

            direction = "SHORT"

            flow_pct = (
                -flow["net_pct"]
            )

            buy_share = (
                100
                - flow["buy_share"]
            )

        open_total = (
            flow["open_total"]
        )

        open_ratio = (

            open_total
            / max(
                amount24,
                1
            )

        )

        # ====================================================
        # ZAYIF PARA AKIŞINI ELE
        # ====================================================

        # Örneğin:
        #
        # +100%
        # $727
        #
        # gibi sinyaller gelmeyecek.

        if (
            open_total
            < MIN_OPEN_NOTIONAL
        ):

            return None

        if (
            open_ratio
            < MIN_OPEN_RATIO
        ):

            return None

        if flow_pct < 15:

            return None

        if buy_share < 60:

            return None

        # ----------------------------------------------------
        # PARA SKORU
        # ----------------------------------------------------

        mscore = money_score(

            flow,

            amount24

        )

        if (
            mscore
            < MIN_MONEY_SCORE
        ):

            return None

        # ====================================================
        # TEKNİK
        # ====================================================

        if direction == "LONG":

            technical = (

                t15["long_score"]
                * 0.35

                + t1["long_score"]
                * 0.40

                + t4["long_score"]
                * 0.25

            )

            near = (

                max(

                    t15["long_dist"],
                    t1["long_dist"]

                )
                >= -2.5

            )

            overheated = (

                max(

                    t15["rsi"],
                    t1["rsi"]

                )
                > 76

            )

            breakout = (

                t15["long_break"]
                or t1["long_break"]

            )

        else:

            technical = (

                t15["short_score"]
                * 0.35

                + t1["short_score"]
                * 0.40

                + t4["short_score"]
                * 0.25

            )

            near = (

                max(

                    t15["short_dist"],
                    t1["short_dist"]

                )
                >= -2.5

            )

            overheated = (

                min(

                    t15["rsi"],
                    t1["rsi"]

                )
                < 24

            )

            breakout = (

                t15["short_break"]
                or t1["short_break"]

            )

        # ----------------------------------------------------
        # HACİM SKORU
        # ----------------------------------------------------

        volume_score = clamp(

            max(
                t15["volume"],
                t1["volume"]
            )
            * 6,

            0,
            20

        )

        # ----------------------------------------------------
        # FINAL
        # ----------------------------------------------------

        final = int(
            round(

                mscore

                + technical
                * 0.60

                + volume_score

            )
        )

        # Aşırı ısınmış
        if overheated:

            final -= 12

        # Kırılım çoktan kaçmışsa
        if breakout:

            if direction == "LONG":

                distance = (
                    t15["long_dist"]
                )

            else:

                distance = (
                    t15["short_dist"]
                )

            if distance > 1.5:

                final -= 10

        # Dirençten çok uzak
        if not near:

            final -= 8

        final = int(
            clamp(
                final,
                0,
                100
            )
        )

        if (
            final
            < MIN_FINAL_SCORE
        ):

            return None

        # ====================================================
        # PRE-PUMP
        # ====================================================

        if direction == "LONG":

            pre = (

                not breakout

                and near

                and t1["trend"]
                == "BULL"

                and t15["rsi"]
                < 72

                and t15["volume"]
                >= 1.0

            )

        else:

            pre = (

                not breakout

                and near

                and t1["trend"]
                == "BEAR"

                and t15["rsi"]
                > 28

                and t15["volume"]
                >= 1.0

            )

        # ====================================================
        # DURUM
        # ====================================================

        if (
            breakout
            and final >= 72
        ):

            status = (
                "BREAKOUT ENTRY"
            )

        elif (
            pre
            and final >= 58
        ):

            status = (
                "PRE-PUMP"
            )

        elif final >= 68:

            status = (
                "STRONG ENTRY"
            )

        else:

            return None

        # ====================================================
        # GİRİŞ PLANI
        # ====================================================

        plan = entry_plan(

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

            "score":
                final,

            "status":
                status,

            "money_score":
                mscore,

            "flow_pct":
                flow_pct,

            "buy_share":
                buy_share,

            "open_total":
                open_total,

            "open_ratio":
                open_ratio,

            "volume":
                max(

                    t15["volume"],
                    t1["volume"]

                ),

            "rsi15":
                t15["rsi"],

            "rsi1h":
                t1["rsi"],

            "amount24":
                amount24,

        })

        return plan

    except Exception as e:

        print(
            symbol,
            "analiz hatası:",
            e
        )

        return None


# ============================================================
# FİYAT FORMAT
# ============================================================

def fmt_price(value):

    value = f(value)

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

def fmt_money(value):

    value = f(value)

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

def build_message(item):

    direction_text = (

        "🟢 LONG"

        if item["direction"]
        == "LONG"

        else

        "🔴 SHORT"

    )

    if item["flow_pct"] >= 60:

        fire = "🔥🔥🔥"

    elif item["flow_pct"] >= 35:

        fire = "🔥🔥"

    else:

        fire = "🔥"

    if (
        item["status"]
        == "BREAKOUT ENTRY"
    ):

        trigger = (
            "🚀 KIRILIM ONAYI"
        )

    else:

        trigger = (
            "🚀 KIRILIM GİRİŞİ"
        )

    return (

        f"🚨 {item['status']} / "
        f"{direction_text}\n\n"

        f"🪙 {item['symbol']}\n"

        f"⭐ {item['score']}/100\n\n"

        f"💰 Para Akışı: "
        f"{fire} "
        f"+{item['flow_pct']:.1f}%\n"

        f"💵 Açılış Akışı: "
        f"{fmt_money(item['open_total'])}\n"

        f"📈 Alış Baskısı: "
        f"{item['buy_share']:.0f}%\n"

        f"📊 Hacim: "
        f"{item['volume']:.1f}x\n\n"

        f"📍 GİRİŞ BÖLGESİ\n"

        f"{fmt_price(item['entry_low'])}"
        f" – "
        f"{fmt_price(item['entry_high'])}\n\n"

        f"{trigger}\n"

        f"{fmt_price(item['breakout_price'])}\n\n"

        f"🛑 STOP\n"

        f"{fmt_price(item['stop'])}\n\n"

        f"🎯 TP1 "
        f"{fmt_price(item['tp1'])}\n"

        f"🎯 TP2 "
        f"{fmt_price(item['tp2'])}\n"

        f"🎯 TP3 "
        f"{fmt_price(item['tp3'])}\n\n"

        f"📌 Destek: "
        f"{fmt_price(item['support'])}\n"

        f"🎯 Direnç: "
        f"{fmt_price(item['resistance'])}\n\n"

        f"⚠️ Teknik sinyaldir. "
        f"Otomatik işlem açmaz."

    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(text):

    if not TOKEN or not CHAT_ID:

        print(
            "Telegram bilgileri eksik."
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
                    True,

            },

            timeout=15

        )

        if response.ok:

            print(
                "Telegram gönderildi."
            )

            return True

        print(
            "Telegram hatası:",
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
        ) as file:

            data = json.load(
                file
            )

        if isinstance(
            data,
            dict
        ):

            return data

    except Exception:

        pass

    return {}


def save_state(state):

    try:

        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(

                state,

                file,

                indent=2,

                ensure_ascii=False

            )

    except Exception as e:

        print(
            "State kayıt hatası:",
            e
        )


# ============================================================
# AYNI COİNİ SÜREKLİ GÖNDERME
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

            "status":
                item["status"],

            "score":
                item["score"],

            "time":
                now,

        }

        return True

    levels = {

        "PRE-PUMP":
            1,

        "STRONG ENTRY":
            2,

        "BREAKOUT ENTRY":
            3,

    }

    old_level = levels.get(

        old.get(
            "status"
        ),

        0

    )

    new_level = levels.get(

        item["status"],

        0

    )

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

    alert = (

        new_level > old_level

        or

        item["score"]
        >= old_score + 5

        or

        now - old_time
        > STATE_EXPIRY

    )

    state[symbol] = {

        "status":
            item["status"],

        "score":
            item["score"],

        "time":
            now,

    }

    return alert


# ============================================================
# ANA RADAR
# ============================================================

def main():

    started = time.time()

    print("=" * 60)

    print(
        "🚀 MEXC PUMP RADAR V12.1"
    )

    print(
        "💰 PARA AKIŞI"
    )

    print(
        "📍 GİRİŞ BÖLGESİ"
    )

    print(
        "🚀 BREAKOUT"
    )

    print(
        "🛑 STOP + TP"
    )

    print("=" * 60)

    # --------------------------------------------------------
    # CONTRACT
    # --------------------------------------------------------

    contracts, symbols = (
        get_contracts()
    )

    # --------------------------------------------------------
    # TICKER
    # --------------------------------------------------------

    tickers = get_tickers()

    if (
        not contracts
        or not tickers
    ):

        raise RuntimeError(
            "MEXC Futures verisi alınamadı."
        )

    ticker_map = {

        str(
            item.get(
                "symbol",
                ""
            )
        ).upper():

        item

        for item in tickers

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

        amount24 = f(

            ticker.get(
                "amount24",
                0
            )

        )

        price = f(

            ticker.get(
                "lastPrice",
                0
            )

        )

        change = abs(

            f(

                ticker.get(
                    "riseFallRate",
                    0
                )

            )
            * 100

        )

        high = f(

            ticker.get(
                "high24Price",
                0
            )

        )

        low = f(

            ticker.get(
                "lower24Price",
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

        # ----------------------------------------------------
        # 24H RANGE KONUMU
        # ----------------------------------------------------

        if high > low:

            position = (

                price - low

            ) / (

                high - low

            )

        else:

            position = 0.5

        # ----------------------------------------------------
        # RANK
        # ----------------------------------------------------

        rank = (

            math.log10(
                max(
                    amount24,
                    1
                )
            )
            * 10

            + position * 5

            - max(
                change - 25,
                0
            )
            * 0.7

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
        "📊 Futures:",
        len(symbols)
    )

    print(
        "📡 Ticker:",
        len(tickers)
    )

    print(
        "🎯 Detaylı analiz:",
        len(candidates)
    )

    # ========================================================
    # DETAYLI ANALİZ
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
                    "Future hata:",
                    symbol,
                    e
                )

    # ========================================================
    # SIRALA
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
    # KONSOL
    # ========================================================

    print(
        "\n===== EN İYİ ADAYLAR ====="
    )

    for item in results[:10]:

        print(

            item["symbol"],

            "|",

            item["direction"],

            "|",

            item["status"],

            "|",

            item["score"],

            "| Money:",

            item["money_score"],

            "| Open:",

            fmt_money(
                item["open_total"]
            )

        )

    print(
        "=========================="
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

    # ========================================================
    # MAX 6 ALARM
    # ========================================================

    alerts = alerts[:6]

    # ========================================================
    # TELEGRAM
    # ========================================================

    for item in alerts:

        print(

            "🚨 YENİ ALARM:",

            item["symbol"],

            item["direction"],

            item["status"],

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

    summary = (

        "🛰 MEXC RADAR V12.1\n\n"

        f"📊 Futures: "
        f"{len(symbols):,}\n"

        f"🔎 Analiz: "
        f"{len(candidates)}\n"

        f"🎯 Uygun aday: "
        f"{len(results)}\n"

        f"🚨 Yeni alarm: "
        f"{len(alerts)}\n"

        f"⏱ Süre: "
        f"{duration:.1f} sn"

    )

    send_telegram(
        summary
    )

    print(
        "✅ Tarama tamamlandı:",
        round(
            duration,
            1
        ),
        "sn"
    )


# ============================================================
# PROGRAM BAŞLANGICI
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        print(
            "🔴 KRİTİK HATA:",
            e
        )

        if TOKEN and CHAT_ID:

            send_telegram(

                "🔴 MEXC RADAR V12.1\n\n"
                "❌ Sistem hatası:\n"
                f"{e}"

            )

        raise
