#!/bin/bash
# Fix script for GCP authentication issues with stake-move service
# This ensures the service uses the VM's service account instead of user credentials

set -e

echo "=========================================="
echo "Fixing GCP Authentication for stake-move service"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Error: This script must be run as root (use sudo)"
    exit 1
fi

echo "1. Updating service file..."
# Backup original
cp /etc/systemd/system/stake-move.service /etc/systemd/system/stake-move.service.backup.$(date +%Y%m%d_%H%M%S)

# Update service file (ensure it uses VM service account)
cat > /etc/systemd/system/stake-move.service << 'EOF'
[Unit]
Description=Daily Stake Move Automation
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/stake-move-automation
ExecStart=/usr/bin/python3 /opt/stake-move-automation/daily_stake_move.py
StandardOutput=journal
StandardError=journal
SyslogIdentifier=stake-move

# Environment variables
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
# Ensure we use VM service account credentials, not user application-default credentials
Environment="GOOGLE_APPLICATION_CREDENTIALS="
# Explicitly use metadata server for authentication (GCP VM service account)
Environment="GCE_METADATA_HOST=metadata.google.internal"

# Security settings
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

echo "✓ Service file updated"

echo ""
echo "2. Reloading systemd daemon..."
systemctl daemon-reload
echo "✓ Systemd reloaded"

echo ""
echo "3. Verifying service configuration..."
systemctl show stake-move.service --property=Environment --no-pager
echo ""

echo "4. Testing service account access..."
# Test if we can access the metadata server
if curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email > /dev/null 2>&1; then
    SERVICE_ACCOUNT=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email)
    echo "✓ VM Service Account: $SERVICE_ACCOUNT"
else
    echo "⚠ Warning: Could not access metadata server. This might not be a GCP VM or metadata server is not accessible."
fi

echo ""
echo "=========================================="
echo "Fix complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Update the Python script on the VM with the latest version"
echo "2. Test the service: sudo systemctl start stake-move.service"
echo "3. Check logs: sudo journalctl -u stake-move.service -f"
echo ""
echo "To update the Python script, copy daily_stake_move.py to:"
echo "  /opt/stake-move-automation/daily_stake_move.py"
