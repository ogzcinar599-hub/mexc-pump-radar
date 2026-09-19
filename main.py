import os
import json
import math
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 🚀 MEXC MONEY FLOW + VOLUME + DEMAND/SUPPLY RADAR
# ============================================================

BASE_URL = "https://contract.mexc.com"

# ============================================================
# TELEGRAM
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "BURAYA_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID", "BURAYA_CHAT_ID")

# ============================================================
# AYARLAR
# ============================================================

MAX_WORKERS = 12

SCAN_INTERVAL = 60

# Minimum 24h USDT hacmi
MIN_24H_VOLUME = 100000

# Hacim normalin kaç katı olmalı?
MIN_VOLUME_RATIO = 1.30

# Para giriş minimum skoru
MIN_MONEY_SCORE = 55

# Toplam sinyal skoru
MIN_TOTAL_SCORE = 68

# RSI
MIN_RSI_15 = 45
MAX_RSI_15 = 72

MIN_RSI_1H = 45
MAX_RSI_1H = 72

MIN_RSI_4H = 45
MAX_RSI_4H = 72

# Son 15 dakikadaki maksimum pump
MAX_15M_PUMP = 5.0

# Son 1 saatte maksimum pump
MAX_1H_PUMP = 8.0

# Aynı coine tekrar alarm vermeme
COOLDOWN_HOURS = 4

# Telegram'da tek taramada maksimum alarm
MAX_ALERTS = 8

# Kaç işlem incelenecek
DEALS_LIMIT = 100

# ============================================================
# DOSYA
# ============================================================

STATE_FILE = "money_flow_state.json"


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
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

        return r.json()

    except Exception:
        return None


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

    except Exception:
        pass


STATE = load_state()


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if (
        not BOT_TOKEN
        or BOT_TOKEN == "BURAYA_BOT_TOKEN"
        or not CHAT_ID
        or CHAT_ID == "BURAYA_CHAT_ID"
    ):
        print(message)
        return

    url = (
        f"https://api.telegram.org/bot"
        f"{BOT_TOKEN}/sendMessage"
    )

    try:

        session.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=10
        )

    except Exception as e:

        print("Telegram hata:", e)


# ============================================================
# SYMBOL FİLTRESİ
# ============================================================

STOCK_WORDS = [
    "AAPL",
    "TSLA",
    "NVDA",
    "MSFT",
    "AMZN",
    "META",
    "GOOG",
    "GOOGL",
    "NFLX",
    "COIN",
    "MSTR",
    "AMD",
    "INTC",
    "BA",
    "DIS",
    "NIO",
    "BABA",
    "PDD",
    "PLTR",
    "QQQ",
    "SPY",
    "IWM",
    "DIA",
    "XAU",
    "XAG",
    "GOLD",
    "SILVER",
    "OIL"
]


def is_stock_like(symbol):

    s = symbol.upper()

    for word in STOCK_WORDS:

        if word in s:
            return True

    return False


# ============================================================
# KONTRATLARI AL
# ============================================================

def get_contracts():

    data = get_json(
        BASE_URL + "/api/v1/contract/detail"
    )

    if not data:
        return []

    result = data.get("data", [])

    symbols = []

    for x in result:

        try:

            symbol = x.get("symbol", "")

            quote = x.get("quoteCoin", "")

            state = x.get("state", 0)

            if not symbol:
                continue

            if quote != "USDT":
                continue

            if state != 0:
                continue

            if is_stock_like(symbol):
                continue

            symbols.append(symbol)

        except Exception:
            continue

    return list(set(symbols))


# ============================================================
# TICKER
# ============================================================

def get_ticker(symbol):

    data = get_json(
        BASE_URL + "/api/v1/contract/ticker",
        params={
            "symbol": symbol
        }
    )

    if not data:
        return None

    d = data.get("data")

    if not d:
        return None

    return d


# ============================================================
# KLINE
# ============================================================

def get_klines(symbol, interval, limit=100):

    data = get_json(
        BASE_URL + "/api/v1/contract/kline/" + symbol,
        params={
            "interval": interval,
            "limit": limit
        }
    )

    if not data:
        return []

    d = data.get("data")

    if not d:
        return []

    try:

        times = d.get("time", [])
        opens = d.get("open", [])
        highs = d.get("high", [])
        lows = d.get("low", [])
        closes = d.get("close", [])
        vols = d.get("vol", [])

        result = []

        length = min(
            len(times),
            len(opens),
            len(highs),
            len(lows),
            len(closes),
            len(vols)
        )

        for i in range(length):

            result.append({
                "time": float(times[i]),
                "open": float(opens[i]),
                "high": float(highs[i]),
                "low": float(lows[i]),
                "close": float(closes[i]),
                "volume": float(vols[i])
            })

        return result

    except Exception:

        return []


