# YT Shorts Reposter

## Fast, safe Termux migration

The GitHub repository must contain code only. Do **not** commit `config.yaml`,
`credentials/`, `shorts.db`, `state.json`, logs, or downloaded videos: they
contain account access, a Discord webhook, and upload history. `.gitignore`
already excludes them.

On this computer, create a private phone-transfer bundle while the bot can be
running safely:

```powershell
python tools/export_private_state.py "$HOME\Downloads\yt-reposter-private"
```

Transfer the resulting `yt-reposter-private` folder directly to the phone
(USB is best). Do not upload it to GitHub, Drive, or a chat app. On the phone,
install Termux from F-Droid and then run:

```sh
pkg install -y git
git clone <YOUR-GITHUB-REPOSITORY-URL> youtube-reposter
cd ~/youtube-reposter
sh termux/install.sh
termux-setup-storage
```

Place the private bundle at
`~/storage/downloads/yt-reposter-private/`, then import and start it:

```sh
cd ~/youtube-reposter
sh termux/import-private-state.sh
nohup sh termux/service.sh >/dev/null 2>&1 &
```

This reuses the existing OAuth token, OAuth client, Discord settings, and
duplicate-history database, so it does not need another Google login. The
service keeps running during a 10-minute or 5-hour Wi-Fi outage and does a
fresh check within about 10 seconds after YouTube becomes reachable.

For automatic recovery after a full phone reboot, install the separate
**Termux:Boot** app from F-Droid, open it once, then run:

```sh
mkdir -p ~/.termux/boot
cp ~/youtube-reposter/termux/boot-start.sh ~/.termux/boot/start-yt-reposter
chmod +x ~/.termux/boot/start-yt-reposter
```

In Android settings, set both Termux and Termux:Boot battery usage to
**Unrestricted**. Android otherwise may kill background work regardless of
the Python code. To inspect the service: `tail -f ~/youtube-reposter/logs/service.log`.

To publish the safe repository from this computer after checking the ignored
files, create an empty GitHub repository and run:

```powershell
git init
git add .
git status --ignored
git commit -m "Termux-ready YouTube reposter"
git branch -M main
git remote add origin <YOUR-GITHUB-REPOSITORY-URL>
git push -u origin main
```

`git status --ignored` must show the private files as ignored, never staged.
If a real Discord webhook was ever committed or posted publicly, regenerate it
in Discord before publishing.

Watches **Channel A** (a channel you own or are authorized to use) for its
newest Short, and automatically uploads it to
**Channel B** (your channel) — same title, same description, no duplicates,
runs forever, and recovers from crashes/reboots/internet loss on its own.

This guide assumes you have **never done this before**. Every step is spelled
out. Follow them in order.

---

## Table of contents

