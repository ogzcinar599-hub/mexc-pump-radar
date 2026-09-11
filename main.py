import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PUMP RADAR 19.0
#
# AMAÇ:
# PUMP BAŞLAMADAN ÖNCEKİ COİNLERİ BULMAK
#
# 3 MODEL:
#
# 🟡 PUMP ÖNCESİ
# 🟢 BREAKOUT
# 🔵 RETEST
#
# SADECE:
# ✅ MEXC USDT FUTURES
# ✅ 15M
# ✅ 1H
# ✅ 4H
# ✅ RSI
# ✅ RSI YÖNÜ
# ✅ HACİM
# ✅ HACİM YÖNÜ
# ✅ EMA TREND
# ✅ MOMENTUM
# ✅ DİRENÇ
# ✅ BREAKOUT
# ✅ RETEST
# ✅ BTC FİLTRESİ
#
# ❌ STOCK
# ❌ TOKENIZED STOCK
# ❌ SPOT
# ❌ AŞIRI ŞİŞMİŞ COIN
# ❌ YÜKSEK HACİM + SATIŞ BASKISI
# ❌ BTC BEARISH LONG
#
# ============================================================


BASE = "https://contract.mexc.com"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HISTORY_FILE = "signal_history.json"

MAX_WORKERS = 12


# ============================================================
# ANA AYARLAR
# ============================================================

MIN_SCORE = 72

MIN_VOLUME = 2.90

MIN_RSI_4H = 47.0

MAX_RSI_15 = 74.0
MAX_RSI_1H = 72.0

COOLDOWN_HOURS = 6

# Aynı taramada Telegram'a maksimum sinyal
MAX_TELEGRAM_SIGNALS = 8


# ============================================================
# PUMP ÖNCESİ AYARLARI
# ============================================================

PRE_MIN_VOLUME = 2.90
PRE_MAX_VOLUME = 15.0

PRE_MAX_15M_CHANGE = 5.0
PRE_MAX_1H_CHANGE = 7.0
PRE_MAX_4H_CHANGE = 10.0


# ============================================================
# BREAKOUT AYARLARI
# ============================================================

BREAKOUT_MIN_VOLUME = 3.0

BREAKOUT_MAX_EXTENSION = 4.5


# ============================================================
# RETEST AYARLARI
# ============================================================

RETEST_LOOKBACK = 8

RETEST_MAX_DISTANCE = 2.0


# ============================================================
# REQUEST
# ============================================================

def get_json(url, params=None, timeout=10):

    try:

        r = requests.get(
            url,
            params=params,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        if r.status_code != 200:
            return None

        return r.json()

    except Exception:

        return None


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(text):

    if not BOT_TOKEN or not CHAT_ID:
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    try:

        r = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": text,
                "disable_web_page_preview": True
            },
            timeout=15
        )

        return r.status_code == 200

    except Exception:

        return False


# ============================================================
# HISTORY
# ============================================================

def load_history():

    try:

        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

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
                indent=2
            )

    except Exception:

        pass


# ============================================================
# STOCK FİLTRESİ
# ============================================================

def is_stock_symbol(symbol):

    s = symbol.upper()

    bad_words = [

        "STOCK",
        "STOCKS",
        "TOKENIZED",
        "TOKENISED",
        "ETF",
        "ETFS",
        "SHARE",
        "SHARES",
        "EQUITY",
        "EQUITIES",
        "INDEX",
        "INDICES"

    ]

    for word in bad_words:

        if word in s:
            return True

    known_stock_names = [

        "AAPL",
        "AMZN",
        "GOOG",
        "GOOGL",
        "META",
        "MSFT",
        "NVDA",
        "TSLA",
        "NFLX",
        "AMD",
        "INTC",
        "COIN",
        "MSTR",
        "PLTR",
        "HOOD",
        "AMBR",
        "MAV",
        "AAL",
        "BA",
        "NKE",
        "DIS",
        "JPM",
        "V",
        "MA",
        "WMT",
        "PFE",
        "PYPL",
        "UBER",
        "ORCL",
        "CRM",
        "AVGO",
        "QCOM",
        "MU",
        "COST",
        "PEP",
        "KO",
        "XOM",
        "CVX"

    ]

    base = (
        s
        .replace("_USDT", "")
        .replace("/USDT", "")
    )

    if base in known_stock_names:
        return True

    return False


# ============================================================
# FUTURES
# ============================================================

