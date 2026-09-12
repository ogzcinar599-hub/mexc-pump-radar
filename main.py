import os
import time
import threading
import requests
import traceback

from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PRE-PUMP RADAR V7.0
#
# ANA AMAÇ:
#
# PUMP BAŞLADIKTAN SONRA DEĞİL,
# PARA / POZİSYON GİRİŞİ BAŞLARKEN BULMAK
#
# 4H  = YAPI
# 1H  = PARA + HACİM
# 15M = TETİK
#
# PARA GİRİŞİ = ANA FİLTRE
#
# OTOMATİK İŞLEM YOK
# ============================================================


BASE = "https://api.mexc.com"

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# AYARLAR
# ============================================================

MAX_WORKERS = 6

MAX_ALERTS = 6

MIN_SCORE = 64

CANDLE_COUNT = 90

TIMEOUT = 12

REQUEST_INTERVAL = 0.12

FOUR_H_MAX = 220

ONE_H_MAX = 100

# İşlem kayıtlarından alınacak son işlem sayısı
DEALS_LIMIT = 100


# ============================================================
# RATE LIMIT
# ============================================================

rate_lock = threading.Lock()

last_request_time = 0.0


def rate_limit():

    global last_request_time

    with rate_lock:

        now = time.time()

        wait = (
            REQUEST_INTERVAL
            -
            (now - last_request_time)
        )

        if wait > 0:
            time.sleep(wait)

        last_request_time = time.time()


# ============================================================
# MEXC GET
# ============================================================

def mexc_get(
    path,
    params=None,
    retry=3
):

    for _ in range(retry):

        try:

            rate_limit()

            response = requests.get(
                BASE + path,
                params=params,
                timeout=TIMEOUT
            )

            if response.status_code != 200:

                time.sleep(0.5)

                continue

            return response.json()

        except Exception:

            time.sleep(0.5)

    return None


# ============================================================
# SYMBOLLER
# ============================================================

def get_symbols():

    print(
        "\n🔎 MEXC Futures coinleri alınıyor...",
        flush=True
    )

    data = mexc_get(
        "/api/v1/contract/detail"
    )

    if not data:

        return []

    rows = data.get(
        "data",
        []
    )

    symbols = []

    for item in rows:

        try:

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

            state = item.get(
                "state"
            )

            if state is not None:

                try:

                    if int(state) != 0:
                        continue

                except Exception:
                    pass

            symbols.append(
                symbol
            )

        except Exception:
            continue

    symbols = sorted(
        set(symbols)
    )

    print(
        f"✅ Futures: {len(symbols)}",
        flush=True
    )

    return symbols


# ============================================================
# KLINE
# ============================================================

def get_klines(
    symbol,
    interval,
    count=CANDLE_COUNT
):

    try:

        seconds_map = {

            "Min15": 900,

            "Min60": 3600,

            "Hour4": 14400

        }

        seconds = seconds_map[
            interval
        ]

        end = int(
            time.time()
        )

        start = (
            end
            -
            seconds * (count + 5)
        )

        data = mexc_get(
            f"/api/v1/contract/kline/{symbol}",
            {
                "interval": interval,
                "start": start,
                "end": end
            }
        )

        if not data:
            return None

        if data.get(
            "success"
        ) is not True:

            return None

        raw = data.get(
            "data"
        )

        if not isinstance(
            raw,
            dict
        ):
            return None

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

        if not closes:
            return None

        n = min(
            len(closes),
            len(highs),
            len(lows),
            len(volumes)
        )

        if n < 50:
            return None

        return {

            "close": [
                float(x)
                for x in closes[-count:]
            ],

            "high": [
                float(x)
                for x in highs[-count:]
            ],

            "low": [
                float(x)
                for x in lows[-count:]
            ],

            "volume": [
                float(x)
                for x in volumes[-count:]
            ]
        }

    except Exception:

        return None


# ============================================================
# TICKER
#
# holdVol = açık pozisyon miktarı
# funding = funding rate
# ============================================================

