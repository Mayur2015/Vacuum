import requests
import time
import json
import os
import traceback
from datetime import datetime
from SmartApi import SmartConnect
import pyotp

# ===== ENV VARIABLES =====
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

API_KEY = os.getenv("API_KEY")
CLIENT_ID = os.getenv("CLIENT_ID")
PASSWORD = os.getenv("PASSWORD")
TOTP_KEY = os.getenv("TOTP_KEY")

last_update_id = 0
morning_sent = False

# ===== GLOBAL DATA =====
last_time = ""
last_mode = ""
last_nifty = 0
last_expiry = ""
last_pcr = 0
last_atm_pcr = 0
last_atm = 0
last_max_pain = 0


# ===== TELEGRAM SEND =====
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.get(url, params={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print("Telegram Error:", e)


# ===== TELEGRAM MENU =====
def send_menu():
    keyboard = {
        "keyboard": [
            ["📊 Get Data"],
            ["🧹 Clear Memory"],
            ["📜 History"]
        ],
        "resize_keyboard": True
    }

    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": "Choose option:",
            "reply_markup": keyboard
        }
    )


# ===== COMMAND HANDLER =====
def check_commands():
    global last_update_id

    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
        params = {"offset": last_update_id + 1}

        res = requests.get(url, params=params).json()

        for upd in res.get("result", []):
            last_update_id = upd["update_id"]

            if "message" in upd:
                text = upd["message"].get("text", "").lower()

                if text == "/start":
                    send_menu()
                elif "data" in text:
                    send_latest()
                elif "clear" in text:
                    clear_memory()
                elif "history" in text:
                    send_history()
    except Exception as e:
        print("Command Error:", e)


# ===== SEND LATEST =====
def send_latest():
    msg = f"""📊 MARKET SNAPSHOT

Time: {last_time}
Mode: {last_mode}

NIFTY: {last_nifty}
Expiry: {last_expiry}

PCR: {round(last_pcr,2)}
ATM PCR: {round(last_atm_pcr,2)}

ATM: {last_atm}
Max Pain: {last_max_pain}
"""
    send_telegram(msg)


# ===== CLEAR MEMORY =====
def clear_memory():
    try:
        with open("pcr_history.json", "w") as f:
            json.dump([], f)
        send_telegram("✅ Memory Cleared")
    except Exception as e:
        print("Clear Error:", e)


# ===== HISTORY =====
def send_history():
    try:
        with open("pcr_history.json", "r") as f:
            data = json.load(f)

        last_5 = data[-5:]
        msg = "📜 MARKET HISTORY\n\n"

        for i, d in enumerate(last_5, 1):
            msg += f"""{i}) {d['time']}
NIFTY: {round(d['nifty'],2)}
PCR: {round(d['pcr'],2)}
ATM PCR: {round(d['atm_pcr'],2)}
Max Pain: {d['max_pain']}

"""

        send_telegram(msg)

    except:
        send_telegram("No history")


# ===== SAVE HISTORY =====
def save_history(entry):
    try:
        with open("pcr_history.json", "r") as f:
            data = json.load(f)
    except:
        data = []

    data.append(entry)

    if len(data) > 500:
        data = data[-500:]

    with open("pcr_history.json", "w") as f:
        json.dump(data, f, indent=4)


# ===== LOGIN =====
def login():
    smartApi = SmartConnect(API_KEY)
    totp = pyotp.TOTP(TOTP_KEY).now()

    session = smartApi.generateSession(CLIENT_ID, PASSWORD, totp)

    if not session['status']:
        raise Exception("Login Failed")

    print("Login Success")
    return smartApi


# ===== LOAD SYMBOL MASTER =====
def load_symbols():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    return requests.get(url, headers={"Cache-Control": "no-cache"}).json()


# ===== MAIN BOT FUNCTION =====
def run_bot(smartApi, symbols):
    global last_time, last_mode, last_nifty, last_expiry
    global last_pcr, last_atm_pcr, last_atm, last_max_pain
    global morning_sent

    now = datetime.now()
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # MODE
    if now.weekday() >= 5:
        mode = "WEEKEND"
    elif now.hour < 9 or now.hour > 15:
        mode = "AFTER MARKET"
    else:
        mode = "LIVE MARKET"

    # MORNING MESSAGE
    if now.hour == 9 and now.minute == 10 and not morning_sent:
        send_telegram("Good Morning Mayur !!\nHave a Profitable Day.\nJai Hanuman 🙏")
        morning_sent = True

    if now.hour > 9:
        morning_sent = False

    # NIFTY
    ltp = smartApi.ltpData("NSE", "NIFTY", "26000")
    nifty = ltp['data']['ltp']

    # OPTIONS FILTER
    opts = [
        s for s in symbols
        if s['exch_seg']=="NFO"
        and "NIFTY" in s.get('symbol','')
        and ("CE" in s.get('symbol','') or "PE" in s.get('symbol',''))
    ]

    expiries = list(set([o['expiry'] for o in opts]))

    exp_list = []
    for e in expiries:
        try:
            d = datetime.strptime(e, "%d%b%Y")
            if d >= now:
                exp_list.append((e,d))
        except:
            pass

    exp_list = sorted(exp_list, key=lambda x: x[1])
    expiry = exp_list[0][0]

    filtered = [o for o in opts if o['expiry']==expiry]

    atm = round(nifty/50)*50

    strike_map = {o['token']: int(float(o['strike'])/100) for o in filtered}

    tokens = [o['token'] for o in filtered if atm-500 <= strike_map[o['token']] <= atm+500]

    fetched = []
    for i in range(0, len(tokens), 50):
        data = smartApi.getMarketData("FULL", {"NFO": tokens[i:i+50]})
        if data['status']:
            fetched += data['data']['fetched']

    total_ce = total_pe = 0
    atm_ce = atm_pe = 0
    strike_data = {}

    for item in fetched:
        sym = item['tradingSymbol']
        oi = item['opnInterest']
        tk = item['symbolToken']

        strike = strike_map.get(tk)
        if strike is None:
            continue

        if strike not in strike_data:
            strike_data[strike] = {"ce":0,"pe":0}

        if "CE" in sym:
            total_ce += oi
            strike_data[strike]["ce"] += oi
            if strike == atm:
                atm_ce = oi
        else:
            total_pe += oi
            strike_data[strike]["pe"] += oi
            if strike == atm:
                atm_pe = oi

    pcr = total_pe/total_ce if total_ce else 0
    atm_pcr = atm_pe/atm_ce if atm_ce else 0

    max_pain = min(strike_data, key=lambda x:
        sum((x-k)*v["ce"] if x>k else (k-x)*v["pe"] for k,v in strike_data.items())
    )

    save_history({
        "time": time_str,
        "nifty": nifty,
        "pcr": pcr,
        "atm_pcr": atm_pcr,
        "max_pain": max_pain
    })

    # STORE GLOBAL
    last_time = time_str
    last_mode = mode
    last_nifty = nifty
    last_expiry = expiry
    last_pcr = pcr
    last_atm_pcr = atm_pcr
    last_atm = atm
    last_max_pain = max_pain

    print("Time:", time_str, "| PCR:", round(pcr,2))
    print("Checking Telegram...")
    check_commands()


# ===== MAIN LOOP =====
if __name__ == "__main__":
    smartApi = login()
    symbols = load_symbols()

    while True:
        try:
            run_bot(smartApi, symbols)
            time.sleep(30)

        except Exception as e:
            print("MAIN ERROR:", e)
            traceback.print_exc()
            time.sleep(10)