# ============================================================
# RSI
# ============================================================

def calculate_rsi(closes, period=14):

    if len(closes) <= period:
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

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

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
# HACİM ORANI
# ============================================================

def volume_ratio(klines, lookback=20):

    if len(klines) < lookback + 2:
        return 0

    current = klines[-1]["volume"]

    previous = [
        x["volume"]
        for x in klines[-lookback-1:-1]
    ]

    avg_volume = sum(previous) / len(previous)

    if avg_volume <= 0:
        return 0

    return current / avg_volume


# ============================================================
# PRICE CHANGE
# ============================================================

def price_change(klines, candles_back):

    if len(klines) <= candles_back:
        return 0

    old_price = klines[-candles_back-1]["close"]
    current = klines[-1]["close"]

    if old_price <= 0:
        return 0

    return (
        (current - old_price)
        / old_price
    ) * 100


# ============================================================
# BTC YÖNÜ
# ============================================================

def get_btc_direction():

    try:

        k15 = get_klines(
            "BTC_USDT",
            "Min15",
            80
        )

        k1h = get_klines(
            "BTC_USDT",
            "Min60",
            80
        )

        k4h = get_klines(
            "BTC_USDT",
            "Hour4",
            80
        )

        if (
            len(k15) < 30
            or len(k1h) < 30
            or len(k4h) < 30
        ):
            return "NEUTRAL"

        c15 = [x["close"] for x in k15]
        c1h = [x["close"] for x in k1h]
        c4h = [x["close"] for x in k4h]

        r15 = calculate_rsi(c15)
        r1h = calculate_rsi(c1h)
        r4h = calculate_rsi(c4h)

        score = 0

        if r15 and r15 > 50:
            score += 1
        elif r15 and r15 < 48:
            score -= 1

        if r1h and r1h > 50:
            score += 1
        elif r1h and r1h < 48:
            score -= 1

        if r4h and r4h > 50:
            score += 1
        elif r4h and r4h < 48:
            score -= 1

        if score >= 2:
            return "BULLISH"

        if score <= -2:
            return "BEARISH"

        return "NEUTRAL"

    except Exception:

        return "NEUTRAL"


# ============================================================
# OPEN FLOW / PARA AKIŞI
# ============================================================

def get_open_flow(symbol):

    data = get_json(
        BASE_URL + "/api/v1/contract/deals/" + symbol,
        params={
            "limit": DEALS_LIMIT
        }
    )

    if not data:
        return None

    deals = data.get("data")

    if not deals:
        return None

    buy_money = 0.0
    sell_money = 0.0

    buy_count = 0
    sell_count = 0

    total_money = 0.0

    try:

        for deal in deals:

            price = float(
                deal.get("p", 0)
            )

            volume = float(
                deal.get("v", 0)
            )

            side = deal.get("T")

            money = price * volume

            if money <= 0:
                continue

            total_money += money

            # MEXC deal side:
            # 1 = buy
            # 2 = sell

            if str(side) == "1":

                buy_money += money
                buy_count += 1

            elif str(side) == "2":

                sell_money += money
                sell_count += 1

        if total_money <= 0:
            return None

        net_flow = buy_money - sell_money

        buy_ratio = (
            buy_money / total_money
        ) * 100

        sell_ratio = (
            sell_money / total_money
        ) * 100

        # ====================================================
        # PARA GİRİŞ SKORU
        # ====================================================

        score = 0

        # %55 üzeri alış baskısı
        if buy_ratio >= 55:
            score += 20

        if buy_ratio >= 60:
            score += 10

        if buy_ratio >= 65:
            score += 10

        if buy_ratio >= 70:
            score += 10

        # Net para akışı
        if net_flow > 0:
            score += 10

        if buy_count > sell_count:
            score += 5

        # Maksimum 65
        score = min(score, 65)

        return {
            "buy_money": buy_money,
            "sell_money": sell_money,
            "net_flow": net_flow,
            "buy_ratio": buy_ratio,
            "sell_ratio": sell_ratio,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "total_money": total_money,
            "money_score": score
        }

    except Exception:

        return None


# ============================================================
# DEMAND / SUPPLY
# ============================================================

