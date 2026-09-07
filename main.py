import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# MEXC FUTURES PUMP RADAR
#
# SADECE USDT-M FUTURES
#
# 4H  = DIP + DÖNÜŞ
# 1H  = TREND
# 15M = MOMENTUM
#
# Amaç:
# Zaten pump olmuş coinleri değil,
# pump öncesi güç toplamaya başlayan Futures coinlerini bulmak.
# ============================================================


BASE = "https://api.mexc.com"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ============================================================
# AYARLAR
# ============================================================

# 100 üzerinden minimum skor
MIN_SCORE = 72

# Güçlü sinyal seviyesi
STRONG_SCORE = 82

# Futures 24H minimum işlem hacmi
MIN_24H_VOLUME = 300000

# 24H değişim
MIN_24H_CHANGE = -15
MAX_24H_CHANGE = 12

# Bir taramada maksimum sinyal
MAX_SIGNALS_PER_SCAN = 3

# Aynı coin tekrar kaç saat gelmesin
DUPLICATE_HOURS = 6

# TP / STOP
TP1_PCT = 1.8
TP2_PCT = 3.5
TP3_PCT = 5.5
STOP_PCT = 2.2

# Futures API rate limit için
MAX_WORKERS = 8

# Hacme göre ilk kaç Futures taransın
MAX_SYMBOLS_TO_SCAN = 180

# ============================================================
# DOSYALAR
# ============================================================

SENT_FILE = "sent_signals.json"


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 PumpRadar-Futures/2.0"
})


# ============================================================
# SENT SIGNALS
# ============================================================

