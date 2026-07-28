# Microsoft 365 Migration Suite

Enterprise-grade Microsoft 365 migration platform for migrating Exchange Online, SharePoint Online, OneDrive, Microsoft Teams, Planner, Power BI, Power Platform, Viva Engage, and other Microsoft 365 workloads using Microsoft Graph APIs.

---

# Features

* Exchange Online Migration
* SharePoint Online Migration
* OneDrive Migration
* Microsoft Teams Migration
* Planner Migration
* Power BI Migration
* Power Platform Migration
* Viva Engage Migration
* Azure AD / Entra ID Integration
* Microsoft Graph API Support
* Secure Credential Encryption
* JWT Authentication
* Real-time Migration Dashboard
* Project-based Migration Management
* Email Notifications
* Audit Logs
* Live Connection Testing

---

# Technology Stack

| Component        | Technology              |
| ---------------- | ----------------------- |
| Frontend         | React                   |
| Backend          | FastAPI (Python)        |
| Database         | MongoDB                 |
| Authentication   | JWT                     |
| Reverse Proxy    | Nginx                   |
| Containerization | Docker & Docker Compose |

---

# System Requirements

| Specification    | Minimum                           | Recommended                     |
| ---------------- | --------------------------------- | ------------------------------- |
| CPU              | 2 Cores                           | 4+ Cores                        |
| RAM              | 4 GB                              | 8–16 GB                         |
| Storage          | 40 GB SSD                         | 100+ GB SSD                     |
| Operating System | Ubuntu 22.04 / Debian 12 / RHEL 9 | Ubuntu 24.04 LTS                |
| Network          | HTTPS (443)                       | HTTPS + Internal Backend Access |

### Required Network Access

Outbound connectivity must be allowed to:

* `graph.microsoft.com`
* `login.microsoftonline.com`
* `*.sharepoint.com`

Inbound Ports:

| Port  | Purpose                      |
| ----- | ---------------------------- |
| 443   | HTTPS                        |
| 80    | HTTP Redirect                |
| 8001  | Backend API (Internal)       |
| 27017 | MongoDB (Internal)           |
| 3000  | React Development (Optional) |

---

# Deployment Options

* **Path A — Docker Compose (Recommended)**
* **Path B — Native Linux Installation (systemd)**

---

# Path A – Docker Deployment

## 1. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

Log out and log back in.

---

## 2. Clone the Repository

```bash
git clone https://github.com/<your-org>/m365-migration-suite.git
cd m365-migration-suite
```

---

## 3. Configure Backend Environment

Create:

```
backend/.env
```

```env
MONGO_URL=mongodb://mongo:27017
DB_NAME=migration_prod

CORS_ORIGINS=https://migrate.yourcorp.com

JWT_SECRET=<64-character-random-secret>

CONN_ENCRYPTION_KEY=<Existing Fernet Key>

ADMIN_EMAIL=admin@yourcorp.com
ADMIN_PASSWORD=<StrongPassword>

EMAIL_PROVIDER=resend
RESEND_API_KEY=
SENDGRID_API_KEY=
```

Generate a JWT secret:

```bash
openssl rand -hex 32
```

---

## 4. Configure Frontend Environment

Create:

```
frontend/.env
```

```env
REACT_APP_BACKEND_URL=https://migrate.yourcorp.com
```

---

## 5. Docker Compose

Create `docker-compose.yml`

```yaml
services:
  mongo:
    image: mongo:7
    restart: unless-stopped
    volumes:
      - mongo_data:/data/db
    networks:
      - migrate

  backend:
    build:
      context: ./backend
    env_file:
      - ./backend/.env
    depends_on:
      - mongo
    restart: unless-stopped
    networks:
      - migrate

  frontend:
    build:
      context: ./frontend
    depends_on:
      - backend
    restart: unless-stopped
    networks:
      - migrate

  nginx:
    image: nginx:alpine
    restart: unless-stopped
    depends_on:
      - backend
      - frontend
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./certs:/etc/nginx/certs:ro
    networks:
      - migrate

volumes:
  mongo_data:

networks:
  migrate:
```

---

