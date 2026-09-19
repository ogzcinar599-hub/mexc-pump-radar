import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC MONEY FLOW RADAR V2
#
# ANA MANTIK:
#
# 1) MEXC USDT FUTURES
# 2) YENİ POZİSYON AÇILIŞI
# 3) LONG PARA GİRİŞİ
# 4) HACİM ARTIŞI
# 5) RSI
# 6) 15M + 1H + 4H
# 7) BTC YÖNÜ
# 8) DEMAND / SUPPLY
#
# T = 1  -> BUY
# T = 2  -> SELL
#
# O = 1  -> OPEN POSITION
# O = 2  -> CLOSE POSITION
# O = 3  -> NO CHANGE
# ============================================================


# ============================================================
# MEXC YENİ FUTURES API
# ============================================================

BASE_URL = "https://api.mexc.com"


# ============================================================
# TELEGRAM
# ============================================================

BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    "BURAYA_BOT_TOKEN"
)

CHAT_ID = os.getenv(
    "CHAT_ID",
    "BURAYA_CHAT_ID"
)


# ============================================================
# GENEL AYARLAR
# ============================================================

MAX_WORKERS = 16

SCAN_INTERVAL = 60

MAX_ALERTS = 8

COOLDOWN_HOURS = 4

STATE_FILE = "money_flow_state.json"


# ============================================================
# HACİM
# ============================================================

MIN_24H_VOLUME = 100000

MIN_VOLUME_RATIO = 1.15


# ============================================================
# PARA GİRİŞİ
# ============================================================

# Minimum long open oranı
MIN_LONG_OPEN_RATIO = 53.0

# Para giriş / çıkış farkı
MIN_NET_FLOW_RATIO = 8.0


# ============================================================
# RSI
# ============================================================

MIN_RSI_15 = 43
MAX_RSI_15 = 73

MIN_RSI_1H = 43
MAX_RSI_1H = 73

MIN_RSI_4H = 42
MAX_RSI_4H = 73


# ============================================================
# PUMP FİLTRESİ
# ============================================================

MAX_15M_PUMP = 6.0

MAX_1H_PUMP = 10.0


# ============================================================
# DEALS
# ============================================================

DEALS_LIMIT = 100


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
})


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
# REQUEST
# ============================================================

def get_json(
    url,
    params=None,
    timeout=8
):

    try:

        r = session.get(
            url,
            params=params,
            timeout=timeout
        )

        if r.status_code != 200:
            return None

        data = r.json()

        if not data:
            return None

        return data

    except Exception:

        return None


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

        print()
        print(message)
        print()

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

        print(
            "Telegram hata:",
            e
        )


# ============================================================
# HİSSE / TOKENIZED STOCK FİLTRESİ
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
    "GOLD",
    "SILVER",
    "OIL"
]


def is_stock_like(symbol):

    symbol = symbol.upper()

    for word in STOCK_WORDS:

        if word in symbol:
            return True

    return False


# ============================================================
# FUTURES LİSTESİ
# ============================================================

def get_contracts():

    data = get_json(
        BASE_URL +
        "/api/v1/contract/detail"
    )

    if not data:
        return []

    contracts = data.get(
        "data",
        []
    )

    symbols = []

    for item in contracts:

        try:

            symbol = item.get(
                "symbol",
                ""
            )

            quote = item.get(
                "quoteCoin",
                ""
            )

            state = item.get(
                "state",
                0
            )

            if not symbol:
                continue

            if quote != "USDT":
                continue

            # MEXC aktif contract
            if state != 0:
                continue

            if is_stock_like(symbol):
                continue

            symbols.append(symbol)

        except Exception:

            continue

    return list(
        set(symbols)
    )


# ============================================================
# TICKER
# ============================================================

def get_ticker(symbol):

    data = get_json(
        BASE_URL +
        "/api/v1/contract/ticker",
        {
            "symbol": symbol
        }
    )

    if not data:
        return None

    return data.get(
        "data"
    )


# ============================================================
# KLINE
# ============================================================

