import os
import json
import time
import math
import threading
import requests

from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PUMP RADAR 22.0
#
# ANA AMAÇ:
# Pump başlamadan önce güçlü LONG adaylarını bulmak
#
# 15M + 1H + 4H
# RSI
# EMA
# HACİM
# MOMENTUM
# BREAKOUT
# RETEST
# FAKE BREAKOUT
# SATIŞ BASKISI
# BTC FİLTRESİ
#
# 22.0 ÖNEMLİ:
# ✅ Yeni MEXC API domain
# ✅ start/end KLINE
# ✅ 429 retry
# ✅ 5xx retry
# ✅ 6 worker
# ✅ 15M / 1H / 4H DATA ayrı rapor
# ✅ API hata teşhisi
# ============================================================


# ============================================================
# AYARLAR
# ============================================================

BASE = "https://api.mexc.com"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HISTORY_FILE = "signal_history.json"

MAX_WORKERS = 6

MIN_SCORE = 65
MAX_TELEGRAM = 8

MIN_VOLUME = 2.90

MIN_RSI_4H = 47.0

COOLDOWN_HOURS = 6

REQUEST_TIMEOUT = 12

KLINE_LIMIT = 100

DEBUG_ERRORS_MAX = 8


# ============================================================
# GLOBAL
# ============================================================

debug_errors = []
debug_lock = threading.Lock()

stats = {
    "TOTAL": 0,

    "DATA15": 0,
    "DATA1H": 0,
    "DATA4H": 0,

    "RSI": 0,
    "VOLUME": 0,
    "RESISTANCE": 0,
    "FAKE": 0,
    "OVEREXTENDED": 0,
    "BTC": 0,
    "QUALITY": 0,

    "SIGNAL": 0,
    "ERROR": 0
}

stats_lock = threading.Lock()


# ============================================================
# DEBUG
# ============================================================

def add_debug_error(text):

    with debug_lock:

        if text in debug_errors:
            return

        if len(debug_errors) < DEBUG_ERRORS_MAX:
            debug_errors.append(text)


# ============================================================
# REQUEST
# ============================================================

def request_json(url, params=None, retries=3):

    headers = {
        "User-Agent": "Mozilla/5.0 MEXC-PUMP-RADAR/22.0",
        "Accept": "application/json"
    }

    last_error = None

    for attempt in range(retries):

        try:

            r = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT
            )

            status = r.status_code

            # ------------------------------------------------
            # RATE LIMIT
            # ------------------------------------------------

            if status == 429:

                last_error = f"429 RATE LIMIT: {url}"

                time.sleep(1.5 * (attempt + 1))

                continue


            # ------------------------------------------------
            # SERVER ERROR
            # ------------------------------------------------

            if status >= 500:

                last_error = f"{status} SERVER ERROR: {url}"

                time.sleep(1.2 * (attempt + 1))

                continue


            # ------------------------------------------------
            # OTHER HTTP ERROR
            # ------------------------------------------------

            if status != 200:

                try:
                    body = r.text[:250]
                except:
                    body = ""

                last_error = f"HTTP {status}: {url} | {body}"

                break


            # ------------------------------------------------
            # JSON
            # ------------------------------------------------

            data = r.json()

            if not isinstance(data, dict):

                last_error = f"JSON FORMAT ERROR: {url}"

                break


            # ------------------------------------------------
            # MEXC API ERROR
            # ------------------------------------------------

            if data.get("success") is False:

                code = data.get("code")
                msg = data.get("message")

                last_error = (
                    f"MEXC ERROR code={code} "
                    f"message={msg} "
                    f"url={url}"
                )

                break


            return data


        except requests.exceptions.Timeout:

            last_error = f"TIMEOUT: {url}"

            time.sleep(1.0 * (attempt + 1))


        except requests.exceptions.RequestException as e:

            last_error = f"REQUEST ERROR: {url} | {str(e)[:150]}"

            time.sleep(1.0 * (attempt + 1))


        except Exception as e:

            last_error = f"UNKNOWN ERROR: {url} | {str(e)[:150]}"

            break


    if last_error:
        add_debug_error(last_error)

    return None


# ============================================================
# HISTORY
# ============================================================

def load_history():

    try:

        if not os.path.exists(HISTORY_FILE):
            return {}

        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    except:

        return {}


