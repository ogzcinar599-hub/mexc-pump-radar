import os
import json
import time
import math
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 🚀 MEXC PUMP RADAR 13.0
#
# AMAÇ:
# Pump başlamadan önce güçlü momentum gösteren coinleri bulmak.
#
# 15M = MOMENTUM
# 1H  = TREND
# 4H  = ANA YÖN
# BTC = YUMUŞAK FİLTRE
#
# TELEGRAM:
# SADECE GÜÇLÜ LONG / SHORT
# İZLEME ADAYI YOK
# ============================================================

BASE = "https://contract.mexc.com"

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

HISTORY_FILE = "signal_history.json"

# ============================================================
# AYARLAR
# ============================================================

MAX_WORKERS = 12

# Temel sinyal puanı
SIGNAL_SCORE = 7

# BTC'nin ters yönünde işlem için gereken puan
OPPOSITE_BTC_SCORE = 8

# 24 saatlik minimum USDT hacmi
MIN_24H_VOLUME = 100000

# Aynı coin tekrar gönderilmesin
HISTORY_HOURS = 12

# Aynı anda Telegram'a maksimum sinyal
MAX_TELEGRAM_SIGNALS = 15

# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 MEXC-Pump-Radar"
})


# ============================================================
# GENEL REQUEST
# ============================================================

def get_json(url, params=None, timeout=10):

    try:

        r = session.get(
            url,
            params=params,
            timeout=timeout
        )

        if r.status_code != 200:
            return None

        data = r.json()

        if not data.get("success", True):
            return None

        return data

    except Exception:
        return None


# ============================================================
# HISTORY
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
                ensure_ascii=False,
                indent=2
            )

    except Exception:
        pass


def clean_history(history):

    now = time.time()

    result = {}

    for symbol, ts in history.items():

        try:

            if now - float(ts) < HISTORY_HOURS * 3600:
                result[symbol] = ts

        except Exception:
            pass

    return result


# ============================================================
# CONTRACTLAR
# ============================================================

def get_contracts():

    data = get_json(
        f"{BASE}/api/v1/contract/detail",
        timeout=15
    )

    if not data:
        return []

    contracts = data.get("data", [])

    result = []

    for c in contracts:

        symbol = c.get("symbol", "")

        if not symbol:
            continue

        # Sadece USDT
        if not symbol.endswith("_USDT"):
            continue

        # Sadece aktif API kontratları varsa kontrol et
        if c.get("apiAllowed") is False:
            # API trading kapalı olması market datasını
            # kullanmamıza engel değil.
            pass

        result.append(symbol)

    return sorted(set(result))


# ============================================================
# TICKER
# ============================================================

def get_tickers():

    data = get_json(
        f"{BASE}/api/v1/contract/ticker",
        timeout=15
    )

    if not data:
        return {}

    raw = data.get("data", [])

    # Bazı API cevaplarında tek obje olabilir
    if isinstance(raw, dict):
        raw = [raw]

    result = {}

    for x in raw:

        symbol = x.get("symbol")

        if not symbol:
            continue

        result[symbol] = x

    return result


# ============================================================
# KLINE
# ============================================================

def get_kline(symbol, interval, limit=80):

    data = get_json(
        f"{BASE}/api/v1/contract/kline/{symbol}",
        params={
            "interval": interval
        },
        timeout=10
    )

    if not data:
        return None

    d = data.get("data")

    if not d:
        return None

    try:

        times = d.get("time", [])
        opens = d.get("open", [])
        closes = d.get("close", [])
        highs = d.get("high", [])
        lows = d.get("low", [])
        vols = d.get("vol", [])

        n = min(
            len(times),
            len(opens),
            len(closes),
            len(highs),
            len(lows),
            len(vols)
        )

        if n < 30:
            return None

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

        # Son mum henüz devam ediyor olabilir.
        # Son mum yerine kapanmış mumu kullanıyoruz.
        if len(candles) > 2:
            candles = candles[:-1]

        return candles[-limit:]

    except Exception:
        return None


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if not values:
        return []

    k = 2 / (period + 1)

    result = [values[0]]

    for price in values[1:]:

        result.append(
            price * k +
            result[-1] * (1 - k)
        )

    return result


# ============================================================
# RSI
# ============================================================

