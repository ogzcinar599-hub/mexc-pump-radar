import os
import time
import json
import math
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PUMP RADAR 8.0
#
# AMAÇ:
# Pump başlamadan önce güçlü hareketleri yakalamak
#
# TELEGRAM:
# SADECE GÜÇLÜ AL SİNYALİ GÖNDERİR
#
# ❌ Sistem aktif mesajı yok
# ❌ Tarama tamamlandı mesajı yok
# ❌ İzleme adayı mesajı yok
# ❌ Pump sonrası mesajı yok
# ❌ Ters trend mesajı yok
#
# ✅ Sadece güçlü sinyal
# ============================================================


BASE = "https://contract.mexc.com"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

STATE_FILE = "signal_history.json"


# ============================================================
# AYARLAR
# ============================================================

MAX_WORKERS = 12

MIN_SCORE = 85

# Aynı coin tekrar gönderilmesin
SIGNAL_COOLDOWN = 6 * 60 * 60

# 24 saatlik aşırı pump filtresi
MAX_24H_PUMP = 12.0

# 1 saat aşırı yükselmişse pump sonrası kabul et
MAX_1H_PUMP = 5.0

# 15 dakikada çok sert yükselmişse geç kalınmış kabul et
MAX_15M_PUMP = 3.5

# Hacim çarpanı
MIN_VOLUME_RATIO = 1.35

# RSI sınırları
MIN_RSI_15 = 48
MAX_RSI_15 = 72

MIN_RSI_1H = 48
MAX_RSI_1H = 72

# Minimum likidite
MIN_24H_VOLUME = 100000


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
})


# ============================================================
# GENEL HTTP
# ============================================================

def get_json(url, params=None, timeout=15):

    try:

        r = session.get(
            url,
            params=params,
            timeout=timeout
        )

        if r.status_code != 200:
            return None

        data = r.json()

        return data

    except Exception:
        return None


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(text):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram bilgileri yok.")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:

        r = session.post(
            url,
            data=payload,
            timeout=15
        )

        if r.status_code == 200:
            return True

        print("Telegram hata:", r.text[:300])

    except Exception as e:

        print("Telegram bağlantı hatası:", e)

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
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print("State kayıt hatası:", e)


# ============================================================
# MEXC FUTURES KONTRATLARI
# ============================================================

def get_contracts():

    data = get_json(
        f"{BASE}/api/v1/contract/detail"
    )

    if not data:
        return []

    rows = data.get("data", [])

    result = []

    for x in rows:

        try:

            symbol = str(
                x.get("symbol", "")
            ).upper()

            quote = str(
                x.get("quoteCoin", "")
            ).upper()

            settle = str(
                x.get("settleCoin", "")
            ).upper()

            state = x.get("state", 0)

            # ------------------------------------------------
            # SADECE USDT FUTURES
            # ------------------------------------------------

            if quote != "USDT":
                continue

            if settle != "USDT":
                continue

            if not symbol.endswith("_USDT"):
                continue

            # Aktif kontrat
            if state not in [0, 1, None]:
                continue

            result.append(symbol)

        except Exception:
            continue

    return result


# ============================================================
# TICKER
# ============================================================

def get_ticker(symbol):

    data = get_json(
        f"{BASE}/api/v1/contract/ticker",
        params={
            "symbol": symbol
        }
    )

    if not data:
        return None

    d = data.get("data")

    if not isinstance(d, dict):
        return None

    try:

        last = float(d.get("lastPrice", 0))
        rise = float(d.get("riseRate", 0))
        volume = float(d.get("volume24", 0))

        if last <= 0:
            return None

        # riseRate bazı cevaplarda oran olabilir
        # örnek 0.0515 = +5.15%
        if abs(rise) < 1:
            rise *= 100

        return {
            "price": last,
            "change24": rise,
            "volume24": volume
        }

    except Exception:
        return None


# ============================================================
# KLINE
# ============================================================

