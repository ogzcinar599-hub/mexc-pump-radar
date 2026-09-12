import os
import time
import math
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 🚀 MEXC PRE-PUMP RADAR V8
#
# AMAÇ:
# LSK gibi pump başlamadan ÖNCE güçlü para/pozisyon akışı
# görülen coinleri bulmak.
#
# ANA ÖNCELİK:
# 💰 Para / Pozisyon Akışı
# 🔥 Alış Baskısı
# 📈 Hacim İvmesi
# 🎯 Dirence Yakınlık
# 🧊 Aşırı ısınmamış fiyat
#
# TELEGRAM:
# SADECE GÜÇLÜ ADAYLAR
# ============================================================

BASE = "https://api.mexc.com"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MAX_WORKERS = 6

# Teknik tarama
CANDLE_COUNT = 90
TECH_TOP = 140

# Telegram
MAX_ALERTS = 6
MIN_SCORE = 60

# API
REQUEST_INTERVAL = 0.11
DEALS_LIMIT = 100

session = requests.Session()

_last_request = 0


# ============================================================
# API
# ============================================================

def mexc_get(path, params=None, timeout=15):

    global _last_request

    wait = REQUEST_INTERVAL - (time.time() - _last_request)

    if wait > 0:
        time.sleep(wait)

    try:
        r = session.get(
            BASE + path,
            params=params or {},
            timeout=timeout
        )

        _last_request = time.time()

        if r.status_code != 200:
            return None

        data = r.json()

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

        r = session.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text
            },
            timeout=15
        )

        return r.status_code == 200

    except Exception as e:

        print("Telegram hata:", e)
        return False


# ============================================================
# SYMBOLS
# ============================================================

def get_symbols():

    data = mexc_get("/api/v1/contract/detail")

    if not data:
        return []

    rows = data.get("data", [])

    symbols = []

    for x in rows:

        symbol = x.get("symbol", "")

        if not symbol.endswith("_USDT"):
            continue

        # Sadece aktif futures
        if x.get("state") not in [0, 1, "0", "1", None]:
            continue

        symbols.append(symbol)

    return sorted(set(symbols))


# ============================================================
# KLINE
# ============================================================

def get_klines(symbol, interval):

    end = int(time.time())
    start = end - (CANDLE_COUNT * 4 * 3600)

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

    times = d.get("time", [])
    opens = d.get("open", [])
    closes = d.get("close", [])
    highs = d.get("high", [])
    lows = d.get("low", [])
    vols = d.get("vol", [])

    n = min(
        len(times),
        len(opens),
        len(closes),
        len(highs),
        len(lows),
        len(vols)
    )

    result = []

    for i in range(n):

        try:

            result.append({
                "time": float(times[i]),
                "open": float(opens[i]),
                "close": float(closes[i]),
                "high": float(highs[i]),
                "low": float(lows[i]),
                "vol": float(vols[i])
            })

        except Exception:
            pass

    return result


# ============================================================
# BASIC INDICATORS
# ============================================================

def rsi(values, period=14):

    if len(values) < period + 1:
        return 50

    gains = []
    losses = []

    for i in range(1, len(values)):

        diff = values[i] - values[i - 1]

        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def sma(values, period):

    if len(values) < period:
        return sum(values) / max(1, len(values))

    return sum(values[-period:]) / period


def pct_change(a, b):

    if b == 0:
        return 0

    return ((a - b) / b) * 100


def volume_ratio(candles, recent=5, base=20):

    if len(candles) < base + recent:
        return 1

    recent_vol = sum(
        x["vol"] for x in candles[-recent:]
    ) / recent

    old = candles[-(base + recent):-recent]

    base_vol = sum(
        x["vol"] for x in old
    ) / max(1, len(old))

    if base_vol <= 0:
        return 1

    return recent_vol / base_vol


# ============================================================
# TECHNICAL ANALYSIS
# ============================================================

