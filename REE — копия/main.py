"""
main.py — Discord бот: профиль, магазин ролей, ГС-активность, золото.

Команды: /profile /top /shop /balance /craft
"""

import asyncio
import io
import os
import random
import time
from collections import defaultdict

import discord
from discord import app_commands
from dotenv import load_dotenv

import store
from api import start_api
from profile_card import generate_profile_card
from shop_card import generate_shop_card
from craft_card import generate_craft_card
from achievement_showcase import generate_achievement_showcase, resolve_profile_image
from panel_layout import build_home_layout, build_text_layout, wrap_interactive_layout

load_dotenv()

# ── Настройки XP ──────────────────────────────────────────────────────
VOICE_TICK_SEC  = 10
VOICE_XP_MIN    = 10
VOICE_XP_MAX    = 15
MSG_XP_MIN      = 1
MSG_XP_MAX      = 2
MSG_XP_COOLDOWN = 60

# ── Настройки Gold ────────────────────────────────────────────────────
GOLD_PER_LEVELUP  = 100
GOLD_PER_MSG      = 1
GOLD_PER_5MIN_VC  = 10    # каждые 5 минут в ГС

# ── Фон карточек ──────────────────────────────────────────────────────
import glob as _glob
_profile_dir = os.path.join(os.path.dirname(__file__), "profile")
_bg_files    = _glob.glob(os.path.join(_profile_dir, "*.png")) + \
               _glob.glob(os.path.join(_profile_dir, "*.jpg"))
BG_IMAGE = _bg_files[0] if _bg_files else None
PANEL_MAIN_IMAGE = resolve_profile_image("profiile.png") or resolve_profile_image("profiile")


def _panel_image_file() -> discord.File | None:
    if PANEL_MAIN_IMAGE and os.path.isfile(PANEL_MAIN_IMAGE):
        return discord.File(PANEL_MAIN_IMAGE, "profiile.png")
    return None

# Достижения панели (картинки в папке profile/)
WHATTHIS_CHANNEL_ID = 1352962802222108755
WHATTHIS_REQUIRED_SEC = 72 * 3600

PANEL_ACHIEVEMENTS = [
    {
        "id":       "objora",
        "name":     "ОБЖОРА",
        "image":    "objora",
        "type":     "craft_count",
        "required": 5,
    },
    {
        "id":         "whatthis",
        "name":       "ЧТО ЭТО ?",
        "image":      "whatthis",
        "type":         "channel_voice",
        "channel_id": WHATTHIS_CHANNEL_ID,
        "required_sec": WHATTHIS_REQUIRED_SEC,
    },
    {
        "id":    "vinovnyy",
        "name":  "ВИНОВНЫЙ",
        "image": "vinovat",
        "type":  "secret",
    },
]

ACHIEVEMENT_VOICE_CHANNELS = {WHATTHIS_CHANNEL_ID}

# ── Магазин ролей ─────────────────────────────────────────────────────
SHOP_ROLES = [
    {"role_id": 1425890278287343666, "name": "Nochnoj Typchik", "price": 66,    "temp_days": None},
    {"role_id": 1424344060344274995, "name": "ARKHANGEL",       "price": 100,   "temp_days": None},
    {"role_id": 1454250788217032776, "name": "STATUS-CU",       "price": 300,   "temp_days": None},
    {"role_id": 1454251098045943829, "name": "STATUS-SILVER",   "price": 1000,  "temp_days": None},
    {"role_id": 1454251017951641771, "name": "STATUS-GOLD",     "price": 2000,  "temp_days": None},
    {"role_id": 1429088689945837699, "name": "STATUS-TITAN",    "price": 5000,  "temp_days": None},
    {"role_id": 1473785315352117370, "name": "S W A G",         "price": 12000, "temp_days": None},
    {"role_id": 1461821621278081146, "name": "ANARHIST",        "price": 3000,  "temp_days": 7},
]
ITEMS_PER_PAGE = 3

# ── Крафт артефактов ──────────────────────────────────────────────────
CRAFT_CHANNEL_ID = 1454250570259894423
ARTIFACT_LABELS = {"opal": "Opal", "ruby": "Ruby", "diamond": "Diamond"}

CRAFT_RECIPES = [
    {"role_id": 1461821090052702268, "name": "Really ?", "cost": {"opal": 50}},
    {"role_id": 1461821977730875402, "name": "Space",    "cost": {"opal": 5, "diamond": 15}},
    {"role_id": 1461823093914865664, "name": "Moon",     "cost": {"opal": 10, "ruby": 5}},
]

# ── DURKA стрик (отдельно от достижений панели) ───────────────────────
DURKA_CHANNEL_ID   = WHATTHIS_CHANNEL_ID
DURKA_REQUIRED_SEC = 48 * 3600

# ── Статусы по ролям ─────────────────────────────────────────────────
# Порядок важен: первое совпадение = высший приоритет
STATUS_ROLES = [
    (1229484726729965598, "MAIN OWNER"),
    (1273991826843504682, "OWNER"),
    (1385303846473171086, "KURATOR"),
    (1453121460171313273, "MODERATOR"),
    (1453122157835190312, "MODERATOR"),
]

def _get_member_status(member) -> str | None:
    """Возвращает статус по ролям участника или None."""
    if not hasattr(member, "roles"):
        return None
    role_ids = {r.id for r in member.roles}
    for role_id, status_name in STATUS_ROLES:
        if role_id in role_ids:
            return status_name
    return None

# ── Логирование ─────────────────────────────────────────────────────
LOG_CHANNEL_ID      = 1426706105387712636
MOD_ROLE_IDS        = [1453121460171313273, 1453122157835190312]
ADMIN_USER_ID       = 1055143506055807056   # единственный админ

# ── Состояния в памяти ────────────────────────────────────────────────
_msg_xp_cd: dict[tuple, float]   = defaultdict(float)   # кулдаун XP/gold за сообщение
_voice_gold_acc: dict[tuple, float] = defaultdict(float) # накопленные секунды для gold ГС

# ── Discord ───────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.guilds        = True
intents.voice_states  = True
intents.members       = True
intents.messages      = True
intents.message_content = True

client = discord.Client(intents=intents)
tree   = app_commands.CommandTree(client)


# ════════════════════════════════════════════════════════════════════
#   Error handler
# ════════════════════════════════════════════════════════════════════

@tree.error
async def on_app_command_error(interaction, error):
    if isinstance(error, app_commands.CommandInvokeError):
        if isinstance(error.original, discord.NotFound):
            return
    print(f"[CMD ERR] {error}")


# ════════════════════════════════════════════════════════════════════
#   Голосовой тик
# ════════════════════════════════════════════════════════════════════

async def _voice_tick():
    now       = int(time.time())
    all_users = store.load_all()

    for guild in client.guilds:
        try:
            in_voice: set[int] = set()
            for ch in guild.voice_channels:
                for m in ch.members:
                    if not m.bot:
                        in_voice.add(m.id)
                        if ch.id in ACHIEVEMENT_VOICE_CHANNELS:
                            store.add_channel_voice_time(
                                guild.id, m.id, ch.id, VOICE_TICK_SEC
                            )

            prefix = f"{guild.id}_"

            # Кто вышел — фиксируем время
            for key, u in list(all_users.items()):
                if not key.startswith(prefix):
                    continue
                uid = u.get("userId")
                if uid and u.get("lastVoiceJoin") and uid not in in_voice:
                    elapsed = now - u["lastVoiceJoin"]
                    if elapsed > 0:
                        store.add_voice_time(guild.id, uid, elapsed)
                        xp = int((elapsed / 60) * random.randint(VOICE_XP_MIN, VOICE_XP_MAX))
                        if xp > 0:
                            _add_xp_with_levelup(guild.id, uid, xp)
                        _grant_voice_artifacts(guild.id, uid, elapsed)
                    store.clear_voice_join(guild.id, uid)

            # Кто в канале — начисляем тик
            for uid in in_voice:
                store.get_or_create(guild.id, uid)
                store.add_voice_time(guild.id, uid, VOICE_TICK_SEC)
                xp = int((VOICE_TICK_SEC / 60) * random.randint(VOICE_XP_MIN, VOICE_XP_MAX))
                if xp > 0:
                    _add_xp_with_levelup(guild.id, uid, xp)
                vch_id = None
                for ch in guild.voice_channels:
                    if uid in {m.id for m in ch.members if not m.bot}:
                        vch_id = ch.id
                        break
                store.set_voice_join(guild.id, uid, now, vch_id)

                _grant_voice_artifacts(guild.id, uid, VOICE_TICK_SEC)

                # Gold за каждые 5 минут в ГС
                acc_key = (guild.id, uid)
                _voice_gold_acc[acc_key] += VOICE_TICK_SEC
                while _voice_gold_acc[acc_key] >= 300:
                    store.add_gold(guild.id, uid, GOLD_PER_5MIN_VC)
                    _voice_gold_acc[acc_key] -= 300

        except Exception as e:
            print(f"[voice_tick] {guild.name}: {e}")
        await asyncio.sleep(0.05)


