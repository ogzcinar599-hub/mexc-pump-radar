import os
import json
import time
import math
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PUMP RADAR 25.1
#
# AMAÇ:
# SADECE AZ SAYIDA, YÜKSEK POTANSİYELLİ LONG ADAYI
#
# TELEGRAM:
# GİRİŞ
# STOP
# TP1 / TP2 / TP3
# RSI
#
# ZAYIF COINLER GÖNDERİLMEZ
# ============================================================


# ============================================================
# AYARLAR
# ============================================================

BASE = "https://contract.mexc.com"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HISTORY_FILE = "signal_history.json"


# ------------------------------------------------------------
# TARAYICI AYARLARI
# ------------------------------------------------------------

MAX_WORKERS = 4

REQUEST_TIMEOUT = 12
RETRIES = 4
RETRY_BASE = 1.5

# API istekleri arasında minimum süre
MIN_API_INTERVAL = 0.12

# Kaç coin derin taramaya girecek
MAX_CANDIDATES = 180

# Telegram'da aynı taramada maksimum kaç coin
MAX_TELEGRAM = 3

# ANA FİLTRE
MIN_SCORE = 78

# Aynı coin tekrar sinyal vermesin
COOLDOWN_HOURS = 12


# ============================================================
# GLOBAL API RATE LIMIT
# ============================================================

api_lock = threading.Lock()
last_api_request = 0.0


def api_wait():
    global last_api_request

    with api_lock:
        now = time.time()
        wait_time = MIN_API_INTERVAL - (now - last_api_request)

        if wait_time > 0:
            time.sleep(wait_time)

        last_api_request = time.time()


# ============================================================
# HTTP
# ============================================================

session = requests.Session()


def request_json(url, params=None):

    for attempt in range(RETRIES):

        try:

            api_wait()

            r = session.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            # RATE LIMIT
            if r.status_code == 429:

                time.sleep(RETRY_BASE * (attempt + 1))
                continue

            # SERVER HATALARI
            if r.status_code >= 500:

                time.sleep(RETRY_BASE * (attempt + 1))
                continue

            if r.status_code != 200:

                time.sleep(RETRY_BASE)
                continue

            data = r.json()

            # MEXC API ERROR
            if isinstance(data, dict):

                success = data.get("success", True)
                code = data.get("code", 0)

                if success is False:

                    if str(code) in {
                        "510",
                        "511",
                        "502",
                        "503",
                        "504"
                    }:

                        time.sleep(RETRY_BASE * (attempt + 1))
                        continue

                    return None

            return data

        except requests.exceptions.Timeout:

            time.sleep(RETRY_BASE * (attempt + 1))

        except requests.exceptions.RequestException:

            time.sleep(RETRY_BASE * (attempt + 1))

        except Exception:

            time.sleep(RETRY_BASE)

    return None


# ============================================================
# JSON HISTORY
# ============================================================

def load_history():

    try:

        if not os.path.exists(HISTORY_FILE):
            return {}

        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

            if isinstance(data, dict):
                return data

    except Exception:
        pass

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
                indent=2,
                ensure_ascii=False
            )

    except Exception as e:

        print("History kayıt hatası:", e)


def is_cooldown(symbol, history):

    last = history.get(symbol)

    if not last:
        return False

    try:

        last_time = float(last)
        elapsed = time.time() - last_time

        return elapsed < COOLDOWN_HOURS * 3600

    except Exception:

        return False


# ============================================================
# FUTURES SYMBOLS
# ============================================================

def get_futures_symbols():

    url = f"{BASE}/api/v1/contract/detail"

    data = request_json(url)

    if not data:
        return []

    raw = data.get("data", [])

    if isinstance(raw, dict):
        raw = list(raw.values())

    symbols = []

    for item in raw:

        try:

            symbol = str(item.get("symbol", "")).upper()

            state = item.get("state", 0)

            quote_coin = str(
                item.get("quoteCoin", "USDT")
            ).upper()

            if state != 0:
                continue

            if quote_coin != "USDT":
                continue

            if not symbol.endswith("_USDT"):
                continue

            # ------------------------------------------------
            # STOCK / ETF / INDEX / LEVERAGED EXCLUDE
            # ------------------------------------------------

            bad_words = [
                "ETF",
                "STOCK",
                "INDEX",
                "SHARE",
                "3L",
                "3S",
                "5L",
                "5S"
            ]

            if any(x in symbol for x in bad_words):
                continue

            symbols.append(symbol)

        except Exception:
            continue

    return sorted(set(symbols))


