import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC LSK PRE-PUMP RADAR V3
#
# AMAÇ:
# LSK gibi büyük hareketleri mümkün olduğunca erken yakalamak
#
# SADECE:
# ✅ MEXC USDT FUTURES
# ✅ 15M
# ✅ 1H
# ✅ 4H
#
# KULLANILANLAR:
# ✅ 4H SIKIŞMA
# ✅ HACİM GİRİŞİ
# ✅ DİRENÇ
# ✅ HIGHER LOW
# ✅ MOMENTUM
# ✅ RSI TEYİDİ
#
# ÖNEMLİ:
# ❌ Otomatik işlem açmaz
# ❌ Futures emir göndermez
# ❌ Spot taramaz
# ❌ Stock taramaz
# ============================================================


# ============================================================
# AYARLAR
# ============================================================

BASE = "https://api.mexc.com"

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MAX_WORKERS = 8

MIN_SCORE = 72

MAX_ALERTS = 6

COOLDOWN_MINUTES = 45


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
})


# ============================================================
# İSTATİSTİK
# ============================================================

stats = {
    "total": 0,
    "data_ok": 0,
    "filtered": 0,
    "errors": 0,
    "candidates": 0
}


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):

    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN bulunamadı")
        return False

    if not CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID bulunamadı")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:

        response = session.post(
            url,
            json=payload,
            timeout=15
        )

        if response.status_code != 200:

            print(
                "❌ Telegram hata:",
                response.status_code,
                response.text[:300]
            )

            return False

        return True

    except Exception as e:

        print(
            "❌ Telegram bağlantı hatası:",
            repr(e)
        )

        return False


# ============================================================
# MEXC GET
# ============================================================

def mexc_get(path, params=None):

    url = BASE + path

    try:

        response = session.get(
            url,
            params=params,
            timeout=12
        )

        if response.status_code != 200:

            print(
                "API HTTP:",
                response.status_code,
                path
            )

            return None

        data = response.json()

        return data

    except Exception as e:

        print(
            "API ERROR:",
            path,
            repr(e)
        )

        return None


# ============================================================
# FUTURES SEMBOLLERİ
# ============================================================

def get_symbols():

    print("")
    print("=========================================")
    print("📡 MEXC FUTURES SEMBOLLERİ ALINIYOR")
    print("=========================================")

    data = mexc_get(
        "/api/v1/contract/detail"
    )

    if not data:

        print("❌ Futures listesi alınamadı")

        return []

    rows = data.get("data", [])

    if not isinstance(rows, list):

        print(
            "❌ Beklenmeyen Futures response"
        )

        return []

    symbols = []

    for item in rows:

        symbol = item.get(
            "symbol",
            ""
        )

        if not symbol:
            continue

        # Sadece USDT futures
        if not symbol.endswith("_USDT"):
            continue

        # State kontrolü
        state = item.get("state")

        try:

            if state is not None:

                if int(state) != 0:
                    continue

        except Exception:
            pass

        symbols.append(symbol)

    symbols = sorted(
        list(set(symbols))
    )

    print(
        f"✅ Futures sembol sayısı: {len(symbols)}"
    )

    return symbols


# ============================================================
# KLINE
# ============================================================

