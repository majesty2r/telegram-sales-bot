"""
Telegram Sales Bot
------------------
Lets customers pick a language, browse a product catalog, add items to a
cart, and check out by paying with crypto. Payment proof + the order are
forwarded to you (the shop owner) in Telegram, and the customer gets a
confirmation.

Edit products.json to change what you sell, wallets.json for your crypto
addresses, and translations.json to tweak any customer-facing text — no
code changes needed for any of that.

Setup:
  1. pip install -r requirements.txt
  2. Copy .env.example to .env and fill in BOT_TOKEN and ADMIN_CHAT_ID
  3. python bot.py

See README.md for full setup and free hosting instructions.
"""

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, BotCommand
from telegram.helpers import escape_markdown
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # where new orders get sent
SHOP_NAME = os.getenv("SHOP_NAME", "Our Shop")

PRODUCTS_FILE = Path(__file__).parent / "products.json"
WALLETS_FILE = Path(__file__).parent / "wallets.json"
TRANSLATIONS_FILE = Path(__file__).parent / "translations.json"
DELIVERIES_FILE = Path(__file__).parent / "pending_deliveries.json"

ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID and ADMIN_CHAT_ID.lstrip("-").isdigit() else None

DEFAULT_LANG = "en"
SUPPORTED_LANGS = ["en", "zh", "vi", "ar"]  # order shown on the language picker

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states for checkout
CRYPTO_COIN, PAYMENT_PROOF, CONFIRM = range(3)


# ---------- Data loading ----------

def load_deliveries() -> dict:
    if not DELIVERIES_FILE.exists():
        return {}
    try:
        with open(DELIVERIES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_deliveries(deliveries: dict):
    with open(DELIVERIES_FILE, "w", encoding="utf-8") as f:
        json.dump(deliveries, f, ensure_ascii=False, indent=2)


def remember_delivery(admin_message_id: int, buyer_chat_id: int):
    """Links the order notification message (in your chat) to the buyer's chat,
    so a reply to that message can be auto-forwarded to them."""
    deliveries = load_deliveries()
    deliveries[str(admin_message_id)] = buyer_chat_id
    save_deliveries(deliveries)


def load_products():
    with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_products(products):
    with open(PRODUCTS_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)


def decrement_stock(cart: dict):
    """Reduces stock for purchased items. Note: this writes to the local products.json
    at runtime, so it only lasts until the next deploy/restart — see README for details."""
    products = load_products()
    changed = False
    for product in products:
        pid = str(product["id"])
        if pid in cart and "stock" in product:
            product["stock"] = max(0, product["stock"] - cart[pid])
            changed = True
    if changed:
        save_products(products)


def load_wallets():
    if not WALLETS_FILE.exists():
        return []
    with open(WALLETS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_translations():
    with open(TRANSLATIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


TRANSLATIONS = load_translations()


def md(text) -> str:
    """Escape user/config-supplied text so it can't break Telegram's Markdown parsing
    (e.g. a shop name or product name containing _ or * would otherwise crash the send)."""
    return escape_markdown(str(text), version=1)


def get_product(product_id):
    for p in load_products():
        if p["id"] == product_id:
            return p
    return None


def format_price(product):
    currency = product.get("currency", "")
    price = product["price"]
    if currency.upper() == "USD":
        return f"${price:,.2f}" if isinstance(price, float) else f"${price:,}"
    return f"{price:,} {currency}".strip()


def get_cart(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """cart is {product_id (str): quantity}"""
    return context.user_data.setdefault("cart", {})


def cart_total(cart: dict) -> int:
    total = 0
    for pid, qty in cart.items():
        product = get_product(int(pid))
        if product:
            total += product["price"] * qty
    return total


def format_total(cart: dict) -> str:
    total = cart_total(cart)
    products = load_products()
    currency = products[0].get("currency", "") if products else ""
    if currency.upper() == "USD":
        return f"${total:,.2f}" if isinstance(total, float) else f"${total:,}"
    return f"{total:,} {currency}".strip()


# ---------- i18n helpers ----------

def get_lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("lang", DEFAULT_LANG)


def t(context: ContextTypes.DEFAULT_TYPE, key: str, **kwargs) -> str:
    lang = get_lang(context)
    template = TRANSLATIONS.get(lang, {}).get(key) or TRANSLATIONS[DEFAULT_LANG].get(key, key)
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def language_keyboard(prefix: str) -> InlineKeyboardMarkup:
    """prefix is 'slang' for /start (resets cart) or 'clang' for /language (keeps cart)."""
    buttons = [
        [InlineKeyboardButton(TRANSLATIONS[code]["lang_name"], callback_data=f"{prefix}_{code}")]
        for code in SUPPORTED_LANGS
    ]
    return InlineKeyboardMarkup(buttons)


def main_menu_keyboard(context: ContextTypes.DEFAULT_TYPE):
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(context, "btn_view_products"), callback_data="catalog")],
            [InlineKeyboardButton(t(context, "btn_view_cart"), callback_data="view_cart")],
        ]
    )


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = t(context, "welcome", shop_name=md(SHOP_NAME))
    if update.callback_query:
        await update.callback_query.message.reply_text(
            text, parse_mode="Markdown", reply_markup=main_menu_keyboard(context)
        )
    else:
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=main_menu_keyboard(context)
        )