def analyze_technical(symbol):

    try:

        c4 = get_klines(symbol, "Hour4")
        c1 = get_klines(symbol, "Min60")
        c15 = get_klines(symbol, "Min15")

        if len(c4) < 50 or len(c1) < 50 or len(c15) < 50:
            return None

        p4 = [x["close"] for x in c4]
        p1 = [x["close"] for x in c1]
        p15 = [x["close"] for x in c15]

        last = p15[-1]

        rsi4 = rsi(p4)
        rsi1 = rsi(p1)
        rsi15 = rsi(p15)

        v4 = volume_ratio(c4)
        v1 = volume_ratio(c1)
        v15 = volume_ratio(c15)

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

        move_5 = pct_change(
            p15[-1],
            p15[-6]
        )

        # ====================================================
        # DİRENÇ
        # ====================================================

        resistance_price = max(
            x["high"] for x in c1[-25:]
        )

        resistance_pct = (
            (resistance_price - last)
            / last
            * 100
        )

        # ====================================================
        # HIGHER LOW
        # ====================================================

        low_recent = min(
            x["low"] for x in c1[-8:]
        )

        low_previous = min(
            x["low"] for x in c1[-16:-8]
        )

        higher_low = low_recent > low_previous

        # ====================================================
        # COMPRESSION
        # ====================================================

        recent_high = max(
            x["high"] for x in c4[-10:]
        )

        recent_low = min(
            x["low"] for x in c4[-10:]
        )

        range_pct = (
            (recent_high - recent_low)
            / recent_low
            * 100
        )

        compression = range_pct < 18

        # ====================================================
        # HARD REJECT
        # ====================================================

        # Zaten aşırı ısınmış
        if rsi4 > 72:
            return None

        if rsi1 > 72:
            return None

        if rsi15 > 76:
            return None

        # Son mumlarda patlamış
        if move_5 > 10:
            return None

        # 15M'de devasa hacim = çoğu zaman hareket başlamış
        if v15 > 7:
            return None

        # Aşırı uzak direnç
        if resistance_pct > 10:
            return None

        # ====================================================
        # SCORE
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

        # Hacim
        if 0.9 <= v1 <= 2.5:
            score += 7
        elif v1 >= 0.7:
            score += 4

        if 0.8 <= v15 <= 3:
            score += 7
        elif v15 >= 0.7:
            score += 4

        # Momentum
        if 0 < mom1 <= 4:
            score += 5

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
            "symbol": symbol,
            "technical_score": score,
            "rsi4": rsi4,
            "rsi1": rsi1,
            "rsi15": rsi15,
            "v1": v1,
            "v15": v15,
            "mom1": mom1,
            "mom15": mom15,
            "move5": move_5,
            "resistance": resistance_pct,
            "higher_low": higher_low,
            "compression": compression
        }

    except Exception:
        return None


# ============================================================
# TICKER
# ============================================================

def get_ticker(symbol):

    data = mexc_get(
        "/api/v1/contract/ticker",
        {"symbol": symbol}
    )

    if not data:
        return None

    return data.get("data")


# ============================================================
# DEAL FLOW
#
# T = işlem yönü
# O = pozisyon açma/kapama bilgisi
#
# O=1 açılış işlemlerini öncelikli kullanıyoruz.
# ============================================================