def rsi(values, period=14):

    if len(values) < period + 2:
        return []

    gains = []
    losses = []

    for i in range(1, len(values)):

        diff = values[i] - values[i - 1]

        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(
        gains[:period]
    ) / period

    avg_loss = sum(
        losses[:period]
    ) / period

    result = []

    if avg_loss == 0:
        result.append(100)
    else:
        rs = avg_gain / avg_loss
        result.append(100 - (100 / (1 + rs)))

    for i in range(period, len(gains)):

        avg_gain = (
            avg_gain * (period - 1) +
            gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1) +
            losses[i]
        ) / period

        if avg_loss == 0:
            result.append(100)
        else:
            rs = avg_gain / avg_loss
            result.append(
                100 - (100 / (1 + rs))
            )

    return result


# ============================================================
# % DEĞİŞİM
# ============================================================

def pct(a, b):

    if a == 0:
        return 0

    return ((b - a) / a) * 100


# ============================================================
# VOLUME RATIO
# ============================================================

def volume_ratio(candles):

    if len(candles) < 22:
        return 0

    last_vol = candles[-1]["vol"]

    previous = [
        x["vol"]
        for x in candles[-21:-1]
    ]

    avg_vol = sum(previous) / len(previous)

    if avg_vol <= 0:
        return 0

    return last_vol / avg_vol


# ============================================================
# ANALİZ
# ============================================================

def analyze_timeframe(candles):

    if not candles or len(candles) < 30:
        return None

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

    current = closes[-1]

    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)
    ema50 = ema(closes, 50)

    rsis = rsi(closes, 14)

    if not rsis:
        return None

    current_rsi = rsis[-1]

    previous_rsi = (
        rsis[-2]
        if len(rsis) >= 2
        else current_rsi
    )

    # Momentum
    change3 = pct(
        closes[-4],
        closes[-1]
    )

    change6 = pct(
        closes[-7],
        closes[-1]
    )

    # Hacim
    vr = volume_ratio(candles)

    # Son 20 mumun direnci / desteği
    resistance = max(
        highs[-21:-1]
    )

    support = min(
        lows[-21:-1]
    )

    distance_resistance = (
        (resistance - current) /
        current * 100
        if current else 999
    )

    distance_support = (
        (current - support) /
        current * 100
        if current else 999
    )

    # Bullish
    bullish = 0

    # EMA
    if current > ema9[-1]:
        bullish += 1

    if ema9[-1] > ema21[-1]:
        bullish += 1

    if ema21[-1] > ema50[-1]:
        bullish += 1

    # RSI
    if 45 <= current_rsi <= 68:
        bullish += 1

    if current_rsi > previous_rsi:
        bullish += 1

    # Momentum
    if change3 > 0.25:
        bullish += 1

    if change6 > 0.50:
        bullish += 1

    # Volume
    if vr >= 1.30:
        bullish += 1

    if vr >= 1.80:
        bullish += 1

    # Resistance yakınlığı / kırılım
    if distance_resistance <= 1.5:
        bullish += 1

    if current >= resistance:
        bullish += 2

    # Bearish
    bearish = 0

    if current < ema9[-1]:
        bearish += 1

    if ema9[-1] < ema21[-1]:
        bearish += 1

    if ema21[-1] < ema50[-1]:
        bearish += 1

    if 32 <= current_rsi <= 55:
        bearish += 1

    if current_rsi < previous_rsi:
        bearish += 1

    if change3 < -0.25:
        bearish += 1

    if change6 < -0.50:
        bearish += 1

    if vr >= 1.30:
        bearish += 1

    if vr >= 1.80:
        bearish += 1

    if distance_support <= 1.5:
        bearish += 1

    if current <= support:
        bearish += 2

    return {
        "price": current,
        "rsi": current_rsi,
        "rsi_prev": previous_rsi,
        "ema9": ema9[-1],
        "ema21": ema21[-1],
        "ema50": ema50[-1],
        "change3": change3,
        "change6": change6,
        "volume_ratio": vr,
        "resistance": resistance,
        "support": support,
        "distance_resistance": distance_resistance,
        "distance_support": distance_support,
        "bullish": bullish,
        "bearish": bearish
    }


# ============================================================
# BTC ANALİZİ
# ============================================================

