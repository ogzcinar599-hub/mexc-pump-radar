import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 🚀 MEXC PUMP RADAR 14.0
#
# SADECE:
# ✅ MEXC USDT FUTURES
# ✅ 15M + 1H + 4H
# ✅ RSI
# ✅ HACİM
# ✅ MOMENTUM
# ✅ BTC YÖN FİLTRESİ
# ✅ PUMP ÖNCESİ DÖNÜŞ
#
# KESİNLİKLE:
# ❌ STOCK
# ❌ TOKENIZED STOCK
# ❌ SPOT
# ❌ ZAYIF HACİM
# ❌ ZAYIF SKOR
# ❌ İZLEME ADAYI
# ============================================================


BASE = "https://contract.mexc.com"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HISTORY_FILE = "signal_history.json"

MAX_WORKERS = 12

# ============================================================
# 🔥 GÜÇLÜ SİNYAL FİLTRELERİ
# ============================================================

# Artık 7/10 gönderilmeyecek
MIN_SCORE = 8

# Minimum hacim
# 1.70x altındaki hiçbir coin sinyal olamaz
MIN_VOLUME_RATIO = 1.70

# Çok güçlü hacim seviyeleri
STRONG_VOLUME = 2.50
EXTREME_VOLUME = 4.00

# Aynı coin tekrar gönderilmesin
COOLDOWN_HOURS = 6


# ============================================================
# GENEL REQUEST
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
# 🚫 STOCK FİLTRESİ
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

    # Bilinen hisse tokenleri
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
# FUTURES KONTRATLARI
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

        # SADECE USDT FUTURES
        if not symbol.endswith("_USDT"):
            continue

        # STOCK YOK
        if is_stock_symbol(symbol):
            continue

        # AKTİF KONTRAT
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
        f"{BASE}/api/v1/contract/"
        f"kline/{symbol}"
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

        if len(closes) < 30:
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
        return 50

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
        return 100

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# YÜZDE DEĞİŞİM
# ============================================================

def pct_change(
    closes,
    candles
):

    if len(closes) <= candles:
        return 0

    old = closes[-candles - 1]
    new = closes[-1]

    if old == 0:
        return 0

    return (
        (new - old)
        / old
    ) * 100


# ============================================================
# HACİM ORANI
# ============================================================