def get_ticker(symbol):

    data = mexc_get(
        "/api/v1/contract/ticker",
        {
            "symbol": symbol
        }
    )

    if not data:
        return None

    raw = data.get(
        "data"
    )

    if not isinstance(
        raw,
        dict
    ):
        return None

    try:

        return {

            "price": float(
                raw.get(
                    "lastPrice",
                    0
                )
            ),

            "holdVol": float(
                raw.get(
                    "holdVol",
                    0
                )
            ),

            "volume24": float(
                raw.get(
                    "volume24",
                    0
                )
            ),

            "amount24": float(
                raw.get(
                    "amount24",
                    0
                )
            ),

            "funding": float(
                raw.get(
                    "fundingRate",
                    0
                )
            )
        }

    except Exception:

        return None


# ============================================================
# YENİ POZİSYON / PARA AKIŞI
#
# MEXC DEALS:
#
# T = 1 -> alış
# T = 2 -> satış
#
# O = 1 -> pozisyon açılışı
# O = 2 -> pozisyon kapanışı
#
# Biz özellikle:
#
# BUY + OPEN
# SELL + OPEN
#
# karşılaştırıyoruz.
# ============================================================

def get_money_flow(symbol):

    data = mexc_get(
        f"/api/v1/contract/deals/{symbol}",
        {
            "limit": DEALS_LIMIT
        }
    )

    if not data:
        return None

    rows = data.get(
        "data"
    )

    if not isinstance(
        rows,
        list
    ):
        return None

    buy_open = 0.0

    sell_open = 0.0

    total_buy = 0.0

    total_sell = 0.0

    opening_volume = 0.0

    opening_count = 0

    for item in rows:

        try:

            price = float(
                item.get(
                    "p",
                    0
                )
            )

            volume = float(
                item.get(
                    "v",
                    0
                )
            )

            trade_type = int(
                item.get(
                    "T",
                    0
                )
            )

            open_type = int(
                item.get(
                    "O",
                    0
                )
            )

            value = (
                price
                *
                volume
            )

            # ------------------------------------------------
            # TOPLAM ALIM / SATIM
            # ------------------------------------------------

            if trade_type == 1:

                total_buy += value

            elif trade_type == 2:

                total_sell += value

            # ------------------------------------------------
            # SADECE AÇILAN POZİSYONLAR
            # ------------------------------------------------

            if open_type == 1:

                opening_volume += value

                opening_count += 1

                if trade_type == 1:

                    buy_open += value

                elif trade_type == 2:

                    sell_open += value

        except Exception:

            continue

    total_open = (
        buy_open
        +
        sell_open
    )

    if total_open <= 0:

        return {

            "buy_open": 0,
            "sell_open": 0,
            "net": 0,
            "net_pct": 0,
            "opening": 0,
            "count": 0
        }

    # --------------------------------------------------------
    # NET PARA AKIŞI
    # --------------------------------------------------------

    net = (
        buy_open
        -
        sell_open
    )

    net_pct = (
        net
        /
        total_open
    ) * 100

    return {

        "buy_open": buy_open,

        "sell_open": sell_open,

        "net": net,

        "net_pct": net_pct,

        "opening": opening_volume,

        "count": opening_count,

        "total_buy": total_buy,

        "total_sell": total_sell
    }


# ============================================================
# SMA
# ============================================================

def sma(
    values,
    period
):

    if len(values) < period:
        return None

    return (
        sum(
            values[-period:]
        )
        /
        period
    )


# ============================================================
# RSI
# ============================================================

def rsi(
    values,
    period=14
):

    if len(values) < period + 1:
        return None

    gains = []

    losses = []

    start = (
        len(values)
        -
        period
    )

    for i in range(
        start,
        len(values)
    ):

        change = (
            values[i]
            -
            values[i - 1]
        )

        if change > 0:

            gains.append(
                change
            )

            losses.append(0)

        else:

            gains.append(0)

            losses.append(
                abs(change)
            )

    avg_gain = (
        sum(gains)
        /
        period
    )

    avg_loss = (
        sum(losses)
        /
        period
    )

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
# YÜZDE
# ============================================================

def pct_change(
    new,
    old
):

    if old == 0:
        return 0

    return (
        (new - old)
        /
        old
    ) * 100


# ============================================================
# HACİM
# ============================================================

def volume_ratio(
    volumes,
    period=20
):

    if len(volumes) < period + 1:
        return 0

    avg = (
        sum(
            volumes[-period-1:-1]
        )
        /
        period
    )

    if avg <= 0:
        return 0

    return (
        volumes[-1]
        /
        avg
    )