def save_history(history):

    try:

        with open(HISTORY_FILE, "w", encoding="utf-8") as f:

            json.dump(
                history,
                f,
                indent=2,
                ensure_ascii=False
            )

    except Exception as e:

        add_debug_error(
            f"HISTORY SAVE ERROR: {str(e)[:150]}"
        )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(text):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:

        print("Telegram bilgileri yok.")

        return False


    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:

        r = requests.post(
            url,
            json=payload,
            timeout=15
        )

        return r.status_code == 200

    except Exception as e:

        print("Telegram hata:", e)

        return False


# ============================================================
# CONTRACTS
# ============================================================

def get_futures_symbols():

    url = f"{BASE}/api/v1/contract/detail"

    data = request_json(url)

    if not data:
        return []


    rows = data.get("data")

    if not isinstance(rows, list):

        add_debug_error(
            "CONTRACT DETAIL DATA LIST DEĞİL"
        )

        return []


    symbols = []

    for item in rows:

        try:

            symbol = item.get("symbol")

            if not symbol:
                continue

            # ----------------------------------------------
            # SADECE USDT FUTURES
            # ----------------------------------------------

            if not symbol.endswith("_USDT"):
                continue


            # ----------------------------------------------
            # AKTİF KONTRAT
            # ----------------------------------------------

            state = item.get("state")

            if state is not None:

                try:

                    if int(state) != 0:
                        continue

                except:
                    pass


            # ----------------------------------------------
            # STOCK / TOKENIZED STOCK FİLTRESİ
            # ----------------------------------------------

            base = symbol.replace("_USDT", "").upper()

            stock_words = [
                "STOCK",
                "ETF",
                "INDEX",
                "1000SHIB",
                "1000PEPE"
            ]

            if any(x in base for x in stock_words):
                continue


            symbols.append(symbol)


        except:
            continue


    return list(dict.fromkeys(symbols))


# ============================================================
# KLINE
# ============================================================

def get_klines(symbol, interval, limit=100):

    interval_seconds = {

        "Min15": 15 * 60,

        "Min60": 60 * 60,

        "Hour4": 4 * 60 * 60

    }


    sec = interval_seconds[interval]

    now = int(time.time())

    end = now

    start = now - (sec * (limit + 10))


    url = (
        f"{BASE}/api/v1/contract/kline/"
        f"{symbol}"
    )


    params = {

        "interval": interval,

        "start": start,

        "end": end

    }


    data = request_json(
        url,
        params=params
    )


    if not data:

        return None


    raw = data.get("data")


    if raw is None:

        add_debug_error(
            f"{symbol} {interval}: DATA YOK"
        )

        return None


    # ========================================================
    # NORMAL MEXC FORMAT
    #
    # {
    #   data:{
    #       time:[],
    #       open:[],
    #       close:[],
    #       high:[],
    #       low:[],
    #       vol:[]
    #   }
    # }
    # ========================================================

    if isinstance(raw, dict):

        times = raw.get("time") or []

        opens = raw.get("open") or []

        closes = raw.get("close") or []

        highs = raw.get("high") or []

        lows = raw.get("low") or []

        volumes = raw.get("vol") or []


        try:

            n = min(
                len(times),
                len(opens),
                len(closes),
                len(highs),
                len(lows),
                len(volumes)
            )

        except:

            return None


        if n < 40:

            add_debug_error(
                f"{symbol} {interval}: "
                f"YETERSİZ MUM n={n}"
            )

            return None


        times = times[-limit:]
        opens = opens[-limit:]
        closes = closes[-limit:]
        highs = highs[-limit:]
        lows = lows[-limit:]
        volumes = volumes[-limit:]


        try:

            return {
                "time": [float(x) for x in times],
                "open": [float(x) for x in opens],
                "close": [float(x) for x in closes],
                "high": [float(x) for x in highs],
                "low": [float(x) for x in lows],
                "volume": [float(x) for x in volumes]
            }

        except Exception as e:

            add_debug_error(
                f"{symbol} {interval}: "
                f"NUMERIC ERROR {str(e)[:100]}"
            )

            return None


    # ========================================================
    # YEDEK FORMAT
    # ========================================================

    if isinstance(raw, list):

        rows = raw

        if len(rows) < 40:

            add_debug_error(
                f"{symbol} {interval}: "
                f"LIST YETERSİZ n={len(rows)}"
            )

            return None


        parsed = []

        for row in rows:

            if not isinstance(row, (list, tuple)):
                continue

            if len(row) < 6:
                continue

            try:

                parsed.append({

                    "time": float(row[0]),

                    "open": float(row[1]),

                    "high": float(row[2]),

                    "low": float(row[3]),

                    "close": float(row[4]),

                    "volume": float(row[5])

                })

            except:
                continue


        if len(parsed) < 40:

            add_debug_error(
                f"{symbol} {interval}: "
                f"LIST PARSE FAILED"
            )

            return None


        parsed = parsed[-limit:]


        return {

            "time": [x["time"] for x in parsed],

            "open": [x["open"] for x in parsed],

            "close": [x["close"] for x in parsed],

            "high": [x["high"] for x in parsed],

            "low": [x["low"] for x in parsed],

            "volume": [x["volume"] for x in parsed]

        }


    add_debug_error(
        f"{symbol} {interval}: "
        f"BİLİNMEYEN DATA FORMAT"
    )

    return None


