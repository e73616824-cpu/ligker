import random
import time
from telegram import Update
from telegram.ext import ContextTypes
from data.leagues import get_leagues, get_league_by_id, get_team_by_id, search_team, search_player
from utils.data_manager import (
    get_user_team, set_user_team, get_training_data, save_training_data,
    get_league_state, save_league_state, set_announce_channel,
    get_guild_data, save_guild_data, get_match_log
)
from match_engine import init_league, simulate_match_day

TRAINING_TYPES = {
    "kondisyon":     {"name": "Kondisyon Antrenmanı", "emoji": "🏃", "xpBase": 20, "desc": "Dayanıklılığı artırır"},
    "teknik":        {"name": "Teknik Antrenman",     "emoji": "⚽", "xpBase": 25, "desc": "Top kontrolü ve pas"},
    "taktik":        {"name": "Taktik Antrenman",     "emoji": "📋", "xpBase": 30, "desc": "Savunma ve hücum"},
    "gucantrenman":  {"name": "Güç Antrenmanı",       "emoji": "💪", "xpBase": 20, "desc": "Fiziksel güç ve hız"},
    "atismapraktik": {"name": "Atış Pratiği",         "emoji": "🎯", "xpBase": 28, "desc": "Şut isabeti ve güç"},
}
COOLDOWN_HOURS = 6


def estimate_value(player):
    age = player.get("age", 25)
    overall = player.get("overall", 70)
    pos = player.get("position", "CM")
    age_factor = 1.5 if age < 23 else 1.2 if age < 27 else 1.0 if age < 30 else 0.7 if age < 33 else 0.4
    pos_mult = {"ST": 1.3, "CAM": 1.2, "LW": 1.2, "RW": 1.2, "CM": 1.0, "CB": 0.9, "RB": 0.9, "LB": 0.9, "GK": 0.8}.get(pos, 1.0)
    raw = ((overall - 60) / 30) ** 2 * 150 * age_factor * pos_mult
    return round(max(raw, 1) * 10) / 10


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return member.status in ("creator", "administrator")
    except:
        return False


# ── TAKIM Komutları ────────────────────────────────────────────────────────────

async def cmd_takim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    guild_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    my_team_id = get_user_team(guild_id, user_id)
    if not my_team_id:
        return await update.message.reply_text(
            "⚽ <b>Takım Seç</b>\n\n"
            "/takimsec &lt;takım adı&gt; — Takım seç\n"
            "/kadro [takım adı] — Kadro görüntüle\n"
            "/takimlar [lig_id] — Tüm takımlar\n\n"
            "<b>Örnek:</b>\n/takimsec Real Madrid\n/takimsec Manchester City",
            parse_mode="HTML"
        )
    td = get_team_by_id(my_team_id)
    if not td:
        return await update.message.reply_text("❌ Takım bulunamadı.")
    team, league = td["team"], td["league"]
    avg = round(sum(p["overall"] for p in team["players"]) / len(team["players"]))
    await update.message.reply_text(
        f"{team['emoji']} <b>{team['name']}</b>\n\n"
        f"🏆 Lig: {league['emoji']} {league['name']}\n"
        f"🏟️ Stat: {team['stadium']}\n"
        f"👔 Teknik Direktör: {team['manager']}\n"
        f"👥 Kadro: {len(team['players'])} oyuncu\n"
        f"⭐ Ort. Güç: {avg} OVR\n"
        f"💰 Bütçe: €{team['budget']//1000000}M\n\n"
        f"/kadro — Kadroyu görüntüle\n/takimsec &lt;ad&gt; — Takım değiştir",
        parse_mode="HTML"
    )