# ============================================================
# HACİM İVMESİ
# ============================================================

def volume_acceleration(
    volumes
):

    if len(volumes) < 30:
        return 0

    recent = (
        sum(
            volumes[-5:]
        )
        /
        5
    )

    old = (
        sum(
            volumes[-25:-5]
        )
        /
        20
    )

    if old <= 0:
        return 0

    return (
        recent
        /
        old
    )


# ============================================================
# HACİM TRENDİ
# ============================================================

def volume_trend(
    volumes
):

    if len(volumes) < 15:
        return 0

    a = (
        sum(
            volumes[-15:-10]
        )
        /
        5
    )

    b = (
        sum(
            volumes[-10:-5]
        )
        /
        5
    )

    c = (
        sum(
            volumes[-5:]
        )
        /
        5
    )

    if a <= 0:
        return 0

    return c / a


# ============================================================
# MOMENTUM
# ============================================================

def momentum(
    closes,
    candles
):

    if len(closes) < candles + 1:
        return 0

    return pct_change(
        closes[-1],
        closes[-candles-1]
    )


# ============================================================
# HIGHER LOW
# ============================================================

def higher_low_score(
    lows
):

    if len(lows) < 40:
        return 0

    a = min(
        lows[-30:-20]
    )

    b = min(
        lows[-20:-10]
    )

    c = min(
        lows[-10:]
    )

    score = 0

    if b > a:
        score += 7

    if c > b:
        score += 10

    return score


# ============================================================
# SIKIŞMA
# ============================================================

def compression_score(
    highs,
    lows
):

    if len(highs) < 40:
        return 0

    recent_high = max(
        highs[-10:]
    )

    recent_low = min(
        lows[-10:]
    )

    old_high = max(
        highs[-30:-10]
    )

    old_low = min(
        lows[-30:-10]
    )

    recent_range = (
        recent_high
        -
        recent_low
    )

    old_range = (
        old_high
        -
        old_low
    )

    if old_range <= 0:
        return 0

    ratio = (
        recent_range
        /
        old_range
    )

    if ratio <= 0.45:
        return 18

    if ratio <= 0.60:
        return 14

    if ratio <= 0.75:
        return 9

    if ratio <= 0.90:
        return 4

    return 0


# ============================================================
# DİRENÇ
# ============================================================

def resistance_distance(
    closes,
    highs
):

    if len(closes) < 40:
        return 999

    price = closes[-1]

    resistance = max(
        highs[-30:]
    )

    if resistance <= 0:
        return 999

    return (
        (
            resistance
            -
            price
        )
        /
        resistance
    ) * 100


# ============================================================
# ZATEN PUMP MI?
# ============================================================

def already_pumped(
    closes
):

    if len(closes) < 40:
        return True

    m3 = momentum(
        closes,
        3
    )

    m5 = momentum(
        closes,
        5
    )

    m10 = momentum(
        closes,
        10
    )

    m20 = momentum(
        closes,
        20
    )

    if m3 > 10:
        return True

    if m5 > 16:
        return True

    if m10 > 25:
        return True

    if m20 > 40:
        return True

    return False


# ============================================================
# 4H ANALİZ
# ============================================================

def analyze_4h(
    data
):

    if not data:
        return None

    closes = data["close"]

    highs = data["high"]

    lows = data["low"]

    volumes = data["volume"]

    if already_pumped(
        closes
    ):
        return None

    r = rsi(
        closes
    )

    ma20 = sma(
        closes,
        20
    )

    ma50 = sma(
        closes,
        50
    )

    compression = compression_score(
        highs,
        lows
    )

    higher_low = higher_low_score(
        lows
    )

    distance = resistance_distance(
        closes,
        highs
    )

    mom10 = momentum(
        closes,
        10
    )

    score = 0

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if r is not None:

        if 45 <= r <= 65:

            score += 7

        elif 65 < r <= 70:

            score += 3

    # --------------------------------------------------------
    # MA
    # --------------------------------------------------------

    if ma20 and ma50:

        if closes[-1] > ma20:

            score += 6

        if ma20 > ma50:

            score += 6

    # --------------------------------------------------------
    # SIKIŞMA
    # --------------------------------------------------------

    score += compression

    # --------------------------------------------------------
    # HIGHER LOW
    # --------------------------------------------------------

    score += higher_low

    # --------------------------------------------------------
    # DİRENÇ
    # --------------------------------------------------------

    if 0 <= distance <= 3:

        score += 12

    elif 3 < distance <= 6:

        score += 9

    elif 6 < distance <= 10:

        score += 4

    # --------------------------------------------------------
    # KONTROLLÜ MOMENTUM
    # --------------------------------------------------------

    if 0 < mom10 < 10:

        score += 5

    elif mom10 > 15:

        score -= 5

    return {

        "score": score,

        "rsi": r,

        "distance": distance,

        "momentum": mom10
    }


