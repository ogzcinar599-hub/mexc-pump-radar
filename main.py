# ============================================================
# 🚀 MEXC PUMP RADAR 13.0
# 🎯 SADECE FUTURES USDT
# 🚫 STOCK / AALSTOCK / NVDASTOCK vb. YOK
# 🟢 BTC BULLISH  -> SADECE LONG
# 🔴 BTC BEARISH  -> SADECE SHORT
# ⚪ BTC NEUTRAL  -> İŞLEM YOK
# ============================================================

import os
import time
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# ⚙️ AYARLAR
# ============================================================

BASE_URL = "https://contract.mexc.com"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SCAN_INTERVAL = 300
MAX_WORKERS = 20

# Aynı anda en fazla kaç sinyal Telegram'a gönderilsin
MAX_SIGNALS = 10

# ============================================================
# 🎯 SİNYAL FİLTRELERİ
# ============================================================

# LONG
LONG_RSI_MIN = 53
LONG_RSI_MAX = 72

# SHORT
SHORT_RSI_MIN = 28
SHORT_RSI_MAX = 47

# Hacim
VOLUME_RATIO_MIN = 1.20

# 15 dakikalık fiyat hareketi
PRICE_CHANGE_MIN = 0.30

# Güçlü sinyal minimum skor
MIN_SCORE = 7


# ============================================================
# 🚫 STOCK FİLTRESİ
# ============================================================

STOCK_KEYWORDS = [
    "STOCK",
    "AALSTOCK",
    "NVDASTOCK",
    "TSLASTOCK",
    "AAPLASTOCK",
    "AMZNSTOCK",
    "GOOGLSTOCK",
    "MSTRSTOCK",
    "COINSTOCK",
    "META_STOCK",
    "STOCK_USDT"
]


# ============================================================
# 🌐 SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
})


# ============================================================
# 📡 TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram bilgileri bulunamadı.")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:

        r = session.post(
            url,
            data=data,
            timeout=10
        )

        if r.status_code == 200:
            return True

        print("Telegram hata:", r.text)

    except Exception as e:

        print("Telegram gönderim hatası:", e)

    return False


# ============================================================
# 📊 MEXC FUTURES KONTRATLARI
# ============================================================

def get_futures_symbols():

    url = f"{BASE_URL}/api/v1/contract/detail"

    try:

        r = session.get(
            url,
            timeout=15
        )

        if r.status_code != 200:
            print("❌ Kontrat API hatası")
            return []

        data = r.json().get("data", [])

        symbols = []

        for item in data:

            symbol = str(
                item.get("symbol", "")
            ).upper()

            quote = str(
                item.get("quoteCoin", "")
            ).upper()

            contract_type = str(
                item.get("contractType", "")
            ).upper()

            state = item.get("state", 1)

            # ------------------------------------------------
            # SADECE USDT
            # ------------------------------------------------

            if quote != "USDT":
                continue

            # ------------------------------------------------
            # SADECE PERPETUAL FUTURES
            # ------------------------------------------------

            if contract_type != "PERPETUAL":
                continue

            # ------------------------------------------------
            # AKTİF
            # ------------------------------------------------

            if state != 1:
                continue

            # ------------------------------------------------
            # 🚫 STOCK TAMAMEN ENGELLENİYOR
            # ------------------------------------------------

            if "STOCK" in symbol:
                continue

            bad = False

            for keyword in STOCK_KEYWORDS:

                if keyword in symbol:
                    bad = True
                    break

            if bad:
                continue

            symbols.append(symbol)

        return sorted(set(symbols))

    except Exception as e:

        print("❌ Futures liste hatası:", e)
        return []


# ============================================================
# 🕯️ KLINE
# ============================================================

def get_klines(symbol, interval="Min15", limit=100):

    url = f"{BASE_URL}/api/v1/contract/kline/{symbol}"

    params = {
        "interval": interval,
        "limit": limit
    }

    try:

        r = session.get(
            url,
            params=params,
            timeout=10
        )

        if r.status_code != 200:
            return None

        data = r.json().get("data")

        if not data:
            return None

        return data

    except Exception:

        return None


