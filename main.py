import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PRE-PUMP RADAR V10
#
# AMAÇ:
# Pump başlamadan ÖNCE güçlü para/pozisyon akışı gösteren
# coinleri yakalamak.
#
# SKOR:
# 💰 PARA AKIŞI = 50
# 📊 TEKNİK     = 30
# 📈 HACİM      = 20
# ⭐ TOPLAM     = 100
#
# MEXC FUTURES USDT
# 4H + 1H + 15M
# Telegram
# ============================================================


# ============================================================
# AYARLAR
# ============================================================

BASE = "https://api.mexc.com"

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID"
)

MAX_WORKERS = 8

CANDLE_COUNT = 90

# Teknik filtreden sonra para akışı taranacak maksimum coin
TECH_TOP = 120

# Telegram maksimum sinyal
MAX_ALERTS = 6

# Minimum final skor
MIN_SCORE = 55

# Minimum para akışı skoru
MIN_MONEY_SCORE = 14

# API hız kontrolü
REQUEST_INTERVAL = 0.10

# Son işlemler
DEALS_LIMIT = 100


session = requests.Session()

_last_request = 0.0

CONTRACT_INFO = {}


# ============================================================
# MEXC API GET
# ============================================================

def mexc_get(
    path,
    params=None,
    timeout=15
):

    global _last_request

    wait = (
        REQUEST_INTERVAL
        -
        (
            time.time()
            -
            _last_request
        )
    )

    if wait > 0:
        time.sleep(wait)

    try:

        response = session.get(
            BASE + path,
            params=params or {},
            timeout=timeout
        )

        _last_request = time.time()

        if response.status_code != 200:

            return None

        data = response.json()

        if isinstance(data, dict):

            if data.get("success") is False:

                return None

        return data

    except Exception:

        return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(
    text
):

    if (
        not TELEGRAM_BOT_TOKEN
        or
        not TELEGRAM_CHAT_ID
    ):

        print(
            "⚠️ Telegram ENV bulunamadı."
        )

        return False

    url = (
        "https://api.telegram.org/bot"
        +
        TELEGRAM_BOT_TOKEN
        +
        "/sendMessage"
    )

    try:

        response = session.post(
            url,
            json={
                "chat_id":
                    TELEGRAM_CHAT_ID,
                "text":
                    text
            },
            timeout=15
        )

        if response.status_code == 200:

            return True

        print(
            "Telegram HTTP:",
            response.status_code
        )

        return False

    except Exception as e:

        print(
            "Telegram hata:",
            e
        )

        return False


# ============================================================
# FUTURES CONTRACTLARINI AL
# ============================================================

def get_contracts():

    global CONTRACT_INFO

    data = mexc_get(
        "/api/v1/contract/detail"
    )

    if not data:

        return []

    rows = data.get(
        "data",
        []
    )

    if not isinstance(
        rows,
        list
    ):

        return []

    CONTRACT_INFO = {}

    symbols = []

    for item in rows:

        symbol = item.get(
            "symbol",
            ""
        )

        if not symbol.endswith(
            "_USDT"
        ):

            continue

        try:

            state = int(
                item.get(
                    "state",
                    0
                )
            )

        except Exception:

            state = 0

        if state != 0:

            continue

        try:

            contract_size = float(
                item.get(
                    "contractSize",
                    0
                )
            )

        except Exception:

            contract_size = 0.0

        if contract_size <= 0:

            continue

        CONTRACT_INFO[
            symbol
        ] = {

            "contract_size":
                contract_size,

            "base_coin":
                item.get(
                    "baseCoin"
                ),

            "quote_coin":
                item.get(
                    "quoteCoin"
                ),

            "settle_coin":
                item.get(
                    "settleCoin"
                )
        }

        symbols.append(
            symbol
        )

    return sorted(
        set(symbols)
    )


# ============================================================
# KLINE
# ============================================================