def get_klines(
    symbol,
    interval,
    limit=100
):

    data = mexc_get(
        f"/api/v1/contract/kline/{symbol}",
        {
            "interval": interval,
            "limit": limit
        }
    )

    if not data:

        return []

    rows = data.get("data")

    if not rows:

        return []

    result = []

    # --------------------------------------------------------
    # MEXC DICT FORMAT
    # --------------------------------------------------------

    if isinstance(rows, dict):

        times = rows.get(
            "time",
            []
        )

        opens = rows.get(
            "open",
            []
        )

        highs = rows.get(
            "high",
            []
        )

        lows = rows.get(
            "low",
            []
        )

        closes = rows.get(
            "close",
            []
        )

        volumes = rows.get(
            "vol",
            []
        )

        n = min(
            len(times),
            len(opens),
            len(highs),
            len(lows),
            len(closes),
            len(volumes)
        )

        for i in range(n):

            try:

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
                        volumes[i]
                    )
                })

            except Exception:
                continue

    # --------------------------------------------------------
    # LIST FORMAT
    # --------------------------------------------------------

    elif isinstance(rows, list):

        for row in rows:

            try:

                if len(row) < 6:
                    continue

                result.append({

                    "time": float(
                        row[0]
                    ),

                    "open": float(
                        row[1]
                    ),

                    "high": float(
                        row[2]
                    ),

                    "low": float(
                        row[3]
                    ),

                    "close": float(
                        row[4]
                    ),

                    "volume": float(
                        row[5]
                    )
                })

            except Exception:
                continue

    # MEXC verisi zaman sıralı olsun
    result.sort(
        key=lambda x: x["time"]
    )

    return result


# ============================================================
# RSI
# ============================================================

def calculate_rsi(
    values,
    period=14
):

    if len(values) < period + 2:

        return None

    gains = []
    losses = []

    for i in range(
        1,
        len(values)
    ):

        diff = (
            values[i]
            - values[i - 1]
        )

        if diff >= 0:

            gains.append(diff)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(diff)
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

        return 100.0

    rs = (
        avg_gain
        / avg_loss
    )

    return (
        100
        - (
            100
            / (1 + rs)
        )
    )


# ============================================================
# SMA
# ============================================================

def sma(
    values,
    period
):

    if len(values) < period:

        return None

    return (
        sum(values[-period:])
        / period
    )


# ============================================================
# DEĞİŞİM %
# ============================================================

def percent_change(
    candles,
    bars
):

    if len(candles) <= bars:

        return 0.0

    old = candles[
        -bars - 1
    ]["close"]

    new = candles[-1]["close"]

    if old <= 0:

        return 0.0

    return (
        (new - old)
        / old
    ) * 100


# ============================================================
# HACİM RASYOSU
# ============================================================

def volume_ratio(
    candles,
    lookback=20
):

    if len(candles) < (
        lookback + 1
    ):

        return 0.0

    current = candles[
        -1
    ]["volume"]

    previous = [
        x["volume"]
        for x in candles[
            -lookback - 1:
            -1
        ]
    ]

    if not previous:

        return 0.0

    average = (
        sum(previous)
        / len(previous)
    )

    if average <= 0:

        return 0.0

    return (
        current
        / average
    )


# ============================================================
# SIKIŞMA
# ============================================================

def get_compression(
    candles
):

    if len(candles) < 25:

        return False, 999.0

    recent = candles[
        -20:
    ]

    highest = max(
        x["high"]
        for x in recent
    )

    lowest = min(
        x["low"]
        for x in recent
    )

    if lowest <= 0:

        return False, 999.0

    width = (
        (
            highest
            - lowest
        )
        / lowest
    ) * 100

    if width <= 15:

        return True, width

    if width <= 22:

        return True, width

    return False, width


# ============================================================
# HIGHER LOW
# ============================================================

def has_higher_low(
    candles
):

    if len(candles) < 12:

        return False

    first = candles[
        -12:-6
    ]

    second = candles[
        -6:
    ]

    low1 = min(
        x["low"]
        for x in first
    )

    low2 = min(
        x["low"]
        for x in second
    )

    return low2 > low1


# ============================================================
# DİRENÇ
# ============================================================

def resistance_distance(
    candles
):

    if len(candles) < 25:

        return None, 999.0

    previous = candles[
        -21:-1
    ]

    resistance = max(
        x["high"]
        for x in previous
    )

    price = candles[
        -1
    ]["close"]

    if resistance <= 0:

        return None, 999.0

    distance = (
        (
            resistance
            - price
        )
        / resistance
    ) * 100

    return resistance, distance


# ============================================================
# ANALİZ
# ============================================================