# ---------- Language selection ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start always resets the cart and lets the customer pick a language fresh."""
    context.user_data["cart"] = {}
    for key in ("payment_method", "payment_proof", "payment_proof_file_id"):
        context.user_data.pop(key, None)
    await update.message.reply_text(
        "🌐 Please choose your language / 请选择语言 / Vui lòng chọn ngôn ngữ / الرجاء اختيار اللغة:",
        reply_markup=language_keyboard("slang"),
    )


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/language changes language without touching the cart."""
    await update.message.reply_text(
        "🌐 Please choose your language / 请选择语言 / Vui lòng chọn ngôn ngữ / الرجاء اختيار اللغة:",
        reply_markup=language_keyboard("clang"),
    )


async def language_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, lang_code = query.data.split("_", 1)
    if lang_code not in SUPPORTED_LANGS:
        lang_code = DEFAULT_LANG
    context.user_data["lang"] = lang_code

    await query.edit_message_text(t(context, "language_set"))
    await send_main_menu(update, context)

    # Show the product catalog right away so the buyer doesn't need an extra tap.
    text, keyboard = build_catalog(context)
    await query.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


# ---------- Catalog browsing ----------

def build_catalog(context: ContextTypes.DEFAULT_TYPE):
    products = load_products()
    keyboard = []
    for p in products:
        label = f"{p['name']} — {format_price(p)}"
        if "stock" in p:
            label += " | ❌ 0" if p["stock"] <= 0 else f" | 📦 {p['stock']}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"prod_{p['id']}")])
    keyboard.append([InlineKeyboardButton(t(context, "btn_view_cart"), callback_data="view_cart")])
    return t(context, "catalog_header"), InlineKeyboardMarkup(keyboard)


async def show_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text, keyboard = build_catalog(context)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


def get_view_qty(context: ContextTypes.DEFAULT_TYPE, product_id: int) -> int:
    return context.user_data.setdefault("view_qty", {}).get(str(product_id), 1)


def set_view_qty(context: ContextTypes.DEFAULT_TYPE, product_id: int, qty: int):
    context.user_data.setdefault("view_qty", {})[str(product_id)] = max(1, min(qty, 99))


def build_product_view(context: ContextTypes.DEFAULT_TYPE, product: dict):
    stock = product.get("stock")
    sold_out = stock is not None and stock <= 0
    qty = get_view_qty(context, product["id"])

    text = (
        f"*{md(product['name'])}*\n"
        f"💰 {format_price(product)}\n"
    )
    if stock is not None:
        text += t(context, "out_of_stock") + "\n" if sold_out else t(context, "in_stock", stock=stock) + "\n"
    text += f"\n{md(product.get('description', ''))}"

    if sold_out:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(t(context, "btn_back_to_catalog"), callback_data="catalog")]]
        )
        return text, keyboard

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("➖", callback_data=f"qtydec_{product['id']}"),
                InlineKeyboardButton(f"{qty}", callback_data="noop"),
                InlineKeyboardButton("➕", callback_data=f"qtyinc_{product['id']}"),
            ],
            [
                InlineKeyboardButton(
                    t(context, "btn_add_qty_to_cart", qty=qty), callback_data=f"add_{product['id']}"
                )
            ],
            [InlineKeyboardButton(t(context, "btn_back_to_catalog"), callback_data="catalog")],
        ]
    )
    return text, keyboard


async def show_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_id = int(query.data.split("_")[1])
    product = get_product(product_id)
    if not product:
        await query.edit_message_text("Sorry, that product is no longer available.")
        return

    set_view_qty(context, product_id, 1)  # fresh view starts at quantity 1
    text, keyboard = build_product_view(context, product)

    image_url = product.get("image_url")
    if image_url:
        await query.message.reply_photo(
            photo=image_url, caption=text, parse_mode="Markdown", reply_markup=keyboard
        )
        await query.message.delete()
    else:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def adjust_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, product_id_str = query.data.split("_")
    product_id = int(product_id_str)
    product = get_product(product_id)
    if not product:
        await query.answer()
        return

    current = get_view_qty(context, product_id)
    new_qty = current + 1 if action == "qtyinc" else current - 1
    stock = product.get("stock")
    if stock is not None:
        new_qty = min(new_qty, stock)
    set_view_qty(context, product_id, new_qty)
    await query.answer()

    text, keyboard = build_product_view(context, product)
    if query.message.photo:
        await query.edit_message_caption(caption=text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


# ---------- Cart ----------

async def add_to_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🛒")
    product_id = query.data.split("_")[1]
    qty_to_add = get_view_qty(context, int(product_id))
    cart = get_cart(context)
    cart[product_id] = cart.get(product_id, 0) + qty_to_add
    set_view_qty(context, int(product_id), 1)  # reset stepper for next time

    product = get_product(int(product_id))
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(context, "btn_view_cart"), callback_data="view_cart")],
            [InlineKeyboardButton(t(context, "btn_continue_shopping"), callback_data="catalog")],
        ]
    )
    text = t(context, "added_to_cart", qty=qty_to_add, name=md(product["name"]))
    if query.message.photo:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


def build_cart_text(context: ContextTypes.DEFAULT_TYPE, cart: dict) -> str:
    lines = [t(context, "cart_header")]
    for pid, qty in cart.items():
        product = get_product(int(pid))
        if product:
            lines.append(
                t(context, "cart_line", name=md(product["name"]), qty=qty, price=format_price(product))
            )
    lines.append(t(context, "cart_total", total=format_total(cart)))
    return "\n".join(lines)


async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cart = get_cart(context)

    if not cart:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(t(context, "btn_view_products"), callback_data="catalog")]]
        )
        text = t(context, "cart_empty")
    else:
        text = build_cart_text(context, cart)
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(t(context, "btn_checkout"), callback_data="checkout")],
                [InlineKeyboardButton(t(context, "btn_clear_cart"), callback_data="clear_cart")],
                [InlineKeyboardButton(t(context, "btn_continue_shopping"), callback_data="catalog")],
            ]
        )

    if query.message.photo:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def clear_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data["cart"] = {}
    await query.answer(t(context, "cart_cleared"))
    await view_cart(update, context)


# ---------- Checkout conversation ----------

async def checkout_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cart = get_cart(context)
    if not cart:
        await query.edit_message_text(t(context, "cart_empty_checkout"))
        return ConversationHandler.END

    wallets = load_wallets()
    if not wallets:
        await query.message.reply_text(t(context, "payment_not_set_up"))
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(w["coin"], callback_data=f"coin_{i}")] for i, w in enumerate(wallets)]
    )
    await query.message.reply_text(t(context, "choose_coin"), reply_markup=keyboard)
    return CRYPTO_COIN


async def crypto_coin_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    wallets = load_wallets()
    index = int(query.data.split("_")[1])
    wallet = wallets[index]

    context.user_data["payment_method"] = f"Crypto — {wallet['coin']}"
    cart = get_cart(context)

    text = t(
        context,
        "pay_with_coin",
        coin=md(wallet["coin"]),
        address=wallet["address"],
        total=format_total(cart),
    )
    await query.edit_message_text(text, parse_mode="Markdown")
    return PAYMENT_PROOF


async def payment_proof_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        context.user_data["payment_proof"] = "photo"
        context.user_data["payment_proof_file_id"] = update.message.photo[-1].file_id
    else:
        context.user_data["payment_proof"] = update.message.text.strip()
    return await show_order_summary(update, context)


async def show_order_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cart = get_cart(context)
    lines = [t(context, "order_summary_header")]
    for pid, qty in cart.items():
        product = get_product(int(pid))
        if product:
            lines.append(
                t(context, "cart_line", name=md(product["name"]), qty=qty, price=format_price(product))
            )
    lines.append(t(context, "cart_total", total=format_total(cart)))
    lines.append(
        t(context, "summary_payment", method=md(context.user_data.get("payment_method", "N/A")))
    )
    if context.user_data.get("payment_proof") == "photo":
        lines.append(t(context, "summary_proof_photo"))
    elif context.user_data.get("payment_proof"):
        lines.append(t(context, "summary_proof_text", proof=md(context.user_data["payment_proof"])))

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(context, "btn_confirm_order"), callback_data="confirm_order")],
            [InlineKeyboardButton(t(context, "btn_cancel"), callback_data="cancel_order")],
        ]
    )
    text = "\n".join(lines)
    if update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    return CONFIRM


async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cart = get_cart(context)
    user = query.from_user

    # Admin-facing order notification stays in English regardless of buyer's language.
    lines = [f"🆕 *New order from {md(SHOP_NAME)}*\n"]
    for pid, qty in cart.items():
        product = get_product(int(pid))
        if product:
            lines.append(f"• {md(product['name'])} x{qty} — {format_price(product)} each")
    lines.append(f"\n*Total: {format_total(cart)}*")
    lines.append(f"💳 Payment: {md(context.user_data.get('payment_method', 'N/A'))}")
    proof = context.user_data.get("payment_proof")
    if proof and proof != "photo":
        lines.append(f"🧾 Proof: {md(proof)}")
    lines.append(f"🌐 Buyer language: {TRANSLATIONS.get(get_lang(context), {}).get('lang_name', 'N/A')}")
    lines.append(f"\n💬 Telegram: @{user.username or 'N/A'} (id: {user.id})")
    lines.append("\n↩️ *Reply to this message* with their product/login details to send it to them automatically.")
    order_text = "\n".join(lines)

    buyer_chat_id = query.message.chat_id

    if ADMIN_CHAT_ID:
        try:
            proof_file_id = context.user_data.get("payment_proof_file_id")
            if proof_file_id:
                sent = await context.bot.send_photo(
                    chat_id=ADMIN_CHAT_ID,
                    photo=proof_file_id,
                    caption=order_text,
                    parse_mode="Markdown",
                )
            else:
                sent = await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID, text=order_text, parse_mode="Markdown"
                )
            remember_delivery(sent.message_id, buyer_chat_id)
        except Exception as e:
            logger.error("Failed to notify admin: %s", e)
    else:
        logger.warning("ADMIN_CHAT_ID not set — order was not forwarded to the shop owner.")

    await query.edit_message_text(t(context, "order_confirmed"))

    try:
        decrement_stock(cart)
    except Exception as e:
        logger.error("Failed to update stock: %s", e)

    context.user_data["cart"] = {}
    for key in ("payment_method", "payment_proof", "payment_proof_file_id"):
        context.user_data.pop(key, None)
    return ConversationHandler.END


async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t(context, "order_cancelled"))
    return ConversationHandler.END


# ---------- Order fulfillment (admin replies auto-forward to the buyer) ----------

async def cancel_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(t(context, "checkout_cancelled"))
    return ConversationHandler.END


async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.reply_to_message:
        return

    deliveries = load_deliveries()
    buyer_chat_id = deliveries.get(str(message.reply_to_message.message_id))
    if not buyer_chat_id:
        return  # not a reply to an order notification — ignore

    # Look up the buyer's chosen language so the delivery message matches it.
    buyer_data = context.application.user_data.get(buyer_chat_id, {})
    buyer_lang = buyer_data.get("lang", DEFAULT_LANG)
    prefix = (
        TRANSLATIONS.get(buyer_lang, {}).get("order_fulfilled_prefix")
        or TRANSLATIONS[DEFAULT_LANG]["order_fulfilled_prefix"]
    )

    try:
        if message.photo:
            await context.bot.send_photo(
                chat_id=buyer_chat_id,
                photo=message.photo[-1].file_id,
                caption=f"{prefix}\n\n{message.caption}" if message.caption else prefix,
            )
        elif message.document:
            await context.bot.send_document(
                chat_id=buyer_chat_id,
                document=message.document.file_id,
                caption=f"{prefix}\n\n{message.caption}" if message.caption else prefix,
            )
        elif message.text:
            await context.bot.send_message(chat_id=buyer_chat_id, text=f"{prefix}\n\n{message.text}")
        else:
            return
        await message.reply_text("✅ Sent to the buyer.")
    except Exception as e:
        logger.error("Failed to forward delivery to buyer: %s", e)
        await message.reply_text(f"⚠️ Couldn't send to the buyer: {e}")


# ---------- Misc ----------

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(t(context, "help_text"))


async def cart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cart = get_cart(context)
    if not cart:
        await update.message.reply_text(
            t(context, "cart_empty"), reply_markup=main_menu_keyboard(context)
        )
        return
    text = build_cart_text(context, cart)
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(context, "btn_checkout"), callback_data="checkout")],
            [InlineKeyboardButton(t(context, "btn_clear_cart"), callback_data="clear_cart")],
        ]
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def post_init(app: Application):
    """Registers the bot's command menu (the '/' button in Telegram)."""
    await app.bot.set_my_commands(
        [
            BotCommand("start", "🔄 Restart / New order"),
            BotCommand("cart", "🧺 View your cart"),
            BotCommand("language", "🌐 Change language"),
            BotCommand("cancel", "❌ Cancel checkout"),
            BotCommand("help", "❓ Help"),
        ]
    )


