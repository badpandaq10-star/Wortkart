"""
WortKart — Flask Backend
Kullanıcı sistemi, global içerikler ve istatistikler SQLite'da tutulur.
"""

from flask import Flask, request, jsonify, send_from_directory, make_response
import sqlite3, hashlib, os, json
from datetime import datetime, date
from functools import wraps
import secrets

app = Flask(__name__, static_folder=".")

# Manuel CORS
@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Token"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

@app.route("/api/<path:path>", methods=["OPTIONS"])
def options_handler(path):
    return make_response("", 204)

DB_PATH = "wortkart.db"
ADMIN_USERNAME = "badpandaq12"
ADMIN_PASSWORD = "1258"

# ─── Veritabanı ──────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            username  TEXT UNIQUE NOT NULL,
            password  TEXT NOT NULL,
            email     TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            last_active TEXT DEFAULT (datetime('now')),
            stats     TEXT DEFAULT '{}',
            badges    TEXT DEFAULT '[]',
            sr_data   TEXT DEFAULT '{}',
            custom_data TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token     TEXT PRIMARY KEY,
            user_id   INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS global_content (
            key   TEXT PRIMARY KEY,
            value TEXT DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS daily_progress (
            user_id INTEGER,
            day     TEXT,
            count   INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, day)
        );
        """)
        # Varsayılan global_content satırlarını ekle
        for k in ["fcWords","arWords","cwSentences","hmWords","xoxQuestions"]:
            conn.execute("INSERT OR IGNORE INTO global_content(key,value) VALUES(?,?)", (k, "[]"))
        # Demo kullanıcısı
        pw = hashlib.sha256("demo123".encode()).hexdigest()
        conn.execute("""INSERT OR IGNORE INTO users(username,password,email,stats)
                        VALUES('demo',?,'','{}')""", (pw,))
        conn.commit()

# ─── Auth yardımcıları ───────────────────────────────────────
def make_token():
    return secrets.token_hex(32)

def get_current_user(token):
    with get_db() as conn:
        row = conn.execute(
            "SELECT u.* FROM users u JOIN sessions s ON u.id=s.user_id WHERE s.token=?", (token,)
        ).fetchone()
    return row

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-Token","")
        user = get_current_user(token)
        if not user:
            return jsonify({"error":"Yetkisiz"}), 401
        request.user = user
        return f(*args, **kwargs)
    return wrapper

def default_stats():
    return {
        "fc":{"correct":0,"total":0},
        "ar":{"correct":0,"total":0},
        "cw":{"correct":0,"errors":0},
        "hm":{"won":0,"lost":0},
        "xox":{"wins":0,"draws":0},
        "points":0, "streak":0,
        "matchWins":0,
        "lastActive": datetime.now().isoformat()
    }

def row_to_user(row):
    d = dict(row)
    d["stats"]       = json.loads(d.get("stats") or "{}")
    d["badges"]      = json.loads(d.get("badges") or "[]")
    d["sr_data"]     = json.loads(d.get("sr_data") or "{}")
    d["custom_data"] = json.loads(d.get("custom_data") or "{}")
    d.pop("password", None)
    return d

# ─── Auth endpointleri ───────────────────────────────────────
@app.route("/api/register", methods=["POST"])
def register():
    data = request.json or {}
    username = data.get("username","").strip()
    password = data.get("password","")
    email    = data.get("email","").strip()

    if not username:
        return jsonify({"error":"Kullanıcı adı gerekli"}), 400
    if len(password) < 4:
        return jsonify({"error":"Şifre en az 4 karakter olmalı"}), 400

    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    stats_json = json.dumps(default_stats())
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users(username,password,email,stats) VALUES(?,?,?,?)",
                (username, pw_hash, email, stats_json)
            )
            conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error":"Bu kullanıcı adı zaten alınmış"}), 409

    return jsonify({"ok": True})

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    username = data.get("username","").strip()
    password = data.get("password","")
    pw_hash  = hashlib.sha256(password.encode()).hexdigest()

    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username=? AND password=?", (username, pw_hash)
        ).fetchone()
        if not user:
            return jsonify({"error":"Kullanıcı adı veya şifre hatalı"}), 401

        token = make_token()
        conn.execute("INSERT INTO sessions(token,user_id) VALUES(?,?)", (token, user["id"]))
        conn.execute("UPDATE users SET last_active=datetime('now') WHERE id=?", (user["id"],))
        conn.commit()

    return jsonify({"token": token, "user": row_to_user(user)})

@app.route("/api/logout", methods=["POST"])
@require_auth
def logout():
    token = request.headers.get("X-Token","")
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()
    return jsonify({"ok": True})

@app.route("/api/me", methods=["GET"])
@require_auth
def me():
    return jsonify(row_to_user(request.user))

# ─── Stats ──────────────────────────────────────────────────
@app.route("/api/stats", methods=["POST"])
@require_auth
def update_stats():
    data  = request.json or {}
    user  = request.user
    stats = json.loads(user["stats"] or "{}")

    # Gelen alanları birleştir
    for key, val in data.items():
        if key == "points":
            stats["points"] = stats.get("points", 0) + val
        elif key in stats and isinstance(stats[key], dict) and isinstance(val, dict):
            for k2, v2 in val.items():
                stats[key][k2] = stats[key].get(k2, 0) + v2
        else:
            stats[key] = val

    stats["lastActive"] = datetime.now().isoformat()

    with get_db() as conn:
        conn.execute("UPDATE users SET stats=?,last_active=datetime('now') WHERE id=?",
                     (json.dumps(stats), user["id"]))
        conn.commit()

    return jsonify({"stats": stats})

# ─── Badges ─────────────────────────────────────────────────
@app.route("/api/badges", methods=["POST"])
@require_auth
def update_badges():
    data   = request.json or {}
    badges = data.get("badges", [])
    with get_db() as conn:
        conn.execute("UPDATE users SET badges=? WHERE id=?",
                     (json.dumps(badges), request.user["id"]))
        conn.commit()
    return jsonify({"ok": True})

# ─── Spaced Repetition ──────────────────────────────────────
@app.route("/api/sr", methods=["POST"])
@require_auth
def update_sr():
    sr_data = request.json or {}
    with get_db() as conn:
        conn.execute("UPDATE users SET sr_data=? WHERE id=?",
                     (json.dumps(sr_data), request.user["id"]))
        conn.commit()
    return jsonify({"ok": True})

# ─── Günlük İlerleme ────────────────────────────────────────
@app.route("/api/daily", methods=["GET"])
@require_auth
def get_daily():
    today = date.today().isoformat()
    with get_db() as conn:
        row = conn.execute(
            "SELECT count FROM daily_progress WHERE user_id=? AND day=?",
            (request.user["id"], today)
        ).fetchone()
    return jsonify({"count": row["count"] if row else 0, "day": today})

@app.route("/api/daily", methods=["POST"])
@require_auth
def add_daily():
    n = (request.json or {}).get("n", 1)
    today = date.today().isoformat()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO daily_progress(user_id,day,count) VALUES(?,?,?)
            ON CONFLICT(user_id,day) DO UPDATE SET count=count+?
        """, (request.user["id"], today, n, n))
        row = conn.execute(
            "SELECT count FROM daily_progress WHERE user_id=? AND day=?",
            (request.user["id"], today)
        ).fetchone()
        conn.commit()
    return jsonify({"count": row["count"] if row else n})

