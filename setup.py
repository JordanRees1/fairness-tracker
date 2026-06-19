#!/usr/bin/env python3
"""Interactive setup for the Fairness Tracker.

Creates the SQLite database, the two users, and the admin/config settings.
Re-run any time to reconfigure (it will ask before overwriting existing data).
"""

import os
import sys
import json
import getpass
import secrets
import sqlite3

from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("FAIRNESS_DB", os.path.join(BASE_DIR, "fairness.db"))
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")


def prompt(label, default=None):
    suffix = f" [{default}]" if default else ""
    val = input(f"{label}{suffix}: ").strip()
    return val or (default or "")


def prompt_pin(label):
    while True:
        pin = getpass.getpass(f"{label} (digits, hidden): ").strip()
        if pin.isdigit() and len(pin) >= 4:
            return pin
        print("  PIN must be at least 4 digits.")


def prompt_secret(label):
    while True:
        a = getpass.getpass(f"{label} (hidden): ")
        b = getpass.getpass("  confirm: ")
        if a and a == b:
            return a
        print("  Empty or mismatch, try again.")


def main():
    if os.path.exists(DB_PATH):
        ans = input(f"{DB_PATH} already exists. Overwrite ALL data? [y/N]: ").strip().lower()
        if ans != "y":
            print("Aborted.")
            sys.exit(0)
        os.remove(DB_PATH)

    print("\n--- Users ---")
    name1 = prompt("Person 1 name", "Jordan")
    pin1 = prompt_pin(f"{name1}'s PIN")
    name2 = prompt("Person 2 name", "Scarlet")
    pin2 = prompt_pin(f"{name2}'s PIN")
    if pin1 == pin2:
        print("\nThe two PINs must be different (the PIN is how the app tells you apart).")
        sys.exit(1)

    print("\n--- Settings ---")
    while True:
        try:
            fairness = int(prompt("Fairness parameter F", "2"))
            if fairness >= 1:
                break
        except ValueError:
            pass
        print("  Must be a whole number >= 1.")

    print("\n--- Admin ---")
    admin_pw = prompt_secret("Admin password")
    default_path = secrets.token_urlsafe(9)
    admin_path = prompt("Admin URL token (the /admin/<token> path)", default_path)

    con = sqlite3.connect(DB_PATH)
    with open(SCHEMA_PATH) as f:
        con.executescript(f.read())

    con.execute(
        "INSERT INTO users(key,name,pin_hash,count) VALUES(?,?,?,0)",
        ("jordan", name1, generate_password_hash(pin1)),
    )
    con.execute(
        "INSERT INTO users(key,name,pin_hash,count) VALUES(?,?,?,0)",
        ("scarlet", name2, generate_password_hash(pin2)),
    )
    for k, v in {
        "fairness_param": str(fairness),
        "admin_pw_hash": generate_password_hash(admin_pw),
        "admin_path": admin_path,
    }.items():
        con.execute("INSERT INTO config(key,value) VALUES(?,?)", (k, v))
    con.commit()
    con.close()

    print("\nDone. Database created at", DB_PATH)
    print(f"Admin panel:  /admin/{admin_path}")
    print("Start locally with:  python app.py   (then open http://localhost:8000)")


if __name__ == "__main__":
    main()
