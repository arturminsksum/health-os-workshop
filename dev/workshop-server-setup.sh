#!/usr/bin/env bash
# Настройка общего учебного сервера: N учётных записей, у каждой своя копия проекта и своя страница.
# Запуск от root:  OPENAI_API_KEY=sk-... USERS=10 bash workshop-server-setup.sh
# Пишет карточки участников в /root/workshop-cards.txt (логин, пароль, адрес страницы).
set -euo pipefail
USERS="${USERS:-10}"
REPO="https://github.com/iamdzennn/health-os-workshop.git"
IP="$(curl -s -4 ifconfig.me)"
: "${OPENAI_API_KEY:?нужен OPENAI_API_KEY}"

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q git python3-pil nodejs npm nano >/dev/null
npm install -g -s @anthropic-ai/claude-code @openai/codex >/dev/null

# вход по паролю (в облачном образе Ubuntu выключен)
echo "PasswordAuthentication yes" > /etc/ssh/sshd_config.d/60-workshop.conf
systemctl restart ssh

# страница каждого участника работает всегда, как служба
cat > /etc/systemd/system/healthos-web@.service <<'UNIT'
[Unit]
Description=Health OS page for %i
After=network-online.target
[Service]
User=%i
WorkingDirectory=/home/%i/health-os
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 run.py web
Restart=always
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload

: > /root/workshop-cards.txt
for n in $(seq 1 "$USERS"); do
  u="user$n"
  port=$((8600 + n))
  pw="$(python3 -c 'import secrets,string;a=string.ascii_lowercase+string.digits;print("".join(secrets.choice(a) for _ in range(10)))')"
  id "$u" >/dev/null 2>&1 || useradd -m -s /bin/bash "$u"
  echo "$u:$pw" | chpasswd
  chmod 700 "/home/$u"
  sudo -u "$u" bash -c "cd ~ && rm -rf health-os && git clone -q $REPO health-os"
  cat > "/home/$u/health-os/.env" <<ENV
OPENAI_API_KEY=$OPENAI_API_KEY
OPENAI_MODEL=gpt-5.4-mini
TELEGRAM_BOT_TOKEN=
WEB_PORT=$port
WEB_PASSWORD=$pw
PUBLIC_URL=http://$IP:$port
REMIND_HOUR=9
REMIND_DAYS_AHEAD=14
ENV
  chown "$u:" "/home/$u/health-os/.env"; chmod 600 "/home/$u/health-os/.env"
  systemctl enable -q --now "healthos-web@$u"
  printf 'Health OS — карточка участника\nВход на сервер:  ssh %s@%s\nПароль:          %s\nСтраница:        http://%s:%s  (логин любой, пароль тот же)\n\n' \
    "$u" "$IP" "$pw" "$IP" "$port" >> /root/workshop-cards.txt
done
echo "Готово: $USERS участников, карточки в /root/workshop-cards.txt"