# ============================================================
# TICKERS
# ============================================================

def get_all_tickers():

    url = f"{BASE}/api/v1/contract/ticker"

    data = request_json(url)

    if not data:
        return []

    raw = data.get("data", [])

    # Bazı cevaplarda dict gelebilir
    if isinstance(raw, dict):

        # Tek ticker
        if "symbol" in raw:
            raw = [raw]

        else:
            raw = list(raw.values())

    if not isinstance(raw, list):
        return []

    return raw


# ============================================================
# KLINES
# ============================================================

def get_klines(symbol, interval, limit=80):

    interval_minutes = {
        "Min15": 15,
        "Min60": 60,
        "Hour4": 240
    }

    minutes = interval_minutes.get(interval)

    if not minutes:
        return None

    now_ms = int(time.time() * 1000)

    start_ms = now_ms - (
        minutes * 60 * 1000 * (limit + 10)
    )

    end_ms = now_ms

    url = f"{BASE}/api/v1/contract/kline/{symbol}"

    params = {
        "interval": interval,
        "start": start_ms,
        "end": end_ms
    }

    data = request_json(
        url,
        params=params
    )

    if not data:
        return None

    raw = data.get("data")

    if not raw:
        return None

    # --------------------------------------------------------
    # DICT FORMAT
    # --------------------------------------------------------

    if isinstance(raw, dict):

        try:

            times = raw.get("time", [])
            opens = raw.get("open", [])
            closes = raw.get("close", [])
            highs = raw.get("high", [])
            lows = raw.get("low", [])
            vols = raw.get("vol", [])

            n = min(
                len(times),
                len(opens),
                len(closes),
                len(highs),
                len(lows),
                len(vols)
            )

            candles = []

            for i in range(n):

                candles.append({
                    "time": float(times[i]),
                    "open": float(opens[i]),
                    "close": float(closes[i]),
                    "high": float(highs[i]),
                    "low": float(lows[i]),
                    "vol": float(vols[i])
                })

            return candles[-limit:]

        except Exception:

            return None

    # --------------------------------------------------------
    # LIST FORMAT
    # --------------------------------------------------------

    if isinstance(raw, list):

        candles = []

        for x in raw:

            try:

                if isinstance(x, dict):

                    candles.append({
                        "time": float(x.get("time", 0)),
                        "open": float(x.get("open", 0)),
                        "close": float(x.get("close", 0)),
                        "high": float(x.get("high", 0)),
                        "low": float(x.get("low", 0)),
                        "vol": float(
                            x.get(
                                "vol",
                                x.get("volume", 0)
                            )
                        )
                    })

                elif isinstance(x, list) and len(x) >= 6:

                    candles.append({
                        "time": float(x[0]),
                        "open": float(x[1]),
                        "close": float(x[2]),
                        "high": float(x[3]),
                        "low": float(x[4]),
                        "vol": float(x[5])
                    })

            except Exception:
                continue

        return candles[-limit:]

    return None


# ============================================================
# RSI
# ============================================================

def calculate_rsi(closes, period=14):

    if not closes or len(closes) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(closes)):

        change = closes[i] - closes[i - 1]

        if change >= 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(
        gains[:period]
    ) / period

    avg_loss = sum(
        losses[:period]
    ) / period

    for i in range(period, len(gains)):

        avg_gain = (
            (avg_gain * (period - 1))
            + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1))
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if not values or len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        result = (
            (price - result)
            * multiplier
            + result
        )

    return result


# ============================================================
# MOMENTUM
# ============================================================

def pct_change(values, candles):

    if not values or len(values) <= candles:
        return 0.0

    old = values[-candles - 1]
    new = values[-1]

    if old == 0:
        return 0.0

    return (
        (new - old)
        / old
        * 100
    )


# ============================================================
# VOLUME
# ============================================================

def volume_ratio(candles):

    if not candles or len(candles) < 22:
        return 0.0

    current = candles[-1]["vol"]

    previous = [
        x["vol"]
        for x in candles[-21:-1]
    ]

    avg = sum(previous) / len(previous)

    if avg <= 0:
        return 0.0

    return current / avg


