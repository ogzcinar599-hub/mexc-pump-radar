import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PUMP RADAR 20.0
#
# AMAÇ:
# Gerçek pump başlamadan önce güçlü LONG adaylarını bulmak.
#
# MODELLER:
# 🟡 PUMP ÖNCESİ
# 🟢 BREAKOUT
# 🔵 RETEST
#
# ANA FİLTRELER:
# ✅ MEXC USDT FUTURES
# ✅ 15M + 1H + 4H
# ✅ RSI yönü
# ✅ Hacim yönü
# ✅ 4H EMA trendi
# ✅ Momentum
# ✅ Direnç
# ✅ Breakout
# ✅ Retest
# ✅ Mum satış baskısı
# ✅ BTC yönü
#
# KESİNLİKLE:
# ❌ STOCK
# ❌ TOKENIZED STOCK
# ❌ SPOT
# ❌ AŞIRI ŞİŞMİŞ COIN
# ❌ YÜKSEK HACİM + SATIŞ BASKISI
# ❌ RSI DÜŞERKEN LONG
#
# ============================================================


BASE = "https://contract.mexc.com"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HISTORY_FILE = "sent_signals.json"

MAX_WORKERS = 12

# ============================================================
# AYARLAR
# ============================================================

MIN_VOLUME = 2.90

MIN_QUALITY = 72

MAX_TELEGRAM = 8

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

        closes = [
            float(x)
            for x in d.get("close", [])
        ]

        volumes = [
            float(x)
            for x in d.get("vol", [])
        ]

        highs = [
            float(x)
            for x in d.get("high", [])
        ]

        lows = [
            float(x)
            for x in d.get("low", [])
        ]

        opens = [
            float(x)
            for x in d.get("open", [])
        ]

        if len(closes) < 50:
            return None

        return {

            "close": closes,
            "volume": volumes,
            "high": highs,
            "low": lows,
            "open": opens

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

    for i in range(
        1,
        len(closes)
    ):

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
    closes,
    period
):

    if len(closes) < period:

        return closes[-1]

    multiplier = (
        2
        / (period + 1)
    )

    ema = sum(
        closes[:period]
    ) / period

    for price in closes[period:]:

        ema = (
            price - ema
        ) * multiplier + ema

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

    if len(volumes) < 30:

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
# Hacim yüksek ama fiyat aşağı gidiyorsa:
# ❌ LONG için tehlike
#
# Hacim yükselirken yeşil mumlar güçleniyorsa:
# ✅ LONG
# ============================================================

def volume_direction(
    opens,
    closes,
    volumes
):

    if len(closes) < 8:

        return "NEUTRAL", 0.0

    avg_old = (
        sum(volumes[-8:-4])
        / 4
    )

    avg_new = (
        sum(volumes[-4:])
        / 4
    )

    if avg_old <= 0:

        return "NEUTRAL", 0.0

    volume_growth = (
        (avg_new - avg_old)
        / avg_old
    ) * 100

    green = 0
    red = 0

    for i in range(
        -4,
        0
    ):

        if closes[i] > opens[i]:

            green += volumes[i]

        else:

            red += volumes[i]

    total = green + red

    if total <= 0:

        return "NEUTRAL", volume_growth

    buy_ratio = (
        green / total
    )

    if (
        volume_growth > 20
        and buy_ratio >= 0.58
    ):

        return "BUY", volume_growth

    if (
        volume_growth > 20
        and buy_ratio <= 0.42
    ):

        return "SELL", volume_growth

    if buy_ratio > 0.55:

        return "BUY", volume_growth

    if buy_ratio < 0.45:

        return "SELL", volume_growth

    return "NEUTRAL", volume_growth


# ============================================================
# RSI YÖNÜ
# ============================================================

def rsi_direction(closes):

    if len(closes) < 35:

        return "NEUTRAL"

    rsi_now = calculate_rsi(
        closes[-20:]
    )

    rsi_old = calculate_rsi(
        closes[-25:-5]
    )

    if rsi_now > rsi_old + 2:

        return "UP"

    if rsi_now < rsi_old - 2:

        return "DOWN"

    return "FLAT"