# ─── Global İçerik ──────────────────────────────────────────
@app.route("/api/global", methods=["GET"])
def get_global():
    with get_db() as conn:
        rows = conn.execute("SELECT key,value FROM global_content").fetchall()
    return jsonify({r["key"]: json.loads(r["value"]) for r in rows})

@app.route("/api/global", methods=["POST"])
def set_global():
    # Admin kontrolü
    token = request.headers.get("X-Token","")
    user  = get_current_user(token)
    if not user or user["username"] != ADMIN_USERNAME:
        return jsonify({"error":"Yetkisiz"}), 403

    data = request.json or {}
    with get_db() as conn:
        for key in ["fcWords","arWords","cwSentences","hmWords","xoxQuestions"]:
            if key in data:
                conn.execute("UPDATE global_content SET value=? WHERE key=?",
                             (json.dumps(data[key]), key))
        conn.commit()
    return jsonify({"ok": True})

# ─── Özel Kelimeler (kullanıcıya ait) ───────────────────────
@app.route("/api/custom", methods=["GET"])
@require_auth
def get_custom():
    d = json.loads(request.user["custom_data"] or "{}")
    return jsonify(d)

@app.route("/api/custom", methods=["POST"])
@require_auth
def set_custom():
    data = request.json or {}
    with get_db() as conn:
        conn.execute("UPDATE users SET custom_data=? WHERE id=?",
                     (json.dumps(data), request.user["id"]))
        conn.commit()
    return jsonify({"ok": True})

# ─── Liderboard ─────────────────────────────────────────────
@app.route("/api/leaderboard", methods=["GET"])
def leaderboard():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT username, stats FROM users ORDER BY CAST(json_extract(stats,'$.points') AS INTEGER) DESC LIMIT 50"
        ).fetchall()
    result = []
    for r in rows:
        stats = json.loads(r["stats"] or "{}")
        result.append({"username": r["username"], "points": stats.get("points", 0)})
    return jsonify(result)

# ─── Admin ──────────────────────────────────────────────────
@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.json or {}
    if data.get("password") != ADMIN_PASSWORD:
        return jsonify({"error":"Şifre hatalı"}), 403
    return jsonify({"ok": True})

@app.route("/api/admin/users", methods=["GET"])
def admin_users():
    token = request.headers.get("X-Token","")
    user  = get_current_user(token)
    if not user or user["username"] != ADMIN_USERNAME:
        return jsonify({"error":"Yetkisiz"}), 403

    with get_db() as conn:
        rows = conn.execute(
            "SELECT id,username,email,created_at,last_active,stats,badges FROM users"
        ).fetchall()
    return jsonify([{
        "id": r["id"], "username": r["username"], "email": r["email"],
        "created_at": r["created_at"], "last_active": r["last_active"],
        "stats": json.loads(r["stats"] or "{}"),
        "badges": json.loads(r["badges"] or "[]")
    } for r in rows])

@app.route("/api/admin/reset_user", methods=["POST"])
def admin_reset_user():
    token = request.headers.get("X-Token","")
    user  = get_current_user(token)
    if not user or user["username"] != ADMIN_USERNAME:
        return jsonify({"error":"Yetkisiz"}), 403

    user_id = (request.json or {}).get("user_id")
    with get_db() as conn:
        conn.execute("UPDATE users SET stats=?,badges='[]' WHERE id=?",
                     (json.dumps(default_stats()), user_id))
        conn.commit()
    return jsonify({"ok": True})

# ─── Static files ────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(".", "index.html")

# ─── Main ────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    print("✅ WortKart sunucusu başlatıldı → http://localhost:5000")
    app.run(debug=True, port=5000)