# ============================================================
# 1H ANALİZ
# ============================================================

def analyze_1h(
    data
):

    if not data:
        return None

    closes = data["close"]

    highs = data["high"]

    lows = data["low"]

    volumes = data["volume"]

    r = rsi(
        closes
    )

    ma20 = sma(
        closes,
        20
    )

    ma50 = sma(
        closes,
        50
    )

    vr = volume_ratio(
        volumes
    )

    acc = volume_acceleration(
        volumes
    )

    trend = volume_trend(
        volumes
    )

    hl = higher_low_score(
        lows
    )

    distance = resistance_distance(
        closes,
        highs
    )

    mom = momentum(
        closes,
        5
    )

    # ========================================================
    # ÖLÜ HACİM
    # ========================================================

    if vr < 0.80:

        return None

    score = 0

    # RSI
    if r is not None:

        if 50 <= r <= 67:

            score += 7

        elif 45 <= r < 50:

            score += 3

        elif r > 72:

            score -= 8

    # MA
    if ma20 and ma50:

        if closes[-1] > ma20:

            score += 6

        if ma20 > ma50:

            score += 6

    # Hacim
    if vr >= 1.30:

        score += 8

    elif vr >= 1.10:

        score += 6

    elif vr >= 0.90:

        score += 3

    # Hacim ivmesi
    if acc >= 1.50:

        score += 8

    elif acc >= 1.25:

        score += 6

    elif acc >= 1.10:

        score += 3

    # Hacim trendi
    if trend >= 1.50:

        score += 5

    elif trend >= 1.20:

        score += 3

    # Higher Low
    if hl >= 12:

        score += 7

    elif hl >= 7:

        score += 4

    # Momentum
    if 0.3 <= mom <= 8:

        score += 6

    elif mom > 12:

        score -= 5

    elif mom < -8:

        score -= 5

    # Direnç
    if 0 <= distance <= 3:

        score += 7

    elif 3 < distance <= 6:

        score += 5

    elif 6 < distance <= 10:

        score += 2

    return {

        "score": score,

        "rsi": r,

        "volume": vr,

        "acc": acc,

        "trend": trend,

        "distance": distance,

        "momentum": mom
    }


# ============================================================
# 15M ANALİZ
# ============================================================

def analyze_15m(
    data
):

    if not data:
        return None

    closes = data["close"]

    highs = data["high"]

    volumes = data["volume"]

    r = rsi(
        closes
    )

    vr = volume_ratio(
        volumes
    )

    acc = volume_acceleration(
        volumes
    )

    trend = volume_trend(
        volumes
    )

    distance = resistance_distance(
        closes,
        highs
    )

    mom3 = momentum(
        closes,
        3
    )

    mom5 = momentum(
        closes,
        5
    )

    # ========================================================
    # AŞIRI ISINMIŞ 15M
    # ========================================================

    if r is not None and r > 75:

        return None

    if vr < 0.70:

        return None

    score = 0

    # RSI
    if r is not None:

        if 50 <= r <= 68:

            score += 5

        elif 45 <= r < 50:

            score += 2

    # Hacim
    if vr >= 1.50:

        score += 8

    elif vr >= 1.20:

        score += 6

    elif vr >= 0.90:

        score += 4

    # Hacim ivmesi
    if acc >= 1.60:

        score += 10

    elif acc >= 1.30:

        score += 7

    elif acc >= 1.10:

        score += 4

    # Hacim trendi
    if trend >= 1.50:

        score += 5

    elif trend >= 1.20:

        score += 3

    # Momentum
    if 0.2 <= mom3 <= 5:

        score += 6

    elif 5 < mom3 <= 8:

        score += 3

    elif mom3 > 10:

        score -= 6

    if mom5 > 15:

        score -= 5

    # Direnç
    if 0 <= distance <= 2:

        score += 8

    elif 2 < distance <= 4:

        score += 6

    elif 4 < distance <= 7:

        score += 3

    return {

        "score": score,

        "rsi": r,

        "volume": vr,

        "acc": acc,

        "trend": trend,

        "distance": distance,

        "momentum": mom3
    }


