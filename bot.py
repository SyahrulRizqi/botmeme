import asyncio
import json
import os
import re
from datetime import datetime
import aiohttp
import websockets
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "8805019899:AAHqjc5OZ6OQfaDpEquTEWZH3EsuV8jZwS8"

subscribers = set()
seen_tokens = set()

# PARAMETER FILTER DEXSCREENER & RADAR
MAX_TOP10_PCT = 35.0       # Max Top 10 Holders 35%
MAX_BUNDLE_PCT = 5.0        # Max Bundle <= 5%
MIN_LP_LOCKED_PCT = 80.0   # LP Lock/Burn minimal 80%

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

# TRACKER STATUS SCANNING TERPISAH PER PLATFORM
stats = {
    "start_time": datetime.now(),
    "matches_found": 0,
    "pumpfun": {"scanned": 0, "last": "Belum ada scan"},
    "dex": {"scanned": 0, "last": "Belum ada scan"},
    "boosts": {"scanned": 0, "last": "Belum ada scan"}
}

def load_narratives_from_txt(filepath="narasimeme.txt") -> dict:
    narratives = {}
    current_cat = "General Meme / Meta"
    
    stopwords = {
        "ini", "salah", "satu", "kategori", "sangat", "besar", "setelah", "membantu", 
        "mendorong", "wajib", "masuk", "database", "khusus", "jangan", "berhenti", 
        "menunjukkan", "bahwa", "bisa", "menjadi", "tersendiri", "juga", "saat", "memiliki", 
        "menarik", "karena", "sekarang", "sudah", "punya", "sejarah", "viral", "dipisahkan", 
        "sering", "menggunakan", "sebaiknya", "dua", "makna", "sehingga", "bagus", "super", 
        "penting", "secara", "eksplisit", "justru", "membuktikan", "budaya", "terbesar", 
        "modern", "untuk", "kamu", "maksud", "yang", "ingin", "menangkap", "luas", 
        "ekosistem", "bukan", "tetapi", "paling", "layar", "contoh", "narasi", "sub-narasi", 
        "kategori", "contohnya", "sebuah", "dibaca", "sebagai", "maka", "buat", "berdasarkan"
    }

    if not os.path.exists(filepath):
        print(f"⚠️ File '{filepath}' tidak ditemukan! Menggunakan database default.", flush=True)
        return {
            "AI Agent": ["ai agent", "ai", "agent", "terminal", "claude"],
            "Dog / Animal": ["dog", "shiba", "floki", "bonk", "wif"],
            "Cat": ["cat", "popcat", "mew"],
            "Frog / Pepe": ["pepe", "frog"]
        }

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()
            if not line or "MASTER DATABASE" in line:
                continue

            if re.match(r'^(?:\d+\.|\b[A-Za-z0-9]+\b\s*\d+\.|\d+|[^\w\s]+)', line) and len(line) < 65:
                cat_name = re.sub(r'^[0-9\.\s\U0001F000-\U000e007f]+', '', line).strip()
                if cat_name and len(cat_name) > 2:
                    current_cat = cat_name.title()
                    if current_cat not in narratives:
                        narratives[current_cat] = set()
                    continue

            parts = re.split(r'[\t|,\n]+', line)
            for p in parts:
                clean_p = re.sub(r'[^\w\s\+\-]', '', p).strip().lower()
                if clean_p and len(clean_p) >= 2 and len(clean_p.split()) <= 4:
                    if clean_p not in stopwords and not clean_p.isdigit():
                        if current_cat not in narratives:
                            narratives[current_cat] = set()
                        narratives[current_cat].add(clean_p)

        final_db = {}
        for cat, kw_set in narratives.items():
            sorted_kws = sorted(list(kw_set), key=len, reverse=True)
            if sorted_kws:
                final_db[cat] = sorted_kws

        print(f"✅ Berhasil memuat {len(final_db)} kategori narasi dari '{filepath}'.", flush=True)
        return final_db

    except Exception as e:
        print(f"⚠️ Error membaca {filepath}: {e}", flush=True)
        return {"Meme / Meta": ["pepe", "doge", "shib", "trump", "ai"]}

