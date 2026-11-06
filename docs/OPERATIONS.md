# Deployment and operations

## Choose a deployment boundary

Use the foreground launcher for local evaluation. For an unattended single-host deployment, use a dedicated Linux machine, service account, restricted data directory, HTTPS ingress and monitored backups. The supplied units are templates for `/opt/packaging_intelligence`; they are not an automatic production certification or high-availability deployment.

Only one application process may own the database/job worker. Do not run `scripts/run.sh` alongside the service. Ollama is a separately managed optional service; its failure must not be mistaken for complete application failure.

## Dedicated Linux service

Run the following as an operator with sudo, after reviewing paths and ensuring no existing installation uses them. These steps create a separate service account and do not migrate any existing data:

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv poppler-utils tesseract-ocr tesseract-ocr-eng
sudo useradd --system --user-group --home-dir /var/lib/packaging-intelligence --shell /usr/sbin/nologin packaging
sudo git clone https://github.com/ssathvick/packaging_intelligence.git /opt/packaging_intelligence
cd /opt/packaging_intelligence
sudo python3 -m venv .venv
sudo .venv/bin/python -m pip install -r requirements.lock.txt
sudo install -d -o packaging -g packaging -m 700 /var/lib/packaging-intelligence /var/backups/packaging-intelligence
sudo install -m 600 .env.example /etc/packaging-intelligence.env
sudoedit /etc/packaging-intelligence.env
```

Set `AXIOM_DATA=/var/lib/packaging-intelligence`. Keep local origin/host defaults for local-only use, or configure your real HTTPS hostname as described below. Set the correct local Ollama URL. Use simple `NAME=value` syntax compatible with both Bash and systemd; no shell expansion in the service environment file. Root reads this mode-600 file when starting the unit.

```bash
sudo install -m 644 deploy/packaging-intelligence.service /etc/systemd/system/
sudo install -m 644 deploy/packaging-intelligence-backup.service /etc/systemd/system/
sudo install -m 644 deploy/packaging-intelligence-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now packaging-intelligence.service
sudo systemctl enable --now packaging-intelligence-backup.timer
sudo systemctl status packaging-intelligence.service --no-pager
curl --fail http://127.0.0.1:8015/api/health
sudo cat /var/lib/packaging-intelligence/setup-token
```

Complete owner setup promptly through the intended browser origin. If bootstrapping locally on a remote host, use an SSH port forward and localhost origin; configure HTTPS before allowing customer access. Source files under `/opt` should remain operator-owned; the service only needs read access there and write access to its data directory. If changing data locations, update both environment configuration and unit `ReadWritePaths`.

The timer runs around 02:30 in the server's configured timezone with up to five minutes jitter. `Persistent=true` catches missed schedules when the timer starts. Verify its actual schedule and first run. Backup storage is local until you configure independent offsite replication.

## HTTPS and remote access

Provision a domain and valid TLS certificate with your chosen reverse proxy or tunnel. Route that hostname to `http://127.0.0.1:8015` on the same host, preserve the original Host header, and keep port 8015 inaccessible from external networks. Configure:

```dotenv
AXIOM_ORIGINS=https://packaging.example
AXIOM_ALLOWED_HOSTS=packaging.example,www.packaging.example,localhost,127.0.0.1
AXIOM_SECURE_COOKIES=1
AXIOM_PUBLIC_URL=https://packaging.example
```

Replace the example hostname. Redirect HTTP to HTTPS at ingress, configure request/body/time limits, and add edge-level rate limiting appropriate to your deployment. This application does not trust forwarded client-IP headers; login throttling alone is not a comprehensive public traffic control. Keep ingress credentials outside source control. Do not expose the Ollama API.

Restart the app and test login/session persistence, CSRF rejection, an unauthorized project request, uploads, file downloads and canonical redirects through the actual public hostname. Secure cookies intentionally do not work over plain HTTP localhost sign-in. No production tunnel, domain credentials or certificate material are distributed in this repository.

## Routine monitoring

```bash
sudo systemctl status packaging-intelligence.service --no-pager
sudo journalctl -u packaging-intelligence.service -n 100 --no-pager
sudo systemctl list-timers packaging-intelligence-backup.timer --no-pager
sudo journalctl -u packaging-intelligence-backup.service -n 50 --no-pager
curl --fail http://127.0.0.1:8015/api/health
```

Health checks database access and worker-thread state, not actual queue progress, model quality or customer connectivity. Monitor failed/old jobs, connector errors, delivery retries, disk capacity, backup age/verification, process restarts, TLS expiry and model availability. Configure alerts to an accountable operator with incident response and recovery targets. No external alerting service is bundled.

## Backup, verification and restore

For a local checkout, load the same environment used by the application:

```bash
cd /path/to/packaging_intelligence
set -a
source .env
set +a
.venv/bin/python ops/backup.py create /path/to/backup-destination
```

The command prints the newly created backup directory and verified document count. It uses SQLite's online backup API and copies the exact immutable sources referenced by that snapshot. Verification checks database hash, integrity, foreign keys, source hashes and count. A complete manifest is written only after source copying succeeds.

For the systemd installation, run the configured service rather than sourcing its root-owned secrets in your normal shell:

```bash
sudo systemctl start packaging-intelligence-backup.service
sudo journalctl -u packaging-intelligence-backup.service -n 30 --no-pager
```

Use the actual backup directory name returned by the tool:

```bash
.venv/bin/python ops/backup.py verify /path/to/backup-destination/axiompack-TIMESTAMP
.venv/bin/python ops/backup.py restore /path/to/backup-destination/axiompack-TIMESTAMP --target /path/to/new-empty-restore-directory
```

Restore refuses a nonempty target and revokes saved sessions. Test restored data in an isolated instance with a separate port and no enabled external connectivity; review connectors before permitting outbound calls. For live recovery, stop the application, preserve old data for rollback, point `AXIOM_DATA` and service write permissions to the restored directory, set correct ownership, then restart and validate documents, catalog, audit and representative decisions. Never overwrite a running database.

Backups contain customer data. Encrypt and restrict access, replicate offsite, establish retention and disk alerts, and perform timed restore drills. `.env`, TLS/tunnel credentials and model weights are not part of data backups; protect/recover those separately. Inbox files not yet ingested are also outside the referenced-source backup. The backup tool does not automatically delete old backups.

## Account recovery

There is no SMTP reset flow. A trusted local operator can list users or reset a password interactively, using the same `AXIOM_DATA` environment and filesystem identity as the service:

```bash
.venv/bin/python ops/manage.py users
.venv/bin/python ops/manage.py reset-password --email user@example.com
```

Do not put passwords on the command line. Reset prompts twice, records an audit event and revokes that user's sessions. For the system service, a root operator can run the command with `AXIOM_DATA=/var/lib/packaging-intelligence`; protect terminal output because account lists contain personal information.

## Update and rollback

1. Record the deployed commit/tag and environment/dependency versions. Verify a complete backup.
2. Stop the app (leave other unrelated services alone).
3. Check out a reviewed release, install its lockfile and run isolated tests. Do not source production secrets into tests.
4. Restart and check health, worker progress, login, document extraction, audit and a representative synthetic workflow.
5. If rollback is needed, stop the app, restore the prior code and matching dependency environment. Incompatible schema changes require restoring the matching data snapshot to a new directory; reverting code alone is insufficient.

Schema initialization is idempotent and records versions, but it is not a general reversible migration framework. For upgrades of critical deployments, rehearse on a separate restored copy with connectors disabled before switching the live installation.