async def cmd_takimsec(update: Update, context: ContextTypes.DEFAULT_TYPE):
    guild_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    team_name = " ".join(context.args)
    if not team_name:
        return await update.message.reply_text(
            "Kullanım: /takimsec &lt;takım adı&gt;\nÖrnek: /takimsec Manchester City",
            parse_mode="HTML"
        )
    results = search_team(team_name)
    if not results:
        return await update.message.reply_text(
            f"❌ <b>{team_name}</b> bulunamadı. /takimlar ile tüm takımları görebilirsin.",
            parse_mode="HTML"
        )
    team, league = results[0]["team"], results[0]["league"]
    set_user_team(guild_id, user_id, team["id"])
    await update.message.reply_text(
        f"✅ <b>Takımın Seçildi: {team['emoji']} {team['name']}</b>\n\n"
        f"🏆 Lig: {league['emoji']} {league['name']}\n"
        f"🏟️ Stat: {team['stadium']}\n"
        f"👔 Teknik Direktör: {team['manager']}\n"
        f"👥 Kadro: {len(team['players'])} oyuncu\n"
        f"💰 Bütçe: €{team['budget']//1000000}M\n\n"
        "Artık antrenman yapabilirsin! /antrenman",
        parse_mode="HTML"
    )


async def cmd_kadro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    guild_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    team_name = " ".join(context.args)
    if team_name:
        results = search_team(team_name)
        if not results:
            return await update.message.reply_text(f"❌ <b>{team_name}</b> bulunamadı.", parse_mode="HTML")
        td = results[0]
    else:
        my_team_id = get_user_team(guild_id, user_id)
        if not my_team_id:
            return await update.message.reply_text(
                "❌ Önce bir takım seç: /takimsec &lt;takım adı&gt;", parse_mode="HTML"
            )
        td = get_team_by_id(my_team_id)
        if not td:
            return await update.message.reply_text("❌ Takım verisi bulunamadı.")

    team, league = td["team"], td["league"]
    pos_order = ["GK", "CB", "RB", "LB", "DM", "CM", "CAM", "RW", "LW", "ST"]
    pos_emoji = {"GK": "🧤", "CB": "🛡️", "RB": "🛡️", "LB": "🛡️", "CM": "⚙️", "CAM": "🎯", "DM": "🛡️", "RW": "⚡", "LW": "⚡", "ST": "🔥"}

    by_pos = {}
    for p in team["players"]:
        by_pos.setdefault(p["position"], []).append(p)

    msg = f"{team['emoji']} <b>{team['name']} — Kadro</b>\n{league['emoji']} {league['name']}\n\n"
    for pos in pos_order:
        players = by_pos.get(pos, [])
        if not players:
            continue
        msg += f"{pos_emoji.get(pos, '⚽')} <b>{pos}</b>\n"
        for p in players:
            msg += f"  • {p['name']} ({p['nationality']}) — OVR: <b>{p['overall']}</b>\n"
        msg += "\n"

    if len(msg) > 4096:
        msg = msg[:4000] + "\n<i>...(liste kısaltıldı)</i>"
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_takimlar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    league_id = context.args[0].lower() if context.args else None
    if not league_id:
        leagues = get_leagues()
        msg = "🌍 <b>Tüm Ligler</b>\n\n"
        for l in leagues:
            msg += f"{l['emoji']} <b>{l['name']}</b> — <code>{l['id']}</code> ({len(l['teams'])} takım)\n"
        msg += "\nDetay için: /takimlar &lt;lig_id&gt;"
        return await update.message.reply_text(msg, parse_mode="HTML")

    league = get_league_by_id(league_id)
    if not league:
        return await update.message.reply_text(f"❌ <b>{league_id}</b> ligi bulunamadı.", parse_mode="HTML")

    msg = f"{league['emoji']} <b>{league['name']} — Takımlar</b>\n\n"
    for t in league["teams"]:
        msg += f"{t['emoji']} <b>{t['name']}</b>\n   🏟️ {t['stadium']} | 👔 {t['manager']}\n\n"
    await update.message.reply_text(msg, parse_mode="HTML")


# ── ANTRENMAN Komutları ───────────────────────────────────────────────────────