NARRATIVE_DATABASE = load_narratives_from_txt("narasimeme.txt")

def deteksi_narasi(nama: str, simbol: str) -> tuple[bool, str, str]:
    teks_pencarian = f"{nama} {simbol}".lower()
    for kategori, keywords in NARRATIVE_DATABASE.items():
        for kw in keywords:
            pattern = r'\b' + re.escape(kw) + r'\b'
            if re.search(pattern, teks_pencarian):
                return True, kategori, kw
    return False, "Organik / Daily Trade", "-"

async def fetch_json(session: aiohttp.ClientSession, url: str, timeout=10):
    try:
        async with session.get(url, headers=HEADERS, timeout=timeout) as res:
            if res.status == 200:
                return await res.json()
    except Exception:
        pass
    return None

def cek_sosmed(pair):
    info = pair.get('info', {})
    websites = info.get('websites') or []
    socials = info.get('socials') or []

    has_web = len(websites) > 0
    has_x = any(s.get('type') == 'twitter' or 'x.com' in s.get('url', '') or 'twitter.com' in s.get('url', '') for s in socials)
    has_tg = any(s.get('type') == 'telegram' or 't.me' in s.get('url', '') for s in socials)

    return (has_web or has_x or has_tg), has_web, has_x, has_tg

def cek_dex_paid_only(pair) -> tuple[bool, str]:
    info = pair.get('info', {})
    has_header = bool(info.get('header'))
    has_icon = bool(info.get('imageUrl'))
    is_paid = has_header or has_icon
    label = "✅ DEX PAID (Profile / Banner Updated)" if is_paid else "⚪ UNPAID"
    return is_paid, label

def hitung_bundle(rug_resp):
    if 'bundledPct' in rug_resp and rug_resp['bundledPct'] is not None:
        return float(rug_resp['bundledPct'])
    risks = rug_resp.get('risks') or []
    for risk in risks:
        r_name = str(risk.get('name', '')).lower()
        if 'bundle' in r_name:
            val_str = str(risk.get('value', '0')).replace('%', '').strip()
            try:
                return float(val_str)
            except ValueError:
                return 99.0
    return 0.0

def hitung_lp_lock(rug_resp):
    markets = rug_resp.get('markets') or []
    if not markets:
        return 0.0
    max_lp_lock = 0.0
    for m in markets:
        lp = m.get('lp', {})
        pct_locked = float(lp.get('lpLockedPct', 0) or 0)
        pct_burned = float(lp.get('lpBurnedPct', 0) or 0)
        total = pct_locked + pct_burned
        if total > max_lp_lock:
            max_lp_lock = total
    return max_lp_lock

# --- PEMROSES RADAR ---

