"""
relay_server/bot.py — updated with machine UID deep-link activation
"""
import datetime, json, os

USERS_FILE    = "users.json"
BETA_CUTOFF   = datetime.date(2026, 7, 30)
PAYMENT_HOURS = int(os.environ.get("PAYMENT_HOURS", "5"))
PRICE_USDT    = os.environ.get("PAYMENT_AMOUNT_USDT", "1")
PRICE_USD     = os.environ.get("PAYMENT_AMOUNT_USD",  "1")
PRODUCT_NAME  = os.environ.get("PRODUCT_NAME",        "TechGuyTool")

def _is_beta():          return datetime.date.today() <= BETA_CUTOFF
def _load_users():
    try:
        with open(USERS_FILE) as f: return json.load(f)
    except: return {}
def _save_users(u):
    with open(USERS_FILE, "w") as f: json.dump(u, f, indent=2)
def _is_admin(update, admin):
    return (update.effective_user.username or "").lower() == admin.lower()
def _beta_footer():
    if _is_beta():
        days = (BETA_CUTOFF - datetime.date.today()).days
        return f"\n\n🟢 Beta FREE until July 30, 2025 ({days} days left)"
    return f"\n\n⚡ {PRICE_USDT} USDT or ${PRICE_USD} = {PAYMENT_HOURS} hours  |  use /pay"

async def cmd_start(update, ctx):
    uid   = str(update.effective_user.id)
    name  = update.effective_user.first_name or "Technician"
    uname = update.effective_user.username or ""
    machine_uid = " ".join(ctx.args).strip().upper() if ctx.args else ""
    if machine_uid and len(machine_uid) == 16:
        users = _load_users()
        if uid not in users:
            users[uid] = {"name": name, "username": uname, "active": True,
                          "plan": "beta", "registered": str(datetime.date.today())}
        users[uid]["machine_uid"] = machine_uid
        if _is_beta():
            users[uid]["active"] = True
            users[uid].setdefault("plan", "beta")
        _save_users(users)
        if _is_beta():
            days = (BETA_CUTOFF - datetime.date.today()).days
            await update.message.reply_text(
                f"✅ Device activated, {name}!\n\nBeta is FREE until July 30, 2025 ({days} days left).\n\nGo back to the app and press Start Repair."
                f"{_beta_footer()}"
            )
        else:
            u = _load_users().get(uid, {})
            if u.get("active") and u.get("hours_remaining", 0) > 0:
                await update.message.reply_text(f"✅ Device registered, {name}. Account active — go back to the app.{_beta_footer()}")
            else:
                await update.message.reply_text(f"Device registered, {name}. Beta ended — use /pay to activate.")
        return
    await update.message.reply_text(
        f"👋 Welcome to {PRODUCT_NAME}, {name}!\n\nCommands:\n  /register — activate your account\n  /status   — check your plan\n  /pay      — buy access (post-beta){_beta_footer()}"
    )

async def cmd_register(update, ctx):
    uid   = str(update.effective_user.id)
    name  = update.effective_user.first_name or "Technician"
    uname = update.effective_user.username or ""
    users = _load_users()
    if uid in users and users[uid].get("active"):
        u = users[uid]
        await update.message.reply_text(f"Already active!\n\nPlan:  {u.get('plan','beta')}\nHours: {u.get('hours_remaining','∞ (beta)')}{_beta_footer()}")
        return
    if _is_beta():
        users[uid] = {"name": name, "username": uname, "active": True, "plan": "beta", "registered": str(datetime.date.today())}
        _save_users(users)
        await update.message.reply_text(f"✅ Activated! Welcome, {name}.\n\nFull access until July 30, 2025.{_beta_footer()}")
    else:
        if uid not in users:
            users[uid] = {"name": name, "username": uname, "active": False, "plan": "none", "registered": str(datetime.date.today())}
            _save_users(users)
        await update.message.reply_text(f"Registered, {name}. Beta ended.\nUse /pay to activate.")

async def cmd_status(update, ctx):
    uid   = str(update.effective_user.id)
    users = _load_users()
    if uid not in users:
        await update.message.reply_text("Not registered.\nUse /register to activate.")
        return
    u    = users[uid]
    plan = u.get("plan", "none")
    dev  = "✅ Linked" if u.get("machine_uid") else "⚠️ Not linked — open app to link"
    await update.message.reply_text(
        f"👤 {u.get('name','Technician')}\nPlan:   {plan}\nActive: {'Yes ✅' if u.get('active') else 'No ❌'}\nHours:  {u.get('hours_remaining','∞ (beta)' if plan=='beta' else 0)}\nJoined: {u.get('registered','?')}\nDevice: {dev}{_beta_footer()}"
    )

async def cmd_pay(update, ctx):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    beta_note = " (not needed yet — beta is still active)" if _is_beta() else ""
    keyboard = [
        [InlineKeyboardButton(f"USDT — Binance Pay (link)    {PRICE_USDT} USDT", callback_data="pay_binance_link")],
        [InlineKeyboardButton(f"USDT — Binance Pay (QR code) {PRICE_USDT} USDT", callback_data="pay_binance_qr")],
        [InlineKeyboardButton(f"Card / PayPal                ${PRICE_USD}", callback_data="pay_paypal")],
    ]
    await update.message.reply_text(f"💳 Buy {PRODUCT_NAME} access{beta_note}\n\n{PRICE_USDT} USDT  or  ${PRICE_USD}  →  {PAYMENT_HOURS} hours\n\nPayment detected automatically.", reply_markup=InlineKeyboardMarkup(keyboard))

