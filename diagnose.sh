#!/bin/bash
# Diagnostic script to check why stake-move didn't run

echo "=========================================="
echo "Stake Move Diagnostic Script"
echo "=========================================="
echo ""

echo "1. Timer Status"
echo "----------------------------------------"
sudo systemctl status stake-move.timer --no-pager -l
echo ""

echo "2. Timer Schedule"
echo "----------------------------------------"
sudo systemctl list-timers stake-move.timer --all
echo ""

echo "3. Service Status"
echo "----------------------------------------"
sudo systemctl status stake-move.service --no-pager -l
echo ""

echo "4. Recent Service Logs (last 50 lines)"
echo "----------------------------------------"
sudo journalctl -u stake-move.service -n 50 --no-pager
echo ""

echo "5. Service Execution History"
echo "----------------------------------------"
sudo journalctl -u stake-move.service --since "yesterday" --no-pager
echo ""

echo "6. Check if service ran today"
echo "----------------------------------------"
TODAY=$(date +%Y-%m-%d)
echo "Today's date: $TODAY"
sudo journalctl -u stake-move.service --since "today 00:00:00" --no-pager
echo ""

echo "7. Check log files"
echo "----------------------------------------"
if [ -d "/var/log/stake-move" ]; then
    echo "Log directory exists:"
    ls -lah /var/log/stake-move/
    echo ""
    echo "Today's log file:"
    if [ -f "/var/log/stake-move/${TODAY}.log" ]; then
        echo "Found today's log file:"
        tail -50 "/var/log/stake-move/${TODAY}.log"
    else
        echo "No log file found for today: /var/log/stake-move/${TODAY}.log"
    fi
    echo ""
    echo "Summary log (last 20 lines):"
    if [ -f "/var/log/stake-move/summary.log" ]; then
        tail -20 "/var/log/stake-move/summary.log"
    else
        echo "No summary.log found"
    fi
else
    echo "Log directory /var/log/stake-move does not exist"
fi
echo ""

echo "8. Check for errors in systemd journal"
echo "----------------------------------------"
sudo journalctl -u stake-move.service -p err --since "yesterday" --no-pager
echo ""

echo "9. Test manual service execution (dry-run check)"
echo "----------------------------------------"
echo "Checking if service can be started manually..."
echo "Note: This will NOT actually run the script, just check if it can start"
sudo systemctl show stake-move.service --property=LoadState,ActiveState,SubState,ExecStart
echo ""

echo "=========================================="
echo "Diagnostic complete"
echo "=========================================="
