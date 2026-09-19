import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC MONEY FLOW RADAR V3
#
# PARA GİRİŞİ + GERÇEK USDT NOTIONAL + HACİM + RSI
#
# SADECE:
# ✅ MEXC USDT FUTURES
# ✅ Yeni pozisyon açılışları
# ✅ Long / Short para akışı
# ✅ Gerçek USDT notional
# ✅ Hacim artışı
# ✅ RSI
# ✅ 15M + 1H + 4H
# ✅ BTC yönü
# ✅ Demand / Supply
# ✅ Cooldown
#
# T = 1 -> BUY
# T = 2 -> SELL
#
# O = 1 -> OPEN
# O = 2 -> CLOSE
# O = 3 -> NO CHANGE
# ============================================================


# ============================================================
# MEXC FUTURES API
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
# 24H HACİM
# ============================================================

MIN_24H_VOLUME = 100000


# ============================================================
# ANLIK HACİM
#
# 0.38x GİBİ HACİMLER ARTIK GEÇMEYECEK
# ============================================================

MIN_VOLUME_RATIO = 1.20


# ============================================================
# PARA GİRİŞİ
# ============================================================

# Açılış işlemlerinde minimum Long oranı
MIN_LONG_RATIO = 53.0

# Long - Short net farkı
MIN_NET_RATIO = 5.0

# Minimum gerçek açılış notional
MIN_OPEN_NOTIONAL = 50000


# ============================================================
# RSI
# ============================================================

MIN_RSI_15 = 43
MAX_RSI_15 = 72

MIN_RSI_1H = 43
MAX_RSI_1H = 68

MIN_RSI_4H = 42
MAX_RSI_4H = 68


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

        response = session.get(
            url,
            params=params,
            timeout=timeout
        )

        if response.status_code != 200:
            return None

        data = response.json()

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

        response = session.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=10
        )

        if response.status_code != 200:

            print(
                "Telegram hata:",
                response.text
            )

    except Exception as e:

        print(
            "Telegram hata:",
            e
        )


# ============================================================
# TOKENIZED STOCK FİLTRESİ
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
# FUTURES KONTRATLARI
# ============================================================