def volume_growth(candles):

    if not candles or len(candles) < 15:
        return 0.0

    recent = [
        x["vol"]
        for x in candles[-3:]
    ]

    old = [
        x["vol"]
        for x in candles[-13:-3]
    ]

    if not old:
        return 0.0

    recent_avg = sum(recent) / len(recent)
    old_avg = sum(old) / len(old)

    if old_avg <= 0:
        return 0.0

    return recent_avg / old_avg


# ============================================================
# SELLING PRESSURE
# ============================================================

def selling_pressure(candles):

    if not candles:
        return 1.0

    c = candles[-1]

    high = c["high"]
    low = c["low"]
    open_price = c["open"]
    close = c["close"]

    rng = high - low

    if rng <= 0:
        return 0.0

    upper_wick = high - max(
        open_price,
        close
    )

    body = abs(close - open_price)

    # Büyük üst fitil = satış baskısı
    if upper_wick > body * 2.5:
        return 1.0

    # Kırmızı büyük mum
    if close < open_price:

        red_body = open_price - close

        if red_body > rng * 0.60:
            return 1.0

    return 0.0


# ============================================================
# PUMP ALREADY
# ============================================================

def pump_already(
    candles15,
    candles1h,
    rsi15,
    rsi1h,
    rsi4h
):

    if not candles15 or not candles1h:
        return True

    close15 = [
        x["close"]
        for x in candles15
    ]

    close1h = [
        x["close"]
        for x in candles1h
    ]

    move15_6 = pct_change(
        close15,
        6
    )

    move15_12 = pct_change(
        close15,
        12
    )

    move1h_4 = pct_change(
        close1h,
        4
    )

    # --------------------------------------------------------
    # ZATEN PUMP YAPMIŞ
    # --------------------------------------------------------

    if move15_6 >= 7.5:
        return True

    if move15_12 >= 12:
        return True

    if move1h_4 >= 8:
        return True

    # --------------------------------------------------------
    # RSI ÇOK SICAK
    # --------------------------------------------------------

    if rsi15 is not None and rsi15 >= 78:
        return True

    if rsi1h is not None and rsi1h >= 72:
        return True

    if rsi4h is not None and rsi4h >= 70:
        return True

    return False


# ============================================================
# RESISTANCE / STRUCTURE
# ============================================================

def structure_score(candles):

    if not candles or len(candles) < 30:
        return 0, False, False, 0.0

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

    price = closes[-1]

    # Son mumları hariç geçmiş direnç
    resistance = max(
        highs[-25:-3]
    )

    if resistance <= 0:
        return 0, False, False, 0.0

    distance = (
        (price - resistance)
        / resistance
        * 100
    )

    breakout = (
        price > resistance * 1.002
    )

    # Retest:
    # Son mumun low'u dirence yaklaşmış
    retest = False

    if len(lows) >= 3:

        recent_low = min(
            lows[-3:]
        )

        if (
            recent_low
            <= resistance * 1.012
            and price > resistance
        ):
            retest = True

    # --------------------------------------------------------
    # STRUCTURE SCORE
    # --------------------------------------------------------

    if retest:
        score = 15

    elif breakout:
        score = 13

    elif price >= resistance * 0.97:
        score = 10

    elif price >= resistance * 0.94:
        score = 7

    else:
        score = 2

    return (
        score,
        breakout,
        retest,
        resistance
    )


# ============================================================
# TREND SCORE
# ============================================================

def timeframe_trend(candles):

    if not candles or len(candles) < 55:
        return 0

    closes = [
        x["close"]
        for x in candles
    ]

    price = closes[-1]

    ema20 = ema(
        closes,
        20
    )

    ema50 = ema(
        closes,
        50
    )

    if ema20 is None or ema50 is None:
        return 0

    score = 0

    if price > ema20:
        score += 3

    if price > ema50:
        score += 3

    if ema20 > ema50:
        score += 2

    # Son 5 mum yükseliyorsa
    if pct_change(closes, 5) > 0:
        score += 1

    return min(score, 9)


def trend_score(
    candles15,
    candles1h,
    candles4h
):

    s15 = timeframe_trend(candles15)
    s1h = timeframe_trend(candles1h)
    s4h = timeframe_trend(candles4h)

    total = (
        s15
        + s1h
        + s4h
    )

    # 20 üzerinden
    return min(
        20,
        int(
            total
            / 27
            * 20
        )
    )


# ============================================================
# RSI SCORE
# ============================================================

