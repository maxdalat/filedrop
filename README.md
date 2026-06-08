# filedrop

Secured Flask file browser with account requests, administrator approval, per-user home folders, and administrator access to the shared upload root.

Passwords are stored as salted `scrypt` hashes. Sessions are server-side records handed to the browser as opaque, HttpOnly cookies signed with a runtime-generated RSA keypair. Local runtime state belongs in `instance/`, and local uploaded files belong in `uploads/`. Docker deployments store both under `/data` so the container can be replaced without deleting user data.

## Run with Docker

Persist `/data` outside the container:

```sh
docker build -t filedrop .
docker run --rm -p 8000:8000 \
  -v filedrop-data:/data \
  filedrop
```

Open <http://localhost:8000>. On a fresh installation, the first visitor is redirected to a one-time setup page to choose the initial administrator username, email address, and password.

You can also use Docker Compose:

```sh
docker compose up --build
```

The Docker image runs Gunicorn with threaded request handling so uploads do not block folder browsing, downloads, or page reloads.

## Coolify Persistence

Filedrop follows the same deployment pattern as apps like Immich: the Docker image is disposable, and user data lives in persistent storage mounted into the container.

In Coolify, add persistent storage for the app:

- Mount path: `/data`
- Contents: SQLite database, session signing keys, and uploaded files
- Keep this storage when redeploying or rebuilding the app

Redeploying the app should not delete files as long as the same persistent storage remains attached. Deleting the Coolify persistent storage volume, changing the mount path, or deploying without the `/data` mount will create a fresh empty install.

The image includes a Docker health check for Coolify. It probes `/api/health` every 10 seconds and reports live container health after verifying SQLite access and the writable upload directory. Coolify will surface the health state automatically when health checks are enabled for the application.

When deploying behind HTTPS, set `FILEDROP_SECURE_COOKIES=true`. This adds the browser's `Secure` flag to session cookies. Do not expose the app publicly over plain HTTP.

## Run Locally

Start the app without administrator environment variables:

```powershell
py -3 app.py
```

Open <http://localhost:8000>. If `instance/filedrop.db` has no users, the app opens the one-time administrator setup page. Existing installations keep their current accounts.

## Account Flow

New users request an account with a username, email address, and password. The app stores the email address but does not send or verify email. An administrator approves or denies each request.

An administrator can issue a temporary password or promote an approved user to administrator from the account-management page. Temporary passwords are displayed once, existing sessions are revoked, and the user must choose a new password after signing in.

The initial administrator can never be demoted. Other administrators can be promoted or demoted from the account-management page.

Files can be dragged into folders, and selected items can be grouped into a new folder. The file-browser settings let each user keep duplicate names as numbered copies or replace existing items.

The appearance setting is remembered in the browser and applies to every page. New browsers follow the operating-system theme until a preference is chosen.

## Optional Paths

For a non-Docker deployment, runtime directories can be moved with:

```sh
FILEDROP_INSTANCE_PATH=/secure/path/filedrop-instance
FILEDROP_UPLOAD_PATH=/data/filedrop-uploads
```