def _add_xp_with_levelup(guild_id: int, user_id: int, amount: int):
    """Добавляет XP и начисляет gold если был level up."""
    old_xp  = store.get_or_create(guild_id, user_id).get("xp", 0)
    old_lvl = store.xp_to_level(old_xp)
    store.add_xp(guild_id, user_id, amount)
    new_xp  = store.get_or_create(guild_id, user_id).get("xp", 0)
    new_lvl = store.xp_to_level(new_xp)
    if new_lvl > old_lvl:
        bonus = (new_lvl - old_lvl) * GOLD_PER_LEVELUP
        store.add_gold(guild_id, user_id, bonus)


def _grant_voice_artifacts(guild_id: int, user_id: int, seconds: int) -> list[str]:
    return store.add_artifact_voice_seconds(guild_id, user_id, seconds)


# ════════════════════════════════════════════════════════════════════
#   Events
# ════════════════════════════════════════════════════════════════════

async def _sync_slash_commands():
    synced = await tree.sync()
    names = sorted(c.name for c in synced)
    print(f"[OK] Global slash commands ({len(names)}): {', '.join(names) or 'none'}")
    guild_id = (os.getenv("DISCORD_GUILD_ID") or "").strip()
    if guild_id.isdigit():
        guild_obj = discord.Object(id=int(guild_id))
        tree.copy_global_to(guild=guild_obj)
        await tree.sync(guild=guild_obj)
        print(f"[OK] Guild slash sync for {guild_id} (instant update)")


@client.event
async def on_ready():
    print(f"[OK] Bot: {client.user} (ID: {client.user.id})")
    client.add_view(PanelPersistentLayoutView())
    client.add_view(AchievementPickPersistentView())
    client.add_view(RolesApplyView())   # persistent: dropdown always works
    await _sync_slash_commands()

    # ── Восстановление ГС-сессий после перезапуска ─────────────────
    # Если бот упал пока люди были в ГС — lastVoiceJoin остался в JSON.
    # Зачисляем потерянное время и переставляем метку на "сейчас".
    now = int(time.time())
    all_users = store.load_all()
    for guild in client.guilds:
        in_voice: set[int] = set()
        for ch in guild.voice_channels:
            for m in ch.members:
                if not m.bot:
                    in_voice.add(m.id)

        prefix = f"{guild.id}_"
        for key, u in all_users.items():
            if not key.startswith(prefix):
                continue
            uid = u.get("userId")
            lv  = u.get("lastVoiceJoin")
            if not uid or not lv:
                continue
            elapsed = now - lv
            if elapsed < 0:
                elapsed = 0
            if uid in in_voice:
                # Пользователь ВСЁ ЕЩЁ в ГС → зачисляем разрыв и обновляем метку
                if elapsed > 0:
                    store.add_voice_time(guild.id, uid, elapsed)
                    xp = int((elapsed / 60) * random.randint(VOICE_XP_MIN, VOICE_XP_MAX))
                    if xp > 0:
                        _add_xp_with_levelup(guild.id, uid, xp)
                    _grant_voice_artifacts(guild.id, uid, elapsed)
                store.set_voice_join(guild.id, uid, now)
                print(f"[restore] {uid} in voice, +{elapsed}s")
            else:
                # Пользователь уже вышел → фиксируем и закрываем сессию
                if elapsed > 0:
                    store.add_voice_time(guild.id, uid, elapsed)
                    xp = int((elapsed / 60) * random.randint(VOICE_XP_MIN, VOICE_XP_MAX))
                    if xp > 0:
                        _add_xp_with_levelup(guild.id, uid, xp)
                    _grant_voice_artifacts(guild.id, uid, elapsed)
                store.clear_voice_join(guild.id, uid)
                print(f"[restore] {uid} left voice, +{elapsed}s")

    print("[OK] Voice sessions restored")

    async def voice_loop():
        await asyncio.sleep(VOICE_TICK_SEC)
        while True:
            await _voice_tick()
            await asyncio.sleep(VOICE_TICK_SEC)

    async def temp_role_loop():
        while True:
            await asyncio.sleep(60)
            try:
                now = time.time()
                for tr in store.get_all_temp_roles():
                    if tr["expiresAt"] <= now:
                        g = client.get_guild(tr["guildId"])
                        if g:
                            m = g.get_member(tr["userId"])
                            r = g.get_role(tr["roleId"])
                            if m and r and r in m.roles:
                                await m.remove_roles(r, reason="Temp role expired")
                        store.remove_temp_role(tr["guildId"], tr["userId"], tr["roleId"])
            except Exception as e:
                print(f"[temp_roles] {e}")

    asyncio.create_task(voice_loop())
    asyncio.create_task(temp_role_loop())
    asyncio.create_task(start_api())
    print(f"[OK] Voice tick every {VOICE_TICK_SEC}s | Temp role check every 60s | API started")


@client.event
async def on_member_join(member: discord.Member):
    if not member.bot:
        store.get_or_create(member.guild.id, member.id)
        await bot_log(f"Member joined: {member} (ID: {member.id})")


@client.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    now = int(time.time())
    gid, uid = member.guild.id, member.id
    prev_ch = before.channel
    next_ch = after.channel

    # ── Общий учёт времени ──────────────────────────────────────────
    if prev_ch and not next_ch:
        # Вышел из войса полностью
        u = store.get_or_create(gid, uid)
        if u.get("lastVoiceJoin"):
            elapsed = now - u["lastVoiceJoin"]
            if elapsed > 0:
                store.add_voice_time(gid, uid, elapsed)
                xp = int((elapsed / 60) * random.randint(VOICE_XP_MIN, VOICE_XP_MAX))
                if xp > 0:
                    _add_xp_with_levelup(gid, uid, xp)
                _grant_voice_artifacts(gid, uid, elapsed)
                if prev_ch.id in ACHIEVEMENT_VOICE_CHANNELS:
                    store.add_channel_voice_time(gid, uid, prev_ch.id, elapsed)
        store.clear_voice_join(gid, uid)
        _voice_gold_acc.pop((gid, uid), None)
    elif not prev_ch and next_ch:
        store.get_or_create(gid, uid)
        store.set_voice_join(gid, uid, now, next_ch.id)
    elif prev_ch and next_ch and prev_ch.id != next_ch.id:
        u = store.get_or_create(gid, uid)
        if u.get("lastVoiceJoin"):
            elapsed = now - u["lastVoiceJoin"]
            if elapsed > 0 and prev_ch.id in ACHIEVEMENT_VOICE_CHANNELS:
                store.add_channel_voice_time(gid, uid, prev_ch.id, elapsed)
        store.set_voice_join(gid, uid, now, next_ch.id)

    # ── Отслеживание стрика DURKA ────────────────────────────────────
    was_in_durka  = prev_ch and prev_ch.id == DURKA_CHANNEL_ID
    now_in_durka  = next_ch and next_ch.id == DURKA_CHANNEL_ID

    if now_in_durka and not was_in_durka:
        # Зашёл в DURKA — ставим метку начала стрика
        store.set_durka_join(gid, uid, now)
    elif was_in_durka and not now_in_durka:
        # Вышел из DURKA — сбрасываем стрик (прерывание = сброс)
        store.clear_durka_join(gid, uid)


# ════════════════════════════════════════════════════════════════════
#   Roles Apply View  (/roles — persistent dropdown)
# ════════════════════════════════════════════════════════════════════

ROLES_APPLY_CHANNEL_ID = 1453292095812010035

_ROLE_LABELS = {
    "admin":     "Администратор",
    "senior_mod": "СТР.Модератор",
    "moderator": "Модератор",
    "creator":   "Креатор",
    "support":   "Саппорт",
}