def analyze_btc():

    result = {
        "direction": "NEUTRAL",
        "bullish": 0,
        "bearish": 0,
        "rsi15": 50,
        "rsi1h": 50,
        "rsi4h": 50
    }

    data15 = get_kline(
        "BTC_USDT",
        "Min15",
        80
    )

    data1h = get_kline(
        "BTC_USDT",
        "Min60",
        80
    )

    data4h = get_kline(
        "BTC_USDT",
        "Hour4",
        80
    )

    a15 = analyze_timeframe(data15)
    a1h = analyze_timeframe(data1h)
    a4h = analyze_timeframe(data4h)

    if not a15 or not a1h or not a4h:
        return result

    bullish = 0
    bearish = 0

    bullish += a15["bullish"]
    bullish += a1h["bullish"]
    bullish += a4h["bullish"]

    bearish += a15["bearish"]
    bearish += a1h["bearish"]
    bearish += a4h["bearish"]

    result["bullish"] = bullish
    result["bearish"] = bearish

    result["rsi15"] = a15["rsi"]
    result["rsi1h"] = a1h["rsi"]
    result["rsi4h"] = a4h["rsi"]

    # BTC yönü daha yumuşak belirleniyor
    if bullish >= bearish + 3:
        result["direction"] = "BULLISH"

    elif bearish >= bullish + 3:
        result["direction"] = "BEARISH"

    else:
        result["direction"] = "NEUTRAL"

    return result


# ============================================================
# COIN ANALİZİ
# ============================================================

def analyze_coin(symbol, ticker, btc):

    try:

        # 24H hacim
        volume24 = float(
            ticker.get("amount24", 0) or 0
        )

        if volume24 < MIN_24H_VOLUME:
            return None

        # Çok sert dump/pump sonrası coinleri biraz filtrele
        daily_change = float(
            ticker.get("riseFallRate", 0) or 0
        ) * 100

        # Aşırı şişmiş coinleri kovalamıyoruz
        if daily_change > 35:
            return None

        # ====================================================
        # KLINE
        # ====================================================

        c15 = get_kline(
            symbol,
            "Min15",
            80
        )

        c1h = get_kline(
            symbol,
            "Min60",
            80
        )

        c4h = get_kline(
            symbol,
            "Hour4",
            80
        )

        if not c15 or not c1h or not c4h:
            return None

        a15 = analyze_timeframe(c15)
        a1h = analyze_timeframe(c1h)
        a4h = analyze_timeframe(c4h)

        if not a15 or not a1h or not a4h:
            return None

        # ====================================================
        # LONG SCORE
        # ====================================================

        long_score = 0

        # 15M momentum
        if a15["bullish"] >= 5:
            long_score += 2
        elif a15["bullish"] >= 3:
            long_score += 1

        # 1H trend
        if a1h["bullish"] >= 5:
            long_score += 2
        elif a1h["bullish"] >= 3:
            long_score += 1

        # 4H ana yön
        if a4h["bullish"] >= 5:
            long_score += 2
        elif a4h["bullish"] >= 3:
            long_score += 1

        # Hacim patlaması
        if a15["volume_ratio"] >= 1.5:
            long_score += 1

        if a15["volume_ratio"] >= 2.0:
            long_score += 1

        # RSI dönüş
        if (
            a15["rsi_prev"] < a15["rsi"] and
            a15["rsi"] >= 40
        ):
            long_score += 1

        # 1H RSI sağlıklı momentum
        if 45 <= a1h["rsi"] <= 68:
            long_score += 1

        # Direnç yakınlığı
        if a15["distance_resistance"] <= 1.2:
            long_score += 1

        # 4H dipten dönüş
        if (
            a4h["rsi"] >= 30 and
            a4h["rsi_prev"] < a4h["rsi"]
        ):
            long_score += 1

        # ====================================================
        # SHORT SCORE
        # ====================================================

        short_score = 0

        if a15["bearish"] >= 5:
            short_score += 2
        elif a15["bearish"] >= 3:
            short_score += 1

        if a1h["bearish"] >= 5:
            short_score += 2
        elif a1h["bearish"] >= 3:
            short_score += 1

        if a4h["bearish"] >= 5:
            short_score += 2
        elif a4h["bearish"] >= 3:
            short_score += 1

        if a15["volume_ratio"] >= 1.5:
            short_score += 1

        if a15["volume_ratio"] >= 2.0:
            short_score += 1

        if (
            a15["rsi_prev"] > a15["rsi"] and
            a15["rsi"] <= 60
        ):
            short_score += 1

        if 32 <= a1h["rsi"] <= 55:
            short_score += 1

        if a15["distance_support"] <= 1.2:
            short_score += 1

        # ====================================================
        # YÖN
        # ====================================================

        direction = None
        score = 0

        if long_score > short_score:
            direction = "LONG"
            score = long_score

        elif short_score > long_score:
            direction = "SHORT"
            score = short_score

        else:
            return None

        # ====================================================
        # BTC SOFT FILTER
        # ====================================================

        btc_direction = btc["direction"]

        required_score = SIGNAL_SCORE

        if btc_direction == "BULLISH" and direction == "SHORT":
            required_score = OPPOSITE_BTC_SCORE

        elif btc_direction == "BEARISH" and direction == "LONG":
            required_score = OPPOSITE_BTC_SCORE

        if score < required_score:
            return None

        # ====================================================
        # EKSTRA KALİTE KONTROLÜ
        # ====================================================

        # LONG için 15M veya 1H momentum şartı
        if direction == "LONG":

            if (
                a15["change3"] <= 0 and
                a1h["change3"] <= 0
            ):
                return None

            if a15["rsi"] < 38:
                return None

        # SHORT için
        if direction == "SHORT":

            if (
                a15["change3"] >= 0 and
                a1h["change3"] >= 0
            ):
                return None

            if a15["rsi"] > 65:
                return None

        # ====================================================
        # ENTRY
        # ====================================================

        entry = float(
            ticker.get("lastPrice")
            or a15["price"]
        )

        # ====================================================
        # STOP / TP
        # ====================================================

        if direction == "LONG":

            # Son 15M desteğinin biraz altı
            stop_base = a15["support"]

            # Stop çok uzaksa ATR benzeri yüzde kullan
            stop = min(
                stop_base,
                entry * 0.985
            )

            risk = entry - stop

            if risk <= 0:
                return None

            # Stop aşırı uzaksa sinyali alma
            risk_pct = (
                risk / entry * 100
            )

            if risk_pct > 3.5:
                stop = entry * 0.975
                risk = entry - stop

            tp1 = entry + risk * 1.0
            tp2 = entry + risk * 2.0
            tp3 = entry + risk * 3.0

        else:

            stop_base = a15["resistance"]

            stop = max(
                stop_base,
                entry * 1.015
            )

            risk = stop - entry

            if risk <= 0:
                return None

            risk_pct = (
                risk / entry * 100
            )

            if risk_pct > 3.5:
                stop = entry * 1.025
                risk = stop - entry

            tp1 = entry - risk * 1.0
            tp2 = entry - risk * 2.0
            tp3 = entry - risk * 3.0

        return {
            "symbol": symbol,
            "direction": direction,
            "score": score,
            "entry": entry,
            "stop": stop,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "volume24": volume24,
            "daily_change": daily_change,
            "rsi15": a15["rsi"],
            "rsi1h": a1h["rsi"],
            "rsi4h": a4h["rsi"],
            "volume_ratio": a15["volume_ratio"],
            "btc_direction": btc_direction
        }

    except Exception:
        return None


