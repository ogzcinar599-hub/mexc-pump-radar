import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# MEXC CRYPTO FUTURES PUMP RADAR
#
# 🟢 LONG:
#    4H DIP + DÖNÜŞ
#    1H TOPARLANMA
#    15M MOMENTUM
#
# 🔴 SHORT:
#    PUMP SONRASI TEPE
#    1H DÜŞÜŞ
#    15M SATIŞ MOMENTUMU
#
# SADECE MEXC CRYPTO FUTURES
# STOCK / ETF / INDEX YOK
# ============================================================


BASE = "https://api.mexc.com"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ============================================================
# AYARLAR
# ============================================================

# Minimum aday skoru
MIN_SCORE = 72

# 24H minimum USDT hacmi
MIN_24H_VOLUME = 300000

# 24H değişim filtresi
MIN_24H_CHANGE = -25
MAX_24H_CHANGE = 30

# Her taramada maksimum sinyal
MAX_SIGNALS_PER_SCAN = 4

# Aynı coin için tekrar sinyal süresi
DUPLICATE_HOURS = 6

# LONG TP / STOP
LONG_TP1 = 1.8
LONG_TP2 = 3.5
LONG_TP3 = 5.5
LONG_STOP = 2.2

# SHORT TP / STOP
SHORT_TP1 = 1.8
SHORT_TP2 = 3.5
SHORT_TP3 = 5.5
SHORT_STOP = 2.2

# Paralel istek
MAX_WORKERS = 12

# Kline bar sayısı
KLINE_BARS = 90


# ============================================================
# DOSYA
# ============================================================

SENT_FILE = "sent_signals.json"


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "MEXC-Crypto-Futures-Pump-Radar/2.0"
})


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(text):

    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN eksik")
        return False

    if not CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID eksik")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:

        r = session.post(
            url,
            json=payload,
            timeout=15
        )

        if r.status_code == 200:

            print("✅ Telegram gönderildi")
            return True

        print(
            "❌ Telegram:",
            r.status_code,
            r.text[:300]
        )

    except Exception as e:

        print(
            "❌ Telegram hata:",
            e
        )

    return False


# ============================================================
# TELEGRAM TEST
# ============================================================

def telegram_test():

    message = (
        "🟢 <b>PUMP RADAR AKTİF</b>\n\n"

        "✅ Telegram bağlantısı çalışıyor.\n"
        "✅ GitHub Actions çalışıyor.\n\n"

        "💎 <b>SADECE CRYPTO FUTURES</b>\n"
        "🚫 Stock / ETF / Index yok.\n\n"

        "🟢 LONG:\n"
        "4H dip + dönüş\n"
        "1H toparlanma\n"
        "15M momentum\n\n"

        "🔴 SHORT:\n"
        "Pump sonrası tepe\n"
        "1H düşüş\n"
        "15M satış momentum\n\n"

        "🚀 Radar taramaya başladı."
    )

    return send_telegram(message)


# ============================================================
# JSON GET
# ============================================================

def get_json(url, params=None):

    try:

        r = session.get(
            url,
            params=params,
            timeout=15
        )

        if r.status_code != 200:

            print(
                "HTTP:",
                r.status_code,
                url
            )

            return None

        data = r.json()

        return data

    except Exception as e:

        print(
            "GET hata:",
            e
        )

        return None


# ============================================================
# FUTURES KONTRATLARI
# ============================================================

