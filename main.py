import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PUMP RADAR 18.0
#
# AMAÇ:
# PUMP BAŞLADIKTAN SONRA KOŞMAK DEĞİL
# PUMP ÖNCESİ / BREAKOUT + RETEST YAPISINI BULMAK
#
# SADECE:
# ✅ MEXC USDT FUTURES
# ✅ 15M + 1H + 4H
# ✅ RSI
# ✅ RSI YÖNÜ
# ✅ HACİM
# ✅ HACİM YÖNÜ
# ✅ MOMENTUM
# ✅ EMA TREND
# ✅ BREAKOUT
# ✅ RETEST
# ✅ DİRENÇ FİLTRESİ
# ✅ BTC YÖN FİLTRESİ
#
# ENGELLER:
# ❌ STOCK
# ❌ TOKENIZED STOCK
# ❌ SPOT
# ❌ BTC TERS YÖN
# ❌ AŞIRI ŞİŞMİŞ COIN
# ❌ FAKE BREAKOUT
# ❌ YÜKSEK SATIŞ HACMİ
# ❌ DİRENCE ÇOK YAKIN GİRİŞ
#
# ============================================================


BASE = "https://contract.mexc.com"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HISTORY_FILE = "signal_history.json"

MAX_WORKERS = 12


# ============================================================
# ANA FİLTRELER
# ============================================================

MIN_SCORE = 8

# Minimum hacim
MIN_VOLUME = 2.90

# 4H RSI minimum
MIN_RSI_4H = 49.0

# RSI aşırı şişme
MAX_RSI_15_LONG = 75.0
MAX_RSI_1H_LONG = 75.0

# Çok uzamış hareketleri engelle
MAX_CHANGE_15_LONG = 6.0
MAX_CHANGE_1H_LONG = 8.0
MAX_CHANGE_4H_LONG = 12.0

# Dirence maksimum uzaklık
MAX_RESISTANCE_DISTANCE = 4.0

# Breakout'un üzerinde fazla koşmuşsa
MAX_BREAKOUT_EXTENSION = 5.0

# Cooldown
COOLDOWN_HOURS = 6


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
    limit=100
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
        volumes = d.get("vol", [])
        highs = d.get("high", [])
        lows = d.get("low", [])
        opens = d.get("open", [])

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

    multiplier = 2 / (
        period + 1
    )

    ema = sum(
        values[:period]
    ) / period

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
#
# ARTIK SADECE HACMİN BÜYÜKLÜĞÜNE DEĞİL
# HACMİN HANGİ YÖNDE GELDİĞİNE BAKIYORUZ.
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
# Son yüksek hacimli mumlar:
#
# 🟢 Yukarı kapanış = BUY PRESSURE
# 🔴 Aşağı kapanış = SELL PRESSURE
#
# ============================================================

def volume_direction(
    opens,
    closes,
    volumes
):

    if len(closes) < 5:
        return "NEUTRAL", 0.0

    avg = (
        sum(volumes[-21:-1])
        / 20
    )

    if avg <= 0:
        return "NEUTRAL", 0.0

    buy_score = 0.0
    sell_score = 0.0

    recent_start = len(closes) - 3

    for i in range(
        recent_start,
        len(closes)
    ):

        vol_ratio = (
            volumes[i]
            / avg
        )

        body = (
            closes[i]
            - opens[i]
        )

        if body > 0:

            buy_score += max(
                vol_ratio,
                0
            )

        elif body < 0:

            sell_score += max(
                vol_ratio,
                0
            )

    total = (
        buy_score
        + sell_score
    )

    if total <= 0:
        return "NEUTRAL", 0.0

    buy_percent = (
        buy_score
        / total
    ) * 100

    if buy_percent >= 60:

        return (
            "BUY",
            buy_percent
        )

    if buy_percent <= 40:

        return (
            "SELL",
            buy_percent
        )

    return (
        "NEUTRAL",
        buy_percent
    )


# ============================================================
# RSI YÖNÜ
# ============================================================

def rsi_direction(closes):

    if len(closes) < 25:

        return (
            "NEUTRAL",
            0
        )

    current = calculate_rsi(
        closes
    )

    previous = calculate_rsi(
        closes[:-1]
    )

    delta = (
        current
        - previous
    )

    if delta >= 1.0:

        return (
            "UP",
            delta
        )

    if delta <= -1.0:

        return (
            "DOWN",
            delta
        )

    return (
        "FLAT",
        delta
    )


# ============================================================
# BREAKOUT / DİRENÇ
# ============================================================