def _make_roles_embed(guild_name: str | None = None) -> discord.Embed:
    title_name = (guild_name or "REE").upper()[:24]
    embed = discord.Embed(
        title=f"МЕНЮ {title_name}",
        description="*Выберите раздел , который хотите открыть*",
        color=0x2B2D31,
    )
    return embed


async def _publish_roles(channel: discord.abc.Messageable, guild: discord.Guild):
    guild_name = guild.name
    embed = _make_roles_embed(guild_name)
    panel_file = _panel_image_file()
    if panel_file:
        embed.set_image(url="attachment://profiile.png")
    await channel.send(
        embed=embed,
        files=[panel_file] if panel_file else [],
        view=RolesApplyView(),
    )


class RolesApplySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Администратор", value="admin", emoji="👑",
                description="Подать заявку на должность Администратора",
            ),
            discord.SelectOption(
                label="СТР.Модератор", value="senior_mod", emoji="🛡️",
                description="Подать заявку на должность СТР.Модератора",
            ),
            discord.SelectOption(
                label="Модератор", value="moderator", emoji="🔨",
                description="Подать заявку на должность Модератора",
            ),
            discord.SelectOption(
                label="Креатор", value="creator", emoji="🎨",
                description="Подать заявку на должность Креатора",
            ),
            discord.SelectOption(
                label="Саппорт", value="support", emoji="🎧",
                description="Подать заявку на должность Саппорта",
            ),
        ]
        super().__init__(
            placeholder="Выберите раздел меню",
            custom_id="roles_apply_select",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        chosen = _ROLE_LABELS.get(self.values[0], self.values[0])
        user   = interaction.user

        # ── ЛС пользователю ──────────────────────────────────────────
        dm_embed = discord.Embed(
            title="✅  Заявка принята!",
            description=(
                f"Ваша заявка на должность **{chosen}** была **принята**.\n\n"
                "Скоро с вами свяжутся и проконсультируют.\n"
                "Ожидайте — рассмотрение может занять до **24 часов**."
            ),
            color=0x2ECC71,
        )
        dm_embed.set_footer(text="Спасибо за интерес к команде!")
        try:
            dm = await user.create_dm()
            await dm.send(embed=dm_embed)
        except Exception:
            pass   # ЛС закрыты — игнорируем

        # ── Уведомление в канал персонала ────────────────────────────
        notify_ch = interaction.client.get_channel(ROLES_APPLY_CHANNEL_ID)
        if notify_ch:
            notify_embed = discord.Embed(
                title="📥  Новая заявка на должность",
                description=(
                    f"{user.mention} подал(а) запрос на **{chosen}**."
                ),
                color=0xB22222,
            )
            notify_embed.set_thumbnail(url=user.display_avatar.url)
            notify_embed.set_footer(text=f"ID: {user.id}")
            await notify_ch.send(embed=notify_embed)

        await interaction.response.send_message(
            f"✅ Ваша заявка на **{chosen}** отправлена! Проверьте личные сообщения.",
            ephemeral=True,
        )


class RolesApplyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RolesApplySelect())


@client.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    # ── !admin — админ-панель ───────────────────────────────────────────────
    if message.content.strip().lower().startswith("!admin"):
        if message.author.id != ADMIN_USER_ID:
            await message.reply("У вас нет доступа к этой команде.", delete_after=5)
            return
        await _handle_admin(message)
        return

    # ── !moder — панель модератора ────────────────────────────────────
    if message.content.strip().lower() == "!moder":
        # Проверяем роль модератора
        member_roles = {r.id for r in message.author.roles}
        is_mod = any(rid in member_roles for rid in MOD_ROLE_IDS)
        # Также разрешаем OWNER/KURATOR
        is_mod = is_mod or any(
            rid in member_roles
            for rid, _ in STATUS_ROLES
            if _ in ("MAIN OWNER", "OWNER", "KURATOR")
        )
        if not is_mod:
            await message.reply("You don't have permission.", delete_after=5)
            return
        view  = ModerPanelView(message.guild.id)
        embed = discord.Embed(
            title="MODERATOR PANEL",
            description="Click REPORTS to manage pending reports.",
            color=0xFF3333,
        )
        await message.channel.send(embed=embed, view=view)
        return

    # ── !panel — панель сервера ─────────────────────────────────────
    if message.content.strip().lower().startswith("!panel"):
        if not message.author.guild_permissions.manage_messages:
            await message.reply(
                "Нет доступа. Нужно право «Управление сообщениями».",
                delete_after=8,
            )
            return
        try:
            await _publish_panel(message.channel, message.guild)
        except discord.Forbidden:
            await message.reply("Нет прав отправить панель в этот канал.", delete_after=8)
        except Exception as e:
            print(f"[panel] {e}")
            await message.reply("Не удалось опубликовать панель.", delete_after=8)
        return

    if message.content.strip().lower().startswith("!profile"):
        try:
            png, view = await _build_profile(message.guild, message.author)
            await message.channel.send(
                file=discord.File(io.BytesIO(png), "profile.png"), view=view
            )
        except discord.NotFound:
            pass
        return

    # ── !shop — магазин ролей ───────────────────────────────────────
    if message.content.strip().lower().startswith("!shop"):
        member = message.guild.get_member(message.author.id) or message.author
        view = ShopView(message.guild, member)
        try:
            png = await view._render()
            await message.channel.send(file=discord.File(io.BytesIO(png), "shop.png"), view=view)
        except discord.NotFound:
            pass
        return

    # ── !balance — баланс золота ───────────────────────────────────────
    if message.content.strip().lower().startswith("!balance"):
        gold = store.get_gold(message.guild.id, message.author.id)
        embed = discord.Embed(title="Gold Balance", color=0xFFBE1E)
        embed.add_field(name="Gold", value=f"**{gold} G**")
        embed.set_footer(text="+1G/msg | +10G/5min voice | +100G/level up")
        await message.channel.send(embed=embed)
        return

    # ── !top — топ по уровню ───────────────────────────────────────
    if message.content.strip().lower().startswith("!top"):
        parts = message.content.strip().split()
        count = 10
        if len(parts) > 1 and parts[1].isdigit():
            count = int(parts[1])
        limit = min(10, max(1, count))
        members = store.get_top(message.guild.id, limit)
        lines = []
        for i, u in enumerate(members, 1):
            m = message.guild.get_member(u["userId"])
            name = m.display_name if m else f"<@{u['userId']}>"
            lvl = store.xp_to_level(u.get("xp", 0))
            gold = u.get("gold", 0)
            icon = {1: "#1", 2: "#2", 3: "#3"}.get(i, f"#{i}")
            lines.append(f"**{icon}** {name} — LVL **{lvl}**  |  {gold}G")
        embed = discord.Embed(title="TOP by Level",
                              description="\n".join(lines) if lines else "Empty.",
                              color=0x7850FF)
        await message.channel.send(embed=embed)
        return

    # ── XP и золото за сообщение ──────────────────────────────────────
    gid, uid = message.guild.id, message.author.id
    now = time.time()
    cd_key = (gid, uid)
    if now - _msg_xp_cd[cd_key] >= MSG_XP_COOLDOWN:
        xp = random.randint(MSG_XP_MIN, MSG_XP_MAX)
        _add_xp_with_levelup(gid, uid, xp)
        store.add_gold(gid, uid, GOLD_PER_MSG)
        _msg_xp_cd[cd_key] = now


# ════════════════════════════════════════════════════════════════════
#   Admin handler
# ════════════════════════════════════════════════════════════════════

_ADMIN_HELP = (
    "**!admin** — управление XP и уровнями\n\n"
    "`!admin xp add @user <сумма>` — выдать XP\n"
    "`!admin xp remove @user <сумма>` — отнять XP\n"
    "`!admin level add @user <кол-во>` — выдать уровни\n"
    "`!admin level remove @user <кол-во>` — отнять уровни\n"
    "`!admin stats @user` — посмотреть стату пользователя"
)

