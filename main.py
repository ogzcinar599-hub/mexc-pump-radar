import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 🚀 MEXC PRE-PUMP RADAR V8
#
# AMAÇ:
# LSK gibi büyük hareket başlamadan ÖNCE adayları bulmak.
#
# ANA ÖNCELİK:
# 💰 PARA / POZİSYON AKIŞI
# 🔥 ALIŞ BASKISI
# 📈 HACİM İVMESİ
# 🎯 DİRENCE YAKINLIK
# 🧊 AŞIRI ISINMAMIŞ YAPI
#
# SKOR:
# 💰 PARA AKIŞI     = 50
# 📊 TEKNİK         = 30
# 📈 HACİM          = 20
# TOPLAM            = 100
# ============================================================


# ============================================================
# AYARLAR
# ============================================================

BASE = "https://api.mexc.com"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MAX_WORKERS = 6

# Her coin için alınacak mum sayısı
CANDLE_COUNT = 90

# Teknik filtreden sonra para akışına girecek maksimum coin
TECH_TOP = 140

# Telegram maksimum mesaj
MAX_ALERTS = 6

# Minimum final puan
MIN_SCORE = 55

# API istek aralığı
REQUEST_INTERVAL = 0.11

# Son işlemler
DEALS_LIMIT = 100

session = requests.Session()

_last_request = 0


# ============================================================
# API REQUEST
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

        print("⚠️ Telegram ENV bulunamadı")

        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
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
# FUTURES COINLER
# ============================================================

def get_symbols():

    data = mexc_get(
        "/api/v1/contract/detail"
    )

    if not data:

        return []

    rows = data.get(
        "data",
        []
    )

    symbols = []

    for item in rows:

        symbol = item.get(
            "symbol",
            ""
        )

        if not symbol.endswith("_USDT"):
            continue

        # Aktif kontratlar
        state = item.get(
            "state"
        )

        if state not in [
            0,
            1,
            "0",
            "1",
            None
        ]:
            continue

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

    # 90 adet 4 saatlik veri için geniş pencere
    start = end - (
        CANDLE_COUNT *
        4 *
        3600
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
                    float(times[i]),

                "open":
                    float(opens[i]),

                "close":
                    float(closes[i]),

                "high":
                    float(highs[i]),

                "low":
                    float(lows[i]),

                "vol":
                    float(vols[i])

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
            100 /
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
        (current - previous)
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
        base + recent
    ):

        return 1.0

    recent_part = candles[-recent:]

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

    if len(candles) < 30:

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

        # Son 5 adet 15M mumdaki hareket
        move5 = pct_change(
            p15[-1],
            p15[-6]
        )

        # ====================================================
        # DİRENÇ
        # ====================================================

        resistance_price = max(
            x["high"]
            for x in c1[-25:]
        )

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

        recent_high = max(
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
                    recent_high
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
        # 🚫 AŞIRI ISINMIŞ COİNLERİ ELE
        # ====================================================

        # 4H fazla yükselmiş
        if rsi4 > 72:
            return None

        # 1H fazla yükselmiş
        if rsi1 > 72:
            return None

        # 15M aşırı sıcak
        if rsi15 > 76:
            return None

        # Son 75 dakikada zaten güçlü hareket
        if move5 > 10:
            return None

        # 15M'de devasa hacim = hareket başlamış olabilir
        if v15 > 7:
            return None

        # Direnç çok uzaktaysa erken breakout ihtimali zayıf
        if resistance_pct > 10:
            return None

        # ====================================================
        # TEKNİK PUAN
        #
        # Maksimum yaklaşık 65
        # Daha sonra 30 puana normalize edilecek.
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
            "symbol": symbol
        }
    )

    if not data:

        return None

    return data.get(
        "data"
    )