def volume_ratio(volumes):

    if len(volumes) < 25:
        return 1

    current = volumes[-1]

    avg = (
        sum(volumes[-21:-1])
        / 20
    )

    if avg <= 0:
        return 1

    return current / avg


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

        # Güvenlik
        if is_stock_symbol(symbol):
            return None

        data15 = get_klines(
            symbol,
            "Min15",
            80
        )

        data1h = get_klines(
            symbol,
            "Min60",
            80
        )

        data4h = get_klines(
            symbol,
            "Hour4",
            80
        )

        if (
            not data15
            or not data1h
            or not data4h
        ):

            return None

        c15 = data15["close"]
        c1h = data1h["close"]
        c4h = data4h["close"]

        v15 = data15["volume"]

        price = c15[-1]

        rsi15 = calculate_rsi(c15)
        rsi1h = calculate_rsi(c1h)
        rsi4h = calculate_rsi(c4h)

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

        vol = volume_ratio(v15)

        # ====================================================
        # 🚫 EN ÖNEMLİ HACİM FİLTRESİ
        #
        # 1.70x ALTINDA HİÇBİR SİNYAL YOK
        # ====================================================

        if vol < MIN_VOLUME_RATIO:

            return None

        # ====================================================
        # LONG SKOR
        # ====================================================

        long_score = 0

        # 4H dip / dönüş
        if 30 <= rsi4h <= 48:

            long_score += 2

        elif 48 < rsi4h <= 58:

            long_score += 1

        # 1H toparlanma
        if rsi1h >= 45:
            long_score += 1

        if rsi1h > 50:
            long_score += 1

        # 15M momentum
        if rsi15 >= 50:
            long_score += 1

        if change15 > 0:
            long_score += 1

        if change1h > 0:
            long_score += 1

        # ====================================================
        # HACİM PUANI
        # ====================================================

        if vol >= MIN_VOLUME_RATIO:
            long_score += 1

        if vol >= STRONG_VOLUME:
            long_score += 1

        if vol >= EXTREME_VOLUME:
            long_score += 1

        # BTC
        if btc_direction == "BULLISH":

            long_score += 2

        elif btc_direction == "BEARISH":

            long_score -= 2

        # ====================================================
        # SHORT SKOR
        # ====================================================

        short_score = 0

        # 4H zayıflık
        if 52 <= rsi4h <= 70:

            short_score += 1

        if rsi4h > 70:

            short_score += 2

        # 1H
        if rsi1h < 50:

            short_score += 1

        if rsi1h < 42:

            short_score += 1

        # 15M
        if rsi15 < 50:

            short_score += 1

        if change15 < 0:

            short_score += 1

        if change1h < 0:

            short_score += 1

        # ====================================================
        # SHORT HACİM
        # ====================================================

        if vol >= MIN_VOLUME_RATIO:

            short_score += 1

        if vol >= STRONG_VOLUME:

            short_score += 1

        if vol >= EXTREME_VOLUME:

            short_score += 1

        # BTC
        if btc_direction == "BEARISH":

            short_score += 2

        elif btc_direction == "BULLISH":

            short_score -= 2

        # ====================================================
        # PUMP ÖNCESİ LONG FİLTRESİ
        # ====================================================

        # Zaten çok yükselmiş coinleri kovalamıyoruz

        if change4h > 12:

            long_score -= 2

        if change1h > 8:

            long_score -= 2

        # Aşırı RSI

        if rsi15 > 78:

            long_score -= 2

        if rsi1h > 75:

            long_score -= 1

        # ====================================================
        # YÖN
        # ====================================================

        if (
            long_score >= MIN_SCORE
            and long_score > short_score
        ):

            direction = "LONG"
            score = long_score

        elif (
            short_score >= MIN_SCORE
            and short_score > long_score
        ):

            direction = "SHORT"
            score = short_score

        else:

            return None

        # ====================================================
        # EK GÜVENLİK
        # ====================================================

        # BTC ters yöndeyse işlemi engelle

        if (
            direction == "LONG"
            and btc_direction == "BEARISH"
        ):

            return None

        if (
            direction == "SHORT"
            and btc_direction == "BULLISH"
        ):

            return None

        # ====================================================
        # GİRİŞ / STOP / TP
        # ====================================================

        if direction == "LONG":

            entry = price

            stop = entry * 0.978

            tp1 = entry * 1.022
            tp2 = entry * 1.045
            tp3 = entry * 1.070

        else:

            entry = price

            stop = entry * 1.022

            tp1 = entry * 0.978
            tp2 = entry * 0.955
            tp3 = entry * 0.930

        return {

            "symbol": symbol.replace(
                "_USDT",
                "/USDT"
            ),

            "direction": direction,

            "score": min(
                score,
                10
            ),

            "entry": entry,
            "stop": stop,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,

            "rsi15": rsi15,
            "rsi1h": rsi1h,
            "rsi4h": rsi4h,

            "volume": vol,

            "btc": btc_direction
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

    if signal["direction"] == "LONG":

        title = "🟢 LONG SİNYAL"

    else:

        title = "🔴 SHORT SİNYAL"

    # Hacim durumunu belirle

    if signal["volume"] >= EXTREME_VOLUME:

        volume_text = (
            f"🚀 Hacim: "
            f"{signal['volume']:.1f}x"
        )

    elif signal["volume"] >= STRONG_VOLUME:

        volume_text = (
            f"🔥 Hacim: "
            f"{signal['volume']:.1f}x"
        )

    else:

        volume_text = (
            f"📈 Hacim: "
            f"{signal['volume']:.1f}x"
        )

    message = f"""
{title}
━━━━━━━━━━━━━━━━

💎 {signal["symbol"]}

⭐ Güç: {signal["score"]}/10

🎯 Giriş: {fmt_price(signal["entry"])}
🛑 Stop: {fmt_price(signal["stop"])}

💰 TP1: {fmt_price(signal["tp1"])}
💰 TP2: {fmt_price(signal["tp2"])}
💰 TP3: {fmt_price(signal["tp3"])}

📊 RSI 15M: {signal["rsi15"]:.1f}
📊 RSI 1H: {signal["rsi1h"]:.1f}
📊 RSI 4H: {signal["rsi4h"]:.1f}

{volume_text}

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
    print("🚀 MEXC PUMP RADAR 14.0")
    print()
    print("🌐 BTC yön filtresi aktif")
    print("🟢 BULLISH = LONG")
    print("🔴 BEARISH = SHORT")
    print("⚪ NEUTRAL = İŞLEM YOK")
    print()

    print("🚫 STOCK FİLTRESİ AKTİF")
    print("🚫 SPOT FİLTRESİ AKTİF")
    print("🚫 TOKENIZED STOCK FİLTRESİ AKTİF")
    print()

    print(
        f"🔥 Minimum hacim: "
        f"{MIN_VOLUME_RATIO:.2f}x"
    )

    print(
        f"⭐ Minimum skor: "
        f"{MIN_SCORE}/10"
    )

    print()

    print("🌐 BTC yönü analiz ediliyor...")

    btc_direction, btc15, btc1h, btc4h = (
        get_btc_direction()
    )

    print("=" * 45)

    print(
        f"🌐 BTC YÖNÜ: "
        f"{btc_direction}"
    )

    print(
        f"15M: "
        f"{btc15:+.2f}%"
    )

    print(
        f"1H: "
        f"{btc1h:+.2f}%"
    )

    print(
        f"4H: "
        f"{btc4h:+.2f}%"
    )

    print("=" * 45)

    symbols = get_futures_symbols()

    print(
        f"📊 Futures kontrat: "
        f"{len(symbols)}"
    )

    # Ek güvenlik

    symbols = [
        s
        for s in symbols

        if s.endswith("_USDT")
        and not is_stock_symbol(s)
    ]

    print(
        f"🧹 Stock sonrası: "
        f"{len(symbols)}"
    )

    print(
        f"🔎 Taranacak: "
        f"{len(symbols)}"
    )

    history = load_history()

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

                result = future.result()

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
        key=lambda x: (
            x["score"],
            x["volume"]
        ),
        reverse=True
    )

    print()

    print(
        f"🎯 Güçlü sinyal: "
        f"{len(signals)}"
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
        # SON HACİM KONTROLÜ
        # ----------------------------------------------------

        if (
            signal["volume"]
            < MIN_VOLUME_RATIO
        ):

            print(
                f"🚫 Atlandı: "
                f"{symbol} "
                f"(hacim düşük)"
            )

            continue

        # ----------------------------------------------------
        # SON SKOR KONTROLÜ
        # ----------------------------------------------------

        if (
            signal["score"]
            < MIN_SCORE
        ):

            print(
                f"🚫 Atlandı: "
                f"{symbol} "
                f"(skor düşük)"
            )

            continue

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
                f"Hacim "
                f"{signal['volume']:.1f}x"
            )

        time.sleep(0.4)

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