async def proses_koin_dex(session: aiohttp.ClientSession, address: str, app: Application, sumber: str):
    dex_url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
    dex_res = await fetch_json(session, dex_url)
    
    if not dex_res or not dex_res.get('pairs'):
        return

    pair = dex_res['pairs'][0]
    likuiditas = pair.get('liquidity', {}).get('usd', 0)
    mcap = float(pair.get('marketCap') or pair.get('fdv') or 0)
    ada_sosmed, has_web, has_x, has_tg = cek_sosmed(pair)
    _, dex_paid_label = cek_dex_paid_only(pair)

    if likuiditas >= 1000 and ada_sosmed:
        rug_url = f"https://api.rugcheck.xyz/v1/tokens/{address}/report"
        rug_resp = await fetch_json(session, rug_url)
        
        if rug_resp:
            score = rug_resp.get('score', 99999)
            risks = rug_resp.get('risks') or []
            danger_count = sum(1 for r in risks if r.get('level') == 'danger')
            
            lp_lock_pct = hitung_lp_lock(rug_resp)
            top_holders = rug_resp.get('topHolders') or []
            top10_pct = sum(float(h.get('pct', h.get('percent', 0))) for h in top_holders[:10])
            bundle_pct = hitung_bundle(rug_resp)

            if (score < 2500 and danger_count == 0 and lp_lock_pct >= MIN_LP_LOCKED_PCT and top10_pct <= MAX_TOP10_PCT and bundle_pct <= MAX_BUNDLE_PCT):
                stats["matches_found"] += 1
                nama = pair['baseToken']['name']
                simbol = pair['baseToken']['symbol']
                harga = pair.get('priceUsd', '0')
                volume = pair.get('volume', {}).get('h24', 0)
                pair_address = pair.get('pairAddress', '')

                is_narrative, kategori, keyword = deteksi_narasi(nama, simbol)
                header = "🔥 **[HOT NARRATIVE PLAY]** 🔥" if is_narrative else "⚡ **[DAILY TRADE SIGNAL]** ⚡"
                meta_info = f"🏷️ **Meta:** `{kategori}`" + (f" *(Matched: \"{keyword}\")*" if is_narrative else "")
                
                pesan = (
                    f"{header}\n"
                    f"📡 *Sumber Radar: {sumber}*\n"
                    f"{meta_info}\n\n"
                    f"🪙 **{nama} ({simbol})** | SOLANA\n"
                    f"💵 Harga: ${harga}\n"
                    f"💰 Market Cap: ${mcap:,.2f}\n"
                    f"💧 Likuiditas: ${likuiditas:,.2f}\n"
                    f"📊 Volume 24j: ${volume:,.2f}\n"
                    f"📢 DEX Status: `{dex_paid_label}`\n\n"
                    f"🛡️ **Keamanan DEX:** 🟢 AMAN (Skor: {score})\n"
                    f"🌐 Sosmed: Web {'✅' if has_web else '❌'} | X {'✅' if has_x else '❌'} | TG {'✅' if has_tg else '❌'}\n"
                    f"🔒 LP Lock / Burn: `{lp_lock_pct:.1f}%` *(>=80%)*\n"
                    f"👥 Top 10 Holders: `{top10_pct:.1f}%` *(<=35%)*\n"
                    f"📦 Bundle Supply: `{bundle_pct:.1f}%` *(<=5%)*\n\n"
                    f"📝 CA: `{address}`"
                )
                
                keyboard = [[
                    InlineKeyboardButton("📊 DexScreener", url=f"https://dexscreener.com/solana/{address}"),
                    InlineKeyboardButton("🚀 Photon", url=f"https://photon-sol.tinyastro.io/en/lp/{pair_address}"),
                    InlineKeyboardButton("📈 GMGN", url=f"https://gmgn.ai/sol/token/{address}")
                ]]

                for chat_id in list(subscribers):
                    try:
                        await app.bot.send_message(chat_id=chat_id, text=pesan, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
                    except Exception:
                        pass

async def proses_koin_pumpfun(session: aiohttp.ClientSession, data: dict, app: Application):
    address = data.get('mint')
    nama = data.get('name', 'Unknown')
    simbol = data.get('symbol', 'UNKNOWN')

    dex_url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
    dex_res = await fetch_json(session, dex_url)
    
    dex_paid_label = "⚪ UNPAID"
    if dex_res and dex_res.get('pairs'):
        pair = dex_res['pairs'][0]
        _, dex_paid_label = cek_dex_paid_only(pair)

    stats["matches_found"] += 1
    is_narrative, kategori, keyword = deteksi_narasi(nama, simbol)
    header = f"🚀 **[NEW PUMP.FUN LAUNCH]** 🚀"
    meta_info = f"🏷️ **Meta:** `{kategori}`" + (f" *(Matched: \"{keyword}\")*" if is_narrative else "")
    
    pesan = (
        f"{header}\n"
        f"📡 *Sumber Radar: Pump.fun (Bonding Curve)*\n"
        f"{meta_info}\n\n"
        f"🪙 **{nama} ({simbol})** | SOLANA\n"
        f"📢 DEX Status: `{dex_paid_label}`\n"
        f"⚡ Status: Baru Lahir di Bonding Curve\n\n"
        f"📝 CA: `{address}`"
    )
    
    keyboard = [[
        InlineKeyboardButton("💊 Pump.fun", url=f"https://pump.fun/{address}"),
        InlineKeyboardButton("📈 GMGN", url=f"https://gmgn.ai/sol/token/{address}")
    ]]

    for chat_id in list(subscribers):
        try:
            await app.bot.send_message(chat_id=chat_id, text=pesan, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            pass

# --- SCANNER LOOPS ---

# 1. PUMP.FUN WEBSOCKET DENGAN FIX STABILITY
async def scanner_pumpfun(app: Application):
    print("⚡ [Pump.fun] WebSocket Radar Aktif...", flush=True)
    uri = "wss://pumpportal.fun/api/data"
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                # ping_interval=None mencegah bentrok frame PING dengan server Pumpportal
                async with websockets.connect(uri, ping_interval=None) as ws:
                    payload = {"op": "subscribeNewToken"}
                    await ws.send(json.dumps(payload))
                    print("✅ [Pump.fun] Connected & Subscribed to WebSocket!", flush=True)
                    
                    while True:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=45.0)
                            waktu = datetime.now().strftime("%H:%M:%S WIB")
                            stats["pumpfun"]["last"] = waktu
                            stats["pumpfun"]["scanned"] += 1
                            print(f"[{waktu}] 💊 [Pump.fun] Scan Token #{stats['pumpfun']['scanned']}", flush=True)

                            if subscribers:
                                data = json.loads(msg)
                                address = data.get('mint')
                                if address and address not in seen_tokens:
                                    seen_tokens.add(address)
                                    asyncio.create_task(proses_koin_pumpfun(session, data, app))
                        except asyncio.TimeoutError:
                            print("⚠️ [Pump.fun] Idle 45s, Reconnecting...", flush=True)
                            break
            except Exception as e:
                print(f"⚠️ [Pump.fun] Error WebSocket: {e}, Reconnecting in 5s...", flush=True)
                await asyncio.sleep(5)

# 2. DEXSCREENER LATEST PROFILES
async def scanner_dexscreener(app: Application):
    print("🔄 [DexScreener] Radar Aktif...", flush=True)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                url = "https://api.dexscreener.com/token-profiles/latest/v1"
                resp = await fetch_json(session, url)
                waktu = datetime.now().strftime("%H:%M:%S WIB")
                stats["dex"]["last"] = waktu
                
                if resp and isinstance(resp, list):
                    for item in resp:
                        chain = item.get('chainId', '')
                        address = item.get('tokenAddress', '')
                        if chain == 'solana' and address and address not in seen_tokens:
                            seen_tokens.add(address)
                            stats["dex"]["scanned"] += 1
                            print(f"[{waktu}] 🦅 [DexScreener] Checking CA: {address[:8]}... Total: {stats['dex']['scanned']}", flush=True)
                            if subscribers:
                                asyncio.asyncio.create_task(proses_koin_dex(session, address, app, "DexScreener"))
            except Exception:
                pass
            await asyncio.sleep(10)

# 3. DEXSCREENER BOOSTS / TRENDING
async def scanner_boosts(app: Application):
    print("🚀 [DexBoosts] Radar Aktif...", flush=True)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                url = "https://api.dexscreener.com/token-boosts/latest/v1"
                resp = await fetch_json(session, url)
                waktu = datetime.now().strftime("%H:%M:%S WIB")
                stats["boosts"]["last"] = waktu
                
                if resp and isinstance(resp, list):
                    for item in resp:
                        chain = item.get('chainId', '')
                        address = item.get('tokenAddress', '')
                        if chain == 'solana' and address and address not in seen_tokens:
                            seen_tokens.add(address)
                            stats["boosts"]["scanned"] += 1
                            print(f"[{waktu}] 🚀 [DexBoosts] Checking CA: {address[:8]}... Total: {stats['boosts']['scanned']}", flush=True)
                            if subscribers:
                                asyncio.create_task(proses_koin_dex(session, address, app, "DexBoosts"))
            except Exception:
                pass
            await asyncio.sleep(15)

# COMMAND BOT TELEGRAM
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pesan = "Halo Bro! 🤖 Bot Radar Multi-Platform Aktif!\n\nKetik `/scan_on` untuk mulai menerima sinyal.\nKetik `/status` untuk cek kondisi radar."
    await update.message.reply_text(pesan, parse_mode='Markdown')

async def scan_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subscribers.add(update.effective_chat.id)
    await update.message.reply_text("✅ **Auto-Scanner DIAKTIFKAN!** Monitoring Pump.fun, DexScreener, & DexBoosts.", parse_mode='Markdown')

async def scan_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subscribers.discard(update.effective_chat.id)
    await update.message.reply_text("🔴 **Auto-Scanner DIMATIKAN.**", parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = datetime.now() - stats["start_time"]
    jam, sisa = divmod(int(uptime.total_seconds()), 3600)
    menit, detik = divmod(sisa, 60)
    
    total_semua = stats["pumpfun"]["scanned"] + stats["dex"]["scanned"] + stats["boosts"]["scanned"]
    
    pesan = (
        f"📊 **[STATUS RADAR & HEARTBEAT]**\n\n"
        f"🟢 **Status Bot:** Aktif & Scanning...\n"
        f"⏱️ **Uptime Bot:** {jam}j {menit}m {detik}d\n"
        f"👥 **Subscriber Aktif:** {len(subscribers)} Chat\n"
        f"🎯 **Sinyal Lolos Filter:** `{stats['matches_found']}`\n\n"
        f"🔍 **Statistik Token Per Platform:**\n"
        f"• 💊 **Pump.fun:** `{stats['pumpfun']['scanned']}` token *(Scan: {stats['pumpfun']['last']})*\n"
        f"• 🦅 **DexScreener:** `{stats['dex']['scanned']}` token *(Scan: {stats['dex']['last']})*\n"
        f"• 🚀 **DexBoosts:** `{stats['boosts']['scanned']}` token *(Scan: {stats['boosts']['last']})*\n\n"
        f"🌐 **Total Keseluruhan Diperiksa:** `{total_semua}`"
    )
    await update.message.reply_text(pesan, parse_mode='Markdown')

async def cek_koin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("Format salah bro! Ketik: /cek <Alamat_Kontrak>")
        return

    contract_address = context.args[0]
    pesan_proses = await update.message.reply_text(f"🔍 Memindai {contract_address[:5]}... di DexScreener & Rugcheck...")

    async with aiohttp.ClientSession() as session:
        dex_url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
        response = await fetch_json(session, dex_url)
        
        if response and response.get('pairs'):
            pair = response['pairs'][0] 
            nama = pair['baseToken']['name']
            simbol = pair['baseToken']['symbol']
            harga = pair.get('priceUsd', '0')
            mcap = float(pair.get('marketCap') or pair.get('fdv') or 0)
            likuiditas = pair.get('liquidity', {}).get('usd', 0)
            volume_24h = pair.get('volume', {}).get('h24', 0)
            jaringan = pair['chainId'].upper()

            ada_sosmed, has_web, has_x, has_tg = cek_sosmed(pair)
            _, dex_paid_label = cek_dex_paid_only(pair)
            sosmed_info = f"🌐 **Sosmed:** Web {'✅' if has_web else '❌'} | X {'✅' if has_x else '❌'} | TG {'✅' if has_tg else '❌'}"

            status_rug = "Tidak didukung"
            insider_info = bundle_info = lp_info = "Data tidak tersedia"
            
            if jaringan == "SOLANA":
                rug_url = f"https://api.rugcheck.xyz/v1/tokens/{contract_address}/report"
                rug_resp = await fetch_json(session, rug_url)
                
                if rug_resp:
                    score = rug_resp.get('score', 0)
                    risks = rug_resp.get('risks') or []
                    danger_count = sum(1 for r in risks if r.get('level') == 'danger')

                    lp_lock_pct = hitung_lp_lock(rug_resp)
                    status_lp = "🟢 LOCKED" if lp_lock_pct >= MIN_LP_LOCKED_PCT else "🔴 UNLOCKED"
                    lp_info = f"🔒 **LP Lock / Burn:** `{lp_lock_pct:.1f}%` ({status_lp})"

                    top_holders = rug_resp.get('topHolders') or []
                    top10_pct = sum(float(h.get('pct', h.get('percent', 0))) for h in top_holders[:10])
                    
                    bundle_pct = hitung_bundle(rug_resp)
                    bundle_info = f"📦 **Bundle Supply:** `{bundle_pct:.1f}%` ({'🟢 PAS (<5%)' if bundle_pct <= MAX_BUNDLE_PCT else '🔴 ADA BUNDLE'})"

                    insider_info = f"👥 Top 10 Holders: `{top10_pct:.1f}%` ({'🟢 PAS' if top10_pct <= MAX_TOP10_PCT else '🔴 TINGGI'})"

                    if score < 2500 and danger_count == 0 and bundle_pct <= MAX_BUNDLE_PCT:
                        status_rug = f"🟢 AMAN (Skor: {score})"
                    else:
                        status_rug = f"🔴 BAHAYA / HATI-HATI (Skor: {score})"

            is_narrative, kategori, keyword = deteksi_narasi(nama, simbol)
            meta_info = f"🏷️ **Meta:** `{kategori}`" + (f" *(Matched: \"{keyword}\")*" if is_narrative else "")

            pesan = (
                f"🪙 **{nama} ({simbol})** | {jaringan}\n"
                f"{meta_info}\n\n"
                f"💵 Harga: ${harga}\n"
                f"💰 Market Cap: ${mcap:,.2f}\n"
                f"💧 Likuiditas: ${likuiditas:,.2f}\n"
                f"📊 Volume 24j: ${volume_24h:,.2f}\n"
                f"📢 DEX Status: `{dex_paid_label}`\n\n"
                f"🛡️ **Keamanan:** {status_rug}\n"
                f"{sosmed_info}\n"
                f"{lp_info}\n"
                f"🕵️ **Analisis Insider:**\n{insider_info}\n"
                f"{bundle_info}\n\n"
                f"📝 CA: `{contract_address}`"
            )

            keyboard = [[
                InlineKeyboardButton("📊 DexScreener", url=f"https://dexscreener.com/solana/{contract_address}"),
                InlineKeyboardButton("🚀 Photon", url=f"https://photon-sol.tinyastro.io/en/lp/{pair.get('pairAddress', '')}"),
                InlineKeyboardButton("📈 GMGN", url=f"https://gmgn.ai/sol/token/{contract_address}")
            ]]
            await pesan_proses.edit_text(pesan, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await pesan_proses.edit_text("❌ Koin tidak ditemukan atau koneksi API terganggu.")

async def post_init(application: Application):
    asyncio.create_task(scanner_pumpfun(application))
    asyncio.create_task(scanner_dexscreener(application))
    asyncio.create_task(scanner_boosts(application))

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cek", cek_koin))
    app.add_handler(CommandHandler("scan_on", scan_on))
    app.add_handler(CommandHandler("scan_off", scan_off))
    app.add_handler(CommandHandler("status", status_command))
    
    print("Bot Radar Multi-Platform Aktif!", flush=True)
    app.run_polling()

if __name__ == '__main__':
    main()