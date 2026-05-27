# IMS Data Fetcher — cPanel Deployment Guide

## Overview

This guide walks you through deploying the IMS Data Fetcher on a cPanel shared hosting server. The application logs into the **XIMS (Internet Management System)** panel at `ims.marvellousfiber.com/Admin`, fetches upcoming renewal data, and exports it to CSV (and optionally MySQL).

---

## What You Need Before Starting

| Requirement | Details |
|-------------|---------|
| cPanel hosting | With SSH access or Terminal feature |
| Python 3.9+ | Most cPanel hosts have this pre-installed |
| XIMS credentials | Username: `countrylink`, Password: your admin password |
| Outbound HTTPS | Server must be able to reach `ims.marvellousfiber.com` |

---

## Step 1: Prepare Files for Upload

On your local machine, gather these files/folders to upload:

```
ims_automation/
├── src/                    ← All Python source files (REQUIRED)
│   ├── __init__.py
│   ├── config_loader.py
│   ├── session_manager.py
│   ├── login_handler.py
│   ├── renewal_api.py
│   ├── data_parser.py
│   ├── date_parser.py
│   ├── data_exporter.py
│   ├── diagnostics.py
│   └── main.py
├── .env                    ← Credentials file (REQUIRED)
├── .env.example            ← Template reference
├── requirements.txt        ← Python dependencies (REQUIRED)
├── run_fetcher.sh          ← Cron runner script (REQUIRED)
├── setup_cpanel.sh         ← One-time setup script (REQUIRED)
└── pyproject.toml          ← Project config
```

**DO NOT upload these** (they are not needed on the server):
- `venv/` or `.venv/` (virtual environment — will be created on server)
- `tests/` (test files)
- `.pytest_cache/`
- `.hypothesis/`
- `.kiro/`
- `render.yaml`
- `runtime.txt`

---

## Step 2: Upload to cPanel

### Option A: Using cPanel File Manager

1. Log into cPanel
2. Open **File Manager**
3. Navigate to your home directory (`/home/your_username/`)
4. Create a new folder called `ims_automation`
5. Open that folder
6. Click **Upload** and upload all the files listed above
7. For the `src/` folder: create it first, then upload files inside it

### Option B: Using SFTP (Recommended)

Use FileZilla or WinSCP:
- Host: your server hostname
- Port: 21 (FTP) or the SSH port for SFTP
- Username: your cPanel username
- Password: your cPanel password

Upload the entire `ims_automation/` folder to `/home/your_username/`

### Option C: Using Git (if available)

```bash
cd ~
git clone https://your-repo-url.git ims_automation
```

---

## Step 3: SSH into Your Server

### Option A: cPanel Terminal

1. Log into cPanel
2. Scroll down to **Advanced** section
3. Click **Terminal**
4. You're now in a shell

### Option B: SSH Client (PuTTY / Windows Terminal)

```bash
ssh your_username@your-server-hostname -p 22
```

---

## Step 4: Run the Setup Script

```bash
cd ~/ims_automation
chmod +x setup_cpanel.sh
./setup_cpanel.sh
```

**What this does:**
- Creates a Python virtual environment (`venv/`)
- Installs all required packages (requests, beautifulsoup4, python-dotenv, PyMySQL)
- Creates `logs/`, `output/`, `diagnostics/` directories
- Sets file permissions (makes `.env` readable only by you)

### If you get "python3: command not found"

Check what Python versions are available:
```bash
ls /usr/bin/python*
```

Common alternatives:
```bash
# Try one of these:
python3.9 -m venv venv
python3.11 -m venv venv
/usr/local/bin/python3 -m venv venv
```

If you find the correct path, edit `setup_cpanel.sh` line 14 to use it.

### If you get "pip: externally-managed-environment" error

This happens on newer systems. The virtual environment approach already handles this, but if it persists:
```bash
source venv/bin/activate
pip install --break-system-packages -r requirements.txt
```

---

## Step 5: Configure Your Credentials

Edit the `.env` file with your actual XIMS password:

```bash
nano ~/ims_automation/.env
```

Find this line:
```
IMS_PASSWORD=your_password_here
```

Replace `your_password_here` with your actual XIMS admin password.

**Full `.env` configuration:**

