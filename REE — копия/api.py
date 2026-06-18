"""
api.py — HTTP API для сайта: топ игроков, профили.
Запускается как фоновая задача внутри основного процесса бота.
"""

import os
import json

from aiohttp import web
import store

API_PORT = int(os.getenv("API_PORT", "8080"))
API_TOKEN = os.getenv("API_TOKEN", "")
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "*")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))


def _cors(origin="*"):
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
    }


def _json(data, status=200):
    return web.json_response(data, status=status, headers=_cors(CORS_ORIGIN))


def _check_token(request):
    if not API_TOKEN:
        return True
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {API_TOKEN}"


# ── Top Players ─────────────────────────────────────────────────────

async def handle_top(request):
    if not _check_token(request):
        return _json({"error": "unauthorized"}, 401)
    if not GUILD_ID:
        return _json({"error": "GUILD_ID not configured"}, 500)

    limit = min(int(request.query.get("limit", "10")), 50)
    top = store.get_top(GUILD_ID, limit)

    players = []
    for i, u in enumerate(top, 1):
        uid = u.get("userId", 0)
        players.append({
            "rank": i,
            "userId": uid,
            "level": store.xp_to_level(u.get("xp", 0)),
            "xp": u.get("xp", 0),
            "xpInLevel": store.xp_in_current_level(u.get("xp", 0)),
            "gold": u.get("gold", 0),
            "voiceTime": store.format_voice_time(u.get("voiceSeconds", 0)),
            "voiceSeconds": u.get("voiceSeconds", 0),
            "artifacts": u.get("artifacts", {}),
            "craftCount": u.get("craftCount", 0),
            "avatarUrl": f"https://cdn.discordapp.com/avatars/{uid}/{uid}.png?size=128",
        })

    return _json({"guildId": GUILD_ID, "players": players})


# ── Player Profile ──────────────────────────────────────────────────

async def handle_profile(request):
    if not _check_token(request):
        return _json({"error": "unauthorized"}, 401)
    if not GUILD_ID:
        return _json({"error": "GUILD_ID not configured"}, 500)

    try:
        user_id = int(request.match_info["user_id"])
    except (ValueError, KeyError):
        return _json({"error": "invalid user_id"}, 400)

    u = store.get_or_create(GUILD_ID, user_id)
    rank = store.get_rank(GUILD_ID, user_id)

    profile = {
        "userId": user_id,
        "level": store.xp_to_level(u.get("xp", 0)),
        "xp": u.get("xp", 0),
        "xpInLevel": store.xp_in_current_level(u.get("xp", 0)),
        "gold": u.get("gold", 0),
        "voiceTime": store.format_voice_time(u.get("voiceSeconds", 0)),
        "voiceSeconds": u.get("voiceSeconds", 0),
        "artifacts": u.get("artifacts", {}),
        "craftCount": u.get("craftCount", 0),
        "rank": rank,
        "avatarUrl": f"https://cdn.discordapp.com/avatars/{user_id}/{user_id}.png?size=256",
    }

    return _json(profile)


# ── All Players (light) ─────────────────────────────────────────────

async def handle_players(request):
    if not _check_token(request):
        return _json({"error": "unauthorized"}, 401)
    if not GUILD_ID:
        return _json({"error": "GUILD_ID not configured"}, 500)

    limit = min(int(request.query.get("limit", "50")), 200)
    offset = int(request.query.get("offset", "0"))
    top = store.get_top(GUILD_ID, limit + offset)
    page = top[offset:offset + limit]

    players = []
    for i, u in enumerate(page, offset + 1):
        uid = u.get("userId", 0)
        players.append({
            "rank": i,
            "userId": uid,
            "level": store.xp_to_level(u.get("xp", 0)),
            "xp": u.get("xp", 0),
            "gold": u.get("gold", 0),
            "voiceTime": store.format_voice_time(u.get("voiceSeconds", 0)),
            "avatarUrl": f"https://cdn.discordapp.com/avatars/{uid}/{uid}.png?size=128",
        })

    return _json({"guildId": GUILD_ID, "players": players, "offset": offset, "limit": limit})


# ── Status ──────────────────────────────────────────────────────────

async def handle_status(request):
    return _json({
        "status": "ok",
        "guildId": GUILD_ID,
        "version": "1.0",
    })


# ── CORS preflight ──────────────────────────────────────────────────

async def options_handler(request):
    return web.Response(status=204, headers=_cors(CORS_ORIGIN))


# ── App ─────────────────────────────────────────────────────────────

def create_app():
    app = web.Application()

    for path in ["/api/top", "/api/profile/{user_id}", "/api/players", "/api/status"]:
        app.router.add_get(path, {
            "/api/top": handle_top,
            "/api/profile/{user_id}": handle_profile,
            "/api/players": handle_players,
            "/api/status": handle_status,
        }[path])
        app.router.add_options(path, options_handler)

    return app


async def start_api():
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", API_PORT)
    await site.start()
    print(f"[API] HTTP server on port {API_PORT}")