def analyze(
    symbol
):

    try:

        c15 = get_klines(
            symbol,
            "Min15",
            100
        )

        c1h = get_klines(
            symbol,
            "Hour1",
            100
        )

        c4h = get_klines(
            symbol,
            "Hour4",
            100
        )

        if (
            len(c15) < 50
            or len(c1h) < 50
            or len(c4h) < 50
        ):

            return None

        stats["data_ok"] += 1

        close15 = [
            x["close"]
            for x in c15
        ]

        close1h = [
            x["close"]
            for x in c1h
        ]

        close4h = [
            x["close"]
            for x in c4h
        ]

        price = close15[-1]

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

        if None in (
            rsi15,
            rsi1h,
            rsi4h
        ):

            return None

        # ----------------------------------------------------
        # HACİM
        # ----------------------------------------------------

        vol15 = volume_ratio(
            c15
        )

        vol1h = volume_ratio(
            c1h
        )

        vol4h = volume_ratio(
            c4h
        )

        # ----------------------------------------------------
        # FİYAT HAREKETİ
        # ----------------------------------------------------

        move15 = percent_change(
            c15,
            4
        )

        move1h = percent_change(
            c1h,
            4
        )

        move4h = percent_change(
            c4h,
            4
        )

        move24h = percent_change(
            c15,
            96
        )

        # ====================================================
        # GEÇ KALMA FİLTRESİ
        # ====================================================

        if move24h >= 30:

            stats["filtered"] += 1

            return None

        if move4h >= 20:

            stats["filtered"] += 1

            return None

        if move1h >= 15:

            stats["filtered"] += 1

            return None

        if move15 >= 12:

            stats["filtered"] += 1

            return None

        if rsi15 >= 76:

            stats["filtered"] += 1

            return None

        # ====================================================
        # SIKIŞMA
        # ====================================================

        compressed, width = (
            get_compression(c4h)
        )

        # ====================================================
        # DİRENÇ
        # ====================================================

        resistance, distance = (
            resistance_distance(c15)
        )

        # ====================================================
        # HIGHER LOW
        # ====================================================

        hl4 = has_higher_low(
            c4h
        )

        hl1 = has_higher_low(
            c1h
        )

        # ====================================================
        # MA
        # ====================================================

        ma5 = sma(
            close4h,
            5
        )

        ma10 = sma(
            close4h,
            10
        )

        ma30 = sma(
            close4h,
            30
        )

        if None in (
            ma5,
            ma10,
            ma30
        ):

            return None

        # ====================================================
        # SCORE
        # ====================================================

        score = 0

        reasons = []

        # ----------------------------------------------------
        # 4H SIKIŞMA = 20
        # ----------------------------------------------------

        if compressed:

            if width <= 15:

                score += 20

                reasons.append(
                    "4H güçlü sıkışma"
                )

            else:

                score += 14

                reasons.append(
                    "4H sıkışma"
                )

        # ----------------------------------------------------
        # HACİM = 20
        # ----------------------------------------------------

        if vol15 >= 2.0:

            score += 10

            reasons.append(
                f"15M hacim {vol15:.1f}x"
            )

        elif vol15 >= 1.5:

            score += 5

            reasons.append(
                f"15M hacim {vol15:.1f}x"
            )

        if vol1h >= 1.8:

            score += 10

            reasons.append(
                f"1H hacim {vol1h:.1f}x"
            )

        elif vol1h >= 1.4:

            score += 5

            reasons.append(
                f"1H hacim {vol1h:.1f}x"
            )

        # ----------------------------------------------------
        # DİRENÇ = 20
        # ----------------------------------------------------

        if 0 <= distance <= 2:

            score += 20

            reasons.append(
                "Direnç çok yakın"
            )

        elif 2 < distance <= 5:

            score += 15

            reasons.append(
                "Direnç yakın"
            )

        elif 5 < distance <= 10:

            score += 8

            reasons.append(
                "Dirence yaklaşıyor"
            )

        # ----------------------------------------------------
        # HIGHER LOW = 15
        # ----------------------------------------------------

        if hl4:

            score += 8

            reasons.append(
                "4H higher-low"
            )

        if hl1:

            score += 7

            reasons.append(
                "1H higher-low"
            )

        # ----------------------------------------------------
        # MOMENTUM = 15
        # ----------------------------------------------------

        old15 = percent_change(
            c15[:-4],
            4
        )

        old1h = percent_change(
            c1h[:-4],
            4
        )

        if move15 > old15:

            score += 8

            reasons.append(
                "15M momentum artıyor"
            )

        if move1h > old1h:

            score += 7

            reasons.append(
                "1H momentum artıyor"
            )

        # ----------------------------------------------------
        # RSI = SADECE 10
        # ----------------------------------------------------

        if (
            52 <= rsi15 <= 68
            and
            50 <= rsi1h <= 68
            and
            rsi4h >= 45
        ):

            score += 10

            reasons.append(
                "RSI üçlü uyum"
            )

        elif (
            50 <= rsi15 <= 70
            and
            48 <= rsi1h <= 70
        ):

            score += 5

        # ====================================================
        # KRİTİK KONTROLLER
        # ====================================================

        # Sıkışma yoksa güçlü sinyal olmasın
        if not compressed:

            score = min(
                score,
                69
            )

        # Hacim kesinlikle gerekli
        if (
            vol15 < 1.3
            and
            vol1h < 1.3
        ):

            return None

        # Çok düşük RSI
        if rsi15 < 42:

            return None

        # MA yapısı tamamen kötü ise
        if (
            price < ma30
            and
            ma5 < ma10
        ):

            return None

        # ====================================================
        # SCORE
        # ====================================================

        if score < MIN_SCORE:

            return None

        # ====================================================
        # STAGE
        # ====================================================

        if score >= 90:

            stage = (
                "🔥 ÇOK GÜÇLÜ ERKEN"
            )

        elif score >= 82:

            stage = (
                "🚀 GÜÇLÜ ERKEN"
            )

        else:

            stage = (
                "⚡ ERKEN ADAY"
            )

        # ====================================================
        # GİRİŞ
        # ====================================================

        entry_low = price * 0.997

        entry_high = price * 1.008

        # ====================================================
        # TP
        # ====================================================

        tp1 = price * 1.05

        tp2 = price * 1.10

        tp3 = price * 1.18

        # ====================================================
        # STOP
        # ====================================================

        stop = price * 0.975

        return {

            "symbol": symbol,

            "score": score,

            "stage": stage,

            "price": price,

            "rsi15": rsi15,
            "rsi1h": rsi1h,
            "rsi4h": rsi4h,

            "vol15": vol15,
            "vol1h": vol1h,
            "vol4h": vol4h,

            "move15": move15,
            "move1h": move1h,
            "move4h": move4h,
            "move24h": move24h,

            "width": width,

            "resistance": resistance,
            "distance": distance,

            "entry_low": entry_low,
            "entry_high": entry_high,

            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,

            "stop": stop,

            "reasons": reasons
        }

    except Exception as e:

        stats["errors"] += 1

        return None


