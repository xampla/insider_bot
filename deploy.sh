#!/bin/bash

# Insider Trading Bot - Ubuntu Deployment Script
# This script sets up the bot to run as a systemd service with automatic restarts

set -e

echo "🚀 Insider Trading Bot - Ubuntu Deployment"
echo "=========================================="

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   echo "❌ This script should NOT be run as root. Run as the ubuntu user."
   exit 1
fi

# Configuration
BOT_USER="ubuntu"
BOT_DIR="/home/ubuntu/insider_bot"
SERVICE_NAME="insider-bot"

echo "📋 Configuration:"
echo "   User: $BOT_USER"
echo "   Directory: $BOT_DIR"
echo "   Service: $SERVICE_NAME"
echo

# Check if we're in the right directory
if [[ ! -f "main.py" ]]; then
    echo "❌ main.py not found. Please run this script from the bot directory."
    exit 1
fi

# Step 1: Create necessary directories
echo "📁 Creating directory structure..."
mkdir -p logs
mkdir -p backups

# Step 2: Install Python dependencies (if venv doesn't exist)
if [[ ! -d "insider_bot_env" ]]; then
    echo "🐍 Creating Python virtual environment..."
    python3 -m venv insider_bot_env
    source insider_bot_env/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    echo "✅ Virtual environment created"
else
    echo "✅ Virtual environment already exists"
fi

# Step 3: Validate environment file
if [[ ! -f ".env" ]]; then
    echo "⚠️  .env file not found!"
    echo "   Please create .env with your API credentials before starting the service."
    echo "   Use .env.example as a template."
fi

# Step 4: Set up systemd service
echo "🔧 Setting up systemd service..."

# Update paths in service file
sed "s|/home/ubuntu/insider_bot|$PWD|g" insider-bot.service > /tmp/insider-bot.service
sed -i "s|User=ubuntu|User=$USER|g" /tmp/insider-bot.service
sed -i "s|Group=ubuntu|Group=$USER|g" /tmp/insider-bot.service

# Install service file (requires sudo)
echo "   Installing service file..."
sudo cp /tmp/insider-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME
echo "✅ Service installed and enabled"

# Step 5: Set up log rotation
echo "📝 Setting up log rotation..."
sudo cp logrotate.conf /etc/logrotate.d/insider-bot
echo "✅ Log rotation configured"

# Step 6: Set correct permissions
echo "🔒 Setting permissions..."
chmod +x main.py
chmod 755 logs/
find . -name "*.py" -exec chmod 644 {} \;
find . -name "*.sh" -exec chmod +x {} \;

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
echo "📝 Log Files:"
echo "   Application: $PWD/insider_bot.log"
echo "   Service:     $PWD/logs/service.log"
echo "   System:      sudo journalctl -u $SERVICE_NAME"
echo
echo "🔄 The bot will automatically:"
echo "   ✅ Start on system boot"
echo "   ✅ Restart if it crashes"
echo "   ✅ Rotate logs daily"
echo "   ✅ Run with resource limits (1GB RAM, 50% CPU)"
echo
echo "⚠️  Remember to:"
echo "   1. Configure your .env file with API credentials"
echo "   2. Test with paper trading first"
echo "   3. Monitor logs for the first few hours"
echo

# Cleanup
rm -f /tmp/insider-bot.service