def get_klines(symbol, interval="Min15", limit=120):

    data = get_json(
        f"{BASE}/api/v1/contract/kline/{symbol}",
        params={
            "interval": interval
        }
    )

    if not data:
        return []

    d = data.get("data")

    if not isinstance(d, dict):
        return []

    try:

        times = d.get("time", [])
        opens = d.get("open", [])
        highs = d.get("high", [])
        lows = d.get("low", [])
        closes = d.get("close", [])
        vols = d.get("vol", [])

        rows = []

        n = min(
            len(times),
            len(opens),
            len(highs),
            len(lows),
            len(closes),
            len(vols)
        )

        for i in range(max(0, n - limit), n):

            rows.append({
                "time": float(times[i]),
                "open": float(opens[i]),
                "high": float(highs[i]),
                "low": float(lows[i]),
                "close": float(closes[i]),
                "volume": float(vols[i])
            })

        return rows

    except Exception:
        return []


# ============================================================
# RSI
# ============================================================

def calculate_rsi(values, period=14):

    if len(values) < period + 2:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        diff = values[i] - values[i - 1]

        if diff > 0:
            gains.append(diff)
            losses.append(0)

        else:
            gains.append(0)
            losses.append(abs(diff))

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
        return 100

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# CHANGE
# ============================================================

def percent_change(klines, candles):

    if len(klines) < candles + 1:
        return 0

    old = klines[-candles - 1]["close"]
    new = klines[-1]["close"]

    if old <= 0:
        return 0

    return (
        (new - old) / old
    ) * 100


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        result = (
            (price - result)
            * multiplier
        ) + result

    return result


# ============================================================
# ATR
# ============================================================

def calculate_atr(klines, period=14):

    if len(klines) < period + 2:
        return None

    trs = []

    for i in range(1, len(klines)):

        high = klines[i]["high"]
        low = klines[i]["low"]
        prev = klines[i - 1]["close"]

        tr = max(
            high - low,
            abs(high - prev),
            abs(low - prev)
        )

        trs.append(tr)

    if len(trs) < period:
        return None

    return sum(
        trs[-period:]
    ) / period


# ============================================================
# VOLUME RATIO
# ============================================================

def volume_ratio(klines):

    if len(klines) < 25:
        return 0

    current = klines[-1]["volume"]

    previous = [
        x["volume"]
        for x in klines[-21:-1]
    ]

    if not previous:
        return 0

    avg = sum(previous) / len(previous)

    if avg <= 0:
        return 0

    return current / avg


# ============================================================
# HIGHER LOW
# ============================================================

def higher_low(klines):

    if len(klines) < 15:
        return False

    lows = [
        x["low"]
        for x in klines[-12:]
    ]

    # Son dip
    recent_low = min(
        lows[-5:]
    )

    # Önceki dip
    previous_low = min(
        lows[:7]
    )

    return recent_low > previous_low


# ============================================================
# 1H HIGHER LOW
# ============================================================

def one_hour_higher_low(klines):

    if len(klines) < 15:
        return False

    lows = [
        x["low"]
        for x in klines[-12:]
    ]

    recent = min(
        lows[-5:]
    )

    previous = min(
        lows[:7]
    )

    return recent > previous


# ============================================================
# DİRENÇ
# ============================================================

def resistance_level(klines):

    if len(klines) < 25:
        return None

    # Son mum hariç önceki 20 mum
    highs = [
        x["high"]
        for x in klines[-21:-1]
    ]

    if not highs:
        return None

    return max(highs)


# ============================================================
# DİRENÇ KIRILIMI
# ============================================================

def breakout(klines):

    if len(klines) < 25:
        return False, None

    resistance = resistance_level(
        klines
    )

    if resistance is None:
        return False, None

    close = klines[-1]["close"]

    # %0.15 üzeri kırılım
    broken = (
        close >
        resistance * 1.0015
    )

    return broken, resistance


# ============================================================
# SIKIŞMA
# ============================================================