def rsi_quality_score(
    rsi15,
    rsi1h,
    rsi4h
):

    score = 0

    # --------------------------------------------------------
    # 15M
    # --------------------------------------------------------

    if rsi15 is not None:

        if 54 <= rsi15 <= 65:
            score += 7

        elif 50 <= rsi15 < 54:
            score += 5

        elif 65 < rsi15 <= 70:
            score += 5

        elif 48 <= rsi15 < 50:
            score += 3

    # --------------------------------------------------------
    # 1H
    # --------------------------------------------------------

    if rsi1h is not None:

        if 55 <= rsi1h <= 65:
            score += 7

        elif 52 <= rsi1h < 55:
            score += 5

        elif 65 < rsi1h <= 69:
            score += 5

        elif 50 <= rsi1h < 52:
            score += 3

    # --------------------------------------------------------
    # 4H
    # --------------------------------------------------------

    if rsi4h is not None:

        if 50 <= rsi4h <= 62:
            score += 6

        elif 47 <= rsi4h < 50:
            score += 4

        elif 62 < rsi4h <= 67:
            score += 4

    return min(
        score,
        20
    )


# ============================================================
# VOLUME SCORE
# ============================================================

def volume_score(
    candles15,
    candles1h
):

    vr15 = volume_ratio(
        candles15
    )

    vr1h = volume_ratio(
        candles1h
    )

    growth15 = volume_growth(
        candles15
    )

    score = 0

    # 15M
    if vr15 >= 2.5:
        score += 8

    elif vr15 >= 1.8:
        score += 6

    elif vr15 >= 1.5:
        score += 5

    elif vr15 >= 1.25:
        score += 3

    # 1H
    if vr1h >= 2.0:
        score += 5

    elif vr1h >= 1.5:
        score += 4

    elif vr1h >= 1.25:
        score += 2

    # hacim gelişiyorsa bonus
    if growth15 >= 1.20:
        score += 2

    return min(
        score,
        15
    )


# ============================================================
# MOMENTUM SCORE
# ============================================================

def momentum_score(
    candles15,
    candles1h,
    candles4h
):

    c15 = [
        x["close"]
        for x in candles15
    ]

    c1h = [
        x["close"]
        for x in candles1h
    ]

    c4h = [
        x["close"]
        for x in candles4h
    ]

    m15 = pct_change(
        c15,
        4
    )

    m1h = pct_change(
        c1h,
        3
    )

    m4h = pct_change(
        c4h,
        3
    )

    score = 0

    # 15M
    if 0.4 <= m15 <= 4.0:
        score += 4

    elif m15 > 0:
        score += 2

    # 1H
    if 0.5 <= m1h <= 6.0:
        score += 4

    elif m1h > 0:
        score += 2

    # 4H
    if m4h > 0:
        score += 2

    return (
        min(score, 10),
        m15,
        m1h,
        m4h
    )


# ============================================================
# PRE-PUMP SCORE
# ============================================================

def pre_pump_score(
    candles15,
    candles1h,
    rsi15,
    rsi1h
):

    c15 = [
        x["close"]
        for x in candles15
    ]

    c1h = [
        x["close"]
        for x in candles1h
    ]

    m15 = pct_change(
        c15,
        6
    )

    m1h = pct_change(
        c1h,
        4
    )

    score = 0

    # Henüz çok yükselmemiş ama momentum var
    if 0.5 <= m15 <= 5:
        score += 6

    elif 0 < m15 <= 7:
        score += 4

    # 1H sağlıklı yükseliş
    if 0.5 <= m1h <= 7:
        score += 5

    elif m1h > 0:
        score += 3

    # RSI erken aşamadaysa
    if (
        rsi15 is not None
        and 52 <= rsi15 <= 68
    ):
        score += 2

    if (
        rsi1h is not None
        and 53 <= rsi1h <= 68
    ):
        score += 2

    return min(
        score,
        15
    )


# ============================================================
# BTC DURUMU
# ============================================================

def get_btc_state():

    c15 = get_klines(
        "BTC_USDT",
        "Min15",
        50
    )

    c1h = get_klines(
        "BTC_USDT",
        "Min60",
        50
    )

    if not c15 or not c1h:
        return 3

    close15 = [
        x["close"]
        for x in c15
    ]

    close1h = [
        x["close"]
        for x in c1h
    ]

    m15 = pct_change(
        close15,
        4
    )

    m1h = pct_change(
        close1h,
        3
    )

    # Sert BTC düşüşü
    if m15 < -1.2 and m1h < -2.0:
        return 0

    # BTC negatif
    if m15 < -0.5 or m1h < -1.0:
        return 2

    # BTC nötr/pozitif
    if m15 >= 0 and m1h >= 0:
        return 5

    return 3


