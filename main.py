import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# MEXC PUMP RADAR
# 4H DIP + 1H TREND + 15M CONFIRMATION
# TELEGRAM
# ============================================================

BASE = "https://api.mexc.com"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SCAN_INTERVAL = 300
MAX_WORKERS = 10

# Güçlü sinyal için minimum puan
MIN_SCORE = 78

# Minimum 24H hacim
MIN_24H_VOLUME = 500000

# 24H değişim çok kötü ise ele
MIN_24H_CHANGE = -12

# Bir taramada maksimum sinyal
MAX_SIGNALS_PER_SCAN = 5

# Aynı coin tekrar gönderilmeden önce
DUPLICATE_TIME = 6 * 60 * 60

# TP
TP1_PCT = 0.018
TP2_PCT = 0.035
TP3_PCT = 0.055

# Stop
STOP_PCT = 0.022

STATE_FILE = "sent_signals.json"


# ============================================================
# SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "Mozilla/5.0"
})


# ============================================================
# HTTP GET
# ============================================================

def get(url, params=None, timeout=10):

    try:

        response = SESSION.get(
            url,
            params=params,
            timeout=timeout
        )

        if response.status_code != 200:
            return None

        return response.json()

    except Exception as e:

        print("GET ERROR:", e)

        return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_TOKEN:
        print("TELEGRAM_BOT_TOKEN bulunamadı.")
        return False

    if not CHAT_ID:
        print("TELEGRAM_CHAT_ID bulunamadı.")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:

        response = SESSION.post(
            url,
            json=payload,
            timeout=10
        )

        if response.status_code == 200:
            return True

        print(
            "Telegram hata:",
            response.text
        )

        return False

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

        if not os.path.exists(STATE_FILE):
            return {}

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:
        return {}


def save_state(state):

    try:

        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                state,
                f,
                indent=2
            )

    except Exception as e:

        print(
            "State kayıt hatası:",
            e
        )


def clean_state(state):

    now = int(time.time())

    delete_list = []

    for symbol, timestamp in state.items():

        if now - timestamp > 86400:
            delete_list.append(symbol)

    for symbol in delete_list:
        del state[symbol]


# ============================================================
# CONTRACT LIST
# ============================================================

def get_contracts():

    data = get(
        f"{BASE}/api/v1/contract/detail"
    )

    if not data:
        return []

    if isinstance(data, dict):
        data = data.get("data", [])

    result = []

    for item in data:

        try:

            symbol = item.get(
                "symbol",
                ""
            )

            quote_coin = item.get(
                "quoteCoin",
                ""
            )

            state = item.get(
                "state",
                0
            )

            if quote_coin != "USDT":
                continue

            if state != 0:
                continue

            if not symbol.endswith("_USDT"):
                continue

            result.append(symbol)

        except Exception:
            continue

    return result


# ============================================================
# TICKER
# ============================================================

def get_ticker(symbol):

    data = get(
        f"{BASE}/api/v1/contract/ticker",
        {
            "symbol": symbol
        }
    )

    if not data:
        return None

    if isinstance(data, dict):
        return data.get("data")

    return data


# ============================================================
# KLINE
# ============================================================

def get_klines(
    symbol,
    interval,
    limit=120
):

    data = get(
        f"{BASE}/api/v1/contract/kline/{symbol}",
        {
            "interval": interval,
            "limit": limit
        }
    )

    if not data:
        return []

    if isinstance(data, dict):
        data = data.get("data")

    if not isinstance(data, dict):
        return []

    try:

        times = data.get(
            "time",
            []
        )

        opens = data.get(
            "open",
            []
        )

        highs = data.get(
            "high",
            []
        )

        lows = data.get(
            "low",
            []
        )

        closes = data.get(
            "close",
            []
        )

        volumes = data.get(
            "vol",
            []
        )

        length = min(
            len(times),
            len(opens),
            len(highs),
            len(lows),
            len(closes),
            len(volumes)
        )

        candles = []

        for i in range(length):

            candles.append({

                "time": float(times[i]),

                "open": float(opens[i]),

                "high": float(highs[i]),

                "low": float(lows[i]),

                "close": float(closes[i]),

                "volume": float(volumes[i])

            })

        return candles

    except Exception:

        return []


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (
        period + 1
    )

    result = sum(
        values[:period]
    ) / period

    for value in values[period:]:

        result = (
            (value - result)
            * multiplier
        ) + result

    return result