def resistance_analysis(
    closes,
    highs
):

    if len(highs) < 25:

        return {

            "resistance": 0,
            "distance": 0,
            "breakout": False,
            "retest": False,
            "extension": 0

        }

    # Son 20 mumun yüksekliği
    resistance = max(
        highs[-21:-1]
    )

    price = closes[-1]

    if resistance <= 0:

        return {

            "resistance": 0,
            "distance": 0,
            "breakout": False,
            "retest": False,
            "extension": 0

        }

    distance = (
        (
            resistance
            - price
        )
        / resistance
    ) * 100

    # Son mum breakout yapmış mı?
    previous_close = closes[-2]

    breakout = (
        price > resistance
        and previous_close <= resistance
    )

    # Son birkaç mum içinde breakout olmuş mu?
    recent_breakout = False

    for i in range(
        max(1, len(closes) - 5),
        len(closes)
    ):

        previous_resistance = max(
            highs[
                max(0, i - 21):i
            ]
        )

        if (
            closes[i]
            > previous_resistance
        ):

            recent_breakout = True
            break

    # Resistance üstünde ne kadar uzamış?
    extension = (
        (
            price
            - resistance
        )
        / resistance
    ) * 100

    # Retest:
    # Fiyat breakout seviyesine yaklaşmış
    # ama tekrar altında kapanmamış.
    retest = False

    if recent_breakout:

        lower_distance = abs(
            price - resistance
        ) / resistance * 100

        if (
            lower_distance <= 2.5
            and price >= resistance * 0.995
        ):

            retest = True

    return {

        "resistance":
            resistance,

        "distance":
            distance,

        "breakout":
            breakout
            or recent_breakout,

        "retest":
            retest,

        "extension":
            extension

    }


# ============================================================
# 4H TREND
# ============================================================

def trend_analysis(closes):

    if len(closes) < 60:

        return {

            "ema20": closes[-1],
            "ema50": closes[-1],
            "bullish": False,
            "slope": 0

        }

    ema20 = calculate_ema(
        closes,
        20
    )

    ema50 = calculate_ema(
        closes,
        50
    )

    previous_ema20 = calculate_ema(
        closes[:-3],
        20
    )

    slope = (
        (
            ema20
            - previous_ema20
        )
        / previous_ema20
    ) * 100

    bullish = (
        ema20 >= ema50
        and slope >= 0
    )

    return {

        "ema20":
            ema20,

        "ema50":
            ema50,

        "bullish":
            bullish,

        "slope":
            slope

    }


# ============================================================
# BTC YÖNÜ
# ============================================================

