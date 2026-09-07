"""
Discord Key Bot — ISHU AUTH integration
Slash /key command: owner gets permanent/custom-expiry options; normal users get a 48-hour
key after completing a shortener link.
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
NAME     = CFG.get("name", "")
OWNERID  = CFG.get("ownerid", "")
SECRET   = CFG.get("secret", "")
VERSION  = CFG.get("version", "1.0")
SHORTENER = CFG.get("shortener", "")      # destination long URL
VPLINK_API = CFG.get("vplink_api", "")    # VPLINK API token (optional but recommended)
BOT_OWNER = int(CFG.get("owner_id", 0))   # Discord user id of the admin
KEY_HOURS = int(CFG.get("key_hours", 48))
COOLDOWN_HOURS = int(CFG.get("cooldown_hours", 48))
KEY_TYPE = CFG.get("key_type", "license")   # "license" (key only) or "user" (username+password)


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


async def _shorten() -> str | None:
    """Generate a short link via VPLINK API. Returns the short URL, or the raw
    destination link if VPLINK is not configured or fails."""
    if not VPLINK_API or not SHORTENER:
        return SHORTENER or None
    params = {
        "api": VPLINK_API,
        "url": SHORTENER,
        "format": "text",
    }
    async with aiohttp.ClientSession() as s:
        try:
            async with s.get(
                "https://vplink.in/api", params=params,
                timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status == 200:
                    text = (await r.text()).strip()
                    if text.startswith("https://vplink.in/"):
                        return text
        except Exception:
            pass
    return SHORTENER or None


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
class ShortenerView(ui.View):
    """Shown to normal users: shortener link + 'I completed' button."""
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

    @ui.button(label="I completed the link", style=discord.ButtonStyle.success, emoji="\u2705")
    async def on_complete(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This button is not for you.", ephemeral=True)

        allowed, remaining = _user_cooldown_ok(self.user_id)
        if not allowed:
            return await interaction.response.send_message(
                f"Please wait {_format_time(remaining)} before generating a new key.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        username = f"dc_{self.user_id}"
        data = await _botkey(username, duration=f"{KEY_HOURS}h", ltype=KEY_TYPE)

        if not data.get("ok"):
            return await interaction.followup.send("Failed to generate key. Try again later.", ephemeral=True)

        body = _fmt_issue(data)
        expires = data.get("expires", "")

        DATA["cooldowns"][str(self.user_id)] = time.time()
        DATA["last_keys"][str(self.user_id)] = {"body": body, "expires": expires}
        _save_data(DATA)

        try:
            await interaction.user.send(
                f"{body}\nExpires: {expires}"
            )
            await interaction.followup.send("Sent your key via DM!", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(
                f"{body}\nExpires: {expires}\n\n*Could not DM you — please enable DMs.*",
                ephemeral=True,
            )


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

    await interaction.response.defer(ephemeral=True)
    link = await _shorten()
    if not link:
        return await interaction.followup.send("Shortener link is not configured. Contact admin.", ephemeral=True)
    await interaction.followup.send(
        f"Complete the shortener below to receive a **{KEY_HOURS}h** key:\n{link}",
        view=ShortenerView(interaction.user.id),
        ephemeral=True,
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
    await tree.sync()
    print(f"Logged in as {bot.user}  |  /key synced")


bot.run(CFG["token"])
