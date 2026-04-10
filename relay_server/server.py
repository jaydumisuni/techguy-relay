import json, os, secrets, string, threading, time, datetime, urllib.request
from flask import Flask, request, jsonify

app = Flask(__name__)

PAYMENT_HOURS = int(os.environ.get("PAYMENT_HOURS", "5"))
BETA_CUTOFF   = datetime.date(2026, 7, 30)

def is_beta_active(): return datetime.date.today() <= BETA_CUTOFF

_registry = {}
_lock     = threading.Lock()
CODE_TTL  = 60

def _load_users():
    try:
        with open("users.json") as f: return json.load(f)
    except: return {}

def _save_users(u):
    with open("users.json", "w") as f: json.dump(u, f, indent=2)

def _activate_user(user_id, hours, method):
    users = _load_users()
    if user_id not in users: users[user_id] = {}
    users[user_id]["active"] = True
    users[user_id]["plan"]   = "paid"
    users[user_id]["hours_remaining"] = users[user_id].get("hours_remaining", 0) + hours
    users[user_id]["last_payment_method"] = method
    _save_users(users)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if token:
        _tg_send(token, user_id, f"✅ Payment confirmed via {method}!\n+{hours} hours added.")
        admin_id = os.environ.get("ADMIN_CHAT_ID", "")
        if admin_id:
            _tg_send(token, admin_id, f"💰 Payment received\nMethod: {method}\nUser: {user_id}\nHours: +{hours}")

def _tg_send(token, chat_id, text):
    try:
        data = json.dumps({"chat_id": chat_id, "text": text}).encode()
        req  = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
               data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except: pass

def _cleanup_expired():
    now = time.time()
    with _lock:
        for k in [k for k, v in _registry.items() if now - v["ts"] > CODE_TTL]:
            del _registry[k]

def _cleanup_loop():
    while True:
        time.sleep(30)
        _cleanup_expired()

threading.Thread(target=_cleanup_loop, daemon=True).start()

def _gen_code():
    chars = string.ascii_uppercase + string.digits
    return "TG-" + "".join(secrets.choice(chars) for _ in range(6))

def get_stats():
    _cleanup_expired()
    with _lock:
        sessions = [{"code": c, "label": e.get("label","—")} for c, e in _registry.items()]
    users = _load_users()
    return {"active_codes": len(sessions), "sessions": sessions,
            "total_users": len(users), "active_users": sum(1 for u in users.values() if u.get("active")),
            "beta_active": is_beta_active(), "beta_cutoff": str(BETA_CUTOFF)}

@app.route("/register", methods=["POST"])
def register():
    data  = request.get_json(force=True, silent=True) or {}
    port  = data.get("port")
    if not port: return jsonify({"error": "port required"}), 400
    private = ("192.", "10.", "172.")
    host  = (data.get("public_ip") or "").strip()
    host  = host if host and not any(host.startswith(p) for p in private) else request.remote_addr
    with _lock:
        for _ in range(20):
            code = _gen_code()
            if code not in _registry: break
        _registry[code] = {"host": host, "port": int(port), "ts": time.time(), "label": (data.get("label") or "client").strip()}
    return jsonify({"code": code, "host": host, "port": int(port)})

@app.route("/resolve/<code>", methods=["GET"])
def resolve(code):
    _cleanup_expired()
    code = code.strip().upper()
    with _lock: entry = _registry.get(code)
    if not entry: return jsonify({"error": "not found"}), 404
    return jsonify({"host": entry["host"], "port": entry["port"]})

@app.route("/heartbeat", methods=["POST"])
def heartbeat():
    data = request.get_json(force=True, silent=True) or {}
    code = (data.get("code") or "").strip().upper()
    with _lock:
        if code in _registry:
            _registry[code]["ts"] = time.time()
            return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404

@app.route("/unregister", methods=["POST"])
def unregister():
    data = request.get_json(force=True, silent=True) or {}
    code = (data.get("code") or "").strip().upper()
    with _lock: _registry.pop(code, None)
    return jsonify({"ok": True})

@app.route("/health", methods=["GET"])
def health():
    with _lock: count = len(_registry)
    return jsonify({"status": "ok", "active_codes": count, "beta": is_beta_active()})

@app.route("/stats", methods=["GET"])
def stats():
    return jsonify(get_stats())

@app.route("/api/check-uid", methods=["GET"])
def check_uid():
    uid = request.args.get("uid", "").strip().upper()
    if not uid: return jsonify({"error": "uid required"}), 400
    users = _load_users()
    for user_id, user in users.items():
        if user.get("machine_uid") == uid:
            if is_beta_active():
                return jsonify({"active": True, "plan": user.get("plan","beta"), "beta": True, "registered": True})
            active = bool(user.get("active") and user.get("hours_remaining", 0) > 0)
            return jsonify({"active": active, "plan": user.get("plan","none"), "beta": False, "registered": True})
    return jsonify({"active": False, "plan": "none", "beta": is_beta_active(), "registered": False})

@app.route("/binance-webhook", methods=["POST"])
def binance_webhook():
    try:
        from payments import binance_verify_webhook, binance_parse_webhook
    except ImportError:
        return jsonify({"error": "payments module not found"}), 500
    raw = request.get_data(as_text=True)
    sig = request.headers.get("BinancePay-Signature", "")
    if not binance_verify_webhook(raw, sig): return jsonify({"error": "invalid signature"}), 401
    payment = binance_parse_webhook(request.get_json(force=True) or {})
    if payment: _activate_user(payment["user_id"], PAYMENT_HOURS, "Binance Pay")
    return jsonify({"returnCode": "SUCCESS", "returnMessage": None})

@app.route("/paypal-webhook", methods=["POST"])
def paypal_webhook():
    try:
        from payments import paypal_verify_webhook, paypal_parse_webhook
    except ImportError:
        return jsonify({"error": "payments module not found"}), 500
    raw = request.get_data(as_text=True)
    if not paypal_verify_webhook(dict(request.headers), raw): return jsonify({"error": "invalid signature"}), 401
    payment = paypal_parse_webhook(request.get_json(force=True) or {})
    if payment: _activate_user(payment["user_id"], PAYMENT_HOURS, "PayPal")
    return "", 200

def _start_bot_thread():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    admin = os.environ.get("ADMIN_TG_USERNAME", "jaydumisuni").strip()
    if not token:
        print("[relay] No TELEGRAM_BOT_TOKEN — bot not started.")
        return
    try:
        from bot import start_bot
        print(f"[relay] Starting bot (admin: @{admin})...")
        start_bot(token=token, admin_username=admin, get_stats_fn=get_stats)
    except Exception as exc:
        print(f"[relay] Bot error: {exc}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=_start_bot_thread, daemon=True, name="tg-bot").start()
    app.run(host="0.0.0.0", port=port)