# ============================================================
# PARA GİRİŞİ PUANI
#
# ANA FİLTRE
# ============================================================

def money_score(
    flow,
    ticker
):

    if not flow:

        return 0

    score = 0

    net_pct = flow["net_pct"]

    opening = flow["opening"]

    buy_open = flow["buy_open"]

    sell_open = flow["sell_open"]

    # ========================================================
    # NET YENİ POZİSYON AKIŞI
    # ========================================================

    if net_pct >= 45:

        score += 40

    elif net_pct >= 35:

        score += 34

    elif net_pct >= 25:

        score += 28

    elif net_pct >= 18:

        score += 22

    elif net_pct >= 10:

        score += 14

    elif net_pct >= 5:

        score += 7

    elif net_pct < 0:

        score -= 15

    # ========================================================
    # YETERLİ İŞLEM AKIŞI
    # ========================================================

    if opening <= 0:

        return 0

    # ========================================================
    # BUY / SELL DENGESİ
    # ========================================================

    total = (
        buy_open
        +
        sell_open
    )

    if total > 0:

        buy_share = (
            buy_open
            /
            total
        ) * 100

        if buy_share >= 70:

            score += 10

        elif buy_share >= 62:

            score += 7

        elif buy_share >= 55:

            score += 3

    # ========================================================
    # FUNDING
    #
    # Aşırı pozitif funding'i cezalandırıyoruz.
    # ========================================================

    if ticker:

        funding = ticker[
            "funding"
        ]

        # Çok yüksek funding =
        # kalabalık long riski

        if funding > 0.0015:

            score -= 8

        elif funding > 0.001:

            score -= 3

    return max(
        0,
        min(
            score,
            50
        )
    )


# ============================================================
# ANA COIN ANALİZİ
# ============================================================

def analyze_symbol(
    symbol
):

    try:

        # ----------------------------------------------------
        # 4H
        # ----------------------------------------------------

        data4 = get_klines(
            symbol,
            "Hour4"
        )

        a4 = analyze_4h(
            data4
        )

        if not a4:
            return None

        if a4["score"] < 25:
            return None

        # ----------------------------------------------------
        # 1H
        # ----------------------------------------------------

        data1 = get_klines(
            symbol,
            "Min60"
        )

        a1 = analyze_1h(
            data1
        )

        if not a1:
            return None

        if a1["score"] < 20:
            return None

        # ----------------------------------------------------
        # 15M
        # ----------------------------------------------------

        data15 = get_klines(
            symbol,
            "Min15"
        )

        a15 = analyze_15m(
            data15
        )

        if not a15:
            return None

        # ----------------------------------------------------
        # TICKER
        # ----------------------------------------------------

        ticker = get_ticker(
            symbol
        )

        if not ticker:
            return None

        # ----------------------------------------------------
        # PARA AKIŞI
        # ----------------------------------------------------

        flow = get_money_flow(
            symbol
        )

        if not flow:
            return None

        # ====================================================
        # PARA GİRİŞİ ZORUNLU
        # ====================================================

        if flow["net_pct"] < 8:

            return None

        # ====================================================
        # PARA PUANI
        # ====================================================

        money = money_score(
            flow,
            ticker
        )

        if money < 10:

            return None

        # ====================================================
        # TEKNİK PUAN
        # ====================================================

        technical = (

            a4["score"] * 0.25

            +

            a1["score"] * 0.30

            +

            a15["score"] * 0.20

        )

        # ====================================================
        # HACİM PUANI
        # ====================================================

        volume_bonus = 0

        if a1["volume"] >= 1.10:

            volume_bonus += 5

        if a1["acc"] >= 1.25:

            volume_bonus += 5

        if a15["acc"] >= 1.30:

            volume_bonus += 5

        # ====================================================
        # PARA GİRİŞİ ANA AĞIRLIK
        # ====================================================

        total = (

            money * 0.55

            +

            technical * 0.35

            +

            volume_bonus * 0.10

        )

        total = round(
            total,
            1
        )

        # ====================================================
        # AŞIRI ISINMIŞ COINLERİ ELE
        # ====================================================

        if (
            a4["rsi"] is not None
            and
            a4["rsi"] > 70
        ):

            total -= 8

        if (
            a1["rsi"] is not None
            and
            a1["rsi"] > 72
        ):

            total -= 8

        if (
            a15["rsi"] is not None
            and
            a15["rsi"] > 73
        ):

            total -= 8

        # ====================================================
        # 15M HACİM AŞIRI PATLAMIŞSA
        # PUMP BAŞLAMIŞ OLABİLİR
        # ====================================================

        if a15["volume"] > 5:

            total -= 10

        if a15["momentum"] > 8:

            total -= 8

        # ====================================================
        # FİNAL
        # ====================================================

        if total < MIN_SCORE:

            return None

        return {

            "symbol": symbol,

            "score": total,

            "price": ticker["price"],

            "money_score": money,

            "net_flow": flow["net_pct"],

            "buy_open": flow["buy_open"],

            "sell_open": flow["sell_open"],

            "hold_vol": ticker["holdVol"],

            "funding": ticker["funding"],

            "rsi4": a4["rsi"],

            "rsi1": a1["rsi"],

            "rsi15": a15["rsi"],

            "vol1": a1["volume"],

            "vol15": a15["volume"],

            "acc1": a1["acc"],

            "acc15": a15["acc"],

            "dist4": a4["distance"],

            "dist15": a15["distance"],

            "mom1": a1["momentum"],

            "mom15": a15["momentum"]
        }

    except Exception:

        return None


