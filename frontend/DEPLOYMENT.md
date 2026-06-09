# Frontend Deployment

This Next.js application compiles in `standalone` output mode and runs inside a production-ready alpine Docker container listening on port `8090`.

## Production Deployment (Recommended)

In production, the frontend is deployed alongside the Discord bot using the root `compose.yml` file. This ensures both containers mount the shared `data/` volume for real-time JSON database sharing.

### Deployment Steps on Host

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/ahuei123456/offkai-bot.git
   cd offkai-bot
   ```

2. **Configure Environment Secrets**:
   Create a `.env` file at the root:
   ```env
   DISCORD_TOKEN=your_bot_token_here
   GUILDS=123456789012345678
   ADMIN_KEY=your_secure_admin_password_here
   ```

3. **Configure Bot Paths**:
   Create a `bot/config.json` configuration inside the `bot/` folder pointing to `data/` directories:
   ```json
   {
       "EVENTS_FILE": "data/events.json",
       "RESPONSES_FILE": "data/responses.json",
       "WAITLIST_FILE": "data/waitlist.json",
       "RANKING_FILE": "data/ranking.json"
   }
   ```

4. **Launch the Monorepo Containers**:
   ```bash
   docker compose up -d --build
   ```

5. **Verify Health**:
   ```bash
   curl --fail http://127.0.0.1:8090/api/health
   # {"status":"ok"}
   ```

---

## Automatic CI/CD Redeployment

Every push to the production branch of the repository triggers a redeployment on your production runner.

- **Self-Hosted Runner**:
  - The repository comes configured with a GitHub Actions workflow located at `.github/workflows/deploy-to-pi.yml` which deploys updates to a self-hosted runner.
  - The runner must have permissions to execute `docker compose` and control local container lifecycles.
- **Service Verification**:
  - The deployment script or container automatically runs a Docker HEALTHCHECK polling `/api/health` before considering the deployment successful.