# ============================================================
# RSI
# ============================================================

def rsi(values, period=14):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = (
            values[i]
            - values[i - 1]
        )

        if change > 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(abs(change))

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
# ATR
# ============================================================

def atr(candles, period=14):

    if len(candles) < period + 1:
        return None

    true_ranges = []

    for i in range(
        1,
        len(candles)
    ):

        current = candles[i]
        previous = candles[i - 1]

        tr = max(

            current["high"]
            - current["low"],

            abs(
                current["high"]
                - previous["close"]
            ),

            abs(
                current["low"]
                - previous["close"]
            )

        )

        true_ranges.append(tr)

    return (
        sum(
            true_ranges[-period:]
        )
        / period
    )


# ============================================================
# AVERAGE VOLUME
# ============================================================

def average_volume(
    candles,
    period=20
):

    if len(candles) < period:
        return 0

    return (
        sum(
            candle["volume"]
            for candle
            in candles[-period:]
        )
        / period
    )


# ============================================================
# CANDLE STRENGTH
# ============================================================

def candle_strength(candle):

    high = candle["high"]
    low = candle["low"]
    open_price = candle["open"]
    close = candle["close"]

    candle_range = high - low

    if candle_range <= 0:
        return 0

    body = abs(
        close - open_price
    )

    upper_wick = (
        high
        - max(
            open_price,
            close
        )
    )

    lower_wick = (
        min(
            open_price,
            close
        )
        - low
    )

    score = 0

    # Yeşil mum
    if close > open_price:
        score += 2

    # Gövde güçlü
    if (
        body / candle_range
        > 0.45
    ):
        score += 2

    # Alt fitil
    if (
        lower_wick / candle_range
        > 0.25
    ):
        score += 2

    # Kapanış üst bölgede
    if (
        close
        >= low
        + candle_range * 0.65
    ):
        score += 2

    # Üst fitil kısa
    if (
        upper_wick / candle_range
        < 0.30
    ):
        score += 1

    return score


# ============================================================
# 4H ANALYSIS
# ============================================================

def analyze_4h(candles):

    if len(candles) < 60:
        return None

    closes = [
        x["close"]
        for x in candles
    ]

    current = closes[-1]

    low_30 = min(
        x["low"]
        for x in candles[-30:]
    )

    high_30 = max(
        x["high"]
        for x in candles[-30:]
    )

    price_range = (
        high_30 - low_30
    )

    if price_range <= 0:
        return None

    position = (
        current - low_30
    ) / price_range

    ema20 = ema(
        closes,
        20
    )

    ema50 = ema(
        closes,
        50
    )

    current_rsi = rsi(
        closes,
        14
    )

    recent_high = max(
        x["high"]
        for x in candles[-15:]
    )

    drawdown = (
        (
            recent_high
            - current
        )
        / recent_high
    ) * 100

    score = 0
    reasons = []

    # ----------------------------------------
    # DIP
    # ----------------------------------------

    if position <= 0.35:

        score += 20
        reasons.append(
            "4H dip bölgesi"
        )

    elif position <= 0.48:

        score += 12
        reasons.append(
            "4H düşük bölge"
        )

    # ----------------------------------------
    # RSI
    # ----------------------------------------

    if current_rsi is not None:

        if (
            32
            <= current_rsi
            <= 45
        ):

            score += 15
            reasons.append(
                "RSI toparlanıyor"
            )

        elif (
            25
            <= current_rsi
            < 32
        ):

            score += 8
            reasons.append(
                "RSI aşırı düşük"
            )

    # ----------------------------------------
    # EMA
    # ----------------------------------------

    if ema20 and ema50:

        if current > ema20:

            score += 10
            reasons.append(
                "EMA20 üstü"
            )

        elif current > ema50:

            score += 6
            reasons.append(
                "EMA50 üstü"
            )

    # ----------------------------------------
    # GERİ ÇEKİLME
    # ----------------------------------------

    if drawdown >= 8:

        score += 8
        reasons.append(
            "sert geri çekilme"
        )

    # ----------------------------------------
    # MUM
    # ----------------------------------------

    score += (
        candle_strength(
            candles[-1]
        )
        * 2
    )

    return {

        "score": score,

        "rsi": current_rsi,

        "position": position,

        "drawdown": drawdown,

        "reasons": reasons

    }


