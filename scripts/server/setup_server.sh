#!/usr/bin/env bash
# One-time, idempotent setup of the Artha server: Oracle Cloud Always Free,
# Ubuntu 24.04 aarch64. Run as the login user:
#   bash ~/artha/scripts/server/setup_server.sh
#
# Installs the toolchain and the code, and deliberately STOPS THERE. It does
# not copy data and does not install the crontab: that is the cutover, a
# separate step, so the laptop and the server never run the same paper book
# at the same time.
set -euo pipefail

sudo timedatectl set-timezone Asia/Kolkata  # cron runs on local time: jobs are IST
sudo apt-get update -qq
sudo apt-get install -y -qq git cron curl
sudo systemctl enable --now cron

if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

repo="$HOME/artha"
if [ ! -d "$repo/.git" ]; then
  git clone https://github.com/vj0246/artha.git "$repo"
fi
git -C "$repo" pull --ff-only
cd "$repo"
uv sync --frozen

mkdir -p "$HOME/quant-data/reports/paper" "$HOME/.config/artha"
touch "$HOME/.config/artha/env"
chmod 600 "$HOME/.config/artha/env"

echo "setup complete $(date -Is), timezone $(timedatectl show -p Timezone --value)"
echo "next: copy data, then at cutover:  crontab $repo/scripts/server/crontab"