def get_klines(
    symbol,
    interval,
    limit=80
):

    data = get_json(
        BASE_URL +
        f"/api/v1/contract/kline/{symbol}",
        {
            "interval": interval,
            "limit": limit
        }
    )

    if not data:
        return []

    d = data.get(
        "data"
    )

    if not d:
        return []

    try:

        times = d.get(
            "time",
            []
        )

        opens = d.get(
            "open",
            []
        )

        highs = d.get(
            "high",
            []
        )

        lows = d.get(
            "low",
            []
        )

        closes = d.get(
            "close",
            []
        )

        vols = d.get(
            "vol",
            []
        )

        length = min(
            len(times),
            len(opens),
            len(highs),
            len(lows),
            len(closes),
            len(vols)
        )

        result = []

        for i in range(length):

            result.append({

                "time": float(
                    times[i]
                ),

                "open": float(
                    opens[i]
                ),

                "high": float(
                    highs[i]
                ),

                "low": float(
                    lows[i]
                ),

                "close": float(
                    closes[i]
                ),

                "volume": float(
                    vols[i]
                )

            })

        return result

    except Exception:

        return []


# ============================================================
# RSI
# ============================================================

def calculate_rsi(
    closes,
    period=14
):

    if len(closes) <= period:
        return None

    gains = []
    losses = []

    for i in range(
        1,
        len(closes)
    ):

        diff = (
            closes[i]
            -
            closes[i - 1]
        )

        if diff > 0:

            gains.append(diff)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(diff)
            )

    avg_gain = (
        sum(gains[:period])
        /
        period
    )

    avg_loss = (
        sum(losses[:period])
        /
        period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            (
                avg_gain *
                (period - 1)
            )
            +
            gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss *
                (period - 1)
            )
            +
            losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = (
        avg_gain /
        avg_loss
    )

    return (
        100 -
        (
            100 /
            (1 + rs)
        )
    )


# ============================================================
# HACİM ORANI
# ============================================================

def get_volume_ratio(
    klines,
    lookback=20
):

    if len(klines) < (
        lookback + 2
    ):

        return 0

    current = klines[-1][
        "volume"
    ]

    previous = [
        x["volume"]
        for x in
        klines[
            -lookback-1:-1
        ]
    ]

    if not previous:
        return 0

    avg_volume = (
        sum(previous)
        /
        len(previous)
    )

    if avg_volume <= 0:
        return 0

    return (
        current /
        avg_volume
    )


# ============================================================
# PRICE CHANGE
# ============================================================

def get_change(
    klines,
    candles_back
):

    if len(klines) <= candles_back:
        return 0

    old = klines[
        -candles_back-1
    ]["close"]

    current = klines[
        -1
    ]["close"]

    if old <= 0:
        return 0

    return (
        (
            current - old
        )
        /
        old
    ) * 100


# ============================================================
# BTC YÖNÜ
# ============================================================

def get_btc_direction():

    try:

        k15 = get_klines(
            "BTC_USDT",
            "Min15",
            60
        )

        k1h = get_klines(
            "BTC_USDT",
            "Min60",
            60
        )

        k4h = get_klines(
            "BTC_USDT",
            "Hour4",
            60
        )

        if (
            len(k15) < 30
            or
            len(k1h) < 30
            or
            len(k4h) < 30
        ):

            return "NEUTRAL"

        r15 = calculate_rsi([
            x["close"]
            for x in k15
        ])

        r1h = calculate_rsi([
            x["close"]
            for x in k1h
        ])

        r4h = calculate_rsi([
            x["close"]
            for x in k4h
        ])

        score = 0

        if r15 > 51:
            score += 1

        elif r15 < 47:
            score -= 1

        if r1h > 51:
            score += 1

        elif r1h < 47:
            score -= 1

        if r4h > 51:
            score += 1

        elif r4h < 47:
            score -= 1

        if score >= 2:
            return "BULLISH"

        if score <= -2:
            return "BEARISH"

        return "NEUTRAL"

    except Exception:

        return "NEUTRAL"


# ============================================================
# 🔥 GERÇEK PARA GİRİŞİ
#
# T = 1 -> BUY
# T = 2 -> SELL
#
# O = 1 -> OPEN
# O = 2 -> CLOSE
# O = 3 -> NO CHANGE
#
# Biz özellikle O=1'e bakıyoruz.
# ============================================================