# ============================================================
# ALERT
# ============================================================

def send_alert(
    x
):

    reason_text = "\n".join(
        f"• {r}"
        for r in x["reasons"][:7]
    )

    message = f"""
<b>🚀 LSK-TİPİ ERKEN PUMP</b>

<b>{x["symbol"]}</b>

{x["stage"]}

⭐ GÜÇ: <b>{x["score"]}/100</b>

💰 FİYAT
<b>{x["price"]:.8g}</b>

📊 RSI
15M: {x["rsi15"]:.1f}
1H: {x["rsi1h"]:.1f}
4H: {x["rsi4h"]:.1f}

📈 HACİM
15M: <b>{x["vol15"]:.1f}x</b>
1H: <b>{x["vol1h"]:.1f}x</b>

📉 HAREKET
15M: {x["move15"]:+.1f}%
1H: {x["move1h"]:+.1f}%
4H: {x["move4h"]:+.1f}%
24H: {x["move24h"]:+.1f}%

📦 4H SIKIŞMA
{x["width"]:.1f}%

🎯 DİRENÇ
{x["distance"]:.1f}% uzaklıkta

🎯 GİRİŞ
{x["entry_low"]:.8g}
→
{x["entry_high"]:.8g}

🥇 TP1
{x["tp1"]:.8g}

🥈 TP2
{x["tp2"]:.8g}

🥉 TP3
{x["tp3"]:.8g}

🛑 STOP
{x["stop"]:.8g}

<b>🔎 YAPI</b>
{reason_text}

⚠️ Otomatik teknik taramadır.
Pump garantisi değildir.
"""

    telegram(
        message
    )


