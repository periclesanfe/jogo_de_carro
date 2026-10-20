#!/bin/bash
# One-time VPS setup (Ubuntu 24.04), as root, next to a copy of jogo-deploy from the same commit, never the copy
# in /srv/jogo/app (the deploy user can write it, and this runs as root):
#   bash setup.sh 'ssh-ed25519 AAAA... jogo-ci'
# Re-run it after changing anything under ops/. It creates the "deploy" user that the CI logs in as, the pinned
# Python runtime and a checkout of the repo, and installs ops/jogo-deploy as that key's only command.
set -euo pipefail
[[ $(realpath "$(dirname "$0")") != /srv/jogo* ]] || { echo "rode de uma cópia fora de /srv/jogo" >&2; exit 2; }

key=${1:-}
if [[ ! $key =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+(\ [A-Za-z0-9._@-]+)?$ ]]; then
    echo "uso: bash setup.sh 'ssh-ed25519 AAAA... jogo-ci'" >&2
    exit 2
fi
REPO=https://github.com/periclesanfe/jogo_de_carro.git
UV_VERSION=0.12.23

apt-get update -qq
apt-get install -y -qq git curl ca-certificates >/dev/null

if ! command -v uv >/dev/null || [[ $(uv --version) != "uv $UV_VERSION"* ]]; then
    curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi
# the baseline build, not the _v2/_v3/_v4 variants: the server must simulate exactly like the browser
UV_PYTHON_INSTALL_DIR=/opt/uv-python uv python install --no-bin cpython-3.12.12-linux-x86_64-gnu

# /srv/jogo and the key belong to root, so the deploy user (which runs the game's code) cannot change its key;
# password '*', not '!': key login then works with "UsePAM no" too
id deploy &>/dev/null || useradd --system --home-dir /srv/jogo --no-create-home --shell /bin/bash --password '*' deploy
install -d -m 755 -o root -g root /srv/jogo /srv/jogo/.ssh
install -d -m 755 -o deploy -g deploy /srv/jogo/app /srv/jogo/cache /srv/jogo/venv
[[ -d /srv/jogo/app/.git ]] || runuser -u deploy -- git clone --quiet "$REPO" /srv/jogo/app
runuser -u deploy -- git -C /srv/jogo/app fetch --quiet origin
# the deploy script comes from the commit this setup.sh was downloaded from
install -m 755 -o root -g root "$(dirname "$0")/jogo-deploy" /usr/local/bin/jogo-deploy
echo "restrict,command=\"/usr/local/bin/jogo-deploy\" $key" >/srv/jogo/.ssh/authorized_keys
chmod 644 /srv/jogo/.ssh/authorized_keys

echo "pronto. secret DEPLOY_KNOWN_HOSTS (troque <host> pelo DEPLOY_HOST; com porta: [host]:porta):"
echo "<host> $(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)"
echo "cpu: $(awk -F': ' '/^model name/ {print $2; exit}' /proc/cpuinfo) | $(nproc) vCPU | $(. /etc/os-release; echo "$PRETTY_NAME")"