# ============================================================
# BASIC FUNCTIONS
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = sum(values[:period]) / period

    for price in values[period:]:

        result = (
            (price - result) * multiplier
            + result
        )

    return result


def rsi(values, period=14):

    if len(values) < period + 2:
        return None


    gains = []
    losses = []


    for i in range(1, len(values)):

        change = values[i] - values[i - 1]

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )


    avg_gain = (
        sum(gains[:period]) / period
    )

    avg_loss = (
        sum(losses[:period]) / period
    )


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


def pct_change(a, b):

    if a == 0:
        return 0

    return (
        (b - a) / a
    ) * 100


def average(values):

    if not values:
        return 0

    return sum(values) / len(values)


# ============================================================
# VOLUME
# ============================================================

def volume_analysis(volumes, closes):

    if len(volumes) < 25:
        return 0, 0, False


    previous = volumes[-21:-1]

    avg_vol = average(previous)

    if avg_vol <= 0:
        return 0, 0, False


    current = volumes[-1]

    previous_candle = volumes[-2]

    current_ratio = current / avg_vol

    peak_ratio = (
        max(volumes[-3:])
        / avg_vol
    )


    price_change = pct_change(
        closes[-2],
        closes[-1]
    )


    # ========================================================
    # HACİM YÖNÜ
    # ========================================================

    buying_volume = (
        price_change > 0
        and current >= previous_candle * 0.75
    )


    score = 0


    if current_ratio >= 2.0:
        score += 10

    if current_ratio >= 3.0:
        score += 8

    if current_ratio >= 5.0:
        score += 7

    if peak_ratio >= 5.0:
        score += 5


    # Hacim var ama fiyat düşüyorsa puan kes
    if current_ratio >= 3.0 and price_change < -1.0:
        score -= 10


    if buying_volume:
        score += 8


    return current_ratio, score, buying_volume


# ============================================================
# SELLING PRESSURE
# ============================================================

def selling_pressure(opens, closes, highs, lows):

    if len(closes) < 5:
        return False


    bad = 0


    for i in range(-5, 0):

        o = opens[i]

        c = closes[i]

        h = highs[i]

        l = lows[i]


        candle_range = h - l

        if candle_range <= 0:
            continue


        upper_wick = h - max(o, c)

        body = abs(c - o)


        # Uzun üst fitil
        if upper_wick > body * 1.8:

            bad += 1


        # Büyük kırmızı mum
        if c < o:

            drop = pct_change(o, c)

            if drop < -1.5:
                bad += 1


    return bad >= 3


# ============================================================
# FAKE BREAKOUT
# ============================================================

def fake_breakout(highs, closes):

    if len(highs) < 25:
        return False


    resistance = max(
        highs[-21:-2]
    )


    previous = closes[-2]

    current = closes[-1]


    # Önce direncin üzerine çıkıp tekrar altına geldiyse
    if previous > resistance and current < resistance:

        return True


    # Çok uzun fitil
    if (
        highs[-1] > resistance
        and current < resistance * 0.995
    ):

        return True


    return False


# ============================================================
# RESISTANCE
# ============================================================

def resistance_info(highs, closes):

    if len(highs) < 30:
        return None, False, False


    resistance = max(
        highs[-25:-2]
    )


    current = closes[-1]


    distance = pct_change(
        resistance,
        current
    )


    breakout = current > resistance * 1.002


    near = (
        abs(distance) <= 2.0
    )


    return resistance, breakout, near