# ============================================================
# TEK TARAMA
# ============================================================

def scan():

    print("")
    print("=========================================")
    print("🔍 MEXC PUMP RADAR BAŞLADI")
    print("=========================================")

    symbols = get_symbols()

    if not symbols:

        raise RuntimeError(
            "Futures sembolleri alınamadı."
        )

    stats["total"] = len(
        symbols
    )

    results = []

    print("")
    print(
        f"🔎 {len(symbols)} Futures coin taranıyor..."
    )

    start = time.time()

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        jobs = [
            executor.submit(
                analyze,
                symbol
            )
            for symbol in symbols
        ]

        for job in as_completed(
            jobs
        ):

            try:

                result = job.result()

                if result:

                    results.append(
                        result
                    )

            except Exception:

                stats["errors"] += 1

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    stats["candidates"] = len(
        results
    )

    elapsed = (
        time.time()
        - start
    )

    print("")
    print("=========================================")
    print("📊 TARAMA TAMAMLANDI")
    print("=========================================")

    print(
        f"Toplam Futures : {stats['total']}"
    )

    print(
        f"Verisi uygun   : {stats['data_ok']}"
    )

    print(
        f"Filtrelenen    : {stats['filtered']}"
    )

    print(
        f"Hata           : {stats['errors']}"
    )

    print(
        f"Aday           : {stats['candidates']}"
    )

    print(
        f"Süre           : {elapsed:.1f} saniye"
    )

    print(
        "========================================="
    )

    if not results:

        print(
            "⚪ Bu taramada güçlü LSK tipi aday yok."
        )

        telegram(
            "⚪ <b>PUMP RADAR</b>\n\n"
            "Bu taramada LSK tipi "
            "güçlü erken pump adayı bulunamadı."
        )

        return

    print("")
    print(
        "🔥 EN GÜÇLÜ ADAYLAR"
    )

    for i, x in enumerate(
        results[:MAX_ALERTS],
        1
    ):

        print(
            f"{i}. "
            f"{x['symbol']} "
            f"{x['score']}/100 "
            f"RSI15={x['rsi15']:.1f} "
            f"VOL15={x['vol15']:.1f}x"
        )

    print("")

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    for x in results[
        :MAX_ALERTS
    ]:

        send_alert(
            x
        )

    print(
        "📨 Telegram bildirimleri gönderildi."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print("=========================================")
    print("🚀 MEXC LSK PRE-PUMP RADAR V3")
    print("=========================================")
    print("")

    if not TOKEN:

        print(
            "❌ TELEGRAM_BOT_TOKEN YOK"
        )

    else:

        print(
            "✅ TELEGRAM_BOT_TOKEN bulundu"
        )

    if not CHAT_ID:

        print(
            "❌ TELEGRAM_CHAT_ID YOK"
        )

    else:

        print(
            "✅ TELEGRAM_CHAT_ID bulundu"
        )

    scan()

    print("")
    print(
        "✅ RADAR TAMAMLANDI"
    )
    print(
        "ℹ️ Program normal şekilde kapatılıyor."
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
