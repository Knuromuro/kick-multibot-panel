# KickBot

KickBot provides a simple web panel for launching Selenium based bots for Kick.com.
Accounts and bot groups are defined in `data.json` and can be started from the dashboard after logging in.

## Features

- Login page with fixed `admin/admin` credentials
- Dashboard listing groups with buttons to start them or all at once
- JSON configuration for accounts and groups
- Selenium bot runner that logs in and reads per account message files
- Flash messages showing operation status

## Running

Install dependencies and start the web app:

```bash
pip install -r requirements.txt
python -m app.app
```

Open [http://localhost:5000/login](http://localhost:5000/login) and log in with `admin/admin`.

## Configuration

Edit `data.json` to configure accounts and groups. Each account may specify a proxy. Message
files should be stored in the `messages/` directory using the account id as the filename
(e.g. `messages/1.txt`).

Bots are launched in separate processes using `subprocess.Popen` and will open Chrome windows
when executed.
