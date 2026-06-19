"""Fairness Tracker — a tiny Flask app for two people.

Each person has a counter. You may log the activity only if doing so keeps
your lead within the fairness parameter F:

    your_count + 1 - their_count <= F

The "Can I?" check evaluates this rule; "I did it" re-evaluates it atomically
before incrementing, so a stale green screen can't push you past the limit.
"""

import os
import json
import time
import sqlite3
import threading
from datetime import datetime
from functools import wraps

from flask import (
    Flask, g, request, session, redirect, url_for, render_template, abort, flash
)
from werkzeug.security import check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("FAIRNESS_DB", os.path.join(BASE_DIR, "fairness.db"))
SECRET_KEY_PATH = os.path.join(BASE_DIR, ".secret_key")

app = Flask(__name__)


def _load_secret_key():
    """Persist a secret key on disk so sessions survive restarts."""
    if os.path.exists(SECRET_KEY_PATH):
        with open(SECRET_KEY_PATH, "rb") as f:
            return f.read()
    key = os.urandom(32)
    with open(SECRET_KEY_PATH, "wb") as f:
        f.write(key)
    os.chmod(SECRET_KEY_PATH, 0o600)
    return key


app.secret_key = _load_secret_key()

# Serialises the read-check-increment in /did. With one gunicorn worker this is
# already serial, but the dev server is threaded, so we lock to be safe.
_write_lock = threading.Lock()

# --- Simple in-memory login lockout (per IP) -------------------------------
_fail = {}            # bucket -> [fail_count, first_fail_ts]
LOCK_MAX = 5          # allowed failures within the window
LOCK_WINDOW = 300     # seconds


def check_lockout(bucket):
    rec = _fail.get(bucket)
    return bool(rec and rec[0] >= LOCK_MAX and (time.time() - rec[1]) < LOCK_WINDOW)


def record_fail(bucket):
    rec = _fail.get(bucket)
    if not rec or (time.time() - rec[1]) >= LOCK_WINDOW:
        _fail[bucket] = [1, time.time()]
    else:
        rec[0] += 1


def clear_fail(bucket):
    _fail.pop(bucket, None)