```env
# XIMS Login (REQUIRED - fill these in)
IMS_LOGIN_URL=https://ims.marvellousfiber.com/Admin
IMS_USERNAME=countrylink
IMS_PASSWORD=YOUR_ACTUAL_PASSWORD

# Operational Settings
IMS_PAGE_SIZE=50
IMS_DATE_FORMAT=yyyy/MM/dd
IMS_RETRY_COUNT=2
IMS_CONN_TIMEOUT=30
IMS_READ_TIMEOUT=60

# Export (csv saves to output/ folder)
IMS_EXPORT_FORMATS=csv

# MySQL (set to true if you want database storage)
IMS_MYSQL_ENABLED=false

# Logging
IMS_FILE_LOGGING=true
IMS_DEBUG=false
IMS_DIAGNOSTIC=false
```

Save: `Ctrl+O` → `Enter` → `Ctrl+X`

---

## Step 6: Test the Fetcher Manually

```bash
cd ~/ims_automation
chmod +x run_fetcher.sh
./run_fetcher.sh
```

**Expected output:**
```
=== IMS Fetch Started: 2026-05-27 12:00:00 ===
Date range: 2026/05/26 to 2026/05/27
2026-05-27 12:00:01 - INFO - src.main - IMS Data Fetcher starting
2026-05-27 12:00:01 - INFO - src.main - Authenticating with ISP admin panel
2026-05-27 12:00:02 - INFO - src.login_handler - Authentication successful
2026-05-27 12:00:02 - INFO - src.main - Fetching renewal data...
2026-05-27 12:00:03 - INFO - src.main - Fetched 45 total records
2026-05-27 12:00:03 - INFO - src.main - Exporting to CSV: output/renewals_2026-05-26_2026-05-27.csv
2026-05-27 12:00:03 - INFO - src.main - IMS Data Fetcher completed successfully
=== Fetch Completed Successfully ===
```

**Verify the CSV was created:**
```bash
ls -la ~/ims_automation/output/
cat ~/ims_automation/output/renewals_*.csv | head -5
```

### If login fails:

1. **Check credentials**: Try logging in manually at `https://ims.marvellousfiber.com/Admin` in a browser
2. **Enable diagnostics**: Edit `.env` and set `IMS_DIAGNOSTIC=true`, then re-run
3. **Check diagnostic output**: `ls ~/ims_automation/diagnostics/` — look at the request/response files
4. **Check if server can reach the URL**:
   ```bash
   source ~/ims_automation/venv/bin/activate
   python -c "import requests; r = requests.get('https://ims.marvellousfiber.com/Admin'); print(r.status_code)"
   ```

---

## Step 7: Set Up Automated Cron Job

### Via cPanel Interface

1. Log into **cPanel**
2. Go to **Advanced** → **Cron Jobs**
3. Under "Add New Cron Job":

| Field | Value |
|-------|-------|
| Common Settings | Once Per Day (or custom) |
| Minute | `0` |
| Hour | `6` |
| Day | `*` |
| Month | `*` |
| Weekday | `*` |

4. In the **Command** field, enter:

```
/home/YOUR_USERNAME/ims_automation/run_fetcher.sh >> /home/YOUR_USERNAME/ims_automation/logs/cron.log 2>&1
```

> ⚠️ Replace `YOUR_USERNAME` with your actual cPanel username!

5. Click **Add New Cron Job**

### Verify Cron is Working

Wait for the scheduled time, then check:
```bash
cat ~/ims_automation/logs/cron.log
```

Or run it manually to test the cron command:
```bash
/home/YOUR_USERNAME/ims_automation/run_fetcher.sh >> /home/YOUR_USERNAME/ims_automation/logs/cron.log 2>&1
cat ~/ims_automation/logs/cron.log
```

---

## Step 8 (Optional): MySQL Database Export

If you want renewal data stored in a MySQL database:

### 8.1 Create Database

1. Go to **cPanel** → **MySQL Databases**
2. Create new database: `YOUR_USERNAME_ims` (cPanel prefixes your username)
3. Create new user: `YOUR_USERNAME_imsuser` with a strong password
4. Click **Add User to Database** → select both → grant **ALL PRIVILEGES**

### 8.2 Create the Table

