# Offkai Bot Frontend

A Next.js frontend application that serves as the RSVP page and check-in portal for the Offkai Discord Bot. It integrates directly with the bot's JSON databases (`events.json`, `responses.json`, and `checkins.json`) to provide real-time updates and staff check-in capabilities.

## Features

- **Attendee RSVP Interface**: A clean, responsive page displaying the active event name, venue, Google Maps link, date/time, registration status, and a personal QR code for attendees to check in.
- **Staff Check-In Dashboard**: A password-protected panel (located at `/admin`) authorizing staff to scan attendee QR codes using their device camera (via `html5-qrcode`) or manually look up and check in attendees by name.
- **Direct Database Integration**: Reads directly from the shared bot databases and logs check-ins to `checkins.json`.
- **Health Check API**: Endpoint at `/api/health` for docker orchestrator monitoring.

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