## 6. Backend Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn","server:app","--host","0.0.0.0","--port","8001"]
```

---

## 7. Frontend Dockerfile

```dockerfile
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json yarn.lock ./

RUN yarn install --frozen-lockfile

COPY . .

RUN yarn build

FROM nginx:alpine

COPY --from=build /app/build /usr/share/nginx/html
COPY --from=build /app/nginx-spa.conf /etc/nginx/conf.d/default.conf
```

---

## 8. Frontend Nginx Configuration

```nginx
server {

    listen 80;

    root /usr/share/nginx/html;

    index index.html;

    location / {
        try_files $uri /index.html;
    }

}
```

---

## 9. Reverse Proxy Configuration

```nginx
server {

    listen 80;

    server_name migrate.yourcorp.com;

    return 301 https://$host$request_uri;

}

server {

    listen 443 ssl http2;

    server_name migrate.yourcorp.com;

    ssl_certificate     /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;

    client_max_body_size 100M;

    location /api/ {

        proxy_pass http://backend:8001/api/;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        proxy_read_timeout 300;

    }

    location / {

        proxy_pass http://frontend:80;

        proxy_set_header Host $host;

    }

}
```

---

## 10. Configure SSL

Use Let's Encrypt:

```bash
certbot certonly --standalone -d migrate.yourcorp.com
```

Copy:

```
fullchain.pem
privkey.pem
```

to:

```
certs/
```

---

## 11. Start the Platform

```bash
docker compose up -d
```

View logs:

```bash
docker compose logs -f
```

Open:

```
https://migrate.yourcorp.com
```

Login using the administrator credentials configured in `backend/.env`.

---

# Path B – Manual Installation

## Install Dependencies

```bash
sudo apt update

sudo apt install -y \
python3.11 \
python3.11-venv \
python3-pip \
mongodb \
nginx \
nodejs \
npm

sudo npm install -g yarn serve
```

---

## Clone Repository

```bash
git clone https://github.com/<your-org>/m365-migration-suite.git /opt/migrate

cd /opt/migrate/backend
```

---

## Backend Setup

```bash
python3.11 -m venv venv

source venv/bin/activate

pip install -r requirements.txt
```

Create:

```
/opt/migrate/backend/.env
```

using the same variables as the Docker deployment, but set:

```env
MONGO_URL=mongodb://localhost:27017
```

---

## Frontend Build

```bash
cd /opt/migrate/frontend

yarn install

yarn build
```

The production build is created in:

```
frontend/build
```

---

## Enable Services

```bash
sudo systemctl enable --now mongod
sudo systemctl reload nginx
```

---

# Security Recommendations

* Rotate all secrets before production deployment.
* Preserve the existing `CONN_ENCRYPTION_KEY` if previously encrypted tenant credentials must remain accessible.
* Enable MongoDB authentication.
* Restrict ports `8001` and `27017` to internal access only.
* Enforce TLS 1.2 or newer.
* Configure HSTS headers.
* Enable Fail2Ban for Nginx.
* Configure log rotation.

---

# Backup Strategy

Nightly MongoDB backup:

```bash
mongodump --uri="$MONGO_URL" --out=/backup/mongo/$(date +%F)
```

Recommended backup destinations:

* Azure Blob Storage
* Amazon S3
* NAS
* Secure Remote Server

---

# Health Checks

Backend:

```bash
curl https://migrate.yourcorp.com/api/
```

Authentication:

```bash
curl -X POST https://migrate.yourcorp.com/api/auth/login \
-H "Content-Type: application/json" \
-d '{"email":"admin@yourcorp.com","password":"<password>"}'
```

---

# Post-Deployment Verification

1. Open the web application.
2. Sign in using the administrator account.
3. Configure Microsoft Entra ID source and destination connections.
4. Test both connections.
5. Create a new migration project.
6. Load the saved tenant connections.
7. Discover Microsoft 365 resources.
8. Start a migration.
9. Monitor migration progress through the dashboard.

---

# License

Internal Enterprise License.

---

# Support

For deployment assistance, troubleshooting, or feature requests, contact your system administrator or the project maintainers.