1. Go to **cPanel** → **phpMyAdmin**
2. Select your new database from the left sidebar
3. Click the **SQL** tab
4. Paste and run:

```sql
CREATE TABLE IF NOT EXISTS renewals (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(50) UNIQUE NOT NULL,
    cust_name VARCHAR(200),
    mobile_no VARCHAR(20),
    plan_name VARCHAR(100),
    amount VARCHAR(20),
    plan_expiry_date DATETIME,
    zone_name VARCHAR(100),
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

5. Click **Go**

### 8.3 Update .env

```bash
nano ~/ims_automation/.env
```

Update these lines:
```env
IMS_MYSQL_ENABLED=true
IMS_MYSQL_HOST=localhost
IMS_MYSQL_PORT=3306
IMS_MYSQL_DB=YOUR_USERNAME_ims
IMS_MYSQL_USER=YOUR_USERNAME_imsuser
IMS_MYSQL_PASSWORD=your_db_password
IMS_EXPORT_FORMATS=csv,mysql
```

### 8.4 Test MySQL Export

```bash
cd ~/ims_automation
./run_fetcher.sh
```

Then check in phpMyAdmin that records appeared in the `renewals` table.

---

## Custom Date Range Fetch

To fetch data for a specific date range (not just yesterday-to-today):

```bash
cd ~/ims_automation
source venv/bin/activate
python -m src.main --from-date 2026/01/01 --to-date 2026/05/27 --export csv
deactivate
```

---

## Monitoring & Maintenance

### Check Logs

```bash
# Cron execution log
tail -50 ~/ims_automation/logs/cron.log

# Application log (detailed)
tail -50 ~/ims_automation/logs/ims_data_fetcher.log
```

### View Recent CSV Exports

```bash
ls -lt ~/ims_automation/output/ | head -10
```

### Clear Old Files (optional cleanup cron)

Add another cron job to delete CSVs older than 30 days:
```
0 0 * * 0 find /home/YOUR_USERNAME/ims_automation/output -name "*.csv" -mtime +30 -delete
```

### Update the Application

If you make code changes:
```bash
cd ~/ims_automation
# Upload new src/ files via File Manager or SFTP
# Then restart is automatic (no daemon to restart — it's a cron script)
```

### Update Dependencies

```bash
cd ~/ims_automation
source venv/bin/activate
pip install -r requirements.txt --upgrade
deactivate
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `python3: command not found` | Try `python3.9`, `python3.11`, or check `/usr/bin/python*` |
| `ModuleNotFoundError` | Make sure `source venv/bin/activate` is in your script |
| Connection timeout to XIMS | Your host may block outbound HTTPS — contact support |
| Login fails with "no session cookie" | Credentials may be wrong, or XIMS changed their login form |
| `Permission denied` on run_fetcher.sh | Run `chmod +x ~/ims_automation/run_fetcher.sh` |
| Cron not running | Check cPanel → Cron Jobs, verify the path is absolute |
| Empty CSV (0 records) | Check date range — there may be no renewals for that period |
| MySQL connection refused | Verify host is `localhost`, and user has privileges on the database |

### Enable Debug Mode for Troubleshooting

```bash
nano ~/ims_automation/.env
# Set these:
# IMS_DEBUG=true
# IMS_DIAGNOSTIC=true
```

Then run again — check `diagnostics/` folder for raw HTTP request/response data.

---

## Security Notes

- `.env` file permissions are set to `600` (only your user can read it)
- Passwords are never logged (masked with `***MASKED***` in all output)
- The `.gitignore` excludes `.env` from version control
- MySQL password is excluded from error messages

---

## Summary of Commands

```bash
# One-time setup
cd ~/ims_automation
chmod +x setup_cpanel.sh run_fetcher.sh
./setup_cpanel.sh
nano .env  # Fill in your password

# Manual test
./run_fetcher.sh

# Check results
ls output/
cat logs/cron.log

# Custom date range
source venv/bin/activate
python -m src.main --from-date 2026/01/01 --to-date 2026/05/31 --export csv
deactivate
```

**Cron command** (add in cPanel → Cron Jobs):
```
0 6 * * * /home/YOUR_USERNAME/ims_automation/run_fetcher.sh >> /home/YOUR_USERNAME/ims_automation/logs/cron.log 2>&1
```