def get_futures_symbols():

    data = get_json(
        f"{BASE}/api/v1/contract/detail"
    )

    if not data:
        return []

    symbols = []

    for item in data.get("data", []):

        symbol = item.get("symbol")

        if not symbol:
            continue

        symbol = symbol.upper()

        if not symbol.endswith("_USDT"):
            continue

        if is_stock_symbol(symbol):
            continue

        if item.get("state") not in [0, None]:
            continue

        symbols.append(symbol)

    return list(
        dict.fromkeys(symbols)
    )


# ============================================================
# KLINE
# ============================================================

def get_klines(
    symbol,
    interval,
    limit=120
):

    url = (
        f"{BASE}/api/v1/contract/kline/"
        f"{symbol}"
    )

    data = get_json(
        url,
        params={
            "interval": interval,
            "limit": limit
        }
    )

    if not data:
        return None

    d = data.get("data")

    if not d:
        return None

    try:

        closes = d.get("close", [])
        opens = d.get("open", [])
        volumes = d.get("vol", [])
        highs = d.get("high", [])
        lows = d.get("low", [])

        if len(closes) < 30:
            return None

        return {

            "close": [
                float(x)
                for x in closes
            ],

            "open": [
                float(x)
                for x in opens
            ],

            "volume": [
                float(x)
                for x in volumes
            ],

            "high": [
                float(x)
                for x in highs
            ],

            "low": [
                float(x)
                for x in lows
            ]

        }

    except Exception:

        return None


# ============================================================
# RSI
# ============================================================

def calculate_rsi(
    closes,
    period=14
):

    if len(closes) < period + 2:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(closes)):

        change = (
            closes[i]
            - closes[i - 1]
        )

        if change >= 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(change)
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
            avg_gain * (period - 1)
            + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1)
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return (
        100
        - (
            100
            / (1 + rs)
        )
    )


# ============================================================
# EMA
# ============================================================

def calculate_ema(
    values,
    period
):

    if len(values) < period:
        return values[-1]

    multiplier = (
        2
        / (period + 1)
    )

    ema = (
        sum(values[:period])
        / period
    )

    for price in values[period:]:

        ema = (
            (price - ema)
            * multiplier
        ) + ema

    return ema


# ============================================================
# YÜZDE DEĞİŞİM
# ============================================================

def pct_change(
    closes,
    candles
):

    if len(closes) <= candles:
        return 0.0

    old = closes[
        -candles - 1
    ]

    new = closes[-1]

    if old == 0:
        return 0.0

    return (
        (new - old)
        / old
    ) * 100


# ============================================================
# HACİM ORANI
# ============================================================

def volume_ratio(volumes):

    if len(volumes) < 25:
        return 1.0

    avg = (
        sum(volumes[-21:-1])
        / 20
    )

    if avg <= 0:
        return 1.0

    recent = volumes[-3:]

    ratios = [
        x / avg
        for x in recent
    ]

    return max(ratios)


# ============================================================
# HACİM YÖNÜ
#
# Hacim yüksekken mumun gövdesine bakıyoruz.
#
# BUY  = alış baskısı
# SELL = satış baskısı
#
# ============================================================

def volume_direction(
    opens,
    closes,
    volumes
):

    if len(closes) < 25:
        return "NEUTRAL", 50.0

    avg = (
        sum(volumes[-21:-1])
        / 20
    )

    if avg <= 0:
        return "NEUTRAL", 50.0

    buy_volume = 0.0
    sell_volume = 0.0

    start = max(
        0,
        len(closes) - 5
    )

    for i in range(
        start,
        len(closes)
    ):

        ratio = (
            volumes[i]
            / avg
        )

        body = (
            closes[i]
            - opens[i]
        )

        # Mum gövdesinin yüzdesi
        if body > 0:

            buy_volume += ratio

        elif body < 0:

            sell_volume += ratio

    total = (
        buy_volume
        + sell_volume
    )

    if total <= 0:
        return "NEUTRAL", 50.0

    buy_percent = (
        buy_volume
        / total
    ) * 100

    if buy_percent >= 60:

        return "BUY", buy_percent

    if buy_percent <= 40:

        return "SELL", buy_percent

    return "NEUTRAL", buy_percent


# ============================================================
# RSI YÖNÜ
# ============================================================

