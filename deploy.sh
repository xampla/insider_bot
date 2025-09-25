#!/bin/bash

# Insider Trading Bot - Ubuntu Deployment Script
# This script sets up the bot to run as a systemd service with automatic restarts
# Works from any directory with any user - fully portable!

set -e

echo "🚀 Insider Trading Bot - Ubuntu Deployment"
echo "=========================================="

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   echo "❌ This script should NOT be run as root."
   echo "   Run as your regular user (it will ask for sudo when needed)"
   exit 1
fi

# Auto-detect configuration
BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_USER="$(whoami)"
BOT_GROUP="$(id -gn)"
SERVICE_NAME="insider-bot"

echo "🔍 Auto-detected Configuration:"
echo "   User: $BOT_USER"
echo "   Group: $BOT_GROUP"
echo "   Directory: $BOT_DIR"
echo "   Service: $SERVICE_NAME"
echo

# Validate we're in the right directory
if [[ ! -f "$BOT_DIR/main.py" ]]; then
    echo "❌ main.py not found in $BOT_DIR"
    echo "   Please run this script from the insider bot directory."
    exit 1
fi

if [[ ! -f "$BOT_DIR/insider-bot.service" ]]; then
    echo "❌ insider-bot.service template not found in $BOT_DIR"
    echo "   Please ensure all deployment files are present."
    exit 1
fi

echo "✅ Directory validation passed"
echo

# Step 1: Create necessary directories
echo "📁 Creating directory structure..."
mkdir -p "$BOT_DIR/backups"

# Step 2: Install Python dependencies (if venv doesn't exist)
if [[ ! -d "$BOT_DIR/insider_bot_env" ]]; then
    echo "🐍 Creating Python virtual environment..."
    cd "$BOT_DIR"
    python3 -m venv insider_bot_env
    source insider_bot_env/bin/activate
    pip install --upgrade pip
    if [[ -f "requirements.txt" ]]; then
        pip install -r requirements.txt
    else
        echo "⚠️  requirements.txt not found - you may need to install dependencies manually"
    fi
    echo "✅ Virtual environment created"
else
    echo "✅ Virtual environment already exists"
fi

# Step 3: Validate environment file
if [[ ! -f "$BOT_DIR/.env" ]]; then
    echo "⚠️  .env file not found!"
    echo "   Please create .env with your API credentials before starting the service."
    if [[ -f "$BOT_DIR/.env.example" ]]; then
        echo "   You can copy .env.example as a template:"
        echo "   cp .env.example .env && nano .env"
    fi
    echo
fi

# Step 4: Generate systemd service file
echo "🔧 Generating systemd service file..."

# Create service file with substituted values
sed -e "s|{{BOT_DIR}}|$BOT_DIR|g" \
    -e "s|{{BOT_USER}}|$BOT_USER|g" \
    -e "s|{{BOT_GROUP}}|$BOT_GROUP|g" \
    "$BOT_DIR/insider-bot.service" > /tmp/insider-bot.service

echo "✅ Service file generated with:"
echo "   Directory: $BOT_DIR"
echo "   User/Group: $BOT_USER/$BOT_GROUP"

# Install service file (requires sudo)
echo "   Installing service file (requires sudo)..."
sudo cp /tmp/insider-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME
echo "✅ Service installed and enabled"

# Step 5: Journal logging is handled by systemd automatically
echo "📝 Logging configured (using systemd journal)..."
echo "✅ Journal logging ready"

# Step 6: Set correct permissions
echo "🔒 Setting permissions..."
chmod +x "$BOT_DIR/main.py"
find "$BOT_DIR" -name "*.py" -exec chmod 644 {} \;
find "$BOT_DIR" -name "*.sh" -exec chmod +x {} \;

# Step 7: Test the service
echo "🧪 Testing service configuration..."
sudo systemctl start $SERVICE_NAME
sleep 3

if sudo systemctl is-active --quiet $SERVICE_NAME; then
    echo "✅ Service started successfully!"
    echo
    echo "📊 Service Status:"
    sudo systemctl status $SERVICE_NAME --no-pager -l
else
    echo "❌ Service failed to start. Check logs:"
    echo "   sudo journalctl -u $SERVICE_NAME --no-pager -l"
fi

echo
echo "🎯 DEPLOYMENT COMPLETE!"
echo "======================"
echo
echo "📋 Service Management Commands:"
echo "   Start:   sudo systemctl start $SERVICE_NAME"
echo "   Stop:    sudo systemctl stop $SERVICE_NAME"
echo "   Restart: sudo systemctl restart $SERVICE_NAME"
echo "   Status:  sudo systemctl status $SERVICE_NAME"
echo "   Logs:    sudo journalctl -u $SERVICE_NAME -f"
echo
echo "📝 Logging:"
echo "   All logs:    sudo journalctl -u $SERVICE_NAME -f"
echo "   Recent logs: sudo journalctl -u $SERVICE_NAME --no-pager -l"
echo
echo "🔄 The bot will automatically:"
echo "   ✅ Start on system boot"
echo "   ✅ Restart if it crashes"
echo "   ✅ Log to systemd journal (auto-managed)"
echo "   ✅ Run with resource limits (1GB RAM, 50% CPU)"
echo "   ✅ Work from: $BOT_DIR"
echo "   ✅ Run as: $BOT_USER:$BOT_GROUP"
echo
echo "⚠️  Remember to:"
echo "   1. Configure your .env file with API credentials"
echo "   2. Test with paper trading first"
echo "   3. Monitor logs for the first few hours"
echo

# Cleanup
rm -f /tmp/insider-bot.service

echo "🧹 Cleanup completed - ready to trade! 🚀"