# ============================================================
# RETEST
# ============================================================

def retest_signal(highs, lows, closes):

    if len(closes) < 30:
        return False


    resistance = max(
        highs[-30:-5]
    )


    current = closes[-1]

    previous_low = lows[-2]


    # Fiyat eski direncin üstünde
    # son mum retest yapmış
    if current > resistance:

        if previous_low <= resistance * 1.01:

            return True


    return False


# ============================================================
# PUMP BEFORE
# ============================================================

def pump_before(closes):

    if len(closes) < 30:
        return False


    move_6 = pct_change(
        closes[-7],
        closes[-1]
    )


    move_12 = pct_change(
        closes[-13],
        closes[-1]
    )


    # Son 6 mumda aşırı kaçmış
    if move_6 >= 10:
        return True


    if move_12 >= 18:
        return True


    return False


# ============================================================
# BTC DIRECTION
# ============================================================

def btc_direction():

    results = {}


    for interval in [
        "Min15",
        "Min60",
        "Hour4"
    ]:

        data = get_klines(
            "BTC_USDT",
            interval,
            60
        )


        if not data:

            results[interval] = 0

            continue


        closes = data["close"]


        if len(closes) < 10:

            results[interval] = 0

            continue


        change = pct_change(
            closes[-5],
            closes[-1]
        )


        results[interval] = change


    score = 0


    if results.get("Min15", 0) > 0:
        score += 1

    if results.get("Min60", 0) > 0:
        score += 1

    if results.get("Hour4", 0) > 0:
        score += 1


    if score >= 2:
        return "BULLISH", results


    if score == 1:
        return "NEUTRAL", results


    return "BEARISH", results


# ============================================================
# ANALYZE COIN
# ============================================================