async def _handle_admin(message: discord.Message):
    parts = message.content.strip().split()
    # parts[0] = '!admin'

    async def _err(text: str):
        await message.reply(f"❌ {text}", delete_after=10)

    async def _ok(text: str):
        await message.reply(f"✅ {text}")

    if len(parts) < 2:
        embed = discord.Embed(title="ADMIN PANEL", description=_ADMIN_HELP, color=0xFF6600)
        await message.reply(embed=embed)
        return

    sub = parts[1].lower()

    # ── !admin stats @user ──────────────────────────────────────────
    if sub == "stats":
        if not message.mentions:
            await _err("Укажи пользователя: `!admin stats @user`")
            return
        target = message.mentions[0]
        u = store.get_or_create(message.guild.id, target.id)
        xp  = u.get("xp", 0)
        lvl = store.xp_to_level(xp)
        gold = u.get("gold", 0)
        vs  = store.format_voice_time(u.get("voiceSeconds", 0))
        rank = store.get_rank(message.guild.id, target.id)
        embed = discord.Embed(title=f"Stats: {target.display_name}", color=0x7850FF)
        embed.add_field(name="Level",   value=str(lvl),  inline=True)
        embed.add_field(name="XP",      value=str(xp),   inline=True)
        embed.add_field(name="Gold",    value=f"{gold}G", inline=True)
        embed.add_field(name="GS Time", value=vs,         inline=True)
        embed.add_field(name="Rank",    value=f"#{rank}", inline=True)
        await message.reply(embed=embed)
        return

    # ── !admin xp/level add/remove @user <amount> ──────────────────
    if sub not in ("xp", "level") or len(parts) < 5:
        embed = discord.Embed(title="ADMIN PANEL", description=_ADMIN_HELP, color=0xFF6600)
        await message.reply(embed=embed)
        return

    action = parts[2].lower()
    if action not in ("add", "remove"):
        await _err("Действие должно быть `add` или `remove`.")
        return

    if not message.mentions:
        await _err("Укажи пользователя через @mention.")
        return

    target = message.mentions[0]
    try:
        amount = int(parts[4])
        if amount <= 0:
            raise ValueError
    except (ValueError, IndexError):
        await _err("Укажи корректное положительное число.")
        return

    gid = message.guild.id
    uid = target.id
    store.get_or_create(gid, uid)

    if sub == "xp":
        if action == "add":
            _add_xp_with_levelup(gid, uid, amount)
            u = store.get_or_create(gid, uid)
            await _ok(f"Выдал **{amount} XP** → {target.mention} (всего: {u.get('xp',0)} XP, LVL {store.xp_to_level(u.get('xp',0))})")
        else:
            u = store.get_or_create(gid, uid)
            cur = u.get("xp", 0)
            new_xp = max(0, cur - amount)
            diff = cur - new_xp
            store.add_xp(gid, uid, -diff)
            u2 = store.get_or_create(gid, uid)
            await _ok(f"Снял **{diff} XP** → {target.mention} (осталось: {u2.get('xp',0)} XP, LVL {store.xp_to_level(u2.get('xp',0))})")

    elif sub == "level":
        u = store.get_or_create(gid, uid)
        cur_lvl = store.xp_to_level(u.get("xp", 0))
        if action == "add":
            xp_to_add = amount * store.XP_PER_LEVEL
            _add_xp_with_levelup(gid, uid, xp_to_add)
            new_lvl = store.xp_to_level(store.get_or_create(gid, uid).get("xp", 0))
            await _ok(f"Выдал **{amount} ур.** → {target.mention} (был {cur_lvl} → стал {new_lvl})")
        else:
            lvls_to_remove = min(amount, cur_lvl)
            xp_to_remove = lvls_to_remove * store.XP_PER_LEVEL
            cur_xp = u.get("xp", 0)
            store.add_xp(gid, uid, -min(xp_to_remove, cur_xp))
            new_lvl = store.xp_to_level(store.get_or_create(gid, uid).get("xp", 0))
            await _ok(f"Снял **{lvls_to_remove} ур.** → {target.mention} (был {cur_lvl} → стал {new_lvl})")


# ════════════════════════════════════════════════════════════════════
#   Shop View
# ════════════════════════════════════════════════════════════════════

