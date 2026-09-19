import os
import json
import time
import threading
import requests

from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC MONEY FLOW RADAR V4
#
# AMAÇ:
# PUMP ÖNCESİ PARA GİRİŞİ + HACİM HIZLANMASI
#
# SADECE:
# ✅ USDT FUTURES
# ✅ Yüksek 24H hacimli adaylar
# ✅ Yeni OPEN işlemleri
# ✅ Long / Short para akışı
# ✅ Gerçek USDT notional
# ✅ 15M hacim artışı
# ✅ 15M / 1H / 4H RSI
# ✅ BTC yönü
# ✅ Demand bölgesi
# ✅ Cooldown
# ✅ Telegram
#
# API YÜKÜ:
# 998 coin yerine sadece TOP_CANDIDATES analiz edilir.
# ============================================================


# ============================================================
# MEXC
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
# GENEL
# ============================================================

# İlk aşamada kaç coin detaylı analiz edilecek?
TOP_CANDIDATES = 120

# Aynı anda kaç worker?
MAX_WORKERS = 6

# İki tarama arası
SCAN_INTERVAL = 90

# Bir taramada maksimum Telegram alarmı
MAX_ALERTS = 8

# Aynı coin tekrar alarm süresi
COOLDOWN_HOURS = 4


# ============================================================
# API RATE LIMIT
# ============================================================

# İstekler arasında minimum bekleme
REQUEST_INTERVAL = 0.13

request_lock = threading.Lock()

last_request_time = 0.0


def rate_limited_request(
    url,
    params=None,
    timeout=10
):

    global last_request_time

    with request_lock:

        now = time.monotonic()

        wait = (
            REQUEST_INTERVAL
            -
            (
                now -
                last_request_time
            )
        )

        if wait > 0:

            time.sleep(wait)

        last_request_time = time.monotonic()

    try:

        response = session.get(
            url,
            params=params,
            timeout=timeout
        )

        if response.status_code != 200:

            return None

        return response.json()

    except Exception:

        return None


# ============================================================
# STATE
# ============================================================

STATE_FILE = "money_flow_state.json"


def load_state():

    try:

        if not os.path.exists(
            STATE_FILE
        ):

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
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({

    "User-Agent":
        "Mozilla/5.0",

    "Accept":
        "application/json"

})


# ============================================================
# STOCK / TOKENIZED STOCK FİLTRESİ
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
# CONTRACT CACHE
# ============================================================

CONTRACT_CACHE = {}

CONTRACT_CACHE_TIME = 0

CONTRACT_CACHE_TTL = 300


# ============================================================
# FUTURES KONTRATLARI
# ============================================================

def get_contracts():

    global CONTRACT_CACHE
    global CONTRACT_CACHE_TIME

    now = time.time()

    # Cache kullan
    if (
        CONTRACT_CACHE
        and
        now -
        CONTRACT_CACHE_TIME
        <
        CONTRACT_CACHE_TTL
    ):

        return CONTRACT_CACHE

    data = rate_limited_request(

        BASE_URL +
        "/api/v1/contract/detail"

    )

    if not data:

        if CONTRACT_CACHE:

            return CONTRACT_CACHE

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

            if is_stock_like(
                symbol
            ):

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

    if result:

        CONTRACT_CACHE = result

        CONTRACT_CACHE_TIME = now

    return result


# ============================================================
# TOP TICKER
#
# TEK TEK TICKER ÇAĞIRMAK YOK.
#
# TÜM TICKER'LAR TEK İSTEKLE ALINIYOR.
# ============================================================

def get_all_tickers():

    data = rate_limited_request(

        BASE_URL +
        "/api/v1/contract/ticker"

    )

    if not data:

        return {}

    ticker_data = data.get(
        "data"
    )

    if not ticker_data:

        return {}

    result = {}

    # Bazı API cevaplarında liste gelir
    if isinstance(
        ticker_data,
        list
    ):

        for item in ticker_data:

            try:

                symbol = item.get(
                    "symbol",
                    ""
                )

                if not symbol:

                    continue

                result[symbol] = item

            except Exception:

                continue

    # Bazı yapılarda dict gelebilir
    elif isinstance(
        ticker_data,
        dict
    ):

        # Eğer doğrudan symbol -> data ise
        if "symbol" in ticker_data:

            symbol = ticker_data.get(
                "symbol"
            )

            result[symbol] = (
                ticker_data
            )

        else:

            for symbol, item in (
                ticker_data.items()
            ):

                if isinstance(
                    item,
                    dict
                ):

                    result[symbol] = item

    return result