def main():
    if not BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN is not set. Copy .env.example to .env and add your bot token."
        )

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    checkout_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(checkout_start, pattern="^checkout$")],
        states={
            CRYPTO_COIN: [CallbackQueryHandler(crypto_coin_selected, pattern="^coin_")],
            PAYMENT_PROOF: [
                MessageHandler(
                    (filters.TEXT & ~filters.COMMAND) | filters.PHOTO, payment_proof_received
                )
            ],
            CONFIRM: [
                CallbackQueryHandler(confirm_order, pattern="^confirm_order$"),
                CallbackQueryHandler(cancel_order, pattern="^cancel_order$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_checkout)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cart", cart_command))
    app.add_handler(CommandHandler("language", language_command))
    if ADMIN_CHAT_ID_INT is not None:
        app.add_handler(
            MessageHandler(
                filters.Chat(chat_id=ADMIN_CHAT_ID_INT) & filters.REPLY, handle_admin_reply
            )
        )
    app.add_handler(checkout_conv)
    app.add_handler(CallbackQueryHandler(language_selected, pattern="^slang_"))
    app.add_handler(CallbackQueryHandler(language_selected, pattern="^clang_"))
    app.add_handler(CallbackQueryHandler(show_catalog, pattern="^catalog$"))
    app.add_handler(CallbackQueryHandler(show_product, pattern="^prod_"))
    app.add_handler(CallbackQueryHandler(adjust_quantity, pattern="^qtyinc_"))
    app.add_handler(CallbackQueryHandler(adjust_quantity, pattern="^qtydec_"))
    app.add_handler(CallbackQueryHandler(noop, pattern="^noop$"))
    app.add_handler(CallbackQueryHandler(add_to_cart, pattern="^add_"))
    app.add_handler(CallbackQueryHandler(view_cart, pattern="^view_cart$"))
    app.add_handler(CallbackQueryHandler(clear_cart, pattern="^clear_cart$"))

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