def detect_demand_supply(klines):

    if len(klines) < 30:
        return "NONE"

    recent = klines[-20:]

    lows = [
        x["low"]
        for x in recent
    ]

    highs = [
        x["high"]
        for x in recent
    ]

    current = klines[-1]["close"]

    low_zone = min(lows)
    high_zone = max(highs)

    range_size = high_zone - low_zone

    if range_size <= 0:
        return "NONE"

    # Demand'a yakınlık
    demand_distance = (
        current - low_zone
    ) / range_size

    # Supply'a yakınlık
    supply_distance = (
        high_zone - current
    ) / range_size

    # Alt bölgenin %25'i
    if demand_distance <= 0.25:

        # Son mum yükselişse demand teyidi
        if klines[-1]["close"] >= klines[-1]["open"]:
            return "DEMAND"

    # Üst bölgenin %25'i
    if supply_distance <= 0.25:

        if klines[-1]["close"] <= klines[-1]["open"]:
            return "SUPPLY"

    return "NONE"


# ============================================================
# MONEY FLOW DERECESİ
# ============================================================

def money_strength(score):

    if score >= 55:
        return "ÇOK GÜÇLÜ"

    if score >= 45:
        return "GÜÇLÜ"

    if score >= 35:
        return "ORTA"

    return "ZAYIF"


# ============================================================
# TEK COIN ANALİZİ
# ============================================================

def analyze_symbol(symbol, btc_direction):

    try:

        ticker = get_ticker(symbol)

        if not ticker:
            return None

        # ====================================================
        # 24H HACİM
        # ====================================================

        amount = float(
            ticker.get("amount24", 0)
        )

        if amount < MIN_24H_VOLUME:
            return None

        # ====================================================
        # KLINE
        # ====================================================

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
            100
        )

        if (
            len(k15) < 40
            or len(k1h) < 40
            or len(k4h) < 40
        ):
            return None

        # ====================================================
        # RSI
        # ====================================================

        rsi15 = calculate_rsi(
            [x["close"] for x in k15]
        )

        rsi1h = calculate_rsi(
            [x["close"] for x in k1h]
        )

        rsi4h = calculate_rsi(
            [x["close"] for x in k4h]
        )

        if (
            rsi15 is None
            or rsi1h is None
            or rsi4h is None
        ):
            return None

        # RSI filtre
        if not (
            MIN_RSI_15 <= rsi15 <= MAX_RSI_15
        ):
            return None

        if not (
            MIN_RSI_1H <= rsi1h <= MAX_RSI_1H
        ):
            return None

        if not (
            MIN_RSI_4H <= rsi4h <= MAX_RSI_4H
        ):
            return None

        # ====================================================
        # HACİM
        # ====================================================

        vr15 = volume_ratio(k15)

        vr1h = volume_ratio(k1h)

        if vr15 < MIN_VOLUME_RATIO:
            return None

        # ====================================================
        # FİYAT HAREKETİ
        # ====================================================

        change15 = price_change(
            k15,
            1
        )

        change1h = price_change(
            k15,
            4
        )

        change4h = price_change(
            k4h,
            1
        )

        # Çoktan pump yapmış coinleri alma
        if change15 > MAX_15M_PUMP:
            return None

        if change1h > MAX_1H_PUMP:
            return None

        # ====================================================
        # PARA AKIŞI
        # ====================================================

        flow = get_open_flow(symbol)

        if not flow:
            return None

        money_score = flow["money_score"]

        if money_score < MIN_MONEY_SCORE:
            return None

        # ====================================================
        # DEMAND / SUPPLY
        # ====================================================

        zone = detect_demand_supply(k4h)

        # ====================================================
        # TOPLAM SKOR
        # ====================================================

        total_score = 0

        # Para
        total_score += min(
            money_score,
            65
        )

        # Hacim
        if vr15 >= 1.30:
            total_score += 5

        if vr15 >= 1.60:
            total_score += 5

        if vr15 >= 2.00:
            total_score += 5

        # RSI
        if 50 <= rsi15 <= 65:
            total_score += 5

        if 50 <= rsi1h <= 65:
            total_score += 5

        # 4H trend
        if rsi4h >= 50:
            total_score += 5

        # Demand bonus
        if zone == "DEMAND":
            total_score += 10

        # BTC
        if btc_direction == "BULLISH":
            total_score += 5

        # ====================================================
        # BTC BEARISH İSE LONG ZAYIFLAT
        # ====================================================

        if btc_direction == "BEARISH":

            total_score -= 10

        if total_score < MIN_TOTAL_SCORE:
            return None

        # ====================================================
        # SONUÇ
        # ====================================================

        return {
            "symbol": symbol,
            "money_score": money_score,
            "total_score": total_score,

            "buy_money": flow["buy_money"],
            "sell_money": flow["sell_money"],
            "net_flow": flow["net_flow"],

            "buy_ratio": flow["buy_ratio"],
            "sell_ratio": flow["sell_ratio"],

            "volume_ratio": vr15,

            "rsi15": rsi15,
            "rsi1h": rsi1h,
            "rsi4h": rsi4h,

            "change15": change15,
            "change1h": change1h,
            "change4h": change4h,

            "zone": zone,

            "btc": btc_direction
        }

    except Exception as e:

        return None