# ============================================================
# 🔢 RSI
# ============================================================

def calculate_rsi(closes, period=14):

    if len(closes) < period + 2:
        return None

    gains = []
    losses = []

    for i in range(1, len(closes)):

        diff = closes[i] - closes[i - 1]

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

    return 100 - (100 / (1 + rs))


# ============================================================
# 📈 EMA
# ============================================================

def calculate_ema(values, period=20):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    ema = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        ema = (
            price - ema
        ) * multiplier + ema

    return ema


# ============================================================
# 📊 HACİM ORANI
# ============================================================

def calculate_volume_ratio(volumes):

    if len(volumes) < 21:
        return 0

    current = volumes[-1]

    average = sum(
        volumes[-21:-1]
    ) / 20

    if average <= 0:
        return 0

    return current / average


# ============================================================
# ₿ BTC YÖNÜ
# ============================================================

def get_btc_direction():

    results = {}

    for interval in [
        "Min15",
        "Min60",
        "Hour4"
    ]:

        data = get_klines(
            "BTC_USDT",
            interval,
            100
        )

        if not data:
            return "NEUTRAL", results

        try:

            closes = [
                float(x)
                for x in data["close"]
            ]

            rsi = calculate_rsi(closes)

            ema20 = calculate_ema(
                closes,
                20
            )

            price = closes[-1]

            change = (
                (closes[-1] - closes[-2])
                / closes[-2]
            ) * 100

            results[interval] = {
                "rsi": rsi,
                "ema": ema20,
                "price": price,
                "change": change
            }

        except Exception:
            return "NEUTRAL", results

    bullish = 0
    bearish = 0

    # --------------------------------------------------------
    # 15M
    # --------------------------------------------------------

    x = results["Min15"]

    if x["price"] > x["ema"]:
        bullish += 1

    if x["rsi"] > 50:
        bullish += 1

    if x["change"] > 0:
        bullish += 1

    if x["price"] < x["ema"]:
        bearish += 1

    if x["rsi"] < 50:
        bearish += 1

    if x["change"] < 0:
        bearish += 1

    # --------------------------------------------------------
    # 1H
    # --------------------------------------------------------

    x = results["Min60"]

    if x["price"] > x["ema"]:
        bullish += 2

    if x["rsi"] > 50:
        bullish += 2

    if x["change"] > 0:
        bullish += 1

    if x["price"] < x["ema"]:
        bearish += 2

    if x["rsi"] < 50:
        bearish += 2

    if x["change"] < 0:
        bearish += 1

    # --------------------------------------------------------
    # 4H
    # --------------------------------------------------------

    x = results["Hour4"]

    if x["price"] > x["ema"]:
        bullish += 3

    if x["rsi"] > 50:
        bullish += 2

    if x["change"] > 0:
        bullish += 1

    if x["price"] < x["ema"]:
        bearish += 3

    if x["rsi"] < 50:
        bearish += 2

    if x["change"] < 0:
        bearish += 1

    # --------------------------------------------------------
    # YÖN
    # --------------------------------------------------------

    if bullish >= bearish + 3:
        direction = "BULLISH"

    elif bearish >= bullish + 3:
        direction = "BEARISH"

    else:
        direction = "NEUTRAL"

    return direction, results


# ============================================================
# 🔍 COIN ANALİZİ
# ============================================================

