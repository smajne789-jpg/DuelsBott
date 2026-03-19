# Telegram Duel Bot (FIXED COMMISSION 10%)
# =========================================

import asyncio
import random
import aiosqlite
import aiohttp

from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

# ================= CONFIG =================
BOT_TOKEN = "8706062192:AAFwM2ZxkVnXqoGuDVSXGcdf5Cw3tbuEl5A"
ADMIN_ID = 8034491282
WITHDRAW_CHANNEL_ID = -5113722562
CRYPTO_PAY_TOKEN = "552774:AAmFNSbZesnNHDgVLPMvv2jLhHyfxY3mylr"

COMMISSION_PERCENT = 0.10  # 10% комиссия

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ================= FSM =================
class DepositState(StatesGroup):
    amount = State()

class WithdrawState(StatesGroup):
    amount = State()

class DuelState(StatesGroup):
    bet = State()

# ================= DB =================
async def init_db():
    async with aiosqlite.connect("db.sqlite3") as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 0)")
        await db.execute("CREATE TABLE IF NOT EXISTS invoices (invoice_id TEXT, user_id INTEGER, amount REAL, status TEXT)")
        await db.commit()

# ================= UTILS =================
async def get_balance(uid):
    async with aiosqlite.connect("db.sqlite3") as db:
        async with db.execute("SELECT balance FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

async def update_balance(uid, amount):
    async with aiosqlite.connect("db.sqlite3") as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
        await db.commit()

# ================= UI =================
def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="💰 Пополнить", callback_data="deposit"),
         InlineKeyboardButton(text="📤 Вывод", callback_data="withdraw")],
        [InlineKeyboardButton(text="🎮 Играть", callback_data="duel")]
    ])

# ================= START =================
@dp.message(Command("start"))
async def start(msg: types.Message):
    async with aiosqlite.connect("db.sqlite3") as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (msg.from_user.id,))
        await db.commit()

    await msg.answer("Бот запущен!", reply_markup=menu())

# ================= PROFILE =================
@dp.callback_query(F.data == "profile")
async def profile(call):
    bal = await get_balance(call.from_user.id)
    await call.message.answer(f"Баланс: {bal}")

# ================= DEPOSIT =================
@dp.callback_query(F.data == "deposit")
async def deposit(call, state: FSMContext):
    await call.message.answer("Введите сумму:")
    await state.set_state(DepositState.amount)

@dp.message(DepositState.amount)
async def deposit_amount(msg: types.Message, state: FSMContext):
    amount = float(msg.text)

    async with aiohttp.ClientSession() as session:
        headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN}
        data = {"asset": "USDT", "amount": str(amount)}

        async with session.post("https://pay.crypt.bot/api/createInvoice", json=data, headers=headers) as resp:
            res = await resp.json()

    invoice = res["result"]

    async with aiosqlite.connect("db.sqlite3") as db:
        await db.execute("INSERT INTO invoices VALUES (?,?,?,?)",
                         (invoice["invoice_id"], msg.from_user.id, amount, "pending"))
        await db.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Оплатить", url=invoice["pay_url"])]
    ])

    await msg.answer("Оплати:", reply_markup=kb)
    await state.clear()

# ================= WEBHOOK =================
async def crypto_webhook(request):
    data = await request.json()

    if data.get("update_type") != "invoice_paid":
        return web.Response(text="ok")

    invoice = data["payload"]
    invoice_id = str(invoice["invoice_id"])

    async with aiosqlite.connect("db.sqlite3") as db:
        async with db.execute("SELECT user_id, amount, status FROM invoices WHERE invoice_id=?", (invoice_id,)) as cur:
            row = await cur.fetchone()

        if not row:
            return web.Response(text="not found")

        user_id, amount, status = row

        if status == "paid":
            return web.Response(text="already")

        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
        await db.execute("UPDATE invoices SET status='paid' WHERE invoice_id=?", (invoice_id,))
        await db.commit()

    await bot.send_message(user_id, f"Пополнение: {amount}$")
    return web.Response(text="ok")

# ================= WITHDRAW =================
@dp.callback_query(F.data == "withdraw")
async def withdraw(call, state: FSMContext):
    await call.message.answer("Введите сумму:")
    await state.set_state(WithdrawState.amount)

@dp.message(WithdrawState.amount)
async def withdraw_amount(msg: types.Message, state: FSMContext):
    amount = float(msg.text)
    bal = await get_balance(msg.from_user.id)

    if bal < amount:
        return await msg.answer("Недостаточно средств")

    await bot.send_message(WITHDRAW_CHANNEL_ID,
                           f"Заявка на вывод\nID: {msg.from_user.id}\nСумма: {amount}")

    await msg.answer("Отправлено")
    await state.clear()

# ================= DUEL =================
duels = {}

@dp.callback_query(F.data == "duel")
async def duel(call, state: FSMContext):
    await call.message.answer("Введите ставку:")
    await state.set_state(DuelState.bet)

@dp.message(DuelState.bet)
async def duel_process(msg: types.Message, state: FSMContext):
    bet = float(msg.text)
    bal = await get_balance(msg.from_user.id)

    if bal < bet:
        return await msg.answer("Недостаточно средств")

    duels[msg.from_user.id] = bet
    await msg.answer("Ждём соперника...")

    for user, b in duels.items():
        if user != msg.from_user.id and b == bet:

            await update_balance(user, -bet)
            await update_balance(msg.from_user.id, -bet)

            r1 = random.randint(1, 6)
            r2 = random.randint(1, 6)

            if r1 > r2:
                winner = user
            elif r2 > r1:
                winner = msg.from_user.id
            else:
                await update_balance(user, bet)
                await update_balance(msg.from_user.id, bet)
                return await msg.answer("Ничья")

            total_bank = bet * 2
            commission = total_bank * COMMISSION_PERCENT
            win = total_bank - commission

            await update_balance(winner, win)

            await bot.send_message(user, f"{r1} vs {r2} Победитель: {winner}\nВыигрыш: {win}")
            await bot.send_message(msg.from_user.id, f"{r1} vs {r2} Победитель: {winner}\nВыигрыш: {win}")

            del duels[user]
            del duels[msg.from_user.id]
            break

    await state.clear()

# ================= RUN =================
async def main():
    await init_db()

    app = web.Application()
    app.router.add_post("/webhook", crypto_webhook)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

    print("Webhook started")

    await dp.start_polling(bot)

asyncio.run(main())
