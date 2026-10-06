import asyncio
import json
import logging
import os
import re
from aiohttp import web, ClientSession, ClientTimeout
import websockets
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Config & Variables
TOKEN = os.environ.get("TELEGRAM_TOKEN", "ISI_TOKEN_TELEGRAM_KAMU_DI_SINI")
SCAN_ACTIVE = True

# Load Narasi Meme
def load_narasi():
    try:
        with open("narasimeme.txt", "r", encoding="utf-8") as f:
            lines = [line.strip().lower() for line in f if line.strip()]
        print(f"Berhasil memuat {len(lines)} kategori narasi dari 'narasimeme.txt'.", flush=True)
        return lines
    except Exception as e:
        print(f"Gagal membaca narasimeme.txt: {e}", flush=True)
        return []

NARASI_KEYWORDS = load_narasi()

# ---------------------------------------------------------
# 1. DUMMY WEB SERVER (Untuk Health Check Render)
# ---------------------------------------------------------
async def start_dummy_server():
    while True:
        try:
            async def handle(request):
                return web.Response(text="Bot Radar Active & Running 24/7!")

            app_web = web.Application()
            app_web.router.add_get('/', handle)
            runner = web.AppRunner(app_web)
            await runner.setup()
            
            port = int(os.environ.get("PORT", 8080))
            site = web.TCPSite(runner, '0.0.0.0', port)
            await site.start()
            print(f"Dummy HTTP Server berjalan di port {port}", flush=True)
            
            # Biarkan server tetap aktif
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Error pada Dummy Server: {e}, merekrut ulang dalam 5 detik...", flush=True)
            await asyncio.sleep(5)

# ---------------------------------------------------------
# 2. SCANNER PUMP.FUN (WebSocket Safe Connection)
# ---------------------------------------------------------
async def scanner_pumpfun(application: Application):
    url = "wss://pumpportal.fun/api/data"
    while True:
        try:
            if not SCAN_ACTIVE:
                await asyncio.sleep(5)
                continue

            async with websockets.connect(
                url, 
                ping_interval=20, 
                ping_timeout=20,
                close_timeout=10
            ) as ws:
                # Subscribe ke koin baru yang diluncurkan
                payload = {"method": "subscribeNewToken"}
                await ws.send(json.dumps(payload))
                print("Scanner Pump.fun berhasil terhubung!", flush=True)

                async for message in ws:
                    if not SCAN_ACTIVE:
                        break
                    
                    data = json.loads(message)
                    # Logika Pemrosesan Koin Baru Pump.fun
                    # (Filter narasi / rugcheck di sini)
                    
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Pump.fun] Koneksi terputus: {e}. Reconnecting dalam 5 detik...", flush=True)
            await asyncio.sleep(5)

# ---------------------------------------------------------
# 3. SCANNER DEXSCREENER (HTTP Polling / WebSocket)
# ---------------------------------------------------------
async def scanner_dexscreener(application: Application):
    timeout = ClientTimeout(total=15)
    while True:
        try:
            if not SCAN_ACTIVE:
                await asyncio.sleep(5)
                continue

            async with ClientSession(timeout=timeout) as session:
                while SCAN_ACTIVE:
                    # Contoh Polling API DexScreener Profil Terbaru
                    url = "https://api.dexscreener.com/token-profiles/latest/v1"
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            # Proses data DexScreener di sini...
                            pass
                    
                    await asyncio.sleep(10) # Jeda antar request
                    
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[DexScreener] Error: {e}. Reconnecting dalam 5 detik...", flush=True)
            await asyncio.sleep(5)

# ---------------------------------------------------------
# 4. SCANNER DEXBOOSTS
# ---------------------------------------------------------
async def scanner_boosts(application: Application):
    timeout = ClientTimeout(total=15)
    while True:
        try:
            if not SCAN_ACTIVE:
                await asyncio.sleep(5)
                continue

            async with ClientSession(timeout=timeout) as session:
                while SCAN_ACTIVE:
                    url = "https://api.dexscreener.com/token-boosts/top/v1"
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            # Proses data Boosts di sini...
                            pass
                    
                    await asyncio.sleep(15)
                    
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[DexBoosts] Error: {e}. Reconnecting dalam 5 detik...", flush=True)
            await asyncio.sleep(5)

# ---------------------------------------------------------
# TELEGRAM COMMAND HANDLERS
# ---------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Halo! Bot Radar Memecoin Solana siap memantau koin 24/7.")

async def scan_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global SCAN_ACTIVE
    SCAN_ACTIVE = True
    await update.message.reply_text("🟢 Scanning Radar DIAKTIFKAN.")

async def scan_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global SCAN_ACTIVE
    SCAN_ACTIVE = False
    await update.message.reply_text("🔴 Scanning Radar DIMATIKAN.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_str = "🟢 Aktif" if SCAN_ACTIVE else "🔴 Nonaktif"
    await update.message.reply_text(f"📊 Status Radar: {status_str}\nTotal Narasi: {len(NARASI_KEYWORDS)}")

# ---------------------------------------------------------
# INITIALIZATION & MAIN FUNCTION
# ---------------------------------------------------------
async def post_init(application: Application):
    # Buat background tasks secara aman
    asyncio.create_task(start_dummy_server())
    asyncio.create_task(scanner_pumpfun(application))
    asyncio.create_task(scanner_dexscreener(application))
    asyncio.create_task(scanner_boosts(application))

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan_on", scan_on))
    app.add_handler(CommandHandler("scan_off", scan_off))
    app.add_handler(CommandHandler("status", status_command))

    print("Bot Radar Multi-Platform Siap & Aktif!", flush=True)
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