class ShopView(discord.ui.View):
    def __init__(self, guild: discord.Guild, user: discord.Member, from_panel: bool = False):
        super().__init__(timeout=None if from_panel else 180)
        self.guild      = guild
        self.user       = user
        self.from_panel = from_panel
        self.page       = 0
        self.total      = (len(SHOP_ROLES) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        self._rebuild()

    def _page_items(self):
        s = self.page * ITEMS_PER_PAGE
        return SHOP_ROLES[s:s + ITEMS_PER_PAGE]

    def _rebuild(self):
        self.clear_items()
        # Навигация
        prev = discord.ui.Button(label="<< Prev", style=discord.ButtonStyle.secondary,
                                 disabled=(self.page == 0), row=0)
        prev.callback = self._prev
        self.add_item(prev)

        pg_btn = discord.ui.Button(label=f"Page {self.page+1}/{self.total}",
                                   style=discord.ButtonStyle.secondary, disabled=True, row=0)
        self.add_item(pg_btn)

        nxt = discord.ui.Button(label="Next >>", style=discord.ButtonStyle.secondary,
                                disabled=(self.page == self.total - 1), row=0)
        nxt.callback = self._next
        self.add_item(nxt)

        # Кнопки покупки
        for i, item in enumerate(self._page_items()):
            role  = self.guild.get_role(item["role_id"])
            name  = item.get("name") or (role.name[:20] if role else f"Role #{self.page*ITEMS_PER_PAGE+i+1}")
            label = f"#{self.page*ITEMS_PER_PAGE+i+1} Buy - {item['price']}G"
            btn   = discord.ui.Button(label=label, style=discord.ButtonStyle.success, row=i+1)
            btn.callback = self._make_buy(item, role, name)
            self.add_item(btn)

        if self.from_panel:
            menu = PanelSelectMenu()
            menu.row = 4
            self.add_item(menu)

    async def _render(self) -> bytes:
        items_data = []
        for i, item in enumerate(self._page_items()):
            role  = self.guild.get_role(item["role_id"])
            name  = item.get("name") or (role.name if role else f"Role #{self.page*ITEMS_PER_PAGE+i+1}")
            owned = role in self.user.roles if role else False
            color = role.color.value if role else 0
            dur   = f"{item['temp_days']} days" if item.get("temp_days") else None
            items_data.append({"name": name, "price": item["price"],
                               "duration": dur, "owned": owned, "color": color})
        gold = store.get_gold(self.guild.id, self.user.id)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, generate_shop_card, items_data, self.page, self.total, gold, BG_IMAGE
        )

    async def _shop_edit(self, interaction: discord.Interaction, png: bytes):
        file = discord.File(io.BytesIO(png), "shop.png")
        if self.from_panel:
            layout = wrap_interactive_layout(
                "Магазин", "Покупка ролей за золото", "shop.png",
                self, 0xFFBE1E, PanelSelectMenu(),
            )
            await _panel_edit(interaction, view=layout, file=file)
        else:
            await interaction.edit_original_response(attachments=[file], view=self)

    async def _prev(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except discord.NotFound:
            return
        self.page -= 1
        self._rebuild()
        await self._shop_edit(interaction, await self._render())

    async def _next(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except discord.NotFound:
            return
        self.page += 1
        self._rebuild()
        await self._shop_edit(interaction, await self._render())

    def _make_buy(self, item: dict, role, name: str):
        async def callback(interaction: discord.Interaction):
            try:
                await interaction.response.defer(ephemeral=not self.from_panel)
            except discord.NotFound:
                return

            if interaction.user.id != self.user.id:
                await interaction.followup.send("This shop is not yours!", ephemeral=True)
                return

            member = self.guild.get_member(interaction.user.id)
            if not member:
                await interaction.followup.send("Cannot find you in guild.", ephemeral=True)
                return

            # Уже есть постоянно?
            if role and role in member.roles and not item.get("temp_days"):
                await interaction.followup.send(
                    f"You already have **{name}**!", ephemeral=True)
                return

            # Списываем gold
            if not store.spend_gold(self.guild.id, self.user.id, item["price"]):
                gold = store.get_gold(self.guild.id, self.user.id)
                await interaction.followup.send(
                    f"Not enough gold! You have **{gold}G**, need **{item['price']}G**.",
                    ephemeral=True)
                return

            # Выдаём роль
            if role:
                try:
                    await member.add_roles(role, reason="Shop purchase")
                except discord.Forbidden:
                    store.add_gold(self.guild.id, self.user.id, item["price"])  # refund
                    await interaction.followup.send(
                        "No permission to give role. Gold refunded.", ephemeral=True)
                    return

            # Сохраняем временную роль
            if item.get("temp_days") and role:
                expires = time.time() + item["temp_days"] * 86400
                store.set_temp_role(self.guild.id, self.user.id, item["role_id"], expires)
                msg = f"Bought **{name}** for **{item['price']}G**! (expires in {item['temp_days']} days)"
            else:
                msg = f"Bought **{name}** for **{item['price']}G**!"

            gold_left = store.get_gold(self.guild.id, self.user.id)
            await interaction.followup.send(
                f"{msg}\nBalance: **{gold_left}G**", ephemeral=True)

            self._rebuild()
            png = await self._render()
            try:
                if self.from_panel:
                    layout = wrap_interactive_layout(
                        "Магазин", "Покупка ролей за золото", "shop.png",
                        self, 0xFFBE1E, PanelSelectMenu(),
                    )
                    await interaction.message.edit(
                        attachments=[discord.File(io.BytesIO(png), "shop.png")],
                        embed=None,
                        content=None,
                        view=layout,
                    )
                else:
                    await interaction.edit_original_response(
                        attachments=[discord.File(io.BytesIO(png), "shop.png")], view=self
                    )
            except Exception:
                pass
        return callback


# ════════════════════════════════════════════════════════════════════
#   Craft View
# ════════════════════════════════════════════════════════════════════

class CraftView(discord.ui.View):
    def __init__(self, guild: discord.Guild, user: discord.Member, from_panel: bool = False):
        super().__init__(timeout=None if from_panel else 180)
        self.guild      = guild
        self.user       = user
        self.from_panel = from_panel
        self.page       = 0
        self.total      = (len(CRAFT_RECIPES) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        self._rebuild()

    def _page_items(self):
        s = self.page * ITEMS_PER_PAGE
        return CRAFT_RECIPES[s:s + ITEMS_PER_PAGE]

    def _rebuild(self):
        self.clear_items()
        prev = discord.ui.Button(label="<< Prev", style=discord.ButtonStyle.secondary,
                                 disabled=(self.page == 0), row=0)
        prev.callback = self._prev
        self.add_item(prev)

        pg_btn = discord.ui.Button(label=f"Page {self.page+1}/{self.total}",
                                   style=discord.ButtonStyle.secondary, disabled=True, row=0)
        self.add_item(pg_btn)

        nxt = discord.ui.Button(label="Next >>", style=discord.ButtonStyle.secondary,
                                disabled=(self.page == self.total - 1), row=0)
        nxt.callback = self._next
        self.add_item(nxt)

        for i, item in enumerate(self._page_items()):
            role = self.guild.get_role(item["role_id"])
            name = item.get("name") or (role.name[:16] if role else f"#{self.page*ITEMS_PER_PAGE+i+1}")
            cost_str = store.format_artifact_cost(item["cost"])
            label = f"Craft: {cost_str}"[:80]
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.success, row=i + 1)
            btn.callback = self._make_craft(item, role, name)
            self.add_item(btn)

        if self.from_panel:
            menu = PanelSelectMenu()
            menu.row = 4
            self.add_item(menu)

    async def _render(self) -> bytes:
        items_data = []
        for i, item in enumerate(self._page_items()):
            role = self.guild.get_role(item["role_id"])
            name = item.get("name") or (role.name if role else f"Role #{self.page*ITEMS_PER_PAGE+i+1}")
            owned = role in self.user.roles if role else False
            color = role.color.value if role else 0
            dur = f"{item['temp_days']} days" if item.get("temp_days") else None
            items_data.append({
                "name": name,
                "cost_str": store.format_artifact_cost(item["cost"]),
                "duration": dur,
                "owned": owned,
                "color": color,
            })
        arts = store.get_artifacts(self.guild.id, self.user.id)
        acc, _ = store.get_artifact_voice_progress(self.guild.id, self.user.id)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, generate_craft_card, items_data, self.page, self.total,
            arts, acc, BG_IMAGE,
        )

    async def _craft_edit(self, interaction: discord.Interaction, png: bytes):
        file = discord.File(io.BytesIO(png), "craft.png")
        if self.from_panel:
            layout = wrap_interactive_layout(
                "Крафт", "Создание ролей из артефактов", "craft.png",
                self, 0x7850FF, PanelSelectMenu(),
            )
            await _panel_edit(interaction, view=layout, file=file)
        else:
            await interaction.edit_original_response(attachments=[file], view=self)

    async def _prev(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except discord.NotFound:
            return
        self.page -= 1
        self._rebuild()
        await self._craft_edit(interaction, await self._render())

    async def _next(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except discord.NotFound:
            return
        self.page += 1
        self._rebuild()
        await self._craft_edit(interaction, await self._render())

    def _make_craft(self, item: dict, role, name: str):
        async def callback(interaction: discord.Interaction):
            try:
                await interaction.response.defer(ephemeral=not self.from_panel)
            except discord.NotFound:
                return

            if interaction.user.id != self.user.id:
                await interaction.followup.send("Это не твой крафт!", ephemeral=True)
                return

            member = self.guild.get_member(interaction.user.id)
            if not member:
                await interaction.followup.send("Не найден на сервере.", ephemeral=True)
                return

            if role and role in member.roles and not item.get("temp_days"):
                await interaction.followup.send(f"У тебя уже есть **{name}**!", ephemeral=True)
                return

            cost = item["cost"]
            if not store.spend_artifacts(self.guild.id, self.user.id, cost):
                arts = store.get_artifacts(self.guild.id, self.user.id)
                await interaction.followup.send(
                    f"Не хватает артефактов!\nНужно: **{store.format_artifact_cost(cost)}**\n"
                    f"У тебя: **{store.format_artifacts(arts)}**",
                    ephemeral=True,
                )
                return

            if role:
                try:
                    await member.add_roles(role, reason="Craft")
                except discord.Forbidden:
                    store.add_artifacts(self.guild.id, self.user.id, cost)
                    await interaction.followup.send(
                        "Нет прав выдать роль. Артефакты возвращены.", ephemeral=True)
                    return

            store.increment_craft_count(self.guild.id, self.user.id)
            _check_panel_achievements(self.guild.id, self.user.id)

            if item.get("temp_days") and role:
                expires = time.time() + item["temp_days"] * 86400
                store.set_temp_role(self.guild.id, self.user.id, item["role_id"], expires)
                msg = f"Скрафчено **{name}**! (срок: {item['temp_days']} дн.)"
            else:
                msg = f"Скрафчено **{name}**!"

            arts_left = store.get_artifacts(self.guild.id, self.user.id)
            await interaction.followup.send(
                f"{msg}\nОсталось: **{store.format_artifacts(arts_left)}**",
                ephemeral=True,
            )

            self._rebuild()
            png = await self._render()
            try:
                if self.from_panel:
                    layout = wrap_interactive_layout(
                        "Крафт", "Создание ролей из артефактов", "craft.png",
                        self, 0x7850FF, PanelSelectMenu(),
                    )
                    await interaction.message.edit(
                        attachments=[discord.File(io.BytesIO(png), "craft.png")],
                        embed=None,
                        content=None,
                        view=layout,
                    )
                else:
                    await interaction.message.edit(
                        attachments=[discord.File(io.BytesIO(png), "craft.png")],
                        view=self,
                    )
            except Exception:
                pass
        return callback


# ════════════════════════════════════════════════════════════════════
#   Panel achievements + ProfileView
# ════════════════════════════════════════════════════════════════════

def _panel_achievement_progress(guild_id: int, user_id: int, ach: dict) -> tuple[float, bool]:
    now = time.time()
    completed = store.get_achievements(guild_id, user_id)
    done = completed.get(ach["id"], False)
    if done:
        return 1.0, True

    ratio = 0.0
    if ach["type"] == "craft_count":
        cur = store.get_craft_count(guild_id, user_id)
        req = ach["required"]
        ratio = min(1.0, cur / req)
        if cur >= req:
            store.complete_achievement(guild_id, user_id, ach["id"])
            return 1.0, True
    elif ach["type"] == "channel_voice":
        ch_id = ach["channel_id"]
        cur = store.get_channel_voice_seconds(guild_id, user_id, ch_id)
        u = store.get_or_create(guild_id, user_id)
        if u.get("lastVoiceJoin") and u.get("lastVoiceChannelId") == ch_id:
            cur += max(0, int(now) - u["lastVoiceJoin"])
        req = ach["required_sec"]
        ratio = min(1.0, cur / req)
        if cur >= req:
            store.complete_achievement(guild_id, user_id, ach["id"])
            return 1.0, True
    elif ach["type"] == "secret":
        ratio = 0.0

    return ratio, done


def _check_panel_achievements(guild_id: int, user_id: int):
    for ach in PANEL_ACHIEVEMENTS:
        _panel_achievement_progress(guild_id, user_id, ach)


async def _render_achievement_showcase(guild_id: int, user_id: int, index: int) -> bytes:
    ach = PANEL_ACHIEVEMENTS[index]
    ratio, done = _panel_achievement_progress(guild_id, user_id, ach)
    img_path = resolve_profile_image(ach["image"])
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        generate_achievement_showcase,
        img_path,
        ach["name"],
        ratio,
        done,
        index,
        len(PANEL_ACHIEVEMENTS),
    )


async def _show_achievement_panel(
    interaction: discord.Interaction,
    index: int,
    user_id: int | None = None,
):
    gid = interaction.guild_id
    uid = user_id or interaction.user.id
    index = index % len(PANEL_ACHIEVEMENTS)
    _check_panel_achievements(gid, uid)
    png = await _render_achievement_showcase(gid, uid, index)
    ach = PANEL_ACHIEVEMENTS[index]
    done = store.get_achievements(gid, uid).get(ach["id"], False)
    inner = AchievementsShowcaseView(gid, uid, index, from_panel=True)
    body = f"**{ach['name']}** — выбери достижение в списке ниже"
    layout = wrap_interactive_layout(
        "Достижения", body, "achievement.png",
        inner, 0x55FF99 if done else 0x7850FF, PanelSelectMenu(),
    )
    await _panel_edit(
        interaction, view=layout,
        file=discord.File(io.BytesIO(png), "achievement.png"),
    )


class AchievementSelectMenu(discord.ui.Select):
    def __init__(self, guild_id: int = 0, user_id: int = 0, current_index: int = 0):
        options = []
        for i, ach in enumerate(PANEL_ACHIEVEMENTS):
            done = False
            if guild_id and user_id:
                done = store.get_achievements(guild_id, user_id).get(ach["id"], False)
            options.append(discord.SelectOption(
                label=ach["name"][:100],
                value=str(i),
                emoji="✅" if done else "📋",
                description="Выполнено" if done else "Смотреть прогресс",
                default=(i == current_index),
            ))
        super().__init__(
            custom_id="ree_achievement_pick",
            placeholder="Выберите достижение",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("Только на сервере.", ephemeral=True)
            return
        try:
            await interaction.response.defer()
        except discord.NotFound:
            return
        try:
            index = int(self.values[0])
            await _show_achievement_panel(interaction, index)
        except Exception as e:
            print(f"[achievements] {e}")
            try:
                await interaction.followup.send("Не удалось открыть достижение.", ephemeral=True)
            except discord.NotFound:
                pass


class AchievementsShowcaseView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int, index: int = 0, from_panel: bool = False):
        super().__init__(timeout=None if from_panel else 180)
        self.guild_id   = guild_id
        self.user_id    = user_id
        self.index      = index % len(PANEL_ACHIEVEMENTS)
        self.from_panel = from_panel
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        if self.from_panel:
            pick = AchievementSelectMenu(self.guild_id, self.user_id, self.index)
            pick.row = 0
            self.add_item(pick)
        else:
            prev = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary,
                                     disabled=(self.index <= 0))
            prev.callback = self._prev
            self.add_item(prev)
            nxt = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary,
                                    disabled=(self.index >= len(PANEL_ACHIEVEMENTS) - 1))
            nxt.callback = self._next
            self.add_item(nxt)

    async def _edit_showcase(self, interaction: discord.Interaction):
        if self.from_panel:
            await _show_achievement_panel(interaction, self.index, self.user_id)
            return
        png = await _render_achievement_showcase(self.guild_id, self.user_id, self.index)
        ach = PANEL_ACHIEVEMENTS[self.index]
        file = discord.File(io.BytesIO(png), "achievement.png")
        embed = discord.Embed(
            title="Достижения",
            description=f"**{ach['name']}**",
            color=0x55FF99 if store.get_achievements(self.guild_id, self.user_id).get(ach["id"]) else 0x7850FF,
        )
        embed.set_image(url="attachment://achievement.png")
        embed.set_footer(text="◀ ▶ — переключить достижение")
        await interaction.edit_original_response(
            embed=embed,
            attachments=[file],
            view=self,
        )

    async def _prev(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Это не твоё меню.", ephemeral=True)
            return
        try:
            await interaction.response.defer()
        except discord.NotFound:
            return
        self.index = max(0, self.index - 1)
        self._rebuild()
        await self._edit_showcase(interaction)

    async def _next(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Это не твоё меню.", ephemeral=True)
            return
        try:
            await interaction.response.defer()
        except discord.NotFound:
            return
        self.index = min(len(PANEL_ACHIEVEMENTS) - 1, self.index + 1)
        self._rebuild()
        await self._edit_showcase(interaction)


async def _send_achievements_showcase(interaction: discord.Interaction, index: int = 0):
    gid, uid = interaction.guild_id, interaction.user.id
    _check_panel_achievements(gid, uid)
    png = await _render_achievement_showcase(gid, uid, index)
    ach = PANEL_ACHIEVEMENTS[index]
    done = store.get_achievements(gid, uid).get(ach["id"], False)
    embed = discord.Embed(
        title="Достижения",
        description=f"**{ach['name']}**",
        color=0x55FF99 if done else 0x7850FF,
    )
    embed.set_image(url="attachment://achievement.png")
    embed.set_footer(text="◀ ▶ — переключить достижение")
    view = AchievementsShowcaseView(gid, uid, index)
    await interaction.followup.send(
        embed=embed,
        file=discord.File(io.BytesIO(png), "achievement.png"),
        view=view,
        ephemeral=True,
    )


class ProfileView(discord.ui.View):
    def __init__(self, guild: discord.Guild, user: discord.Member):
        super().__init__(timeout=180)
        self.guild = guild
        self.user  = user


# ════════════════════════════════════════════════════════════════════
#   Profile helpers
# ════════════════════════════════════════════════════════════════════

def _profile_stats(guild_id: int, target: discord.abc.User) -> dict:
    u = store.get_or_create(guild_id, target.id)
    live = max(0, int(time.time()) - u.get("lastVoiceJoin", 0)) if u.get("lastVoiceJoin") else 0
    return {
        "name":      target.display_name,
        "level":     store.xp_to_level(u.get("xp", 0)),
        "xpCurrent": store.xp_in_current_level(u.get("xp", 0)),
        "xpNeed":    store.XP_PER_LEVEL,
        "gs":        store.format_voice_time(u.get("voiceSeconds", 0) + live),
        "top":       store.get_rank(guild_id, target.id) or "-",
        "gold":      u.get("gold", 0),
        "artifacts": store.get_artifacts(guild_id, target.id),
    }


async def _build_profile(guild: discord.Guild, target: discord.abc.User) -> tuple[bytes, ProfileView]:
    gid = guild.id
    stats = _profile_stats(gid, target)
    member = target if isinstance(target, discord.Member) else guild.get_member(target.id)
    if not isinstance(member, discord.Member):
        raise ValueError(f"Member {target.id} not in guild {guild.id}")
    status = _get_member_status(member)
    view = ProfileView(guild, member)
    user_banner = store.get_banner(gid, target.id)
    bg_path = user_banner if user_banner and os.path.isfile(user_banner) else BG_IMAGE
    png = await generate_profile_card(
        target.display_avatar.replace(size=256).url, stats,
        custom_image_path=bg_path, status=status,
    )
    return png, view


# ════════════════════════════════════════════════════════════════════
#   Server panel (Components V2 + select menu)
# ════════════════════════════════════════════════════════════════════

def _attach_panel_menu(view: discord.ui.View) -> discord.ui.View:
    menu = PanelSelectMenu()
    menu.row = 4
    view.add_item(menu)
    view.timeout = None
    return view


async def _panel_edit(
    interaction: discord.Interaction,
    *,
    view: discord.ui.LayoutView,
    file: discord.File | None = None,
):
    kwargs: dict = {"view": view, "embed": None, "content": None}
    kwargs["attachments"] = [file] if file else []
    await interaction.edit_original_response(**kwargs)


async def _panel_handle_home(interaction: discord.Interaction):
    guild_name = interaction.guild.name if interaction.guild else None
    has_img = _panel_image_file() is not None
    layout = build_home_layout(
        guild_name, has_image=has_img, select_menu=PanelSelectMenu(),
    )
    await _panel_edit(interaction, view=layout, file=_panel_image_file())


async def _panel_handle_profile(interaction: discord.Interaction):
    if not interaction.guild:
        return
    member = interaction.guild.get_member(interaction.user.id) or interaction.user
    if not isinstance(member, discord.Member):
        await interaction.followup.send("Не удалось найти участника.", ephemeral=True)
        return
    png, inner = await _build_profile(interaction.guild, member)
    _attach_panel_menu(inner)
    layout = wrap_interactive_layout(
        "Профиль", f"**{member.display_name}**", "profile.png",
        inner, 0x7850FF, PanelSelectMenu(),
    )
    await _panel_edit(
        interaction, view=layout,
        file=discord.File(io.BytesIO(png), "profile.png"),
    )


async def _panel_handle_shop(interaction: discord.Interaction):
    if not interaction.guild:
        return
    member = interaction.guild.get_member(interaction.user.id) or interaction.user
    inner = ShopView(interaction.guild, member, from_panel=True)
    png = await inner._render()
    layout = wrap_interactive_layout(
        "Магазин", "Покупка ролей за золото", "shop.png",
        inner, 0xFFBE1E, PanelSelectMenu(),
    )
    await _panel_edit(
        interaction, view=layout,
        file=discord.File(io.BytesIO(png), "shop.png"),
    )


async def _panel_handle_craft(interaction: discord.Interaction):
    if not interaction.guild:
        return
    member = interaction.guild.get_member(interaction.user.id) or interaction.user
    inner = CraftView(interaction.guild, member, from_panel=True)
    png = await inner._render()
    layout = wrap_interactive_layout(
        "Крафт", "Создание ролей из артефактов", "craft.png",
        inner, 0x7850FF, PanelSelectMenu(),
    )
    await _panel_edit(
        interaction, view=layout,
        file=discord.File(io.BytesIO(png), "craft.png"),
    )


async def _panel_handle_wallet(interaction: discord.Interaction):
    gid = interaction.guild_id
    gold = store.get_gold(gid, interaction.user.id)
    arts = store.get_artifacts(gid, interaction.user.id)
    acc, _ = store.get_artifact_voice_progress(gid, interaction.user.id)
    mins_done = acc // 60
    body = (
        f"**Золото:** {gold} G\n"
        f"**Opal:** {arts.get('opal', 0)} | **Ruby:** {arts.get('ruby', 0)} | "
        f"**Diamond:** {arts.get('diamond', 0)}\n"
        f"**До артефакта:** {mins_done}/60 мин в ГС\n"
        f"-# Diamond 80% | Ruby 15% | Opal 5% за час в голосе"
    )
    layout = build_text_layout("Кошелёк", body, 0xFFBE1E, PanelSelectMenu())
    await _panel_edit(interaction, view=layout)


async def _panel_handle_top(interaction: discord.Interaction):
    gid = interaction.guild_id
    members = store.get_top(gid, 10)
    lines = []
    for i, u in enumerate(members, 1):
        m = interaction.guild.get_member(u["userId"])
        name = m.display_name if m else f"<@{u['userId']}>"
        lvl = store.xp_to_level(u.get("xp", 0))
        gold = u.get("gold", 0)
        icon = {1: "#1", 2: "#2", 3: "#3"}.get(i, f"#{i}")
        lines.append(f"**{icon}** {name} — LVL **{lvl}** | {gold}G")
    body = "\n".join(lines) if lines else "Пока пусто."
    layout = build_text_layout("Рейтинг по уровню", body, 0x7850FF, PanelSelectMenu())
    await _panel_edit(interaction, view=layout)


async def _panel_handle_achievements(interaction: discord.Interaction, index: int = 0):
    await _show_achievement_panel(interaction, index)


class PanelSelectMenu(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Главная",
                description="Вернуться к главному экрану",
                value="home",
                emoji="🏠",
            ),
            discord.SelectOption(
                label="Профиль",
                description="Карточка уровня, золота и артефактов",
                value="profile",
                emoji="🪪",
            ),
            discord.SelectOption(
                label="Магазин",
                description="Покупка ролей за золото",
                value="shop",
                emoji="🛒",
            ),
            discord.SelectOption(
                label="Крафт",
                description="Создание ролей из артефактов",
                value="craft",
                emoji="⚗️",
            ),
            discord.SelectOption(
                label="Кошелёк",
                description="Золото и инвентарь артефактов",
                value="wallet",
                emoji="💰",
            ),
            discord.SelectOption(
                label="Рейтинг",
                description="Топ участников по уровню",
                value="top",
                emoji="🏆",
            ),
            discord.SelectOption(
                label="Достижения",
                description="Секретные задания и прогресс",
                value="achievements",
                emoji="🏅",
            ),
        ]
        super().__init__(
            custom_id="ree_panel_select",
            placeholder="Выберите раздел меню",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("Только на сервере.", ephemeral=True)
            return
        try:
            await interaction.response.defer()
        except discord.NotFound:
            return
        handlers = {
            "home":         _panel_handle_home,
            "profile":      _panel_handle_profile,
            "shop":         _panel_handle_shop,
            "craft":        _panel_handle_craft,
            "wallet":       _panel_handle_wallet,
            "top":          _panel_handle_top,
            "achievements": _panel_handle_achievements,
        }
        handler = handlers.get(self.values[0])
        if not handler:
            await interaction.followup.send("Раздел не найден.", ephemeral=True)
            return
        try:
            await handler(interaction)
        except Exception as e:
            print(f"[panel] {e}")
            try:
                await interaction.followup.send("Не удалось открыть раздел.", ephemeral=True)
            except discord.NotFound:
                pass


class PanelPersistentLayoutView(discord.ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        row = discord.ui.ActionRow()
        row.add_item(PanelSelectMenu())
        self.add_item(row)


class AchievementPickPersistentView(discord.ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        row = discord.ui.ActionRow()
        row.add_item(AchievementSelectMenu())
        self.add_item(row)


async def _publish_panel(channel: discord.abc.Messageable, guild: discord.Guild):
    has_img = _panel_image_file() is not None
    layout = build_home_layout(
        guild.name, has_image=has_img, select_menu=PanelSelectMenu(),
    )
    panel_file = _panel_image_file()
    await channel.send(
        view=layout,
        files=[panel_file] if panel_file else [],
    )


# ════════════════════════════════════════════════════════════════════
#   Slash Commands
# ════════════════════════════════════════════════════════════════════

@tree.command(name="profile", description="Опубликовать панель сервера в канале")
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
async def cmd_profile(interaction: discord.Interaction):
    if interaction.guild is None or interaction.channel is None:
        return
    try:
        await interaction.response.defer(ephemeral=True)
    except discord.NotFound:
        return
    try:
        await _publish_panel(interaction.channel, interaction.guild)
        await interaction.followup.send("Панель опубликована.", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("Нет прав отправить сообщение в этот канал.", ephemeral=True)
    except discord.NotFound:
        pass
    except Exception as e:
        print(f"[profile] {e}")
        try:
            await interaction.followup.send("Не удалось опубликовать панель.", ephemeral=True)
        except discord.NotFound:
            pass


@tree.command(name="craft", description="Крафт ролей из артефактов")
@app_commands.guild_only()
async def cmd_craft(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
    except discord.NotFound:
        return
    member = interaction.guild.get_member(interaction.user.id) or interaction.user
    view = CraftView(interaction.guild, member)
    try:
        png = await view._render()
        await interaction.followup.send(
            file=discord.File(io.BytesIO(png), "craft.png"),
            view=view,
        )
    except discord.NotFound:
        pass


@tree.command(name="shop", description="Magazin rolej za zoloto")
async def cmd_shop(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
    except discord.NotFound:
        return
    member = interaction.guild.get_member(interaction.user.id) or interaction.user
    view   = ShopView(interaction.guild, member)
    try:
        png = await view._render()
        await interaction.followup.send(
            file=discord.File(io.BytesIO(png), "shop.png"), view=view
        )
    except discord.NotFound:
        pass


@tree.command(name="balance", description="Tvoj balans zolota")
async def cmd_balance(interaction: discord.Interaction):
    try:
        await interaction.response.defer(ephemeral=True)
    except discord.NotFound:
        return
    gold = store.get_gold(interaction.guild_id, interaction.user.id)
    embed = discord.Embed(title="Gold Balance", color=0xFFBE1E)
    embed.add_field(name="Gold", value=f"**{gold} G**")
    embed.set_footer(text="+1G/msg | +10G/5min voice | +100G/level up")
    try:
        await interaction.followup.send(embed=embed, ephemeral=True)
    except discord.NotFound:
        pass


@tree.command(name="top", description="Top po urovnyu")
@app_commands.describe(count="1-10")
async def cmd_top(interaction: discord.Interaction, count: int = 10):
    try:
        await interaction.response.defer()
    except discord.NotFound:
        return
    limit   = min(10, max(1, count))
    members = store.get_top(interaction.guild_id, limit)
    lines   = []
    for i, u in enumerate(members, 1):
        m    = interaction.guild.get_member(u["userId"])
        name = m.display_name if m else f"<@{u['userId']}>"
        lvl  = store.xp_to_level(u.get("xp", 0))
        gold = u.get("gold", 0)
        icon = {1: "#1", 2: "#2", 3: "#3"}.get(i, f"#{i}")
        lines.append(f"**{icon}** {name} — LVL **{lvl}**  |  {gold}G")
    embed = discord.Embed(title="TOP by Level",
                          description="\n".join(lines) if lines else "Empty.",
                          color=0x7850FF)
    try:
        await interaction.followup.send(embed=embed)
    except discord.NotFound:
        pass


# ════════════════════════════════════════════════════════════════════
#   Логирование в канал
# ════════════════════════════════════════════════════════════════════

async def bot_log(msg: str):
    """Отправляет лог-сообщение в канал LOG_CHANNEL_ID."""
    try:
        ch = client.get_channel(LOG_CHANNEL_ID)
        if ch:
            await ch.send(f"`[LOG]` {msg}")
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════
#   Report Views (модераторская панель !moder)
# ════════════════════════════════════════════════════════════════════

class ReportDetailView(discord.ui.View):
    def __init__(self, report: dict):
        super().__init__(timeout=300)
        self.report = report

    @discord.ui.button(label="Reviewed", style=discord.ButtonStyle.success, emoji="\u2705")
    async def reviewed(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            return
        r = store.update_report_status(self.report["id"], "reviewed", interaction.user.id)
        if not r:
            await interaction.followup.send("Report not found.", ephemeral=True)
            return
        try:
            reporter = await client.fetch_user(r["reporterId"])
            dm = await reporter.create_dm()
            embed = discord.Embed(
                title=f"Report #{r['id']} -- Reviewed",
                description=(
                    f"Your report against **{r['targetName']}** "
                    f"has been **reviewed** by a moderator.\n"
                    f"Thank you for helping keep the server safe!"
                ),
                color=0x55FF55,
            )
            await dm.send(embed=embed)
        except Exception:
            pass
        await bot_log(f"Report #{r['id']} REVIEWED by {interaction.user}")
        await interaction.followup.send(
            f"Report #{r['id']} marked as **reviewed**.", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Declined", style=discord.ButtonStyle.danger, emoji="\u274C")
    async def declined(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            return
        r = store.update_report_status(self.report["id"], "declined", interaction.user.id)
        if not r:
            await interaction.followup.send("Report not found.", ephemeral=True)
            return
        try:
            reporter = await client.fetch_user(r["reporterId"])
            dm = await reporter.create_dm()
            embed = discord.Embed(
                title=f"Report #{r['id']} -- Declined",
                description=(
                    f"Your report against **{r['targetName']}** "
                    f"has been **declined** by a moderator.\n"
                    f"The report did not meet the criteria."
                ),
                color=0xFF5555,
            )
            await dm.send(embed=embed)
        except Exception:
            pass
        await bot_log(f"Report #{r['id']} DECLINED by {interaction.user}")
        await interaction.followup.send(
            f"Report #{r['id']} marked as **declined**.", ephemeral=True)
        self.stop()


class ReportListView(discord.ui.View):
    def __init__(self, guild_id: int, page: int = 0):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.page     = page
        self.per_page = 5
        self._reports = store.get_pending_reports(guild_id)
        self._reports.sort(key=lambda r: r["id"], reverse=True)
        self.total    = max(1, (len(self._reports) + self.per_page - 1) // self.per_page)
        self._rebuild()

    def _page_items(self):
        s = self.page * self.per_page
        return self._reports[s:s + self.per_page]

    def _rebuild(self):
        self.clear_items()
        if self.page > 0:
            prev_btn = discord.ui.Button(label="<", style=discord.ButtonStyle.secondary)
            prev_btn.callback = self._prev
            self.add_item(prev_btn)
        if self.page < self.total - 1:
            nxt_btn = discord.ui.Button(label=">", style=discord.ButtonStyle.secondary)
            nxt_btn.callback = self._nxt
            self.add_item(nxt_btn)
        for rpt in self._page_items():
            btn = discord.ui.Button(label=f"#{rpt['id']}", style=discord.ButtonStyle.primary, row=1)
            btn.callback = self._make_detail(rpt)
            self.add_item(btn)

    def _make_detail(self, rpt):
        async def callback(interaction: discord.Interaction):
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.NotFound:
                return
            fresh = store.get_report(rpt["id"])
            if not fresh:
                await interaction.followup.send("Report not found.", ephemeral=True)
                return
            reporter = client.get_user(fresh["reporterId"])
            r_name   = reporter.display_name if reporter else f"<@{fresh['reporterId']}>"
            server_txt = "YES" if fresh.get("targetOnServer") else "NO"
            embed = discord.Embed(
                title=f"Report #{fresh['id']}  |  {fresh['status'].upper()}",
                color={"pending": 0xFFAA00, "reviewed": 0x55FF55,
                       "declined": 0xFF5555}.get(fresh["status"], 0x888888),
            )
            embed.add_field(name="Reporter",    value=r_name, inline=True)
            embed.add_field(name="Target",      value=f"**{fresh['targetName']}**", inline=True)
            embed.add_field(name="On server?",  value=server_txt, inline=True)
            embed.add_field(name="Info",        value=fresh["targetInfo"][:1024], inline=False)
            ts = fresh.get("createdAt", 0)
            embed.set_footer(text=f"Created: {time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))}")
            view = ReportDetailView(fresh) if fresh["status"] == "pending" else None
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        return callback

    async def _prev(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except discord.NotFound:
            return
        self.page -= 1
        self._rebuild()
        embed = self._make_list_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    async def _nxt(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except discord.NotFound:
            return
        self.page += 1
        self._rebuild()
        embed = self._make_list_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    def _make_list_embed(self) -> discord.Embed:
        lines = []
        for rpt in self._page_items():
            reporter = client.get_user(rpt["reporterId"])
            r_name   = reporter.display_name if reporter else f"ID:{rpt['reporterId']}"
            lines.append(f"**#{rpt['id']}** -- from **{r_name}** vs **{rpt['targetName'][:20]}**")
        embed = discord.Embed(
            title="REPORTS -- Pending",
            description="\n".join(lines) if lines else "No pending reports.",
            color=0xFFAA00,
        )
        embed.set_footer(text=f"Page {self.page+1}/{self.total}  |  Click # to open")
        return embed


class ModerPanelView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id

    @discord.ui.button(label="REPORTS", style=discord.ButtonStyle.danger)
    async def reports_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            return
        view  = ReportListView(self.guild_id)
        embed = view._make_list_embed()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


# ════════════════════════════════════════════════════════════════════
#   Запуск
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    token = (os.getenv("DISCORD_TOKEN") or "").strip().strip('"').strip("'")
    if not token:
        print("[ERR] No DISCORD_TOKEN in .env!")
        raise SystemExit(1)
    print("[..] Starting bot...")
    client.run(token, log_level=20)