def analyze_coin(symbol, btc_state):

    try:

        # ====================================================
        # DATA
        # ====================================================

        d15 = get_klines(
            symbol,
            "Min15",
            KLINE_LIMIT
        )

        if not d15:

            return None, "DATA15"


        d1h = get_klines(
            symbol,
            "Min60",
            KLINE_LIMIT
        )

        if not d1h:

            return None, "DATA1H"


        d4h = get_klines(
            symbol,
            "Hour4",
            KLINE_LIMIT
        )

        if not d4h:

            return None, "DATA4H"


        # ====================================================
        # 15M
        # ====================================================

        c15 = d15["close"]

        h15 = d15["high"]

        l15 = d15["low"]

        o15 = d15["open"]

        v15 = d15["volume"]


        # ====================================================
        # 1H
        # ====================================================

        c1h = d1h["close"]

        h1h = d1h["high"]

        l1h = d1h["low"]

        v1h = d1h["volume"]


        # ====================================================
        # 4H
        # ====================================================

        c4h = d4h["close"]

        h4h = d4h["high"]

        l4h = d4h["low"]

        o4h = d4h["open"]


        # ====================================================
        # RSI
        # ====================================================

        rsi15 = rsi(c15)

        rsi1h = rsi(c1h)

        rsi4h = rsi(c4h)


        if (
            rsi15 is None
            or rsi1h is None
            or rsi4h is None
        ):

            return None, "DATA4H"


        # ====================================================
        # 4H RSI ANA FİLTRE
        # ====================================================

        if rsi4h < MIN_RSI_4H:

            return None, "RSI"


        # ====================================================
        # EMA
        # ====================================================

        ema20_15 = ema(c15, 20)

        ema50_15 = ema(c15, 50)

        ema20_1h = ema(c1h, 20)

        ema50_1h = ema(c1h, 50)

        ema20_4h = ema(c4h, 20)

        ema50_4h = ema(c4h, 50)


        if not all([
            ema20_15,
            ema50_15,
            ema20_1h,
            ema50_1h,
            ema20_4h,
            ema50_4h
        ]):

            return None, "DATA4H"


        # ====================================================
        # VOLUME
        # ====================================================

        volume_ratio, volume_score, buying_volume = (
            volume_analysis(
                v15,
                c15
            )
        )


        if volume_ratio < MIN_VOLUME:

            return None, "VOLUME"


        # ====================================================
        # SELLING PRESSURE
        # ====================================================

        selling = selling_pressure(
            o15,
            c15,
            h15,
            l15
        )


        if selling:

            return None, "FAKE"


        # ====================================================
        # FAKE BREAKOUT
        # ====================================================

        if fake_breakout(
            h15,
            c15
        ):

            return None, "FAKE"


        # ====================================================
        # RESISTANCE
        # ====================================================

        resistance, breakout, near_resistance = (
            resistance_info(
                h1h,
                c1h
            )
        )


        if resistance is None:

            return None, "RESISTANCE"


        # ====================================================
        # PUMP ALREADY HAPPENED MI?
        # ====================================================

        if pump_before(c15):

            return None, "OVEREXTENDED"


        # ====================================================
        # TREND
        # ====================================================

        trend_score = 0


        # 15M
        if c15[-1] > ema20_15:
            trend_score += 5

        if ema20_15 > ema50_15:
            trend_score += 5


        # 1H
        if c1h[-1] > ema20_1h:
            trend_score += 7

        if ema20_1h > ema50_1h:
            trend_score += 8


        # 4H
        if c4h[-1] > ema20_4h:
            trend_score += 7

        if ema20_4h > ema50_4h:
            trend_score += 8


        # ====================================================
        # RSI MOMENTUM
        # ====================================================

        rsi_score = 0


        if 50 <= rsi15 <= 72:
            rsi_score += 7


        if 50 <= rsi1h <= 68:
            rsi_score += 7


        if 47 <= rsi4h <= 65:
            rsi_score += 8


        # RSI aşırı şişmişse kes
        if rsi15 > 78:
            rsi_score -= 10


        if rsi1h > 75:
            rsi_score -= 8


        # ====================================================
        # MOMENTUM
        # ====================================================

        momentum_score = 0


        move15 = pct_change(
            c15[-5],
            c15[-1]
        )


        move1h = pct_change(
            c1h[-4],
            c1h[-1]
        )


        move4h = pct_change(
            c4h[-3],
            c4h[-1]
        )


        if move15 > 0:
            momentum_score += 5


        if move1h > 0:
            momentum_score += 6


        if move4h > 0:
            momentum_score += 6


        if move15 > 2:
            momentum_score += 3


        # ====================================================
        # BREAKOUT / RETEST
        # ====================================================

        breakout_score = 0


        if breakout:

            breakout_score += 10


        if retest_signal(
            h1h,
            l1h,
            c1h
        ):

            breakout_score += 12


        if near_resistance and not breakout:

            breakout_score -= 3


        # ====================================================
        # BTC
        # ====================================================

        btc_score = 0


        if btc_state == "BULLISH":

            btc_score = 8


        elif btc_state == "NEUTRAL":

            btc_score = 3


        else:

            btc_score = -10


        # ====================================================
        # BTC BEARISH HARD FILTER
        # ====================================================

        if btc_state == "BEARISH":

            return None, "BTC"


        # ====================================================
        # TOTAL QUALITY
        # ====================================================

        score = (

            trend_score
            + rsi_score
            + volume_score
            + momentum_score
            + breakout_score
            + btc_score

        )


        # ====================================================
        # MAX SCORE NORMALIZATION
        # ====================================================

        score = max(
            0,
            min(
                100,
                score
            )
        )


        if score < MIN_SCORE:

            return None, "QUALITY"


        # ====================================================
        # ENTRY
        # ====================================================

        entry = c15[-1]


        # ====================================================
        # STOP
        # ====================================================

        # Yakın swing low
        swing_low = min(
            l15[-8:]
        )


        stop = swing_low * 0.997


        # Stop çok uzaksa yüzde bazlı
        risk = pct_change(
            stop,
            entry
        )


        if risk < 0:
            risk = abs(risk)


        if risk < 1.0:

            stop = entry * 0.985


        elif risk > 4.0:

            stop = entry * 0.975


        # ====================================================
        # TP
        # ====================================================

        risk_amount = entry - stop


        if risk_amount <= 0:

            return None, "QUALITY"


        tp1 = entry + risk_amount * 1.5

        tp2 = entry + risk_amount * 2.3

        tp3 = entry + risk_amount * 3.2


        # ====================================================
        # SIGNAL
        # ====================================================

        result = {

            "symbol": symbol,

            "side": "LONG",

            "score": round(score, 1),

            "entry": entry,

            "stop": stop,

            "tp1": tp1,

            "tp2": tp2,

            "tp3": tp3,

            "rsi15": rsi15,

            "rsi1h": rsi1h,

            "rsi4h": rsi4h,

            "volume": volume_ratio,

            "btc": btc_state,

            "move15": move15,

            "move1h": move1h,

            "move4h": move4h,

            "resistance": resistance,

            "breakout": breakout,

            "retest": retest_signal(
                h1h,
                l1h,
                c1h
            ),

            "trend_score": trend_score,

            "rsi_score": rsi_score,

            "volume_score": volume_score,

            "momentum_score": momentum_score,

            "breakout_score": breakout_score,

            "btc_score": btc_score

        }


        return result, "SIGNAL"


    except Exception as e:

        add_debug_error(
            f"{symbol}: ANALYZE ERROR "
            f"{str(e)[:180]}"
        )

        return None, "ERROR"


