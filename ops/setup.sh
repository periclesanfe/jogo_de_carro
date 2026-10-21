#!/bin/bash
# VPS setup (Ubuntu 24.04), as root, from a copy of ops/ taken from one commit, never the copy in /srv/jogo/app
# (the deploy user can write it, and this runs as root):
#   bash setup.sh 'ssh-ed25519 AAAA... jogo-ci'
# Re-run it after changing anything under ops/: every step is safe to repeat. It creates the "jogo" user that
# the CI logs in as and that runs the server, the pinned Python runtime and a checkout of the repo; installs
# ops/jogo-deploy as that key's only command, jogo.service and its one sudo rule, the daily backup, and the
# nginx site (whose certificate must already exist). /etc/jogo/env is created once and never overwritten.
set -euo pipefail
here=$(realpath "$(dirname "$0")")
[[ $here != /srv/jogo* ]] || { echo "rode de uma cópia fora de /srv/jogo" >&2; exit 2; }
die() { echo "$*" >&2; exit 1; }

key=${1:-}
if [[ ! $key =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+(\ [A-Za-z0-9._@-]+)?$ ]]; then
    echo "uso: bash setup.sh 'ssh-ed25519 AAAA... jogo-ci'" >&2
    exit 2
fi
command -v nginx >/dev/null || die "falta o nginx (este script só instala o site dele)"
REPO=https://github.com/periclesanfe/jogo_de_carro.git
UV_VERSION=0.12.23

apt-get update -qq
apt-get install -y -qq git curl ca-certificates sudo sqlite3 zstd >/dev/null

if ! command -v uv >/dev/null || [[ $(uv --version) != "uv $UV_VERSION"* ]]; then
    curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi
# the baseline build, not the _v2/_v3/_v4 variants: the server must simulate exactly like the browser
UV_PYTHON_INSTALL_DIR=/opt/uv-python uv python install --no-bin cpython-3.12.12-linux-x86_64-gnu

# A user of its own ("deploy" may already exist on the box for something else). /srv/jogo and the key belong to
# root, so this user (which runs the game's code) cannot change its key; password '*', not '!': key login then
# works with "UsePAM no" too
if id jogo &>/dev/null; then
    [[ $(getent passwd jogo | cut -d: -f6) == /srv/jogo ]] || { echo "o usuário jogo já existe com outra home" >&2; exit 2; }
else
    useradd --system --home-dir /srv/jogo --no-create-home --shell /bin/bash --password '*' jogo
fi
install -d -m 755 -o root -g root /srv/jogo /srv/jogo/.ssh
# www: the web root; venvs: one server venv per deployed commit
install -d -m 755 -o jogo -g jogo /srv/jogo/app /srv/jogo/cache /srv/jogo/venv /srv/jogo/venvs /srv/jogo/www
install -d -m 700 -o jogo -g jogo /srv/jogo/www-tmp  # where jogo-deploy unpacks a build before publishing it
chown -Rh jogo:jogo /srv/jogo/app /srv/jogo/cache /srv/jogo/venv  # -h: never the interpreter a venv link points at
install -d -m 750 -o jogo -g jogo /var/lib/jogo  # the database; the only place jogo.service may write
install -d -m 700 -o jogo -g jogo /var/backups/jogo
[[ -d /srv/jogo/app/.git ]] || runuser -u jogo -- git clone --quiet "$REPO" /srv/jogo/app
runuser -u jogo -- git -C /srv/jogo/app fetch --quiet origin
# the deploy and backup scripts come from the commit this setup.sh was downloaded from
install -m 755 -o root -g root "$here/jogo-deploy" "$here/jogo-backup" /usr/local/bin/
echo "restrict,command=\"/usr/local/bin/jogo-deploy\" $key" >/srv/jogo/.ssh/authorized_keys
chmod 644 /srv/jogo/.ssh/authorized_keys

