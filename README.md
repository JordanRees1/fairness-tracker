# Fairness Tracker

A tiny two-person fairness tracker. Each person has a counter; you may log the
activity only if doing so keeps your lead within the fairness parameter `F`:

```
your_count + 1 - their_count <= F
```

The **"Can I?"** button shows a full-screen **green (Yes)** or **red (No)**.
On green, **"I did it"** increments your counter — but the server re-checks the
rule at that moment, so a stale screen can never push you past the limit.

## Stack
Flask + SQLite, served by gunicorn (1 worker). No JS framework. Built to run on
a Raspberry Pi 4B with a tiny memory footprint, reached over Tailscale.

## Run locally (laptop)

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python setup.py        # set names, PINs, admin password, F, admin URL token
./venv/bin/python app.py          # dev server on http://localhost:8000
```

- User entry: <http://localhost:8000> — each person logs in with their own PIN.
- Admin: `http://localhost:8000/admin/<token>` — the token is printed by `setup.py`.

`setup.py` creates `fairness.db`. A persistent session key is written to
`.secret_key` on first run. Both are git-ignored and never leave the machine.

## Deploy to the Raspberry Pi

The app only needs to be reachable over your tailnet — no port forwarding or
public HTTPS. Tailscale encrypts the transport.

```bash
# on the Pi
git clone <repo> /home/pi/fairness   # or copy the folder over
cd /home/pi/fairness
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python setup.py           # set your real PINs / admin password

# install the service (edit User/paths in fairness.service first if not 'pi')
sudo cp fairness.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fairness
```

Find the Pi's tailnet address and open it from either phone:

```bash
tailscale ip -4          # e.g. 100.x.y.z  -> http://100.x.y.z:8000
```

Or use the MagicDNS name: `http://<pi-hostname>:8000`.

Optional — HTTPS + a clean hostname via Tailscale:

```bash
sudo tailscale serve --bg 8000       # serves it at https://<pi-hostname>.<tailnet>.ts.net
```

Then tighten the bind to localhost in `fairness.service`
(`--bind 127.0.0.1:8000`) so only `tailscale serve` exposes it.

## Admin panel
- See both counters and adjust them ±1 (e.g. to correct a mistake).
- Reset both to 0.
- Change the fairness parameter `F` live.
- Full activity log: every login check and "I did it", who did it, when, the
  result (allowed/blocked), and the counter snapshot at that moment.

## Reconfigure later
Re-run `./venv/bin/python setup.py` (it asks before overwriting). To change just
`F`, use the admin panel instead.
