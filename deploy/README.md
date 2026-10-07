# Деплой (Hetzner CX22, с нуля)

```bash
# 1. система
apt update && apt install -y docker.io docker-compose-plugin git
# 2. код
git clone <repo> /opt/writing-assistant && cd /opt/writing-assistant
# 3. конфиг
cp .env.example .env && nano .env   # заполнить токены Payme/Telegram/Anthropic
# 4. старт
docker compose -f deploy/docker-compose.prod.yml up -d --build
# 5. миграции
docker compose -f deploy/docker-compose.prod.yml exec api alembic upgrade head
```

HTTPS: добавить certbot отдельным compose-override поверх nginx.
Payme callback доступен на `/payme/callback`, статика лендинга — на `/`.