async def cmd_antrenman(update: Update, context: ContextTypes.DEFAULT_TYPE):
    guild_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)

    my_team_id = get_user_team(guild_id, user_id)
    if not my_team_id:
        return await update.message.reply_text("❌ Önce takım seç: /takimsec &lt;takım adı&gt;", parse_mode="HTML")
    td = get_team_by_id(my_team_id)
    if not td:
        return await update.message.reply_text("❌ Takım bulunamadı.")
    team = td["team"]

    sub = context.args[0].lower() if context.args else None

    if not sub:
        training_data = get_training_data(guild_id, user_id) or {}
        last = training_data.get("lastTraining")
        cooldown_ms = COOLDOWN_HOURS * 3600
        can_train = not last or (time.time() - last) > cooldown_ms
        msg = f"{team['emoji']} <b>{team['name']} — Antrenman</b>\n\n"
        for key, t in TRAINING_TYPES.items():
            msg += f"{t['emoji']} /antrenman {key}\n   <i>{t['desc']}</i>\n\n"
        if can_train:
            msg += "✅ <b>Antrenman yapabilirsin!</b>"
        else:
            remaining = int((last + cooldown_ms - time.time()) / 60)
            msg += f"⏳ Sonraki antrenman: <b>{remaining} dakika sonra</b>"
        msg += f"\n📈 Toplam seans: {training_data.get('totalSessions', 0)}"
        return await update.message.reply_text(msg, parse_mode="HTML")

    training_data = get_training_data(guild_id, user_id) or {"lastTraining": None, "totalSessions": 0, "history": []}
    cooldown_ms = COOLDOWN_HOURS * 3600
    last = training_data.get("lastTraining")
    if last and (time.time() - last) < cooldown_ms:
        remaining = int((last + cooldown_ms - time.time()) / 60)
        return await update.message.reply_text(
            f"⏳ Antrenman için <b>{remaining} dakika</b> daha bekle!", parse_mode="HTML"
        )

    tt = TRAINING_TYPES.get(sub)
    if not tt:
        return await update.message.reply_text("❌ Geçersiz antrenman tipi. Kullanım: /antrenman", parse_mode="HTML")

    xp = tt["xpBase"] + random.randint(0, 14)
    boosted = random.randint(3, 7)
    featured = random.sample(team["players"], min(3, len(team["players"])))
    featured_txt = "\n".join(f"• <b>{p['name']}</b> ({p['position']})" for p in featured)

    results = [
        "🌟 Mükemmel antrenman! Takım harika bir form tutturdu.",
        "✅ İyi bir antrenman geçti. Oyuncular motivasyonlu.",
        "📈 Verimli çalışma. Bazı oyuncular dikkat çekti.",
        "⚽ Solid bir antrenman. Taktikler oturdu.",
        "💪 Fiziksel antrenman tamamlandı. Takım güçlendi.",
    ]

    training_data["lastTraining"] = time.time()
    training_data["totalSessions"] = training_data.get("totalSessions", 0) + 1
    training_data.setdefault("history", []).insert(0, {"type": sub, "xp": xp, "date": time.time()})
    training_data["history"] = training_data["history"][:20]
    save_training_data(guild_id, user_id, training_data)

    await update.message.reply_text(
        f"{tt['emoji']} <b>{tt['name']} Tamamlandı!</b>\n\n"
        f"{random.choice(results)}\n\n"
        f"⭐ XP Kazanıldı: <b>+{xp} XP</b>\n"
        f"👥 Etkilenen Oyuncu: <b>{boosted} oyuncu</b>\n\n"
        f"🌟 <b>Öne Çıkan Oyuncular:</b>\n{featured_txt}\n\n"
        f"⏳ Sonraki antrenman: {COOLDOWN_HOURS} saat sonra",
        parse_mode="HTML"
    )


# ── TRANSFER Komutları ────────────────────────────────────────────────────────