# ============================================================
# TOP CANDIDATES
# ============================================================

def get_top_candidates(
    contracts
):

    tickers = get_all_tickers()

    if not tickers:

        print(
            "❌ Toplu ticker alınamadı."
        )

        return []

    candidates = []

    for symbol, info in (
        contracts.items()
    ):

        ticker = tickers.get(
            symbol
        )

        if not ticker:

            continue

        try:

            amount24 = float(
                ticker.get(
                    "amount24",
                    0
                )
            )

            if amount24 <= 0:

                continue

            candidates.append({

                "symbol":
                    symbol,

                "amount24":
                    amount24,

                "ticker":
                    ticker

            })

        except Exception:

            continue

    candidates.sort(
        key=lambda x:
            x["amount24"],
        reverse=True
    )

    return candidates[
        :TOP_CANDIDATES
    ]


# ============================================================
# KLINE
# ============================================================

def get_klines(
    symbol,
    interval,
    limit=80
):

    data = rate_limited_request(

        BASE_URL +
        f"/api/v1/contract/kline/{symbol}",

        {
            "interval":
                interval,

            "limit":
                limit
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

        for i in range(
            length
        ):

            result.append({

                "time":
                    float(
                        times[i]
                    ),

                "open":
                    float(
                        opens[i]
                    ),

                "high":
                    float(
                        highs[i]
                    ),

                "low":
                    float(
                        lows[i]
                    ),

                "close":
                    float(
                        closes[i]
                    ),

                "volume":
                    float(
                        volumes[i]
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

            gains.append(
                diff
            )

            losses.append(0)

        else:

            gains.append(0)

            losses.append(
                abs(diff)
            )

    avg_gain = (
        sum(
            gains[:period]
        )
        /
        period
    )

    avg_loss = (
        sum(
            losses[:period]
        )
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
            -lookback - 1:
            -1
        ]

    ]

    if not previous_volumes:

        return 0

    average_volume = (
        sum(
            previous_volumes
        )
        /
        len(
            previous_volumes
        )
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

    if len(klines) <= (
        candles_back
    ):

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

        if (
            r15 is None
            or
            r1h is None
            or
            r4h is None
        ):

            return "NEUTRAL"

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
# 🔥 PARA GİRİŞİ
#
# T = 1 BUY
# T = 2 SELL
#
# O = 1 OPEN
#
# GERÇEK NOTIONAL:
#
# contracts *
# contract_size *
# price
# ============================================================

def get_money_flow(
    symbol,
    contract_size
):

    data = rate_limited_request(

        BASE_URL +
        f"/api/v1/contract/deals/{symbol}",

        {
            "limit":
                DEALS_LIMIT
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

    total_open = 0.0

    long_count = 0

    short_count = 0

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

            # SADECE OPEN
            if operation != 1:

                continue

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

            if side == 1:

                long_open += notional

                long_count += 1

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

        score = 0

        if long_ratio >= 52:

            score += 10

        if long_ratio >= 55:

            score += 10

        if long_ratio >= 60:

            score += 10

        if long_ratio >= 65:

            score += 10

        if long_ratio >= 70:

            score += 10

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
                score

        }

    except Exception:

        return None


# ============================================================
# DEMAND
# ============================================================

def detect_zone(
    klines
):

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
# MONEY STRENGTH
# ============================================================

def money_strength(
    score
):

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
    candidate,
    contract_info,
    btc_direction
):

    symbol = candidate[
        "symbol"
    ]

    try:

        contract_size = (
            contract_info[
                "contract_size"
            ]
        )

        # ====================================================
        # 24H HACİM
        # ====================================================

        amount24 = candidate[
            "amount24"
        ]

        if amount24 < MIN_24H_VOLUME:

            return None

        # ====================================================
        # 15M
        # ====================================================

        k15 = get_klines(

            symbol,
            "Min15",
            80

        )

        if len(k15) < 30:

            return None

        # ====================================================
        # HACİM
        # ====================================================

        volume15 = volume_ratio(
            k15
        )

        # EN ÖNEMLİ FİLTRE
        if volume15 < MIN_VOLUME_RATIO:

            return None

        # ====================================================
        # 15M PUMP
        # ====================================================

        change15 = price_change(
            k15,
            1
        )

        change1h = price_change(
            k15,
            4
        )

        if change15 > MAX_15M_PUMP:

            return None

        if change1h > MAX_1H_PUMP:

            return None

        # ====================================================
        # PARA GİRİŞİ
        # ====================================================

        flow = get_money_flow(

            symbol,
            contract_size

        )

        if not flow:

            return None

        # ====================================================
        # GERÇEK PARA
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
        # NET GİRİŞ
        # ====================================================

        if (
            flow["net_ratio"]
            <
            MIN_NET_RATIO
        ):

            return None

        # ====================================================
        # 1H
        # ====================================================

        k1h = get_klines(

            symbol,
            "Min60",
            80

        )

        if len(k1h) < 30:

            return None

        # ====================================================
        # 4H
        # ====================================================

        k4h = get_klines(

            symbol,
            "Hour4",
            80

        )

        if len(k4h) < 30:

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
        # DEMAND
        # ====================================================

        zone = detect_zone(
            k4h
        )

        # ====================================================
        # SKOR
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

        # DEMAND BONUS
        if zone == "DEMAND":

            score += 8

        # BTC
        if btc_direction == "BULLISH":

            score += 5

        elif btc_direction == "BEARISH":

            score -= 5

        # ====================================================
        # SKOR FİLTRESİ
        # ====================================================

        if score < MIN_SCORE:

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

            "zone":
                zone,

            "btc":
                btc_direction,

            "contract_size":
                contract_size,

            "amount24":
                amount24

        }

    except Exception:

        return None


# ============================================================
# PARA FORMAT
# ============================================================

def money_format(
    value
):

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
# TELEGRAM
# ============================================================

def create_message(
    x
):

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
🚨 <b>PARA GİRİŞİ + HACİM</b>

🟢 <b>{x["symbol"]}</b>

💰 Para:
<b>{strength}</b>

🟢 Long Açılış:
<b>{money_format(x["long_open"])} USDT</b>

🔴 Short Açılış:
<b>{money_format(x["short_open"])} USDT</b>

💵 Net Giriş:
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
<b>{zone}</b>

{btc}

🔥 <b>SKOR: {x["score"]}</b>
""".strip()


# ============================================================
# COOLDOWN
# ============================================================

def can_send(
    symbol
):

    last_time = STATE.get(
        symbol,
        0
    )

    return (

        time.time() -
        last_time

        >=

        COOLDOWN_HOURS *
        3600

    )


def mark_sent(
    symbol
):

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
        "🚀 MEXC MONEY FLOW RADAR V4"
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
    # CONTRACT
    # ========================================================

    contracts = get_contracts()

    if not contracts:

        print(
            "❌ Futures listesi alınamadı."
        )

        return

    print(
        "Toplam Futures:",
        len(contracts)
    )

    # ========================================================
    # TOP CANDIDATES
    # ========================================================

    candidates = get_top_candidates(
        contracts
    )

    print(
        "Detaylı taranacak:",
        len(candidates)
    )

    if not candidates:

        print(
            "❌ Aday listesi boş."
        )

        return

    print(
        "İlk aday:",
        candidates[0]["symbol"]
    )

    # ========================================================
    # ANALİZ
    # ========================================================

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {}

        for candidate in candidates:

            symbol = candidate[
                "symbol"
            ]

            future = executor.submit(

                analyze_symbol,

                candidate,

                contracts[symbol],

                btc_direction

            )

            futures[future] = symbol

        for future in as_completed(
            futures
        ):

            try:

                result = (
                    future.result()
                )

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

            x["net_open"],

            x["volume_ratio"]

        ),

        reverse=True

    )

    print()
    print(
        "🔥 GÜÇLÜ SONUÇ:",
        len(results)
    )

    # ========================================================
    # SONUÇLARI GÖSTER
    # ========================================================

    for x in results:

        print()

        print(

            x["symbol"],

            "| SCORE:",
            x["score"],

            "| MONEY:",
            x["money_score"],

            "| LONG:",
            round(
                x["long_ratio"],
                1
            ),

            "| NET:",
            money_format(
                x["net_open"]
            ),

            "| VOL:",
            round(
                x["volume_ratio"],
                2
            )

        )

    # ========================================================
    # TELEGRAM
    # ========================================================

    sent = 0

    for x in results:

        symbol = x[
            "symbol"
        ]

        if not can_send(
            symbol
        ):

            continue

        message = create_message(
            x
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
        "🚀 MEXC MONEY FLOW RADAR V4"
    )

    print(
        "=========================================="
    )

    print()
    print(
        "998 Futures → TOP 120 → PARA + HACİM"
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