1. [What you need before starting](#1-what-you-need-before-starting)
2. [Install Termux + Debian (on your Android phone)](#2-install-termux--debian-on-your-android-phone)
3. [Get the project files onto the phone](#3-get-the-project-files-onto-the-phone)
4. [Install Python packages](#4-install-python-packages)
5. [Find Channel A's Channel ID](#5-find-channel-as-channel-id)
6. [Set up Channel B on Google Cloud (OAuth)](#6-set-up-channel-b-on-google-cloud-oauth)
7. [Set up the Discord webhook (optional but recommended)](#7-set-up-the-discord-webhook-optional-but-recommended)
8. [Fill in config.yaml](#8-fill-in-configyaml)
9. [First run — the one manual step](#9-first-run--the-one-manual-step)
10. [Keep it running forever](#10-keep-it-running-forever)
11. [How to check it's working](#11-how-to-check-its-working)
12. [How duplicate protection works](#12-how-duplicate-protection-works)
13. [Troubleshooting](#13-troubleshooting)
14. [Database schema](#14-database-schema)
15. [Folder structure](#15-folder-structure)

---

## 1. What you need before starting

- An Android phone with some free storage (a few GB is plenty).
- A Google account for **Channel B** — the channel that will receive the
  reposted videos. You need to be able to log into this account.
- The **Channel ID or URL** of **Channel A** — the channel you're copying
  Shorts from. You don't need to own it or log into it.
- (Optional) A Discord server where you want status messages sent.
- About 20–30 minutes, mostly waiting for installs.

---

## 2. Install Termux + Debian (on your Android phone)

> Skip this section if Debian is already installed and running inside Termux.

1. Install **Termux** from F-Droid (not the Play Store version — it's
   outdated): https://f-droid.org/packages/com.termux/
2. Open Termux and run:
   ```bash
   pkg update -y && pkg upgrade -y
   pkg install -y proot-distro
   proot-distro install debian
   proot-distro login debian
   ```
3. You are now inside a Debian Linux shell running on your phone. Every
   command from here on is typed inside this Debian shell (run
   `proot-distro login debian` again any time you reopen Termux).
4. Install the basics:
   ```bash
   apt update && apt install -y python3 python3-pip python3-venv ffmpeg git nano
   ```

---

## 3. Get the project files onto the phone

If you already have this project's folder on your computer, copy every file
in it (`main.py`, `config.yaml`, all the `.py` files, `requirements.txt`,
etc.) into a folder on the phone, e.g. `~/yt-reposter/`. The easiest way is:

- Zip the project folder on your computer.
- Transfer the zip to the phone (USB cable, Google Drive, Telegram — whatever
  is easiest).
- Inside Debian:
  ```bash
  mkdir -p ~/yt-reposter
  cd ~/yt-reposter
  unzip /path/to/project.zip
  ```

If instead the project lives in a Git repository, just:
```bash
git clone <your-repo-url> ~/yt-reposter
cd ~/yt-reposter
```

From now on, every command in this guide is run from inside that project
folder (`cd ~/yt-reposter`).

---

## 4. Install Python packages

Still inside the project folder:

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

`source venv/bin/activate` needs to be run **every time you open a new
terminal** before running the bot. (The restart-forever script in
[section 10](#10-keep-it-running-forever) already does this for you.)

---

## 5. Find Channel A's Channel ID

Channel A is the channel you're copying Shorts **from**. You do not need to
log into it or own it — you only need its ID.

A channel ID always looks like `UC` followed by 22 characters, e.g.
`UCX6OQ3DkcsbYNE6H8uQQuVA`.

**If the channel's URL already looks like `youtube.com/channel/UCxxxxxxx...`**
— that's it, copy the part starting with `UC`.

**If the channel's URL instead looks like `youtube.com/@somehandle`** (most
channels today), you need one extra step to find the real ID:

1. Open the channel in a **desktop browser** (not the phone app).
2. Right-click anywhere on the page → **View Page Source** (or press
   `Ctrl+U`).
3. Press `Ctrl+F` to search the page source for the text `"channelId"`.
4. You'll see something like `"channelId":"UCX6OQ3DkcsbYNE6H8uQQuVA"` — copy
   the `UC...` value (without the quotes).

Keep this ID handy — it goes into `config.yaml` in [step 8](#8-fill-in-configyaml).

---

## 6. Set up Channel B on Google Cloud (OAuth)

Channel B is **your** channel — the one that will receive the uploads. YouTube
requires every app that uploads videos to identify itself via a Google Cloud
project and ask your permission once. This is a one-time setup.

### 6.1 Create a Google Cloud project

1. Go to https://console.cloud.google.com/ and log in with the Google account
   that owns/manages **Channel B**.
2. Click the project dropdown at the top → **New Project**.
3. Give it any name (e.g. "yt-reposter") → **Create**.
4. Wait a few seconds, then select the new project from the dropdown so it's
   active.

### 6.2 Enable the YouTube Data API

1. In the search bar at the top, type **YouTube Data API v3** and open it.
2. Click **Enable**.

### 6.3 Configure the OAuth consent screen

1. In the left sidebar, go to **APIs & Services → OAuth consent screen**.
2. User Type: choose **External** → **Create**.
3. Fill in the required fields: App name (anything, e.g. "YT Reposter"),
   User support email (your email), Developer contact email (your email).
   Leave everything else default → **Save and Continue** through each page.
4. On the **Scopes** page, you can just click **Save and Continue** (no
   changes needed).
5. On the **Test users** page, click **Add Users** and add the exact Gmail
   address that owns Channel B. This is required — without it, login will be
   rejected. → **Save and Continue**.
6. Click **Back to Dashboard**. The app will stay in "Testing" mode, which is
   fine — it works indefinitely as long as your account is listed as a test
   user.

### 6.4 Create the OAuth client credentials

1. Go to **APIs & Services → Credentials**.
2. Click **+ Create Credentials → OAuth client ID**.
3. Application type: **Desktop app**.
4. Name: anything (e.g. "yt-reposter-desktop") → **Create**.
5. A popup shows your client ID/secret — click **Download JSON**.
6. Rename the downloaded file to `client_secret.json`.

### 6.5 Put the credentials file in place

Inside the project folder on your phone:

```bash
mkdir -p credentials
```

Move/copy the downloaded `client_secret.json` into that `credentials/`
folder, so the final path is `~/yt-reposter/credentials/client_secret.json`
(same as the phone transfer method you used in step 3 — USB, Drive,
Telegram, etc.).

You do **not** need to create `token.json` yourself — it's generated
automatically the first time you run the bot (see [section 9](#9-first-run--the-one-manual-step)).

---

## 7. Set up the Discord webhook (optional but recommended)

This lets the bot message you every time it starts, uploads, fails, or has a
problem. Skip this whole section and set `discord.enabled: false` in
`config.yaml` if you don't want notifications.

1. Open Discord, go to the server/channel where you want messages posted.
2. Click the gear icon next to the channel name → **Integrations → Webhooks**.
3. Click **New Webhook** (or **Create Webhook**).
4. Give it a name (e.g. "YT Reposter Bot") → **Copy Webhook URL**.
5. Keep that URL handy — it goes into `config.yaml` next.

Treat this URL like a password: anyone who has it can post messages into that
channel.

---

## 8. Fill in config.yaml

Inside the project folder:

```bash
cp config.example.yaml config.yaml
nano config.yaml
```

Edit these values (everything else can stay as-is):

| Key | What to put there |
|---|---|
| `source_channel.channel_id` | Channel A's ID from [section 5](#5-find-channel-as-channel-id) |
| `destination_channel.oauth_client_json` | Leave as `credentials/client_secret.json` if you followed section 6.5 exactly |
| `destination_channel.token_json` | Leave as `credentials/token.json` — created automatically |
| `discord.enabled` | `true` if you set up Discord, otherwise `false` |
| `discord.webhook_url` | The webhook URL from [section 7](#7-set-up-the-discord-webhook-optional-but-recommended) (leave the placeholder if `discord.enabled` is `false`) |

Everything else (`check_interval_minutes`, `max_retry_attempts`, etc.) has
sane defaults — leave them unless you know you want to change them.

Save and exit nano: `Ctrl+O`, then `Enter`, then `Ctrl+X`.

---

## 9. First run — the one manual step

This is the only time you'll need to interact with the bot by hand. It needs
you to prove, once, that you own Channel B.

```bash
source venv/bin/activate
python main.py
```

What happens:

1. The bot checks disk space, the database, and your internet connection.
2. Because there's no `token.json` yet, it prints a long Google login URL in
   the terminal.
3. Copy that URL and open it in **any browser** (phone or computer — it
   doesn't need to be on the same device).
4. Log in with the Google account that owns **Channel B**.
5. You'll see a warning that says the app isn't verified — this is expected
   because the app is in "Testing" mode (section 6.3). Click **Advanced →
   Go to (your app name) (unsafe)**, then **Allow** on the permissions
   screen.
6. Google shows you an authorization code (or redirects — either way, follow
   what the terminal instructions say) — copy the code and paste it back
   into the terminal where the bot is waiting, then press Enter.
7. The bot saves `credentials/token.json` and continues running normally.
   You will **never have to do this again** — it refreshes itself silently
   forever, unless you manually revoke access from your Google account.

Leave it running for a minute to confirm it doesn't immediately crash, then
press `Ctrl+C` to stop it — you're ready for the next section.

---

## 10. Keep it running forever

The bot needs to keep running 24/7 to actually catch new Shorts. Termux has
no `systemd`, so use a simple restart-forever loop plus Termux:Boot so it
survives phone reboots.

### 10.1 The restart loop

Create a small script:

```bash
nano ~/yt-reposter/run.sh
```

Paste this in:

```bash
#!/bin/bash
cd ~/yt-reposter
source venv/bin/activate
while true; do
  python main.py
  echo "Bot exited, restarting in 10 seconds..."
  sleep 10
done
```

Save (`Ctrl+O`, `Enter`, `Ctrl+X`), then make it executable:

```bash
chmod +x ~/yt-reposter/run.sh
```

### 10.2 Run it inside tmux (so it survives closing Termux)

```bash
pkg install -y tmux      # inside Debian; if unavailable, run in Termux itself
tmux new -s ytbot
proot-distro login debian    # if tmux is running in Termux, not Debian
~/yt-reposter/run.sh
```

Detach without stopping it: press `Ctrl+B`, then `D`. Reattach any time with
`tmux attach -t ytbot`.

### 10.3 Auto-start on phone reboot (Termux:Boot)

1. Install **Termux:Boot** from F-Droid:
   https://f-droid.org/packages/com.termux.boot/
2. Open Termux:Boot once (it just needs to run once to register itself).
3. In Termux (not Debian), create:
   ```bash
   mkdir -p ~/.termux/boot
   nano ~/.termux/boot/start-ytbot.sh
   ```
4. Paste:
   ```bash
   #!/bin/bash
   termux-wake-lock
   proot-distro login debian -- bash -c "~/yt-reposter/run.sh"
   ```
5. Save, then `chmod +x ~/.termux/boot/start-ytbot.sh`.
6. Also disable battery optimization for Termux in your phone's Android
   settings (Settings → Apps → Termux → Battery → Unrestricted), otherwise
   Android may kill it in the background.

---

## 11. How to check it's working

- Watch the terminal output while it runs — it logs each check cycle.
- Check `logs/app.log` for a running history:
  ```bash
  tail -f ~/yt-reposter/logs/app.log
  ```
- If Discord is enabled, you'll get a message when the bot starts, when it
  finds a new Short, when it uploads, and a daily summary every 24 hours.
- A `shorts.db` file and `state.json` will appear in the project folder once
  it's run at least one cycle.

---

## 12. How duplicate protection works

The SQLite `uploaded_videos` table is the source of truth for what has
already been reposted — every successful upload is recorded there, and every
new candidate from Channel A is checked against it **before** download even
starts.

`state.json` covers the edge case where the process dies *after* uploading to
Channel B but *before* the database write is saved: on the next run, the bot
checks whether a video with the same title already exists on Channel B before
attempting to upload it again — so it can't accidentally double-post even
after a crash mid-upload.

---

## 13. Troubleshooting

- **"Token expired / revoked" or login errors**: delete
  `credentials/token.json` and run `python main.py` again — it'll walk you
  through the login step again (section 9).
- **Database corruption**: look for a file named
  `shorts.db.corrupt.<some number>` — the bot automatically quarantines a
  corrupt database and builds a fresh one on startup. Nothing to do; you'll
  just lose duplicate-history for videos uploaded before the corruption.
- **Disk full**: free up space on the phone — the bot refuses to download
  below 500MB free space and will alert you instead of failing silently.
- **Quota errors** (`QuotaExceededError` in the logs / Discord): YouTube caps
  free API usage at 10,000 units/day. Just wait — it resets daily around
  midnight Pacific time, and the bot automatically resumes on its own.
- **"Internet unavailable. Waiting..." forever**: check the phone's Wi-Fi or
  mobile data. The bot checks every 30 seconds and resumes automatically as
  soon as connectivity returns — no restart needed.
- **App got killed after closing Termux**: make sure you're running it inside
  `tmux` (section 10.2) and that battery optimization is disabled for Termux
  (section 10.3, step 6).
- **Google says "app isn't verified"**: this is expected and safe for your
  own use (section 6.3 keeps the app in Testing mode) — click through
  Advanced → Go to (app name).

---

## 14. Database schema

```sql
CREATE TABLE uploaded_videos (
    video_id          TEXT PRIMARY KEY,  -- Channel A's original video ID
    upload_date       TEXT NOT NULL,     -- ISO-8601 UTC timestamp
    uploaded_video_id TEXT NOT NULL,     -- the new video ID on Channel B
    title             TEXT NOT NULL
);
```

---

## 15. Folder structure

```
yt-reposter/
├── main.py                # entry point — run this
├── run.sh                 # restart-forever wrapper you create in section 10
├── scheduler.py            # forever-loop, heartbeat, daily summary
├── config.yaml              # your real settings (private, don't share)
├── config.example.yaml      # template with comments
├── requirements.txt
├── utils.py, logger.py, state.py, database.py, notifier.py
├── network.py, retry.py, youtube_api.py, downloader.py, uploader.py
├── credentials/
│   ├── client_secret.json   # from Google Cloud (section 6.4)
│   └── token.json           # auto-created on first login (section 9)
├── downloads/                # temporary video files, auto-cleaned
├── logs/
│   ├── app.log
│   ├── error.log
│   └── upload.log
├── shorts.db                 # duplicate-protection database
└── state.json                 # crash-recovery state
```
