import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PUMP RADAR 21.0
#
# AMAÇ:
# PUMP BAŞLAMADAN ÖNCE GÜÇLÜ COİNLERİ BULMAK
#
# MODEL:
# 🟡 PUMP ÖNCESİ
# 🟢 BREAKOUT
# 🔵 RETEST
#
# FİLTRELER:
# RSI
# HACİM
# HACİM YÖNÜ
# EMA TREND
# MOMENTUM
# DİRENÇ
# BREAKOUT
# RETEST
# SATIŞ BASKISI
# FAKE BREAKOUT
# BTC
#
# SADECE:
# MEXC USDT FUTURES
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

MIN_VOLUME = 2.90

MIN_RSI_4H = 47.0

MIN_QUALITY = 65

MAX_TELEGRAM = 8

COOLDOWN_HOURS = 6


# ============================================================
# FİYAT HAREKETİ AYARLARI
# ============================================================

# Çok hızlı yükselmişse peşinden koşma
MAX_15M_CHANGE = 8.0
MAX_1H_CHANGE = 12.0
MAX_4H_CHANGE = 18.0

# Çok yüksek RSI
MAX_RSI_15 = 82
MAX_RSI_1H = 78

# Dirence çok yakınsa riskli
RESISTANCE_DANGER = 0.004


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

        if len(closes) < 40:

            return None

        return {

            "close": [
                float(x)
                for x in closes
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

def ema(
    values,
    period
):

    if len(values) < period:

        return 0

    multiplier = 2 / (
        period + 1
    )

    result = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        result = (
            price - result
        ) * multiplier + result

    return result


# ============================================================
# EMA SERİSİ
# ============================================================

def ema_series(
    values,
    period
):

    if len(values) < period:

        return []

    multiplier = 2 / (
        period + 1
    )

    result = [
        sum(values[:period]) / period
    ]

    for price in values[period:]:

        result.append(
            (
                price - result[-1]
            ) * multiplier
            + result[-1]
        )

    return result


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
# HACİM ANALİZİ
#
# ESKİ SİSTEMDE:
#
# Son 3 mumun EN YÜKSEK hacmini kullanıyorduk.
#
# Bu problem oluşturabilir:
#
# Mum 1 = 36x
# Mum 2 = 2x
# Mum 3 = 1x
#
# Sistem 36x diyordu.
#
# AMA pump bitmiş olabilir.
#
# YENİ:
# current volume
# previous volume
# recent peak
#
# birlikte inceleniyor.
# ============================================================

def volume_analysis(volumes):

    if len(volumes) < 30:

        return {
            "current": 1.0,
            "previous": 1.0,
            "peak": 1.0,
            "average": 1.0,
            "direction": "WEAK"
        }

    avg = (
        sum(volumes[-21:-1])
        / 20
    )

    if avg <= 0:

        avg = 1

    current = (
        volumes[-1]
        / avg
    )

    previous = (
        volumes[-2]
        / avg
    )

    peak = max(
        volumes[-3:]
    ) / avg

    if current > previous * 1.10:

        direction = "RISING"

    elif current < previous * 0.70:

        direction = "FALLING"

    else:

        direction = "STABLE"

    return {

        "current": current,
        "previous": previous,
        "peak": peak,
        "average": avg,
        "direction": direction

    }


# ============================================================
# DİRENÇ
# ============================================================

def get_resistance(
    highs,
    lookback=20
):

    if len(highs) < lookback + 2:

        return 0

    # Son mumu hariç tutuyoruz.
    # Böylece mevcut mum kendisiyle
    # direnç karşılaştırması yapmıyor.

    return max(
        highs[-lookback-1:-1]
    )


# ============================================================
# BREAKOUT
# ============================================================

def detect_breakout(
    closes,
    highs
):

    resistance = get_resistance(
        highs,
        20
    )

    if resistance <= 0:

        return False

    current = closes[-1]

    previous = closes[-2]

    # %0.2 üstü gerçek kırılım
    breakout_level = (
        resistance * 1.002
    )

    if (
        current > breakout_level
        and previous <= resistance
    ):

        return True

    return False


# ============================================================
# RETEST
# ============================================================

def detect_retest(
    closes,
    highs,
    lows
):

    resistance = get_resistance(
        highs,
        20
    )

    if resistance <= 0:

        return False

    current = closes[-1]

    recent_low = min(
        lows[-3:]
    )

    # Fiyat direncin üzerinde
    # veya çok yakınında olmalı.

    above = (
        current >= resistance * 0.998
    )

    # Son mumlarda eski dirence
    # temas / yaklaşma

    touched = (
        recent_low
        <= resistance * 1.006
    )

    # Son kapanış direncin altında
    # ezilmemeli.

    holding = (
        current >= resistance * 0.998
    )

    return (
        above
        and touched
        and holding
    )


# ============================================================
# PUMP ÖNCESİ
# ============================================================

def detect_pump_before(
    price,
    resistance,
    rsi15,
    rsi1h,
    change15,
    change1h,
    volume_current
):

    if resistance <= 0:

        return False

    distance = (
        resistance - price
    ) / price * 100

    # Dirence %0.3 - %4 mesafe
    # Çok uzak değil
    # Çok geç de değil

    near_resistance = (
        0.3 <= distance <= 4.0
    )

    rsi_ok = (
        48 <= rsi15 <= 72
        and
        45 <= rsi1h <= 68
    )

    momentum_ok = (
        change15 > -1.0
        and
        change1h > -3.0
    )

    volume_ok = (
        volume_current >= 1.30
    )

    return (
        near_resistance
        and rsi_ok
        and momentum_ok
        and volume_ok
    )


# ============================================================
# SATIŞ BASKISI
# ============================================================

def selling_pressure(
    opens,
    closes,
    volumes
):

    if len(closes) < 10:

        return False

    current_close = closes[-1]
    previous_close = closes[-2]

    current_volume = volumes[-1]
    previous_volume = volumes[-2]

    # Büyük kırmızı mum
    red = (
        current_close
        < previous_close
    )

    # Hacim yükselirken fiyat düşüyorsa
    # satış baskısı olabilir.

    volume_rising = (
        current_volume
        > previous_volume * 1.20
    )

    return (
        red
        and volume_rising
    )


# ============================================================
# FAKE BREAKOUT
# ============================================================

def fake_breakout_filter(
    closes,
    highs,
    lows,
    volumes
):

    if len(closes) < 5:

        return False

    resistance = get_resistance(
        highs,
        20
    )

    if resistance <= 0:

        return False

    # Önceki mum direnç üstüne çıktı mı?
    previous_break = (
        closes[-2]
        > resistance
    )

    # Son mum tekrar aşağı mı indi?

    current_failed = (
        closes[-1]
        < resistance * 0.995
    )

    # Son mum hacimli satış mı?

    current_red = (
        closes[-1]
        < closes[-2]
    )

    return (
        previous_break
        and current_failed
        and current_red
    )


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

            return None, "STOCK"

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

            return None, "DATA"

        c15 = data15["close"]
        v15 = data15["volume"]
        h15 = data15["high"]
        l15 = data15["low"]

        c1h = data1h["close"]

        c4h = data4h["close"]

        price = c15[-1]

        # ----------------------------------------------------
        # RSI
        # ----------------------------------------------------

        rsi15 = calculate_rsi(c15)

        rsi1h = calculate_rsi(c1h)

        rsi4h = calculate_rsi(c4h)

        # ----------------------------------------------------
        # HARD RSI
        # ----------------------------------------------------

        if rsi4h < MIN_RSI_4H:

            return None, "RSI4H"

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

        volume = volume_analysis(
            v15
        )

        volume_current = (
            volume["current"]
        )

        volume_peak = (
            volume["peak"]
        )

        # Hard volume:
        # Son mum veya son 3 mum içinde
        # anlamlı hacim olmalı.

        if volume_peak < MIN_VOLUME:

            return None, "VOLUME"

        # ----------------------------------------------------
        # EMA
        # ----------------------------------------------------

        ema9_15 = ema(
            c15,
            9
        )

        ema20_15 = ema(
            c15,
            20
        )

        ema20_4h = ema(
            c4h,
            20
        )

        ema50_4h = ema(
            c4h,
            50
        )

        # ----------------------------------------------------
        # EMA TREND
        # ----------------------------------------------------

        ema_trend = (
            ema20_4h
            > ema50_4h
        )

        price_above_ema = (
            price > ema9_15
        )

        # ----------------------------------------------------
        # DİRENÇ
        # ----------------------------------------------------

        resistance = get_resistance(
            h15,
            20
        )

        if resistance <= 0:

            return None, "RESISTANCE"

        # ----------------------------------------------------
        # BREAKOUT
        # ----------------------------------------------------

        breakout = detect_breakout(
            c15,
            h15
        )

        # ----------------------------------------------------
        # RETEST
        # ----------------------------------------------------

        retest = detect_retest(
            c15,
            h15,
            l15
        )

        # ----------------------------------------------------
        # PUMP ÖNCESİ
        # ----------------------------------------------------

        pump_before = detect_pump_before(
            price,
            resistance,
            rsi15,
            rsi1h,
            change15,
            change1h,
            volume_current
        )

        # ----------------------------------------------------
        # FAKE BREAKOUT
        # ----------------------------------------------------

        fake = fake_breakout_filter(
            c15,
            h15,
            l15,
            v15
        )

        if fake:

            return None, "FAKE"

        # ----------------------------------------------------
        # SATIŞ BASKISI
        # ----------------------------------------------------

        sell_pressure = selling_pressure(
            [],
            c15,
            v15
        )

        # Son mum güçlü satış ise
        # LONG kalitesini ciddi düşürüyoruz.

        # ----------------------------------------------------
        # AŞIRI HAREKET
        # ----------------------------------------------------

        over_extended = (

            change15 > MAX_15M_CHANGE

            or

            change1h > MAX_1H_CHANGE

            or

            change4h > MAX_4H_CHANGE

            or

            rsi15 > MAX_RSI_15

            or

            rsi1h > MAX_RSI_1H

        )

        if over_extended:

            return None, "OVEREXTENDED"

        # ====================================================
        # LONG KALİTE PUANI
        # ====================================================

        quality = 0

        reasons = []

        # ----------------------------------------------------
        # RSI
        # ----------------------------------------------------

        if 50 <= rsi15 <= 70:

            quality += 8
            reasons.append("RSI15")

        elif 47 <= rsi15 < 50:

            quality += 4

        if 48 <= rsi1h <= 68:

            quality += 8
            reasons.append("RSI1H")

        elif rsi1h > 68:

            quality += 3

        if 47 <= rsi4h <= 60:

            quality += 8
            reasons.append("RSI4H")

        elif rsi4h > 60:

            quality += 4

        # ----------------------------------------------------
        # EMA
        # ----------------------------------------------------

        if ema_trend:

            quality += 10
            reasons.append("EMA4H")

        elif c4h[-1] > ema20_4h:

            quality += 6
            reasons.append("EMA RECOVERY")

        # ----------------------------------------------------
        # 15M EMA
        # ----------------------------------------------------

        if price_above_ema:

            quality += 5
            reasons.append("EMA15")

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------

        if change15 > 0:

            quality += 6
            reasons.append("MOM15")

        elif change15 > -0.5:

            quality += 3

        if change1h > 0:

            quality += 6
            reasons.append("MOM1H")

        elif change1h > -1:

            quality += 3

        # ----------------------------------------------------
        # HACİM
        # ----------------------------------------------------

        if volume_current >= 2.90:

            quality += 10
            reasons.append("VOL NOW")

        elif volume_current >= 2.0:

            quality += 7

        elif volume_current >= 1.30:

            quality += 4

        # ----------------------------------------------------
        # HACİM YÖNÜ
        # ----------------------------------------------------

        if volume["direction"] == "RISING":

            quality += 6
            reasons.append("VOL RISING")

        elif volume["direction"] == "STABLE":

            quality += 2

        # ----------------------------------------------------
        # BREAKOUT
        # ----------------------------------------------------

        if breakout:

            quality += 12
            reasons.append("BREAKOUT")

        # ----------------------------------------------------
        # RETEST
        # ----------------------------------------------------

        if retest:

            quality += 12
            reasons.append("RETEST")

        # ----------------------------------------------------
        # PUMP ÖNCESİ
        # ----------------------------------------------------

        if pump_before:

            quality += 10
            reasons.append("PUMP BEFORE")

        # ----------------------------------------------------
        # BTC
        # ----------------------------------------------------

        if btc_direction == "BULLISH":

            quality += 7
            reasons.append("BTC BULLISH")

        elif btc_direction == "NEUTRAL":

            quality += 3
            reasons.append("BTC NEUTRAL")

        elif btc_direction == "BEARISH":

            # BTC Bearish LONG engeli
            return None, "BTC"

        # ----------------------------------------------------
        # SATIŞ BASKISI
        # ----------------------------------------------------

        if sell_pressure:

            quality -= 15

            reasons.append(
                "SELL PRESSURE"
            )

        # ----------------------------------------------------
        # DİRENÇ MESAFESİ
        # ----------------------------------------------------

        distance = (
            resistance - price
        ) / price * 100

        if (
            0.5
            <= distance
            <= 3.0
        ):

            quality += 7

            reasons.append(
                "RESISTANCE NEAR"
            )

        elif distance > 5:

            quality -= 3

        # ----------------------------------------------------
        # DİRENCE ÇOK YAKIN
        # ----------------------------------------------------

        danger_distance = (
            resistance - price
        ) / price
        if (
            danger_distance
            < RESISTANCE_DANGER
            and not breakout
            and not retest
        ):

            quality -= 8

        # ====================================================
        # YENİ EK GÜVENLİK
        # ====================================================

        # Hacim çok yüksek ama fiyat düşüyorsa
        # pump değil satış olabilir.

        if (
            volume_peak >= 8
            and
            change15 < -1
            and
            not retest
        ):

            quality -= 12

            reasons.append(
                "HIGH VOL SELL"
            )

        # Son mum kırmızı + hacim düşüşü
        # ve fiyat EMA altında ise LONG kalitesi düşer.

        if (
            sell_pressure
            and
            not breakout
            and
            not retest
        ):

            quality -= 10

        # ====================================================
        # KALİTE
        # ====================================================

        if quality < MIN_QUALITY:

            return None, "QUALITY"

        # ====================================================
        # YÖN
        # ====================================================

        direction = "LONG"

        # ====================================================
        # GİRİŞ / STOP / TP
        # ====================================================

        entry = price

        # Stop biraz daha teknik.
        # %2.2

        stop = (
            entry * 0.978
        )

        # TP

        tp1 = (
            entry * 1.022
        )

        tp2 = (
            entry * 1.045
        )

        tp3 = (
            entry * 1.070
        )

        # ====================================================
        # MODEL
        # ====================================================

        if retest:

            model = "RETEST"

        elif breakout:

            model = "BREAKOUT"

        elif pump_before:

            model = "PUMP ÖNCESİ"

        else:

            model = "MOMENTUM"

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

            "quality":
                min(
                    max(
                        quality,
                        0
                    ),
                    100
                ),

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

            "volume":
                volume_peak,

            "volume_current":
                volume_current,

            "volume_direction":
                volume["direction"],

            "change15":
                change15,

            "change1h":
                change1h,

            "change4h":
                change4h,

            "resistance":
                resistance,

            "btc":
                btc_direction,

            "breakout":
                breakout,

            "retest":
                retest,

            "pump_before":
                pump_before,

            "reasons":
                reasons

        }, "OK"

    except Exception as e:

        print(
            f"⚠️ {symbol} HATA: {e}"
        )

        return None, "ERROR"


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

    if signal["model"] == "PUMP ÖNCESİ":

        model_icon = "🟡"

    elif signal["model"] == "BREAKOUT":

        model_icon = "🟢"

    elif signal["model"] == "RETEST":

        model_icon = "🔵"

    else:

        model_icon = "⚪"

    message = f"""
🟢 LONG SİNYAL
━━━━━━━━━━━━━━━━

💎 {signal["symbol"]}

{model_icon} Model: {signal["model"]}

⭐ Kalite: {signal["quality"]}/100

🎯 Giriş: {fmt_price(signal["entry"])}
🛑 Stop: {fmt_price(signal["stop"])}

💰 TP1: {fmt_price(signal["tp1"])}
💰 TP2: {fmt_price(signal["tp2"])}
💰 TP3: {fmt_price(signal["tp3"])}

📊 RSI 15M: {signal["rsi15"]:.1f}
📊 RSI 1H: {signal["rsi1h"]:.1f}
📊 RSI 4H: {signal["rsi4h"]:.1f}

🔥 Hacim Peak: {signal["volume"]:.1f}x
🔥 Hacim Şimdi: {signal["volume_current"]:.1f}x
📈 Hacim Yönü: {signal["volume_direction"]}

🚀 15M: {signal["change15"]:+.2f}%
🚀 1H: {signal["change1h"]:+.2f}%
🚀 4H: {signal["change4h"]:+.2f}%

🚧 Direnç: {fmt_price(signal["resistance"])}

{"🚀 BREAKOUT: EVET" if signal["breakout"] else "⚪ BREAKOUT: HAYIR"}
{"🔄 RETEST: EVET" if signal["retest"] else "⚪ RETEST: HAYIR"}
{"🟡 PUMP ÖNCESİ: EVET" if signal["pump_before"] else "⚪ PUMP ÖNCESİ: HAYIR"}

🌐 BTC: {signal["btc"]}

━━━━━━━━━━━━━━━━
⚠️ Otomatik teknik taramadır.
"""

    return message.strip()


# ============================================================
# ANA RADAR
# ============================================================

def main():

    print()
    print("=" * 55)
    print("🚀 MEXC PUMP RADAR 21.0")
    print("=" * 55)

    print(
        "🧠 PUMP ÖNCESİ + BREAKOUT + RETEST"
    )

    print(
        "📊 RSI + HACİM + EMA + MOMENTUM"
    )

    print(
        "🛡️ SATIŞ BASKISI + FAKE BREAKOUT"
    )

    print(
        "🚫 STOCK / SPOT / TOKENIZED STOCK"
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
        f"{MIN_QUALITY}/100"
    )

    print(
        f"📨 Maksimum Telegram: "
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

    print()
    print(
        "=" * 55
    )

    print(
        f"🌐 BTC YÖNÜ: {btc_direction}"
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

    print()
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
        f"🔎 Tarama: "
        f"{len(symbols)}"
    )

    print()

    # ========================================================
    # REJECTION COUNTER
    # ========================================================

    reject = {

        "DATA": 0,
        "RSI4H": 0,
        "VOLUME": 0,
        "RESISTANCE": 0,
        "FAKE": 0,
        "OVEREXTENDED": 0,
        "BTC": 0,
        "QUALITY": 0,
        "STOCK": 0,
        "ERROR": 0

    }

    signals = []

    completed = 0

    # ========================================================
    # PARALEL
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
                or
                completed == len(symbols)
            ):

                print(
                    f"İlerleme: "
                    f"{completed}/"
                    f"{len(symbols)}"
                )

            symbol = futures[future]

            try:

                result, reason = (
                    future.result()
                )

                if reason in reject:

                    reject[reason] += 1

                if result:

                    signals.append(
                        result
                    )

            except Exception as e:

                reject["ERROR"] += 1

                print(
                    f"⚠️ Future hata "
                    f"{symbol}: {e}"
                )

    # ========================================================
    # SIRALAMA
    # ========================================================

    signals.sort(
        key=lambda x:
        (
            x["quality"],
            x["volume_current"],
            x["volume"]
        ),
        reverse=True
    )

    # ========================================================
    # SONUÇ
    # ========================================================

    print()
    print("=" * 55)

    print(
        f"🎯 UYGUN ADAY: "
        f"{len(signals)}"
    )

    print("=" * 55)

    # ========================================================
    # REJECTION RAPORU
    # ========================================================

    print()
    print("🧹 ELEME RAPORU")
    print("-" * 40)

    print(
        f"RSI 4H düşük       : "
        f"{reject['RSI4H']}"
    )

    print(
        f"Hacim düşük        : "
        f"{reject['VOLUME']}"
    )

    print(
        f"Direnç verisi      : "
        f"{reject['RESISTANCE']}"
    )

    print(
        f"Fake breakout      : "
        f"{reject['FAKE']}"
    )

    print(
        f"Aşırı yükselmiş    : "
        f"{reject['OVEREXTENDED']}"
    )

    print(
        f"BTC filtresi       : "
        f"{reject['BTC']}"
    )

    print(
        f"Kalite düşük       : "
        f"{reject['QUALITY']}"
    )

    print(
        f"Veri hatası        : "
        f"{reject['DATA']}"
    )

    print(
        f"Teknik hata        : "
        f"{reject['ERROR']}"
    )

    print("-" * 40)

    # ========================================================
    # ADAYLAR
    # ========================================================

    for signal in signals:

        print(
            f"🔥 {signal['symbol']} "
            f"| {signal['model']} "
            f"| {signal['quality']}/100 "
            f"| VOL "
            f"{signal['volume_current']:.1f}x "
            f"| RSI4H "
            f"{signal['rsi4h']:.1f}"
        )

    # ========================================================
    # TELEGRAM
    # ========================================================

    history = load_history()

    sent = 0

    now = time.time()

    print()
    print("=" * 55)
    print("📨 TELEGRAM")
    print("=" * 55)

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
        # KALİTE
        # ----------------------------------------------------

        if (
            signal["quality"]
            < MIN_QUALITY
        ):

            continue

        # ----------------------------------------------------
        # HACİM
        # ----------------------------------------------------

        if (
            signal["volume"]
            < MIN_VOLUME
        ):

            continue

        # ----------------------------------------------------
        # BTC
        # ----------------------------------------------------

        if (
            direction == "LONG"
            and
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
                f"📨 {sent}/{MAX_TELEGRAM} "
                f"{symbol} "
                f"{signal['model']} "
                f"{signal['quality']}/100"
            )

        time.sleep(0.5)

    # ========================================================
    # HISTORY
    # ========================================================

    save_history(history)

    # ========================================================
    # SON RAPOR
    # ========================================================

    print()
    print("=" * 55)

    print(
        f"🎯 Güçlü aday: "
        f"{len(signals)}"
    )

    print(
        f"📨 Telegram gönderilen: "
        f"{sent}"
    )

    print(
        f"🟡 Pump öncesi: "
        f"{sum(1 for x in signals if x['pump_before'])}"
    )

    print(
        f"🟢 Breakout: "
        f"{sum(1 for x in signals if x['breakout'])}"
    )

    print(
        f"🔵 Retest: "
        f"{sum(1 for x in signals if x['retest'])}"
    )

    print(
        "🏁 Tarama tamamlandı."
    )

    print("=" * 55)
    print()


# ============================================================
# START
# ===========================================================

if __name__ == "__main__":

    main()