def analyze_symbol(symbol):

    try:

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

        if not data15 or not data1h or not data4h:
            return None

        close15 = [
            float(x)
            for x in data15["close"]
        ]

        volume15 = [
            float(x)
            for x in data15["vol"]
        ]

        close1h = [
            float(x)
            for x in data1h["close"]
        ]

        close4h = [
            float(x)
            for x in data4h["close"]
        ]

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

        if None in [
            rsi15,
            rsi1h,
            rsi4h
        ]:
            return None

        # ----------------------------------------------------
        # FİYAT
        # ----------------------------------------------------

        price = close15[-1]

        change15 = (
            (close15[-1] - close15[-2])
            / close15[-2]
        ) * 100

        # ----------------------------------------------------
        # HACİM
        # ----------------------------------------------------

        volume_ratio = calculate_volume_ratio(
            volume15
        )

        # ----------------------------------------------------
        # EMA
        # ----------------------------------------------------

        ema20_15 = calculate_ema(
            close15,
            20
        )

        ema20_1h = calculate_ema(
            close1h,
            20
        )

        # ----------------------------------------------------
        # LONG SKORU
        # ----------------------------------------------------

        long_score = 0

        if rsi15 >= LONG_RSI_MIN:
            long_score += 2

        if rsi15 <= LONG_RSI_MAX:
            long_score += 1

        if rsi1h > 50:
            long_score += 2

        if rsi4h > 50:
            long_score += 1

        if price > ema20_15:
            long_score += 1

        if close1h[-1] > ema20_1h:
            long_score += 1

        if volume_ratio >= VOLUME_RATIO_MIN:
            long_score += 1

        if change15 >= PRICE_CHANGE_MIN:
            long_score += 1

        # ----------------------------------------------------
        # SHORT SKORU
        # ----------------------------------------------------

        short_score = 0

        if rsi15 <= SHORT_RSI_MAX:
            short_score += 2

        if rsi15 >= SHORT_RSI_MIN:
            short_score += 1

        if rsi1h < 50:
            short_score += 2

        if rsi4h < 50:
            short_score += 1

        if price < ema20_15:
            short_score += 1

        if close1h[-1] < ema20_1h:
            short_score += 1

        if volume_ratio >= VOLUME_RATIO_MIN:
            short_score += 1

        if change15 <= -PRICE_CHANGE_MIN:
            short_score += 1

        return {
            "symbol": symbol,
            "price": price,
            "rsi15": rsi15,
            "rsi1h": rsi1h,
            "rsi4h": rsi4h,
            "volume_ratio": volume_ratio,
            "change15": change15,
            "long_score": long_score,
            "short_score": short_score
        }

    except Exception:

        return None


# ============================================================
# 💰 TP / STOP
# ============================================================

def calculate_levels(price, direction):

    if direction == "LONG":

        stop = price * 0.985

        tp1 = price * 1.020
        tp2 = price * 1.040
        tp3 = price * 1.065

    else:

        stop = price * 1.015

        tp1 = price * 0.980
        tp2 = price * 0.960
        tp3 = price * 0.935

    return stop, tp1, tp2, tp3


# ============================================================
# 📨 TELEGRAM MESAJI
# ============================================================

def format_signal(data, direction, btc_direction):

    symbol = data["symbol"]

    price = data["price"]

    score = (
        data["long_score"]
        if direction == "LONG"
        else data["short_score"]
    )

    stop, tp1, tp2, tp3 = calculate_levels(
        price,
        direction
    )

    if direction == "LONG":
        emoji = "🟢"
    else:
        emoji = "🔴"

    message = f"""
{emoji} <b>{direction} SİNYAL</b>
━━━━━━━━━━━━━━━━

💎 <b>{symbol.replace("_", "/")}</b>

⭐ Güç: <b>{score}/10</b>

🎯 Giriş: <b>{price:.8f}</b>
🛑 Stop: <b>{stop:.8f}</b>

💰 TP1: <b>{tp1:.8f}</b>
💰 TP2: <b>{tp2:.8f}</b>
💰 TP3: <b>{tp3:.8f}</b>

📊 RSI 15M: {data["rsi15"]:.1f}
📊 RSI 1H: {data["rsi1h"]:.1f}
📊 RSI 4H: {data["rsi4h"]:.1f}

🔥 Hacim: {data["volume_ratio"]:.1f}x
📈 15M: {data["change15"]:+.2f}%

🌐 BTC: {btc_direction}

━━━━━━━━━━━━━━━━
⚠️ Otomatik teknik tarama.
"""

    return message.strip()


# ============================================================
# 🧠 SİNYAL GEÇMİŞİ
# ============================================================

HISTORY_FILE = "signal_history.json"


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
                indent=2,
                ensure_ascii=False
            )

    except Exception as e:

        print(
            "Geçmiş kaydedilemedi:",
            e
        )


# ============================================================
# 🚀 ANA RADAR
# ============================================================