def get_contracts():

    data = get_json(
        BASE_URL +
        "/api/v1/contract/detail"
    )

    if not data:
        return {}

    contracts = data.get(
        "data",
        []
    )

    result = {}

    for item in contracts:

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

            contract_size = float(
                item.get(
                    "contractSize",
                    0
                )
            )

            if not symbol:
                continue

            if quote_coin != "USDT":
                continue

            if state != 0:
                continue

            if contract_size <= 0:
                continue

            if is_stock_like(symbol):
                continue

            result[symbol] = {

                "contract_size":
                    contract_size,

                "base_coin":
                    item.get(
                        "baseCoin",
                        ""
                    )

            }

        except Exception:

            continue

    return result


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

        volumes = d.get(
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

        result = []

        for i in range(length):

            result.append({

                "time":
                    float(times[i]),

                "open":
                    float(opens[i]),

                "high":
                    float(highs[i]),

                "low":
                    float(lows[i]),

                "close":
                    float(closes[i]),

                "volume":
                    float(volumes[i])

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

        difference = (
            closes[i]
            -
            closes[i - 1]
        )

        if difference > 0:

            gains.append(
                difference
            )

            losses.append(0)

        else:

            gains.append(0)

            losses.append(
                abs(difference)
            )

    average_gain = (
        sum(gains[:period])
        /
        period
    )

    average_loss = (
        sum(losses[:period])
        /
        period
    )

    for i in range(
        period,
        len(gains)
    ):

        average_gain = (
            (
                average_gain *
                (period - 1)
            )
            +
            gains[i]
        ) / period

        average_loss = (
            (
                average_loss *
                (period - 1)
            )
            +
            losses[i]
        ) / period

    if average_loss == 0:
        return 100

    rs = (
        average_gain /
        average_loss
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

def volume_ratio(
    klines,
    lookback=20
):

    if len(klines) < (
        lookback + 2
    ):

        return 0

    current_volume = (
        klines[-1]["volume"]
    )

    previous_volumes = [

        x["volume"]

        for x in
        klines[
            -lookback - 1:-1
        ]

    ]

    if not previous_volumes:
        return 0

    average_volume = (
        sum(previous_volumes)
        /
        len(previous_volumes)
    )

    if average_volume <= 0:
        return 0

    return (
        current_volume /
        average_volume
    )


# ============================================================
# FİYAT DEĞİŞİMİ
# ============================================================

def price_change(
    klines,
    candles_back
):

    if len(klines) <= candles_back:
        return 0

    old_price = klines[
        -candles_back - 1
    ]["close"]

    current_price = klines[
        -1
    ]["close"]

    if old_price <= 0:
        return 0

    return (
        (
            current_price -
            old_price
        )
        /
        old_price
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

            return "NEUTRAL"

        score = 0

        if rsi15 > 51:

            score += 1

        elif rsi15 < 47:

            score -= 1

        if rsi1h > 51:

            score += 1

        elif rsi1h < 47:

            score -= 1

        if rsi4h > 51:

            score += 1

        elif rsi4h < 47:

            score -= 1

        if score >= 2:

            return "BULLISH"

        if score <= -2:

            return "BEARISH"

        return "NEUTRAL"

    except Exception:

        return "NEUTRAL"


# ============================================================
# 🔥 PARA GİRİŞİ
#
# T = 1 BUY
# T = 2 SELL
#
# O = 1 OPEN
#
# GERÇEK NOTIONAL:
#
# contracts × contractSize × price
# ============================================================

def get_money_flow(
    symbol,
    contract_size
):

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

    long_open = 0.0
    short_open = 0.0

    long_count = 0
    short_count = 0

    total_open = 0.0

    try:

        for deal in deals:

            price = float(
                deal.get(
                    "p",
                    0
                )
            )

            contracts = float(
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

            if contracts <= 0:
                continue

            # SADECE YENİ POZİSYON
            if operation != 1:
                continue

            # GERÇEK USDT DEĞERİ
            notional = (
                contracts
                *
                contract_size
                *
                price
            )

            if notional <= 0:
                continue

            total_open += notional

            # BUY OPEN
            if side == 1:

                long_open += notional

                long_count += 1

            # SELL OPEN
            elif side == 2:

                short_open += notional

                short_count += 1

        if total_open <= 0:
            return None

        long_ratio = (
            long_open /
            total_open
        ) * 100

        short_ratio = (
            short_open /
            total_open
        ) * 100

        net_open = (
            long_open -
            short_open
        )

        net_ratio = (
            net_open /
            total_open
        ) * 100

        # ====================================================
        # MONEY SCORE
        # ====================================================

        money_score = 0

        if long_ratio >= 52:
            money_score += 10

        if long_ratio >= 55:
            money_score += 10

        if long_ratio >= 60:
            money_score += 10

        if long_ratio >= 65:
            money_score += 10

        if long_ratio >= 70:
            money_score += 10

        if net_ratio >= 5:
            money_score += 5

        if net_ratio >= 10:
            money_score += 5

        if net_ratio >= 15:
            money_score += 5

        money_score = min(
            money_score,
            75
        )

        return {

            "long_open":
                long_open,

            "short_open":
                short_open,

            "total_open":
                total_open,

            "long_ratio":
                long_ratio,

            "short_ratio":
                short_ratio,

            "net_open":
                net_open,

            "net_ratio":
                net_ratio,

            "long_count":
                long_count,

            "short_count":
                short_count,

            "money_score":
                money_score

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

    lowest = min(
        x["low"]
        for x in recent
    )

    highest = max(
        x["high"]
        for x in recent
    )

    current = klines[-1][
        "close"
    ]

    price_range = (
        highest -
        lowest
    )

    if price_range <= 0:
        return "NONE"

    position = (
        current -
        lowest
    ) / price_range

    last = klines[-1]

    # DEMAND
    if position <= 0.25:

        if (
            last["close"]
            >=
            last["open"]
        ):

            return "DEMAND"

    # SUPPLY
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
# TEK COIN ANALİZİ
# ============================================================

def analyze_symbol(
    symbol,
    contract_info,
    btc_direction
):

    try:

        contract_size = (
            contract_info[
                "contract_size"
            ]
        )

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
            symbol,
            contract_size
        )

        if not flow:
            return None

        # ====================================================
        # GERÇEK PARA FİLTRESİ
        # ====================================================

        if (
            flow["total_open"]
            <
            MIN_OPEN_NOTIONAL
        ):

            return None

        # ====================================================
        # LONG ORANI
        # ====================================================

        if (
            flow["long_ratio"]
            <
            MIN_LONG_RATIO
        ):

            return None

        # ====================================================
        # NET PARA
        # ====================================================

        if (
            flow["net_ratio"]
            <
            MIN_NET_RATIO
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
        # RSI FİLTRE
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

        volume15 = volume_ratio(
            k15
        )

        volume1h = volume_ratio(
            k1h
        )

        # ÖNEMLİ:
        #
        # 0.38x artık GEÇEMEZ.
        #
        if volume15 < MIN_VOLUME_RATIO:

            return None

        # ====================================================
        # PRICE CHANGE
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

        # Çoktan patlamış coinleri alma
        if change15 > MAX_15M_PUMP:

            return None

        if change1h > MAX_1H_PUMP:

            return None

        # ====================================================
        # DEMAND / SUPPLY
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
        if volume15 >= 1.20:

            score += 5

        if volume15 >= 1.50:

            score += 5

        if volume15 >= 2.00:

            score += 5

        if volume15 >= 3.00:

            score += 5

        # RSI
        if 50 <= rsi15 <= 63:

            score += 4

        if 50 <= rsi1h <= 63:

            score += 4

        if 48 <= rsi4h <= 63:

            score += 4

        # DEMAND
        if zone == "DEMAND":

            score += 8

        # BTC
        if btc_direction == "BULLISH":

            score += 5

        elif btc_direction == "BEARISH":

            score -= 5

        # ====================================================
        # MINIMUM SKOR
        # ====================================================

        if score < 60:

            return None

        return {

            "symbol":
                symbol,

            "score":
                score,

            "money_score":
                flow["money_score"],

            "long_open":
                flow["long_open"],

            "short_open":
                flow["short_open"],

            "total_open":
                flow["total_open"],

            "long_ratio":
                flow["long_ratio"],

            "short_ratio":
                flow["short_ratio"],

            "net_open":
                flow["net_open"],

            "net_ratio":
                flow["net_ratio"],

            "volume_ratio":
                volume15,

            "volume_1h":
                volume1h,

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
                btc_direction,

            "contract_size":
                contract_size

        }

    except Exception:

        return None


# ============================================================
# PARA FORMAT
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
# TELEGRAM MESAJI
# ============================================================

def create_message(x):

    strength = money_strength(
        x["money_score"]
    )

    # DEMAND / SUPPLY
    if x["zone"] == "DEMAND":

        zone_text = "🟢 DEMAND"

    elif x["zone"] == "SUPPLY":

        zone_text = "🔴 SUPPLY"

    else:

        zone_text = "⚪ YOK"

    # BTC
    if x["btc"] == "BULLISH":

        btc_text = "🟢 BTC BULLISH"

    elif x["btc"] == "BEARISH":

        btc_text = "🔴 BTC BEARISH"

    else:

        btc_text = "⚪ BTC NEUTRAL"

    message = f"""
🚨 <b>PARA GİRİŞİ + HACİM</b>

🟢 <b>{x["symbol"]}</b>

💰 Para: <b>{strength}</b>

🟢 Long Açılış:
<b>{money_format(x["long_open"])} USDT</b>

🔴 Short Açılış:
<b>{money_format(x["short_open"])} USDT</b>

💵 Net Açılış:
<b>+{money_format(x["net_open"])} USDT</b>

📊 Long Oranı:
<b>%{x["long_ratio"]:.1f}</b>

📈 Hacim:
<b>{x["volume_ratio"]:.2f}x</b>

RSI 15M:
<b>{x["rsi15"]:.1f}</b>

RSI 1H:
<b>{x["rsi1h"]:.1f}</b>

RSI 4H:
<b>{x["rsi4h"]:.1f}</b>

🎯 Bölge:
<b>{zone_text}</b>

{btc_text}

🔥 <b>SKOR: {x["score"]}</b>
""".strip()

    return message


# ============================================================
# COOLDOWN
# ============================================================

def can_send(symbol):

    last_time = STATE.get(
        symbol,
        0
    )

    current_time = time.time()

    return (
        current_time -
        last_time
        >=
        COOLDOWN_HOURS * 3600
    )


def mark_sent(symbol):

    STATE[symbol] = time.time()

    save_state(
        STATE
    )


# ============================================================
# ANA TARAMA
# ============================================================

def scan():

    print()
    print(
        "=" * 70
    )

    print(
        "🚀 MEXC MONEY FLOW RADAR V3"
    )

    print(
        "=" * 70
    )

    # ========================================================
    # BTC
    # ========================================================

    btc_direction = (
        get_btc_direction()
    )

    print(
        "BTC YÖNÜ:",
        btc_direction
    )

    # ========================================================
    # FUTURES
    # ========================================================

    contracts = get_contracts()

    print(
        "Futures:",
        len(contracts)
    )

    if not contracts:

        print(
            "❌ Futures listesi alınamadı."
        )

        return

    # ========================================================
    # ANALİZ
    # ========================================================

    results = []

    symbols = list(
        contracts.keys()
    )

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        future_map = {}

        for symbol in symbols:

            future = executor.submit(
                analyze_symbol,
                symbol,
                contracts[symbol],
                btc_direction
            )

            future_map[future] = symbol

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
    # SIRALAMA
    # ========================================================

    results.sort(
        key=lambda x: (
            x["score"],
            x["money_score"],
            x["net_open"],
            x["volume_ratio"]
        ),
        reverse=True
    )

    print()
    print(
        "🔥 Güçlü sonuç:",
        len(results)
    )

    # ========================================================
    # SONUÇLARI GÖSTER
    # ========================================================

    sent = 0

    for result in results:

        symbol = result[
            "symbol"
        ]

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
            "| NET:",
            money_format(
                result["net_open"]
            ),
            "| VOL:",
            round(
                result["volume_ratio"],
                2
            )
        )

        # COOLDOWN
        if not can_send(
            symbol
        ):

            continue

        # TELEGRAM
        message = create_message(
            result
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
        "🚀 MEXC MONEY FLOW RADAR V3"
    )

    print(
        "=========================================="
    )

    print()
    print(
        "Para girişi + hacim sistemi başlatılıyor..."
    )

    print()

    while True:

        try:

            scan()

        except KeyboardInterrupt:

            print()
            print(
                "Program kapatıldı."
            )

            break

        except Exception as error:

            print()
            print(
                "ANA HATA:",
                error
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