def get_futures_contracts():

    print("")
    print("📡 MEXC Crypto Futures kontratları alınıyor...")

    data = get_json(
        f"{BASE}/api/v1/contract/detail"
    )

    if not data:

        print("❌ Futures kontrat verisi alınamadı.")
        return []

    contracts = data.get(
        "data",
        []
    )

    result = []

    for c in contracts:

        try:

            symbol = str(
                c.get("symbol", "")
            ).upper()

            state = c.get(
                "state",
                0
            )

            quote = str(
                c.get("quoteCoin", "")
            ).upper()

            settle = str(
                c.get("settleCoin", "")
            ).upper()

            hidden = c.get(
                "isHidden",
                False
            )

            # ------------------------------------------------
            # SADECE USDT CRYPTO FUTURES
            # ------------------------------------------------

            if not symbol.endswith("_USDT"):
                continue

            if quote != "USDT":
                continue

            if settle != "USDT":
                continue

            # Aktif kontrat
            if str(state) != "0":
                continue

            if hidden:
                continue

            # Stablecoin çiftlerini alma
            base_coin = symbol.replace(
                "_USDT",
                ""
            )

            stablecoins = {
                "USDT",
                "USDC",
                "FDUSD",
                "TUSD",
                "DAI",
                "USDE",
                "USD1"
            }

            if base_coin in stablecoins:
                continue

            result.append(symbol)

        except Exception:
            continue

    result = sorted(
        list(set(result))
    )

    print(
        "💎 Crypto Futures:",
        len(result)
    )

    return result


# ============================================================
# FUTURES TICKER
# ============================================================

def get_futures_tickers():

    print(
        "📊 Futures ticker verisi alınıyor..."
    )

    data = get_json(
        f"{BASE}/api/v1/contract/ticker"
    )

    if not data:
        return {}

    raw = data.get(
        "data",
        []
    )

    if isinstance(raw, dict):

        raw = [raw]

    result = {}

    for x in raw:

        try:

            symbol = str(
                x.get("symbol", "")
            ).upper()

            if not symbol.endswith("_USDT"):
                continue

            price = float(
                x.get(
                    "lastPrice",
                    0
                )
            )

            volume = float(
                x.get(
                    "amount24",
                    0
                )
            )

            change = float(
                x.get(
                    "riseFallRate",
                    0
                )
            ) * 100

            high24 = float(
                x.get(
                    "high24Price",
                    0
                )
            )

            low24 = float(
                x.get(
                    "lower24Price",
                    0
                )
            )

            if price <= 0:
                continue

            result[symbol] = {

                "price": price,

                "volume": volume,

                "change": change,

                "high24": high24,

                "low24": low24,

                "funding": float(
                    x.get(
                        "fundingRate",
                        0
                    )
                )
            }

        except Exception:
            continue

    print(
        "📊 Ticker alınan:",
        len(result)
    )

    return result


# ============================================================
# KLINE
# ============================================================

