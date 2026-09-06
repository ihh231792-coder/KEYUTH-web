#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================
 ISHU AUTH - Lite Backend Server (server.py)
 Author: ISHU
============================================
Run:      python server.py
Then:     http://localhost:3000

This server uses a SQLite database — your app/bot (or C#/APK panel)
verifies against it live. The panel's Users page also uses this
server in live DB mode when online.

Endpoints:
  GET  /api/ping
  POST /api/bootstrap            {key, appid, appname}
  GET  /api/licenses?appid=      header: x-api-key
  POST /api/license              {key, appid, username, password, type, duration, hwid}
  POST /api/license/resethwid    {key, appid, id}
  POST /api/license/renew        {key, appid, id, duration}
  POST /api/license/ban          {key, appid, id, banned}
  DELETE /api/license/<id>       body: {key, appid, id}
  POST /api/verify               {key, appid, user, pass, hwid}
"""

import json
import sqlite3
import hashlib
import uuid
import os
import re
import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "ishu_auth.db")
PORT = int(os.environ.get("PORT", "3000"))

DUR_MS = {
    "permanent": 0,
    "1h": 3600 * 1000,
    "3h": 3 * 3600 * 1000,
    "6h": 6 * 3600 * 1000,
    "12h": 12 * 3600 * 1000,
    "24h": 24 * 3600 * 1000,
    "1d": 1 * 24 * 3600 * 1000,
    "3d": 3 * 24 * 3600 * 1000,
    "7d": 7 * 24 * 3600 * 1000,
    "30d": 30 * 24 * 3600 * 1000,
    "90d": 90 * 24 * 3600 * 1000,
    "1y": 365 * 24 * 3600 * 1000,
}

SECRET_PEPPER = "ISHU-AUTH-2026"


def sha(s):
    return hashlib.sha256((s + SECRET_PEPPER).encode("utf-8")).hexdigest().upper()


def gen_key(prefix):
    toks = []
    for _ in range(8):
        toks.append(uuid.uuid4().hex[:4].upper())
    return prefix + "_" + "-".join(toks)


def new_id():
    return uuid.uuid4().hex[:16]


def db_init():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS owners (
            api_key TEXT, appid TEXT, appname TEXT, owner_label TEXT,
            PRIMARY KEY (api_key, appid)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
            id TEXT PRIMARY KEY,
            appid TEXT,
            username TEXT,
            password_hash TEXT,
            type TEXT,
            license_key TEXT,
            hwid TEXT,
            hwid_locked INTEGER DEFAULT 1,
            duration TEXT,
            expires_at INTEGER,
            created_at INTEGER,
            last_login INTEGER,
            banned INTEGER DEFAULT 0
        )
    """)
    cols = [r[1] for r in con.execute("PRAGMA table_info(licenses)")]
    if "hwid_locked" not in cols:
        con.execute("ALTER TABLE licenses ADD COLUMN hwid_locked INTEGER DEFAULT 1")
    con.commit()
    con.close()


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def row2dict(r):
    d = dict(r)
    return d


def ok(**data):
    data.setdefault("ok", True)
    return json.dumps(data).encode("utf-8")


def fail(msg, code=400):
    return (json.dumps({"ok": False, "message": msg}).encode("utf-8"), code)