# ============================================================
# FORMAT PRICE
# ============================================================

def fmt_price(x):

    try:

        x = float(x)

        if x >= 1000:
            return f"{x:.2f}"

        if x >= 1:
            return f"{x:.4f}"

        if x >= 0.01:
            return f"{x:.6f}"

        if x >= 0.0001:
            return f"{x:.8f}"

        return f"{x:.10f}"

    except Exception:
        return str(x)


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(signal):

    if not TOKEN or not CHAT_ID:
        return False

    symbol = signal["symbol"].replace(
        "_USDT",
        ""
    )

    direction = signal["direction"]

    if direction == "LONG":
        emoji = "🟢"
    else:
        emoji = "🔴"

    text = (
        f"{emoji} {direction} SİNYAL\n"
        f"━━━━━━━━━━━━━━\n"
        f"💎 {symbol}/USDT\n"
        f"⭐ Güç: {signal['score']}/10\n\n"
        f"🎯 Giriş: {fmt_price(signal['entry'])}\n"
        f"🛑 Stop: {fmt_price(signal['stop'])}\n"
        f"💰 TP1: {fmt_price(signal['tp1'])}\n"
        f"💰 TP2: {fmt_price(signal['tp2'])}\n"
        f"💰 TP3: {fmt_price(signal['tp3'])}\n\n"
        f"📊 RSI 15M: {signal['rsi15']:.1f}\n"
        f"📊 RSI 1H: {signal['rsi1h']:.1f}\n"
        f"📊 RSI 4H: {signal['rsi4h']:.1f}\n"
        f"🔥 Hacim: {signal['volume_ratio']:.1f}x\n"
        f"🌐 BTC: {signal['btc_direction']}\n"
        f"━━━━━━━━━━━━━━\n"
        f"⚠️ Sinyal otomatik teknik taramadır."
    )

    try:

        r = session.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": text
            },
            timeout=10
        )

        return r.status_code == 200

    except Exception:
        return False


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print("🚀 MEXC PUMP RADAR 13.0")
    print("🌐 BTC YÖNÜ = YUMUŞAK FİLTRE")
    print("🟢 LONG")
    print("🔴 SHORT")
    print("⚪ NEUTRAL = İŞLEM YOK")
    print("")

    # --------------------------------------------------------
    # BTC
    # --------------------------------------------------------

    print("🌐 BTC yönü analiz ediliyor...")

    btc = analyze_btc()

    print("--------------------------------")
    print(
        f"🌐 BTC YÖNÜ: {btc['direction']}"
    )

    print(
        f"15M: RSI {btc['rsi15']:.1f}"
    )

    print(
        f"1H : RSI {btc['rsi1h']:.1f}"
    )

    print(
        f"4H : RSI {btc['rsi4h']:.1f}"
    )

    print(
        f"Bullish skor: {btc['bullish']}"
    )

    print(
        f"Bearish skor: {btc['bearish']}"
    )

    print("--------------------------------")

    # --------------------------------------------------------
    # CONTRACTS
    # --------------------------------------------------------

    contracts = get_contracts()

    if not contracts:

        print("❌ Futures kontratları alınamadı.")
        return

    tickers = get_tickers()

    if not tickers:

        print("❌ Ticker verisi alınamadı.")
        return

    # Ticker'da bulunanları kullan
    symbols = [
        s for s in contracts
        if s in tickers
    ]

    print(
        f"📊 Futures kontrat: {len(symbols)}"
    )

    # --------------------------------------------------------
    # HACME GÖRE ÖN ELEME
    # --------------------------------------------------------

    liquid_symbols = []

    for symbol in symbols:

        ticker = tickers.get(symbol, {})

        try:

            volume24 = float(
                ticker.get(
                    "amount24",
                    0
                ) or 0
            )

            if volume24 >= MIN_24H_VOLUME:
                liquid_symbols.append(symbol)

        except Exception:
            pass

    print(
        f"💧 Likit kontrat: {len(liquid_symbols)}"
    )

    # --------------------------------------------------------
    # HISTORY
    # --------------------------------------------------------

    history = clean_history(
        load_history()
    )

    # Daha önce yakın zamanda gönderilenleri
    # taramadan çıkar
    scan_symbols = [
        s for s in liquid_symbols
        if s not in history
    ]

    print(
        f"🔎 Taranacak: {len(scan_symbols)}"
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    results = []

    total = len(scan_symbols)
    completed = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_coin,
                symbol,
                tickers[symbol],
                btc
            ): symbol
            for symbol in scan_symbols
        }

        for future in as_completed(futures):

            completed += 1

            try:

                result = future.result()

                if result:
                    results.append(result)

            except Exception:
                pass

            if (
                completed % 50 == 0
                or completed == total
            ):

                print(
                    f"İlerleme: "
                    f"{completed}/{total}"
                )

    # --------------------------------------------------------
    # SCORE SIRALAMA
    # --------------------------------------------------------

    results.sort(
        key=lambda x: (
            x["score"],
            x["volume_ratio"]
        ),
        reverse=True
    )

    # --------------------------------------------------------
    # SADECE EN GÜÇLÜLER
    # --------------------------------------------------------

    strong = results[
        :MAX_TELEGRAM_SIGNALS
    ]

    print("")
    print(
        f"🎯 Güçlü sinyal: {len(strong)}"
    )

    telegram_count = 0

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    for signal in strong:

        print(
            f"{signal['symbol']} "
            f"{signal['direction']} "
            f"{signal['score']}/10"
        )

        ok = send_telegram(signal)

        if ok:

            telegram_count += 1

            history[
                signal["symbol"]
            ] = time.time()

            # Telegram API rate limit
            time.sleep(0.15)

    # --------------------------------------------------------
    # HISTORY SAVE
    # --------------------------------------------------------

    save_history(history)

    # --------------------------------------------------------
    # SONUÇ
    # --------------------------------------------------------

    print("")
    print(
        f"📩 Telegram gönderilen: "
        f"{telegram_count}"
    )

    print("🏁 Tarama tamamlandı.")
    print("")


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
