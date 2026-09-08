"""
Discord Key Bot — ISHU AUTH integration
Slash /key command: owner gets permanent/custom-expiry options; normal users
choose License Key or Username+Password, then must REALLY complete a VPLINK
link. Completion is verified server-side (callback hit) — no "I completed"
button — and the key is auto-DM'd when it fires.
"""
import os, json, time, asyncio, secrets
from pathlib import Path

import aiohttp
import discord
from discord import app_commands, ui

# ── Config ──────────────────────────────────────────────────────────────────
CFG_PATH = Path(__file__).parent / "config.json"
DATA_PATH = Path(__file__).parent / "data.json"

with open(CFG_PATH, encoding="utf-8") as _f:
    CFG = json.load(_f)

SERVER   = CFG.get("server", "").rstrip("/")
NAME     = CFG.get("name", "")          # app label (also used as appid fallback)
MASTER_KEY = CFG.get("key", "")         # master api_key for /api/bootstrap
OWNERID  = CFG.get("ownerid", "")
SECRET   = CFG.get("secret", "")
VERSION  = CFG.get("version", "1.0")
SHORTENER = CFG.get("shortener", "")      # destination long URL
VPLINK_API = CFG.get("vplink_api", "")    # VPLINK API token (optional but recommended)
BOT_OWNER = int(CFG.get("owner_id", 0))   # Discord user id of the admin
KEY_HOURS = int(CFG.get("key_hours", 48))
COOLDOWN_HOURS = int(CFG.get("cooldown_hours", 48))


# ── Persistent data ─────────────────────────────────────────────────────────
def _load_data():
    if DATA_PATH.exists():
        try:
            return json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"cooldowns": {}, "last_keys": {}}

def _save_data(d):
    DATA_PATH.write_text(json.dumps(d, indent=2), encoding="utf-8")

DATA = _load_data()


# ── API helper ──────────────────────────────────────────────────────────────
def _passwd() -> str:
    return "UP-" + secrets.token_hex(4).upper()

async def _botkey(username: str, duration: str = "48h", ltype: str = "license", password: str | None = None):
    payload = {
        "name": NAME, "ownerid": OWNERID, "secret": SECRET, "version": VERSION,
        "username": username, "duration": duration, "lock": True,
        "type": ltype,
    }
    if ltype == "user":
        payload["password"] = password or _passwd()
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{SERVER}/api/botkey", json=payload, timeout=aiohttp.ClientTimeout(total=25)) as r:
            return await r.json()


