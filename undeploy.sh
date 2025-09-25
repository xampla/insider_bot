#!/bin/bash

# Insider Trading Bot - Ubuntu Undeployment Script
# This script safely removes the systemd service and cleans up deployment files

set -e

SERVICE_NAME="insider-bot"

echo "🔄 Insider Trading Bot - Undeployment"
echo "====================================="

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   echo "❌ This script should NOT be run as root."
   echo "   Run as your regular user (it will ask for sudo when needed)"
   exit 1
fi

echo "⚠️  This will:"
echo "   • Stop the insider-bot service"
echo "   • Disable auto-start on boot"
echo "   • Remove systemd service file"
echo "   • Remove log rotation config"
echo "   • Keep your bot files and data intact"
echo

read -p "Continue with undeployment? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Undeployment cancelled"
    exit 0
fi

echo "🛑 Stopping and disabling service..."

# Check if service exists
if systemctl list-unit-files | grep -q "$SERVICE_NAME.service"; then
    # Stop service if running
    if systemctl is-active --quiet $SERVICE_NAME; then
        echo "   Stopping $SERVICE_NAME service..."
        sudo systemctl stop $SERVICE_NAME
    else
        echo "   Service is already stopped"
    fi

    # Disable service if enabled
    if systemctl is-enabled --quiet $SERVICE_NAME; then
        echo "   Disabling $SERVICE_NAME service..."
        sudo systemctl disable $SERVICE_NAME
    else
        echo "   Service is already disabled"
    fi
else
    echo "   Service not found - may already be undeployed"
fi

echo "🗑️  Removing service files..."

# Remove systemd service file
if [[ -f "/etc/systemd/system/$SERVICE_NAME.service" ]]; then
    echo "   Removing systemd service file..."
    sudo rm "/etc/systemd/system/$SERVICE_NAME.service"
    echo "   ✅ Service file removed"
else
    echo "   Service file not found"
fi

# Logrotate config no longer used (journal logging only)

# Reload systemd
echo "   Reloading systemd daemon..."
sudo systemctl daemon-reload
sudo systemctl reset-failed 2>/dev/null || true

echo "🧹 Cleaning up temporary files..."

# Remove temporary files that might have been created
rm -f /tmp/insider-bot.service
rm -f /tmp/insider-bot-logrotate

echo "✅ UNDEPLOYMENT COMPLETE!"
echo "======================="
echo
echo "📋 What was removed:"
echo "   ✅ Systemd service ($SERVICE_NAME)"
echo "   ✅ Auto-start on boot"
echo "   ✅ Temporary deployment files"
echo
echo "📁 What was kept:"
echo "   ✅ Bot source code and configuration"
echo "   ✅ Virtual environment (insider_bot_env/)"
echo "   ✅ Database (insider_trading_bot.db)"
echo "   ✅ Environment file (.env)"
echo "   ℹ️  Logs are in systemd journal: sudo journalctl -u $SERVICE_NAME"
echo
echo "🔄 To redeploy:"
echo "   ./deploy.sh"
echo
echo "🗑️  To completely remove bot:"
echo "   rm -rf \$(pwd)  # ⚠️  WARNING: Deletes everything!"
echo
echo "👋 Service successfully undeployed!"