# The server's settings, created once (mode 0600 until complete), with a random SESSION_SECRET
install -d -m 750 -o root -g jogo /etc/jogo
if [[ ! -e /etc/jogo/env ]]; then
    secret=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
    [[ $secret =~ ^[0-9a-f]{64}$ ]] || die "não consegui gerar o SESSION_SECRET"
    tmp=$(mktemp /etc/jogo/.env.XXXXXX)
    # through awk's environment, not its arguments: any local user can read a command line in /proc
    secret=$secret awk '$0 == "SESSION_SECRET=" { $0 = $0 ENVIRON["secret"] } 1' "$here/env.example" >"$tmp"
    grep -qxE 'SESSION_SECRET=[0-9a-f]{64}' "$tmp" || die "env.example sem a linha SESSION_SECRET="
    chown root:jogo "$tmp"
    chmod 640 "$tmp"
    mv "$tmp" /etc/jogo/env
    echo "criado /etc/jogo/env: preencha Google e SMTP quando existirem e guarde uma cópia dele"
fi

# The deploy may restart the server, and nothing else
tmp=$(mktemp)
echo 'jogo ALL=(root) NOPASSWD: /usr/bin/systemctl restart jogo.service' >"$tmp"
visudo -cqf "$tmp" || die "regra do sudo inválida"
install -m 440 -o root -g root "$tmp" /etc/sudoers.d/jogo
rm -f "$tmp"
visudo -cq || die "o sudoers não passa no visudo -c"
# Security updates never restart the server (that would drop every race); the next deploy restarts it
mkdir -p /etc/needrestart/conf.d
# shellcheck disable=SC2016  # perl, written as is
echo '$nrconf{override_rc}{qr(^jogo\.service$)} = 0;' >/etc/needrestart/conf.d/jogo.conf

for unit in jogo.service jogo-backup.service jogo-backup.timer; do
    # before the first deploy the only complaint allowed is the missing venv
    out=$(systemd-analyze verify "$here/$unit" 2>&1 | grep -v ': Command /srv/jogo/venvs/current/bin/uvicorn is not executable: No such file or directory$' || true)
    [[ -z $out ]] || die "systemd-analyze verify $unit: $out"
done
install -m 644 "$here/jogo.service" "$here/jogo-backup.service" "$here/jogo-backup.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --quiet --now jogo-backup.timer
systemctl enable --quiet jogo.service
if [[ -e /srv/jogo/venvs/current ]]; then
    systemctl restart jogo.service  # picks up a changed unit or env; the first deploy starts it otherwise
fi

# The nginx site. The running nginx only ever loads a config that passed nginx -t; when it fails, the previous
# file goes back (so the next reload, e.g. certbot's, still works) and nothing is reloaded.
site=/etc/nginx/sites-available/jogo
link=/etc/nginx/sites-enabled/jogo
if ! cmp -s "$here/nginx/jogo.conf" "$site" || [[ $(readlink "$link") != "$site" ]]; then
    rm -f "$site.bak"
    enabled=
    [[ ! -e $link ]] || enabled=yes
    if [[ $enabled ]]; then cp "$link" "$site.bak"; elif [[ -e $site ]]; then cp "$site" "$site.bak"; fi
    install -m 644 "$here/nginx/jogo.conf" "$site"
    ln -sfn "$site" "$link"
    if ! nginx -tq; then
        if [[ -e $site.bak ]]; then cp "$site.bak" "$site"; else rm -f "$site"; fi
        [[ $enabled ]] || rm -f "$link"
        die "nginx -t falhou: a config anterior do jogo voltou e o nginx não foi recarregado"
    fi
    systemctl reload nginx
    echo "nginx: site do jogo instalado e recarregado (cópia anterior em $site.bak)"
fi

echo "pronto. secret DEPLOY_KNOWN_HOSTS (troque <host> pelo DEPLOY_HOST; com porta: [host]:porta):"
echo "<host> $(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)"
echo "cpu: $(awk -F': ' '/^model name/ {print $2; exit}' /proc/cpuinfo) | $(nproc) vCPU | $(. /etc/os-release; echo "$PRETTY_NAME")"