# ============================================================
# 1H ANALYSIS
# ============================================================

def analyze_1h(candles):

    if len(candles) < 60:
        return None

    closes = [
        x["close"]
        for x in candles
    ]

    current = closes[-1]

    ema9 = ema(
        closes,
        9
    )

    ema21 = ema(
        closes,
        21
    )

    ema50 = ema(
        closes,
        50
    )

    current_rsi = rsi(
        closes,
        14
    )

    score = 0
    reasons = []

    # Trend
    if ema9 and ema21:

        if ema9 > ema21:

            score += 15
            reasons.append(
                "1H trend yukarı"
            )

        elif current > ema21:

            score += 8
            reasons.append(
                "1H EMA21 üstü"
            )

    # EMA50
    if (
        ema50
        and current > ema50
    ):

        score += 8
        reasons.append(
            "1H EMA50 üstü"
        )

    # RSI
    if current_rsi is not None:

        if (
            48
            <= current_rsi
            <= 68
        ):

            score += 10
            reasons.append(
                "1H RSI güçlü"
            )

        elif current_rsi > 70:

            score -= 5

    # Momentum
    if (
        len(closes) >= 5
        and closes[-1] > closes[-5]
    ):

        score += 5
        reasons.append(
            "1H momentum pozitif"
        )

    return {

        "score": score,

        "rsi": current_rsi,

        "reasons": reasons

    }


# ============================================================
# 15M ANALYSIS
# ============================================================

def analyze_15m(candles):

    if len(candles) < 50:
        return None

    closes = [
        x["close"]
        for x in candles
    ]

    current = closes[-1]

    ema9 = ema(
        closes,
        9
    )

    ema21 = ema(
        closes,
        21
    )

    current_rsi = rsi(
        closes,
        14
    )

    avg_volume = average_volume(
        candles,
        20
    )

    current_volume = (
        candles[-1]["volume"]
    )

    score = 0
    reasons = []

    # ----------------------------------------
    # EMA
    # ----------------------------------------

    if ema9 and ema21:

        if ema9 > ema21:

            score += 12
            reasons.append(
                "15M EMA yukarı"
            )

        if current > ema9:

            score += 6
            reasons.append(
                "15M EMA9 üstü"
            )

    # ----------------------------------------
    # RSI
    # ----------------------------------------

    if current_rsi is not None:

        if (
            50
            <= current_rsi
            <= 70
        ):

            score += 10
            reasons.append(
                "15M RSI teyit"
            )

        elif (
            45
            <= current_rsi
            < 50
        ):

            score += 5

    # ----------------------------------------
    # HACİM
    # ----------------------------------------

    if avg_volume > 0:

        volume_ratio = (
            current_volume
            / avg_volume
        )

        if volume_ratio >= 1.5:

            score += 12
            reasons.append(
                "hacim patlaması"
            )

        elif volume_ratio >= 1.15:

            score += 7
            reasons.append(
                "hacim teyidi"
            )

    else:

        volume_ratio = 0

    # ----------------------------------------
    # MUM
    # ----------------------------------------

    score += (
        candle_strength(
            candles[-1]
        )
        * 2
    )

    return {

        "score": score,

        "rsi": current_rsi,

        "volume_ratio": volume_ratio,

        "reasons": reasons

    }


