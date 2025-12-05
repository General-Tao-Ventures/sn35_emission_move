# GCP VM Stake Move Automation

Automated daily stake move operation that runs at 8AM PST on a GCP Compute Engine VM. This system moves stake from a specific hotkey to RT21 using wallet `sn35`, with password stored in a `.env` file and comprehensive logging.

## Overview

This automation system:
- Runs daily at **8AM PST** (16:00 UTC)
- Moves stake from hotkey `5EsmkLf4VnpgNM31syMjAWsUrQdW2Yu5xzWbv6oDQydP9vVx` to `5CATQqY6rA26Kkvm2abMTRtxnwyxigHZKxNJq86bUcpYsn35` (RT21)
- Uses wallet `sn35` for authentication
- Stores wallet password in a `.env` file (simple and secure)
- Uses Python with direct `subtensor.move_stake()` API calls (more reliable than CLI)
- Logs all operations with detailed stake amounts and timestamps
- Sends Telegram notifications for operation status, daily summaries, and logs
- Tracks metrics: success/failure counts, total stake moved, success rates
- Handles errors gracefully with proper notifications

## Architecture

- **Platform**: GCP Compute Engine VM (persistent storage for wallet files)
- **Implementation**: Python script using Bittensor SDK (no CLI dependencies)
- **Scheduling**: Systemd timer (reliable, persistent across reboots)
- **Secrets**: `.env` file for wallet password and Telegram credentials
- **Logging**: Structured logs with timestamps, stake amounts, and operation results
- **Notifications**: Telegram bot integration with daily summary reports and metrics tracking

## Prerequisites

1. **GCP Account** with billing enabled (or any Linux server)
2. **VM Instance** (e2-micro or larger) running Linux (Ubuntu/Debian recommended)
3. **Python 3.8+** installed on the VM
4. **Wallet files** for `sn35` wallet available
5. **Root/sudo access** on the VM

## Setup Instructions

### Step 1: Create GCP VM Instance