# ============================================================
# ANA ANALİZ
# ============================================================

def analyze_coin(symbol):

    try:

        candles15 = get_klines(
            symbol,
            "Min15",
            80
        )

        candles1h = get_klines(
            symbol,
            "Min60",
            80
        )

        candles4h = get_klines(
            symbol,
            "Hour4",
            80
        )

        if (
            not candles15
            or not candles1h
            or not candles4h
        ):
            return None

        if (
            len(candles15) < 55
            or len(candles1h) < 55
            or len(candles4h) < 55
        ):
            return None

        close15 = [
            x["close"]
            for x in candles15
        ]

        close1h = [
            x["close"]
            for x in candles1h
        ]

        close4h = [
            x["close"]
            for x in candles4h
        ]

        price = close15[-1]

        if price <= 0:
            return None

        # ----------------------------------------------------
        # RSI
        # ----------------------------------------------------

        rsi15 = calculate_rsi(
            close15
        )

        rsi1h = calculate_rsi(
            close1h
        )

        rsi4h = calculate_rsi(
            close4h
        )

        if (
            rsi15 is None
            or rsi1h is None
            or rsi4h is None
        ):
            return None

        # ----------------------------------------------------
        # RSI HARD FILTER
        # ----------------------------------------------------

        if rsi15 < 48:
            return None

        if rsi1h < 50:
            return None

        if rsi4h < 47:
            return None

        if rsi15 > 72:
            return None

        if rsi1h > 70:
            return None

        if rsi4h > 68:
            return None

        # ----------------------------------------------------
        # PUMP ALREADY?
        # ----------------------------------------------------

        if pump_already(
            candles15,
            candles1h,
            rsi15,
            rsi1h,
            rsi4h
        ):
            return None

        # ----------------------------------------------------
        # SELLING PRESSURE
        # ----------------------------------------------------

        if selling_pressure(
            candles15
        ):
            return None

        # ----------------------------------------------------
        # TREND
        # ----------------------------------------------------

        tr_score = trend_score(
            candles15,
            candles1h,
            candles4h
        )

        # Çok zayıf trend
        if tr_score < 13:
            return None

        # ----------------------------------------------------
        # RSI SCORE
        # ----------------------------------------------------

        rs_score = rsi_quality_score(
            rsi15,
            rsi1h,
            rsi4h
        )

        if rs_score < 14:
            return None

        # ----------------------------------------------------
        # VOLUME
        # ----------------------------------------------------

        vol_score = volume_score(
            candles15,
            candles1h
        )

        # Hacimsiz coin istemiyoruz
        if vol_score < 6:
            return None

        # ----------------------------------------------------
        # PRE-PUMP
        # ----------------------------------------------------

        pp_score = pre_pump_score(
            candles15,
            candles1h,
            rsi15,
            rsi1h
        )

        if pp_score < 9:
            return None

        # ----------------------------------------------------
        # STRUCTURE
        # ----------------------------------------------------

        st_score, breakout, retest, resistance = (
            structure_score(
                candles1h
            )
        )

        # Çok uzakta direnç varsa istemiyoruz
        if resistance <= 0:
            return None

        distance = (
            (price - resistance)
            / resistance
            * 100
        )

        # Direncin çok üzerinde kovalamaca
        if distance > 2.5:
            return None

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------

        mom_score, m15, m1h, m4h = momentum_score(
            candles15,
            candles1h,
            candles4h
        )

        if mom_score < 7:
            return None

        # ----------------------------------------------------
        # BTC
        # ----------------------------------------------------

        btc_score = get_btc_state()

        if btc_score < 2:
            return None

        # ----------------------------------------------------
        # TOPLAM SCORE
        # ----------------------------------------------------

        score = (
            tr_score
            + rs_score
            + vol_score
            + pp_score
            + st_score
            + mom_score
            + btc_score
        )

        # ----------------------------------------------------
        # ERKEN GİRİŞ BONUSU
        # ----------------------------------------------------

        early_bonus = 0

        if (
            52 <= rsi15 <= 65
            and 53 <= rsi1h <= 65
            and 48 <= rsi4h <= 62
            and 0 < m15 < 4
            and 0 < m1h < 6
        ):
            early_bonus = 5

        score += early_bonus

        score = min(
            100,
            max(0, score)
        )

        # ----------------------------------------------------
        # ÇOK SIKI SON FİLTRE
        # ----------------------------------------------------

        if score < MIN_SCORE:
            return None

        # En azından 1H trend pozitif
        if m1h <= 0:
            return None

        # 15M momentum pozitif
        if m15 <= 0:
            return None

        # 4H momentum negatifse alma
        if m4h < -1.0:
            return None

        # ----------------------------------------------------
        # VOLUME
        # ----------------------------------------------------

        vr15 = volume_ratio(
            candles15
        )

        vr1h = volume_ratio(
            candles1h
        )

        # ----------------------------------------------------
        # ENTRY
        # ----------------------------------------------------

        entry = price

        # ----------------------------------------------------
        # ATR BENZERİ VOLATİLİTE
        # ----------------------------------------------------

        recent_ranges = []

        for c in candles15[-14:]:

            if c["close"] <= 0:
                continue

            recent_ranges.append(
                (
                    c["high"]
                    - c["low"]
                )
                / c["close"]
            )

        if recent_ranges:

            avg_range = (
                sum(recent_ranges)
                / len(recent_ranges)
            )

        else:

            avg_range = 0.015

        # Stop yaklaşık 1.8 - 2.5%
        stop_pct = max(
            0.018,
            min(
                0.028,
                avg_range * 1.8
            )
        )

        stop = entry * (
            1 - stop_pct
        )

        # ----------------------------------------------------
        # TAKE PROFITS
        # ----------------------------------------------------

        tp1 = entry * 1.040
        tp2 = entry * 1.065
        tp3 = entry * 1.095

        # ----------------------------------------------------
        # SONUÇ
        # ----------------------------------------------------

        return {
            "symbol": symbol,

            "score": score,

            "entry": entry,
            "stop": stop,

            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,

            "rsi15": rsi15,
            "rsi1h": rsi1h,
            "rsi4h": rsi4h,

            "volume15": vr15,
            "volume1h": vr1h,

            "momentum15": m15,
            "momentum1h": m1h,
            "momentum4h": m4h,

            "breakout": breakout,
            "retest": retest,

            "btc_score": btc_score
        }

    except Exception as e:

        print(
            f"ANALİZ HATASI {symbol}: {e}"
        )

        return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(text):

    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN yok")
        return False

    if not TELEGRAM_CHAT_ID:
        print("TELEGRAM_CHAT_ID yok")
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True
    }

    try:

        r = requests.post(
            url,
            json=payload,
            timeout=15
        )

        if r.status_code == 200:

            data = r.json()

            if data.get("ok"):
                return True

        print(
            "Telegram hata:",
            r.text[:500]
        )

    except Exception as e:

        print(
            "Telegram bağlantı hatası:",
            e
        )

    return False