def get_deal_flow(symbol):

    data = mexc_get(
        f"/api/v1/contract/deals/{symbol}",
        {
            "limit": DEALS_LIMIT
        }
    )

    if not data:
        return None

    rows = data.get("data", [])

    if not isinstance(rows, list) or not rows:
        return None

    buy_open = 0.0
    sell_open = 0.0

    buy_all = 0.0
    sell_all = 0.0

    open_count = 0

    for x in rows:

        try:

            price = float(x.get("p", 0))
            volume = float(x.get("v", 0))

            T = int(x.get("T", 0))
            O = int(x.get("O", 0))

            notional = abs(price * volume)

            if notional <= 0:
                continue

            # ------------------------------------------------
            # T=1 BUY
            # T=2 SELL
            # ------------------------------------------------

            if T == 1:
                buy_all += notional

            elif T == 2:
                sell_all += notional

            # ------------------------------------------------
            # O=1 = OPEN
            # ------------------------------------------------

            if O == 1:

                open_count += 1

                if T == 1:
                    buy_open += notional

                elif T == 2:
                    sell_open += notional

        except Exception:
            continue

    # ========================================================
    # Öncelik OPEN FLOW
    # ========================================================

    open_total = buy_open + sell_open

    if open_total > 0:

        net = buy_open - sell_open

        net_pct = (
            net / open_total * 100
        )

        buy_share = (
            buy_open / open_total * 100
        )

        flow_type = "OPEN"

    else:

        # Açılış verisi yoksa son işlemlerin yönünü
        # yedek akış olarak kullan.
        total = buy_all + sell_all

        if total <= 0:
            return None

        net = buy_all - sell_all

        net_pct = (
            net / total * 100
        )

        buy_share = (
            buy_all / total * 100
        )

        flow_type = "TRADE"

    return {
        "buy_open": buy_open,
        "sell_open": sell_open,
        "open_total": open_total,
        "buy_all": buy_all,
        "sell_all": sell_all,
        "net": net,
        "net_pct": net_pct,
        "buy_share": buy_share,
        "open_count": open_count,
        "flow_type": flow_type
    }


# ============================================================
# PARA GİRİŞİ SKORU
# ============================================================

def money_score(flow):

    if not flow:
        return 0

    net = flow["net_pct"]
    buy_share = flow["buy_share"]

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
    # AŞIRI POZİTİF AKIŞ CEZASI
    #
    # Aşırı pozitif = bazen zaten hareket başlamış olabilir.
    # ========================================================

    if net > 60:
        score -= 5

    return max(0, min(score, 50))


# ============================================================
# FİNAL ANALİZ
# ============================================================

