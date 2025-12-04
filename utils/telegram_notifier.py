#!/usr/bin/env python3
"""
Telegram notification handler for stake move automation.
Based on patterns from liquidity_flow_controller's SlackNotifier.
"""

import json
import os
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Any
import requests


class TelegramNotifier:
    """Handles Telegram notifications for stake move automation with daily summaries"""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.enabled = bool(bot_token and chat_id)
        
        self.vm_ip = self._get_vm_ip()
        self.vm_hostname = self._get_vm_hostname()
        self.git_branch = self._get_git_branch()

        # Daily summary tracking
        self.startup_time = datetime.now(timezone.utc)
        self.daily_summary_lock = threading.Lock()
        self.last_summary_date = None

        # Persistent metrics (survive restarts)
        self.metrics_file = "stake_move_lifetime_metrics.json"
        self.lifetime_metrics = self._load_lifetime_metrics()

        # Daily metrics (reset each day)
        self.daily_metrics = {
            "stake_moves_count": 0,
            "stake_moves_failed": 0,
            "total_stake_moved": 0.0,  # in TAO
        }

        # Start daily summary thread
        self._start_daily_summary_thread()

    def _get_vm_ip(self) -> str:
        """Get the VM's IP address"""
        try:
            response = requests.get('https://api.ipify.org', timeout=5)
            return response.text
        except Exception:
            try:
                hostname = socket.gethostname()
                return socket.gethostbyname(hostname)
            except Exception:
                return "Unknown IP"

    def _get_vm_hostname(self) -> str:
        """Get the VM's hostname"""
        try:
            return socket.gethostname()
        except Exception:
            return "Unknown Hostname"

    def _get_git_branch(self) -> str:
        """Get the current git branch"""
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                capture_output=True,
                text=True,
                check=True,
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            branch = result.stdout.strip()
            if branch:
                return branch
            return "Unknown Branch"
        except Exception:
            return "Unknown Branch"

    def _load_lifetime_metrics(self) -> Dict[str, Any]:
        """Load persistent metrics from file"""
        try:
            metrics_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                self.metrics_file
            )
            if os.path.exists(metrics_path):
                with open(metrics_path, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        
        # Default metrics
        return {
            "total_lifetime_stake_moved": 0.0,
            "total_uptime_seconds": 0,
            "last_shutdown_time": None
        }

    def _save_lifetime_metrics(self):
        """Save persistent metrics to file"""
        try:
            # Update uptime
            current_session_uptime = (datetime.now(timezone.utc) - self.startup_time).total_seconds()
            self.lifetime_metrics["total_uptime_seconds"] += current_session_uptime
            self.lifetime_metrics["last_shutdown_time"] = datetime.now(timezone.utc).isoformat()

            metrics_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                self.metrics_file
            )
            with open(metrics_path, 'w') as f:
                json.dump(self.lifetime_metrics, f)
        except Exception:
            pass

    def _start_daily_summary_thread(self):
        """Start the daily summary thread"""
        if not self.enabled:
            return

        def daily_summary_loop():
            while True:
                try:
                    now = datetime.now(timezone.utc)
                    # Calculate seconds until next midnight UTC
                    next_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    if next_midnight <= now:
                        next_midnight = next_midnight.replace(day=next_midnight.day + 1)

                    sleep_seconds = (next_midnight - now).total_seconds()
                    time.sleep(sleep_seconds)

                    # Send daily summary
                    self._send_daily_summary()

                except Exception:
                    time.sleep(3600)  # Sleep 1 hour on error

        summary_thread = threading.Thread(target=daily_summary_loop, daemon=True)
        summary_thread.start()

    def _get_uptime_str(self) -> str:
        """Get formatted uptime string"""
        current_uptime = (datetime.now(timezone.utc) - self.startup_time).total_seconds()
        total_uptime = self.lifetime_metrics["total_uptime_seconds"] + current_uptime

        if total_uptime >= 86400:
            return f"{total_uptime / 86400:.1f} days"
        else:
            return f"{total_uptime / 3600:.1f} hours"

    def _send_daily_summary(self):
        """Send daily summary report"""
        with self.daily_summary_lock:
            try:
                # Calculate uptime
                uptime_str = self._get_uptime_str()

                # Calculate success rate
                total_attempts = self.daily_metrics["stake_moves_count"] + self.daily_metrics["stake_moves_failed"]
                if total_attempts > 0:
                    success_rate = (self.daily_metrics["stake_moves_count"] / total_attempts) * 100
                else:
                    success_rate = 0.0

                # Build message
                message = f"""📊 <b>Daily Summary Report</b>

Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
Script Uptime: {uptime_str}

🔄 <b>Stake Moves</b>
Success: {self.daily_metrics['stake_moves_count']}
Failed: {self.daily_metrics['stake_moves_failed']}
Success Rate: {success_rate:.1f}%

💰 <b>Today's Stake Moved</b>
{self.daily_metrics['total_stake_moved']:.9f} α

📈 <b>Lifetime Stake Moved</b>
{self.lifetime_metrics['total_lifetime_stake_moved']:.9f} α

🖥️ <b>System Info</b>
Host: {self.vm_hostname}
IP: {self.vm_ip}
Branch: {self.git_branch}"""

                self.send_message(message)

                # Update lifetime metrics
                self.lifetime_metrics["total_lifetime_stake_moved"] += self.daily_metrics["total_stake_moved"]

                # Reset daily metrics after successful send
                self.daily_metrics = {
                    "stake_moves_count": 0,
                    "stake_moves_failed": 0,
                    "total_stake_moved": 0.0,
                }

            except Exception:
                pass

    def send_message(self, message: str, parse_mode: str = "HTML"):
        """Send a message to Telegram"""
        if not self.enabled:
            return

        try:
            response = requests.post(
                f"{self.api_url}/sendMessage",
                data={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True
                },
                timeout=10
            )
            response.raise_for_status()
        except Exception:
            pass  # Fail silently to avoid disrupting main flow

    def send_document(self, file_path: str, caption: str = ""):
        """Send a document/file to Telegram"""
        if not self.enabled:
            return

        try:
            with open(file_path, 'rb') as f:
                response = requests.post(
                    f"{self.api_url}/sendDocument",
                    data={
                        "chat_id": self.chat_id,
                        "caption": caption
                    },
                    files={"document": f},
                    timeout=30
                )
                response.raise_for_status()
        except Exception:
            pass  # Fail silently

    def record_stake_move_success(self, amount_tao: float):
        """Record a successful stake move"""
        with self.daily_summary_lock:
            self.daily_metrics["stake_moves_count"] += 1
            self.daily_metrics["total_stake_moved"] += amount_tao

    def record_stake_move_failure(self):
        """Record a failed stake move"""
        with self.daily_summary_lock:
            self.daily_metrics["stake_moves_failed"] += 1

    def shutdown(self):
        """Clean shutdown - save metrics"""
        try:
            self._save_lifetime_metrics()
        except Exception:
            pass

