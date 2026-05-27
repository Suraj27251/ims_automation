# IMS Data Fetcher — cPanel Deployment Guide

## Overview

This guide deploys the IMS Data Fetcher using **cPanel's "Setup Python App"** feature. Credentials and configuration are stored as **environment variables in the Python App settings** — no `.env` file needed on the server.

**Target**: XIMS (Internet Management System) at `https://ims.marvellousfiber.com/Admin`

---

## Prerequisites

| Requirement | Details |
|-------------|---------|
| cPanel hosting | With "Setup Python App" feature available |
| Python 3.9+ | Selected during app setup |
| SSH or Terminal access | For initial setup and testing |
| XIMS credentials | Username: `countrylink`, Password: your admin password |
| Outbound HTTPS | Server must reach `ims.marvellousfiber.com` |

---

## Step 1: Create Python App in cPanel

1. Log into **cPanel**
2. Go to **Software** → **Setup Python App**
3. Click **+ Create Application**
4. Fill in:

| Field | Value |
|-------|-------|
| Python version | `3.9` (or highest available) |
| Application root | `ims_automation` |
| Application URL | (leave blank — this is a CLI app, not a web app) |
| Application startup file | `passenger_wsgi.py` (we'll create a dummy one) |

5. Click **Create**

> **Note**: cPanel requires a startup file even for non-web apps. We'll create a placeholder.

---

## Step 2: Upload Project Files

Upload these files to `/home/YOUR_USERNAME/ims_automation/`:

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
├── requirements.txt        ← Python dependencies (REQUIRED)
├── run_fetcher.sh          ← Cron runner script (REQUIRED)
├── setup_cpanel.sh         ← Setup helper (REQUIRED)
└── passenger_wsgi.py       ← Dummy file for cPanel (REQUIRED)
```

**DO NOT upload**: `venv/`, `.venv/`, `tests/`, `.pytest_cache/`, `.hypothesis/`, `.kiro/`, `.env`

### Upload Methods

- **cPanel File Manager**: Navigate to `ims_automation/`, upload files
- **SFTP**: Use FileZilla/WinSCP to upload to `/home/YOUR_USERNAME/ims_automation/`
- **Git**: `cd ~ && git clone YOUR_REPO_URL ims_automation`

---

## Step 3: Create the Dummy Startup File

Since cPanel Python App requires a WSGI file, create a placeholder:

**Via cPanel File Manager** — create `passenger_wsgi.py` in `ims_automation/` with this content:

```python
# Placeholder for cPanel Python App requirement
# This app runs as a CLI cron job, not a web server
def application(environ, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b'IMS Data Fetcher - CLI application. Use cron jobs to run.']
```

Or via SSH:
```bash
cd ~/ims_automation
cat > passenger_wsgi.py << 'EOF'
def application(environ, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b'IMS Data Fetcher - CLI application. Use cron jobs to run.']
EOF
```

---

## Step 4: Set Environment Variables in Python App

This is where you put your credentials — **no `.env` file needed**.

1. Go to **cPanel** → **Setup Python App**
2. Click the **pencil icon** (edit) on your `ims_automation` app
3. Scroll down to **Environment variables** section
4. Add each variable by clicking **Add Variable**:

### Required Variables

| Name | Value |
|------|-------|
| `IMS_LOGIN_URL` | `https://ims.marvellousfiber.com/Admin` |
| `IMS_USERNAME` | `countrylink` |
| `IMS_PASSWORD` | `your_actual_password` |

### Optional Variables (recommended)

| Name | Value | Description |
|------|-------|-------------|
| `IMS_PAGE_SIZE` | `50` | Records per API page |
| `IMS_DATE_FORMAT` | `yyyy/MM/dd` | Date format for API |
| `IMS_RETRY_COUNT` | `2` | Retry attempts on failure |
| `IMS_CONN_TIMEOUT` | `30` | Connection timeout (seconds) |
| `IMS_READ_TIMEOUT` | `60` | Read timeout (seconds) |
| `IMS_EXPORT_FORMATS` | `csv` | Export type: console, csv, mysql |
| `IMS_FILE_LOGGING` | `true` | Enable log files |
| `IMS_DEBUG` | `false` | Debug mode (set true for troubleshooting) |
| `IMS_DIAGNOSTIC` | `false` | Save raw HTTP data |
| `IMS_MYSQL_ENABLED` | `false` | Enable MySQL export |

### MySQL Variables (only if using database export)

| Name | Value |
|------|-------|
| `IMS_MYSQL_HOST` | `localhost` |
| `IMS_MYSQL_PORT` | `3306` |
| `IMS_MYSQL_DB` | `YOUR_USERNAME_ims` |
| `IMS_MYSQL_USER` | `YOUR_USERNAME_imsuser` |
| `IMS_MYSQL_PASSWORD` | `your_db_password` |

5. Click **Save** (or **Update**) after adding all variables

---

## Step 5: Install Dependencies

### Option A: Via cPanel Python App Interface

1. In the Python App edit screen, scroll to **Configuration files**
2. Enter `requirements.txt` in the field
3. Click **Run Pip Install**

### Option B: Via SSH/Terminal

```bash
cd ~/ims_automation

# Enter the virtual environment created by cPanel Python App
source /home/YOUR_USERNAME/virtualenv/ims_automation/3.9/bin/activate
# OR (depending on your cPanel version):
source /home/YOUR_USERNAME/ims_automation/venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create required directories
mkdir -p logs output diagnostics

# Set permissions
chmod +x run_fetcher.sh
```

> **Tip**: Check the Python App page — it shows the exact path to your virtual environment's `activate` script. Copy that path.

---

## Step 6: Find Your Virtual Environment Path

This is important for the cron job. In cPanel:

1. Go to **Setup Python App**
2. Click edit on your app
3. Look for text like:
   ```
   source /home/YOUR_USERNAME/virtualenv/ims_automation/3.9/bin/activate
   ```
   or at the top it shows:
   ```
   Enter to the virtual environment: source /home/YOUR_USERNAME/virtualenv/ims_automation/3.9/bin/activate && cd /home/YOUR_USERNAME/ims_automation
   ```

4. **Copy this command** — you'll need it for the cron job

---

## Step 7: Test Manually

SSH into your server and run:

```bash
# Activate the Python App's virtual environment (use YOUR path from Step 6)
source /home/YOUR_USERNAME/virtualenv/ims_automation/3.9/bin/activate
cd ~/ims_automation

# Test the fetcher
python -m src.main --from-date 2026/05/01 --to-date 2026/05/27 --export csv

# Check output
ls -la output/
```

**Expected output:**
```
2026-05-27 12:00:01 - INFO - src.main - IMS Data Fetcher starting
2026-05-27 12:00:01 - INFO - src.main - Authenticating with ISP admin panel
2026-05-27 12:00:02 - INFO - src.login_handler - Authentication successful
2026-05-27 12:00:03 - INFO - src.main - Fetched 45 total records
2026-05-27 12:00:03 - INFO - src.main - Exporting to CSV: output/renewals_2026-05-01_2026-05-27.csv
2026-05-27 12:00:03 - INFO - src.main - IMS Data Fetcher completed successfully
```

If it works, proceed to set up the cron job.

---

## Step 8: Set Up Cron Job

### Via cPanel Cron Jobs

1. Go to **cPanel** → **Advanced** → **Cron Jobs**
2. Set schedule:

| Field | Value | Meaning |
|-------|-------|---------|
| Minute | `0` | At minute 0 |
| Hour | `6` | At 6 AM |
| Day | `*` | Every day |
| Month | `*` | Every month |
| Weekday | `*` | Every weekday |

3. **Command** — use the full activation path from Step 6:

```bash
source /home/YOUR_USERNAME/virtualenv/ims_automation/3.9/bin/activate && cd /home/YOUR_USERNAME/ims_automation && python -m src.main --from-date $(date -d 'yesterday' '+\%Y/\%m/\%d') --to-date $(date '+\%Y/\%m/\%d') --export csv >> /home/YOUR_USERNAME/ims_automation/logs/cron.log 2>&1
```

> ⚠️ **Important**: In cPanel cron commands, percent signs `%` must be escaped as `\%`

### Alternative: Use the Shell Script

If the above is too long, use the runner script instead:

```bash
/bin/bash /home/YOUR_USERNAME/ims_automation/run_fetcher.sh >> /home/YOUR_USERNAME/ims_automation/logs/cron.log 2>&1
```

> **Note**: When using `run_fetcher.sh`, make sure the virtual environment path inside the script matches your actual path. Edit `run_fetcher.sh` if needed.

4. Click **Add New Cron Job**

---

## Step 9 (Optional): MySQL Database Export

### 9.1 Create Database in cPanel

1. **cPanel** → **MySQL Databases**
2. Create database: type `ims` → it becomes `YOUR_USERNAME_ims`
3. Create user: type `imsuser` with a strong password → becomes `YOUR_USERNAME_imsuser`
4. Add user to database → grant **ALL PRIVILEGES**

### 9.2 Create Table

1. **cPanel** → **phpMyAdmin**
2. Select your database
3. Click **SQL** tab, paste:

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

4. Click **Go**

### 9.3 Add MySQL Environment Variables

Go back to **Setup Python App** → edit your app → add these environment variables:

| Name | Value |
|------|-------|
| `IMS_MYSQL_ENABLED` | `true` |
| `IMS_MYSQL_HOST` | `localhost` |
| `IMS_MYSQL_PORT` | `3306` |
| `IMS_MYSQL_DB` | `YOUR_USERNAME_ims` |
| `IMS_MYSQL_USER` | `YOUR_USERNAME_imsuser` |
| `IMS_MYSQL_PASSWORD` | `your_db_password` |
| `IMS_EXPORT_FORMATS` | `csv,mysql` |

Click **Save**.

---

## Verifying Everything Works

### Check Cron Logs
```bash
tail -50 ~/ims_automation/logs/cron.log
```

### Check Application Logs
```bash
tail -50 ~/ims_automation/logs/ims_data_fetcher.log
```

### Check CSV Output
```bash
ls -lt ~/ims_automation/output/ | head -10
head -5 ~/ims_automation/output/renewals_*.csv
```

### Check MySQL Data (if enabled)
Go to **phpMyAdmin** → select your database → browse the `renewals` table.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: No module named 'src'` | Make sure you `cd` to the project directory before running |
| `ModuleNotFoundError: No module named 'requests'` | Dependencies not installed — run pip install in the venv |
| Environment variables not found | Verify they're set in Setup Python App; for cron, use the full `source activate` command |
| Login fails | Enable `IMS_DIAGNOSTIC=true` in env vars, re-run, check `diagnostics/` folder |
| Connection timeout | Your host may block outbound HTTPS — contact hosting support |
| `Permission denied` on script | Run `chmod +x ~/ims_automation/run_fetcher.sh` |
| Cron not running | Verify path is absolute, `%` is escaped as `\%` in cPanel cron |
| Empty CSV | No renewals in that date range — try a wider range |
| `python: command not found` in cron | Use full path: `/home/YOUR_USERNAME/virtualenv/ims_automation/3.9/bin/python` |

### Quick Debug Test

```bash
source /home/YOUR_USERNAME/virtualenv/ims_automation/3.9/bin/activate
cd ~/ims_automation
python -c "
from src.config_loader import load_config
config = load_config()
print(f'Login URL: {config.login_url}')
print(f'Username: {config.username}')
print(f'Password: {\"*\" * len(config.password)}')
print('Config loaded successfully!')
"
```

This confirms environment variables are being read correctly.

---

## Security Notes

- ✅ Credentials stored in cPanel's Python App environment variables (not in files)
- ✅ No `.env` file on the server (nothing to accidentally expose)
- ✅ Passwords are masked in all log output (`***MASKED***`)
- ✅ MySQL password excluded from error messages
- ✅ Environment variables are only accessible to your user account

---

## Summary

| Step | Action | Where |
|------|--------|-------|
| 1 | Create Python App | cPanel → Setup Python App |
| 2 | Upload files | File Manager / SFTP |
| 3 | Create passenger_wsgi.py | File Manager |
| 4 | Set environment variables | Setup Python App → Environment variables |
| 5 | Install dependencies | Setup Python App → Pip Install / SSH |
| 6 | Note venv path | Setup Python App page |
| 7 | Test manually | SSH Terminal |
| 8 | Create cron job | cPanel → Cron Jobs |
| 9 | (Optional) MySQL setup | MySQL Databases + phpMyAdmin |