# ============================================================
# LEVELS
# ============================================================

def calculate_levels(
    candles,
    entry
):

    recent_low = min(
        x["low"]
        for x in candles[-20:]
    )

    current_atr = atr(
        candles,
        14
    )

    if current_atr is None:

        current_atr = (
            entry * 0.01
        )

    atr_stop = (
        entry
        - current_atr * 1.5
    )

    percentage_stop = (
        entry
        * (1 - STOP_PCT)
    )

    stop = max(

        recent_low * 0.995,

        atr_stop,

        percentage_stop

    )

    if stop >= entry:

        stop = (
            entry
            * 0.978
        )

    tp1 = (
        entry
        * (1 + TP1_PCT)
    )

    tp2 = (
        entry
        * (1 + TP2_PCT)
    )

    tp3 = (
        entry
        * (1 + TP3_PCT)
    )

    return (
        stop,
        tp1,
        tp2,
        tp3
    )


# ============================================================
# SYMBOL ANALYSIS
# ============================================================

def analyze_symbol(symbol):

    try:

        ticker = get_ticker(
            symbol
        )

        if not ticker:
            return None

        price = float(
            ticker.get(
                "lastPrice",
                0
            )
        )

        volume24 = float(
            ticker.get(
                "amount24",
                0
            )
            or ticker.get(
                "volume24",
                0
            )
            or 0
        )

        change24 = float(
            ticker.get(
                "riseFallRate",
                0
            )
            or 0
        ) * 100

        if price <= 0:
            return None

        if volume24 < MIN_24H_VOLUME:
            return None

        if change24 < MIN_24H_CHANGE:
            return None

        # ================================================
        # 4H
        # ================================================

        candles_4h = get_klines(
            symbol,
            "Hour4",
            100
        )

        # ================================================
        # 1H
        # ================================================

        candles_1h = get_klines(
            symbol,
            "Min60",
            100
        )

        # ================================================
        # 15M
        # ================================================

        candles_15m = get_klines(
            symbol,
            "Min15",
            100
        )

        if (
            len(candles_4h) < 60
            or len(candles_1h) < 60
            or len(candles_15m) < 60
        ):

            return None

        analysis_4h = analyze_4h(
            candles_4h
        )

        analysis_1h = analyze_1h(
            candles_1h
        )

        analysis_15m = analyze_15m(
            candles_15m
        )

        if (
            not analysis_4h
            or not analysis_1h
            or not analysis_15m
        ):

            return None

        total_score = (

            analysis_4h["score"]

            + analysis_1h["score"]

            + analysis_15m["score"]

        )

        # ================================================
        # GÜÇLÜ TEYİT
        # ================================================

        if analysis_4h["score"] < 20:
            return None

        if analysis_1h["score"] < 15:
            return None

        if analysis_15m["score"] < 15:
            return None

        if total_score < MIN_SCORE:
            return None

        # ================================================
        # LEVELS
        # ================================================

        entry = price

        stop, tp1, tp2, tp3 = (
            calculate_levels(
                candles_15m,
                entry
            )
        )

        risk = entry - stop

        if risk <= 0:
            return None

        risk_pct = (
            risk
            / entry
        ) * 100

        # Stop %5'ten fazla ise alma
        if risk_pct > 5:
            return None

        reasons = []

        reasons.extend(
            analysis_4h["reasons"]
        )

        reasons.extend(
            analysis_1h["reasons"]
        )

        reasons.extend(
            analysis_15m["reasons"]
        )

        return {

            "symbol": symbol,

            "price": entry,

            "score": total_score,

            "stop": stop,

            "tp1": tp1,

            "tp2": tp2,

            "tp3": tp3,

            "risk_pct": risk_pct,

            "change24": change24,

            "volume24": volume24,

            "reasons": reasons[:6]

        }

    except Exception as e:

        print(
            symbol,
            "analiz hatası:",
            e
        )

        return None


