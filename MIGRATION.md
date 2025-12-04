# Migration Guide: Bash to Python

This guide explains how to stop the current bash-based automation and deploy the new Python version.

## Step 1: Stop Current Automation

```bash
# Stop the timer (prevents new runs)
sudo systemctl stop stake-move.timer

# Disable the timer (prevents auto-start on reboot)
sudo systemctl disable stake-move.timer

# Check if a service is currently running
sudo systemctl status stake-move.service

# If a service is running, wait for it to complete or stop it
# (Note: Stopping a running service might interrupt an in-progress stake move)
sudo systemctl stop stake-move.service
```

## Step 2: Backup Current Setup

```bash
# Create backup directory
sudo mkdir -p /opt/stake-move-automation-backup

# Backup old bash script
sudo cp /opt/stake-move-automation/daily_stake_move.sh /opt/stake-move-automation-backup/ 2>/dev/null || echo "No old script found"

# Backup systemd files
sudo cp /etc/systemd/system/stake-move.service /opt/stake-move-automation-backup/
sudo cp /etc/systemd/system/stake-move.timer /opt/stake-move-automation-backup/
```

## Step 3: Transfer New Files to VM

From your local machine:

```bash
# Transfer all new files
scp daily_stake_move.py utils/telegram_notifier.py utils/__init__.py requirements.txt deploy.sh stake-move.service USER@VM_IP:~/stake-move-automation/

# Or use gcloud compute scp
gcloud compute scp --recurse daily_stake_move.py utils/ requirements.txt deploy.sh stake-move.service VM_NAME:~/stake-move-automation/ --zone=ZONE
```

## Step 4: Run Deployment Script

SSH into your VM and run:

```bash
cd ~/stake-move-automation
chmod +x deploy.sh
sudo ./deploy.sh
```

The deployment script will:
- Install Python dependencies
- Copy files to `/opt/stake-move-automation/`
- Update systemd service configuration
- Set up GCP Secret Manager (if needed)
- Configure Telegram (if needed)
- Enable and start the timer

## Step 5: Verify Installation

```bash
# Check timer status
sudo systemctl status stake-move.timer

# Check next run time
sudo systemctl list-timers stake-move.timer

# Verify Python script exists and is executable
ls -l /opt/stake-move-automation/daily_stake_move.py

# Verify utils directory exists
ls -l /opt/stake-move-automation/utils/

# Test Python dependencies
python3 -c "import bittensor; import google.cloud.secretmanager; import requests; print('All dependencies OK')"
```

## Step 6: Test Run (Optional)

Before waiting for the scheduled run, you can test manually:

```bash
# Run the service manually
sudo systemctl start stake-move.service

# Watch the logs
sudo journalctl -u stake-move.service -f

# Or check the log file
tail -f /var/log/stake-move/$(date +%Y-%m-%d).log
```

## Step 7: Verify It's Working

After the next scheduled run (or manual test):

1. **Check logs**:
   ```bash
   tail -f /var/log/stake-move/$(date +%Y-%m-%d).log
   ```

2. **Check Telegram notifications** - You should receive:
   - Start notification
   - Success notification with stake amounts moved and destination total
   - Daily log file
   - Daily summary at midnight UTC

3. **Verify metrics file**:
   ```bash
   ls -l /opt/stake-move-automation/stake_move_lifetime_metrics.json
   ```

## Rollback (If Needed)

If something goes wrong, you can rollback:

```bash
# Stop new service
sudo systemctl stop stake-move.timer
sudo systemctl disable stake-move.timer

# Restore old files
sudo cp /opt/stake-move-automation-backup/daily_stake_move.sh /opt/stake-move-automation/
sudo cp /opt/stake-move-automation-backup/stake-move.service /etc/systemd/system/
sudo systemctl daemon-reload

# Update service to use bash script
sudo sed -i 's|ExecStart=.*|ExecStart=/opt/stake-move-automation/daily_stake_move.sh|' /etc/systemd/system/stake-move.service
sudo systemctl daemon-reload

# Re-enable timer
sudo systemctl enable stake-move.timer
sudo systemctl start stake-move.timer
```

## Key Differences

### Old (Bash)
- Uses `expect` to interact with `btcli stake move` CLI
- Parses stake amounts from CLI output
- Basic Telegram notifications

### New (Python)
- Uses `subtensor.move_stake()` API directly
- Fetches stake amounts using `subtensor.get_stake()`
- Enhanced Telegram notifications with daily summaries
- Tracks metrics (success/failure counts, total stake moved)
- More reliable error handling

## Troubleshooting

### Python Dependencies Not Found

```bash
# Install manually
pip3 install -r /opt/stake-move-automation/requirements.txt

# Or for user install
pip3 install --user -r /opt/stake-move-automation/requirements.txt
```

### Service Fails to Start

```bash
# Check service logs
sudo journalctl -u stake-move.service -n 50

# Check Python script syntax
python3 -m py_compile /opt/stake-move-automation/daily_stake_move.py

# Test script manually
cd /opt/stake-move-automation
python3 daily_stake_move.py
```

### Wallet Password Issues

The Python script uses `MINER_WALLET_PASSWORD` environment variable. Make sure:
1. GCP Secret Manager secret exists: `stake-move-wallet-sn35-password`
2. Service account has Secret Manager access
3. Application Default Credentials are set up:
   ```bash
   gcloud auth application-default login
   ```