def rsi_direction(closes):

    if len(closes) < 25:

        return "FLAT", 0.0

    current = calculate_rsi(
        closes
    )

    previous = calculate_rsi(
        closes[:-1]
    )

    previous2 = calculate_rsi(
        closes[:-2]
    )

    delta = (
        current
        - previous
    )

    delta2 = (
        previous
        - previous2
    )

    if (
        delta > 0.7
        and delta2 >= 0
    ):

        return "UP", delta

    if (
        delta < -0.7
        and delta2 <= 0
    ):

        return "DOWN", delta

    return "FLAT", delta


# ============================================================
# 4H TREND
# ============================================================

def get_trend(closes):

    if len(closes) < 60:

        return {

            "ema20": closes[-1],
            "ema50": closes[-1],
            "slope": 0.0,
            "trend": "NEUTRAL"

        }

    ema20 = calculate_ema(
        closes,
        20
    )

    ema50 = calculate_ema(
        closes,
        50
    )

    ema20_prev = calculate_ema(
        closes[:-5],
        20
    )

    if ema20_prev == 0:

        slope = 0.0

    else:

        slope = (
            (
                ema20
                - ema20_prev
            )
            / ema20_prev
        ) * 100

    if (
        ema20 > ema50
        and slope >= 0
    ):

        trend = "BULLISH"

    elif (
        ema20 >= ema50 * 0.995
        and slope >= -0.15
    ):

        trend = "RECOVERY"

    else:

        trend = "BEARISH"

    return {

        "ema20": ema20,
        "ema50": ema50,
        "slope": slope,
        "trend": trend

    }


# ============================================================
# 15M BREAKOUT / RETEST
# ============================================================

def breakout_retest_analysis(
    closes,
    highs
):

    result = {

        "resistance": 0.0,
        "breakout": False,
        "retest": False,
        "extension": 0.0,
        "breakout_price": 0.0

    }

    if len(closes) < 35:
        return result

    # --------------------------------------------------------
    # Ana direnç
    # Son 20 kapanmış mumun en yüksek değeri
    # --------------------------------------------------------

    resistance = max(
        highs[-21:-1]
    )

    price = closes[-1]

    result["resistance"] = resistance

    if resistance <= 0:
        return result

    # --------------------------------------------------------
    # Mevcut breakout
    # --------------------------------------------------------

    previous_close = closes[-2]

    if (
        price > resistance
        and previous_close <= resistance
    ):

        result["breakout"] = True

        result["breakout_price"] = resistance

    # --------------------------------------------------------
    # Son 8 mum içerisinde breakout ara
    # --------------------------------------------------------

    recent_breakout_level = None

    start = max(
        21,
        len(closes) - RETEST_LOOKBACK - 1
    )

    for i in range(
        start,
        len(closes) - 1
    ):

        left_start = max(
            0,
            i - 20
        )

        if i <= left_start:
            continue

        local_resistance = max(
            highs[left_start:i]
        )

        if (
            closes[i]
            > local_resistance
        ):

            if i > 0:

                if (
                    closes[i - 1]
                    <= local_resistance
                ):

                    recent_breakout_level = (
                        local_resistance
                    )

    # --------------------------------------------------------
    # Retest
    # --------------------------------------------------------

    if recent_breakout_level:

        distance = (
            abs(
                price
                - recent_breakout_level
            )
            / recent_breakout_level
        ) * 100

        if (
            distance
            <= RETEST_MAX_DISTANCE
            and price
            >= recent_breakout_level * 0.995
        ):

            result["retest"] = True

            result["breakout_price"] = (
                recent_breakout_level
            )

    # --------------------------------------------------------
    # Breakout extension
    # --------------------------------------------------------

    level = (
        result["breakout_price"]
        if result["breakout_price"] > 0
        else resistance
    )

    result["extension"] = (
        (
            price
            - level
        )
        / level
    ) * 100

    return result


# ============================================================
# BTC
# ============================================================

def get_btc_direction():

    data15 = get_klines(
        "BTC_USDT",
        "Min15",
        100
    )

    data1h = get_klines(
        "BTC_USDT",
        "Min60",
        100
    )

    data4h = get_klines(
        "BTC_USDT",
        "Hour4",
        100
    )

    if (
        not data15
        or not data1h
        or not data4h
    ):

        return (
            "NEUTRAL",
            0,
            0,
            0
        )

    c15 = data15["close"][:-1]
    c1h = data1h["close"][:-1]
    c4h = data4h["close"][:-1]

    p15 = pct_change(
        c15,
        4
    )

    p1h = pct_change(
        c1h,
        4
    )

    p4h = pct_change(
        c4h,
        3
    )

    long_score = 0
    short_score = 0

    if p15 > 0:
        long_score += 1
    else:
        short_score += 1

    if p1h > 0:
        long_score += 1
    else:
        short_score += 1

    if p4h > 0:
        long_score += 1
    else:
        short_score += 1

    if long_score >= 2:

        direction = "BULLISH"

    elif short_score >= 2:

        direction = "BEARISH"

    else:

        direction = "NEUTRAL"

    return (
        direction,
        p15,
        p1h,
        p4h
    )