def compression(klines):

    if len(klines) < 25:
        return False

    ranges = []

    for x in klines[-20:]:

        if x["close"] <= 0:
            continue

        ranges.append(
            (
                x["high"] -
                x["low"]
            ) / x["close"] * 100
        )

    if len(ranges) < 10:
        return False

    avg = sum(ranges) / len(ranges)

    recent = sum(
        ranges[-5:]
    ) / 5

    return recent < avg * 0.80


# ============================================================
# TEK COIN ANALİZİ
# ============================================================

def analyze_symbol(symbol):

    ticker = get_ticker(symbol)

    if not ticker:
        return None

    price = ticker["price"]

    change24 = ticker["change24"]

    volume24 = ticker["volume24"]

    # --------------------------------------------------------
    # 24H ÖN FİLTRE
    # --------------------------------------------------------

    if volume24 < MIN_24H_VOLUME:
        return None

    # Pump'ı çoktan yapmış coin
    if change24 > MAX_24H_PUMP:
        return None

    # --------------------------------------------------------
    # KLINE
    # --------------------------------------------------------

    k15 = get_klines(
        symbol,
        "Min15",
        100
    )

    k1h = get_klines(
        symbol,
        "Min60",
        100
    )

    k4h = get_klines(
        symbol,
        "Hour4",
        80
    )

    if (
        len(k15) < 40
        or len(k1h) < 40
        or len(k4h) < 30
    ):
        return None

    # --------------------------------------------------------
    # DEĞİŞİMLER
    # --------------------------------------------------------

    change15 = percent_change(
        k15,
        1
    )

    change1h = percent_change(
        k1h,
        1
    )

    # Pump sonrası filtre
    if change1h > MAX_1H_PUMP:
        return None

    if change15 > MAX_15M_PUMP:
        return None

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    closes15 = [
        x["close"]
        for x in k15
    ]

    closes1h = [
        x["close"]
        for x in k1h
    ]

    closes4h = [
        x["close"]
        for x in k4h
    ]

    rsi15 = calculate_rsi(
        closes15
    )

    rsi1h = calculate_rsi(
        closes1h
    )

    rsi4h = calculate_rsi(
        closes4h
    )

    if (
        rsi15 is None
        or rsi1h is None
        or rsi4h is None
    ):
        return None

    # Çok zayıf
    if rsi15 < MIN_RSI_15:
        return None

    if rsi1h < MIN_RSI_1H:
        return None

    # Aşırı alınmış
    if rsi15 > MAX_RSI_15:
        return None

    if rsi1h > MAX_RSI_1H:
        return None

    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    vr = volume_ratio(
        k15
    )

    if vr < MIN_VOLUME_RATIO:
        return None

    # --------------------------------------------------------
    # HIGHER LOW
    # --------------------------------------------------------

    hl15 = higher_low(
        k15
    )

    hl1h = one_hour_higher_low(
        k1h
    )

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    is_breakout, resistance = breakout(
        k15
    )

    # --------------------------------------------------------
    # EMA TREND
    # --------------------------------------------------------

    ema20_1h = ema(
        closes1h,
        20
    )

    ema50_1h = ema(
        closes1h,
        50
    )

    trend1h = False

    if (
        ema20_1h
        and ema50_1h
        and price > ema20_1h
        and ema20_1h > ema50_1h
    ):
        trend1h = True

    # 4H trend
    ema20_4h = ema(
        closes4h,
        20
    )

    trend4h = False

    if (
        ema20_4h
        and price > ema20_4h
    ):
        trend4h = True

    # --------------------------------------------------------
    # SIKIŞMA
    # --------------------------------------------------------

    squeeze = compression(
        k15
    )

    # --------------------------------------------------------
    # SKOR
    # --------------------------------------------------------

    score = 0

    reasons = []

    # 15M momentum
    if change15 > 0:
        score += 10
        reasons.append(
            "15M MOMENTUM"
        )

    # 1H trend
    if trend1h:
        score += 15
        reasons.append(
            "1H TREND"
        )

    # 4H trend
    if trend4h:
        score += 10
        reasons.append(
            "4H TREND"
        )

    # Higher low
    if hl15:
        score += 12
        reasons.append(
            "HIGHER LOW"
        )

    # 1H higher low
    if hl1h:
        score += 10
        reasons.append(
            "1H HIGHER LOW"
        )

    # Hacim
    if vr >= 1.35:
        score += 15
        reasons.append(
            "HACİM"
        )

    if vr >= 1.70:
        score += 5

    # Breakout
    if is_breakout:
        score += 18
        reasons.append(
            "DİRENÇ KIRILIMI"
        )

    # Sıkışma
    if squeeze:
        score += 8
        reasons.append(
            "SIKIŞMA"
        )

    # RSI sağlıklı bölgede
    if (
        52 <= rsi15 <= 68
        and 52 <= rsi1h <= 68
    ):
        score += 7
        reasons.append(
            "RSI TEYİDİ"
        )

    # 15M yükseliş
    if 0 < change15 <= 2.5:
        score += 5

    # --------------------------------------------------------
    # GÜÇLÜ SİNYAL
    # --------------------------------------------------------

    if score < MIN_SCORE:
        return None

    # En az 2 ana yapısal teyit
    structure_count = sum([
        hl15,
        hl1h,
        trend1h,
        is_breakout
    ])

    if structure_count < 2:
        return None

    # --------------------------------------------------------
    # STOP / TP
    # --------------------------------------------------------

    atr = calculate_atr(
        k15,
        14
    )

    if not atr or atr <= 0:
        return None

    # ATR tabanlı stop
    stop = price - (
        atr * 1.35
    )

    risk = price - stop

    if risk <= 0:
        return None

    tp1 = price + (
        risk * 1.0
    )

    tp2 = price + (
        risk * 1.8
    )

    tp3 = price + (
        risk * 2.6
    )

    # --------------------------------------------------------
    # SİNYAL TİPİ
    # --------------------------------------------------------

    if is_breakout:
        signal_type = "🔥 DİRENÇ KIRILIMI"

    elif hl15 and hl1h and vr >= 1.5:
        signal_type = "🚀 PUMP ÖNCESİ GÜÇLENME"

    else:
        signal_type = "⚡ ERKEN MOMENTUM"

    return {
        "symbol": symbol,
        "score": score,
        "price": price,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "stop": stop,
        "change24": change24,
        "change1h": change1h,
        "change15": change15,
        "volume_ratio": vr,
        "rsi15": rsi15,
        "rsi1h": rsi1h,
        "rsi4h": rsi4h,
        "resistance": resistance,
        "higher_low": hl15,
        "higher_low_1h": hl1h,
        "breakout": is_breakout,
        "squeeze": squeeze,
        "signal_type": signal_type,
        "reasons": reasons
    }