1. Go to [GCP Console](https://console.cloud.google.com/compute/instances)
2. Create a new VM instance:
   - **Machine type**: e2-micro (sufficient for this task)
   - **OS**: Ubuntu 22.04 LTS or Debian 11+
   - **Boot disk**: 20GB standard persistent disk
   - **Firewall**: Allow HTTP/HTTPS traffic (if needed)
   - **Service account**: Not required (we use `.env` file instead)

### Step 2: Install Python Dependencies

The deployment script will automatically install Python dependencies, but you can verify Python is installed:

```bash
# Verify Python 3.8+ is installed
python3 --version

# Verify pip3 is installed
pip3 --version
```

**Note**: The deployment script (`deploy.sh`) will automatically install all required Python packages from `requirements.txt`:
- `bittensor` - Bittensor SDK for blockchain interactions
- `python-dotenv` - Load environment variables from `.env` file
- `requests` - HTTP library for Telegram API

### Step 3: Transfer Wallet Files

Copy your wallet files to the VM. The wallet files should be located at `~/.bittensor/wallets/`:

```bash
# From your local machine, copy wallet directory
scp -r ~/.bittensor/wallets/sn35 USER@VM_IP:~/.bittensor/wallets/

# Or use gcloud compute scp
gcloud compute scp --recurse ~/.bittensor/wallets/sn35 VM_NAME:~/.bittensor/wallets/ --zone=ZONE
```

**Security Note**: Ensure wallet files have proper permissions:
```bash
chmod 600 ~/.bittensor/wallets/sn35/coldkey
chmod 600 ~/.bittensor/wallets/sn35/hotkeys/*
```

### Step 4: Install gcloud CLI on VM

If not already installed:

```bash
# Add gcloud repository
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | sudo tee -a /etc/apt/sources.list.d/google-cloud-sdk.list

# Import Google Cloud public key
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key --keyring /usr/share/keyrings/cloud.google.gpg add -

# Install gcloud
sudo apt-get update && sudo apt-get install -y google-cloud-sdk

# Authenticate (if needed)
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

### Step 5: Set Up Telegram Bot (Optional but Recommended)

To receive notifications and daily logs via Telegram:

1. **Create a Telegram Bot**:
   - Open Telegram and search for [@BotFather](https://t.me/botfather)
   - Send `/newbot` and follow instructions to create a bot
   - Save the bot token (e.g., `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

2. **Get Your Chat ID**:
   
   **Option A: Private Chat (Personal)**
   - Search for your bot in Telegram and start a conversation
   - Send any message to your bot
   - Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
   - Find your chat ID in the response (look for `"chat":{"id":123456789}`)
   
   **Option B: Group Chat (Recommended for notifications)**
   - Create a Telegram group or use an existing one
   - Add your bot to the group as a member (or admin)
   - Send a message in the group (e.g., "Hello")
   - Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
   - Find the group chat ID in the response (look for `"chat":{"id":-1001234567890}`)
   - **Note**: Group chat IDs are negative numbers (e.g., `-1003492410161`)
   - Make sure the bot has permission to send messages in the group

3. **Store credentials in `.env` file** (see Step 5 below for details)

**Note**: Telegram notifications are optional. You can skip this step and configure it later if needed.

### Step 6: Deploy Automation Scripts

1. **Transfer files to VM**:
   ```bash
   # Create directory on VM
   mkdir -p ~/stake-move-automation
   
   # Copy files from local machine
   scp daily_stake_move.sh stake-move.service stake-move.timer deploy.sh USER@VM_IP:~/stake-move-automation/
   ```

2. **Run deployment script**:
   ```bash
   cd ~/stake-move-automation
   chmod +x deploy.sh
   sudo ./deploy.sh
   ```

   The deployment script will:
   - Install required dependencies
   - Configure systemd service and timer
   - Enable and start the timer
   - Show next scheduled run time
   
   **Important**: You'll need to create a `.env` file manually (see Step 5)

### Step 7: Verify Installation

Check that everything is set up correctly:

```bash
# Check timer status
sudo systemctl status stake-move.timer

# Check next run time
sudo systemctl list-timers stake-move.timer

# View service logs (if test run was executed)
sudo journalctl -u stake-move.service -n 50
```

## Configuration

### Modify Schedule Time

To change the execution time, edit `/etc/systemd/system/stake-move.timer`:

```ini
[Timer]
# Change to desired time (format: HH:MM:00 TIMEZONE)
OnCalendar=*-*-* 08:00:00 America/Los_Angeles
```

Then reload:
```bash
sudo systemctl daemon-reload
sudo systemctl restart stake-move.timer
```

### Step 5: Create `.env` File

Create a `.env` file in `/opt/stake-move-automation/` with your credentials:

```bash
sudo nano /opt/stake-move-automation/.env
```

Add the following content (replace with your actual values):

```bash
# Wallet password for sn35 wallet (REQUIRED)
WALLET_PASSWORD=your_wallet_password_here

# Telegram bot token (optional - for notifications)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# Telegram chat ID (optional - for notifications)
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
```

**Security**: Set proper permissions on the `.env` file:
```bash
sudo chmod 600 /opt/stake-move-automation/.env
sudo chown root:root /opt/stake-move-automation/.env
```

### Update Wallet Password

To update the password, edit the `.env` file:

```bash
sudo nano /opt/stake-move-automation/.env
# Update WALLET_PASSWORD=your_new_password
```

### Configure or Update Telegram Settings

To configure or update Telegram, edit the `.env` file:

```bash
sudo nano /opt/stake-move-automation/.env
# Update TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
```

To disable Telegram notifications, simply remove or comment out the Telegram lines in the `.env` file (the script will gracefully skip notifications if they're not set).

### Change Hotkey Addresses

Edit `/opt/stake-move-automation/daily_stake_move.sh`:

```bash
ORIGIN_HOTKEY="YOUR_ORIGIN_HOTKEY"
DEST_HOTKEY="YOUR_DEST_HOTKEY"
```

Then restart the service:
```bash
sudo systemctl daemon-reload
```

## Monitoring

### View Daily Logs

```bash
# Today's log
tail -f /var/log/stake-move/$(date +%Y-%m-%d).log

# Specific date
cat /var/log/stake-move/2024-01-15.log

# Summary log (all operations)
tail -f /var/log/stake-move/summary.log
```

### View Systemd Logs

```bash
# Service logs
sudo journalctl -u stake-move.service -f

# Timer logs
sudo journalctl -u stake-move.timer -f

# Last 100 lines
sudo journalctl -u stake-move.service -n 100
```

### Check Timer Status

```bash
# Current status
sudo systemctl status stake-move.timer

# List all timers
sudo systemctl list-timers

# Next run time
sudo systemctl list-timers stake-move.timer --no-pager
```

### Telegram Notifications

If Telegram is configured, you will receive:

1. **Start Notification**: Sent when the operation begins
   - Shows operation start time
   - Origin and destination hotkey addresses
   - Wallet name

2. **Success/Failure Notification**: Sent when operation completes
   - Success: Shows stake amounts moved (fetched directly from blockchain)
   - Failure: Shows detailed error message

3. **Daily Log File**: Complete log file sent as a document attachment

4. **Daily Summary Report**: Automatically sent at midnight UTC with:
   - Success/failure counts and success rate
   - Total stake moved today
   - Lifetime total stake moved
   - Script uptime
   - System info (hostname, IP, git branch)

**Test Telegram notifications**:
```bash
# Send a test notification
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/sendMessage" \
  -d "chat_id=<YOUR_CHAT_ID>" \
  -d "text=Test notification"
```

### Manual Execution

To run the operation manually (for testing):

```bash
# Start service manually
sudo systemctl start stake-move.service

# View output
sudo journalctl -u stake-move.service -f
```

## Log Format

### Daily Log File (`/var/log/stake-move/YYYY-MM-DD.log`)

```
[2024-01-15 08:00:01 PST] ==========================================
[2024-01-15 08:00:01 PST] Starting daily stake move operation
[2024-01-15 08:00:01 PST] ==========================================
[2024-01-15 08:00:01 PST] Origin Netuid: 35
[2024-01-15 08:00:01 PST] Destination Netuid: 35
[2024-01-15 08:00:01 PST] Origin Hotkey: 5EsmkLf4VnpgNM31syMjAWsUrQdW2Yu5xzWbv6oDQydP9vVx
[2024-01-15 08:00:01 PST] Destination Hotkey: 5CATQqY6rA26Kkvm2abMTRtxnwyxigHZKxNJq86bUcpYsn35
[2024-01-15 08:00:01 PST] Wallet: sn35
[2024-01-15 08:00:02 PST] Fetching password from GCP Secret Manager...
[2024-01-15 08:00:03 PST] Password retrieved successfully
[2024-01-15 08:00:04 PST] Executing stake move operation...
[2024-01-15 08:00:10 PST] Operation completed successfully
[2024-01-15 08:00:10 PST] Origin stake info: 1,234.5886
[2024-01-15 08:00:10 PST] Destination stake info: 20,162.4246
[2024-01-15 08:00:11 PST] ==========================================
[2024-01-15 08:00:11 PST] Daily stake move operation completed
[2024-01-15 08:00:11 PST] ==========================================
```

### Summary Log (`/var/log/stake-move/summary.log`)

```
[2024-01-15 08:00:11 PST] SUCCESS: Stake moved from 5EsmkLf4VnpgNM31syMjAWsUrQdW2Yu5xzWbv6oDQydP9vVx to 5CATQqY6rA26Kkvm2abMTRtxnwyxigHZKxNJq86bUcpYsn35
[2024-01-15 08:00:11 PST]   Origin stake: 1,234.5886
[2024-01-15 08:00:11 PST]   Destination stake: 20,162.4246
```

## Troubleshooting

### Timer Not Running

1. **Check timer status**:
   ```bash
   sudo systemctl status stake-move.timer
   ```

2. **Check if timer is enabled**:
   ```bash
   sudo systemctl is-enabled stake-move.timer
   ```

3. **Enable and start timer**:
   ```bash
   sudo systemctl enable stake-move.timer
   sudo systemctl start stake-move.timer
   ```

### Service Fails to Start

1. **Check service logs**:
   ```bash
   sudo journalctl -u stake-move.service -n 100
   ```

2. **Check script permissions**:
   ```bash
   ls -l /opt/stake-move-automation/daily_stake_move.py
   sudo chmod +x /opt/stake-move-automation/daily_stake_move.py
   ```

3. **Verify Python dependencies are installed**:
   ```bash
   python3 -c "import bittensor; import google.cloud.secretmanager; import requests"
   ```

4. **Verify script path in service file**:
   ```bash
   cat /etc/systemd/system/stake-move.service
   ```

### Password Retrieval Fails

1. **Check `.env` file exists and has correct permissions**:
   ```bash
   ls -la /opt/stake-move-automation/.env
   # Should show: -rw------- (600 permissions, owned by root)
   ```

2. **Verify `.env` file has WALLET_PASSWORD set**:
   ```bash
   sudo grep WALLET_PASSWORD /opt/stake-move-automation/.env
   # Should show: WALLET_PASSWORD=your_password
   ```

3. **Test reading environment variables**:
   ```bash
   cd /opt/stake-move-automation
   python3 -c "from dotenv import load_dotenv; import os; load_dotenv(); print('WALLET_PASSWORD set:', bool(os.getenv('WALLET_PASSWORD')))"
   ```

### Python Dependencies Issues

1. **Verify Python packages are installed**:
   ```bash
   python3 -c "import bittensor; print('bittensor:', bittensor.__version__)"
   python3 -c "import dotenv; print('python-dotenv: OK')"
   python3 -c "import requests; print('requests:', requests.__version__)"
   ```

2. **Check wallet files exist**:
   ```bash
   ls -la ~/.bittensor/wallets/sn35/
   ```

3. **Test Python script manually**:
   ```bash
   cd /opt/stake-move-automation
   python3 daily_stake_move.py
   ```

4. **Reinstall dependencies if needed**:
   ```bash
   pip3 install -r /opt/stake-move-automation/requirements.txt
   ```

### Logs Not Being Created

1. **Check log directory permissions**:
   ```bash
   ls -ld /var/log/stake-move
   sudo mkdir -p /var/log/stake-move
   sudo chmod 755 /var/log/stake-move
   ```

2. **Check script can write to log directory**:
   ```bash
   sudo -u root touch /var/log/stake-move/test.log
   ```

### Timezone Issues

1. **Check system timezone**:
   ```bash
   timedatectl
   ```

2. **Set timezone if needed**:
   ```bash
   sudo timedatectl set-timezone America/Los_Angeles
   ```

3. **Verify timer timezone**:
   ```bash
   cat /etc/systemd/system/stake-move.timer | grep OnCalendar
   ```

### Telegram Notifications Not Working

1. **Verify `.env` file has Telegram credentials**:
   ```bash
   sudo grep TELEGRAM /opt/stake-move-automation/.env
   # Should show: TELEGRAM_BOT_TOKEN=... and TELEGRAM_CHAT_ID=...
   ```

2. **Test bot token and chat ID**:
   ```bash
   cd /opt/stake-move-automation
   source <(sudo cat .env | grep -E '^TELEGRAM' | sed 's/^/export /')
   curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
     -d "chat_id=${TELEGRAM_CHAT_ID}" \
     -d "text=Test message"
   ```

3. **Check logs for Telegram errors**:
   ```bash
   sudo journalctl -u stake-move.service | grep -i telegram
   ```

4. **Verify curl is installed**:
   ```bash
   which curl
   # If not installed: sudo apt-get install curl
   ```

## Cost Estimation

- **GCP VM (e2-micro)**: ~$5-10/month (always-on) or ~$1-2/month (preemptible)
- **Storage**: Minimal (`.env` file is tiny, ~100 bytes)
- **Storage**: Minimal (logs are small, ~1MB per month)
- **Network**: Minimal (only Secret Manager API calls)

**Total estimated cost**: ~$5-10/month for always-on VM

## Security Considerations

1. **Wallet Files**: Ensure wallet files have restrictive permissions (600)
2. **`.env` file**: Ensure proper file permissions (600) and ownership (root)
3. **VM Access**: Restrict SSH access using firewall rules
4. **Logs**: Consider rotating logs to prevent disk fill-up
5. **Service Account**: Use dedicated service account with minimal permissions

## Maintenance

### Log Rotation

Create `/etc/logrotate.d/stake-move`:

```
/var/log/stake-move/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0644 root root
}
```

### Update Scripts

To update scripts:

```bash
# Copy new files to VM (including utils directory)
scp -r daily_stake_move.py utils/ requirements.txt USER@VM_IP:~/stake-move-automation/

# Update installation
sudo cp ~/stake-move-automation/daily_stake_move.py /opt/stake-move-automation/
sudo cp -r ~/stake-move-automation/utils /opt/stake-move-automation/
sudo cp ~/stake-move-automation/requirements.txt /opt/stake-move-automation/

# Update Python dependencies if requirements.txt changed
sudo -u <service_user> pip3 install -r /opt/stake-move-automation/requirements.txt

# Reload systemd
sudo systemctl daemon-reload
```

## Troubleshooting: Timer Not Running

If the timer shows as active but the script didn't run:

### Step 1: Check if Service Actually Executed

```bash
# Check if service ran today
sudo journalctl -u stake-move.service --since "today 00:00:00" --no-pager

# Check service execution history
sudo journalctl -u stake-move.service --since "yesterday" --no-pager

# Check for errors
sudo journalctl -u stake-move.service -p err --since "yesterday" --no-pager
```

### Step 2: Check Log Files

```bash
# Check today's log file
TODAY=$(date +%Y-%m-%d)
ls -lah /var/log/stake-move/${TODAY}.log
tail -50 /var/log/stake-move/${TODAY}.log

# Check summary log
tail -20 /var/log/stake-move/summary.log
```

### Step 3: Verify Timer Triggered Service

```bash
# Check timer and service relationship
sudo systemctl status stake-move.timer -l
sudo systemctl status stake-move.service -l

# Check if service was triggered but failed
sudo journalctl -u stake-move.service --since "yesterday" | grep -i "failed\|error\|exception"
```

### Step 4: Test Manual Execution

```bash
# Try running the service manually to see if it works
sudo systemctl start stake-move.service

# Watch logs in real-time
sudo journalctl -u stake-move.service -f
```

### Step 5: Check Common Issues

1. **GCP Authentication Errors** (Most Common):
   If you see `Reauthentication is needed. Please run 'gcloud auth application-default login'`:
   
   **Root Cause**: The service runs as `root` but is trying to use expired user application-default credentials.
   
   **Fix**:
   ```bash
   # Option 1: Run the automated fix script (recommended)
   sudo ./fix_auth.sh
   
   # Option 2: Manual fix
   # Update the service file to use VM service account
   sudo cp stake-move.service /etc/systemd/system/
   sudo systemctl daemon-reload
   
   # Update the Python script
   sudo cp daily_stake_move.py /opt/stake-move-automation/
   
   # Verify .env file exists and has correct content
   sudo ls -la /opt/stake-move-automation/.env
   sudo grep WALLET_PASSWORD /opt/stake-move-automation/.env
   ```

2. **Service failed silently**: Check journal logs for Python errors
3. **Timezone mismatch**: Verify system timezone matches timer timezone
   ```bash
   timedatectl
   # Should show America/Los_Angeles or similar
   ```
4. **Permissions issue**: Check if script can write logs
   ```bash
   sudo -u root touch /var/log/stake-move/test.log
   ```
5. **Python dependencies**: Verify all packages are installed
   ```bash
   python3 -c "import bittensor; import dotenv; import requests; print('OK')"
   ```

### Step 6: Force Timer to Recalculate Next Run

If timer seems stuck, reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart stake-move.timer
sudo systemctl status stake-move.timer
```

## Support

For issues or questions:
1. Check logs: `/var/log/stake-move/` and `journalctl -u stake-move.service`
2. Verify all prerequisites are met
3. Test manual execution: `sudo systemctl start stake-move.service`
4. Run the diagnostic script: `./diagnose.sh` (if available on VM)

## Files Reference

- `daily_stake_move.py` - Main Python automation script (uses `subtensor.move_stake()` API)
- `utils/telegram_notifier.py` - Telegram notification handler with daily summaries
- `requirements.txt` - Python dependencies
- `stake-move.service` - Systemd service definition
- `stake-move.timer` - Systemd timer definition (scheduling)
- `deploy.sh` - Deployment and setup script
- `README.md` - This file

**Note**: The old bash script (`daily_stake_move.sh`) has been replaced with the Python implementation for better reliability and maintainability.

## License

This automation script is provided as-is for internal use.