# ============================================================
# MODEL BELİRLEME
# ============================================================

def determine_model(
    pre_score,
    breakout,
    retest
):

    if retest:
        return "🔵 RETEST"

    if breakout:
        return "🟢 BREAKOUT"

    if pre_score >= 72:
        return "🟡 PUMP ÖNCESİ"

    return "🟡 PUMP ÖNCESİ"


# ============================================================
# COIN ANALİZ
# ============================================================

def analyze_coin(
    symbol,
    btc_direction
):

    try:

        if is_stock_symbol(symbol):
            return None

        # ----------------------------------------------------
        # KLINE
        # ----------------------------------------------------

        data15 = get_klines(
            symbol,
            "Min15",
            120
        )

        data1h = get_klines(
            symbol,
            "Min60",
            120
        )

        data4h = get_klines(
            symbol,
            "Hour4",
            120
        )

        if (
            not data15
            or not data1h
            or not data4h
        ):

            return None

        # ----------------------------------------------------
        # SON KAPANMIŞ MUM
        # ----------------------------------------------------

        c15 = data15["close"][:-1]
        o15 = data15["open"][:-1]
        h15 = data15["high"][:-1]
        v15 = data15["volume"][:-1]

        c1h = data1h["close"][:-1]

        c4h = data4h["close"][:-1]

        if (
            len(c15) < 40
            or len(c1h) < 40
            or len(c4h) < 60
        ):

            return None

        # Güncel fiyat
        price = data15["close"][-1]

        # ----------------------------------------------------
        # RSI
        # ----------------------------------------------------

        rsi15 = calculate_rsi(c15)

        rsi1h = calculate_rsi(c1h)

        rsi4h = calculate_rsi(c4h)

        # ----------------------------------------------------
        # RSI YÖNÜ
        # ----------------------------------------------------

        rsi15_dir, rsi15_delta = (
            rsi_direction(c15)
        )

        rsi1h_dir, rsi1h_delta = (
            rsi_direction(c1h)
        )

        rsi4h_dir, rsi4h_delta = (
            rsi_direction(c4h)
        )

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------

        change15 = pct_change(
            c15,
            4
        )

        change1h = pct_change(
            c1h,
            4
        )

        change4h = pct_change(
            c4h,
            3
        )

        # ----------------------------------------------------
        # HACİM
        # ----------------------------------------------------

        volume = volume_ratio(
            v15
        )

        volume_dir, buy_percent = (
            volume_direction(
                o15,
                c15,
                v15
            )
        )

        # ----------------------------------------------------
        # TREND
        # ----------------------------------------------------

        trend = get_trend(c4h)

        ema20 = trend["ema20"]

        ema50 = trend["ema50"]

        # ----------------------------------------------------
        # BREAKOUT / RETEST
        # ----------------------------------------------------

        br = breakout_retest_analysis(
            c15,
            h15
        )

        resistance = br["resistance"]

        breakout = br["breakout"]

        retest = br["retest"]

        extension = br["extension"]

        # ====================================================
        # HARD FİLTRELER
        # ====================================================

        if volume < MIN_VOLUME:
            return None

        if rsi4h < MIN_RSI_4H:
            return None

        if rsi15 > MAX_RSI_15:
            return None

        if rsi1h > MAX_RSI_1H:
            return None

        # BTC bearish = LONG yok
        if btc_direction == "BEARISH":
            return None

        # Aşırı breakout
        if extension > BREAKOUT_MAX_EXTENSION:
            return None

        # ====================================================
        # STRK TİPİ DURUMU ENGELLE
        #
        # Aşırı hacim + satış baskısı
        # ====================================================

        if (
            volume >= 5
            and volume_dir == "SELL"
        ):

            return None

        # ====================================================
        # RSI TAMAMEN DÜŞÜYORSA
        # ====================================================

        if (
            rsi15_dir == "DOWN"
            and rsi1h_dir == "DOWN"
        ):

            return None

        # ====================================================
        # SKOR
        # ====================================================

        score = 0

        # ----------------------------------------------------
        # 4H RSI
        # ----------------------------------------------------

        if 47 <= rsi4h <= 55:

            score += 14

        elif 55 < rsi4h <= 62:

            score += 11

        elif 62 < rsi4h <= 68:

            score += 6

        # ----------------------------------------------------
        # 4H RSI YÖNÜ
        # ----------------------------------------------------

        if rsi4h_dir == "UP":

            score += 7

        elif rsi4h_dir == "DOWN":

            score -= 4

        # ----------------------------------------------------
        # 1H RSI
        # ----------------------------------------------------

        if 50 <= rsi1h <= 65:

            score += 9

        elif 65 < rsi1h <= 70:

            score += 4

        # ----------------------------------------------------
        # 1H RSI YÖNÜ
        # ----------------------------------------------------

        if rsi1h_dir == "UP":

            score += 8

        elif rsi1h_dir == "DOWN":

            score -= 4

        # ----------------------------------------------------
        # 15M RSI
        # ----------------------------------------------------

        if 50 <= rsi15 <= 67:

            score += 7

        elif 67 < rsi15 <= 72:

            score += 3

        # ----------------------------------------------------
        # 15M RSI YÖNÜ
        # ----------------------------------------------------

        if rsi15_dir == "UP":

            score += 8

        elif rsi15_dir == "DOWN":

            score -= 5

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------

        if change15 > 0:

            score += 5

        if change1h > 0:

            score += 5

        # Çok küçük negatif momentum
        # dönüş aşamasında tolere edilebilir.

        if (
            -1.0
            <= change4h
            <= 5.0
        ):

            score += 5

        # ----------------------------------------------------
        # 4H TREND
        # ----------------------------------------------------

        if trend["trend"] == "BULLISH":

            score += 10

        elif trend["trend"] == "RECOVERY":

            score += 7

        elif trend["trend"] == "BEARISH":

            score += 0

        # ----------------------------------------------------
        # FİYAT EMA20
        # ----------------------------------------------------

        if price >= ema20:

            score += 5

        elif price >= ema20 * 0.985:

            score += 3

        # ----------------------------------------------------
        # HACİM
        #
        # Artık 30x hacim ekstra puan almıyor.
        # ----------------------------------------------------

        if (
            2.90
            <= volume
            < 5
        ):

            score += 6

        elif (
            5
            <= volume
            < 10
        ):

            score += 8

        elif (
            10
            <= volume
            < 20
        ):

            score += 5

        elif volume >= 20:

            score += 2

        # ----------------------------------------------------
        # HACİM YÖNÜ
        # ----------------------------------------------------

        if volume_dir == "BUY":

            score += 8

        elif volume_dir == "NEUTRAL":

            score += 2

        elif volume_dir == "SELL":

            score -= 8

        # ----------------------------------------------------
        # ALIŞ BASKISI
        # ----------------------------------------------------

        if buy_percent >= 70:

            score += 5

        elif buy_percent >= 60:

            score += 3

        # ----------------------------------------------------
        # BTC
        # ----------------------------------------------------

        if btc_direction == "BULLISH":

            score += 5

        elif btc_direction == "NEUTRAL":

            score += 1

        # ====================================================
        # PUMP ÖNCESİ MODEL
        # ====================================================

        pre_score = score

        pre_conditions = 0

        if (
            49
            <= rsi4h
            <= 60
        ):

            pre_conditions += 1

        if (
            rsi4h_dir
            == "UP"
        ):

            pre_conditions += 1

        if (
            rsi1h_dir
            == "UP"
        ):

            pre_conditions += 1

        if (
            rsi15_dir
            == "UP"
        ):

            pre_conditions += 1

        if (
            PRE_MIN_VOLUME
            <= volume
            <= PRE_MAX_VOLUME
        ):

            pre_conditions += 1

        if volume_dir == "BUY":

            pre_conditions += 1

        if (
            change15
            > 0
        ):

            pre_conditions += 1

        if (
            change15
            <= PRE_MAX_15M_CHANGE
        ):

            pre_conditions += 1

        if (
            change1h
            <= PRE_MAX_1H_CHANGE
        ):

            pre_conditions += 1

        if (
            change4h
            <= PRE_MAX_4H_CHANGE
        ):

            pre_conditions += 1

        # En az 6 şart
        # pump öncesi adayı
        pre_model = (
            pre_conditions >= 6
        )

        # ====================================================
        # BREAKOUT MODELİ
        # ====================================================

        breakout_score = score

        if breakout:

            breakout_score += 8

        else:

            breakout_score -= 3

        if volume >= BREAKOUT_MIN_VOLUME:

            breakout_score += 3

        if volume_dir == "BUY":

            breakout_score += 3

        if change15 > 0:

            breakout_score += 2

        # ====================================================
        # RETEST MODELİ
        # ====================================================

        retest_score = score

        if retest:

            retest_score += 10

        else:

            retest_score -= 3

        if volume_dir == "BUY":

            retest_score += 3

        if rsi15_dir == "UP":

            retest_score += 2

        # ====================================================
        # EN İYİ MODELİ SEÇ
        # ====================================================

        candidates = []

        if pre_model:

            candidates.append(
                (
                    pre_score,
                    "🟡 PUMP ÖNCESİ"
                )
            )

        if breakout:

            candidates.append(
                (
                    breakout_score,
                    "🟢 BREAKOUT"
                )
            )

        if retest:

            candidates.append(
                (
                    retest_score,
                    "🔵 RETEST"
                )
            )

        if not candidates:

            return None

        candidates.sort(
            key=lambda x: x[0],
            reverse=True
        )

        final_score, model = (
            candidates[0]
        )

        # ====================================================
        # SKOR NORMALİZASYON
        # ====================================================

        final_score = int(
            max(
                0,
                min(
                    final_score,
                    100
                )
            )
        )

        # ====================================================
        # MINIMUM SCORE
        # ====================================================

        if final_score < MIN_SCORE:

            return None

        # ====================================================
        # SON GÜVENLİK
        # ====================================================

        # Çok yüksek RSI
        if rsi15 >= 74:
            return None

        if rsi1h >= 72:
            return None

        # Momentum tamamen bozulmuşsa
        if (
            change15 < -3
            and rsi15_dir == "DOWN"
        ):

            return None

        # Yüksek hacim + satış
        if (
            volume >= 5
            and volume_dir == "SELL"
        ):

            return None

        # ====================================================
        # SKOR → 10'LUK SİSTEM
        # ====================================================

        if final_score >= 90:

            strength = 10

        elif final_score >= 80:

            strength = 9

        else:

            strength = 8

        # ====================================================
        # ENTRY / STOP / TP
        # ====================================================

        entry = price

        # Model bazlı stop
        if retest:

            stop_percent = 0.020

        elif breakout:

            stop_percent = 0.022

        else:

            stop_percent = 0.024

        stop = (
            entry
            * (1 - stop_percent)
        )

        tp1 = (
            entry
            * 1.022
        )

        tp2 = (
            entry
            * 1.045
        )

        tp3 = (
            entry
            * 1.070
        )

        # ====================================================
        # SONUÇ
        # ====================================================

        return {

            "symbol":
                symbol.replace(
                    "_USDT",
                    "/USDT"
                ),

            "direction":
                "LONG",

            "score":
                final_score,

            "strength":
                strength,

            "model":
                model,

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

            "rsi15_dir":
                rsi15_dir,

            "rsi1h_dir":
                rsi1h_dir,

            "rsi4h_dir":
                rsi4h_dir,

            "volume":
                volume,

            "volume_dir":
                volume_dir,

            "buy_percent":
                buy_percent,

            "change15":
                change15,

            "change1h":
                change1h,

            "change4h":
                change4h,

            "ema20":
                ema20,

            "ema50":
                ema50,

            "trend":
                trend["trend"],

            "breakout":
                breakout,

            "retest":
                retest,

            "resistance":
                resistance,

            "extension":
                extension,

            "btc":
                btc_direction

        }

    except Exception:

        return None


