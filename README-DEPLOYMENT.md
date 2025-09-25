# Ubuntu Production Deployment Guide

## Quick Setup (3 Steps)

### 1. Deploy as Service
```bash
# Make deployment script executable
chmod +x deploy.sh

# Run deployment (will ask for sudo password)
./deploy.sh
```

### 2. Configure Credentials
```bash
# Copy and edit environment file
cp .env.example .env
nano .env  # Add your API keys
```

### 3. Start the Bot
```bash
# Start the service
sudo systemctl start insider-bot

# Check status
sudo systemctl status insider-bot
```

## Service Management

```bash
# Start/Stop/Restart
sudo systemctl start insider-bot
sudo systemctl stop insider-bot
sudo systemctl restart insider-bot

# View logs (real-time)
sudo journalctl -u insider-bot -f

# View application logs
tail -f insider_bot.log
```

## What the Service Does

✅ **Auto-starts** on system boot/restart
✅ **Auto-restarts** if the bot crashes
✅ **Logs to files** with automatic rotation
✅ **Resource limits** (1GB RAM, 50% CPU)
✅ **Security** hardening (restricted permissions)

## Log Files

- **Application**: `insider_bot.log` (bot activity)
- **Service**: `logs/service.log` (systemd output)
- **System**: `sudo journalctl -u insider-bot` (system logs)

## File Locations

```
/home/ubuntu/insider_bot/
├── insider_bot.log          # Main application log
├── logs/service.log         # Service output
├── insider_trading_bot.db   # Database
└── .env                     # API credentials
```

That's it! The bot will run indefinitely and survive reboots. 🚀