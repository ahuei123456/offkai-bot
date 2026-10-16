# Offkai Bot Frontend

A Next.js frontend application that serves as the RSVP page and check-in portal for the Offkai Discord Bot. It integrates directly with the bot's JSON databases (`events.json`, `responses.json`, and `checkins.json`) to provide real-time updates and staff check-in capabilities.

## Features

- **Attendee RSVP Interface**: A clean, responsive page displaying the active event name, venue, Google Maps link, date/time, registration status, and a personal QR code for attendees to check in.
- **Staff Check-In Dashboard**: A password-protected panel (located at `/admin`) authorizing staff to scan attendee QR codes using their device camera (via `html5-qrcode`) or manually look up and check in attendees by name.
- **Direct Database Integration**: Reads directly from the shared bot databases and logs check-ins to `checkins.json`.
- **Health Check API**: Endpoint at `/api/health` for docker orchestrator monitoring.

## Check-in identity and migration

Physical arrival comes only from a check-in for the current attending registration,
identified by event, user ID, and `registration_timestamp` (the signup timestamp
normalized to ISO UTC milliseconds, matching the existing payment/admin identity
convention). Signup `arrival_confirmed` is an acknowledgement, not arrival evidence.
Withdrawal, import replacement, or re-registration with a different signup timestamp
does not inherit an earlier arrival, including its guests. Imports must preserve the
timestamp only when preserving the same registration; replacement signups need a new
timestamp.

Legacy `checkins.json` entries without `registration_timestamp` are conservatively
ignored, not automatically assigned to whichever registration exists at upgrade.
Staff must re-scan or manually check in those attendees after deployment. Historical
entries can remain in storage; checkout removes only the current registration's
check-ins. New writes use a same-directory temporary file, fsync, then atomic rename;
failed writes still return `database_write_error` rather than success.

Manual check-in/out API requests must include the displayed row's
`registration_timestamp`; a replaced registration returns HTTP 409
`registration_changed`. Event-switch guards reject actions on old visible rows and
discard delayed mutation/scan responses. Existing QR token formats remain unchanged
and scans resolve the current registration.

Isolated regression smoke (no Discord or production data required), from `frontend/`:

```bash
node --experimental-strip-types --test app/api/checkin-integrity.test.ts app/api/checkin-event-switch.test.ts
```

These exercise actual routes against temporary JSON files and actual hook callbacks
against deferred responses: solo arrival → replacement plus three guests → pending,
new scan → arrived → checkout → pending, legacy invalidation, failed atomic rename,
and event switches (including A → B → A) while mutations/scans are outstanding.

## Directory structure

- `app/`: Next.js 15 App Router pages and layouts.
  - `page.tsx`: The main attendee RSVP card.
  - `admin/page.tsx`: Administrative staff check-in dashboard.
  - `api/db.ts`: Database utility layer to read/write JSON files.
  - `api/attendee/`: API route to get a single attendee's details.
  - `api/attendees/`: API route to list all attendees for admin dashboard.
  - `api/checkin/`: API route to process attendee check-ins.
  - `api/health/`: Simple service health endpoint.
- `offkai-bot-data/`: Mount point for the shared bot data folder in Docker.

## Configuration

The frontend uses environment variables for configuration:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ADMIN_KEY` | ✅ | `""` | The password required to access the `/admin` check-in panel. |
| `BOT_DATA_DIR` | ❌ | `../data` | Directory containing bot data JSON files (mounted to `/app/offkai-bot-data` in container). |
| `MOCK_MODE` | ❌ | `false` | Set to `true` to run the frontend with mock data (useful for frontend styling/design iteration). |

## How to Run

### Option A: Local Development

1. Navigate to the `frontend/` directory:
   ```bash
   cd frontend
   ```
2. Install npm dependencies:
   ```bash
   npm install
   ```
3. Set your environment variables in `frontend/.env.local` or symlink from the root `.env`:
   ```bash
   ln -s ../.env .env.local
   ```
4. Start the development server:
   ```bash
   npm run dev
   ```
   Open [http://localhost:3000](http://localhost:3000) (or specify a port like `npm run dev -- -p 8090`).

### Option B: Docker Container (Standalone)

The frontend Dockerfile is structured to compile Next.js in `standalone` output mode for production-grade performance.

Build and run the container locally:
```bash
docker build -t offkai-frontend .
docker run -p 8090:8090 -v $(pwd)/../data:/app/offkai-bot-data -e ADMIN_KEY=yoursecret offkai-frontend
```

*(Note: In production deployments, it is recommended to run the unified Docker Compose configuration from the repository root).*