# ============================================================
# PRICE FORMAT
# ============================================================

def format_price(price):

    if price >= 1000:
        return f"{price:.2f}"

    if price >= 1:
        return f"{price:.4f}"

    if price >= 0.01:
        return f"{price:.6f}"

    if price >= 0.0001:
        return f"{price:.8f}"

    return f"{price:.10f}"


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

def format_signal(result):

    symbol = result["symbol"].replace(
        "_USDT",
        ""
    )

    reasons = ", ".join(
        result["reasons"][:4]
    )

    return f"""
🚨 <b>GÜÇLÜ PUMP ADAYI</b>

🪙 <b>{symbol}/USDT</b>
⭐ Skor: <b>{result["score"]}</b>

🟢 Giriş
<b>{format_price(result["price"])}</b>

🎯 TP1
<b>{format_price(result["tp1"])}</b>

🎯 TP2
<b>{format_price(result["tp2"])}</b>

🎯 TP3
<b>{format_price(result["tp3"])}</b>

🛑 Stop
<b>{format_price(result["stop"])}</b>

📊 24H: {result["change24"]:+.2f}%
⚡ Risk: %{result["risk_pct"]:.2f}

🔎 {reasons}

⚠️ <i>Analiz sinyalidir, otomatik işlem açmaz.</i>
""".strip()


# ============================================================
# DUPLICATE CONTROL
# ============================================================

def can_send(
    state,
    symbol
):

    now = int(
        time.time()
    )

    last_time = state.get(
        symbol,
        0
    )

    if (
        now - last_time
        < DUPLICATE_TIME
    ):

        return False

    return True


# ============================================================
# SCAN
# ============================================================

def scan():

    print("")
    print(
        "=========================================="
    )
    print(
        "        MEXC PUMP RADAR BAŞLADI"
    )
    print(
        "=========================================="
    )

    contracts = get_contracts()

    if not contracts:

        print(
            "MEXC coin listesi alınamadı."
        )

        return

    print(
        f"Toplam {len(contracts)} coin taranıyor..."
    )

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {}

        for symbol in contracts:

            future = executor.submit(
                analyze_symbol,
                symbol
            )

            futures[future] = symbol

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                if result:

                    results.append(
                        result
                    )

            except Exception as e:

                print(
                    "Thread hata:",
                    e
                )

    # En yüksek skordan düşüğe
    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    print(
        f"Güçlü aday sayısı: {len(results)}"
    )

    state = load_state()

    clean_state(
        state
    )

    sent_count = 0

    for result in results:

        if (
            sent_count
            >= MAX_SIGNALS_PER_SCAN
        ):

            break

        symbol = result["symbol"]

        if not can_send(
            state,
            symbol
        ):

            continue

        message = format_signal(
            result
        )

        print(
            f"Sinyal -> "
            f"{symbol} | "
            f"Skor: "
            f"{result['score']}"
        )

        if send_telegram(
            message
        ):

            state[
                symbol
            ] = int(
                time.time()
            )

            save_state(
                state
            )

            sent_count += 1

            time.sleep(1)

    print(
        f"Bu taramada gönderilen: "
        f"{sent_count}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "MEXC PUMP RADAR"
    )

    if not TELEGRAM_TOKEN:

        print(
            "UYARI: "
            "TELEGRAM_BOT_TOKEN eksik."
        )

    if not CHAT_ID:

        print(
            "UYARI: "
            "TELEGRAM_CHAT_ID eksik."
        )

    while True:

        try:

            scan()

        except Exception as e:

            print(
                "ANA HATA:",
                e
            )

        print("")
        print(
            "Sonraki tarama "
            f"{SCAN_INTERVAL // 60} "
            "dakika sonra..."
        )

        time.sleep(
            SCAN_INTERVAL
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
