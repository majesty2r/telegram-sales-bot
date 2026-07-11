"""
Telegram Sales Bot
------------------
Lets customers browse a product catalog, add items to a cart, and check out
by submitting their name, phone number, and delivery address. The finished
order is sent to you (the shop owner) in a Telegram chat, and the customer
gets a confirmation.

Edit products.json to change what you sell — no code changes needed for that.

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
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states for checkout
NAME, PHONE, ADDRESS, CONFIRM = range(4)


def load_products():
    with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_product(product_id):
    for p in load_products():
        if p["id"] == product_id:
            return p
    return None


def format_price(product):
    return f"{product['price']:,} {product.get('currency', '')}".strip()


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


# ---------- Catalog browsing ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"👋 Welcome to *{SHOP_NAME}*!\n\n"
        "Browse our products below and tap a product to see details, "
        "or add straight to your cart."
    )
    await update.message.reply_text(
        text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )


def main_menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🛍 View Products", callback_data="catalog")],
            [InlineKeyboardButton("🧺 View Cart", callback_data="view_cart")],
        ]
    )


async def show_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    products = load_products()
    keyboard = [
        [InlineKeyboardButton(f"{p['name']} — {format_price(p)}", callback_data=f"prod_{p['id']}")]
        for p in products
    ]
    keyboard.append([InlineKeyboardButton("🧺 View Cart", callback_data="view_cart")])
    await query.edit_message_text(
        "🛍 *Our Products:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_id = int(query.data.split("_")[1])
    product = get_product(product_id)
    if not product:
        await query.edit_message_text("Sorry, that product is no longer available.")
        return

    text = (
        f"*{product['name']}*\n"
        f"💰 {format_price(product)}\n\n"
        f"{product.get('description', '')}"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Add to Cart", callback_data=f"add_{product['id']}")],
            [InlineKeyboardButton("⬅️ Back to Catalog", callback_data="catalog")],
        ]
    )

    image_url = product.get("image_url")
    if image_url:
        await query.message.reply_photo(
            photo=image_url, caption=text, parse_mode="Markdown", reply_markup=keyboard
        )
        await query.message.delete()
    else:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


# ---------- Cart ----------

async def add_to_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Added to cart! 🛒")
    product_id = query.data.split("_")[1]
    cart = get_cart(context)
    cart[product_id] = cart.get(product_id, 0) + 1

    product = get_product(int(product_id))
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧺 View Cart", callback_data="view_cart")],
            [InlineKeyboardButton("⬅️ Continue Shopping", callback_data="catalog")],
        ]
    )
    text = f"✅ Added *{product['name']}* to your cart."
    if query.message.photo:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cart = get_cart(context)

    if not cart:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🛍 View Products", callback_data="catalog")]]
        )
        text = "Your cart is empty."
    else:
        lines = ["🧺 *Your Cart:*\n"]
        for pid, qty in cart.items():
            product = get_product(int(pid))
            if product:
                lines.append(f"• {product['name']} x{qty} — {format_price(product)} each")
        lines.append(f"\n*Total: {cart_total(cart):,} {load_products()[0].get('currency', '')}*")
        text = "\n".join(lines)
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✅ Checkout", callback_data="checkout")],
                [InlineKeyboardButton("🗑 Clear Cart", callback_data="clear_cart")],
                [InlineKeyboardButton("⬅️ Continue Shopping", callback_data="catalog")],
            ]
        )

    if query.message.photo:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def clear_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data["cart"] = {}
    await query.answer("Cart cleared.")
    await view_cart(update, context)


# ---------- Checkout conversation ----------

async def checkout_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cart = get_cart(context)
    if not cart:
        await query.edit_message_text("Your cart is empty. Add something first!")
        return ConversationHandler.END

    await query.message.reply_text(
        "Let's get your order sorted. What's your *full name*?\n\n"
        "(Send /cancel anytime to stop.)",
        parse_mode="Markdown",
    )
    return NAME


async def checkout_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["order_name"] = update.message.text.strip()
    await update.message.reply_text("Thanks! What's your *phone number*?", parse_mode="Markdown")
    return PHONE


async def checkout_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["order_phone"] = update.message.text.strip()
    await update.message.reply_text(
        "Got it. What's your *delivery address*?", parse_mode="Markdown"
    )
    return ADDRESS


async def checkout_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["order_address"] = update.message.text.strip()
    cart = get_cart(context)

    lines = ["📋 *Please confirm your order:*\n"]
    for pid, qty in cart.items():
        product = get_product(int(pid))
        if product:
            lines.append(f"• {product['name']} x{qty} — {format_price(product)} each")
    lines.append(f"\n*Total: {cart_total(cart):,}*")
    lines.append(f"\n👤 {context.user_data['order_name']}")
    lines.append(f"📞 {context.user_data['order_phone']}")
    lines.append(f"📍 {context.user_data['order_address']}")

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Confirm Order", callback_data="confirm_order")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_order")],
        ]
    )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=keyboard)
    return CONFIRM


async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cart = get_cart(context)
    user = query.from_user

    lines = [f"🆕 *New order from {SHOP_NAME}*\n"]
    for pid, qty in cart.items():
        product = get_product(int(pid))
        if product:
            lines.append(f"• {product['name']} x{qty} — {format_price(product)} each")
    lines.append(f"\n*Total: {cart_total(cart):,}*")
    lines.append(f"\n👤 Name: {context.user_data['order_name']}")
    lines.append(f"📞 Phone: {context.user_data['order_phone']}")
    lines.append(f"📍 Address: {context.user_data['order_address']}")
    lines.append(f"\n💬 Telegram: @{user.username or 'N/A'} (id: {user.id})")
    order_text = "\n".join(lines)

    if ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID, text=order_text, parse_mode="Markdown"
            )
        except Exception as e:
            logger.error("Failed to notify admin: %s", e)
    else:
        logger.warning("ADMIN_CHAT_ID not set — order was not forwarded to the shop owner.")

    await query.edit_message_text(
        "🎉 Thank you! Your order has been placed. We'll contact you shortly to confirm delivery."
    )

    context.user_data["cart"] = {}
    for key in ("order_name", "order_phone", "order_address"):
        context.user_data.pop(key, None)
    return ConversationHandler.END


async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Order cancelled. Your cart is still saved.")
    return ConversationHandler.END


async def cancel_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Checkout cancelled. Your cart is still saved.")
    return ConversationHandler.END


# ---------- Misc ----------

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - Show the main menu\n"
        "/cart - View your cart\n"
        "/cancel - Cancel checkout"
    )


async def cart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cart = get_cart(context)
    if not cart:
        await update.message.reply_text(
            "Your cart is empty.", reply_markup=main_menu_keyboard()
        )
        return
    lines = ["🧺 *Your Cart:*\n"]
    for pid, qty in cart.items():
        product = get_product(int(pid))
        if product:
            lines.append(f"• {product['name']} x{qty} — {format_price(product)} each")
    lines.append(f"\n*Total: {cart_total(cart):,}*")
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Checkout", callback_data="checkout")],
            [InlineKeyboardButton("🗑 Clear Cart", callback_data="clear_cart")],
        ]
    )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=keyboard)


def main():
    if not BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN is not set. Copy .env.example to .env and add your bot token."
        )

    app = Application.builder().token(BOT_TOKEN).build()

    checkout_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(checkout_start, pattern="^checkout$")],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, checkout_name)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, checkout_phone)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, checkout_address)],
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
    app.add_handler(checkout_conv)
    app.add_handler(CallbackQueryHandler(show_catalog, pattern="^catalog$"))
    app.add_handler(CallbackQueryHandler(show_product, pattern="^prod_"))
    app.add_handler(CallbackQueryHandler(add_to_cart, pattern="^add_"))
    app.add_handler(CallbackQueryHandler(view_cart, pattern="^view_cart$"))
    app.add_handler(CallbackQueryHandler(clear_cart, pattern="^clear_cart$"))

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
