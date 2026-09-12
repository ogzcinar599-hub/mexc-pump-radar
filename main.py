import os
import json
import time
import math
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PRE-PUMP RADAR V12.2
#
# PARA AKIŞI
# GİRİŞ BÖLGESİ
# KIRILIM GİRİŞİ
# STOP
# TP1 / TP2 / TP3
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

MIN_24H_AMOUNT = 100_000

# Önceki $25K çok sertti.
MIN_OPEN_NOTIONAL = 15_000

# Açılış akışı / 24H hacim
MIN_OPEN_RATIO = 0.0005

# Para skoru
MIN_MONEY_SCORE = 14

# Genel skor
MIN_FINAL_SCORE = 52

STATE_FILE = "signal_state_v12_2.json"
STATE_EXPIRY = 3600


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
# GENEL API
# ============================================================

def api_get(url, params=None):

    global last_request

    try:

        with rate_lock:

            wait = 0.11 - (
                time.time()
                - last_request
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
                    "MEXC-PUMP-RADAR-V12.2"
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

def num(value, default=0.0):

    try:
        return float(value)

    except Exception:
        return default


def average(values):

    if not values:
        return 0.0

    return sum(values) / len(values)


def clamp(value, low, high):

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

def ema(values, period):

    if not values:
        return []

    multiplier = 2 / (
        period + 1
    )

    result = [
        values[0]
    ]

    current = values[0]

    for value in values[1:]:

        current += (
            value - current
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

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# FUTURES KONTRATLARI
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

        clean_symbol = (
            symbol[:-5]
        )

        if (
            base_coin in NON_CRYPTO
            or clean_symbol in NON_CRYPTO
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

    for key in required:

        if key not in data:

            return None

    try:

        length = min(
            len(data[x])
            for x in required
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
# SON İŞLEMLER
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

        # O=1 = pozisyon açılışı
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

        # T=1 alış
        if trade_type == 1:

            buy_open += notional

            buy_count += 1

        # T=2 satış
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

        buy_share = 0

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

    current_rsi = calculate_rsi(
        closes
    )

    previous_rsi = calculate_rsi(
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

    volume_average = average(
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

        price
        / resistance
        - 1

    ) * 100

    short_distance = (

        1
        - price / support

    ) * 100

    # --------------------------------------------------------
    # TREND
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # HIGHER LOW
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

        recent = average(
            ranges[-3:]
        )

        full = average(
            ranges
        )

        if full > 0:

            compression = (
                recent
                < full * 0.85
            )

    # ========================================================
    # LONG SCORE
    # ========================================================

    long_score = 0

    if trend == "BULL":

        long_score += 20

    elif price > ema21:

        long_score += 8

    elif price > ema50:

        long_score += 4

    # RSI
    if 52 <= current_rsi <= 68:

        long_score += 15

    elif 68 < current_rsi <= 72:

        long_score += 7

    # RSI yükseliyor
    if current_rsi > previous_rsi:

        long_score += 6

    # Hacim
    if 1.15 <= volume_ratio <= 2.5:

        long_score += 10

    elif volume_ratio > 2.5:

        long_score += 4

    # Direnç
    if long_break:

        long_score += 12

    elif long_distance >= -1.0:

        long_score += 10

    elif long_distance >= -3.5:

        long_score += 5

    # Yapı
    if higher_low:

        long_score += 8

    if compression:

        long_score += 7

    if momentum_long:

        long_score += 5

    # ========================================================
    # SHORT SCORE
    # ========================================================

    short_score = 0

    if trend == "BEAR":

        short_score += 20

    elif price < ema21:

        short_score += 8

    elif price < ema50:

        short_score += 4

    if 32 <= current_rsi <= 48:

        short_score += 15

    elif 28 <= current_rsi < 32:

        short_score += 7

    if current_rsi < previous_rsi:

        short_score += 6

    if 1.15 <= volume_ratio <= 2.5:

        short_score += 10

    elif volume_ratio > 2.5:

        short_score += 4

    if short_break:

        short_score += 12

    elif short_distance >= -1.0:

        short_score += 10

    elif short_distance >= -3.5:

        short_score += 5

    if lower_high:

        short_score += 8

    if compression:

        short_score += 7

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
            )

    }


# ============================================================
# PARA SKORU
# ============================================================

def calculate_money_score(
    flow,
    amount24
):

    total = flow[
        "open_total"
    ]

    if total <= 0:

        return 0

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

        100
        - flow["buy_share"]

    )

    score = 0

    if total >= 15_000:

        score += 8

    if total >= 30_000:

        score += 5

    if total >= 75_000:

        score += 5

    if ratio >= 0.0005:

        score += 4

    if ratio >= 0.001:

        score += 4

    if net >= 15:

        score += 4

    if net >= 30:

        score += 5

    if net >= 50:

        score += 5

    if share >= 65:

        score += 4

    if share >= 80:

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

def calculate_entry(
    direction,
    t15,
    t1,
    t4
):

    price = t15[
        "close"
    ]

    # --------------------------------------------------------
    # LONG
    # --------------------------------------------------------

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

        breakout = (
            resistance
            * 1.002
        )

        if (
            t15["long_break"]
            or t1["long_break"]
        ):

            # Kırılım gerçekleşmiş
            entry_low = (
                price * 0.997
            )

            entry_high = (
                price * 1.002
            )

        else:

            # Kırılım öncesi bölge
            entry_low = max(

                support,

                price * 0.985

            )

            entry_high = min(

                price * 1.002,

                resistance * 0.995

            )

            if entry_high <= entry_low:

                entry_low = (
                    price * 0.995
                )

                entry_high = (
                    price * 1.002
                )

        # Stop
        risk = max(

            price - support,

            price * 0.012

        )

        stop = price - (
            risk * 0.75
        )

        # Stop maksimum %4
        stop = max(

            stop,

            price * 0.96

        )

        risk_pct = (

            (
                price
                - stop
            )
            / price
            * 100

        )

        risk_pct = clamp(
            risk_pct,
            0.8,
            4.0
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

    # --------------------------------------------------------
    # SHORT
    # --------------------------------------------------------

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

        breakout = (
            support
            * 0.998
        )

        if (
            t15["short_break"]
            or t1["short_break"]
        ):

            entry_low = (
                price * 0.998
            )

            entry_high = (
                price * 1.003
            )

        else:

            entry_low = max(

                price * 0.998,

                support * 1.005

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

        risk = max(

            resistance - price,

            price * 0.012

        )

        stop = price + (
            risk * 0.75
        )

        stop = min(

            stop,

            price * 1.04

        )

        risk_pct = (

            (
                stop
                - price
            )
            / price
            * 100

        )

        risk_pct = clamp(
            risk_pct,
            0.8,
            4.0
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

        amount24 = num(
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
        # PARA AKIŞI FİLTRESİ
        # ====================================================

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

        if flow_pct < 10:

            return None

        if buy_share < 57:

            return None

        money = calculate_money_score(

            flow,

            amount24

        )

        if (
            money
            < MIN_MONEY_SCORE
        ):

            return None

        # ====================================================
        # TEKNİK YÖN
        # ====================================================

        if direction == "LONG":

            technical = (

                t15["long_score"]
                * 0.35

                +

                t1["long_score"]
                * 0.40

                +

                t4["long_score"]
                * 0.25

            )

            distance = max(

                t15["long_dist"],
                t1["long_dist"]

            )

            breakout = (

                t15["long_break"]
                or t1["long_break"]

            )

            trend_ok = (

                t1["trend"]
                in (
                    "BULL",
                    "MIXED"
                )

            )

            overheated = (

                max(
                    t15["rsi"],
                    t1["rsi"]
                )
                > 76

            )

        else:

            technical = (

                t15["short_score"]
                * 0.35

                +

                t1["short_score"]
                * 0.40

                +

                t4["short_score"]
                * 0.25

            )

            distance = max(

                t15["short_dist"],
                t1["short_dist"]

            )

            breakout = (

                t15["short_break"]
                or t1["short_break"]

            )

            trend_ok = (

                t1["trend"]
                in (
                    "BEAR",
                    "MIXED"
                )

            )

            overheated = (

                min(
                    t15["rsi"],
                    t1["rsi"]
                )
                < 24

            )

        # ====================================================
        # DİRENÇ YAKINLIĞI
        # ====================================================

        near = (
            distance
            >= -3.5
        )

        if not near:

            return None

        # ====================================================
        # HACİM
        # ====================================================

        volume = max(

            t15["volume"],
            t1["volume"]

        )

        volume_score = clamp(

            volume * 6,

            0,

            20

        )

        # ====================================================
        # FINAL SKOR
        # ====================================================

        final = int(
            round(

                money

                +

                technical
                * 0.60

                +

                volume_score

            )
        )

        # Aşırı ısınma
        if overheated:

            final -= 12

        # Kırılım kaçmışsa
        if breakout and distance > 1.5:

            final -= 10

        # Trend tamamen ters ise
        if not trend_ok:

            final -= 5

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

            pre_pump = (

                not breakout

                and trend_ok

                and t15["rsi"] < 74

                and volume >= 0.85

                and (
                    t15["higher_low"]
                    or t1["higher_low"]
                )

            )

        else:

            pre_pump = (

                not breakout

                and trend_ok

                and t15["rsi"] > 26

                and volume >= 0.85

                and (
                    t15["lower_high"]
                    or t1["lower_high"]
                )

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
            pre_pump
            and final >= 52
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

        plan = calculate_entry(

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
                money,

            "flow_pct":
                flow_pct,

            "buy_share":
                buy_share,

            "open_total":
                open_total,

            "open_ratio":
                open_ratio,

            "volume":
                volume,

            "rsi15":
                t15["rsi"],

            "rsi1h":
                t1["rsi"],

            "amount24":
                amount24

        })

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

def format_price(value):

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

def format_money(value):

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

def build_trade_message(item):

    direction = (

        "🟢 LONG"

        if item["direction"]
        == "LONG"

        else

        "🔴 SHORT"

    )

    flow = item[
        "flow_pct"
    ]

    if flow >= 60:

        fire = "🔥🔥🔥"

    elif flow >= 35:

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
        f"{direction}\n\n"

        f"🪙 {item['symbol']}\n"

        f"⭐ Skor: "
        f"{item['score']}/100\n\n"

        f"💰 Para Akışı: "
        f"{fire} "
        f"+{flow:.1f}%\n"

        f"💵 Açılış Akışı: "
        f"{format_money(item['open_total'])}\n"

        f"📈 Alış Baskısı: "
        f"{item['buy_share']:.0f}%\n"

        f"📊 Hacim: "
        f"{item['volume']:.1f}x\n\n"

        f"📍 GİRİŞ BÖLGESİ\n"

        f"{format_price(item['entry_low'])}"
        f" – "
        f"{format_price(item['entry_high'])}\n\n"

        f"{trigger}\n"

        f"{format_price(item['breakout'])}\n\n"

        f"🛑 STOP\n"

        f"{format_price(item['stop'])}\n\n"

        f"🎯 TP1 "
        f"{format_price(item['tp1'])}\n"

        f"🎯 TP2 "
        f"{format_price(item['tp2'])}\n"

        f"🎯 TP3 "
        f"{format_price(item['tp3'])}\n\n"

        f"📌 Destek: "
        f"{format_price(item['support'])}\n"

        f"🎯 Direnç: "
        f"{format_price(item['resistance'])}\n\n"

        f"⚠️ Teknik sinyal. "
        f"Otomatik işlem açmaz."

    )


# ============================================================
# TELEGRAM GÖNDER
# ============================================================

def send_telegram(message):

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
# TEKRAR ALARM KONTROLÜ
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
                now

        }

        return True

    levels = {

        "PRE-PUMP":
            1,

        "STRONG ENTRY":
            2,

        "BREAKOUT ENTRY":
            3

    }

    old_level = levels.get(

        old.get(
            "status",
            ""
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

        new_level
        > old_level

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
            now

    }

    return alert


# ============================================================
# ANA RADAR
# ============================================================

def main():

    start = time.time()

    print("=" * 60)

    print(
        "🚀 MEXC PRE-PUMP RADAR V12.2"
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

        change = abs(

            num(

                ticker.get(
                    "riseFallRate",
                    0
                )

            )
            * 100

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

        if (
            amount24
            < MIN_24H_AMOUNT
        ):

            continue

        if price <= 0:

            continue

        # ====================================================
        # 24H KONUM
        # ====================================================

        if high > low:

            position = (

                price - low

            ) / (

                high - low

            )

        else:

            position = 0.5

        # ====================================================
        # RANK
        # ====================================================

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
        "🎯 Analiz:",
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
                    symbol,
                    "Future hata:",
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
    # EN İYİLER
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

            format_money(
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

            build_trade_message(
                item
            )

        )

    # ========================================================
    # ÖZET
    # ========================================================

    duration = (
        time.time()
        - start
    )

    summary = (

        "🛰 MEXC RADAR V12.2\n\n"

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
# BAŞLAT
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

                "🔴 MEXC RADAR V12.2\n\n"
                "❌ Sistem hatası:\n"
                f"{e}"

            )

        raise
