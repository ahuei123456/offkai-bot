# offkai-bot-data (Mount Point)

This folder is a local placeholder and mount point. Do not commit actual event JSON files or attendee data here.

## How it works

1. **Docker Container Environment**:
   In production, the root `compose.yml` mounts the shared host directory `./data` into this path:
   ```yaml
   volumes:
     - ./data:/app/offkai-bot-data
   ```
   The Next.js API routes will automatically detect this container folder path (`/app/offkai-bot-data`) and read the JSON databases (`events.json`, `responses.json`, `checkins.json`) directly from it.

2. **Local Development Environment**:
   When running the Next.js server locally (`npm run dev`), the API routes fallback to reading databases from the relative path `../data/` (the host `data` directory at the repository root). Thus, you do not need to populate or link this folder locally.

## What not to do

- **Do not commit production databases** to this repository. The `data/` folder and `frontend/offkai-bot-data/` contents are Git-ignored.
- **Do not put private keys** or bot tokens in this folder.