# ============================================================
# FİYAT FORMAT
# ============================================================

def format_price(price):

    if price >= 100:
        return f"{price:.2f}"

    if price >= 1:
        return f"{price:.5f}"

    if price >= 0.01:
        return f"{price:.6f}"

    if price >= 0.0001:
        return f"{price:.8f}"

    return f"{price:.10f}"


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def build_message(x):

    symbol = x["symbol"]

    score = x["score"]

    price = x["price"]

    tp1 = x["tp1"]

    tp2 = x["tp2"]

    tp3 = x["tp3"]

    stop = x["stop"]

    return f"""
🚀 <b>PUMP RADAR AL</b>

💎 <b>{symbol}</b>
⭐ <b>Skor: {score}/100</b>

📌 <b>{x["signal_type"]}</b>

🟢 Giriş: <b>{format_price(price)}</b>

🎯 TP1: <b>{format_price(tp1)}</b>
🎯 TP2: <b>{format_price(tp2)}</b>
🎯 TP3: <b>{format_price(tp3)}</b>

🛑 Stop: <b>{format_price(stop)}</b>

📊 24H: {x["change24"]:+.2f}%
⚡ 1H: {x["change1h"]:+.2f}%
🔥 15M: {x["change15"]:+.2f}%
💥 Hacim: <b>{x["volume_ratio"]:.2f}x</b>

📈 RSI 15M: {x["rsi15"]:.1f}
📈 RSI 1H: {x["rsi1h"]:.1f}
📊 RSI 4H: {x["rsi4h"]:.1f}

🔑 Direnç:
<b>{format_price(x["resistance"]) if x["resistance"] else "-"}</b>

📈 Higher Low: {"✅" if x["higher_low"] else "❌"}
📈 1H Higher Low: {"✅" if x["higher_low_1h"] else "❌"}
🔥 Hacim teyidi: {"✅" if x["volume_ratio"] >= 1.35 else "❌"}
💥 Direnç kırılımı: {"✅" if x["breakout"] else "❌"}

💎 <b>MEXC USDT FUTURES</b>

⚠️ <i>Teknik filtrelerden geçen erken hareket sinyalidir.</i>
"""