async def _shorten(url: str) -> str | None:
    """Generate a short link via VPLINK API. Returns the short URL, or the
    original URL if VPLINK is not configured or fails."""
    if not VPLINK_API or not url:
        return url or None
    params = {
        "api": VPLINK_API,
        "url": url,
        "format": "text",
    }
    async with aiohttp.ClientSession() as s:
        try:
            async with s.get(
                "https://vplink.in/api", params=params,
                timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status == 200:
                    text = (await r.text()).strip()
                    if "vplink.in/" in text:
                        return text
        except Exception:
            pass
    return url or None


async def _task_new(user_id: int, ltype: str) -> dict:
    """Register a verified shortlink task on the server. Returns {token,...}."""
    payload = {
        "name": NAME, "ownerid": OWNERID, "secret": SECRET, "version": VERSION,
        "user_id": str(user_id), "ltype": ltype, "destination": SHORTENER,
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(
            f"{SERVER}/api/shortlink/new", json=payload,
            timeout=aiohttp.ClientTimeout(total=25)) as r:
            return await r.json()


async def _task_status(token: str) -> dict:
    """Server-side completion check (no client button involved)."""
    payload = {
        "name": NAME, "ownerid": OWNERID, "secret": SECRET, "version": VERSION,
        "token": token,
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(
            f"{SERVER}/api/shortlink/check", json=payload,
            timeout=aiohttp.ClientTimeout(total=25)) as r:
            return await r.json()


async def _bootstrap():
    """Re-register the owner row. Render's free SQLite DB resets on every
    restart/redeploy, so without this the /api/botkey auth would 401 and the
    bot would show 'API error.' Calling it on startup makes the bot restore
    the owner row automatically — no manual reseed ever needed."""
    if not MASTER_KEY or not NAME:
        return False
    payload = {
        "key": MASTER_KEY,
        "appid": NAME,
        "appname": NAME,
        "ownerid": OWNERID,
        "secret": SECRET,
        "version": VERSION,
    }
    async with aiohttp.ClientSession() as s:
        try:
            async with s.post(
                f"{SERVER}/api/bootstrap", json=payload,
                timeout=aiohttp.ClientTimeout(total=25)) as r:
                if r.status == 200:
                    data = await r.json()
                    return bool(data.get("ok"))
        except Exception:
            return False
    return False


# ── Cooldown check ──────────────────────────────────────────────────────────
def _user_cooldown_ok(user_id: int) -> tuple[bool, float]:
    """Returns (allowed, seconds_remaining)."""
    last = DATA["cooldowns"].get(str(user_id), 0)
    elapsed = time.time() - last
    wait = COOLDOWN_HOURS * 3600 - elapsed
    if wait <= 0:
        return True, 0
    return False, wait


def _format_time(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m {s}s"


def _fmt_issue(data: dict) -> str:
    """Format the issued key for DM — license key OR username/password."""
    if data.get("type") == "user":
        return (f"**Username**\n`{data.get('username', '')}`\n"
                f"**Password**\n`{data.get('password', '')}`")
    return f"**License Key**\n`{data.get('license_key', '')}`"


# ── Bot setup ───────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
bot = discord.Client(intents=intents, activity=discord.Game(name="/key"))
tree = app_commands.CommandTree(bot)


# ── Views ───────────────────────────────────────────────────────────────────
# Pending verified tasks: token -> {channel_id, msg_id, user_id, ltype}
PENDING = {}
TASK_TIMEOUT_SECONDS = 300   # how long the bot waits for a real completion
TASK_POLL_SECONDS = 5


class UserKeyTypeView(ui.View):
    """Shown to normal users: choose what they want — License Key or Username+Password."""
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

    def _pick(self, ltype: str) -> str:
        return "Username + Password" if ltype == "user" else "License Key"

    async def _start(self, interaction: discord.Interaction, ltype: str):
        if interaction.user.id != self.user_id:
            return
        allowed, remaining = _user_cooldown_ok(self.user_id)
        if not allowed:
            return await interaction.response.send_message(
                f"Please wait {_format_time(remaining)} before generating a new key.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        res = await _task_new(self.user_id, ltype)
        if not res.get("ok"):
            return await interaction.followup.send(
                "Could not start the task. Try again later.", ephemeral=True)

        token = res["token"]
        callback = f"{SERVER}/api/shortlink/c?token={token}"
        link = await _shorten(callback)
        if not link:
            return await interaction.followup.send(
                "Shortener link is not configured. Contact admin.", ephemeral=True)
        if VPLINK_API and "vplink.in/" not in link:
            return await interaction.followup.send(
                "\u26a0\ufe0f VPLINK link nahi ban paya \u2014 config me `vplink_api` sahi token check karo.\n"
                "Jab tak VP link nahi khulta, key dena band hai.", ephemeral=True)

        view = ui.View()
        view.add_item(ui.Button(
            label="\U0001f517 Open Link \u2014 Complete the task",
            style=discord.ButtonStyle.link, url=link))

        text = (
            f"Tap **Open Link** \u2014 wo aapke browser me khulega.\n"
            f"100% complete karo (ad \u2192 page khule) fir **intazar karo** \u2014\n\n"
            f"\u23f3 Verifying your completion \u2026 aapka "
            f"**{self._pick(ltype)}** DM me **automatically** jayega.\n"
            f"*Bina link khole koi key nahi mil sakti \u2014 server verify karta hai.*\n\n"
            f"Direct link: {link}\n\n"
            f"Key lasts **{KEY_HOURS}h**."
        )
        msg = await interaction.followup.send(text, view=view, ephemeral=True, wait=True)
        if getattr(msg, "id", None):
            PENDING[token] = {
                "channel_id": interaction.channel_id,
                "msg_id": msg.id,
                "user_id": self.user_id,
                "ltype": ltype,
            }
            bot.loop.create_task(_await_and_issue(token))
        else:
            await interaction.followup.send(
                "Task started, but I couldn't track it. Contact admin.", ephemeral=True)

    @ui.button(label="License Key", style=discord.ButtonStyle.primary, emoji="\U0001f511")
    async def on_license(self, interaction: discord.Interaction, button: ui.Button):
        await self._start(interaction, "license")

    @ui.button(label="Username + Password", style=discord.ButtonStyle.success, emoji="\U0001f465")
    async def on_user(self, interaction: discord.Interaction, button: ui.Button):
        await self._start(interaction, "user")


async def _edit_task(task: dict, text: str):
    channel = bot.get_channel(task["channel_id"])
    if not channel:
        return
    try:
        msg = channel.get_partial_message(task["msg_id"])
        await msg.edit(content=text, view=None)
    except Exception:
        pass


async def _deliver_key(task: dict, token: str):
    """After server confirms a real completion: issue + auto-DM the chosen key."""
    user_id = task["user_id"]
    ltype = task["ltype"]
    data = await _botkey(f"dc_{user_id}", duration=f"{KEY_HOURS}h", ltype=ltype,
                         password=_passwd() if ltype == "user" else None)
    if not data.get("ok"):
        await _edit_task(task, "\u274c Failed to generate your key server-side. Contact admin.")
        PENDING.pop(token, None)
        return

    body = _fmt_issue(data)
    expires = data.get("expires", "")
    DATA["cooldowns"][str(user_id)] = time.time()
    DATA["last_keys"][str(user_id)] = {"body": body, "expires": expires}
    _save_data(DATA)

    dm_text = f"\U0001f511 **Your key is ready!**\n{body}\nExpires: {expires}"
    sent = False
    try:
        target = bot.get_user(user_id) or await bot.fetch_user(user_id)
        await target.send(dm_text)
        sent = True
    except discord.Forbidden:
        sent = False
    except discord.HTTPException:
        sent = False

    what = "Username + Password" if ltype == "user" else "License Key"
    if sent:
        await _edit_task(task, f"\u2705 **Verified \u2014 {what} sent to your DM!**")
    else:
        await _edit_task(task, f"{body}\nExpires: {expires}\n\n*Couldn't DM you \u2014 please enable DMs.*")
    PENDING.pop(token, None)


async def _await_and_issue(token: str):
    """Poll the server until a REAL completion fires (callback hit), then
    auto-DM the key. No user-clickable 'I completed' button exists, so fake
    clicks can't mint keys."""
    task = PENDING.get(token)
    if not task:
        return
    deadline = time.time() + TASK_TIMEOUT_SECONDS
    while time.time() < deadline:
        await asyncio.sleep(TASK_POLL_SECONDS)
        try:
            res = await _task_status(token)
            if res.get("ok") and res.get("completed"):
                await _deliver_key(task, token)
                return
        except Exception:
            pass
    if token in PENDING:
        await _edit_task(task, "\u23f0 **Timeout** \u2014 task was not completed. Run `/key` to try again.")
        PENDING.pop(token, None)


class CustomDaysModal(ui.Modal, title="Custom key duration"):
    days = ui.TextInput(label="Number of days", placeholder="e.g. 2, 5, 10, 90", max_length=5)

    def __init__(self, ltype: str = "license"):
        super().__init__()
        self.ltype = ltype

    async def on_submit(self, interaction: discord.Interaction):
        try:
            n = int(self.days.value.strip())
            if n <= 0 or n > 3650:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message(
                "Enter a valid number of days (1 to 3650).", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        username = f"dc_{interaction.user.id}"
        from datetime import datetime, timezone, timedelta
        until = int((datetime.now(timezone.utc) + timedelta(days=n)).timestamp() * 1000)
        ltype = self.ltype
        data = await _botkey(username, duration="custom", ltype=ltype,
                             password=_passwd() if ltype == "user" else None)
        if not data.get("ok"):
            return await interaction.followup.send("API error.", ephemeral=True)
        await interaction.followup.send(
            f"{_fmt_issue(data)}\nExpires: {data.get('expires')}\nDays: {n}", ephemeral=True)


class OwnerTypeView(ui.View):
    """Owner picks what to issue: license key or username+password."""
    def __init__(self):
        super().__init__(timeout=120)

    @ui.button(label="License Key", style=discord.ButtonStyle.primary, emoji="\U0001f511")
    async def on_license(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "Choose a duration:", view=OwnerDurationView("license"), ephemeral=True)

    @ui.button(label="Username + Password", style=discord.ButtonStyle.success, emoji="\U0001f465")
    async def on_user(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "Choose a duration:", view=OwnerDurationView("user"), ephemeral=True)


class OwnerDurationView(ui.View):
    """Shown to the bot owner — choose key duration."""
    def __init__(self, ltype: str = "license"):
        super().__init__(timeout=120)
        self.ltype = ltype

    async def _issue(self, interaction: discord.Interaction, duration: str):
        await interaction.response.defer(ephemeral=True)
        username = f"dc_{interaction.user.id}"
        ltype = self.ltype
        data = await _botkey(username, duration=duration, ltype=ltype,
                             password=_passwd() if ltype == "user" else None)
        if not data.get("ok"):
            return await interaction.followup.send("API error.", ephemeral=True)
        await interaction.followup.send(
            f"{_fmt_issue(data)}\nExpires: {data.get('expires') or 'permanent'}", ephemeral=True)

    @ui.button(label="Permanent", style=discord.ButtonStyle.danger, emoji="\U0001f512")
    async def on_permanent(self, interaction: discord.Interaction, button: ui.Button):
        await self._issue(interaction, "permanent")

    @ui.button(label="48 hours", style=discord.ButtonStyle.primary, emoji="\u23f0")
    async def on_48h(self, interaction: discord.Interaction, button: ui.Button):
        await self._issue(interaction, "48h")

    @ui.button(label="7 days", style=discord.ButtonStyle.primary, emoji="\U0001f4c5")
    async def on_7d(self, interaction: discord.Interaction, button: ui.Button):
        await self._issue(interaction, "7d")

    @ui.button(label="30 days", style=discord.ButtonStyle.primary, emoji="\U0001f4c6")
    async def on_30d(self, interaction: discord.Interaction, button: ui.Button):
        await self._issue(interaction, "30d")

    @ui.button(label="365 days", style=discord.ButtonStyle.primary, emoji="\U0001f4c5")
    async def on_365d(self, interaction: discord.Interaction, button: ui.Button):
        await self._issue(interaction, "1y")

    @ui.button(label="Custom days", style=discord.ButtonStyle.secondary, emoji="\U0001f4c8")
    async def on_custom(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(CustomDaysModal(self.ltype))


# ── /key command ────────────────────────────────────────────────────────────
@tree.command(name="key", description="Generate or claim a key")
async def key_cmd(interaction: discord.Interaction):
    # Owner path
    if interaction.user.id == BOT_OWNER:
        return await interaction.response.send_message(
            "You are the owner. Choose what to issue:", view=OwnerTypeView(), ephemeral=True
        )

    # Normal user path — cooldown check
    allowed, remaining = _user_cooldown_ok(interaction.user.id)
    if not allowed:
        return await interaction.response.send_message(
            f"Your previous key is still active. Please wait **{_format_time(remaining)}** before generating a new one.",
            ephemeral=True,
        )

    await interaction.response.send_message(
        "What do you want?", view=UserKeyTypeView(interaction.user.id), ephemeral=True,
    )


# ── /mykey command — view your active key ───────────────────────────────────
@tree.command(name="mykey", description="Show your active key and expiry")
async def mykey_cmd(interaction: discord.Interaction):
    info = DATA["last_keys"].get(str(interaction.user.id))
    if not info:
        return await interaction.response.send_message("You don't have a key yet. Use `/key` to get one.", ephemeral=True)
    await interaction.response.send_message(
        f"**Your key**\n{info['body']}\nExpires: {info['expires']}", ephemeral=True
    )


# ── /status command — check cooldown ───────────────────────────────────────
@tree.command(name="status", description="Check how long until you can get a new key")
async def status_cmd(interaction: discord.Interaction):
    allowed, remaining = _user_cooldown_ok(interaction.user.id)
    if allowed:
        return await interaction.response.send_message("You can generate a key now! Use `/key`.", ephemeral=True)
    await interaction.response.send_message(
        f"Please wait **{_format_time(remaining)}** before generating a new key.", ephemeral=True
    )


# ── Startup ─────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    ok = await _bootstrap()
    await tree.sync()
    print(f"Logged in as {bot.user}  |  /key synced  |  owner row: {'re-seeded' if ok else 'NOT seeded (check config key)'}")


bot.run(CFG["token"])