async def cmd_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 <b>Transfer Sistemi</b>\n\n"
        "/transferara &lt;oyuncu adı&gt; — Oyuncu ara\n"
        "/oyuncu &lt;oyuncu adı&gt; — Oyuncu detayı\n"
        "/pazar — Günlük transfer pazarı\n\n"
        "<b>Örnekler:</b>\n/transferara Haaland\n/oyuncu Vinicius",
        parse_mode="HTML"
    )


async def cmd_transferara(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        return await update.message.reply_text("Kullanım: /transferara &lt;oyuncu adı&gt;", parse_mode="HTML")
    results = search_player(query)
    if not results:
        return await update.message.reply_text(f"❌ <b>{query}</b> için sonuç bulunamadı.", parse_mode="HTML")
    msg = f"🔍 <b>Transfer Araması: \"{query}\"</b>\n\n"
    for r in results[:10]:
        p = r["player"]
        val = estimate_value(p)
        msg += f"<b>{p['name']}</b> | {p['position']} | OVR: {p['overall']} | {r['team']['emoji']} {r['team']['shortName']} | 💰 €{val}M\n"
    if len(results) > 10:
        msg += f"\n<i>{len(results)} sonuç, ilk 10 gösteriliyor</i>"
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_oyuncu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        return await update.message.reply_text("Kullanım: /oyuncu &lt;oyuncu adı&gt;", parse_mode="HTML")
    results = search_player(query)
    if not results:
        return await update.message.reply_text(f"❌ <b>{query}</b> bulunamadı.", parse_mode="HTML")
    p, team, league = results[0]["player"], results[0]["team"], results[0]["league"]
    val = estimate_value(p)
    await update.message.reply_text(
        f"👤 <b>{p['name']}</b>\n\n"
        f"🏃 Mevki: <b>{p['position']}</b>\n"
        f"🌍 Milliyet: {p['nationality']}\n"
        f"🎂 Yaş: {p['age']}\n"
        f"⭐ OVR: <b>{p['overall']}</b>\n"
        f"💰 Tahmini Değer: €{val}M\n"
        f"💵 Maaş: £{p['wage']//1000}K/hafta\n"
        f"🏟️ Takım: {team['emoji']} {team['name']}\n"
        f"🏆 Lig: {league['emoji']} {league['name']}",
        parse_mode="HTML"
    )


async def cmd_pazar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_players = []
    for league in get_leagues():
        for team in league["teams"]:
            for player in team["players"]:
                if 75 <= player["overall"] <= 85:
                    all_players.append({"player": player, "team": team, "league": league, "value": estimate_value(player)})
    market = random.sample(all_players, min(8, len(all_players)))
    msg = "💰 <b>Transfer Pazarı — Günlük Teklifler</b>\n\n"
    for item in market:
        p = item["player"]
        msg += f"<b>{p['name']}</b> ({p['position']}) OVR: {p['overall']}\n"
        msg += f"  {item['team']['emoji']} {item['team']['shortName']} | 💰 €{item['value']}M | 🌍 {p['nationality']}\n\n"
    msg += "<i>Detay için: /oyuncu &lt;isim&gt;</i>"
    await update.message.reply_text(msg, parse_mode="HTML")


# ── ADMİN Komutları ──────────────────────────────────────────────────────────

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ Yönetici yetkisi gerekli!")
    await update.message.reply_text(
        "⚙️ <b>Admin Komutları</b>\n\n"
        "/ligbaslat &lt;lig_id&gt; — Lig başlat\n"
        "/ligdurdur &lt;lig_id&gt; — Ligi durdur\n"
        "/ligsifirla &lt;lig_id&gt; — Ligi sıfırla\n"
        "/ligler — Aktif ligleri göster\n"
        "/adminpuan &lt;lig_id&gt; — Puan durumu\n"
        "/simule — Manuel maç simülasyonu\n"
        "/kanal — Bu kanalı duyuru kanalı yap\n\n"
        "<b>Lig ID'leri:</b>\n"
        "<code>premier_league</code> <code>la_liga</code> <code>bundesliga</code>\n"
        "<code>serie_a</code> <code>ligue_1</code> <code>eredivisie</code> <code>primeira_liga</code>",
        parse_mode="HTML"
    )


async def cmd_ligbaslat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ Yönetici yetkisi gerekli!")
    guild_id = str(update.effective_chat.id)
    if not context.args:
        leagues = get_leagues()
        msg = "📋 <b>Mevcut Ligler:</b>\n\n"
        for l in leagues:
            msg += f"{l['emoji']} <code>{l['id']}</code> — {l['name']}\n"
        msg += "\nKullanım: /ligbaslat &lt;lig_id&gt;"
        return await update.message.reply_text(msg, parse_mode="HTML")

    league_id = context.args[0].lower()
    existing = get_league_state(guild_id, league_id)
    if existing and existing.get("status") == "active":
        return await update.message.reply_text(
            f"⚠️ <b>{existing['leagueName']}</b> zaten aktif!\nDurdurmak için: /ligdurdur {league_id}",
            parse_mode="HTML"
        )
    try:
        state = init_league(guild_id, league_id)
        league_data = get_league_by_id(league_id)
        team_list = " | ".join(f"{t['emoji']} {t['name']}" for t in league_data["teams"])
        await update.message.reply_text(
            f"✅ <b>{league_data['emoji']} {state['leagueName']} Başlatıldı!</b>\n\n"
            f"🏟️ Takım: {len(league_data['teams'])} takım\n"
            f"📅 Toplam Hafta: {state['totalRounds']}\n"
            f"⚡ Otomatik: Her gün 18:00 ve 20:00 (TR)\n\n"
            f"<b>Takımlar:</b>\n{team_list}\n\n"
            f"📢 Duyurular için: /kanal",
            parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")


async def cmd_ligdurdur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ Yönetici yetkisi gerekli!")
    guild_id = str(update.effective_chat.id)
    if not context.args:
        return await update.message.reply_text("Kullanım: /ligdurdur &lt;lig_id&gt;", parse_mode="HTML")
    league_id = context.args[0].lower()
    state = get_league_state(guild_id, league_id)
    if not state:
        return await update.message.reply_text("❌ Bu lig bulunamadı veya başlatılmadı.")
    state["status"] = "stopped"
    save_league_state(guild_id, league_id, state)
    await update.message.reply_text(f"⏹️ <b>{state['leagueName']}</b> durduruldu.", parse_mode="HTML")


async def cmd_ligsifirla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ Yönetici yetkisi gerekli!")
    guild_id = str(update.effective_chat.id)
    if not context.args:
        return await update.message.reply_text("Kullanım: /ligsifirla &lt;lig_id&gt;", parse_mode="HTML")
    league_id = context.args[0].lower()
    guild_data = get_guild_data(guild_id)
    if league_id in guild_data.get("leagues", {}):
        del guild_data["leagues"][league_id]
        save_guild_data(guild_id, guild_data)
        await update.message.reply_text(f"🔄 <b>{league_id}</b> ligi sıfırlandı.", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ Lig bulunamadı.")


async def cmd_ligler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ Yönetici yetkisi gerekli!")
    guild_id = str(update.effective_chat.id)
    guild_data = get_guild_data(guild_id)
    active = list(guild_data.get("leagues", {}).values())
    if not active:
        leagues = get_leagues()
        msg = "📋 <b>Başlatılabilir Ligler:</b>\n\n"
        for l in leagues:
            msg += f"{l['emoji']} <code>{l['id']}</code> — {l['name']} ({len(l['teams'])} takım)\n"
        msg += "\n/ligbaslat &lt;id&gt; ile başlatabilirsiniz."
        return await update.message.reply_text(msg, parse_mode="HTML")

    msg = "🏆 <b>Aktif Ligler</b>\n\n"
    for state in active:
        emoji = "🟢" if state["status"] == "active" else "🔴"
        msg += f"{emoji} <b>{state['leagueName']}</b> — Hafta {state['currentRound']}/{state['totalRounds']}\n"
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_adminpuan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ Yönetici yetkisi gerekli!")
    guild_id = str(update.effective_chat.id)
    if not context.args:
        return await update.message.reply_text("Kullanım: /adminpuan &lt;lig_id&gt;", parse_mode="HTML")
    league_id = context.args[0].lower()
    state = get_league_state(guild_id, league_id)
    if not state:
        return await update.message.reply_text("❌ Bu lig bulunamadı.")
    sorted_teams = sorted(state["standings"].values(), key=lambda t: (-t["points"], -t["goalDiff"]))
    medals = ["🥇", "🥈", "🥉"]
    msg = f"📊 <b>{state['leagueName']} — Puan Durumu</b>\nHafta {state['currentRound']}/{state['totalRounds']}\n\n"
    for i, t in enumerate(sorted_teams):
        pos = medals[i] if i < 3 else f"<b>{i+1}.</b>"
        gd = f"+{t['goalDiff']}" if t["goalDiff"] >= 0 else str(t["goalDiff"])
        msg += f"{pos} <b>{t['teamName']}</b> — {t['points']}P | {t['played']}O {t['won']}G {t['drawn']}B {t['lost']}M | {t['goalsFor']}:{t['goalsAgainst']} ({gd})\n"
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_simule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ Yönetici yetkisi gerekli!")
    await update.message.reply_text("⏳ Maç simülasyonu başlıyor...")
    try:
        await simulate_match_day(context.application)
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")


async def cmd_kanal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ Yönetici yetkisi gerekli!")
    guild_id = str(update.effective_chat.id)
    set_announce_channel(guild_id, guild_id)
    await update.message.reply_text("✅ Bu kanal duyuru kanalı olarak ayarlandı! Maç sonuçları buraya gelecek.")


# ── MİSC Komutları ────────────────────────────────────────────────────────────

async def cmd_puan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    guild_id = str(update.effective_chat.id)
    if not context.args:
        leagues = get_leagues()
        msg = "📊 <b>Puan Durumu</b>\n\nLig belirtin:\n\n"
        for l in leagues:
            msg += f"{l['emoji']} <code>/puan {l['id']}</code> — {l['name']}\n"
        return await update.message.reply_text(msg, parse_mode="HTML")

    league_id = context.args[0].lower()
    state = get_league_state(guild_id, league_id)
    if not state:
        return await update.message.reply_text(
            f"❌ <b>{league_id}</b> ligi başlatılmamış.\nAdmin: /ligbaslat {league_id}", parse_mode="HTML"
        )
    sorted_teams = sorted(state["standings"].values(), key=lambda t: (-t["points"], -t["goalDiff"]))
    league_data = get_league_by_id(league_id)
    medals = ["🥇", "🥈", "🥉"]
    msg = f"{league_data.get('emoji', '🏆')} <b>{state['leagueName']} — Puan Durumu</b>\n📅 Hafta {state['currentRound']}/{state['totalRounds']}\n\n"
    for i, t in enumerate(sorted_teams):
        pos = medals[i] if i < 3 else f"{i+1}."
        gd = f"+{t['goalDiff']}" if t["goalDiff"] >= 0 else str(t["goalDiff"])
        msg += f"{pos} <b>{t['teamName']}</b> — <b>{t['points']}P</b>\n    {t['played']}O {t['won']}G {t['drawn']}B {t['lost']}M | {t['goalsFor']}:{t['goalsAgainst']} ({gd})\n"
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_sonuclar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    guild_id = str(update.effective_chat.id)
    log = get_match_log(guild_id, 10)
    if not log:
        return await update.message.reply_text("❌ Henüz hiç maç oynanmadı.")
    from datetime import datetime
    msg = "📋 <b>Son Maç Sonuçları</b>\n\n"
    for m in log:
        date = datetime.fromtimestamp(m["timestamp"]).strftime("%d.%m.%Y")
        w = "›" if m["homeGoals"] > m["awayGoals"] else "‹" if m["awayGoals"] > m["homeGoals"] else "="
        msg += f"<b>{m['homeTeam']} {m['homeGoals']}–{m['awayGoals']} {m['awayTeam']}</b> {w}  <i>{date}</i>\n"
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_fikstür(update: Update, context: ContextTypes.DEFAULT_TYPE):
    guild_id = str(update.effective_chat.id)
    if not context.args:
        leagues = get_leagues()
        msg = "📅 <b>Fikstür</b>\n\nLig belirtin:\n\n"
        for l in leagues:
            msg += f"{l['emoji']} <code>/fikstur {l['id']}</code> — {l['name']}\n"
        return await update.message.reply_text(msg, parse_mode="HTML")

    league_id = context.args[0].lower()
    state = get_league_state(guild_id, league_id)
    if not state:
        return await update.message.reply_text(f"❌ <b>{league_id}</b> ligi başlatılmamış.", parse_mode="HTML")
    league_data = get_league_by_id(league_id)
    if not league_data:
        return await update.message.reply_text("❌ Lig verisi bulunamadı.")

    next_round = state["currentRound"] + 1
    show_rounds = state["fixtures"][next_round - 1: next_round + 2]
    if not show_rounds:
        return await update.message.reply_text("🏁 Fikstür tamamlandı, maç kalmadı.")

    msg = f"{league_data['emoji']} <b>{state['leagueName']} — Fikstür</b>\nMevcut Hafta: {state['currentRound']}/{state['totalRounds']}\n\n"
    for rnd in show_rounds:
        is_next = rnd["round"] == next_round
        msg += f"<b>📅 Hafta {rnd['round']}{' (Sonraki)' if is_next else ''}</b>\n"
        for match in rnd["matches"]:
            ht = next((t for t in league_data["teams"] if t["id"] == match["home"]), None)
            at = next((t for t in league_data["teams"] if t["id"] == match["away"]), None)
            if ht and at:
                msg += f"  {ht['emoji']} {ht['shortName']} vs {at['shortName']} {at['emoji']}\n"
        msg += "\n"
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_yardim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ <b>Futbol Botu — Komutlar</b>\n\n"
        "👤 <b>Takım</b>\n"
        "/takim — Takım bilgisi\n"
        "/takimsec &lt;takım adı&gt; — Takım seç\n"
        "/kadro [takım adı] — Kadro\n"
        "/takimlar [lig_id] — Tüm takımlar\n\n"
        "🏋️ <b>Antrenman</b>\n"
        "/antrenman — Liste\n"
        "/antrenman kondisyon | teknik | taktik | gucantrenman | atismapraktik\n\n"
        "💰 <b>Transfer</b>\n"
        "/transfer — Menü\n"
        "/transferara &lt;oyuncu&gt; — Oyuncu ara\n"
        "/oyuncu &lt;oyuncu&gt; — Detay\n"
        "/pazar — Günlük pazar\n\n"
        "📊 <b>Lig</b>\n"
        "/puan &lt;lig_id&gt; — Puan durumu\n"
        "/sonuclar — Son maçlar\n"
        "/fikstur &lt;lig_id&gt; — Fikstür\n\n"
        "⚙️ <b>Admin</b>\n"
        "/ligbaslat &lt;lig_id&gt; — Lig başlat\n"
        "/ligdurdur | /ligsifirla | /ligler\n"
        "/adminpuan &lt;lig_id&gt; | /simule | /kanal\n\n"
        "🌍 <b>Lig ID'leri:</b>\n"
        "<code>premier_league</code> <code>la_liga</code> <code>bundesliga</code>\n"
        "<code>serie_a</code> <code>ligue_1</code> <code>eredivisie</code> <code>primeira_liga</code>\n\n"
        "<i>⚡ Maçlar her gün 18:00 ve 20:00'de otomatik oynanır!</i>",
        parse_mode="HTML"
    )