def get_money_flow(symbol):

    data = get_json(
        BASE_URL +
        f"/api/v1/contract/deals/{symbol}",
        {
            "limit": DEALS_LIMIT
        }
    )

    if not data:
        return None

    deals = data.get(
        "data"
    )

    if not deals:
        return None

    buy_open = 0.0
    sell_open = 0.0

    buy_close = 0.0
    sell_close = 0.0

    buy_open_count = 0
    sell_open_count = 0

    try:

        for deal in deals:

            price = float(
                deal.get(
                    "p",
                    0
                )
            )

            volume = float(
                deal.get(
                    "v",
                    0
                )
            )

            side = int(
                deal.get(
                    "T",
                    0
                )
            )

            operation = int(
                deal.get(
                    "O",
                    0
                )
            )

            if price <= 0:
                continue

            if volume <= 0:
                continue

            money = (
                price *
                volume
            )

            # =================================================
            # YENİ POZİSYON
            # =================================================

            if operation == 1:

                if side == 1:

                    buy_open += money
                    buy_open_count += 1

                elif side == 2:

                    sell_open += money
                    sell_open_count += 1

            # =================================================
            # KAPATMA
            # =================================================

            elif operation == 2:

                if side == 1:

                    buy_close += money

                elif side == 2:

                    sell_close += money

        total_open = (
            buy_open +
            sell_open
        )

        if total_open <= 0:
            return None

        long_ratio = (
            buy_open /
            total_open
        ) * 100

        short_ratio = (
            sell_open /
            total_open
        ) * 100

        net_open = (
            buy_open -
            sell_open
        )

        net_ratio = (
            net_open /
            total_open
        ) * 100

        # =================================================
        # PARA SKORU
        # =================================================

        score = 0

        # Long open oranı
        if long_ratio >= 52:
            score += 15

        if long_ratio >= 55:
            score += 10

        if long_ratio >= 60:
            score += 10

        if long_ratio >= 65:
            score += 10

        if long_ratio >= 70:
            score += 10

        # Net giriş
        if net_ratio >= 5:
            score += 5

        if net_ratio >= 10:
            score += 5

        if net_ratio >= 15:
            score += 5

        score = min(
            score,
            75
        )

        return {

            "buy_open": buy_open,

            "sell_open": sell_open,

            "buy_close": buy_close,

            "sell_close": sell_close,

            "total_open": total_open,

            "long_ratio": long_ratio,

            "short_ratio": short_ratio,

            "net_open": net_open,

            "net_ratio": net_ratio,

            "buy_open_count":
                buy_open_count,

            "sell_open_count":
                sell_open_count,

            "money_score": score

        }

    except Exception:

        return None


# ============================================================
# DEMAND / SUPPLY
# ============================================================

def detect_zone(klines):

    if len(klines) < 30:
        return "NONE"

    recent = klines[-20:]

    low = min(
        x["low"]
        for x in recent
    )

    high = max(
        x["high"]
        for x in recent
    )

    current = klines[-1][
        "close"
    ]

    rng = high - low

    if rng <= 0:
        return "NONE"

    position = (
        current - low
    ) / rng

    last = klines[-1]

    # Demand
    if position <= 0.25:

        if (
            last["close"]
            >=
            last["open"]
        ):

            return "DEMAND"

    # Supply
    if position >= 0.75:

        if (
            last["close"]
            <=
            last["open"]
        ):

            return "SUPPLY"

    return "NONE"


# ============================================================
# PARA GÜCÜ
# ============================================================

def money_strength(score):

    if score >= 60:
        return "ÇOK GÜÇLÜ"

    if score >= 50:
        return "GÜÇLÜ"

    if score >= 40:
        return "ORTA"

    return "ZAYIF"


# ============================================================
# TEK COIN ANALİZ
# ============================================================

