## Setup

### 1. Create a Conda environment and install dependencies

Create and activate a new Conda environment:

```bash
conda create -n yt-moderation-bot python=3.11
conda activate yt-moderation-bot
```

Install project dependencies:

```bash
pip install -r requirements.txt
```

---

## Configuration

The bot uses the following environment variables:

```env
TG_BOT_TOKEN=
TG_ADMIN_USER_ID=
TG_ADMIN_CHAT_ID=
CLIENT_SECRET_PATH=
YT_CHANNEL_ID=
```

You will also need these local files in the project directory:

* `stop_words.txt`
* `token.json` — created automatically after the first successful Google OAuth login
* `state.sqlite` — created automatically by the bot if needed

---

## Telegram bot setup

### 2. Create a Telegram bot and get `TG_BOT_TOKEN`, `TG_ADMIN_USER_ID`, `TG_ADMIN_CHAT_ID`

1. Open Telegram and start a chat with **@BotFather**.
2. Send `/newbot` and follow the prompts.
3. BotFather will return a bot token — use it as `TG_BOT_TOKEN`.

To get `TG_ADMIN_USER_ID` and `TG_ADMIN_CHAT_ID`:

1. Open a private chat with your new bot.
2. Send any message, for example `/start`.
3. Open this URL in your browser:

```text
https://api.telegram.org/bot<TG_BOT_TOKEN>/getUpdates
```

4. In the JSON response:

   * `from.id` → use as `TG_ADMIN_USER_ID`
   * `chat.id` → use as `TG_ADMIN_CHAT_ID`

---

## Google Cloud / YouTube setup

### 3. Get `CLIENT_SECRET_PATH` and create `token.json`

This bot uses OAuth 2.0 credentials for the YouTube Data API.

1. Open **Google Cloud Console**.
2. Create a new project or select an existing one.
3. Enable **YouTube Data API v3** for that project.
4. Go to **APIs & Services → Credentials**.
5. Create an **OAuth client ID**.
6. Choose the application type used by your bot flow and download the credentials JSON file.
7. Place that file in the project directory, for example:

```text
client_secret.json
```

8. Set:

```env
CLIENT_SECRET_PATH=client_secret.json
```

To create `token.json`, run the bot once:

```bash
python main.py
```

On the first run, Google will open an OAuth consent flow in the browser. Log in with the YouTube account that owns the channel and approve access. After successful authorization, the bot will save `token.json` locally and reuse it on later runs.

---

### 4. Get `YT_CHANNEL_ID`

1. Sign in to YouTube.
2. Open **Settings**.
3. Go to **Advanced settings**.
4. Copy your **Channel ID**.

Set it as:

```env
YT_CHANNEL_ID=UCxxxxxxxxxxxxxxxxxxxxxx
```

---

## Check remaining YouTube API quota

### 5. View remaining API quota in Google Cloud

To view current quota usage in Google Cloud:

1. Open **Google Cloud** Navigation Menu.
2. Go to **APIs & Services**.
3. Choose **YouTube Data API v3** in the **Enabled APIs & services** tab.
4. Open the **Quotas & System Limits** tab.

The quota resets at 00:00 PT (10AM Moscow time).

---

## Running the bot as a systemd service

This bot can be run as a `systemd` service so it starts automatically after a server reboot and restarts if the Python process exits.

### 1. Find the project directory

Open a terminal and go to the folder where `main.py` is located, then print the absolute path:
```bash
pwd
```
Use this path as `WorkingDirectory` in the service file.

### 2. Find the Python path inside your Conda environment

```bash
conda activate YOUR_ENV_NAME
which python
```

Use this exact path in `ExecStart`.

### 3. Create a systemd service file

Create a new file:

```bash
sudo nano /etc/systemd/system/yt-moderation-bot.service
```

Paste this configuration (Shift+Insert):

```ini
[Unit]
Description=YouTube moderation bot
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/home/your_user/yt-moderation-bot
ExecStart=/home/your_user/miniconda3/envs/ytbot/bin/python /home/your_user/yt-moderation-bot/main.py
Restart=always
RestartSec=10
StartLimitIntervalSec=0
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Replace these values:

* `User` → Linux username
* `WorkingDirectory` → the absolute path to the project folder
* `ExecStart` → the absolute path to Python inside the Conda environment, followed by the absolute path to `main.py`

### 4. Reload systemd and start the service

Run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now yt-moderation-bot.service
```

This will reload systemd configuration, enable automatic startup on boot and start the bot immediately.

### 5. Useful service commands

Restart the bot (stop and start again):

```bash
sudo systemctl restart yt-moderation-bot.service
```

Stop the bot:

```bash
sudo systemctl stop yt-moderation-bot.service
```

Start the bot:

```bash
sudo systemctl start yt-moderation-bot.service
```

Disable automatic startup on boot:

```bash
sudo systemctl disable yt-moderation-bot.service
```

To follow logs in real time:

```bash
journalctl -u yt-moderation-bot.service -f
```

Check service status:
```bash
sudo systemctl status yt-moderation-bot.service
```

If everything is correct, the service should be shown as `active (running)`.


### Important

* This project currently stores runtime state in `state.sqlite`.
* If you change the service file later, reload systemd before restarting the service:

```bash
sudo systemctl daemon-reload
sudo systemctl restart yt-moderation-bot.service
```