def run_radar():

    print()
    print("🚀 MEXC PUMP RADAR 13.0")
    print("🌐 SADECE FUTURES USDT")
    print("🚫 STOCKLAR TAMAMEN KALDIRILDI")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # --------------------------------------------------------
    # BTC
    # --------------------------------------------------------

    print("🌐 BTC yönü analiz ediliyor...")

    btc_direction, btc_data = get_btc_direction()

    print(
        f"🌐 BTC YÖNÜ: {btc_direction}"
    )

    if btc_data:

        for interval, label in [
            ("Min15", "15M"),
            ("Min60", "1H"),
            ("Hour4", "4H")
        ]:

            x = btc_data.get(interval)

            if x:

                print(
                    f"{label}: "
                    f"{x['change']:+.2f}% "
                    f"| RSI {x['rsi']:.1f}"
                )

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # --------------------------------------------------------
    # BTC NEUTRAL
    # --------------------------------------------------------

    if btc_direction == "NEUTRAL":

        print(
            "⚪ BTC NEUTRAL → İŞLEM YOK"
        )

        return

    # --------------------------------------------------------
    # FUTURES
    # --------------------------------------------------------

    symbols = get_futures_symbols()

    print(
        f"📊 Futures kontrat: "
        f"{len(symbols)}"
    )

    if not symbols:

        print(
            "❌ Futures bulunamadı."
        )

        return

    print(
        f"🔎 Tarama: {len(symbols)}"
    )

    candidates = []

    # --------------------------------------------------------
    # PARALEL TARAMA
    # --------------------------------------------------------

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

            if completed % 25 == 0:

                print(
                    f"İlerleme: "
                    f"{completed}/{len(symbols)}"
                )

            try:

                data = future.result()

                if not data:
                    continue

                # =================================================
                # BTC BULLISH → SADECE LONG
                # =================================================

                if btc_direction == "BULLISH":

                    if (
                        data["long_score"]
                        >= MIN_SCORE
                    ):

                        candidates.append(
                            (
                                data["long_score"],
                                "LONG",
                                data
                            )
                        )

                # =================================================
                # BTC BEARISH → SADECE SHORT
                # =================================================

                elif btc_direction == "BEARISH":

                    if (
                        data["short_score"]
                        >= MIN_SCORE
                    ):

                        candidates.append(
                            (
                                data["short_score"],
                                "SHORT",
                                data
                            )
                        )

            except Exception:
                continue

    # --------------------------------------------------------
    # SKOR SIRALAMA
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: x[0],
        reverse=True
    )

    print()
    print(
        f"🎯 Güçlü sinyal: "
        f"{len(candidates)}"
    )

    # --------------------------------------------------------
    # GEÇMİŞ
    # --------------------------------------------------------

    history = load_history()

    sent = 0

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    for score, direction, data in candidates:

        if sent >= MAX_SIGNALS:
            break

        symbol = data["symbol"]

        history_key = (
            f"{symbol}_{direction}"
        )

        # Aynı sinyali tekrar gönderme
        if history_key in history:

            print(
                f"⏭️ Tekrar: "
                f"{symbol} "
                f"{direction}"
            )

            continue

        print(
            f"🎯 {symbol} "
            f"{direction} "
            f"{score}/10"
        )

        message = format_signal(
            data,
            direction,
            btc_direction
        )

        if send_telegram(message):

            history[history_key] = {
                "time": time.time(),
                "direction": direction,
                "score": score
            }

            sent += 1

    save_history(history)

    print()
    print(
        f"📨 Telegram gönderilen: "
        f"{sent}"
    )

    print(
        "🏁 Tarama tamamlandı."
    )


# ============================================================
# 🔁 SÜREKLİ ÇALIŞMA
# ============================================================

def main():

    while True:

        try:

            run_radar()

        except Exception as e:

            print(
                "❌ ANA HATA:",
                e
            )

        print()
        print(
            f"⏳ {SCAN_INTERVAL} saniye "
            f"sonra yeni tarama..."
        )

        time.sleep(
            SCAN_INTERVAL
        )


# ============================================================
# ▶️ BAŞLAT
# ============================================================

if __name__ == "__main__":

    main()