# ============================================================
# TELEGRAM FORMAT
# ============================================================

def format_signal(result):

    symbol = result["symbol"].replace(
        "_USDT",
        "/USDT"
    )

    score = result["score"]

    # Güçlü sinyal
    if score >= 90:

        title = "🔥 ÇOK YÜKSEK POTANSİYEL"

    elif score >= 84:

        title = "🚀 YÜKSEK POTANSİYEL"

    else:

        title = "🟢 GÜÇLÜ LONG"

    return f"""🚀 PUMP RADAR 25.1

{title}

{symbol}

⭐ GÜÇ: {score}/100

🎯 GİRİŞ
{result["entry"]:.8f}

🛑 STOP
{result["stop"]:.8f}

🥇 TP1
{result["tp1"]:.8f}

🥈 TP2
{result["tp2"]:.8f}

🥉 TP3
{result["tp3"]:.8f}

📊 RSI

15M: {result["rsi15"]:.1f}
1H: {result["rsi1h"]:.1f}
4H: {result["rsi4h"]:.1f}

⚠️ Otomatik teknik taramadır."""


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("🚀 MEXC PUMP RADAR 25.1")
    print("🎯 SADECE YÜKSEK POTANSİYEL")
    print("=" * 60)

    history = load_history()

    # --------------------------------------------------------
    # SYMBOLS
    # --------------------------------------------------------

    symbols = get_futures_symbols()

    print(
        f"Futures coin sayısı: {len(symbols)}"
    )

    if not symbols:
        print("Futures sembol alınamadı.")
        return

    # --------------------------------------------------------
    # TICKERS
    # --------------------------------------------------------

    tickers = get_all_tickers()

    print(
        f"Ticker sayısı: {len(tickers)}"
    )

    if not tickers:
        print("Ticker alınamadı.")
        return

    ticker_map = {}

    for t in tickers:

        try:

            symbol = str(
                t.get("symbol", "")
            ).upper()

            if symbol not in symbols:
                continue

            last_price = float(
                t.get(
                    "lastPrice",
                    0
                )
            )

            rise = float(
                t.get(
                    "riseFallRate",
                    0
                )
            )

            # MEXC bazı cevaplarda decimal oran döndürür
            # Örn: 0.052 = %5.2
            rise_pct = rise * 100

            amount = float(
                t.get(
                    "amount24",
                    t.get(
                        "amount",
                        0
                    )
                )
                or 0
            )

            ticker_map[symbol] = {
                "price": last_price,
                "rise": rise_pct,
                "amount": amount
            }

        except Exception:
            continue

    # --------------------------------------------------------
    # ÖN FİLTRE
    # --------------------------------------------------------

    valid = []

    for symbol in symbols:

        t = ticker_map.get(symbol)

        if not t:
            continue

        if t["price"] <= 0:
            continue

        # Aşırı düşmüş coinleri alma
        if t["rise"] < -20:
            continue

        valid.append(
            symbol
        )

    # --------------------------------------------------------
    # HACME GÖRE SIRALA
    # --------------------------------------------------------

    top_volume = sorted(
        valid,
        key=lambda x: ticker_map[x]["amount"],
        reverse=True
    )[:120]

    # --------------------------------------------------------
    # GAINER'LARI AL
    # --------------------------------------------------------

    top_gainers = sorted(
        valid,
        key=lambda x: ticker_map[x]["rise"],
        reverse=True
    )[:100]

    candidate_set = set(
        top_volume
    )

    candidate_set.update(
        top_gainers
    )

    candidates = list(
        candidate_set
    )

    # --------------------------------------------------------
    # COOLDOWN
    # --------------------------------------------------------

    candidates = [
        x
        for x in candidates
        if not is_cooldown(
            x,
            history
        )
    ]

    # Çok fazla istek gitmesin
    candidates = candidates[
        :MAX_CANDIDATES
    ]

    print(
        f"Taranacak aday: {len(candidates)}"
    )

    if not candidates:
        print(
            "Cooldown nedeniyle aday yok."
        )
        return

    # --------------------------------------------------------
    # DERİN TARAMA
    # --------------------------------------------------------

    results = []

    completed = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_coin,
                symbol
            ): symbol

            for symbol in candidates
        }

        for future in as_completed(
            futures
        ):

            symbol = futures[future]

            try:

                result = future.result()

                completed += 1

                if result:
                    results.append(result)

            except Exception as e:

                print(
                    f"{symbol} hata: {e}"
                )

    print(
        f"Tarama tamamlandı: {completed}"
    )

    # --------------------------------------------------------
    # SCORE SIRALAMA
    # --------------------------------------------------------

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    # --------------------------------------------------------
    # SADECE EN GÜÇLÜLER
    # --------------------------------------------------------

    strong = [
        x
        for x in results
        if x["score"] >= MIN_SCORE
    ]

    # Aynı taramada maksimum 3
    strong = strong[
        :MAX_TELEGRAM
    ]

    print(
        f"GÜÇLÜ ADAY: {len(strong)}"
    )

    if not strong:

        print(
            "❌ Bu taramada yeterince güçlü coin yok."
        )

        print(
            "Zayıf coinler Telegram'a gönderilmedi."
        )

        return

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    sent_count = 0

    for result in strong:

        text = format_signal(
            result
        )

        print()
        print(
            "SİNYAL:",
            result["symbol"],
            result["score"]
        )

        success = send_telegram(
            text
        )

        if success:

            history[
                result["symbol"]
            ] = time.time()

            sent_count += 1

            # Telegram flood koruması
            time.sleep(1)

    save_history(
        history
    )

    print()
    print("=" * 60)
    print(
        f"Telegram gönderilen: {sent_count}"
    )
    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
