import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# MEXC PRE-PUMP RADAR V9
#
# AMAÇ:
# Pump başlamadan önce güçlü adayları bulmak.
#
# ANA ÖNCELİK:
# 1) Para / pozisyon akışı
# 2) Buy/Open baskısı
# 3) Açılış hacminin 24H hacme oranı
# 4) Hacim ivmesi
# 5) Teknik yapı
# 6) Dirence yakınlık
# 7) Aşırı ısınmamış olması
#
# SKOR:
# PARA AKIŞI = 50
# TEKNİK     = 30
# HACİM      = 20
# TOPLAM     = 100
# ============================================================


# ============================================================
# AYARLAR
# ============================================================

BASE = "https://api.mexc.com"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MAX_WORKERS = 6

CANDLE_COUNT = 90

# Teknik filtreden sonra para akışına girecek maksimum coin
TECH_TOP = 140

# Telegram maksimum coin
MAX_ALERTS = 6

# Final minimum puan
MIN_SCORE = 55

# Minimum para akışı puanı
MIN_MONEY_SCORE = 14

# API istek aralığı
REQUEST_INTERVAL = 0.11

# Son işlemler
DEALS_LIMIT = 100


session = requests.Session()

_last_request = 0

CONTRACT_INFO = {}


# ============================================================
# MEXC GET
# ============================================================

def mexc_get(path, params=None, timeout=15):

    global _last_request

    wait = REQUEST_INTERVAL - (time.time() - _last_request)

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

def send_telegram(text):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:

        print("Telegram ENV bulunamadı")

        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    try:

        response = session.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text
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
# FUTURES CONTRACTLAR
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

    CONTRACT_INFO = {}

    symbols = []

    for item in rows:

        symbol = item.get(
            "symbol",
            ""
        )

        if not symbol.endswith("_USDT"):
            continue

        state = item.get("state")

        # MEXC aktif kontrat
        if state not in [0, "0"]:
            continue

        try:

            contract_size = float(
                item.get(
                    "contractSize",
                    0
                )
            )

        except Exception:

            contract_size = 0

        if contract_size <= 0:
            continue

        CONTRACT_INFO[symbol] = {
            "contract_size": contract_size,
            "base_coin": item.get("baseCoin"),
            "quote_coin": item.get("quoteCoin"),
            "settle_coin": item.get("settleCoin")
        }

        symbols.append(symbol)

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
            "interval": interval,
            "start": start,
            "end": end
        }
    )

    if not data:
        return []

    d = data.get("data")

    if not isinstance(d, dict):
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
                "time": float(times[i]),
                "open": float(opens[i]),
                "close": float(closes[i]),
                "high": float(highs[i]),
                "low": float(lows[i]),
                "vol": float(vols[i]),
                "amount": (
                    float(amounts[i])
                    if i < len(amounts)
                    else 0.0
                )
            })

        except Exception:

            continue

    return candles


# ============================================================
# RSI
# ============================================================