def load_sent():

    try:

        if os.path.exists(SENT_FILE):

            with open(
                SENT_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                return json.load(f)

    except Exception as e:

        print("sent_signals okuma hatası:", e)

    return {}


def save_sent(data):

    try:

        with open(
            SENT_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print("sent_signals yazma hatası:", e)


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(text):

    if not BOT_TOKEN:

        print("❌ TELEGRAM_BOT_TOKEN eksik")

        return False

    if not CHAT_ID:

        print("❌ TELEGRAM_CHAT_ID eksik")

        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    payload = {

        "chat_id": CHAT_ID,

        "text": text,

        "parse_mode": "HTML",

        "disable_web_page_preview": True
    }

    try:

        response = session.post(
            url,
            json=payload,
            timeout=15
        )

        print(
            "Telegram HTTP:",
            response.status_code
        )

        if response.status_code == 200:

            print("✅ Telegram mesajı gönderildi")

            return True

        print(
            "❌ Telegram cevap:",
            response.text[:500]
        )

    except Exception as e:

        print(
            "❌ Telegram bağlantı hatası:",
            e
        )

    return False


# ============================================================
# TELEGRAM TEST
# ============================================================

def telegram_test():

    print("")
    print("=" * 60)
    print("TELEGRAM TEST")
    print("=" * 60)

    message = (
        "🟢 <b>PUMP RADAR AKTİF</b>\n\n"

        "✅ Telegram bağlantısı çalışıyor.\n"
        "✅ GitHub Actions çalışıyor.\n"
        "✅ MEXC Futures bağlantısı çalışıyor.\n\n"

        "🔎 4H dip + dönüş\n"
        "📈 1H trend\n"
        "⚡ 15M momentum\n\n"

        "🎯 Sadece USDT Futures taranıyor.\n\n"

        "Radar taramaya başladı."
    )

    return send_telegram(message)


# ============================================================
# GENERIC JSON
# ============================================================

def get_json(url, params=None):

    try:

        response = session.get(
            url,
            params=params,
            timeout=15
        )

        if response.status_code != 200:

            print(
                "HTTP hata:",
                response.status_code,
                url
            )

            return None

        data = response.json()

        return data

    except Exception as e:

        print(
            "GET hata:",
            e
        )

        return None


# ============================================================
# FUTURES CONTRACTS
# ============================================================

def get_futures_symbols():

    data = get_json(
        f"{BASE}/api/v1/contract/detail"
    )

    if not data:

        print("❌ Futures contract bilgisi alınamadı.")

        return []

    contracts = data.get(
        "data",
        []
    )

    if not isinstance(
        contracts,
        list
    ):

        return []

    symbols = []

    for contract in contracts:

        try:

            symbol = contract.get(
                "symbol",
                ""
            )

            quote_coin = contract.get(
                "quoteCoin",
                ""
            )

            settle_coin = contract.get(
                "settleCoin",
                ""
            )

            state = contract.get(
                "state",
                99
            )

            hidden = contract.get(
                "isHidden",
                False
            )

            # ------------------------------------------------
            # SADECE USDT-M FUTURES
            # ------------------------------------------------

            if quote_coin != "USDT":
                continue

            if settle_coin != "USDT":
                continue

            if not symbol.endswith("_USDT"):
                continue

            # Aktif sözleşme
            if state != 0:
                continue

            # Gizli ürünleri alma
            if hidden:
                continue

            symbols.append(symbol)

        except Exception:

            continue

    print(
        "MEXC USDT Futures:",
        len(symbols)
    )

    return symbols


# ============================================================
# FUTURES TICKER
# ============================================================

def get_futures_tickers():

    data = get_json(
        f"{BASE}/api/v1/contract/ticker"
    )

    if not data:

        return {}

    raw = data.get(
        "data",
        []
    )

    # Tek ticker gelirse
    if isinstance(
        raw,
        dict
    ):

        raw = [raw]

    if not isinstance(
        raw,
        list
    ):

        return {}

    result = {}

    for x in raw:

        try:

            symbol = x.get(
                "symbol",
                ""
            )

            if not symbol.endswith(
                "_USDT"
            ):

                continue

            price = float(
                x.get(
                    "lastPrice",
                    0
                )
            )

            volume24 = float(
                x.get(
                    "volume24",
                    0
                )
            )

            amount24 = float(
                x.get(
                    "amount24",
                    0
                )
            )

            rise_fall_rate = float(
                x.get(
                    "riseFallRate",
                    0
                )
            )

            # MEXC Futures API
            # riseFallRate değerini decimal verir.
            # Örn -0.0176 = -1.76%
            change = (
                rise_fall_rate * 100
            )

            result[symbol] = {

                "price": price,

                "volume": volume24,

                "amount": amount24,

                "change": change,

                "high24": float(
                    x.get(
                        "high24Price",
                        0
                    )
                ),

                "low24": float(
                    x.get(
                        "lower24Price",
                        0
                    )
                ),

                "funding": float(
                    x.get(
                        "fundingRate",
                        0
                    )
                )
            }

        except Exception:

            continue

    print(
        "Futures ticker:",
        len(result)
    )

    return result


# ============================================================
# FUTURES KLINE
# ============================================================

def get_klines(
    symbol,
    interval
):

    try:

        url = (
            f"{BASE}/api/v1/contract/"
            f"kline/{symbol}"
        )

        response = session.get(
            url,
            params={
                "interval": interval
            },
            timeout=15
        )

        if response.status_code != 200:

            print(
                "Kline HTTP:",
                symbol,
                response.status_code
            )

            return []

        result = response.json()

        data = result.get(
            "data"
        )

        if not data:

            return []

        times = data.get(
            "time",
            []
        )

        opens = data.get(
            "open",
            []
        )

        closes = data.get(
            "close",
            []
        )

        highs = data.get(
            "high",
            []
        )

        lows = data.get(
            "low",
            []
        )

        volumes = data.get(
            "vol",
            []
        )

        length = min(
            len(times),
            len(opens),
            len(closes),
            len(highs),
            len(lows),
            len(volumes)
        )

        candles = []

        for i in range(length):

            try:

                candles.append({

                    "time": int(
                        times[i]
                    ),

                    "open": float(
                        opens[i]
                    ),

                    "close": float(
                        closes[i]
                    ),

                    "high": float(
                        highs[i]
                    ),

                    "low": float(
                        lows[i]
                    ),

                    "volume": float(
                        volumes[i]
                    )
                })

            except Exception:

                continue

        # ----------------------------------------------------
        # Son mum halen açık olabilir.
        #
        # Analizde sadece kapanmış mumları kullanıyoruz.
        # ----------------------------------------------------

        if len(candles) > 2:

            candles = candles[:-1]

        return candles

    except Exception as e:

        print(
            "Kline hata:",
            symbol,
            interval,
            e
        )

        return []


# ============================================================
# EMA
# ============================================================

def ema(
    values,
    period
):

    if len(values) < period:

        return None

    multiplier = 2 / (
        period + 1
    )

    value = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        value = (
            (
                price - value
            )
            * multiplier
        ) + value

    return value


# ============================================================
# RSI
# ============================================================

def rsi(
    values,
    period=14
):

    if len(values) < period + 1:

        return None

    gains = []
    losses = []

    for i in range(
        1,
        len(values)
    ):

        change = (
            values[i]
            - values[i - 1]
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
        sum(
            gains[:period]
        )
        / period
    )

    avg_loss = (
        sum(
            losses[:period]
        )
        / period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            (
                avg_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if avg_loss == 0:

        return 100

    rs = (
        avg_gain
        / avg_loss
    )

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# 4H ANA DİP + DÖNÜŞ
# ============================================================

def analyze_4h(candles):

    if len(candles) < 60:

        return None

    closes = [
        x["close"]
        for x in candles
    ]

    current = closes[-1]

    previous = closes[-2]

    ema20 = ema(
        closes,
        20
    )

    ema50 = ema(
        closes,
        50
    )

    ema20_prev = ema(
        closes[:-1],
        20
    )

    rsi_now = rsi(
        closes,
        14
    )

    if not all([
        ema20,
        ema50,
        ema20_prev,
        rsi_now
    ]):

        return None

    # --------------------------------------------------------
    # 4H SON 20 MUM DİPİ
    # --------------------------------------------------------

    recent = candles[-21:]

    swing_low = min(
        x["low"]
        for x in recent
    )

    swing_high = max(
        x["high"]
        for x in recent
    )

    if swing_low <= 0:

        return None

    recovery = (
        (
            current
            - swing_low
        )
        / swing_low
    ) * 100

    # Çok fazla yükselmişse
    # pump zaten başlamış olabilir.
    if recovery > 12:

        return None

    # --------------------------------------------------------
    # DİBE UZAKLIK
    # --------------------------------------------------------

    dip_distance = (
        (
            current
            - swing_low
        )
        / swing_low
    ) * 100

    # --------------------------------------------------------
    # SON MUM
    # --------------------------------------------------------

    last = candles[-1]

    body = abs(
        last["close"]
        - last["open"]
    )

    candle_range = (
        last["high"]
        - last["low"]
    )

    if candle_range > 0:

        body_ratio = (
            body
            / candle_range
        )

    else:

        body_ratio = 0

    # --------------------------------------------------------
    # EMA EĞİMİ
    # --------------------------------------------------------

    ema_slope = (
        (
            ema20
            - ema20_prev
        )
        / ema20_prev
    ) * 100

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 0

    # Dip bölgesi
    if 1 <= dip_distance <= 4:

        score += 25

    elif 4 < dip_distance <= 7:

        score += 20

    elif 7 < dip_distance <= 10:

        score += 12

    elif dip_distance <= 12:

        score += 6

    # EMA20 dönüş
    if ema20 > ema20_prev:

        score += 20

    # Fiyat EMA20'ye yakınsa
    ema_distance = (
        (
            current
            - ema20
        )
        / ema20
    ) * 100

    if -1.5 <= ema_distance <= 3:

        score += 15

    elif -3 <= ema_distance < -1.5:

        score += 10

    elif 3 < ema_distance <= 6:

        score += 8

    # RSI
    if 38 <= rsi_now <= 52:

        score += 20

    elif 52 < rsi_now <= 58:

        score += 15

    elif 34 <= rsi_now < 38:

        score += 10

    elif 58 < rsi_now <= 62:

        score += 8

    # Son mum yeşil
    if last["close"] > last["open"]:

        score += 10

    # Mum gövdesi
    if body_ratio >= 0.60:

        score += 10

    elif body_ratio >= 0.35:

        score += 5

    # Fiyat EMA50 üzerinde ise bonus
    if current > ema50:

        score += 5

    return {

        "score": min(
            score,
            100
        ),

        "current": current,

        "ema20": ema20,

        "ema50": ema50,

        "rsi": rsi_now,

        "swing_low": swing_low,

        "swing_high": swing_high,

        "recovery": recovery,

        "ema_distance": ema_distance,

        "ema_slope": ema_slope
    }


# ============================================================
# 1H TREND
# ============================================================

def analyze_1h(candles):

    if len(candles) < 60:

        return None

    closes = [
        x["close"]
        for x in candles
    ]

    current = closes[-1]

    previous = closes[-2]

    ema20 = ema(
        closes,
        20
    )

    ema50 = ema(
        closes,
        50
    )

    ema20_prev = ema(
        closes[:-1],
        20
    )

    rsi_now = rsi(
        closes,
        14
    )

    if not all([
        ema20,
        ema50,
        ema20_prev,
        rsi_now
    ]):

        return None

    score = 0

    # EMA20
    if current >= ema20:

        score += 30

    elif current >= ema20 * 0.997:

        score += 20

    elif current >= ema20 * 0.99:

        score += 10

    # EMA20 slope
    if ema20 > ema20_prev:

        score += 25

    elif ema20 >= ema20_prev * 0.999:

        score += 10

    # EMA50
    if current > ema50:

        score += 20

    elif current >= ema50 * 0.995:

        score += 10

    # RSI
    if 48 <= rsi_now <= 65:

        score += 20

    elif 42 <= rsi_now < 48:

        score += 12

    elif 65 < rsi_now <= 70:

        score += 10

    # Son mum
    if current > previous:

        score += 5

    return {

        "score": min(
            score,
            100
        ),

        "current": current,

        "ema20": ema20,

        "ema50": ema50,

        "rsi": rsi_now
    }


# ============================================================
# 15M MOMENTUM
# ============================================================

def analyze_15m(candles):

    if len(candles) < 50:

        return None

    closes = [
        x["close"]
        for x in candles
    ]

    current = closes[-1]

    previous = closes[-2]

    ema20 = ema(
        closes,
        20
    )

    rsi_now = rsi(
        closes,
        14
    )

    if not ema20 or not rsi_now:

        return None

    score = 0

    # EMA20
    if current > ema20:

        score += 25

    elif current >= ema20 * 0.997:

        score += 15

    # RSI
    if 50 <= rsi_now <= 68:

        score += 25

    elif 45 <= rsi_now < 50:

        score += 15

    elif 68 < rsi_now <= 72:

        score += 10

    # Son mum
    if current > previous:

        score += 15

    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    recent_volumes = [
        x["volume"]
        for x in candles[-21:-1]
    ]

    if recent_volumes:

        avg_volume = (
            sum(
                recent_volumes
            )
            / len(
                recent_volumes
            )
        )

        current_volume = (
            candles[-1]["volume"]
        )

        if avg_volume > 0:

            volume_ratio = (
                current_volume
                / avg_volume
            )

        else:

            volume_ratio = 0

    else:

        volume_ratio = 0

    if volume_ratio >= 2.0:

        score += 35

    elif volume_ratio >= 1.5:

        score += 28

    elif volume_ratio >= 1.25:

        score += 20

    elif volume_ratio >= 1.10:

        score += 10

    return {

        "score": min(
            score,
            100
        ),

        "current": current,

        "ema20": ema20,

        "rsi": rsi_now,

        "volume_ratio": volume_ratio
    }


# ============================================================
# COIN ANALİZİ
# ============================================================

def analyze_symbol(
    symbol,
    ticker
):

    try:

        change = ticker.get(
            "change",
            0
        )

        volume = ticker.get(
            "amount",
            0
        )

        price = ticker.get(
            "price",
            0
        )

        # ----------------------------------------------------
        # 24H
        # ----------------------------------------------------

        if price <= 0:

            return None

        if volume < MIN_24H_VOLUME:

            return None

        if change < MIN_24H_CHANGE:

            return None

        if change > MAX_24H_CHANGE:

            return None

        # ----------------------------------------------------
        # 4H
        # ----------------------------------------------------

        candles_4h = get_klines(
            symbol,
            "Hour4"
        )

        if not candles_4h:

            return None

        four = analyze_4h(
            candles_4h
        )

        if not four:

            return None

        # ----------------------------------------------------
        # 1H
        # ----------------------------------------------------

        candles_1h = get_klines(
            symbol,
            "Min60"
        )

        if not candles_1h:

            return None

        one = analyze_1h(
            candles_1h
        )

        if not one:

            return None

        # ----------------------------------------------------
        # 15M
        # ----------------------------------------------------

        candles_15m = get_klines(
            symbol,
            "Min15"
        )

        if not candles_15m:

            return None

        fifteen = analyze_15m(
            candles_15m
        )

        if not fifteen:

            return None

        # ----------------------------------------------------
        # AĞIRLIKLI SKOR
        #
        # 4H  = %50
        # 1H  = %30
        # 15M = %20
        # ----------------------------------------------------

        score = (
            four["score"] * 0.50
            +
            one["score"] * 0.30
            +
            fifteen["score"] * 0.20
        )

        score = round(
            score
        )

        if score < MIN_SCORE:

            return None

        # ----------------------------------------------------
        # GİRİŞ
        # ----------------------------------------------------

        entry = price

        # ----------------------------------------------------
        # TP
        # ----------------------------------------------------

        tp1 = (
            entry
            * (
                1
                + TP1_PCT / 100
            )
        )

        tp2 = (
            entry
            * (
                1
                + TP2_PCT / 100
            )
        )

        tp3 = (
            entry
            * (
                1
                + TP3_PCT / 100
            )
        )

        # ----------------------------------------------------
        # STOP
        # ----------------------------------------------------

        stop = (
            entry
            * (
                1
                - STOP_PCT / 100
            )
        )

        # ----------------------------------------------------
        # SIGNAL TYPE
        # ----------------------------------------------------

        if score >= STRONG_SCORE:

            signal_type = "🔥 GÜÇLÜ"

        else:

            signal_type = "🟡 ERKEN ADAY"

        return {

            "symbol": symbol,

            "score": score,

            "signal_type": signal_type,

            "entry": entry,

            "tp1": tp1,

            "tp2": tp2,

            "tp3": tp3,

            "stop": stop,

            "change": change,

            "volume": volume,

            "recovery": four["recovery"],

            "rsi4h": four["rsi"],

            "rsi1h": one["rsi"],

            "rsi15m": fifteen["rsi"],

            "score4h": four["score"],

            "score1h": one["score"],

            "score15m": fifteen["score"],

            "volume_ratio": fifteen[
                "volume_ratio"
            ],

            "funding": ticker.get(
                "funding",
                0
            )
        }

    except Exception as e:

        print(
            symbol,
            "analiz hatası:",
            e
        )

        return None


# ============================================================
# FİYAT FORMAT
# ============================================================

def price_format(price):

    if price >= 100:

        return f"{price:.2f}"

    if price >= 1:

        return f"{price:.4f}"

    if price >= 0.01:

        return f"{price:.6f}"

    if price >= 0.0001:

        return f"{price:.8f}"

    return f"{price:.10f}"


# ============================================================
# TELEGRAM SIGNAL
# ============================================================

def format_signal(x):

    return (

        f"{x['signal_type']} "
        "<b>PUMP ADAYI</b>\n\n"

        f"🪙 <b>{x['symbol']}</b>\n"
        f"⭐ <b>Skor: {x['score']}/100</b>\n\n"

        f"🟢 <b>Giriş:</b> "
        f"{price_format(x['entry'])}\n"

        f"🎯 <b>TP1:</b> "
        f"{price_format(x['tp1'])}\n"

        f"🎯 <b>TP2:</b> "
        f"{price_format(x['tp2'])}\n"

        f"🎯 <b>TP3:</b> "
        f"{price_format(x['tp3'])}\n"

        f"🛑 <b>Stop:</b> "
        f"{price_format(x['stop'])}\n\n"

        f"📊 24H: "
        f"{x['change']:+.2f}%\n"

        f"📉 4H dipten dönüş: "
        f"+{x['recovery']:.2f}%\n"

        f"⚡ 15M hacim: "
        f"{x['volume_ratio']:.2f}x\n\n"

        f"🔎 4H RSI: "
        f"{x['rsi4h']:.1f}\n"

        f"🔎 1H RSI: "
        f"{x['rsi1h']:.1f}\n"

        f"🔎 15M RSI: "
        f"{x['rsi15m']:.1f}\n\n"

        f"📌 4H: {x['score4h']}/100\n"
        f"📈 1H: {x['score1h']}/100\n"
        f"⚡ 15M: {x['score15m']}/100\n\n"

        "📡 <b>MEXC FUTURES</b>\n"
        "⚠️ <i>Analiz sinyalidir, "
        "otomatik işlem açmaz.</i>"
    )


# ============================================================
# ANA TARAMA
# ============================================================

def scan():

    print("")
    print("=" * 70)
    print("🚀 MEXC FUTURES PUMP RADAR BAŞLADI")
    print("=" * 70)

    # --------------------------------------------------------
    # FUTURES CONTRACTS
    # --------------------------------------------------------

    symbols = get_futures_symbols()

    if not symbols:

        print(
            "❌ Futures sembolleri alınamadı."
        )

        send_telegram(
            "🔴 <b>PUMP RADAR HATASI</b>\n\n"
            "MEXC Futures listesi alınamadı."
        )

        return

    # --------------------------------------------------------
    # TICKER
    # --------------------------------------------------------

    tickers = get_futures_tickers()

    if not tickers:

        print(
            "❌ Futures ticker alınamadı."
        )

        send_telegram(
            "🔴 <b>PUMP RADAR HATASI</b>\n\n"
            "MEXC Futures ticker alınamadı."
        )

        return

    # --------------------------------------------------------
    # 24H ÖN FİLTRE
    # --------------------------------------------------------

    filtered = []

    for symbol in symbols:

        ticker = tickers.get(
            symbol
        )

        if not ticker:

            continue

        volume = ticker.get(
            "amount",
            0
        )

        change = ticker.get(
            "change",
            0
        )

        price = ticker.get(
            "price",
            0
        )

        if price <= 0:

            continue

        if volume < MIN_24H_VOLUME:

            continue

        if change < MIN_24H_CHANGE:

            continue

        if change > MAX_24H_CHANGE:

            continue

        filtered.append(
            (
                symbol,
                ticker
            )
        )

    # --------------------------------------------------------
    # HACME GÖRE SIRALA
    # --------------------------------------------------------

    filtered.sort(
        key=lambda x: x[1].get(
            "amount",
            0
        ),
        reverse=True
    )

    # Sadece ilk X coin
    filtered = filtered[
        :MAX_SYMBOLS_TO_SCAN
    ]

    print(
        "Futures 24H filtre sonrası:",
        len(filtered)
    )

    print(
        "Taranacak maksimum coin:",
        MAX_SYMBOLS_TO_SCAN
    )

    if not filtered:

        print(
            "❌ 24H filtreyi geçen Futures yok."
        )

        return

    # --------------------------------------------------------
    # PARALEL TARAMA
    # --------------------------------------------------------

    candidates = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {}

        for symbol, ticker in filtered:

            future = executor.submit(
                analyze_symbol,
                symbol,
                ticker
            )

            futures[future] = symbol

        completed = 0
        total = len(futures)

        for future in as_completed(
            futures
        ):

            symbol = futures[future]

            completed += 1

            try:

                result = future.result()

                if result:

                    candidates.append(
                        result
                    )

                    print(
                        "🔥 ADAY:",
                        symbol,
                        "| SKOR:",
                        result["score"],
                        "| 4H:",
                        result["score4h"],
                        "| 1H:",
                        result["score1h"],
                        "| 15M:",
                        result["score15m"]
                    )

            except Exception as e:

                print(
                    "Future hata:",
                    symbol,
                    e
                )

            if completed % 25 == 0:

                print(
                    "İlerleme:",
                    completed,
                    "/",
                    total
                )

    # --------------------------------------------------------
    # SKORA GÖRE SIRALA
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    print("")
    print(
        "🎯 TOPLAM ADAY:",
        len(candidates)
    )

    # --------------------------------------------------------
    # ADAY YOK
    # --------------------------------------------------------

    if not candidates:

        print(
            "Bu taramada sinyal yok."
        )

        return

    # --------------------------------------------------------
    # EN İYİ ADAYLARI GÖSTER
    # --------------------------------------------------------

    print("")
    print("EN İYİ ADAYLAR:")

    for candidate in candidates[:10]:

        print(
            candidate["symbol"],
            "|",
            candidate["score"],
            "| 4H",
            candidate["score4h"],
            "| 1H",
            candidate["score1h"],
            "| 15M",
            candidate["score15m"]
        )

    # --------------------------------------------------------
    # DUPLICATE TEMİZLE
    # --------------------------------------------------------

    sent = load_sent()

    now = time.time()

    clean = {}

    for symbol, timestamp in sent.items():

        try:

            if (
                now
                - float(timestamp)
                <
                DUPLICATE_HOURS * 3600
            ):

                clean[
                    symbol
                ] = timestamp

        except Exception:

            pass

    sent = clean

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    sent_count = 0

    for candidate in candidates:

        if (
            sent_count
            >= MAX_SIGNALS_PER_SCAN
        ):

            break

        symbol = candidate[
            "symbol"
        ]

        if symbol in sent:

            print(
                "⏭ DUPLICATE:",
                symbol
            )

            continue

        message = format_signal(
            candidate
        )

        success = send_telegram(
            message
        )

        if success:

            sent[symbol] = now

            save_sent(
                sent
            )

            sent_count += 1

            print(
                "✅ GÖNDERİLDİ:",
                symbol,
                candidate["score"]
            )

    print("")
    print(
        "📨 Telegram gönderilen:",
        sent_count
    )

    print("=" * 70)


# ============================================================
# PROGRAM
# ============================================================

if __name__ == "__main__":

    print("")
    print("🚀 PUMP RADAR FUTURES BAŞLIYOR")
    print("")

    # --------------------------------------------------------
    # TELEGRAM TEST
    # --------------------------------------------------------

    if not BOT_TOKEN:

        print(
            "❌ TELEGRAM_BOT_TOKEN YOK"
        )

    if not CHAT_ID:

        print(
            "❌ TELEGRAM_CHAT_ID YOK"
        )

    if BOT_TOKEN and CHAT_ID:

        telegram_test()

    else:

        print(
            "❌ Telegram secretları eksik."
        )

    # --------------------------------------------------------
    # TARAMA
    # --------------------------------------------------------

    try:

        scan()

    except Exception as e:

        print(
            "🔴 ANA HATA:",
            e
        )

        send_telegram(
            "🔴 <b>PUMP RADAR ANA HATA</b>\n\n"
            f"<code>{str(e)[:500]}</code>"
        )

    print("")
    print("🏁 Futures radar taraması tamamlandı.")