# ============================================================
# MEXC İŞLEM AKIŞI
#
# T = 1 → BUY
# T = 2 → SELL
#
# O = 1 → OPEN
# O = 2 → CLOSE
#
# Öncelik:
# BUY OPEN
# SELL OPEN
#
# Bu değer gerçek fiat para girişi değildir.
# Futures pozisyon açılış akışı proxy'sidir.
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

            notional = (
                abs(price * volume)
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
            # YENİ POZİSYON
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
    # OPEN FLOW VARSA ONU KULLAN
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

    # ========================================================
    # YEDEK: TÜM İŞLEMLER
    # ========================================================

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

    return {

        "buy_open":
            buy_open,

        "sell_open":
            sell_open,

        "open_total":
            open_total,

        "buy_all":
            buy_all,

        "sell_all":
            sell_all,

        "net":
            net,

        "net_pct":
            net_pct,

        "buy_share":
            buy_share,

        "open_count":
            open_count,

        "flow_type":
            flow_type
    }


# ============================================================
# PARA GİRİŞİ SKORU
#
# MAKSİMUM 50 PUAN
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

    score = 0

    # ========================================================
    # NET AKIŞ
    # ========================================================

    if net >= 30:

        score += 35

    elif net >= 20:

        score += 30

    elif net >= 15:

        score += 25

    elif net >= 10:

        score += 20

    elif net >= 7:

        score += 15

    elif net >= 4:

        score += 10

    elif net >= 0:

        score += 5

    else:

        score -= 15

    # ========================================================
    # BUY SHARE
    # ========================================================

    if buy_share >= 75:

        score += 15

    elif buy_share >= 68:

        score += 12

    elif buy_share >= 62:

        score += 9

    elif buy_share >= 56:

        score += 5

    elif buy_share < 45:

        score -= 10

    # ========================================================
    # AŞIRI POZİTİF AKIŞ
    #
    # Çok yüksek değer bazen hareketin zaten başladığını
    # gösterebilir.
    # ========================================================

    if net > 60:

        score -= 5

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

    # ========================================================
    # PARA AKIŞI
    # ========================================================

    flow = get_deal_flow(
        symbol
    )

    if not flow:

        return None

    mscore = money_score(
        flow
    )

    # ========================================================
    # PARA GİRİŞİ ÇOK ZAYIFSA ELE
    # ========================================================

    if mscore < 15:

        return None

    # ========================================================
    # TEKNİK 30 PUANA NORMALİZE
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

        volume_part += 10

    elif tech["v1"] >= 1.8:

        volume_part += 8

    elif tech["v1"] >= 1.3:

        volume_part += 6

    elif tech["v1"] >= 1.0:

        volume_part += 4

    # --------------------------------------------------------
    # 15M HACİM
    # --------------------------------------------------------

    if tech["v15"] >= 2.5:

        volume_part += 10

    elif tech["v15"] >= 1.8:

        volume_part += 8

    elif tech["v15"] >= 1.3:

        volume_part += 6

    elif tech["v15"] >= 1.0:

        volume_part += 4

    volume_part = min(
        volume_part,
        20
    )

    # ========================================================
    # TOPLAM 100
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

    # ========================================================
    # FINAL FİLTRE
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
# FIRE LEVEL
# ============================================================

def fire_level(
    net
):

    if net >= 25:

        return "🔥🔥🔥"

    if net >= 15:

        return "🔥🔥"

    if net >= 7:

        return "🔥"

    return "⚡"


# ============================================================
# TELEGRAM MESAJI
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

    fire = fire_level(
        net
    )

    # 1H hacmini ana hacim olarak göster
    volume = x[
        "v1"
    ]

    resistance = x[
        "resistance"
    ]

    return (
        "🚨 PRE-PUMP\n\n"

        f"🪙 {symbol}\n"

        f"⭐ {score:.0f}/100\n\n"

        f"💰 Para Girişi: "
        f"{fire} "
        f"{net:+.1f}%\n"

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

    print("=" * 60)

    print(
        "🚀 MEXC PRE-PUMP RADAR V8"
    )

    print("=" * 60)

    print(
        "💰 ANA FİLTRE: PARA GİRİŞİ"
    )

    print(
        "🔥 YENİ POZİSYON + ALIŞ BASKISI"
    )

    print(
        "🎯 SADECE GÜÇLÜ ADAYLAR"
    )

    # ========================================================
    # API TEST
    # ========================================================

    print(
        "\n🧪 API TEST..."
    )

    test_symbol = "BTC_USDT"

    test_kline = get_klines(
        test_symbol,
        "Min15"
    )

    if test_kline:

        print(
            "✅ Kline OK"
        )

    else:

        print(
            "❌ Kline HATA"
        )

    test_ticker = get_ticker(
        test_symbol
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
        test_symbol
    )

    if test_flow:

        print(
            "✅ İşlem akışı OK | "
            f"Net: "
            f"{test_flow['net_pct']:.2f}% | "
            f"Buy: "
            f"{test_flow['buy_share']:.1f}%"
        )

    else:

        print(
            "⚠️ İşlem akışı okunamadı"
        )

    # ========================================================
    # SYMBOLS
    # ========================================================

    print(
        "\n🔎 MEXC Futures coinleri alınıyor..."
    )

    symbols = get_symbols()

    print(
        f"✅ Futures: "
        f"{len(symbols)}"
    )

    if not symbols:

        print(
            "❌ Futures coin bulunamadı"
        )

        return

    # ========================================================
    # TEKNİK TARAMA
    # ========================================================

    print(
        "\n🟣 TEKNİK ÖN FİLTRE..."
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

        futures = {
            executor.submit(
                worker,
                symbol
            ): symbol

            for symbol in symbols
        }

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

            if (
                done % 100
                == 0
            ):

                print(
                    f"İlerleme "
                    f"{done}/"
                    f"{total_symbols} "
                    f"| Teknik aday "
                    f"{len(technical_candidates)}"
                )

    # ========================================================
    # TEKNİK SKORA GÖRE SIRALA
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

    print(
        "\n✅ Teknik aday: "
        f"{len(technical_candidates)}"
    )

    # ========================================================
    # PARA AKIŞI
    # ========================================================

    print(
        "\n💰 PARA GİRİŞİ TARAMASI..."
    )

    final_candidates = []

    total_technical = len(
        technical_candidates
    )

    for i, tech in enumerate(
        technical_candidates,
        1
    ):

        result = final_analyze(
            tech
        )

        if result:

            final_candidates.append(
                result
            )

        if (
            i % 20
            == 0
        ):

            print(
                f"Para akışı "
                f"{i}/"
                f"{total_technical} "
                f"| Güçlü "
                f"{len(final_candidates)}"
            )

    # ========================================================
    # FİNAL SIRALAMA
    # ========================================================

    final_candidates.sort(
        key=lambda x: (
            x["total_score"],
            x["money_score"],
            x["flow"]["net_pct"]
        ),
        reverse=True
    )

    print(
        "\n💰 Güçlü para girişi: "
        f"{len(final_candidates)}"
    )

    # ========================================================
    # KONSOLDA EN İYİLERİ GÖSTER
    # ========================================================

    if final_candidates:

        print(
            "\n🏆 EN GÜÇLÜ ADAYLAR:"
        )

        for x in final_candidates[
            :10
        ]:

            print(
                f"{x['symbol']} | "
                f"Skor "
                f"{x['total_score']:.1f} | "
                f"Para "
                f"{x['money_score']} | "
                f"Net "
                f"{x['flow']['net_pct']:+.1f}% | "
                f"Buy "
                f"{x['flow']['buy_share']:.1f}%"
            )

    else:

        print(
            "📭 Güçlü para girişi bulunamadı."
        )

    # ========================================================
    # TELEGRAM
    # ========================================================

    sent = 0

    for x in final_candidates[
        :MAX_ALERTS
    ]:

        message = format_telegram(
            x
        )

        print(
            "\n"
            + "-" * 50
        )

        print(
            message
        )

        print(
            "-" * 50
        )

        if send_telegram(
            message
        ):

            sent += 1

    # ========================================================
    # SUMMARY
    # ========================================================

    elapsed = (
        time.time()
        -
        started
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "✅ V8 RADAR TAMAMLANDI"
    )

    print(
        f"⏱️ Süre: "
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
        f"💰 Para girişi: "
        f"{len(final_candidates)}"
    )

    print(
        f"📨 Telegram: "
        f"{sent}"
    )

    print(
        "=" * 60
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    print(
        "### MEXC PRE-PUMP RADAR V8 BAŞLADI ###"
    )

    main()