def rsi(
    values,
    period=14
):

    if len(values) < period + 1:
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

        gains.append(
            max(diff, 0)
        )

        losses.append(
            max(-diff, 0)
        )

    avg_gain = (
        sum(gains[-period:])
        /
        period
    )

    avg_loss = (
        sum(losses[-period:])
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
        100
        -
        (
            100
            /
            (1 + rs)
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
        100
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

    old_part = candles[
        -(base + recent):
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

    old_volume = (
        sum(
            x["vol"]
            for x in old_part
        )
        /
        max(
            1,
            len(old_part)
        )
    )

    if old_volume <= 0:
        return 1.0

    return (
        recent_volume
        /
        old_volume
    )


# ============================================================
# HACİM İVMESİ
# ============================================================

def volume_acceleration(
    candles
):

    if len(candles) < 20:
        return 1.0

    recent = (
        sum(
            x["vol"]
            for x in candles[-5:]
        )
        /
        5
    )

    previous = (
        sum(
            x["vol"]
            for x in candles[-10:-5]
        )
        /
        5
    )

    if previous <= 0:
        return 1.0

    return (
        recent
        /
        previous
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

        last = p15[-1]

        # ====================================================
        # RSI
        # ====================================================

        rsi4 = rsi(p4)
        rsi1 = rsi(p1)
        rsi15 = rsi(p15)

        # ====================================================
        # HACİM
        # ====================================================

        v4 = volume_ratio(c4)
        v1 = volume_ratio(c1)
        v15 = volume_ratio(c15)

        acc1 = volume_acceleration(c1)
        acc15 = volume_acceleration(c15)

        # ====================================================
        # MOMENTUM
        # ====================================================

        mom1 = pct_change(
            p1[-1],
            p1[-5]
        )

        mom15 = pct_change(
            p15[-1],
            p15[-5]
        )

        # Son 5 adet 15M mum
        move5 = pct_change(
            p15[-1],
            p15[-6]
        )

        # Son 20 adet 15M mum
        move20 = pct_change(
            p15[-1],
            p15[-21]
        )

        # ====================================================
        # DİRENÇ
        # ====================================================

        resistance_price = max(
            x["high"]
            for x in c1[-25:]
        )

        if last <= 0:
            return None

        resistance_pct = (
            (
                resistance_price
                -
                last
            )
            /
            last
            *
            100
        )

        # ====================================================
        # HIGHER LOW
        # ====================================================

        recent_low = min(
            x["low"]
            for x in c1[-8:]
        )

        previous_low = min(
            x["low"]
            for x in c1[-16:-8]
        )

        higher_low = (
            recent_low
            >
            previous_low
        )

        # ====================================================
        # COMPRESSION
        # ====================================================

        recent_high_4h = max(
            x["high"]
            for x in c4[-10:]
        )

        recent_low_4h = min(
            x["low"]
            for x in c4[-10:]
        )

        if recent_low_4h > 0:

            range_pct = (
                (
                    recent_high_4h
                    -
                    recent_low_4h
                )
                /
                recent_low_4h
                *
                100
            )

        else:

            range_pct = 100

        compression = (
            range_pct < 18
        )

        # ====================================================
        # AŞIRI ISINMA FİLTRELERİ
        # ====================================================

        # 4H RSI çok sıcak
        if rsi4 > 72:
            return None

        # 1H RSI çok sıcak
        if rsi1 > 72:
            return None

        # 15M RSI çok sıcak
        if rsi15 > 76:
            return None

        # Son 75 dakikada büyük hareket
        if move5 > 10:
            return None

        # Son 5 saatte aşırı hareket
        if move20 > 18:
            return None

        # 15M hacmi çok büyükse pump başlamış olabilir
        if v15 > 7:
            return None

        # Direnç çok uzaktaysa erken breakout adayı zayıf
        if resistance_pct > 10:
            return None

        # ====================================================
        # TEKNİK PUAN
        #
        # Yaklaşık maksimum 65
        # Finalde 30 puana normalize edilir.
        # ====================================================

        score = 0

        # ----------------------------------------------------
        # 4H RSI
        # ----------------------------------------------------

        if 45 <= rsi4 <= 65:
            score += 8

        elif 40 <= rsi4 <= 70:
            score += 5

        # ----------------------------------------------------
        # 1H RSI
        # ----------------------------------------------------

        if 50 <= rsi1 <= 65:
            score += 8

        elif 45 <= rsi1 <= 70:
            score += 5

        # ----------------------------------------------------
        # 15M RSI
        # ----------------------------------------------------

        if 50 <= rsi15 <= 68:
            score += 7

        elif 45 <= rsi15 <= 72:
            score += 4

        # ----------------------------------------------------
        # 1H HACİM
        # ----------------------------------------------------

        if 0.9 <= v1 <= 2.5:
            score += 7

        elif v1 >= 0.7:
            score += 4

        # ----------------------------------------------------
        # 15M HACİM
        # ----------------------------------------------------

        if 0.8 <= v15 <= 3:
            score += 7

        elif v15 >= 0.7:
            score += 4

        # ----------------------------------------------------
        # 1H MOMENTUM
        # ----------------------------------------------------

        if 0 < mom1 <= 4:
            score += 5

        # ----------------------------------------------------
        # 15M MOMENTUM
        # ----------------------------------------------------

        if 0 < mom15 <= 3:
            score += 5

        # ----------------------------------------------------
        # HIGHER LOW
        # ----------------------------------------------------

        if higher_low:
            score += 6

        # ----------------------------------------------------
        # COMPRESSION
        # ----------------------------------------------------

        if compression:
            score += 5

        # ----------------------------------------------------
        # DİRENÇ
        # ----------------------------------------------------

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
# DEAL FLOW
#
# T = 1 -> BUY
# T = 2 -> SELL
#
# O = 1 -> OPEN
# O = 2 -> CLOSE
#
# v = kontrat miktarı
#
# NOTIONAL:
# price x volume x contractSize
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
        symbol,
        {}
    )

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

    # ========================================================
    # İŞLEMLERİ HESAPLA
    # ========================================================

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

            T = int(
                row.get(
                    "T",
                    0
                )
            )

            O = int(
                row.get(
                    "O",
                    0
                )
            )

            if price <= 0:
                continue

            if volume <= 0:
                continue

            # =================================================
            # GERÇEKLEŞTİRİLEN KONTRAT NOTIONAL
            # =================================================

            notional = (
                price
                *
                volume
                *
                contract_size
            )

            if notional <= 0:
                continue

            # =================================================
            # TÜM İŞLEMLER
            # =================================================

            if T == 1:

                buy_all += notional

            elif T == 2:

                sell_all += notional

            # =================================================
            # SADECE OPEN
            # =================================================

            if O == 1:

                open_count += 1

                if T == 1:

                    buy_open += notional

                elif T == 2:

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

        # ====================================================
        # OPEN VERİSİ YOKSA YEDEK
        # ====================================================

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
    # OPEN FLOW / 24H
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
# PARA AKIŞI PUANI
#
# MAKSIMUM 50
#
# SADECE NET % DEĞİL.
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
    # 1. NET AKIŞ
    # MAKS 25
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
    # 2. ALIŞ BASKISI
    # MAKS 12
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
    # 3. OPEN FLOW / 24H
    # MAKS 8
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
    # 4. MUTLAK OPEN NOTIONAL
    # MAKS 5
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
    # %100 BUY'ı OTOMATİK OLARAK MÜKEMMEL KABUL ETME
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
# FİNAL ANALİZ
# ============================================================

def final_analyze(
    tech
):

    symbol = tech[
        "symbol"
    ]

    flow = get_deal_flow(
        symbol
    )

    if not flow:
        return None

    # ========================================================
    # PARA SKORU
    # ========================================================

    mscore = money_score(
        flow
    )

    if mscore < MIN_MONEY_SCORE:

        return None

    # ========================================================
    # TEKNİK 30 PUAN
    # ========================================================

    tech_score = tech[
        "technical_score"
    ]

    technical_part = min(
        (
            tech_score
            /
            65
            *
            30
        ),
        30
    )

    # ========================================================
    # HACİM 20 PUAN
    # ========================================================

    volume_part = 0

    # --------------------------------------------------------
    # 1H HACİM
    # --------------------------------------------------------

    if tech["v1"] >= 2.5:

        volume_part += 8

    elif tech["v1"] >= 1.8:

        volume_part += 7

    elif tech["v1"] >= 1.3:

        volume_part += 5

    elif tech["v1"] >= 1.0:

        volume_part += 3

    # --------------------------------------------------------
    # 15M HACİM
    # --------------------------------------------------------

    if tech["v15"] >= 2.5:

        volume_part += 8

    elif tech["v15"] >= 1.8:

        volume_part += 7

    elif tech["v15"] >= 1.3:

        volume_part += 5

    elif tech["v15"] >= 1.0:

        volume_part += 3

    # --------------------------------------------------------
    # HACİM İVMESİ
    # --------------------------------------------------------

    if tech["acc1"] >= 1.5:

        volume_part += 2

    if tech["acc15"] >= 1.5:

        volume_part += 2

    volume_part = min(
        volume_part,
        20
    )

    # ========================================================
    # TOPLAM
    # ========================================================

    total = (
        mscore
        +
        technical_part
        +
        volume_part
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
    # FUNDING CEZASI
    # ========================================================

    funding = flow[
        "funding_rate"
    ]

    if funding > 0.0015:

        total -= 6

    elif funding > 0.001:

        total -= 3

    # ========================================================
    # NEGATİF PARA AKIŞI KESİN RED
    # ========================================================

    if flow["net_pct"] < 0:

        return None

    # ========================================================
    # FİNAL SKOR
    # ========================================================

    if total < MIN_SCORE:

        return None

    result = dict(
        tech
    )

    result[
        "money_score"
    ] = mscore

    result[
        "technical_part"
    ] = technical_part

    result[
        "volume_part"
    ] = volume_part

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
# FIRE SEVİYESİ
# ============================================================

def fire_level(
    net,
    money
):

    if (
        money >= 42
        and
        net >= 20
    ):

        return "🔥🔥🔥"

    if (
        money >= 34
        and
        net >= 12
    ):

        return "🔥🔥"

    if money >= 25:

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
# TELEGRAM MESAJ
# ============================================================

def format_telegram(
    x
):

    symbol = x[
        "symbol"
    ]

    score = x[
        "total_score"
    ]

    flow = x[
        "flow"
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

    open_vs_24h = flow[
        "open_vs_24h"
    ]

    money = x[
        "money_score"
    ]

    fire = fire_level(
        net,
        money
    )

    volume = x[
        "v1"
    ]

    resistance = x[
        "resistance"
    ]

    money_text = format_money(
        open_total
    )

    return (
        "🚨 PRE-PUMP\n\n"
        f"🪙 {symbol}\n"
        f"⭐ {score:.0f}/100\n\n"
        f"💰 Para Akışı: "
        f"{fire} {net:+.1f}%\n"
        f"💵 Açılış Akışı: "
        f"{money_text}\n"
        f"🟢 Alış Baskısı: "
        f"{buy_share:.0f}%\n"
        f"📊 Akış/24H: "
        f"{open_vs_24h:.2f}%\n"
        f"📈 Hacim: "
        f"{volume:.1f}x\n"
        f"🎯 Direnç: "
        f"%{resistance:.1f}\n\n"
        "TP1 +3% | TP2 +6% | TP3 +10%"
    )


# ============================================================
# DEBUG FLOW
# ============================================================

def debug_flow(
    symbol
):

    print("")
    print("=" * 60)
    print("FLOW DEBUG")
    print("=" * 60)

    flow = get_deal_flow(
        symbol
    )

    if not flow:

        print(
            f"Flow bulunamadı: {symbol}"
        )

        return

    print(
        f"Coin: {symbol}"
    )

    print(
        "Open Total: "
        f"${flow['open_total']:,.2f}"
    )

    print(
        "Buy Open: "
        f"${flow['buy_open']:,.2f}"
    )

    print(
        "Sell Open: "
        f"${flow['sell_open']:,.2f}"
    )

    print(
        "Net: "
        f"{flow['net_pct']:+.2f}%"
    )

    print(
        "Buy Share: "
        f"{flow['buy_share']:.2f}%"
    )

    print(
        "Open / 24H: "
        f"{flow['open_vs_24h']:.4f}%"
    )

    print(
        "Open Count: "
        f"{flow['open_count']}"
    )

    print(
        "Contract Size: "
        f"{flow['contract_size']}"
    )

    print(
        "Funding: "
        f"{flow['funding_rate']}"
    )

    print(
        "Money Score: "
        f"{money_score(flow)}"
    )

    print(
        "=" * 60
    )


# ============================================================
# MAIN
# ============================================================

def main():

    started = time.time()

    print("=" * 65)
    print("MEXC PRE-PUMP RADAR V9")
    print("=" * 65)

    print(
        "PARA AKIŞI = 50 PUAN"
    )

    print(
        "TEKNİK = 30 PUAN"
    )

    print(
        "HACİM = 20 PUAN"
    )

    print(
        "AMAÇ = PUMP ÖNCESİ ADAY"
    )

    # ========================================================
    # CONTRACTLAR
    # ========================================================

    print("")
    print(
        "MEXC Futures coinleri alınıyor..."
    )

    symbols = get_contracts()

    print(
        f"Futures: {len(symbols)}"
    )

    if not symbols:

        print(
            "Futures coin bulunamadı."
        )

        return

    # ========================================================
    # API TEST
    # ========================================================

    test_symbol = "BTC_USDT"

    print("")
    print("API TEST...")

    test_kline = get_klines(
        test_symbol,
        "Min15"
    )

    if test_kline:

        print("Kline OK")

    else:

        print("Kline HATA")

    test_ticker = get_ticker(
        test_symbol
    )

    if test_ticker:

        print("Ticker OK")

        try:

            amount24 = float(
                test_ticker.get(
                    "amount24",
                    0
                )
            )

            print(
                f"24H Amount: "
                f"{amount24:,.0f}"
            )

        except Exception:

            pass

    else:

        print("Ticker HATA")

    test_flow = get_deal_flow(
        test_symbol
    )

    if test_flow:

        print(
            "İşlem akışı OK | "
            f"Net: "
            f"{test_flow['net_pct']:.2f}% | "
            f"Buy: "
            f"{test_flow['buy_share']:.1f}% | "
            f"Open: "
            f"${test_flow['open_total']:,.0f}"
        )

    else:

        print(
            "İşlem akışı okunamadı."
        )

    # ========================================================
    # TEKNİK TARAMA
    # ========================================================

    print("")
    print(
        "TEKNİK ÖN FİLTRE..."
    )

    technical_candidates = []

    total_symbols = len(
        symbols
    )

    def worker(symbol):

        return analyze_technical(
            symbol
        )

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {}

        for symbol in symbols:

            future = executor.submit(
                worker,
                symbol
            )

            futures[future] = symbol

        done = 0

        for future in as_completed(
            futures
        ):

            done += 1

            try:

                result = future.result()

            except Exception:

                result = None

            if result:

                technical_candidates.append(
                    result
                )

            if done % 100 == 0:

                print(
                    f"İlerleme "
                    f"{done}/{total_symbols} "
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
        f"Teknik aday: "
        f"{len(technical_candidates)}"
    )

    # ========================================================
    # PARA AKIŞI
    # ========================================================

    print("")
    print(
        "PARA GİRİŞİ TARAMASI..."
    )

    final_candidates = []

    flow_found = 0

    money_strong = 0

    total_technical = len(
        technical_candidates
    )

    for i, tech in enumerate(
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

                money_strong += 1

            # ------------------------------------------------
            # Final
            #
            # Burada tekrar API çağrısı yapmamak için
            # flow'u
