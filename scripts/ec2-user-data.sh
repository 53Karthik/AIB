#!/bin/bash
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1

echo "Starting deployment setup..."

# Create a 2GB swap file to prevent Out of Memory errors during npm build
dd if=/dev/zero of=/swapfile bs=128M count=16
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo "/swapfile swap swap defaults 0 0" >> /etc/fstab

# Install dependencies
yum update -y
curl -fsSL https://rpm.nodesource.com/setup_20.x | bash -
yum install -y nodejs git python3 python3-pip

# Set up the application directory
mkdir -p /app
cd /app
git clone https://github.com/Sravanth10/AIB.git .

npm install
npm run build
python3 -m venv /app/.venv
/app/.venv/bin/python -m pip install -r /app/backend/requirements.txt

npm install -g pm2

# Start the server on port 80
cat << 'EOF' > /app/ecosystem.config.cjs
module.exports = {
  apps : [{
    name   : "aib-proto",
    script : "/app/.venv/bin/python",
    args   : "-m backend.server",
    interpreter : "none",
    cwd    : "/app",
    env: {
      PORT: 80,
      HOST: "0.0.0.0"
    }
  }]
}
EOF

pm2 start /app/ecosystem.config.cjs
pm2 save
pm2 startup | tail -n 1 | bash

# Auto update script
cat << 'EOF' > /app/auto-update.sh
#!/bin/bash
cd /app
git fetch origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "Updating..."
    git reset --hard origin/main
    npm install
    npm run build
    /app/.venv/bin/python -m pip install -r /app/backend/requirements.txt
    pm2 restart aib-proto
fi
EOF
chmod +x /app/auto-update.sh
(crontab -l 2>/dev/null; echo "* * * * * /app/auto-update.sh >> /var/log/auto-update.log 2>&1") | crontab -

echo "Deployment setup complete!"