def analyze_symbol(
    symbol,
    btc_direction
):

    try:

        # ====================================================
        # TICKER
        # ====================================================

        ticker = get_ticker(
            symbol
        )

        if not ticker:
            return None

        amount24 = float(
            ticker.get(
                "amount24",
                0
            )
        )

        if amount24 < MIN_24H_VOLUME:
            return None

        # ====================================================
        # PARA AKIŞI
        # ====================================================

        flow = get_money_flow(
            symbol
        )

        if not flow:
            return None

        # Ana para filtresi
        if (
            flow["long_ratio"]
            <
            MIN_LONG_OPEN_RATIO
        ):

            return None

        if (
            flow["net_ratio"]
            <
            MIN_NET_FLOW_RATIO
        ):

            return None

        # ====================================================
        # KLINE
        # ====================================================

        k15 = get_klines(
            symbol,
            "Min15",
            80
        )

        k1h = get_klines(
            symbol,
            "Min60",
            80
        )

        k4h = get_klines(
            symbol,
            "Hour4",
            80
        )

        if (
            len(k15) < 30
            or
            len(k1h) < 30
            or
            len(k4h) < 30
        ):

            return None

        # ====================================================
        # RSI
        # ====================================================

        rsi15 = calculate_rsi([
            x["close"]
            for x in k15
        ])

        rsi1h = calculate_rsi([
            x["close"]
            for x in k1h
        ])

        rsi4h = calculate_rsi([
            x["close"]
            for x in k4h
        ])

        if (
            rsi15 is None
            or
            rsi1h is None
            or
            rsi4h is None
        ):

            return None

        # ====================================================
        # RSI FILTRE
        # ====================================================

        if not (
            MIN_RSI_15
            <=
            rsi15
            <=
            MAX_RSI_15
        ):

            return None

        if not (
            MIN_RSI_1H
            <=
            rsi1h
            <=
            MAX_RSI_1H
        ):

            return None

        if not (
            MIN_RSI_4H
            <=
            rsi4h
            <=
            MAX_RSI_4H
        ):

            return None

        # ====================================================
        # HACİM
        # ====================================================

        vol15 = get_volume_ratio(
            k15
        )

        vol1h = get_volume_ratio(
            k1h
        )

        # Çok düşük hacim olmasın
        if vol15 < MIN_VOLUME_RATIO:

            # Ama para girişi çok güçlüyse geçir
            if flow["money_score"] < 60:
                return None

        # ====================================================
        # PRICE CHANGE
        # ====================================================

        change15 = get_change(
            k15,
            1
        )

        change1h = get_change(
            k15,
            4
        )

        change4h = get_change(
            k4h,
            1
        )

        # Zaten patlamış coinleri alma
        if change15 > MAX_15M_PUMP:
            return None

        if change1h > MAX_1H_PUMP:
            return None

        # ====================================================
        # DEMAND
        # ====================================================

        zone = detect_zone(
            k4h
        )

        # ====================================================
        # TOPLAM SKOR
        # ====================================================

        score = 0

        # PARA
        score += min(
            flow["money_score"],
            65
        )

        # HACİM
        if vol15 >= 1.15:
            score += 5

        if vol15 >= 1.50:
            score += 5

        if vol15 >= 2.00:
            score += 5

        # RSI
        if 50 <= rsi15 <= 65:
            score += 4

        if 50 <= rsi1h <= 65:
            score += 4

        if 48 <= rsi4h <= 65:
            score += 4

        # Demand
        if zone == "DEMAND":
            score += 8

        # BTC
        if btc_direction == "BULLISH":
            score += 5

        elif btc_direction == "BEARISH":
            score -= 5

        # ====================================================
        # SON FİLTRE
        # ====================================================

        if score < 60:
            return None

        # ====================================================
        # RESULT
        # ====================================================

        return {

            "symbol": symbol,

            "score": score,

            "money_score":
                flow["money_score"],

            "buy_open":
                flow["buy_open"],

            "sell_open":
                flow["sell_open"],

            "long_ratio":
                flow["long_ratio"],

            "short_ratio":
                flow["short_ratio"],

            "net_open":
                flow["net_open"],

            "net_ratio":
                flow["net_ratio"],

            "volume_ratio":
                vol15,

            "volume_1h":
                vol1h,

            "rsi15":
                rsi15,

            "rsi1h":
                rsi1h,

            "rsi4h":
                rsi4h,

            "change15":
                change15,

            "change1h":
                change1h,

            "change4h":
                change4h,

            "zone":
                zone,

            "btc":
                btc_direction

        }

    except Exception:

        return None


# ============================================================
# MONEY FORMAT
# ============================================================