# ============================================================
# TELEGRAM FORMAT
# ============================================================

def format_signal(x):

    symbol = x["symbol"].replace(
        "_USDT",
        "/USDT"
    )


    return f"""
🚀 <b>PUMP RADAR 22.0</b>

🟢 <b>LONG ADAYI</b>

<b>{symbol}</b>

⭐ Güç: <b>{x['score']}/100</b>

━━━━━━━━━━━━━━

🎯 Giriş:
<b>{x['entry']:.8g}</b>

🛑 Stop:
<b>{x['stop']:.8g}</b>

🥇 TP1:
<b>{x['tp1']:.8g}</b>

🥈 TP2:
<b>{x['tp2']:.8g}</b>

🥉 TP3:
<b>{x['tp3']:.8g}</b>

━━━━━━━━━━━━━━

📊 RSI

15M: <b>{x['rsi15']:.1f}</b>
1H : <b>{x['rsi1h']:.1f}</b>
4H : <b>{x['rsi4h']:.1f}</b>

🔥 Hacim:
<b>{x['volume']:.2f}x</b>

📈 15M:
<b>{x['move15']:+.2f}%</b>

📈 1H:
<b>{x['move1h']:+.2f}%</b>

📈 4H:
<b>{x['move4h']:+.2f}%</b>

━━━━━━━━━━━━━━

BTC:
<b>{x['btc']}</b>

Breakout:
<b>{'EVET' if x['breakout'] else 'HAYIR'}</b>

Retest:
<b>{'EVET' if x['retest'] else 'HAYIR'}</b>

━━━━━━━━━━━━━━

⚠️ Bu sinyal otomatik teknik taramadır.
"""


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print("=" * 65)
    print("🚀 MEXC PUMP RADAR 22.0")
    print("=" * 65)
    print("")


    # ========================================================
    # CONTRACT TEST
    # ========================================================

    symbols = get_futures_symbols()


    if not symbols:

        print("❌ Futures listesi alınamadı.")

        return


    print(
        f"📊 Futures kontratları: {len(symbols)}"
    )


    # ========================================================
    # API DATA TEST
    # ========================================================

    print("")
    print("🔎 MEXC API veri testi...")
    print("")


    for interval in [
        "Min15",
        "Min60",
        "Hour4"
    ]:

        test = get_klines(
            "BTC_USDT",
            interval,
            60
        )


        if test:

            print(
                f"✅ BTC_USDT {interval}: "
                f"{len(test['close'])} mum"
            )

        else:

            print(
                f"❌ BTC_USDT {interval}: "
                f"VERİ YOK"
            )


    # ========================================================
    # BTC
    # ========================================================

    print("")
    print("₿ BTC yönü hesaplanıyor...")


    btc_state, btc_changes = btc_direction()


    print(
        f"₿ BTC DURUM: {btc_state}"
    )


    print(
        f"   15M: {btc_changes.get('Min15', 0):+.2f}%"
    )

    print(
        f"   1H : {btc_changes.get('Min60', 0):+.2f}%"
    )

    print(
        f"   4H : {btc_changes.get('Hour4', 0):+.2f}%"
    )


    # ========================================================
    # HISTORY
    # ========================================================

    history = load_history()

    now = time.time()


    # ========================================================
    # SCAN
    # ========================================================

    print("")
    print("🔍 Tarama başlıyor...")
    print("")


    results = []


    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:


        futures = {

            executor.submit(
                analyze_coin,
                symbol,
                btc_state
            ): symbol

            for symbol in symbols

        }


        for future in as_completed(futures):

            symbol = futures[future]


            try:

                result, reason = future.result()

            except Exception as e:

                result = None

                reason = "ERROR"

                add_debug_error(
                    f"{symbol}: FUTURE ERROR "
                    f"{str(e)[:150]}"
                )


            with stats_lock:

                stats["TOTAL"] += 1


                if reason == "DATA15":
                    stats["DATA15"] += 1

                elif reason == "DATA1H":
                    stats["DATA1H"] += 1

                elif reason == "DATA4H":
                    stats["DATA4H"] += 1

                elif reason == "RSI":
                    stats["RSI"] += 1

                elif reason == "VOLUME":
                    stats["VOLUME"] += 1

                elif reason == "RESISTANCE":
                    stats["RESISTANCE"] += 1

                elif reason == "FAKE":
                    stats["FAKE"] += 1

                elif reason == "OVEREXTENDED":
                    stats["OVEREXTENDED"] += 1

                elif reason == "BTC":
                    stats["BTC"] += 1

                elif reason == "QUALITY":
                    stats["QUALITY"] += 1

                elif reason == "SIGNAL":
                    stats["SIGNAL"] += 1

                elif reason == "ERROR":
                    stats["ERROR"] += 1


            if result:

                # ==========================================
                # COOLDOWN
                # ==========================================

                old = history.get(
                    symbol
                )


                if old:

                    elapsed = (
                        now
                        - old.get(
                            "time",
                            0
                        )
                    )


                    if elapsed < (
                        COOLDOWN_HOURS * 3600
                    ):

                        continue


                results.append(result)


    # ========================================================
    # SORT
    # ========================================================

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )


    # ========================================================
    # TELEGRAM
    # ========================================================

    sent = 0


    for result in results:

        if sent >= MAX_TELEGRAM:
            break


        symbol = result["symbol"]


        # Telegram
        ok = send_telegram(
            format_signal(result)
        )


        if ok:

            history[symbol] = {

                "time": now,

                "score": result["score"],

                "entry": result["entry"],

                "stop": result["stop"]

            }


            sent += 1


            print(
                f"📨 Telegram: "
                f"{symbol} "
                f"{result['score']}/100"
            )


    save_history(history)


    # ========================================================
    # REPORT
    # ========================================================

    print("")
    print("=" * 65)
    print("📊 ELEME RAPORU")
    print("=" * 65)

    print(
        f"Toplam Futures     : {stats['TOTAL']}"
    )

    print(
        f"15M veri hatası    : {stats['DATA15']}"
    )

    print(
        f"1H veri hatası     : {stats['DATA1H']}"
    )

    print(
        f"4H veri hatası     : {stats['DATA4H']}"
    )

    print(
        f"RSI düşük          : {stats['RSI']}"
    )

    print(
        f"Hacim düşük        : {stats['VOLUME']}"
    )

    print(
        f"Direnç             : {stats['RESISTANCE']}"
    )

    print(
        f"Fake breakout      : {stats['FAKE']}"
    )

    print(
        f"Aşırı yükselmiş    : {stats['OVEREXTENDED']}"
    )

    print(
        f"BTC filtresi       : {stats['BTC']}"
    )

    print(
        f"Kalite düşük       : {stats['QUALITY']}"
    )

    print(
        f"Teknik hata        : {stats['ERROR']}"
    )

    print(
        f"Uygun aday         : {len(results)}"
    )

    print(
        f"Telegram gönderim  : {sent}"
    )


    # ========================================================
    # TOP CANDIDATES
    # ========================================================

    print("")
    print("=" * 65)
    print("🔥 EN GÜÇLÜ ADAYLAR")
    print("=" * 65)


    for x in results[:15]:

        print(
            f"{x['symbol']:18} "
            f"{x['score']:5.1f}/100 "
            f"VOL {x['volume']:5.2f}x "
            f"RSI4H {x['rsi4h']:5.1f}"
        )


    # ========================================================
    # API DEBUG
    # ========================================================

    print("")
    print("=" * 65)
    print("🛠 API DEBUG")
    print("=" * 65)


    if debug_errors:

        for err in debug_errors:

            print(
                "⚠️",
                err
            )

    else:

        print(
            "✅ API tarafında kayıtlı hata yok."
        )


    print("")
    print("=" * 65)
    print("✅ RADAR TAMAMLANDI")
    print("=" * 65)
    print("")


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