def get_btc_direction():

    data15 = get_klines(
        "BTC_USDT",
        "Min15",
        80
    )

    data1h = get_klines(
        "BTC_USDT",
        "Min60",
        80
    )

    data4h = get_klines(
        "BTC_USDT",
        "Hour4",
        80
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

    c15 = data15["close"]
    c1h = data1h["close"]
    c4h = data4h["close"]

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

    score_long = 0
    score_short = 0

    if p15 > 0:
        score_long += 1
    else:
        score_short += 1

    if p1h > 0:
        score_long += 1
    else:
        score_short += 1

    if p4h > 0:
        score_long += 1
    else:
        score_short += 1

    if score_long >= 2:

        direction = "BULLISH"

    elif score_short >= 2:

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
# COIN ANALİZİ
# ============================================================

def analyze_coin(
    symbol,
    btc_direction
):

    try:

        # ----------------------------------------------------
        # STOCK
        # ----------------------------------------------------

        if is_stock_symbol(symbol):
            return None

        # ----------------------------------------------------
        # KLINE
        # ----------------------------------------------------

        data15 = get_klines(
            symbol,
            "Min15",
            100
        )

        data1h = get_klines(
            symbol,
            "Min60",
            100
        )

        data4h = get_klines(
            symbol,
            "Hour4",
            100
        )

        if (
            not data15
            or not data1h
            or not data4h
        ):

            return None

        c15 = data15["close"]
        o15 = data15["open"]
        h15 = data15["high"]
        v15 = data15["volume"]

        c1h = data1h["close"]

        c4h = data4h["close"]
        h4h = data4h["high"]

        # ----------------------------------------------------
        # SON KAPANMIŞ MUMU KULLAN
        #
        # Son mum hâlâ oluşuyorsa sinyalin değişmesini
        # azaltmak için göstergelerde bir önceki mumu baz al.
        # ----------------------------------------------------

        c15_closed = c15[:-1]
        o15_closed = o15[:-1]
        h15_closed = h15[:-1]
        v15_closed = v15[:-1]

        c1h_closed = c1h[:-1]

        c4h_closed = c4h[:-1]
        h4h_closed = h4h[:-1]

        if len(c15_closed) < 30:
            return None

        if len(c1h_closed) < 30:
            return None

        if len(c4h_closed) < 60:
            return None

        # ----------------------------------------------------
        # GÜNCEL FİYAT
        # ----------------------------------------------------

        price = c15[-1]

        # ----------------------------------------------------
        # RSI
        # ----------------------------------------------------

        rsi15 = calculate_rsi(
            c15_closed
        )

        rsi1h = calculate_rsi(
            c1h_closed
        )

        rsi4h = calculate_rsi(
            c4h_closed
        )

        # ----------------------------------------------------
        # RSI YÖNÜ
        # ----------------------------------------------------

        rsi15_dir, rsi15_delta = (
            rsi_direction(
                c15_closed
            )
        )

        rsi1h_dir, rsi1h_delta = (
            rsi_direction(
                c1h_closed
            )
        )

        rsi4h_dir, rsi4h_delta = (
            rsi_direction(
                c4h_closed
            )
        )

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------

        change15 = pct_change(
            c15_closed,
            4
        )

        change1h = pct_change(
            c1h_closed,
            4
        )

        change4h = pct_change(
            c4h_closed,
            3
        )

        # ----------------------------------------------------
        # HACİM
        # ----------------------------------------------------

        vol = volume_ratio(
            v15_closed
        )

        volume_dir, buy_percent = (
            volume_direction(
                o15_closed,
                c15_closed,
                v15_closed
            )
        )

        # ====================================================
        # HARD HACİM FİLTRESİ
        # ====================================================

        if vol < MIN_VOLUME:

            return None

        # ====================================================
        # HARD RSI 4H
        # ====================================================

        if rsi4h < MIN_RSI_4H:

            return None

        # ====================================================
        # BTC FİLTRESİ
        #
        # LONG RADARDA BTC bearish ise işlem yok.
        # ====================================================

        if btc_direction == "BEARISH":

            return None

        # ====================================================
        # AŞIRI ŞİŞME HARD FİLTRELERİ
        # ====================================================

        if rsi15 > MAX_RSI_15_LONG:

            return None

        if rsi1h > MAX_RSI_1H_LONG:

            return None

        if change15 > MAX_CHANGE_15_LONG:

            return None

        if change1h > MAX_CHANGE_1H_LONG:

            return None

        if change4h > MAX_CHANGE_4H_LONG:

            return None

        # ====================================================
        # TREND
        # ====================================================

        trend = trend_analysis(
            c4h_closed
        )

        ema20 = trend["ema20"]
        ema50 = trend["ema50"]

        trend_bullish = (
            trend["bullish"]
        )

        # ====================================================
        # DİRENÇ / BREAKOUT
        # ====================================================

        resistance = resistance_analysis(
            c4h_closed,
            h4h_closed
        )

        resistance_price = (
            resistance["resistance"]
        )

        resistance_distance = (
            resistance["distance"]
        )

        breakout = (
            resistance["breakout"]
        )

        retest = (
            resistance["retest"]
        )

        extension = (
            resistance["extension"]
        )

        # ====================================================
        # BREAKOUT'UN ÇOK ÜSTÜNE KOŞMUŞSA
        # ====================================================

        if extension > MAX_BREAKOUT_EXTENSION:

            return None

        # ====================================================
        # LONG SCORE
        # ====================================================

        long_score = 0

        # ----------------------------------------------------
        # 4H RSI
        #
        # 49-55 = dipten dönüş için iyi
        # 55-65 = trend güçlü
        # 65+ = dikkat
        # ----------------------------------------------------

        if 49 <= rsi4h <= 55:

            long_score += 2

        elif 55 < rsi4h <= 65:

            long_score += 1

        # ----------------------------------------------------
        # 4H RSI YÖNÜ
        # ----------------------------------------------------

        if rsi4h_dir == "UP":

            long_score += 1

        elif rsi4h_dir == "DOWN":

            long_score -= 1

        # ----------------------------------------------------
        # 1H RSI
        # ----------------------------------------------------

        if 50 <= rsi1h <= 68:

            long_score += 1

        if rsi1h_dir == "UP":

            long_score += 1

        elif rsi1h_dir == "DOWN":

            long_score -= 1

        # ----------------------------------------------------
        # 15M RSI
        # ----------------------------------------------------

        if 50 <= rsi15 <= 68:

            long_score += 1

        if rsi15_dir == "UP":

            long_score += 1

        elif rsi15_dir == "DOWN":

            long_score -= 1

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------

        if change15 > 0:

            long_score += 1

        if change1h > 0:

            long_score += 1

        # ----------------------------------------------------
        # 4H TREND
        # ----------------------------------------------------

        if trend_bullish:

            long_score += 2

        # Fiyat EMA20'ye yakınsa
        # erken trend dönüşü olabilir.

        if price >= ema20 * 0.985:

            long_score += 1

        # ----------------------------------------------------
        # HACİM
        # ----------------------------------------------------

        if vol >= 2.90:

            long_score += 1

        # ----------------------------------------------------
        # HACİMİN YÖNÜ
        # ----------------------------------------------------

        if volume_dir == "BUY":

            long_score += 2

        elif volume_dir == "SELL":

            long_score -= 2

        # ----------------------------------------------------
        # BTC
        # ----------------------------------------------------

        if btc_direction == "BULLISH":

            long_score += 1

        elif btc_direction == "NEUTRAL":

            long_score += 0

        # ----------------------------------------------------
        # BREAKOUT
        # ----------------------------------------------------

        if breakout:

            long_score += 1

        # ----------------------------------------------------
        # RETEST
        # ----------------------------------------------------

        if retest:

            long_score += 2

        # ----------------------------------------------------
        # DİRENÇ MESAFESİ
        # ----------------------------------------------------

        if (
            resistance_price > 0
            and resistance_distance > 0
        ):

            if (
                resistance_distance
                <= MAX_RESISTANCE_DISTANCE
            ):

                # Dirence çok yakınsa
                # yeni LONG riskli.
                long_score -= 1

        # ----------------------------------------------------
        # AŞIRI HACİM CEZASI
        #
        # 30x hacim artık ekstra puan değil.
        # Çünkü STRK'daki ana problem buydu.
        # ----------------------------------------------------

        if vol >= 30:

            long_score -= 1

        elif vol >= 20:

            long_score -= 0

        # ----------------------------------------------------
        # AŞIRI HAREKET CEZASI
        # ----------------------------------------------------

        if change4h > 8:

            long_score -= 1

        if change1h > 6:

            long_score -= 1

        # ====================================================
        # SATIŞ BASKISI HARD ENGEL
        #
        # Yüksek hacim + satış yönü
        # LONG YOK
        # ====================================================

        if (
            volume_dir == "SELL"
            and vol >= 5
        ):

            return None

        # ====================================================
        # RSI DÜŞÜYOR + FİYAT DÜŞÜYOR
        #
        # Momentum bozuluyorsa LONG yok.
        # ====================================================

        if (
            rsi15_dir == "DOWN"
            and rsi1h_dir == "DOWN"
            and change15 < 0
        ):

            return None

        # ====================================================
        # 4H TREND ÇOK ZAYIFSA
        #
        # EMA20 EMA50'nin ciddi altındaysa
        # pump öncesi dönüşü daha fazla bekle.
        # ====================================================

        if (
            ema20 < ema50
            and trend["slope"] < -0.5
        ):

            long_score -= 2

        # ====================================================
        # FAKE BREAKOUT
        #
        # Resistance üzerine çıkıp tekrar aşağı kapandıysa
        # LONG VERME.
        # ====================================================

        if (
            resistance_price > 0
            and price < resistance_price
            and change15 < 0
            and vol >= 5
        ):

            # Eğer fiyat direnç altında,
            # hacim yüksek ve momentum negatifse
            # breakout başarısız olabilir.
            long_score -= 2

        # ====================================================
        # MIN SCORE
        # ====================================================

        if long_score < MIN_SCORE:

            return None

        # ====================================================
        # SON KONTROL
        # ====================================================

        if btc_direction == "BEARISH":

            return None

        if volume_dir == "SELL":

            return None

        # RSI düşüyorsa 10/10 verilmesin
        if rsi15_dir == "DOWN":

            long_score = min(
                long_score,
                8
            )

        # ====================================================
        # DIRECTION
        # ====================================================

        direction = "LONG"

        score = min(
            max(long_score, 0),
            10
        )

        # ====================================================
        # ENTRY / STOP / TP
        # ====================================================

        entry = price

        # Stop
        stop = (
            entry
            * 0.978
        )

        # TP
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
                direction,

            "score":
                score,

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

            "rsi15_delta":
                rsi15_delta,

            "rsi1h_delta":
                rsi1h_delta,

            "rsi4h_delta":
                rsi4h_delta,

            "volume":
                vol,

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
                trend_bullish,

            "breakout":
                breakout,

            "retest":
                retest,

            "resistance":
                resistance_price,

            "resistance_distance":
                resistance_distance,

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
# TELEGRAM MESAJI
# ============================================================

def create_message(signal):

    message = f"""
🟢 LONG SİNYAL
━━━━━━━━━━━━━━━━

💎 {signal["symbol"]}

⭐ Güç: {signal["score"]}/10

🎯 Giriş: {fmt_price(signal["entry"])}
🛑 Stop: {fmt_price(signal["stop"])}

💰 TP1: {fmt_price(signal["tp1"])}
💰 TP2: {fmt_price(signal["tp2"])}
💰 TP3: {fmt_price(signal["tp3"])}

📊 RSI 15M: {signal["rsi15"]:.1f} {signal["rsi15_dir"]}
📊 RSI 1H: {signal["rsi1h"]:.1f} {signal["rsi1h_dir"]}
📊 RSI 4H: {signal["rsi4h"]:.1f} {signal["rsi4h_dir"]}

🔥 Hacim: {signal["volume"]:.1f}x
📈 Hacim yönü: {signal["volume_dir"]}
🟢 Alış baskısı: {signal["buy_percent"]:.0f}%

📈 4H EMA20: {fmt_price(signal["ema20"])}
📉 4H EMA50: {fmt_price(signal["ema50"])}

🚀 Breakout: {"EVET" if signal["breakout"] else "HAYIR"}
🔄 Retest: {"EVET" if signal["retest"] else "HAYIR"}

🎯 Direnç: {fmt_price(signal["resistance"])}
📏 Dirence mesafe: {signal["resistance_distance"]:.2f}%

🌐 BTC: {signal["btc"]}

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
        "🚀 MEXC PUMP RADAR 18.0"
    )

    print(
        "🧠 PUMP ÖNCESİ RADAR AKTİF"
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
        "🚀 BREAKOUT FİLTRESİ AKTİF"
    )

    print(
        "🔄 RETEST FİLTRESİ AKTİF"
    )

    print(
        "🚨 FAKE BREAKOUT FİLTRESİ AKTİF"
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
        f"⭐ Minimum skor: "
        f"{MIN_SCORE}/10"
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
        "=" * 50
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
        "=" * 50
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
    # PARALEL TARAMA
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
    # SKOR SIRALAMA
    # ========================================================

    signals.sort(
        key=lambda x:
        (
            x["score"],
            x["volume"],
            x["buy_percent"]
        ),
        reverse=True
    )

    print()

    print(
        f"🎯 Güçlü sinyal: "
        f"{len(signals)}"
    )

    # ========================================================
    # SİNYALLER
    # ========================================================

    for signal in signals:

        print(
            f"🔥 {signal['symbol']} "
            f"{signal['direction']} "
            f"{signal['score']}/10 "
            f"RSI4H: "
            f"{signal['rsi4h']:.1f} "
            f"RSI15: "
            f"{signal['rsi15']:.1f} "
            f"Hacim: "
            f"{signal['volume']:.1f}x "
            f"Hacim yönü: "
            f"{signal['volume_dir']} "
            f"Retest: "
            f"{signal['retest']}"
        )

    # ========================================================
    # TELEGRAM
    # ========================================================

    sent = 0

    now = time.time()

    for signal in signals:

        symbol = signal["symbol"]

        direction = signal["direction"]

        key = (
            f"{symbol}_"
            f"{direction}"
        )

        # ----------------------------------------------------
        # COOLDOWN
        # ----------------------------------------------------

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

            print(
                f"🚫 Atlandı: "
                f"{symbol} "
                f"(skor)"
            )

            continue

        if signal["volume"] < MIN_VOLUME:

            print(
                f"🚫 Atlandı: "
                f"{symbol} "
                f"(hacim)"
            )

            continue

        if signal["rsi4h"] < MIN_RSI_4H:

            print(
                f"🚫 Atlandı: "
                f"{symbol} "
                f"(RSI 4H)"
            )

            continue

        if signal["volume_dir"] == "SELL":

            print(
                f"🚫 Atlandı: "
                f"{symbol} "
                f"(satış hacmi)"
            )

            continue

        if signal["btc"] == "BEARISH":

            print(
                f"🚫 Atlandı: "
                f"{symbol} "
                f"(BTC bearish)"
            )

            continue

        # ----------------------------------------------------
        # TELEGRAM
        # ----------------------------------------------------

        message = create_message(
            signal
        )

        if telegram_send(message):

            history[key] = now

            sent += 1

            print(
                f"📨 Telegram: "
                f"{symbol} "
                f"{direction} "
                f"{signal['score']}/10 "
                f"RSI4H "
                f"{signal['rsi4h']:.1f} "
                f"Hacim "
                f"{signal['volume']:.1f}x "
                f"{signal['volume_dir']}"
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