# ============================================================
# MUM GÜCÜ
# ============================================================

def candle_pressure(
    opens,
    closes,
    highs,
    lows
):

    if len(closes) < 6:

        return "NEUTRAL"

    buy_power = 0.0
    sell_power = 0.0

    for i in range(
        -5,
        0
    ):

        high = highs[i]
        low = lows[i]
        op = opens[i]
        cl = closes[i]

        candle_range = (
            high - low
        )

        if candle_range <= 0:
            continue

        body = abs(
            cl - op
        )

        body_ratio = (
            body
            / candle_range
        )

        if cl > op:

            buy_power += body_ratio

        else:

            sell_power += body_ratio

    if buy_power > sell_power * 1.25:

        return "BUY"

    if sell_power > buy_power * 1.25:

        return "SELL"

    return "NEUTRAL"


# ============================================================
# DESTEK / DİRENÇ
# ============================================================

def resistance_level(
    highs,
    lookback=20
):

    if len(highs) < lookback + 2:

        return max(highs[:-1])

    return max(
        highs[-lookback - 1:-1]
    )


def support_level(
    lows,
    lookback=20
):

    if len(lows) < lookback + 2:

        return min(lows[:-1])

    return min(
        lows[-lookback - 1:-1]
    )


# ============================================================
# BREAKOUT
# ============================================================

def breakout_status(
    closes,
    highs,
    volumes
):

    if len(closes) < 30:

        return False

    resistance = resistance_level(
        highs,
        20
    )

    price = closes[-1]

    avg_volume = (
        sum(volumes[-21:-1])
        / 20
    )

    if avg_volume <= 0:

        return False

    current_volume = volumes[-1]

    volume_ok = (
        current_volume
        >= avg_volume * 1.8
    )

    price_ok = (
        price
        > resistance * 1.002
    )

    return (
        price_ok
        and volume_ok
    )


# ============================================================
# RETEST
# ============================================================

def retest_status(
    closes,
    highs,
    lows
):

    if len(closes) < 35:

        return False

    resistance = resistance_level(
        highs,
        20
    )

    recent_low = min(
        lows[-4:]
    )

    recent_close = closes[-1]

    # Fiyat eski dirence geri yaklaşmış
    near_level = (
        recent_low
        <= resistance * 1.012
    )

    # Ama tekrar üstünde kapanmış
    recovered = (
        recent_close
        > resistance
    )

    return (
        near_level
        and recovered
    )


# ============================================================
# PUMP ÖNCESİ
#
# Fiyat henüz çok yükselmemiş,
# direnç altında sıkışıyor,
# RSI yukarı,
# hacim yükseliyor.
# ============================================================

def pre_pump_status(
    closes,
    highs,
    lows,
    rsi15,
    rsi1h,
    vol
):

    if len(closes) < 40:

        return False

    resistance = resistance_level(
        highs,
        20
    )

    price = closes[-1]

    distance = (
        (resistance - price)
        / price
    ) * 100

    recent_change = pct_change(
        closes,
        8
    )

    # Dirence yakın ama henüz kopmamış
    near_resistance = (
        0 < distance <= 4.0
    )

    # Aşırı pump olmamış
    not_pumped = (
        recent_change < 10
    )

    rsi_ok = (
        48 <= rsi15 <= 72
        and rsi1h >= 48
    )

    volume_ok = (
        vol >= MIN_VOLUME
    )

    return (
        near_resistance
        and not_pumped
        and rsi_ok
        and volume_ok
    )