def get_klines(
    symbol,
    interval
):

    end = int(
        time.time()
    )

    # 90 mum
    # Güvenli geniş zaman aralığı
    start = (
        end
        -
        (
            CANDLE_COUNT
            *
            4
            *
            3600
        )
    )

    data = mexc_get(
        f"/api/v1/contract/kline/{symbol}",
        {
            "interval":
                interval,

            "start":
                start,

            "end":
                end
        }
    )

    if not data:

        return []

    d = data.get(
        "data"
    )

    if not isinstance(
        d,
        dict
    ):

        return []

    times = d.get(
        "time",
        []
    )

    opens = d.get(
        "open",
        []
    )

    closes = d.get(
        "close",
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

    vols = d.get(
        "vol",
        []
    )

    amounts = d.get(
        "amount",
        []
    )

    n = min(
        len(times),
        len(opens),
        len(closes),
        len(highs),
        len(lows),
        len(vols)
    )

    candles = []

    for i in range(n):

        try:

            candles.append({

                "time":
                    float(
                        times[i]
                    ),

                "open":
                    float(
                        opens[i]
                    ),

                "close":
                    float(
                        closes[i]
                    ),

                "high":
                    float(
                        highs[i]
                    ),

                "low":
                    float(
                        lows[i]
                    ),

                "vol":
                    float(
                        vols[i]
                    ),

                "amount":
                    (
                        float(
                            amounts[i]
                        )
                        if
                        i < len(amounts)
                        else
                        0.0
                    )
            })

        except Exception:

            continue

    return candles


# ============================================================
# RSI
# ============================================================

def calculate_rsi(
    values,
    period=14
):

    if len(values) < (
        period + 1
    ):

        return 50.0

    gains = []

    losses = []

    for i in range(
        1,
        len(values)
    ):

        diff = (
            values[i]
            -
            values[i - 1]
        )

        if diff > 0:

            gains.append(
                diff
            )

            losses.append(
                0.0
            )

        else:

            gains.append(
                0.0
            )

            losses.append(
                -diff
            )

    avg_gain = (
        sum(
            gains[-period:]
        )
        /
        period
    )

    avg_loss = (
        sum(
            losses[-period:]
        )
        /
        period
    )

    if avg_loss == 0:

        return 100.0

    rs = (
        avg_gain
        /
        avg_loss
    )

    return (
        100.0
        -
        (
            100.0
            /
            (
                1.0 + rs
            )
        )
    )


# ============================================================
# YÜZDE DEĞİŞİM
# ============================================================

def pct_change(
    current,
    previous
):

    if previous == 0:

        return 0.0

    return (
        (
            current
            -
            previous
        )
        /
        previous
        *
        100.0
    )


# ============================================================
# HACİM ORANI
# ============================================================

def volume_ratio(
    candles,
    recent=5,
    base=20
):

    if len(candles) < (
        recent + base
    ):

        return 1.0

    recent_part = candles[
        -recent:
    ]

    previous_part = candles[
        -(recent + base):
        -recent
    ]

    recent_volume = (
        sum(
            x["vol"]
            for x in recent_part
        )
        /
        recent
    )

    previous_volume = (
        sum(
            x["vol"]
            for x in previous_part
        )
        /
        max(
            1,
            len(previous_part)
        )
    )

    if previous_volume <= 0:

        return 1.0

    return (
        recent_volume
        /
        previous_volume
    )


# ============================================================
# HACİM İVMESİ
# ============================================================

def volume_acceleration(
    candles
):

    if len(candles) < 15:

        return 1.0

    recent = (
        sum(
            x["vol"]
            for x in candles[-5:]
        )
        /
        5.0
    )

    previous = (
        sum(
            x["vol"]
            for x in candles[-10:-5]
        )
        /
        5.0
    )

    if previous <= 0:

        return 1.0

    return (
        recent
        /
        previous
    )


# ============================================================
# HIGHER LOW
# ============================================================

def detect_higher_low(
    candles
):

    if len(candles) < 16:

        return False

    recent_low = min(
        x["low"]
        for x in candles[-8:]
    )

    previous_low = min(
        x["low"]
        for x in candles[-16:-8]
    )

    return (
        recent_low
        >
        previous_low
    )


# ============================================================
# COMPRESSION
# ============================================================

def detect_compression(
    candles
):

    if len(candles) < 10:

        return False

    high = max(
        x["high"]
        for x in candles[-10:]
    )

    low = min(
        x["low"]
        for x in candles[-10:]
    )

    if low <= 0:

        return False

    range_pct = (
        (
            high
            -
            low
        )
        /
        low
        *
        100
    )

    return (
        range_pct <= 18
    )


# ============================================================
# TEKNİK ANALİZ
# ============================================================

def analyze_technical(
    symbol
):

    try:

        # ----------------------------------------------------
        # 4H
        # ----------------------------------------------------

        c4 = get_klines(
            symbol,
            "Hour4"
        )

        # ----------------------------------------------------
        # 1H
        # ----------------------------------------------------

        c1 = get_klines(
            symbol,
            "Min60"
        )

        # ----------------------------------------------------
        # 15M
        # ----------------------------------------------------

        c15 = get_klines(
            symbol,
            "Min15"
        )

        if (
            len(c4) < 50
            or
            len(c1) < 50
            or
            len(c15) < 50
        ):

            return None

        p4 = [
            x["close"]
            for x in c4
        ]

        p1 = [
            x["close"]
            for x in c1
        ]

        p15 = [
            x["close"]
            for x in c15
        ]

        current = p15[-1]

        if current <= 0:

            return None

        # ----------------------------------------------------
        # RSI
        # ----------------------------------------------------

        rsi4 = calculate_rsi(
            p4
        )

        rsi1 = calculate_rsi(
            p1
        )

        rsi15 = calculate_rsi(
            p15
        )

        # ----------------------------------------------------
        # HACİM
        # ----------------------------------------------------

        v4 = volume_ratio(
            c4
        )

        v1 = volume_ratio(
            c1
        )

        v15 = volume_ratio(
            c15
        )

        acc1 = volume_acceleration(
            c1
        )

        acc15 = volume_acceleration(
            c15
        )

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------

        mom1 = pct_change(
            p1[-1],
            p1[-5]
        )

        mom15 = pct_change(
            p15[-1],
            p15[-5]
        )

        move5 = pct_change(
            p15[-1],
            p15[-6]
        )

        move20 = pct_change(
            p15[-1],
            p15[-21]
        )

        # ----------------------------------------------------
        # DİRENÇ
        # ----------------------------------------------------

        resistance_price = max(
            x["high"]
            for x in c1[-25:]
        )

        resistance_pct = (
            (
                resistance_price
                -
                current
            )
            /
            current
            *
            100
        )

        # ----------------------------------------------------
        # YAPISAL FİLTRE
        # ----------------------------------------------------

        higher_low = detect_higher_low(
            c1
        )

        compression = detect_compression(
            c4
        )

        # ====================================================
        # AŞIRI ISINMA RED
        # ====================================================

        if rsi4 > 72:

            return None

        if rsi1 > 72:

            return None

        if rsi15 > 76:

            return None

        if v15 > 7:

            return None

        if move5 > 10:

            return None

        if move20 > 18:

            return None

        if resistance_pct > 10:

            return None

        # ====================================================
        # TEKNİK PUAN
        # ====================================================

        score = 0

        # 4H RSI
        if 45 <= rsi4 <= 65:

            score += 8

        elif 40 <= rsi4 <= 70:

            score += 5

        # 1H RSI
        if 50 <= rsi1 <= 65:

            score += 8

        elif 45 <= rsi1 <= 70:

            score += 5

        # 15M RSI
        if 50 <= rsi15 <= 68:

            score += 7

        elif 45 <= rsi15 <= 72:

            score += 4

        # 1H hacim
        if 0.9 <= v1 <= 2.5:

            score += 7

        elif v1 >= 0.7:

            score += 4

        # 15M hacim
        if 0.8 <= v15 <= 3.0:

            score += 7

        elif v15 >= 0.7:

            score += 4

        # 1H momentum
        if 0 < mom1 <= 4:

            score += 5

        # 15M momentum
        if 0 < mom15 <= 3:

            score += 5

        # Higher Low
        if higher_low:

            score += 6

        # Compression
        if compression:

            score += 5

        # Direnç
        if 0.5 <= resistance_pct <= 5:

            score += 7

        elif 0 <= resistance_pct <= 8:

            score += 4

        return {

            "symbol":
                symbol,

            "technical_score":
                score,

            "rsi4":
                rsi4,

            "rsi1":
                rsi1,

            "rsi15":
                rsi15,

            "v4":
                v4,

            "v1":
                v1,

            "v15":
                v15,

            "acc1":
                acc1,

            "acc15":
                acc15,

            "mom1":
                mom1,

            "mom15":
                mom15,

            "move5":
                move5,

            "move20":
                move20,

            "resistance":
                resistance_pct,

            "higher_low":
                higher_low,

            "compression":
                compression
        }

    except Exception:

        return None


# ============================================================
# TICKER
# ============================================================

def get_ticker(
    symbol
):

    data = mexc_get(
        "/api/v1/contract/ticker",
        {
            "symbol":
                symbol
        }
    )

    if not data:

        return None

    return data.get(
        "data"
    )


# ============================================================
# PARA / POZİSYON AKIŞI
#
# T = 1 BUY
# T = 2 SELL
#
# O = 1 OPEN
# O = 2 CLOSE
#
# NOT:
# Bu "gerçek fiat para girişi" değildir.
# Futures işlemlerindeki yönlü yeni pozisyon akışıdır.
# ============================================================

def get_deal_flow(
    symbol
):

    data = mexc_get(
        f"/api/v1/contract/deals/{symbol}",
        {
            "limit":
                DEALS_LIMIT
        }
    )

    if not data:

        return None

    rows = data.get(
        "data",
        []
    )

    if not isinstance(
        rows,
        list
    ):

        return None

    if not rows:

        return None

    contract = CONTRACT_INFO.get(
        symbol
    )

    if not contract:

        return None

    contract_size = contract.get(
        "contract_size",
        0
    )

    if contract_size <= 0:

        return None

    buy_open = 0.0

    sell_open = 0.0

    buy_all = 0.0

    sell_all = 0.0

    open_count = 0

    for row in rows:

        try:

            price = float(
                row.get(
                    "p",
                    0
                )
            )

            volume = float(
                row.get(
                    "v",
                    0
                )
            )

            deal_type = int(
                row.get(
                    "T",
                    0
                )
            )

            open_close = int(
                row.get(
                    "O",
                    0
                )
            )

            if (
                price <= 0
                or
                volume <= 0
            ):

                continue

            notional = (
                price
                *
                volume
                *
                contract_size
            )

            if notional <= 0:

                continue

            # ------------------------------------------------
            # TÜM İŞLEMLER
            # ------------------------------------------------

            if deal_type == 1:

                buy_all += notional

            elif deal_type == 2:

                sell_all += notional

            # ------------------------------------------------
            # SADECE YENİ AÇILAN POZİSYONLAR
            # ------------------------------------------------

            if open_close == 1:

                open_count += 1

                if deal_type == 1:

                    buy_open += notional

                elif deal_type == 2:

                    sell_open += notional

        except Exception:

            continue

    # ========================================================
    # OPEN FLOW
    # ========================================================

    open_total = (
        buy_open
        +
        sell_open
    )

    if open_total > 0:

        net = (
            buy_open
            -
            sell_open
        )

        net_pct = (
            net
            /
            open_total
            *
            100
        )

        buy_share = (
            buy_open
            /
            open_total
            *
            100
        )

        flow_type = "OPEN"

    else:

        total = (
            buy_all
            +
            sell_all
        )

        if total <= 0:

            return None

        net = (
            buy_all
            -
            sell_all
        )

        net_pct = (
            net
            /
            total
            *
            100
        )

        buy_share = (
            buy_all
            /
            total
            *
            100
        )

        flow_type = "TRADE"

    # ========================================================
    # TICKER
    # ========================================================

    ticker = get_ticker(
        symbol
    )

    amount24 = 0.0

    hold_vol = 0.0

    funding_rate = 0.0

    last_price = 0.0

    if ticker:

        try:

            amount24 = float(
                ticker.get(
                    "amount24",
                    0
                )
            )

        except Exception:

            amount24 = 0.0

        try:

            hold_vol = float(
                ticker.get(
                    "holdVol",
                    0
                )
            )

        except Exception:

            hold_vol = 0.0

        try:

            funding_rate = float(
                ticker.get(
                    "fundingRate",
                    0
                )
            )

        except Exception:

            funding_rate = 0.0

        try:

            last_price = float(
                ticker.get(
                    "lastPrice",
                    0
                )
            )

        except Exception:

            last_price = 0.0

    # ========================================================
    # OPEN / 24H
    # ========================================================

    if amount24 > 0:

        open_vs_24h = (
            open_total
            /
            amount24
            *
            100
        )

    else:

        open_vs_24h = 0.0

    return {

        "buy_open":
            buy_open,

        "sell_open":
            sell_open,

        "open_total":
            open_total,

        "net":
            net,

        "net_pct":
            net_pct,

        "buy_share":
            buy_share,

        "open_count":
            open_count,

        "flow_type":
            flow_type,

        "amount24":
            amount24,

        "open_vs_24h":
            open_vs_24h,

        "hold_vol":
            hold_vol,

        "funding_rate":
            funding_rate,

        "last_price":
            last_price,

        "contract_size":
            contract_size
    }


# ============================================================
# PARA AKIŞI SKORU
#
# MAKSIMUM 50
# ============================================================

def money_score(
    flow
):

    if not flow:

        return 0

    net = flow[
        "net_pct"
    ]

    buy_share = flow[
        "buy_share"
    ]

    open_total = flow[
        "open_total"
    ]

    open_vs_24h = flow[
        "open_vs_24h"
    ]

    score = 0

    # ========================================================
    # NET FLOW
    # ========================================================

    if net >= 40:

        score += 25

    elif net >= 30:

        score += 23

    elif net >= 20:

        score += 20

    elif net >= 15:

        score += 17

    elif net >= 10:

        score += 14

    elif net >= 7:

        score += 10

    elif net >= 4:

        score += 6

    elif net >= 0:

        score += 2

    else:

        score -= 15

    # ========================================================
    # BUY SHARE
    # ========================================================

    if buy_share >= 80:

        score += 12

    elif buy_share >= 72:

        score += 10

    elif buy_share >= 65:

        score += 8

    elif buy_share >= 60:

        score += 6

    elif buy_share >= 55:

        score += 3

    elif buy_share < 45:

        score -= 10

    # ========================================================
    # OPEN FLOW / 24H
    # ========================================================

    if open_vs_24h >= 1.0:

        score += 8

    elif open_vs_24h >= 0.50:

        score += 7

    elif open_vs_24h >= 0.25:

        score += 6

    elif open_vs_24h >= 0.10:

        score += 4

    elif open_vs_24h >= 0.05:

        score += 2

    else:

        score -= 3

    # ========================================================
    # MUTLAK OPEN NOTIONAL
    # ========================================================

    if open_total >= 500000:

        score += 5

    elif open_total >= 250000:

        score += 4

    elif open_total >= 100000:

        score += 3

    elif open_total >= 50000:

        score += 2

    elif open_total >= 10000:

        score += 1

    else:

        score -= 3

    # ========================================================
    # %100 BUY'A KÜÇÜK CEZA
    #
    # Çünkü çok küçük örneklerde %100 yanıltıcı olabilir.
    # ========================================================

    if net >= 95:

        score -= 3

    return max(
        0,
        min(
            score,
            50
        )
    )


# ============================================================
# HACİM SKORU
# ============================================================

def volume_score(
    tech
):

    score = 0

    v1 = tech[
        "v1"
    ]

    v15 = tech[
        "v15"
    ]

    acc1 = tech[
        "acc1"
    ]

    acc15 = tech[
        "acc15"
    ]

    # --------------------------------------------------------
    # 1H
    # --------------------------------------------------------

    if 1.3 <= v1 <= 2.5:

        score += 6

    elif 1.0 <= v1 < 1.3:

        score += 4

    elif v1 >= 2.5:

        score += 5

    elif v1 >= 0.8:

        score += 2

    # --------------------------------------------------------
    # 15M
    # --------------------------------------------------------

    if 1.3 <= v15 <= 2.8:

        score += 6

    elif 1.0 <= v15 < 1.3:

        score += 4

    elif v15 >= 2.8:

        score += 4

    elif v15 >= 0.8:

        score += 2

    # --------------------------------------------------------
    # İVME
    # --------------------------------------------------------

    if acc1 >= 1.5:

        score += 4

    elif acc1 >= 1.2:

        score += 2

    if acc15 >= 1.5:

        score += 4

    elif acc15 >= 1.2:

        score += 2

    return min(
        score,
        20
    )


# ============================================================
# FİNAL SKOR
# ============================================================

def calculate_final(
    tech,
    flow
):

    money = money_score(
        flow
    )

    if money < MIN_MONEY_SCORE:

        return None

    # ========================================================
    # TEKNİK 30
    # ========================================================

    technical = min(
        (
            tech["technical_score"]
            /
            65.0
            *
            30.0
        ),
        30.0
    )

    # ========================================================
    # HACİM 20
    # ========================================================

    volume = volume_score(
        tech
    )

    total = (
        money
        +
        technical
        +
        volume
    )

    # ========================================================
    # AŞIRI ISINMA CEZALARI
    # ========================================================

    if tech["rsi15"] > 72:

        total -= 8

    if tech["rsi1"] > 68:

        total -= 5

    if tech["v15"] > 5:

        total -= 8

    if tech["mom1"] > 6:

        total -= 6

    if tech["move5"] > 7:

        total -= 8

    if tech["move20"] > 12:

        total -= 8

    # ========================================================
    # FUNDING
    # ========================================================

    funding = flow[
        "funding_rate"
    ]

    if funding > 0.0015:

        total -= 6

    elif funding > 0.001:

        total -= 3

    # ========================================================
    # NEGATİF FLOW RED
    # ========================================================

    if flow["net_pct"] < 0:

        return None

    if total < MIN_SCORE:

        return None

    result = dict(
        tech
    )

    result[
        "money_score"
    ] = money

    result[
        "technical_part"
    ] = technical

    result[
        "volume_part"
    ] = volume

    result[
        "total_score"
    ] = round(
        total,
        1
    )

    result[
        "flow"
    ] = flow

    return result


# ============================================================
# FIRE
# ============================================================

def fire_level(
    money_score_value,
    net_pct
):

    if (
        money_score_value >= 42
        and
        net_pct >= 20
    ):

        return "🔥🔥🔥"

    if (
        money_score_value >= 34
        and
        net_pct >= 12
    ):

        return "🔥🔥"

    if money_score_value >= 25:

        return "🔥"

    return "⚡"


# ============================================================
# PARA FORMAT
# ============================================================

def format_money(
    value
):

    if value >= 1000000:

        return (
            f"${value / 1000000:.2f}M"
        )

    if value >= 1000:

        return (
            f"${value / 1000:.0f}K"
        )

    return (
        f"${value:.0f}"
    )


# ============================================================
# TELEGRAM
# ============================================================

def format_telegram(
    result
):

    symbol = result[
        "symbol"
    ]

    score = result[
        "total_score"
    ]

    flow = result[
        "flow"
    ]

    money = result[
        "money_score"
    ]

    net = flow[
        "net_pct"
    ]

    buy_share = flow[
        "buy_share"
    ]

    open_total = flow[
        "open_total"
    ]

    volume = result[
        "v1"
    ]

    resistance = result[
        "resistance"
    ]

    fire = fire_level(
        money,
        net
    )

    return (
        "🚨 PRE-PUMP\n\n"

        f"🪙 {symbol}\n"

        f"⭐ {score:.0f}/100\n\n"

        f"💰 Para Girişi: "
        f"{fire} "
        f"{net:+.1f}%\n"

        f"💵 Açılış Akışı: "
        f"{format_money(open_total)}\n"

        f"🟢 Alış Baskısı: "
        f"{buy_share:.0f}%\n"

        f"📈 Hacim: "
        f"{volume:.1f}x\n"

        f"🎯 Direnç: "
        f"%{resistance:.1f}\n\n"

        "TP1 +3% | "
        "TP2 +6% | "
        "TP3 +10%"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    started = time.time()

    print("")
    print("=" * 65)
    print("🚀 MEXC PRE-PUMP RADAR V10")
    print("=" * 65)

    print(
        "💰 PARA AKIŞI = 50"
    )

    print(
        "📊 TEKNİK = 30"
    )

    print(
        "📈 HACİM = 20"
    )

    print(
        "🎯 AMAÇ = PUMP ÖNCESİ"
    )

    # ========================================================
    # FUTURES
    # ========================================================

    print("")
    print(
        "🔎 MEXC Futures coinleri alınıyor..."
    )

    symbols = get_contracts()

    print(
        f"✅ Futures: {len(symbols)}"
    )

    if not symbols:

        print(
            "❌ Futures bulunamadı."
        )

        return

    # ========================================================
    # API TEST
    # ========================================================

    print("")
    print(
        "🧪 API TEST..."
    )

    test_kline = get_klines(
        "BTC_USDT",
        "Min15"
    )

    if test_kline:

        print(
            f"✅ Kline OK | "
            f"{len(test_kline)} mum"
        )

    else:

        print(
            "❌ Kline HATA"
        )

    test_ticker = get_ticker(
        "BTC_USDT"
    )

    if test_ticker:

        print(
            "✅ Ticker OK"
        )

    else:

        print(
            "❌ Ticker HATA"
        )

    test_flow = get_deal_flow(
        "BTC_USDT"
    )

    if test_flow:

        print(
            "✅ İşlem akışı OK | "
            f"Net: "
            f"{test_flow['net_pct']:+.2f}% | "
            f"Buy: "
            f"{test_flow['buy_share']:.1f}%"
        )

    else:

        print(
            "⚠️ BTC işlem akışı okunamadı."
        )

    # ========================================================
    # TEKNİK TARAMA
    # ========================================================

    print("")
    print(
        "🟣 TEKNİK ÖN FİLTRE..."
    )

    technical_candidates = []

    total = len(
        symbols
    )

    completed = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        future_map = {}

        for symbol in symbols:

            future = executor.submit(
                analyze_technical,
                symbol
            )

            future_map[
                future
            ] = symbol

        for future in as_completed(
            future_map
        ):

            completed += 1

            try:

                result = future.result()

            except Exception:

                result = None

            if result:

                technical_candidates.append(
                    result
                )

            if (
                completed % 100 == 0
                or
                completed == total
            ):

                print(
                    f"İlerleme "
                    f"{completed}/{total} "
                    f"| Teknik aday "
                    f"{len(technical_candidates)}"
                )

    # ========================================================
    # TEKNİK SIRALAMA
    # ========================================================

    technical_candidates.sort(
        key=lambda x:
            x["technical_score"],
        reverse=True
    )

    technical_candidates = (
        technical_candidates[
            :TECH_TOP
        ]
    )

    print("")
    print(
        f"✅ Teknik aday: "
        f"{len(technical_candidates)}"
    )

    # ========================================================
    # PARA AKIŞI
    # ========================================================

    print("")
    print(
        "💰 PARA GİRİŞİ TARAMASI..."
    )

    final_candidates = []

    flow_found = 0

    strong_money = 0

    total_technical = len(
        technical_candidates
    )

    for index, tech in enumerate(
        technical_candidates,
        1
    ):

        flow = get_deal_flow(
            tech["symbol"]
        )

        if flow:

            flow_found += 1

            ms = money_score(
                flow
            )

            if ms >= MIN_MONEY_SCORE:

                strong_money += 1

                result = calculate_final(
                    tech,
                    flow
                )

                if result:

                    final_candidates.append(
                        result
                    )

        if (
            index % 20 == 0
            or
            index == total_technical
        ):

            print(
                f"Para akışı "
                f"{index}/{total_technical} "
                f"| Flow {flow_found} "
                f"| Güçlü {strong_money} "
                f"| Final "
                f"{len(final_candidates)}"
            )

    # ========================================================
    # FİNAL SIRALAMA
    # ========================================================

    final_candidates.sort(
        key=lambda x: (
            x["total_score"],
            x["money_score"],
            x["flow"]["open_total"],
            x["flow"]["net_pct"]
        ),
        reverse=True
    )

    # ========================================================
    # EN GÜÇLÜLER
    # ========================================================

    print("")
    print("=" * 65)
    print("🏆 EN GÜÇLÜ ADAYLAR")
    print("=" * 65)

    if final_candidates:

        for result in final_candidates[:15]:

            flow = result[
                "flow"
            ]

            print(
                f"{result['symbol']:15} | "
                f"Skor "
                f"{result['total_score']:5.1f} | "
                f"Para "
                f"{result['money_score']:2d} | "
                f"Net "
                f"{flow['net_pct']:+6.1f}% | "
                f"Buy "
                f"{flow['buy_share']:5.1f}% | "
                f"Open "
                f"${flow['open_total']:,.0f}"
            )

    else:

        print(
            "❌ Güçlü final aday bulunamadı."
        )

    # ========================================================
    # TELEGRAM
    # ========================================================

    print("")
    print(
        "📨 TELEGRAM GÖNDERİMİ..."
    )

    sent = 0

    for result in final_candidates[
        :MAX_ALERTS
    ]:

        message = format_telegram(
            result
        )

        print("")
        print(
            "-" * 60
        )

        print(
            message
        )

        print(
            "-" * 60
        )

        if send_telegram(
            message
        ):

            sent += 1

    # ========================================================
    # BİTİŞ
    # ========================================================

    elapsed = (
        time.time()
        -
        started
    )

    print("")
    print("=" * 65)
    print("✅ V10 RADAR TAMAMLANDI")
    print("=" * 65)

    print(
        f"⏱ Süre: "
        f"{elapsed:.1f} sn"
    )

    print(
        f"🌐 Futures: "
        f"{len(symbols)}"
    )

    print(
        f"🔎 Teknik: "
        f"{len(technical_candidates)}"
    )

    print(
        f"💰 Flow: "
        f"{flow_found}"
    )

    print(
        f"🔥 Güçlü para: "
        f"{strong_money}"
    )

    print(
        f"🎯 Final: "
        f"{len(final_candidates)}"
    )

    print(
        f"📨 Telegram: "
        f"{sent}"
    )

    print("=" * 65)


# ============================================================
# PROGRAM BAŞLAT
# ============================================================

if __name__ == "__main__":

    print("")
    print("=" * 65)
    print("🚀 MEXC PRE-PUMP RADAR V10 BAŞLADI")
    print("=" * 65)

    main()