def final_analyze(tech):

    symbol = tech["symbol"]

    flow = get_deal_flow(symbol)

    if not flow:
        return None

    mscore = money_score(flow)

    # Para akışı yoksa gönderme
    if mscore < 10:
        return None

    # ========================================================
    # TEKNİK
    # ========================================================

    tech_score = tech["technical_score"]

    # ========================================================
    # HACİM BONUS
    # ========================================================

    volume_bonus = 0

    if tech["v1"] >= 1.5:
        volume_bonus += 5

    if tech["v15"] >= 1.2:
        volume_bonus += 5

    # ========================================================
    # TOPLAM
    #
    # PARA GİRİŞİ EN ÖNEMLİ
    # ========================================================

    total = (
        mscore * 0.55
        + tech_score * 0.35
        + volume_bonus
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
    # PARA GİRİŞİ GÜÇLÜ DEĞİLSE SONUÇ YOK
    # ========================================================

    if mscore < 20:
        return None

    if total < MIN_SCORE:
        return None

    result = dict(tech)

    result["money_score"] = mscore
    result["total_score"] = round(total, 1)
    result["flow"] = flow

    return result


# ============================================================
# TELEGRAM FORMAT
# ============================================================

def fire_level(net):

    if net >= 25:
        return "🔥🔥🔥"

    if net >= 15:
        return "🔥🔥"

    if net >= 7:
        return "🔥"

    return "⚡"


def format_telegram(x):

    symbol = x["symbol"]

    score = x["total_score"]

    flow = x["flow"]

    net = flow["net_pct"]

    buy_share = flow["buy_share"]

    fire = fire_level(net)

    volume = max(
        x["v1"],
        x["v15"]
    )

    resistance = x["resistance"]

    return (
        "🚨 PRE-PUMP\n\n"
        f"🪙 {symbol}\n"
        f"⭐ {score:.0f}/100\n\n"
        f"💰 Para Girişi: {fire} "
        f"{net:+.1f}%\n"
        f"🟢 Alış Baskısı: {buy_share:.0f}%\n"
        f"📈 Hacim: {volume:.1f}x\n"
        f"🎯 Direnç: %{resistance:.1f}\n\n"
        "TP1 +3% | TP2 +6% | TP3 +10%"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    started = time.time()

    print("=" * 60)
    print("🚀 MEXC PRE-PUMP RADAR V8")
    print("=" * 60)

    print("💰 ANA FİLTRE: PARA GİRİŞİ")
    print("🔥 YENİ POZİSYON + ALIŞ BASKISI")
    print("🎯 ERKEN PUMP ADAYLARI")

    # ========================================================
    # API TEST
    # ========================================================

    print("\n🧪 API TEST...")

    test_symbol = "BTC_USDT"

    test_kline = get_klines(
        test_symbol,
        "Min15"
    )

    if test_kline:
        print("✅ Kline OK")
    else:
        print("❌ Kline HATA")

    ticker = get_ticker(test_symbol)

    if ticker:
        print("✅ Ticker OK")
    else:
        print("❌ Ticker HATA")

    test_flow = get_deal_flow(test_symbol)

    if test_flow:

        print(
            f"✅ İşlem akışı OK | "
            f"Net: {test_flow['net_pct']:.2f}% | "
            f"Buy: {test_flow['buy_share']:.1f}%"
        )

    else:
        print("⚠️ İşlem akışı okunamadı")

    # ========================================================
    # SYMBOLS
    # ========================================================

    print("\n🔎 MEXC Futures coinleri alınıyor...")

    symbols = get_symbols()

    print(
        f"✅ Futures: {len(symbols)}"
    )

    if not symbols:
        print("❌ Coin bulunamadı")
        return

    # ========================================================
    # TECHNICAL SCAN
    # ========================================================

    print(
        f"\n🟣 TEKNİK ÖN FİLTRE..."
    )

    technical_candidates = []

    total_symbols = len(symbols)

    def worker(symbol):

        return analyze_technical(symbol)

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(worker, s): s
            for s in symbols
        }

        done = 0

        for future in as_completed(futures):

            done += 1

            result = future.result()

            if result:
                technical_candidates.append(result)

            if done % 100 == 0:

                print(
                    f"İlerleme {done}/{total_symbols} | "
                    f"Teknik aday "
                    f"{len(technical_candidates)}"
                )

    # ========================================================
    # TECH TOP
    # ========================================================

    technical_candidates.sort(
        key=lambda x: x["technical_score"],
        reverse=True
    )

    technical_candidates = technical_candidates[:TECH_TOP]

    print(
        f"\n✅ Teknik aday: "
        f"{len(technical_candidates)}"
    )

    # ========================================================
    # MONEY FLOW
    # ========================================================

    print(
        "\n💰 PARA GİRİŞİ TARAMASI..."
    )

    final_candidates = []

    for i, tech in enumerate(
        technical_candidates,
        1
    ):

        result = final_analyze(tech)

        if result:
            final_candidates.append(result)

        if i % 20 == 0:

            print(
                f"Para akışı "
                f"{i}/{len(technical_candidates)} | "
                f"Güçlü "
                f"{len(final_candidates)}"
            )

    # ========================================================
    # SORT
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
        f"\n💰 Güçlü para girişi: "
        f"{len(final_candidates)}"
    )

    # ========================================================
    # TELEGRAM
    # ========================================================

    sent = 0

    for x in final_candidates[:MAX_ALERTS]:

        message = format_telegram(x)

        print("\n" + "-" * 50)
        print(message)
        print("-" * 50)

        if send_telegram(message):
            sent += 1

    # ========================================================
    # SUMMARY
    # ========================================================

    elapsed = time.time() - started

    print("\n" + "=" * 60)
    print("✅ V8 RADAR TAMAMLANDI")
    print(
        f"⏱️ Süre: {elapsed:.1f} sn"
    )
    print(
        f"🌐 Futures: {len(symbols)}"
    )
    print(
        f"🔎 Teknik: {len(technical_candidates)}"
    )
    print(
        f"💰 Para girişi: {len(final_candidates)}"
    )
    print(
        f"📨 Telegram: {sent}"
    )
    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    print(
        "### MEXC PRE-PUMP RADAR V8 BAŞLADI ###"
    )

    main()