# ============================================================
# TP
# ============================================================

def calculate_tp(
    price
):

    return {

        "tp1": price * 1.03,

        "tp2": price * 1.06,

        "tp3": price * 1.10
    }


# ============================================================
# TELEGRAM
#
# SADECE KISA MESAJ
# ============================================================

def format_telegram(
    x
):

    tp = calculate_tp(
        x["price"]
    )

    net = x["net_flow"]

    if net >= 35:

        flow_icon = "🔥🔥🔥"

    elif net >= 25:

        flow_icon = "🔥🔥"

    else:

        flow_icon = "🔥"

    return (
        "🚨 <b>PRE-PUMP</b>\n"
        "\n"
        f"🪙 <b>{x['symbol']}</b>\n"
        f"⭐ <b>{x['score']}/100</b>\n"
        "\n"
        f"💰 Para Girişi: "
        f"<b>{flow_icon} +{net:.1f}%</b>\n"
        f"📈 Hacim: "
        f"<b>{x['vol15']:.1f}x</b>\n"
        f"🎯 Direnç: "
        f"%{x['dist4']:.1f}\n"
        "\n"
        f"TP1 +3% → {tp['tp1']:.8g}\n"
        f"TP2 +6% → {tp['tp2']:.8g}\n"
        f"TP3 +10% → {tp['tp3']:.8g}"
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(
    message
):

    if not TOKEN or not CHAT_ID:

        print(
            "⚠️ Telegram secret yok",
            flush=True
        )

        return False

    try:

        url = (
            "https://api.telegram.org/bot"
            f"{TOKEN}/sendMessage"
        )

        response = requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=15
        )

        if response.status_code == 200:

            print(
                "📨 Telegram gönderildi",
                flush=True
            )

            return True

        print(
            f"❌ Telegram HTTP "
            f"{response.status_code}",
            flush=True
        )

    except Exception as e:

        print(
            f"❌ Telegram: {e}",
            flush=True
        )

    return False


# ============================================================
# API TEST
# ============================================================

