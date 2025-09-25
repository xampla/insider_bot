# Ubuntu Production Deployment Guide

## 🚀 **Directory Agnostic** - Works Anywhere!

The deployment automatically detects your setup:
- ✅ **Any directory** (`/home/user/bot`, `/opt/trading`, `/var/apps/insider_bot`)
- ✅ **Any user** (ubuntu, ec2-user, john, trading-user)
- ✅ **Auto-configuration** (no manual path editing)

## Quick Setup (3 Steps)

### 1. Deploy as Service
```bash
# From your bot directory (wherever you cloned it):
chmod +x deploy.sh
./deploy.sh
```

**The script will auto-detect:**
```
🔍 Auto-detected Configuration:
   User: your-username
   Group: your-group
   Directory: /your/actual/path/insider_bot
   Service: insider-bot
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
✅ **Fully portable** (works from any directory/user)

## Log Files

- **Application**: `insider_bot.log` (bot activity)
- **Service**: `logs/service.log` (systemd output)
- **System**: `sudo journalctl -u insider-bot` (system logs)

## Example Deployments

**Ubuntu Server:**
```bash
/opt/trading/insider_bot/
├── insider_bot.log          # Main application log
├── logs/service.log         # Service output
├── insider_trading_bot.db   # Database
└── .env                     # API credentials
```

**Home Directory:**
```bash
/home/trader/projects/insider_bot/
├── insider_bot.log          # Main application log
├── logs/service.log         # Service output
├── insider_trading_bot.db   # Database
└── .env                     # API credentials
```

**EC2 Instance:**
```bash
/home/ec2-user/insider_bot/
├── insider_bot.log          # Main application log
├── logs/service.log         # Service output
├── insider_trading_bot.db   # Database
└── .env                     # API credentials
```

That's it! Clone anywhere, run `./deploy.sh`, and the bot will run indefinitely! 🚀