def get_klines(
    symbol,
    interval
):

    # --------------------------------------------------------
    # MEXC Futures:
    #
    # Min15
    # Min60
    # Hour4
    #
    # --------------------------------------------------------

    seconds = {

        "Min15": 15 * 60,

        "Min60": 60 * 60,

        "Hour4": 4 * 60 * 60

    }

    candle_seconds = seconds[
        interval
    ]

    end_time = int(
        time.time()
    )

    start_time = (
        end_time
        - (
            candle_seconds
            * (KLINE_BARS + 5)
        )
    )

    data = get_json(

        f"{BASE}/api/v1/contract/"
        f"kline/{symbol}",

        {
            "interval": interval,
            "start": start_time,
            "end": end_time
        }
    )

    if not data:
        return []

    raw = data.get(
        "data"
    )

    if not raw:
        return []

    try:

        times = raw.get(
            "time",
            []
        )

        opens = raw.get(
            "open",
            []
        )

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

        candles = []

        n = min(
            len(times),
            len(opens),
            len(closes),
            len(highs),
            len(lows),
            len(volumes)
        )

        for i in range(n):

            candles.append({

                "time": int(
                    times[i]
                ),

                "open": float(
                    opens[i]
                ),

                "close": float(
                    closes[i]
                ),

                "high": float(
                    highs[i]
                ),

                "low": float(
                    lows[i]
                ),

                "volume": float(
                    volumes[i]
                )
            })

        return candles

    except Exception as e:

        print(
            symbol,
            interval,
            "kline parse:",
            e
        )

        return []


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    value = sum(
        values[:period]
    ) / period

    multiplier = (
        2 / (period + 1)
    )

    for price in values[period:]:

        value = (
            (price - value)
            * multiplier
        ) + value

    return value


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

    for i in range(
        1,
        len(values)
    ):

        change = (
            values[i]
            - values[i - 1]
        )

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
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
            (
                avg_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = (
        avg_gain
        / avg_loss
    )

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# HACİM ORANI
# ============================================================

def volume_ratio(candles):

    if len(candles) < 21:
        return 1.0

    previous = [
        x["volume"]
        for x in candles[-21:-1]
    ]

    current = candles[-1]["volume"]

    if not previous:
        return 1.0

    avg = (
        sum(previous)
        / len(previous)
    )

    if avg <= 0:
        return 1.0

    return (
        current
        / avg
    )


# ============================================================
# 4H LONG
# ============================================================

def analyze_4h_long(candles):

    if len(candles) < 55:
        return None

    closes = [
        x["close"]
        for x in candles
    ]

    current = closes[-1]

    ema20 = ema(
        closes,
        20
    )

    ema50 = ema(
        closes,
        50
    )

    ema20_prev = ema(
        closes[:-3],
        20
    )

    rsi_now = rsi(
        closes,
        14
    )

    if not all([
        ema20,
        ema50,
        ema20_prev,
        rsi_now
    ]):
        return None

    # Son 30 mumdaki dip
    recent30 = candles[-31:-1]

    swing_low = min(
        x["low"]
        for x in recent30
    )

    swing_high = max(
        x["high"]
        for x in recent30
    )

    if swing_low <= 0:
        return None

    recovery = (
        (current - swing_low)
        / swing_low
    ) * 100

    # Dipten çok fazla uzaklaşmışsa
    if recovery > 15:
        return None

    # Henüz dipten yeterli tepki yoksa
    if recovery < 0.5:
        return None

    # EMA mesafesi
    ema_distance = (
        (current - ema20)
        / ema20
    ) * 100

    if ema_distance < -5:
        return None

    if ema_distance > 10:
        return None

    score = 0

    # --------------------------------------------------------
    # DİP
    # --------------------------------------------------------

    if 0.5 <= recovery <= 4:
        score += 25

    elif 4 < recovery <= 8:
        score += 20

    elif 8 < recovery <= 12:
        score += 13

    else:
        score += 7

    # --------------------------------------------------------
    # EMA20
    # --------------------------------------------------------

    if current >= ema20:
        score += 10

    elif current >= ema20 * 0.995:
        score += 7

    # --------------------------------------------------------
    # EMA dönüş
    # --------------------------------------------------------

    if ema20 > ema20_prev:
        score += 10

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if 40 <= rsi_now <= 58:
        score += 15

    elif 35 <= rsi_now < 40:
        score += 10

    elif 58 < rsi_now <= 65:
        score += 8

    # --------------------------------------------------------
    # SON MUM
    # --------------------------------------------------------

    last = candles[-1]

    if last["close"] > last["open"]:
        score += 8

    # --------------------------------------------------------
    # SWING HIGH'DAN UZAKLIK
    # --------------------------------------------------------

    distance_from_high = (
        (swing_high - current)
        / swing_high
    ) * 100

    # Tepeye çok yakın değilse daha iyi
    if distance_from_high >= 5:
        score += 7

    elif distance_from_high >= 2:
        score += 4

    return {

        "score": min(score, 75),

        "rsi": rsi_now,

        "ema20": ema20,

        "recovery": recovery,

        "swing_low": swing_low,

        "swing_high": swing_high,

        "distance_high": distance_from_high
    }


# ============================================================
# 4H SHORT
# PUMP SONRASI DÜŞÜŞ
# ============================================================

def analyze_4h_short(candles):

    if len(candles) < 55:
        return None

    closes = [
        x["close"]
        for x in candles
    ]

    current = closes[-1]

    ema20 = ema(
        closes,
        20
    )

    ema20_prev = ema(
        closes[:-3],
        20
    )

    ema50 = ema(
        closes,
        50
    )

    rsi_now = rsi(
        closes,
        14
    )

    if not all([
        ema20,
        ema20_prev,
        ema50,
        rsi_now
    ]):
        return None

    recent30 = candles[-31:-1]

    swing_low = min(
        x["low"]
        for x in recent30
    )

    swing_high = max(
        x["high"]
        for x in recent30
    )

    if swing_low <= 0:
        return None

    # --------------------------------------------------------
    # PUMP ORANI
    # --------------------------------------------------------

    pump = (
        (swing_high - swing_low)
        / swing_low
    ) * 100

    # En az %8 yükseliş görmüş olmalı
    if pump < 8:
        return None

    # --------------------------------------------------------
    # TEPEYE GÖRE DÜŞÜŞ
    # --------------------------------------------------------

    drop_from_high = (
        (swing_high - current)
        / swing_high
    ) * 100

    # En az %1 geri çekilme
    if drop_from_high < 1:
        return None

    # Çok fazla düşmüşse artık geç olabilir
    if drop_from_high > 15:
        return None

    score = 0

    # --------------------------------------------------------
    # PUMP
    # --------------------------------------------------------

    if pump >= 25:
        score += 25

    elif pump >= 18:
        score += 22

    elif pump >= 12:
        score += 18

    else:
        score += 12

    # --------------------------------------------------------
    # TEPE'DEN DÖNÜŞ
    # --------------------------------------------------------

    if 2 <= drop_from_high <= 7:
        score += 20

    elif 1 <= drop_from_high < 2:
        score += 10

    elif 7 < drop_from_high <= 12:
        score += 12

    # --------------------------------------------------------
    # EMA20 ALTINA DÖNÜŞ
    # --------------------------------------------------------

    if current < ema20:
        score += 15

    elif current < ema20 * 1.01:
        score += 8

    # --------------------------------------------------------
    # EMA EĞİMİ
    # --------------------------------------------------------

    if ema20 < ema20_prev:
        score += 10

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if 55 <= rsi_now <= 72:
        score += 10

    elif 48 <= rsi_now < 55:
        score += 6

    # --------------------------------------------------------
    # SON MUM
    # --------------------------------------------------------

    last = candles[-1]

    if last["close"] < last["open"]:
        score += 8

    return {

        "score": min(score, 75),

        "rsi": rsi_now,

        "ema20": ema20,

        "pump": pump,

        "drop": drop_from_high,

        "swing_high": swing_high,

        "swing_low": swing_low
    }


# ============================================================
# 1H LONG
# ============================================================

def analyze_1h_long(candles):

    if len(candles) < 50:
        return None

    closes = [
        x["close"]
        for x in candles
    ]

    current = closes[-1]
    previous = closes[-2]

    ema20 = ema(
        closes,
        20
    )

    ema50 = ema(
        closes,
        50
    )

    ema20_prev = ema(
        closes[:-3],
        20
    )

    rsi_now = rsi(
        closes,
        14
    )

    if not all([
        ema20,
        ema50,
        ema20_prev,
        rsi_now
    ]):
        return None

    score = 0

    # EMA20
    if current >= ema20:
        score += 12

    elif current >= ema20 * 0.995:
        score += 8

    else:
        return None

    # EMA eğimi
    if ema20 >= ema20_prev:
        score += 8

    else:
        # Hafif yatay trendi tamamen eleme
        if ema20 >= ema20_prev * 0.998:
            score += 4
        else:
            return None

    # EMA50
    if current >= ema50:
        score += 6

    # RSI
    if 45 <= rsi_now <= 68:
        score += 10

    elif 40 <= rsi_now < 45:
        score += 6

    else:
        return None

    # Son mum
    if current > previous:
        score += 5

    return {

        "score": score,

        "rsi": rsi_now,

        "ema20": ema20,

        "ema50": ema50
    }


# ============================================================
# 1H SHORT
# ============================================================

def analyze_1h_short(candles):

    if len(candles) < 50:
        return None

    closes = [
        x["close"]
        for x in candles
    ]

    current = closes[-1]
    previous = closes[-2]

    ema20 = ema(
        closes,
        20
    )

    ema50 = ema(
        closes,
        50
    )

    ema20_prev = ema(
        closes[:-3],
        20
    )

    rsi_now = rsi(
        closes,
        14
    )

    if not all([
        ema20,
        ema50,
        ema20_prev,
        rsi_now
    ]):
        return None

    score = 0

    # EMA20 altı
    if current <= ema20:
        score += 12

    elif current <= ema20 * 1.005:
        score += 8

    else:
        return None

    # EMA eğimi aşağı
    if ema20 < ema20_prev:
        score += 10

    # EMA50
    if current < ema50:
        score += 5

    # RSI
    if 45 <= rsi_now <= 65:
        score += 10

    elif 65 < rsi_now <= 72:
        score += 7

    # Son mum kırmızı
    if current < previous:
        score += 8

    return {

        "score": score,

        "rsi": rsi_now,

        "ema20": ema20,

        "ema50": ema50
    }


# ============================================================
# 15M LONG
# ============================================================

def analyze_15m_long(candles):

    if len(candles) < 30:
        return None

    closes = [
        x["close"]
        for x in candles
    ]

    current = closes[-1]
    previous = closes[-2]

    ema20 = ema(
        closes,
        20
    )

    rsi_now = rsi(
        closes,
        14
    )

    vr = volume_ratio(
        candles
    )

    if not ema20 or not rsi_now:
        return None

    score = 0

    # EMA
    if current > ema20:
        score += 10

    elif current >= ema20 * 0.995:
        score += 6

    else:
        return None

    # RSI
    if 48 <= rsi_now <= 70:
        score += 8

    elif 44 <= rsi_now < 48:
        score += 5

    else:
        return None

    # Momentum
    if current > previous:
        score += 5

    # Hacim
    if vr >= 2.0:
        score += 7

    elif vr >= 1.5:
        score += 6

    elif vr >= 1.15:
        score += 4

    elif vr >= 0.80:
        score += 2

    return {

        "score": score,

        "rsi": rsi_now,

        "ema20": ema20,

        "volume_ratio": vr
    }


# ============================================================
# 15M SHORT
# ============================================================

def analyze_15m_short(candles):

    if len(candles) < 30:
        return None

    closes = [
        x["close"]
        for x in candles
    ]

    current = closes[-1]
    previous = closes[-2]

    ema20 = ema(
        closes,
        20
    )

    rsi_now = rsi(
        closes,
        14
    )

    vr = volume_ratio(
        candles
    )

    if not ema20 or not rsi_now:
        return None

    score = 0

    # EMA
    if current < ema20:
        score += 10

    elif current <= ema20 * 1.005:
        score += 6

    else:
        return None

    # RSI
    if 40 <= rsi_now <= 58:
        score += 8

    elif 58 < rsi_now <= 68:
        score += 5

    # Satış momentumu
    if current < previous:
        score += 6

    # Hacim
    if vr >= 2.0:
        score += 7

    elif vr >= 1.5:
        score += 6

    elif vr >= 1.15:
        score += 4

    elif vr >= 0.80:
        score += 2

    return {

        "score": score,

        "rsi": rsi_now,

        "ema20": ema20,

        "volume_ratio": vr
    }


# ============================================================
# COIN ANALİZİ
# ============================================================

def analyze_symbol(
    symbol,
    ticker
):

    try:

        change = ticker["change"]
        volume = ticker["volume"]
        price = ticker["price"]

        # ----------------------------------------------------
        # 24H
        # ----------------------------------------------------

        if volume < MIN_24H_VOLUME:
            return []

        if change < MIN_24H_CHANGE:
            return []

        if change > MAX_24H_CHANGE:
            return []

        # ----------------------------------------------------
        # KLINE
        # ----------------------------------------------------

        candles4 = get_klines(
            symbol,
            "Hour4"
        )

        if not candles4:
            return []

        candles1 = get_klines(
            symbol,
            "Min60"
        )

        if not candles1:
            return []

        candles15 = get_klines(
            symbol,
            "Min15"
        )

        if not candles15:
            return []

        results = []

        # ====================================================
        # LONG
        # ====================================================

        four_long = analyze_4h_long(
            candles4
        )

        if four_long:

            one_long = analyze_1h_long(
                candles1
            )

            if one_long:

                fifteen_long = analyze_15m_long(
                    candles15
                )

                if fifteen_long:

                    score = (
                        four_long["score"]
                        + one_long["score"]
                        + fifteen_long["score"]
                    )

                    # Bonus
                    if (
                        four_long["recovery"]
                        <= 5
                    ):
                        score += 5

                    if (
                        fifteen_long[
                            "volume_ratio"
                        ] >= 1.5
                    ):
                        score += 5

                    score = min(
                        score,
                        100
                    )

                    if score >= MIN_SCORE:

                        entry = price

                        results.append({

                            "type": "LONG",

                            "symbol": symbol,

                            "score": score,

                            "entry": entry,

                            "tp1": entry * (
                                1 + LONG_TP1 / 100
                            ),

                            "tp2": entry * (
                                1 + LONG_TP2 / 100
                            ),

                            "tp3": entry * (
                                1 + LONG_TP3 / 100
                            ),

                            "stop": entry * (
                                1 - LONG_STOP / 100
                            ),

                            "change": change,

                            "recovery": four_long[
                                "recovery"
                            ],

                            "volume_ratio": fifteen_long[
                                "volume_ratio"
                            ],

                            "rsi4": four_long[
                                "rsi"
                            ],

                            "rsi1": one_long[
                                "rsi"
                            ],

                            "rsi15": fifteen_long[
                                "rsi"
                            ]
                        })

        # ====================================================
        # SHORT
        # ====================================================

        four_short = analyze_4h_short(
            candles4
        )

        if four_short:

            one_short = analyze_1h_short(
                candles1
            )

            if one_short:

                fifteen_short = analyze_15m_short(
                    candles15
                )

                if fifteen_short:

                    score = (
                        four_short["score"]
                        + one_short["score"]
                        + fifteen_short["score"]
                    )

                    if (
                        four_short["drop"]
                        <= 7
                    ):
                        score += 5

                    if (
                        fifteen_short[
                            "volume_ratio"
                        ] >= 1.5
                    ):
                        score += 5

                    score = min(
                        score,
                        100
                    )

                    if score >= MIN_SCORE:

                        entry = price

                        results.append({

                            "type": "SHORT",

                            "symbol": symbol,

                            "score": score,

                            "entry": entry,

                            "tp1": entry * (
                                1 - SHORT_TP1 / 100
                            ),

                            "tp2": entry * (
                                1 - SHORT_TP2 / 100
                            ),

                            "tp3": entry * (
                                1 - SHORT_TP3 / 100
                            ),

                            "stop": entry * (
                                1 + SHORT_STOP / 100
                            ),

                            "change": change,

                            "pump": four_short[
                                "pump"
                            ],

                            "drop": four_short[
                                "drop"
                            ],

                            "volume_ratio": fifteen_short[
                                "volume_ratio"
                            ],

                            "rsi4": four_short[
                                "rsi"
                            ],

                            "rsi1": one_short[
                                "rsi"
                            ],

                            "rsi15": fifteen_short[
                                "rsi"
                            ]
                        })

        return results

    except Exception as e:

        print(
            symbol,
            "analiz:",
            e
        )

        return []


# ============================================================
# PRICE FORMAT
# ============================================================

def price_format(price):

    if price >= 100:
        return f"{price:.2f}"

    if price >= 1:
        return f"{price:.4f}"

    if price >= 0.01:
        return f"{price:.6f}"

    if price >= 0.0001:
        return f"{price:.8f}"

    return f"{price:.10f}"


# ============================================================
# TELEGRAM MESAJ
# ============================================================

def format_signal(x):

    symbol = x["symbol"]
    score = x["score"]

    if x["type"] == "LONG":

        title = "🟢 <b>ERKEN PUMP ADAYI</b>"

        extra = (
            f"📉 4H dipten dönüş: "
            f"+{x['recovery']:.2f}%\n"
        )

    else:

        title = "🔴 <b>PUMP SONRASI DÜŞÜŞ</b>"

        extra = (
            f"🚀 4H pump: +{x['pump']:.1f}%\n"
            f"📉 Tepeden düşüş: -{x['drop']:.2f}%\n"
        )

    return (

        f"{title}\n\n"

        f"💎 <b>{symbol}</b>\n"
        f"⭐ <b>Skor: {score}/100</b>\n\n"

        f"🟢 Giriş: "
        f"<b>{price_format(x['entry'])}</b>\n"

        f"🎯 TP1: "
        f"{price_format(x['tp1'])}\n"

        f"🎯 TP2: "
        f"{price_format(x['tp2'])}\n"

        f"🎯 TP3: "
        f"{price_format(x['tp3'])}\n"

        f"🛑 Stop: "
        f"{price_format(x['stop'])}\n\n"

        f"📊 24H: "
        f"{x['change']:+.2f}%\n"

        f"{extra}"

        f"⚡ 15M hacim: "
        f"{x['volume_ratio']:.2f}x\n\n"

        f"🔎 4H RSI: "
        f"{x['rsi4']:.1f}\n"

        f"🔎 1H RSI: "
        f"{x['rsi1']:.1f}\n"

        f"🔎 15M RSI: "
        f"{x['rsi15']:.1f}\n\n"

        (
            "📈 LONG senaryosu\n"
            if x["type"] == "LONG"
            else
            "📉 SHORT senaryosu\n"
        )

        "⚠️ <i>Analiz sinyalidir. "
        "Otomatik işlem açmaz.</i>"
    )


# ============================================================
# SENT
# ============================================================

def load_sent():

    try:

        if os.path.exists(
            SENT_FILE
        ):

            with open(
                SENT_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                return json.load(f)

    except Exception as e:

        print(
            "sent okuma:",
            e
        )

    return {}


def save_sent(data):

    try:

        with open(
            SENT_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print(
            "sent yazma:",
            e
        )


# ============================================================
# ANA TARAMA
# ============================================================

def scan():

    print("")
    print("=" * 65)
    print("🚀 MEXC CRYPTO FUTURES PUMP RADAR")
    print("=" * 65)

    # --------------------------------------------------------
    # FUTURES
    # --------------------------------------------------------

    symbols = get_futures_contracts()

    if not symbols:

        send_telegram(
            "🔴 <b>RADAR HATASI</b>\n\n"
            "MEXC Crypto Futures alınamadı."
        )

        return

    # --------------------------------------------------------
    # TICKER
    # --------------------------------------------------------

    tickers = get_futures_tickers()

    if not tickers:

        send_telegram(
            "🔴 <b>RADAR HATASI</b>\n\n"
            "Futures ticker alınamadı."
        )

        return

    # --------------------------------------------------------
    # 24H ÖN FİLTRE
    # --------------------------------------------------------

    filtered = []

    for symbol in symbols:

        ticker = tickers.get(
            symbol
        )

        if not ticker:
            continue

        volume = ticker[
            "volume"
        ]

        change = ticker[
            "change"
        ]

        if volume < MIN_24H_VOLUME:
            continue

        if change < MIN_24H_CHANGE:
            continue

        if change > MAX_24H_CHANGE:
            continue

        filtered.append(
            (
                symbol,
                ticker
            )
        )

    print(
        "24H filtre sonrası:",
        len(filtered)
    )

    # --------------------------------------------------------
    # ANALİZ
    # --------------------------------------------------------

    candidates = []

    completed = 0
    total = len(filtered)

    print("")
    print(
        "🔎 Detaylı tarama:",
        total
    )

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {}

        for symbol, ticker in filtered:

            future = executor.submit(
                analyze_symbol,
                symbol,
                ticker
            )

            futures[future] = symbol

        for future in as_completed(
            futures
        ):

            symbol = futures[
                future
            ]

            completed += 1

            try:

                results = future.result()

                if results:

                    for result in results:

                        candidates.append(
                            result
                        )

                        print(
                            "🔥 ADAY:",
                            result["type"],
                            symbol,
                            result["score"]
                        )

            except Exception as e:

                print(
                    symbol,
                    "future:",
                    e
                )

            if completed % 25 == 0:

                print(
                    "İlerleme:",
                    completed,
                    "/",
                    total
                )

    # --------------------------------------------------------
    # SIRALA
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    print("")
    print(
        "🔥 Toplam aday:",
        len(candidates)
    )

    # --------------------------------------------------------
    # ADAY YOK
    # --------------------------------------------------------

    if not candidates:

        print(
            "Bu taramada aday yok."
        )

        return

    # --------------------------------------------------------
    # DUPLICATE TEMİZLE
    # --------------------------------------------------------

    sent = load_sent()

    now = time.time()

    clean = {}

    for key, timestamp in sent.items():

        try:

            if (
                now
                - float(timestamp)
                < DUPLICATE_HOURS * 3600
            ):

                clean[key] = timestamp

        except Exception:
            pass

    sent = clean

    # --------------------------------------------------------
    # GÖNDER
    # --------------------------------------------------------

    sent_count = 0

    for candidate in candidates:

        if (
            sent_count
            >= MAX_SIGNALS_PER_SCAN
        ):
            break

        symbol = candidate[
            "symbol"
        ]

        signal_type = candidate[
            "type"
        ]

        # LONG ve SHORT ayrı tutulur
        key = (
            symbol
            + "_"
            + signal_type
        )

        if key in sent:

            print(
                "⏭ DUPLICATE:",
                key
            )

            continue

        message = format_signal(
            candidate
        )

        success = send_telegram(
            message
        )

        if success:

            sent[key] = now

            save_sent(
                sent
            )

            sent_count += 1

            print(
                "✅ GÖNDERİLDİ:",
                signal_type,
                symbol
            )

    # --------------------------------------------------------
    # SONUÇ
    # --------------------------------------------------------

    long_count = sum(
        1
        for x in candidates
        if x["type"] == "LONG"
    )

    short_count = sum(
        1
        for x in candidates
        if x["type"] == "SHORT"
    )

    print("")
    print(
        "🟢 LONG aday:",
        long_count
    )

    print(
        "🔴 SHORT aday:",
        short_count
    )

    print(
        "📨 Gönderilen:",
        sent_count
    )

    print("=" * 65)
    print("🏁 RADAR TAMAMLANDI")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print("")
    print("🚀 MEXC CRYPTO FUTURES RADAR")
    print("")

    if not BOT_TOKEN:

        print(
            "❌ TELEGRAM_BOT_TOKEN YOK"
        )

    if not CHAT_ID:

        print(
            "❌ TELEGRAM_CHAT_ID YOK"
        )

    if BOT_TOKEN and CHAT_ID:

        telegram_test()

    else:

        print(
            "❌ Telegram secretları eksik."
        )

    try:

        scan()

    except Exception as e:

        print(
            "🔴 ANA HATA:",
            e
        )

        send_telegram(
            "🔴 <b>RADAR ANA HATA</b>\n\n"
            f"<code>{str(e)[:500]}</code>"
        )

    print("")
    print("🏁 Program bitti.")