def api_test():

    print(
        "\n🧪 API TEST",
        flush=True
    )

    data = get_klines(
        "BTC_USDT",
        "Min15",
        50
    )

    if not data:

        print(
            "❌ Kline başarısız",
            flush=True
        )

        return False

    ticker = get_ticker(
        "BTC_USDT"
    )

    if not ticker:

        print(
            "❌ Ticker başarısız",
            flush=True
        )

        return False

    flow = get_money_flow(
        "BTC_USDT"
    )

    print(
        "✅ Kline OK",
        flush=True
    )

    print(
        "✅ Ticker OK",
        flush=True
    )

    if flow:

        print(
            f"✅ İşlem akışı OK | "
            f"Net: {flow['net_pct']:.2f}%",
            flush=True
        )

    else:

        print(
            "⚠️ İşlem akışı alınamadı",
            flush=True
        )

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    start = time.time()

    print(
        "\n"
        "====================================================\n"
        "🚀 MEXC PRE-PUMP RADAR V7.0\n"
        "====================================================",
        flush=True
    )

    print(
        "💰 ANA FİLTRE: PARA GİRİŞİ",
        flush=True
    )

    print(
        "🔥 HACİM + OI/POZİSYON AKIŞI",
        flush=True
    )

    print(
        "🎯 SADECE EN GÜÇLÜ ADAYLAR",
        flush=True
    )

    # --------------------------------------------------------
    # API
    # --------------------------------------------------------

    if not api_test():

        return

    # --------------------------------------------------------
    # SYMBOLS
    # --------------------------------------------------------

    symbols = get_symbols()

    if not symbols:

        print(
            "❌ Coin yok",
            flush=True
        )

        return

    print(
        f"\n🔍 {len(symbols)} Futures coin taranıyor...",
        flush=True
    )

    # --------------------------------------------------------
    # 4H + 1H
    #
    # Önce hızlı teknik filtre
    # --------------------------------------------------------

    candidates = []

    completed = 0

    def technical_scan(
        symbol
    ):

        try:

            data4 = get_klines(
                symbol,
                "Hour4"
            )

            a4 = analyze_4h(
                data4
            )

            if not a4:
                return None

            if a4["score"] < 25:
                return None

            data1 = get_klines(
                symbol,
                "Min60"
            )

            a1 = analyze_1h(
                data1
            )

            if not a1:
                return None

            if a1["score"] < 20:
                return None

            data15 = get_klines(
                symbol,
                "Min15"
            )

            a15 = analyze_15m(
                data15
            )

            if not a15:
                return None

            return {

                "symbol": symbol,

                "a4": a4,

                "a1": a1,

                "a15": a15
            }

        except Exception:

            return None

    print(
        "\n🟣 TEKNİK ÖN FİLTRE...",
        flush=True
    )

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                technical_scan,
                symbol
            ): symbol

            for symbol in symbols
        }

        for future in as_completed(
            futures
        ):

            completed += 1

            try:

                result = future.result()

                if result:

                    candidates.append(
                        result
                    )

            except Exception:
                pass

            if (
                completed % 100 == 0
                or
                completed == len(symbols)
            ):

                print(
                    f"İlerleme "
                    f"{completed}/{len(symbols)} "
                    f"| Teknik aday "
                    f"{len(candidates)}",
                    flush=True
                )

    print(
        f"✅ Teknik aday: "
        f"{len(candidates)}",
        flush=True
    )

    # --------------------------------------------------------
    # PARA AKIŞI
    # --------------------------------------------------------

    print(
        "\n💰 PARA GİRİŞİ TARAMASI...",
        flush=True
    )

    # Teknik olarak en iyileri önce
    candidates.sort(
        key=lambda x: (
            x["a4"]["score"]
            +
            x["a1"]["score"]
            +
            x["a15"]["score"]
        ),
        reverse=True
    )

    candidates = candidates[
        :FOUR_H_MAX
    ]

    final = []

    def money_scan(
        item
    ):

        symbol = item["symbol"]

        ticker = get_ticker(
            symbol
        )

        if not ticker:
            return None

        flow = get_money_flow(
            symbol
        )

        if not flow:
            return None

        # ----------------------------------------------------
        # PARA GİRİŞİ ZORUNLU
        # ----------------------------------------------------

        if flow["net_pct"] < 8:

            return None

        money = money_score(
            flow,
            ticker
        )

        if money < 10:

            return None

        a4 = item["a4"]

        a1 = item["a1"]

        a15 = item["a15"]

        # ----------------------------------------------------
        # PUAN
        # ----------------------------------------------------

        technical = (

            a4["score"] * 0.25

            +

            a1["score"] * 0.30

            +

            a15["score"] * 0.20
        )

        volume_bonus = 0

        if a1["volume"] >= 1.10:
            volume_bonus += 5

        if a1["acc"] >= 1.25:
            volume_bonus += 5

        if a15["acc"] >= 1.30:
            volume_bonus += 5

        total = (

            money * 0.55

            +

            technical * 0.35

            +

            volume_bonus * 0.10
        )

        # ----------------------------------------------------
        # GEÇ KALMIŞ COIN CEZASI
        # ----------------------------------------------------

        if (
            a4["rsi"] is not None
            and
            a4["rsi"] > 70
        ):

            total -= 8

        if (
            a1["rsi"] is not None
            and
            a1["rsi"] > 72
        ):

            total -= 8

        if (
            a15["rsi"] is not None
            and
            a15["rsi"] > 73
        ):

            total -= 8

        if a15["volume"] > 5:

            total -= 10

        if a15["momentum"] > 8:

            total -= 8

        total = round(
            total,
            1
        )

        if total < MIN_SCORE:

            return None

        return {

            "symbol": symbol,

            "score": total,

            "price": ticker["price"],

            "money_score": money,

            "net_flow": flow["net_pct"],

            "buy_open": flow["buy_open"],

            "sell_open": flow["sell_open"],

            "hold_vol": ticker["holdVol"],

            "funding": ticker["funding"],

            "rsi4": a4["rsi"],

            "rsi1": a1["rsi"],

            "rsi15": a15["rsi"],

            "vol1": a1["volume"],

            "vol15": a15["volume"],

            "acc1": a1["acc"],

            "acc15": a15["acc"],

            "dist4": a4["distance"],

            "mom1": a1["momentum"],

            "mom15": a15["momentum"]
        }

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                money_scan,
                item
            )
            for item in candidates
        ]

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                if result:

                    final.append(
                        result
                    )

            except Exception:
                pass

    # --------------------------------------------------------
    # SIRALAMA
    # --------------------------------------------------------

    final.sort(
        key=lambda x: (
            x["money_score"],
            x["score"],
            x["net_flow"]
        ),
        reverse=True
    )

    print(
        "\n====================================================",
        flush=True
    )

    print(
        f"💰 PARA GİRİŞİ OLAN: "
        f"{len(final)}",
        flush=True
    )

    print(
        "====================================================",
        flush=True
    )

    # --------------------------------------------------------
    # LOG
    # --------------------------------------------------------

    for i, x in enumerate(
        final[:15],
        1
    ):

        print(
            f"{i:02d}. "
            f"{x['symbol']} "
            f"| SCORE {x['score']} "
            f"| PARA +{x['net_flow']:.1f}% "
            f"| 1H V {x['vol1']:.2f}x "
            f"| 15M V {x['vol15']:.2f}x "
            f"| RSI15 {x['rsi15']:.1f}",
            flush=True
        )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    alerts = final[
        :MAX_ALERTS
    ]

    if not alerts:

        print(
            "\n📭 Güçlü para girişi bulunamadı.",
            flush=True
        )

    else:

        print(
            f"\n📨 {len(alerts)} coin Telegram'a gönderiliyor...",
            flush=True
        )

        for x in alerts:

            send_telegram(
                format_telegram(x)
            )

            time.sleep(
                0.5
            )

    # --------------------------------------------------------
    # SON
    # --------------------------------------------------------

    elapsed = (
        time.time()
        -
        start
    )

    print(
        "\n====================================================",
        flush=True
    )

    print(
        "✅ V7 RADAR TAMAMLANDI",
        flush=True
    )

    print(
        f"⏱️ Süre: {elapsed:.1f} sn",
        flush=True
    )

    print(
        f"🪙 Futures: {len(symbols)}",
        flush=True
    )

    print(
        f"🔎 Teknik: {len(candidates)}",
        flush=True
    )

    print(
        f"💰 Para girişi: {len(final)}",
        flush=True
    )

    print(
        f"📨 Telegram: {len(alerts)}",
        flush=True
    )

    print(
        "====================================================",
        flush=True
    )


# ============================================================
# BAŞLAT
# ============================================================

if __name__ == "__main__":

    print(
        "### MEXC PRE-PUMP RADAR V7.0 BAŞLADI ###",
        flush=True
    )

    try:

        main()

    except Exception as e:

        print(
            "\n❌ ANA HATA:",
            flush=True
        )

        print(
            str(e),
            flush=True
        )

        traceback.print_exc()

        raise