# ============================================================
# PARA FORMAT
# ============================================================

def format_money(value):

    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"

    if value >= 1_000:
        return f"{value / 1_000:.1f}K"

    return f"{value:.0f}"


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def create_message(x):

    symbol = x["symbol"]

    money_strength_text = money_strength(
        x["money_score"]
    )

    if x["zone"] == "DEMAND":

        zone_text = "🟢 DEMAND"

    elif x["zone"] == "SUPPLY":

        zone_text = "🔴 SUPPLY"

    else:

        zone_text = "⚪ BÖLGE YOK"

    if x["btc"] == "BULLISH":

        btc_text = "🟢 BTC BULLISH"

    elif x["btc"] == "BEARISH":

        btc_text = "🔴 BTC BEARISH"

    else:

        btc_text = "⚪ BTC NEUTRAL"

    message = f"""
🚨 <b>PARA GİRİŞİ + HACİM</b>

🟢 <b>{symbol}</b>

💰 Para Akışı: <b>{money_strength_text}</b>
💵 Alış: <b>{format_money(x["buy_money"])}</b>
💸 Satış: <b>{format_money(x["sell_money"])}</b>

📊 Alış Oranı: <b>%{x["buy_ratio"]:.1f}</b>
📈 Hacim: <b>{x["volume_ratio"]:.2f}x</b>

📊 RSI 15M: <b>{x["rsi15"]:.1f}</b>
📊 RSI 1H: <b>{x["rsi1h"]:.1f}</b>
📊 RSI 4H: <b>{x["rsi4h"]:.1f}</b>

🎯 Bölge: <b>{zone_text}</b>
{btc_text}

🔥 Toplam Skor: <b>{x["total_score"]}</b>
"""

    return message.strip()


# ============================================================
# COOLDOWN
# ============================================================

def can_send(symbol):

    now = time.time()

    last = STATE.get(symbol, 0)

    cooldown = COOLDOWN_HOURS * 3600

    if now - last < cooldown:
        return False

    return True


def mark_sent(symbol):

    STATE[symbol] = time.time()

    save_state(STATE)


# ============================================================
# ANA TARAMA
# ============================================================

def scan():

    print()
    print("=" * 60)
    print("🚀 MONEY FLOW + VOLUME RADAR")
    print("=" * 60)

    btc_direction = get_btc_direction()

    print(
        "BTC YÖNÜ:",
        btc_direction
    )

    symbols = get_contracts()

    if not symbols:

        print("Coin bulunamadı.")
        return

    print(
        "Taranacak futures:",
        len(symbols)
    )

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_symbol,
                symbol,
                btc_direction
            ): symbol
            for symbol in symbols
        }

        for future in as_completed(futures):

            try:

                result = future.result()

                if result:
                    results.append(result)

            except Exception:
                pass

    # ========================================================
    # SKORA GÖRE SIRALA
    # ========================================================

    results.sort(
        key=lambda x: (
            x["total_score"],
            x["money_score"],
            x["volume_ratio"]
        ),
        reverse=True
    )

    print(
        "Güçlü sonuç:",
        len(results)
    )

    alerts = 0

    for result in results:

        symbol = result["symbol"]

        if not can_send(symbol):
            continue

        message = create_message(result)

        print()
        print(
            symbol,
            "| SCORE:",
            result["total_score"],
            "| MONEY:",
            result["money_score"],
            "| VOL:",
            round(
                result["volume_ratio"],
                2
            )
        )

        send_telegram(message)

        mark_sent(symbol)

        alerts += 1

        if alerts >= MAX_ALERTS:
            break


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("==========================================")
    print("🚀 MEXC MONEY FLOW RADAR")
    print("==========================================")
    print()

    while True:

        try:

            scan()

        except KeyboardInterrupt:

            print(
                "Program kapatıldı."
            )

            break

        except Exception as e:

            print(
                "ANA HATA:",
                e
            )

        print()
        print(
            f"⏳ {SCAN_INTERVAL} saniye bekleniyor..."
        )

        time.sleep(
            SCAN_INTERVAL
        )


if __name__ == "__main__":
    main()