# ============================================================
# FİYAT FORMAT
# ============================================================

def fmt_price(price):

    if price >= 1000:

        return f"{price:.2f}"

    if price >= 100:

        return f"{price:.3f}"

    if price >= 10:

        return f"{price:.4f}"

    if price >= 1:

        return f"{price:.5f}"

    if price >= 0.1:

        return f"{price:.6f}"

    if price >= 0.01:

        return f"{price:.7f}"

    if price >= 0.001:

        return f"{price:.8f}"

    return f"{price:.10f}"


# ============================================================
# TELEGRAM
# ============================================================

def create_message(signal):

    message = f"""
🟢 LONG SİNYAL
━━━━━━━━━━━━━━━━

{signal["model"]}

💎 {signal["symbol"]}

⭐ Güç: {signal["strength"]}/10
📊 Kalite skoru: {signal["score"]}/100

🎯 Giriş: {fmt_price(signal["entry"])}
🛑 Stop: {fmt_price(signal["stop"])}

💰 TP1: {fmt_price(signal["tp1"])}
💰 TP2: {fmt_price(signal["tp2"])}
💰 TP3: {fmt_price(signal["tp3"])}

━━━━━━━━━━━━━━━━

📊 RSI 15M:
{signal["rsi15"]:.1f} {signal["rsi15_dir"]}

📊 RSI 1H:
{signal["rsi1h"]:.1f} {signal["rsi1h_dir"]}

📊 RSI 4H:
{signal["rsi4h"]:.1f} {signal["rsi4h_dir"]}

🔥 Hacim:
{signal["volume"]:.1f}x

📈 Hacim yönü:
{signal["volume_dir"]}

🟢 Alış baskısı:
{signal["buy_percent"]:.0f}%

━━━━━━━━━━━━━━━━

📈 4H Trend:
{signal["trend"]}

📈 EMA20:
{fmt_price(signal["ema20"])}

📉 EMA50:
{fmt_price(signal["ema50"])}

🚀 Breakout:
{"EVET" if signal["breakout"] else "HAYIR"}

🔄 Retest:
{"EVET" if signal["retest"] else "HAYIR"}

🎯 Direnç:
{fmt_price(signal["resistance"])}

📏 Breakout uzaması:
{signal["extension"]:.2f}%

━━━━━━━━━━━━━━━━

📈 15M değişim:
{signal["change15"]:+.2f}%

📈 1H değişim:
{signal["change1h"]:+.2f}%

📈 4H değişim:
{signal["change4h"]:+.2f}%

🌐 BTC:
{signal["btc"]}

━━━━━━━━━━━━━━━━
⚠️ Sinyal otomatik teknik taramadır.
"""

    return message.strip()