def _flag(v, default=True):
    if v is None:
        return default
    return str(v).lower() not in ("0", "false", "no", "")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, fmt, *args):
        pass

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not length:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            ctype = (self.headers.get("Content-Type") or "").lower()
            if "application/x-www-form-urlencoded" in ctype:
                from urllib.parse import parse_qs
                return {k: v[0] for k, v in parse_qs(raw).items()}
            return json.loads(raw)
        except Exception:
            return {}

    def _send_json(self, payload, code=200):
        if isinstance(payload, tuple):
            payload, code = payload
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, x-api-key")
        self.send_header("Access-Control-Expose-Headers", "Content-Length")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---------------- API ----------------
    def do_GET(self):
        p = urlparse(self.path)
        if p.path == "/api/ping":
            return self._send_json(ok(version="1.0", server="ishu-auth"))

        if p.path == "/api/licenses":
            api_key = self.headers.get("x-api-key")
            qs = parse_qs(p.query)
            appid = (qs.get("appid") or [""])[0]
            if not api_key or not appid:
                return self._send_json(fail("missing key or appid", 401))
            con = db()
            owner = con.execute("SELECT 1 FROM owners WHERE api_key=? AND appid=?",
                                (api_key, appid)).fetchone()
            if not owner:
                con.close()
                return self._send_json(fail("invalid key/appid", 401))
            rows = con.execute(
                "SELECT * FROM licenses WHERE appid=? ORDER BY created_at DESC", (appid,)
            ).fetchall()
            con.close()
            return self._send_json(ok(list=[row2dict(r) for r in rows]))

        # static files
        return super().do_GET()

    def do_POST(self):
        p = urlparse(self.path)
        body = self._read_json()

        if p.path == "/api/bootstrap":
            key = body.get("key"); appid = body.get("appid"); appname = body.get("appname")
            if not key or not appid:
                return self._send_json(fail("key and appid required"))
            con = db()
            con.execute(
                "INSERT OR REPLACE INTO owners (api_key, appid, appname, owner_label) VALUES (?,?,?,?)",
                (key, appid, appname or "", key[:12]))
            con.commit(); con.close()
            return self._send_json(ok(appid=appid))

        if p.path == "/api/license":
            return self._send_json(self._create_license(body))

        if p.path == "/api/generate":
            return self._send_json(self._create_license(body))

        if p.path == "/api/license/resethwid":
            return self._send_json(self._mutate(body, action="hwid"))

        if p.path == "/api/license/renew":
            return self._send_json(self._mutate(body, action="renew"))

        if p.path == "/api/license/ban":
            return self._send_json(self._mutate(body, action="ban"))

        if p.path == "/api/verify":
            return self._send_json(self._verify(body))

        return self._send_json(fail("unknown api", 404))

    def do_DELETE(self):
        p = urlparse(self.path)
        m = re.match(r"^/api/license/([^/]+)$", p.path)
        if not m:
            return self._send_json(fail("unknown api", 404))
        body = self._read_json()
        return self._send_json(self._mutate(body, action="delete", lic_id=m.group(1)))

    # ---------------- helpers ----------------
    def _authorize(self, key, appid):
        con = db()
        owner = con.execute("SELECT 1 FROM owners WHERE api_key=? AND appid=?", (key, appid)).fetchone()
        con.close()
        return bool(owner)

    def _create_license(self, body):
        key = body.get("key"); appid = body.get("appid")
        if not self._authorize(key, appid):
            return fail("invalid key/appid", 401)
        username = (body.get("username") or "").strip()
        if not username:
            return fail("username required")
        con = db()
        dup = con.execute(
            "SELECT 1 FROM licenses WHERE appid=? AND username=?", (appid, username)).fetchone()
        if dup:
            con.close()
            return fail("user already exists")
        ltype = body.get("type") or "user"
        duration = body.get("duration") or "permanent"
        now = int(datetime.datetime.now().timestamp() * 1000)
        until = body.get("until")
        if until is not None:
            try:
                expires = int(until)
                duration = "until-date"
            except (TypeError, ValueError):
                expires = None
        else:
            ms = DUR_MS.get(duration, 0)
            expires = now + ms if ms else None
        lic = {
            "id": new_id(),
            "appid": appid,
            "username": username,
            "password_hash": sha(body.get("password") or "") if ltype == "user" else None,
            "type": ltype,
            "license_key": body.get("license_key") or gen_key("LIC"),
            "hwid": body.get("hwid") or None,
            "hwid_locked": 1 if _flag(body.get("lock")) else 0,
            "duration": duration,
            "expires_at": expires,
            "created_at": now,
            "last_login": None,
            "banned": 0,
        }
        con.execute(
            "INSERT INTO licenses (id,appid,username,password_hash,type,license_key,hwid,hwid_locked,duration,expires_at,created_at,last_login,banned)"
            " VALUES (:id,:appid,:username,:password_hash,:type,:license_key,:hwid,:hwid_locked,:duration,:expires_at,:created_at,:last_login,:banned)",
            lic)
        con.commit(); con.close()
        return ok(id=lic["id"], license_key=lic["license_key"], username=username,
                  expires=str(datetime.datetime.fromtimestamp(expires / 1000)) if expires else "permanent",
                  expires_at=expires)

    def _mutate(self, body, action, lic_id=None):
        key = body.get("key"); appid = body.get("appid")
        if not self._authorize(key, appid):
            return fail("invalid key/appid", 401)
        lid = lic_id or body.get("id")
        if not lid:
            return fail("id required")
        con = db()
        row = con.execute("SELECT * FROM licenses WHERE id=? AND appid=?", (lid, appid)).fetchone()
        if not row:
            con.close()
            return fail("license not found", 404)
        if action == "hwid":
            con.execute("UPDATE licenses SET hwid=NULL WHERE id=?", (lid,))
            msg = "hwid reset"
        elif action == "renew":
            duration = body.get("duration") or "permanent"
            now = int(datetime.datetime.now().timestamp() * 1000)
            until = body.get("until")
            if until is not None:
                try:
                    expires = int(until)
                    duration = "until-date"
                except (TypeError, ValueError):
                    expires = None
            else:
                ms = DUR_MS.get(duration, 0)
                expires = now + ms if ms else None
            con.execute("UPDATE licenses SET duration=?, expires_at=? WHERE id=?", (duration, expires, lid))
            msg = "renewed"
        elif action == "ban":
            banned = 1 if body.get("banned") else 0
            con.execute("UPDATE licenses SET banned=? WHERE id=?", (banned, lid))
            msg = "banned" if banned else "unbanned"
        else:  # delete
            con.execute("DELETE FROM licenses WHERE id=?", (lid,))
            con.commit(); con.close()
            return ok(message="deleted")
        con.commit(); con.close()
        return ok(message=msg)

    def _verify(self, body):
        key = body.get("key"); appid = body.get("appid")
        user = (body.get("user") or "").strip()
        password = body.get("pass") or ""
        hwid = body.get("hwid") or None
        if not self._authorize(key, appid):
            return fail("invalid key/appid", 401)
        con = db()
        row = con.execute(
            "SELECT * FROM licenses WHERE appid=? AND (username=? OR license_key=?)",
            (appid, user, user)).fetchone()
        if not row:
            con.close()
            return fail("invalid username or license key")
        ltype = row["type"]
        if ltype == "user":
            if sha(password) != row["password_hash"]:
                con.close()
                return fail("invalid password")
        else:
            if password != row["license_key"]:
                con.close()
                return fail("invalid license key")
        if row["banned"]:
            con.close()
            return fail("user banned")
        if row["expires_at"] and int(datetime.datetime.now().timestamp() * 1000) > row["expires_at"]:
            con.close()
            return fail("subscription expired")
        locked = bool(row["hwid_locked"])
        if locked:
            if hwid and row["hwid"] and row["hwid"].lower() != hwid.lower():
                con.close()
                return fail("hwid mismatch")
            new_hwid = row["hwid"] or hwid
        else:
            new_hwid = row["hwid"]
        now = int(datetime.datetime.now().timestamp() * 1000)
        con.execute("UPDATE licenses SET last_login=?, hwid=? WHERE id=?", (now, new_hwid, row["id"]))
        con.commit()
        expires = row["expires_at"]
        con.close()
        return ok(success=True, message="valid",
                  expires=str(datetime.datetime.fromtimestamp(expires / 1000)) if expires else "permanent",
                  username=row["username"], type=ltype)


if __name__ == "__main__":
    db_init()
    print(f"  ISHU AUTH server running -> http://localhost:{PORT}")
    print(f"  SQLite DB: {DB_PATH}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()