def money_format(value):

    if value >= 1_000_000:

        return (
            f"{value / 1_000_000:.2f}M"
        )

    if value >= 1_000:

        return (
            f"{value / 1_000:.1f}K"
        )

    return (
        f"{value:.0f}"
    )


# ============================================================
# TELEGRAM MESAJ
# ============================================================

def create_message(x):

    strength = money_strength(
        x["money_score"]
    )

    if x["zone"] == "DEMAND":

        zone = "🟢 DEMAND"

    elif x["zone"] == "SUPPLY":

        zone = "🔴 SUPPLY"

    else:

        zone = "⚪ YOK"

    if x["btc"] == "BULLISH":

        btc = "🟢 BTC BULLISH"

    elif x["btc"] == "BEARISH":

        btc = "🔴 BTC BEARISH"

    else:

        btc = "⚪ BTC NEUTRAL"

    return f"""
🚨 <b>PARA GİRİŞİ</b>

🟢 <b>{x["symbol"]}</b>

💰 Para: <b>{strength}</b>
🟢 Long Açılış: <b>{money_format(x["buy_open"])}</b>
🔴 Short Açılış: <b>{money_format(x["sell_open"])}</b>

📊 Long Oranı: <b>%{x["long_ratio"]:.1f}</b>
💵 Net Giriş: <b>{money_format(x["net_open"])}</b>

📈 Hacim: <b>{x["volume_ratio"]:.2f}x</b>

RSI 15M: <b>{x["rsi15"]:.1f}</b>
RSI 1H: <b>{x["rsi1h"]:.1f}</b>
RSI 4H: <b>{x["rsi4h"]:.1f}</b>

🎯 Bölge: <b>{zone}</b>
{btc}

🔥 <b>SKOR: {x["score"]}</b>
""".strip()


# ============================================================
# COOLDOWN
# ============================================================

def can_send(symbol):

    last = STATE.get(
        symbol,
        0
    )

    now = time.time()

    return (
        now - last
        >=
        COOLDOWN_HOURS * 3600
    )


def mark_sent(symbol):

    STATE[symbol] = time.time()

    save_state(
        STATE
    )


# ============================================================
# TARAMA
# ============================================================

def scan():

    print()
    print(
        "=" * 65
    )

    print(
        "🚀 MONEY FLOW + VOLUME RADAR V2"
    )

    print(
        "=" * 65
    )

    # ========================================================
    # BTC
    # ========================================================

    btc = get_btc_direction()

    print(
        "BTC YÖNÜ:",
        btc
    )

    # ========================================================
    # CONTRACT
    # ========================================================

    symbols = get_contracts()

    print(
        "Toplam Futures:",
        len(symbols)
    )

    if not symbols:

        print(
            "❌ Futures listesi alınamadı."
        )

        return

    # ========================================================
    # ANALİZ
    # ========================================================

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        future_map = {

            executor.submit(
                analyze_symbol,
                symbol,
                btc
            ):
            symbol

            for symbol in symbols
        }

        for future in as_completed(
            future_map
        ):

            try:

                result = future.result()

                if result:

                    results.append(
                        result
                    )

            except Exception:

                pass

    # ========================================================
    # SIRALA
    # ========================================================

    results.sort(
        key=lambda x: (
            x["score"],
            x["money_score"],
            x["net_ratio"],
            x["volume_ratio"]
        ),
        reverse=True
    )

    print(
        "🔥 Güçlü sonuç:",
        len(results)
    )

    # ========================================================
    # ALARM
    # ========================================================

    sent = 0

    for result in results:

        symbol = result[
            "symbol"
        ]

        if not can_send(
            symbol
        ):

            continue

        message = create_message(
            result
        )

        print()
        print(
            symbol,
            "| SCORE:",
            result["score"],
            "| MONEY:",
            result["money_score"],
            "| LONG:",
            round(
                result["long_ratio"],
                1
            ),
            "| VOL:",
            round(
                result["volume_ratio"],
                2
            )
        )

        send_telegram(
            message
        )

        mark_sent(
            symbol
        )

        sent += 1

        if sent >= MAX_ALERTS:

            break

    print()
    print(
        "📨 Gönderilen alarm:",
        sent
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "=========================================="
    )

    print(
        "🚀 MEXC MONEY FLOW RADAR V2"
    )

    print(
        "=========================================="
    )

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


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