# ============================================================
# ANA RADAR
# ============================================================

def main():

    print()

    print(
        "🚀 MEXC PUMP RADAR 19.0"
    )

    print(
        "🧠 PUMP ÖNCESİ + BREAKOUT + RETEST"
    )

    print(
        "📈 RSI YÖNÜ AKTİF"
    )

    print(
        "🔥 HACİM YÖNÜ AKTİF"
    )

    print(
        "🧭 4H EMA TREND AKTİF"
    )

    print(
        "🚀 BREAKOUT AKTİF"
    )

    print(
        "🔄 RETEST AKTİF"
    )

    print(
        "🪤 FAKE / AŞIRI HAREKET FİLTRESİ AKTİF"
    )

    print()

    print(
        "🚫 STOCK FİLTRESİ AKTİF"
    )

    print(
        "🚫 SPOT FİLTRESİ AKTİF"
    )

    print(
        "🚫 TOKENIZED STOCK FİLTRESİ AKTİF"
    )

    print()

    print(
        f"🔥 Minimum hacim: "
        f"{MIN_VOLUME:.2f}x"
    )

    print(
        f"📊 Minimum RSI 4H: "
        f"{MIN_RSI_4H:.1f}"
    )

    print(
        f"⭐ Minimum kalite: "
        f"{MIN_SCORE}/100"
    )

    print(
        f"📨 Maksimum Telegram: "
        f"{MAX_TELEGRAM_SIGNALS}"
    )

    print()

    # ========================================================
    # BTC
    # ========================================================

    print(
        "🌐 BTC yönü analiz ediliyor..."
    )

    (
        btc_direction,
        btc15,
        btc1h,
        btc4h
    ) = get_btc_direction()

    print(
        "=" * 55
    )

    print(
        f"🌐 BTC YÖNÜ: "
        f"{btc_direction}"
    )

    print(
        f"15M: {btc15:+.2f}%"
    )

    print(
        f"1H: {btc1h:+.2f}%"
    )

    print(
        f"4H: {btc4h:+.2f}%"
    )

    print(
        "=" * 55
    )

    # ========================================================
    # FUTURES
    # ========================================================

    symbols = get_futures_symbols()

    print(
        f"📊 Futures kontrat: "
        f"{len(symbols)}"
    )

    symbols = [
        s
        for s in symbols
        if (
            s.endswith("_USDT")
            and not is_stock_symbol(s)
        )
    ]

    print(
        f"🧹 Stock sonrası: "
        f"{len(symbols)}"
    )

    print(
        f"🔎 Taranacak: "
        f"{len(symbols)}"
    )

    # ========================================================
    # HISTORY
    # ========================================================

    history = load_history()

    signals = []

    completed = 0

    # ========================================================
    # TARAMA
    # ========================================================

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {

            executor.submit(
                analyze_coin,
                symbol,
                btc_direction
            ): symbol

            for symbol in symbols

        }

        for future in as_completed(
            futures
        ):

            completed += 1

            if (
                completed % 25 == 0
                or completed
                == len(symbols)
            ):

                print(
                    f"İlerleme: "
                    f"{completed}/"
                    f"{len(symbols)}"
                )

            try:

                result = (
                    future.result()
                )

                if result:

                    signals.append(
                        result
                    )

            except Exception:

                pass

    # ========================================================
    # SIRALAMA
    # ========================================================

    signals.sort(
        key=lambda x:
        (
            x["score"],
            x["buy_percent"],
            x["volume"]
        ),
        reverse=True
    )

    print()

    print(
        f"🎯 Güçlü aday: "
        f"{len(signals)}"
    )

    # ========================================================
    # MODEL İSTATİSTİK
    # ========================================================

    pre_count = sum(
        1
        for x in signals
        if x["model"]
        == "🟡 PUMP ÖNCESİ"
    )

    breakout_count = sum(
        1
        for x in signals
        if x["model"]
        == "🟢 BREAKOUT"
    )

    retest_count = sum(
        1
        for x in signals
        if x["model"]
        == "🔵 RETEST"
    )

    print(
        f"🟡 Pump öncesi: "
        f"{pre_count}"
    )

    print(
        f"🟢 Breakout: "
        f"{breakout_count}"
    )

    print(
        f"🔵 Retest: "
        f"{retest_count}"
    )

    print()

    # ========================================================
    # BULUNANLAR
    # ========================================================

    for signal in signals:

        print(
            f"{signal['model']} "
            f"{signal['symbol']} "
            f"{signal['strength']}/10 "
            f"Skor:{signal['score']} "
            f"RSI15:{signal['rsi15']:.1f} "
            f"RSI1H:{signal['rsi1h']:.1f} "
            f"RSI4H:{signal['rsi4h']:.1f} "
            f"Hacim:{signal['volume']:.1f}x "
            f"HacimYön:{signal['volume_dir']} "
            f"Alış:{signal['buy_percent']:.0f}%"
        )

    # ========================================================
    # TELEGRAM
    # ========================================================

    sent = 0

    now = time.time()

    # Aynı coin için tekrar
    # aynı taramada gönderme
    sent_symbols = set()

    for signal in signals:

        if sent >= MAX_TELEGRAM_SIGNALS:

            break

        symbol = signal["symbol"]

        # ----------------------------------------------------
        # Aynı coin
        # ----------------------------------------------------

        if symbol in sent_symbols:

            continue

        # ----------------------------------------------------
        # HISTORY
        # ----------------------------------------------------

        key = (
            f"{symbol}_"
            f"LONG"
        )

        last_time = history.get(
            key,
            0
        )

        if (
            now - last_time
            < COOLDOWN_HOURS * 3600
        ):

            print(
                f"⏳ Atlandı: "
                f"{symbol} "
                f"(cooldown)"
            )

            continue

        # ----------------------------------------------------
        # SON GÜVENLİK
        # ----------------------------------------------------

        if signal["score"] < MIN_SCORE:

            continue

        if signal["volume"] < MIN_VOLUME:

            continue

        if signal["rsi4h"] < MIN_RSI_4H:

            continue

        if signal["btc"] == "BEARISH":

            continue

        if signal["volume_dir"] == "SELL":

            continue

        if signal["rsi15"] >= MAX_RSI_15:

            continue

        # ----------------------------------------------------
        # TELEGRAM
        # ----------------------------------------------------

        message = create_message(
            signal
        )

        if telegram_send(message):

            history[key] = now

            sent_symbols.add(
                symbol
            )

            sent += 1

            print(
                f"📨 Telegram: "
                f"{signal['model']} "
                f"{symbol} "
                f"{signal['strength']}/10 "
                f"Skor:{signal['score']} "
                f"Hacim:{signal['volume']:.1f}x"
            )

        time.sleep(0.4)

    # ========================================================
    # HISTORY
    # ========================================================

    save_history(history)

    print()

    print(
        f"📨 Telegram gönderilen: "
        f"{sent}"
    )

    print(
        "🏁 Tarama tamamlandı."
    )

    print()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