# --- Database helpers ------------------------------------------------------
def get_db():
    if "db" not in g:
        if not os.path.exists(DB_PATH):
            abort(500, "Database not found. Run setup.py first.")
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def get_config(key, default=None):
    row = get_db().execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_config(key, value):
    db = get_db()
    db.execute(
        "INSERT INTO config(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    db.commit()


def get_users():
    """Return {key: row} for the two users, ordered by id."""
    rows = get_db().execute("SELECT * FROM users ORDER BY id").fetchall()
    return {r["key"]: r for r in rows}


def fairness_param():
    return int(get_config("fairness_param", "2"))


def can_do(user_key):
    """True if user_key may increment without exceeding the fairness lead."""
    users = get_users()
    me = users[user_key]
    other = next(u for k, u in users.items() if k != user_key)
    return (me["count"] + 1 - other["count"]) <= fairness_param()


def log_event(user_key, action, result):
    db = get_db()
    counts = {k: u["count"] for k, u in get_users().items()}
    db.execute(
        "INSERT INTO events(ts,user_key,action,result,counts) VALUES(?,?,?,?,?)",
        (datetime.now().isoformat(sep=" ", timespec="seconds"),
         user_key, action, result, json.dumps(counts)),
    )
    db.commit()


# --- Auth guards -----------------------------------------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return wrapper


def require_token(token):
    """404 unless the URL token matches the configured admin path."""
    if token != get_config("admin_path"):
        abort(404)


def require_admin(token):
    require_token(token)
    if not session.get("admin"):
        abort(403)


# --- User-facing routes ----------------------------------------------------
@app.route("/")
def index():
    if session.get("user"):
        return redirect(url_for("home"))
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login():
    ip = request.remote_addr or "?"
    if check_lockout("pin:" + ip):
        flash("Too many attempts. Wait a few minutes.")
        return redirect(url_for("index"))

    pin = request.form.get("pin", "").strip()
    for key, u in get_users().items():
        if u["pin_hash"] and check_password_hash(u["pin_hash"], pin):
            clear_fail("pin:" + ip)
            session.clear()
            session["user"] = key
            return redirect(url_for("home"))

    record_fail("pin:" + ip)
    flash("Incorrect PIN.")
    return redirect(url_for("index"))


@app.route("/home")
@login_required
def home():
    me = get_users()[session["user"]]
    return render_template("home.html", name=me["name"])


@app.route("/check", methods=["POST"])
@login_required
def check():
    key = session["user"]
    allowed = can_do(key)
    log_event(key, "check", "allowed" if allowed else "blocked")
    return render_template("result.html", allowed=allowed, did=False)


@app.route("/did", methods=["POST"])
@login_required
def did():
    key = session["user"]
    with _write_lock:
        allowed = can_do(key)          # re-check; state may have changed
        if allowed:
            db = get_db()
            db.execute("UPDATE users SET count = count + 1 WHERE key=?", (key,))
            db.commit()
            log_event(key, "did", "allowed")
        else:
            log_event(key, "did", "blocked")
    return render_template("result.html", allowed=allowed, did=True)


@app.route("/logout", methods=["POST"])
def logout():
    session.pop("user", None)
    return redirect(url_for("index"))


# --- Admin routes ----------------------------------------------------------
@app.route("/admin/<token>")
def admin(token):
    require_token(token)
    if not session.get("admin"):
        return render_template("admin_login.html", token=token)

    users = get_users()
    name_map = {k: u["name"] for k, u in users.items()}
    rows = get_db().execute(
        "SELECT * FROM events ORDER BY id DESC LIMIT 200"
    ).fetchall()
    events = []
    for e in rows:
        counts = json.loads(e["counts"]) if e["counts"] else {}
        events.append({
            "ts": e["ts"],
            "who": name_map.get(e["user_key"], e["user_key"]),
            "action": e["action"],
            "result": e["result"],
            "counts": ", ".join(f"{name_map.get(k, k)}: {v}"
                                for k, v in counts.items()),
        })
    return render_template(
        "admin.html", token=token, users=list(users.values()),
        events=events, F=fairness_param(),
    )


@app.route("/admin/<token>/login", methods=["POST"])
def admin_login(token):
    require_token(token)
    ip = request.remote_addr or "?"
    if check_lockout("admin:" + ip):
        flash("Too many attempts. Wait a few minutes.")
        return redirect(url_for("admin", token=token))

    stored = get_config("admin_pw_hash", "")
    if stored and check_password_hash(stored, request.form.get("password", "")):
        clear_fail("admin:" + ip)
        session["admin"] = True
        return redirect(url_for("admin", token=token))

    record_fail("admin:" + ip)
    flash("Incorrect password.")
    return redirect(url_for("admin", token=token))


@app.route("/admin/<token>/reset", methods=["POST"])
def admin_reset(token):
    require_admin(token)
    db = get_db()
    db.execute("UPDATE users SET count = 0")
    db.commit()
    log_event("admin", "reset", "ok")
    flash("Counters reset to 0.")
    return redirect(url_for("admin", token=token))


@app.route("/admin/<token>/config", methods=["POST"])
def admin_config(token):
    require_admin(token)
    try:
        f = int(request.form.get("fairness_param", ""))
        if f < 1:
            raise ValueError
    except ValueError:
        flash("Fairness parameter must be a whole number >= 1.")
        return redirect(url_for("admin", token=token))
    set_config("fairness_param", f)
    flash(f"Fairness parameter set to {f}.")
    return redirect(url_for("admin", token=token))


@app.route("/admin/<token>/adjust", methods=["POST"])
def admin_adjust(token):
    require_admin(token)
    key = request.form.get("user", "")
    if key not in get_users():
        abort(400)
    try:
        delta = int(request.form.get("delta", ""))
    except ValueError:
        abort(400)
    db = get_db()
    db.execute("UPDATE users SET count = MAX(0, count + ?) WHERE key=?", (delta, key))
    db.commit()
    log_event("admin", "adjust", f"{key}{'+' if delta >= 0 else ''}{delta}")
    return redirect(url_for("admin", token=token))


@app.route("/admin/<token>/logout", methods=["POST"])
def admin_logout(token):
    require_token(token)
    session.pop("admin", None)
    return redirect(url_for("admin", token=token))


if __name__ == "__main__":
    # Local development only. On the Pi this runs under gunicorn (see README).
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=True)