# ============================================================
# COOLDOWN
# ============================================================

def can_send(symbol, state):

    now = time.time()

    old = state.get(
        symbol
    )

    if old is None:
        return True

    try:

        last_time = float(
            old
        )

        if (
            now - last_time
            >= SIGNAL_COOLDOWN
        ):
            return True

    except Exception:
        return True

    return False


# ============================================================
# ANA RADAR
# ============================================================

def main():

    print()
    print("🚀 MEXC PUMP RADAR 8.0")
    print("🎯 SADECE GÜÇLÜ GİRİŞ SİNYALLERİ")
    print()

    if not TELEGRAM_TOKEN:
        print("⚠️ TELEGRAM_BOT_TOKEN yok.")

    if not TELEGRAM_CHAT_ID:
        print("⚠️ TELEGRAM_CHAT_ID yok.")

    # --------------------------------------------------------
    # CONTRACTS
    # --------------------------------------------------------

    symbols = get_contracts()

    print(
        f"Futures kontrat: {len(symbols)}"
    )

    if not symbols:
        print(
            "❌ Futures listesi alınamadı."
        )
        return

    # --------------------------------------------------------
    # STATE
    # --------------------------------------------------------

    state = load_state()

    candidates = []

    # --------------------------------------------------------
    # TARAMA
    # --------------------------------------------------------

    total = len(symbols)

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_symbol,
                symbol
            ): symbol

            for symbol in symbols
        }

        completed = 0

        for future in as_completed(
            futures
        ):

            completed += 1

            symbol = futures[
                future
            ]

            try:

                result = future.result()

                if result:

                    candidates.append(
                        result
                    )

                    print(
                        f"🔥 ADAY: "
                        f"{symbol} "
                        f"{result['score']}"
                    )

            except Exception as e:

                print(
                    f"Hata {symbol}: {e}"
                )

            if (
                completed % 25 == 0
                or completed == total
            ):

                print(
                    f"İlerleme: "
                    f"{completed}/{total}"
                )

    # --------------------------------------------------------
    # SKOR SIRALAMA
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    print()
    print(
        f"🎯 Güçlü aday: "
        f"{len(candidates)}"
    )

    # --------------------------------------------------------
    # TELEGRAM
    # SADECE BURADA GÖNDERİLİR
    # --------------------------------------------------------

    sent = 0

    for candidate in candidates:

        symbol = candidate[
            "symbol"
        ]

        if not can_send(
            symbol,
            state
        ):
            print(
                f"⏳ Cooldown: {symbol}"
            )
            continue

        message = build_message(
            candidate
        )

        ok = telegram_send(
            message
        )

        if ok:

            sent += 1

            state[
                symbol
            ] = time.time()

            save_state(
                state
            )

            print(
                f"✅ GÖNDERİLDİ: "
                f"{symbol} "
                f"{candidate['score']}"
            )

    # --------------------------------------------------------
    # SADECE GITHUB LOGU
    # TELEGRAM'A GİTMEZ
    # --------------------------------------------------------

    print()
    print(
        f"📨 Telegram gönderilen: "
        f"{sent}"
    )

    print(
        "🏁 Tarama tamamlandı."
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