async def pay_callback(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = str(query.from_user.id)
    try:
        from payments import binance_create_order, paypal_create_order
    except ImportError as exc:
        await query.edit_message_text(f"Payment module error: {exc}"); return
    if query.data in ("pay_binance_link", "pay_binance_qr"):
        try:
            order = binance_create_order(uid)
            url = order["checkout_url"] if query.data == "pay_binance_link" else order["qr_code_url"]
            await query.edit_message_text(f"Pay {PRICE_USDT} USDT via Binance:\n\n{url}\n\n✅ Activated automatically on payment.")
        except Exception as exc:
            await query.edit_message_text(f"Binance error: {exc}\n\nTry PayPal instead.")
    elif query.data == "pay_paypal":
        try:
            order = paypal_create_order(uid)
            await query.edit_message_text(f"Pay ${PRICE_USD} via PayPal:\n\n{order['checkout_url']}\n\n✅ Activated automatically on payment.")
        except Exception as exc:
            await query.edit_message_text(f"PayPal error: {exc}\n\nTry Binance instead.")

async def cmd_stats(update, ctx):
    admin_username = ctx.bot_data.get("admin_username", "jaydumisuni")
    if not _is_admin(update, admin_username):
        await update.message.reply_text("⛔ Admin only."); return
    get_stats_fn = ctx.bot_data.get("get_stats_fn")
    s = get_stats_fn() if get_stats_fn else {}
    sessions = s.get("sessions", [])
    sess_lines = "\n".join(f"  • {x.get('label','—')}  [{x.get('code','')}]" for x in sessions) or "  (none)"
    await update.message.reply_text(f"📊 {PRODUCT_NAME} STATS\n{'─'*30}\nBeta: {'🟢 ACTIVE' if s.get('beta_active',True) else '🔴 ENDED'}\n\nRegistered: {s.get('total_users',0)} technicians\nActive:     {s.get('active_users',0)} technicians\n\nLive sessions: {s.get('active_codes',0)}\n{sess_lines}")

async def cmd_users(update, ctx):
    admin_username = ctx.bot_data.get("admin_username", "jaydumisuni")
    if not _is_admin(update, admin_username):
        await update.message.reply_text("⛔ Admin only."); return
    users = _load_users()
    if not users:
        await update.message.reply_text("No users registered yet."); return
    lines = []
    for uid, u in users.items():
        tag = f"@{u['username']}" if u.get("username") else u.get("name", uid)
        plan = u.get("plan","?")
        dev = "🔗" if u.get("machine_uid") else "  "
        lines.append(f"{'✅' if u.get('active') else '❌'}{dev} {tag} — {plan} — {u.get('hours_remaining','∞' if plan=='beta' else 0)}h — {u.get('registered','?')}")
    text = f"👥 USERS ({len(users)}):\n\n" + "\n".join(lines)
    await update.message.reply_text(text[:4000] + ("\n…(truncated)" if len(text)>4000 else ""))

async def cmd_activate(update, ctx):
    admin_username = ctx.bot_data.get("admin_username", "jaydumisuni")
    if not _is_admin(update, admin_username):
        await update.message.reply_text("⛔ Admin only."); return
    args = ctx.args
    if not args or len(args) < 2:
        await update.message.reply_text("Usage: /activate <user_id> <hours>"); return
    try: hours = int(args[1])
    except ValueError:
        await update.message.reply_text("Hours must be a number."); return
    users = _load_users()
    uid = args[0].strip()
    if uid not in users:
        users[uid] = {"name": uid, "username": "", "registered": str(datetime.date.today())}
    users[uid]["active"] = True
    users[uid]["plan"] = "paid"
    users[uid]["hours_remaining"] = users[uid].get("hours_remaining", 0) + hours
    _save_users(users)
    await update.message.reply_text(f"✅ Granted {hours}h to {uid}. Total: {users[uid]['hours_remaining']}h")

def start_bot(token: str, admin_username: str = "jaydumisuni", get_stats_fn=None):
    import asyncio
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler
    async def _run():
        tg_app = Application.builder().token(token).build()
        tg_app.bot_data["admin_username"] = admin_username
        tg_app.bot_data["get_stats_fn"]   = get_stats_fn
        tg_app.add_handler(CommandHandler("start",    cmd_start))
        tg_app.add_handler(CommandHandler("register", cmd_register))
        tg_app.add_handler(CommandHandler("status",   cmd_status))
        tg_app.add_handler(CommandHandler("pay",      cmd_pay))
        tg_app.add_handler(CommandHandler("stats",    cmd_stats))
        tg_app.add_handler(CommandHandler("users",    cmd_users))
        tg_app.add_handler(CommandHandler("activate", cmd_activate))
        tg_app.add_handler(CallbackQueryHandler(pay_callback, pattern="^pay_"))
        print(f"[bot] Running — admin: @{admin_username}")
        await tg_app.run_polling(drop_pending_updates=True)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:    loop.run_until_complete(_run())
    except Exception as exc: print(f"[bot] Stopped: {exc}")
    finally: loop.close()