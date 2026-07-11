# Telegram Sales Bot

A simple, no-payment sales bot: customers browse your product catalog, add items
to a cart, and check out by sending their name, phone number, and delivery
address. You get the order sent straight to your Telegram, then you follow up
to arrange payment/delivery however you normally do.

## What's in this folder

| File | Purpose |
|---|---|
| `bot.py` | The bot itself |
| `products.json` | Your product list — **edit this to update what you sell** |
| `requirements.txt` | Python packages needed |
| `.env.example` | Template for your secret settings |

## 1. Create your bot on Telegram

1. Open Telegram, search for **@BotFather**, and start a chat.
2. Send `/newbot` and follow the prompts (choose a name and a username ending in `bot`).
3. BotFather will give you a **token** like `123456789:AAExampleToken...` — copy it.

## 2. Find your Chat ID (so orders get sent to you)

1. Search for **@userinfobot** on Telegram and send it any message.
2. It replies with your numeric **Id** — that's your `ADMIN_CHAT_ID`.
   (If you want orders sent to a group instead, add your bot to the group,
   send a message, then use `@userinfobot`'s group-id method, or the
   `/getUpdates` API trick described in the Telegram docs.)

## 3. Set up locally

```bash
cd telegram-sales-bot
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and fill in:
```
BOT_TOKEN=your token from BotFather
ADMIN_CHAT_ID=your id from userinfobot
SHOP_NAME=Whatever you want customers to see
```

Run it:
```bash
python bot.py
```

Open Telegram, find your bot, and send `/start`.

## 4. Edit your products

Open `products.json` and edit the list. Each product looks like:

```json
{
  "id": 1,
  "name": "Classic T-Shirt",
  "price": 1500,
  "currency": "KES",
  "description": "100% cotton, unisex, available in S/M/L/XL.",
  "image_url": ""
}
```

- `id` must be a unique whole number.
- `price` is just a number (no commas or currency symbols).
- `image_url` is optional — paste a public image link (e.g. from Imgur) to
  show a photo, or leave it as `""` for text-only.
- Save the file, restart the bot (`Ctrl+C` then `python bot.py` again), and
  your changes are live. No code changes needed.

## 5. Free hosting (so it runs 24/7 without your laptop on)

Any of these work well for a small bot like this. Pick one:

**Railway** (easiest, generous free trial credit)
1. Push this folder to a GitHub repo.
2. Go to railway.app → New Project → Deploy from GitHub repo.
3. Add your `.env` values under the project's Variables tab.
4. Set the start command to `python bot.py` (Railway usually auto-detects it).

**Render**
1. Push to GitHub, then on render.com choose New → Background Worker
   (not Web Service, since this bot doesn't listen on a port).
2. Build command: `pip install -r requirements.txt`
   Start command: `python bot.py`
3. Add your environment variables in the Render dashboard.

**Fly.io**
Good free allowance for small always-on processes; deploy with `fly launch`
after installing the Fly CLI, then set secrets with `fly secrets set BOT_TOKEN=... ADMIN_CHAT_ID=...`.

> Whichever you choose: never commit your real `.env` file to GitHub — only
> commit `.env.example`. Add `.env` to a `.gitignore` file.

## Customizing further

- **Multiple currencies/categories, quantities per item, discounts:** all
  possible — just let me know what you want and I can extend `bot.py`.
- **Accepting payments in-chat** (e.g. M-Pesa, Stripe): also doable, just say
  the word and I'll wire it in.
- **Google Sheets instead of products.json:** if you'd rather manage your
  catalog in a spreadsheet, I can switch it to read from Google Sheets.