# ============================================================
# BTC YÖNÜ
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

    score = 0

    if p15 > 0:
        score += 1

    else:
        score -= 1

    if p1h > 0:
        score += 1

    else:
        score -= 1

    if p4h > 0:
        score += 1

    else:
        score -= 1

    if score >= 2:

        direction = "BULLISH"

    elif score <= -2:

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

        if is_stock_symbol(symbol):

            return None

        # ----------------------------------------------------
        # DATA
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

        c15 = data15["close"]
        o15 = data15["open"]
        h15 = data15["high"]
        l15 = data15["low"]
        v15 = data15["volume"]

        c1h = data1h["close"]

        c4h = data4h["close"]

        # ----------------------------------------------------
        # SON TAMAMLANMIŞ MUM
        #
        # -1 yerine -2 kullanıyoruz.
        # Böylece açık mumdaki ani hacim / RSI değişimi
        # sinyali bozmaz.
        # ----------------------------------------------------

        if len(c15) > 3:

            price = c15[-2]

        else:

            price = c15[-1]

        # ----------------------------------------------------
        # RSI
        # ----------------------------------------------------

        rsi15 = calculate_rsi(
            c15[:-1]
        )

        rsi1h = calculate_rsi(
            c1h[:-1]
        )

        rsi4h = calculate_rsi(
            c4h[:-1]
        )

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------

        change15 = pct_change(
            c15[:-1],
            4
        )

        change1h = pct_change(
            c1h[:-1],
            4
        )

        change4h = pct_change(
            c4h[:-1],
            3
        )

        # ----------------------------------------------------
        # HACİM
        # ----------------------------------------------------

        vol = volume_ratio(
            v15[:-1]
        )

        vol_direction, vol_growth = (
            volume_direction(
                o15[:-1],
                c15[:-1],
                v15[:-1]
            )
        )

        # ----------------------------------------------------
        # RSI YÖNÜ
        # ----------------------------------------------------

        rsi_dir = rsi_direction(
            c15[:-1]
        )

        # ----------------------------------------------------
        # MUM BASKISI
        # ----------------------------------------------------

        pressure = candle_pressure(
            o15[:-1],
            c15[:-1],
            h15[:-1],
            l15[:-1]
        )

        # ----------------------------------------------------
        # 4H EMA
        # ----------------------------------------------------

        ema20_4h = calculate_ema(
            c4h[:-1],
            20
        )

        ema50_4h = calculate_ema(
            c4h[:-1],
            50
        )

        trend_bull = (
            c4h[-2] > ema20_4h
            and ema20_4h > ema50_4h
        )

        trend_bear = (
            c4h[-2] < ema20_4h
            and ema20_4h < ema50_4h
        )

        # ----------------------------------------------------
        # DİRENÇ
        # ----------------------------------------------------

        resistance = resistance_level(
            h15[:-1],
            20
        )

        support = support_level(
            l15[:-1],
            20
        )

        # ----------------------------------------------------
        # BREAKOUT / RETEST
        # ----------------------------------------------------

        breakout = breakout_status(
            c15[:-1],
            h15[:-1],
            v15[:-1]
        )

        retest = retest_status(
            c15[:-1],
            h15[:-1],
            l15[:-1]
        )

        pre_pump = pre_pump_status(
            c15[:-1],
            h15[:-1],
            l15[:-1],
            rsi15,
            rsi1h,
            vol
        )

        # ====================================================
        # QUALITY PUANI
        # ====================================================

        long_points = 0
        short_points = 0

        reasons_long = []
        reasons_short = []

        # ====================================================
        # LONG
        # ====================================================

        # 1 — 4H EMA TREND
        if trend_bull:

            long_points += 15
            reasons_long.append(
                "4H EMA bullish"
            )

        elif trend_bear:

            long_points -= 20

        # 2 — RSI 4H
        if 50 <= rsi4h <= 68:

            long_points += 10
            reasons_long.append(
                "RSI 4H uygun"
            )

        elif 47 <= rsi4h < 50:

            long_points += 5

        elif rsi4h > 75:

            long_points -= 15

        elif rsi4h < 47:

            long_points -= 15

        # 3 — RSI 1H
        if 50 <= rsi1h <= 70:

            long_points += 10
            reasons_long.append(
                "RSI 1H güçlü"
            )

        elif 45 <= rsi1h < 50:

            long_points += 4

        elif rsi1h > 78:

            long_points -= 15

        elif rsi1h < 42:

            long_points -= 15

        # 4 — RSI 15M
        if 52 <= rsi15 <= 72:

            long_points += 8

        elif 48 <= rsi15 < 52:

            long_points += 4

        elif rsi15 > 78:

            long_points -= 20

        elif rsi15 < 42:

            long_points -= 10

        # 5 — RSI YÖNÜ
        if rsi_dir == "UP":

            long_points += 10
            reasons_long.append(
                "RSI yukarı"
            )

        elif rsi_dir == "DOWN":

            long_points -= 15

        # 6 — HACİM
        if vol >= 10:

            long_points += 12

        elif vol >= 5:

            long_points += 10

        elif vol >= MIN_VOLUME:

            long_points += 7

        # 7 — HACİM YÖNÜ
        if vol_direction == "BUY":

            long_points += 10
            reasons_long.append(
                "Alıcı hacmi"
            )

        elif vol_direction == "SELL":

            long_points -= 20

        # ====================================================
        # EN ÖNEMLİ GÜVENLİK:
        # YÜKSEK HACİM + SATIŞ BASKISI
        # ====================================================

        if (
            vol >= 5
            and vol_direction == "SELL"
        ):

            long_points -= 30

        # 8 — MUM BASKISI
        if pressure == "BUY":

            long_points += 8

        elif pressure == "SELL":

            long_points -= 18

        # 9 — MOMENTUM
        if change15 > 0:

            long_points += 5

        else:

            long_points -= 7

        if change1h > 0:

            long_points += 5

        else:

            long_points -= 8

        # 10 — BTC
        if btc_direction == "BULLISH":

            long_points += 10

        elif btc_direction == "BEARISH":

            long_points -= 20

        # 11 — BREAKOUT
        if breakout:

            long_points += 12
            reasons_long.append(
                "Breakout"
            )

        # 12 — RETEST
        if retest:

            long_points += 14
            reasons_long.append(
                "Retest"
            )

        # 13 — PUMP ÖNCESİ
        if pre_pump:

            long_points += 12
            reasons_long.append(
                "Pump öncesi"
            )

        # ====================================================
        # AŞIRI YÜKSELİŞ CEZALARI
        # ====================================================

        if change15 > 12:

            long_points -= 15

        if change1h > 15:

            long_points -= 15

        if change4h > 25:

            long_points -= 20

        # ====================================================
        # SHORT
        # ====================================================

        # 1 — EMA
        if trend_bear:

            short_points += 15

        elif trend_bull:

            short_points -= 20

        # 2 — RSI 4H
        if 35 <= rsi4h <= 50:

            short_points += 10

        elif rsi4h > 75:

            short_points += 10

        elif rsi4h < 25:

            short_points -= 15

        # 3 — RSI 1H
        if 30 <= rsi1h <= 50:

            short_points += 10

        elif rsi1h > 78:

            short_points += 12

        elif rsi1h < 25:

            short_points -= 15

        # 4 — RSI 15M
        if 28 <= rsi15 <= 50:

            short_points += 8

        elif rsi15 > 78:

            short_points += 10

        elif rsi15 < 20:

            short_points -= 15

        # 5 — RSI yön
        if rsi_dir == "DOWN":

            short_points += 10

        elif rsi_dir == "UP":

            short_points -= 15

        # 6 — hacim
        if vol >= 10:

            short_points += 12

        elif vol >= 5:

            short_points += 10

        elif vol >= MIN_VOLUME:

            short_points += 7

        # 7 — satış hacmi
        if vol_direction == "SELL":

            short_points += 10

        elif vol_direction == "BUY":

            short_points -= 15

        # 8 — mum
        if pressure == "SELL":

            short_points += 8

        elif pressure == "BUY":

            short_points -= 18

        # 9 — momentum
        if change15 < 0:

            short_points += 5

        if change1h < 0:

            short_points += 5

        # 10 — BTC
        if btc_direction == "BEARISH":

            short_points += 10

        elif btc_direction == "BULLISH":

            short_points -= 20

        # ====================================================
        # YÖN KARARI
        # ====================================================

        if long_points >= short_points:

            raw_score = long_points
            direction = "LONG"

        else:

            raw_score = short_points
            direction = "SHORT"

        quality = max(
            0,
            min(
                100,
                int(raw_score)
            )
        )

        # ====================================================
        # LONG EK GÜVENLİK
        # ====================================================

        if direction == "LONG":

            # RSI düşüyorsa
            if rsi_dir == "DOWN":
                return None

            # Hacim satış yönündeyse
            if vol_direction == "SELL":
                return None

            # Mum satış baskısı
            if pressure == "SELL":
                return None

            # 4H tamamen bearish
            if trend_bear:
                return None

            # BTC bearish
            if btc_direction == "BEARISH":
                return None

            # Momentum iki timeframe'de negatif
            if (
                change15 < 0
                and change1h < 0
            ):
                return None

        # ====================================================
        # SHORT EK GÜVENLİK
        # ====================================================

        if direction == "SHORT":

            if rsi_dir == "UP":
                return None

            if vol_direction == "BUY":
                return None

            if pressure == "BUY":
                return None

            if trend_bull:
                return None

            if btc_direction == "BULLISH":
                return None

        # ====================================================
        # MİNİMUM HACİM
        # ====================================================

        if vol < MIN_VOLUME:

            return None

        # ====================================================
        # MİNİMUM KALİTE
        # ====================================================

        if quality < MIN_QUALITY:

            return None

        # ====================================================
        # MODEL
        # ====================================================

        if direction == "LONG":

            if retest:

                model = "🔵 RETEST"

            elif breakout:

                model = "🟢 BREAKOUT"

            elif pre_pump:

                model = "🟡 PUMP ÖNCESİ"

            else:

                model = "🟢 TREND"

        else:

            model = "🔴 SHORT"

        # ====================================================
        # GİRİŞ / STOP / TP
        # ====================================================

        entry = price

        if direction == "LONG":

            # Destek ile giriş arasında güvenli stop
            technical_stop = (
                support * 0.992
            )

            percentage_stop = (
                entry * 0.978
            )

            stop = min(
                technical_stop,
                percentage_stop
            )

            risk = (
                entry - stop
            )

            if risk <= 0:

                return None

            tp1 = (
                entry
                + risk * 1.5
            )

            tp2 = (
                entry
                + risk * 2.5
            )

            tp3 = (
                entry
                + risk * 4.0
            )

        else:

            technical_stop = (
                resistance * 1.008
            )

            percentage_stop = (
                entry * 1.022
            )

            stop = max(
                technical_stop,
                percentage_stop
            )

            risk = (
                stop - entry
            )

            if risk <= 0:

                return None

            tp1 = (
                entry
                - risk * 1.5
            )

            tp2 = (
                entry
                - risk * 2.5
            )

            tp3 = (
                entry
                - risk * 4.0
            )

        # ====================================================
        # RESULT
        # ====================================================

        return {

            "symbol":
                symbol.replace(
                    "_USDT",
                    "/USDT"
                ),

            "direction":
                direction,

            "quality":
                quality,

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

            "rsi_direction":
                rsi_dir,

            "volume":
                vol,

            "volume_direction":
                vol_direction,

            "volume_growth":
                vol_growth,

            "pressure":
                pressure,

            "change15":
                change15,

            "change1h":
                change1h,

            "change4h":
                change4h,

            "btc":
                btc_direction,

            "breakout":
                breakout,

            "retest":
                retest,

            "pre_pump":
                pre_pump,

            "trend_bull":
                trend_bull,

            "trend_bear":
                trend_bear,

            "reasons":
                reasons_long

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
# TELEGRAM MESAJ
# ============================================================

def create_message(signal):

    if signal["direction"] == "LONG":

        title = "🟢 LONG SİNYAL"

    else:

        title = "🔴 SHORT SİNYAL"

    reason_text = ""

    if signal["reasons"]:

        reason_text = (
            "\n".join(
                [
                    f"✅ {x}"
                    for x in signal["reasons"][:5]
                ]
            )
        )

    else:

        reason_text = "✅ Çoklu teknik teyit"

    message = f"""
{title}
━━━━━━━━━━━━━━━━

💎 {signal["symbol"]}

🧠 Model: {signal["model"]}

⭐ Kalite: {signal["quality"]}/100

🎯 Giriş: {fmt_price(signal["entry"])}
🛑 Stop: {fmt_price(signal["stop"])}

💰 TP1: {fmt_price(signal["tp1"])}
💰 TP2: {fmt_price(signal["tp2"])}
💰 TP3: {fmt_price(signal["tp3"])}

📊 RSI 15M: {signal["rsi15"]:.1f}
📊 RSI 1H: {signal["rsi1h"]:.1f}
📊 RSI 4H: {signal["rsi4h"]:.1f}

📈 RSI yönü: {signal["rsi_direction"]}

🔥 Hacim: {signal["volume"]:.1f}x
🔥 Hacim yönü: {signal["volume_direction"]}

💹 15M: {signal["change15"]:+.2f}%
💹 1H: {signal["change1h"]:+.2f}%
💹 4H: {signal["change4h"]:+.2f}%

🕯 Mum baskısı: {signal["pressure"]}

🚀 Breakout: {"EVET" if signal["breakout"] else "HAYIR"}
🔄 Retest: {"EVET" if signal["retest"] else "HAYIR"}
🟡 Pump öncesi: {"EVET" if signal["pre_pump"] else "HAYIR"}

🌐 BTC: {signal["btc"]}

━━━━━━━━━━━━━━━━
🧠 TEKNİK TEYİT

{reason_text}

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
        "🚀 MEXC PUMP RADAR 20.0"
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
        "🕯 SATIŞ BASKISI FİLTRESİ AKTİF"
    )

    print(
        "🚫 STOCK / SPOT FİLTRESİ AKTİF"
    )

    print()

    print(
        f"🔥 Minimum hacim: "
        f"{MIN_VOLUME:.2f}x"
    )

    print(
        f"⭐ Minimum kalite: "
        f"{MIN_QUALITY}/100"
    )

    print(
        f"📩 Maksimum Telegram: "
        f"{MAX_TELEGRAM}"
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
        f"1H : {btc1h:+.2f}%"
    )

    print(
        f"4H : {btc4h:+.2f}%"
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

    print()

    # ========================================================
    # ANALİZ
    # ========================================================

    signals = []

    completed = 0

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
                or completed == len(symbols)
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
        key=lambda x: (
            x["quality"],
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
    # EKRAN
    # ========================================================

    for signal in signals:

        print(
            f"🔥 "
            f"{signal['symbol']} "
            f"{signal['direction']} "
            f"{signal['quality']}/100 "
            f"{signal['model']} "
            f"RSI4H:"
            f"{signal['rsi4h']:.1f} "
            f"Hacim:"
            f"{signal['volume']:.1f}x "
            f"RSI:"
            f"{signal['rsi_direction']} "
            f"VOL:"
            f"{signal['volume_direction']}"
        )

    # ========================================================
    # TELEGRAM
    # ========================================================

    history = load_history()

    sent = 0

    now = time.time()

    for signal in signals:

        if sent >= MAX_TELEGRAM:

            break

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
                f"⏳ Cooldown: "
                f"{symbol}"
            )

            continue

        # ----------------------------------------------------
        # SON KONTROLLER
        # ----------------------------------------------------

        if signal["quality"] < MIN_QUALITY:

            continue

        if signal["volume"] < MIN_VOLUME:

            continue

        # LONG güvenlik
        if direction == "LONG":

            if (
                signal["rsi_direction"]
                == "DOWN"
            ):

                print(
                    f"🚫 LONG RSI düşüyor: "
                    f"{symbol}"
                )

                continue

            if (
                signal["volume_direction"]
                == "SELL"
            ):

                print(
                    f"🚫 LONG satış hacmi: "
                    f"{symbol}"
                )

                continue

            if (
                signal["pressure"]
                == "SELL"
            ):

                print(
                    f"🚫 LONG satış baskısı: "
                    f"{symbol}"
                )

                continue

            if (
                signal["btc"]
                == "BEARISH"
            ):

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
                f"{signal['quality']}/100"
            )

        time.sleep(0.5)

    # ========================================================
    # HISTORY
    # ========================================================

    save_history(history)

    print()

    print(
        f"🎯 Güçlü aday: "
        f"{len(signals)}"
    )

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
