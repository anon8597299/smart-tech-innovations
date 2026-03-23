# Deploy IYS Dashboard to dashboard.improveyoursite.com

## Files Created
- `requirements.txt` — Python dependencies
- `Procfile` — Deployment start command
- `runtime.txt` — Python version
- `render.yaml` — Render config (optional)
- Updated `app.py` with basic auth middleware

## Deployment Options

### Option 1: Render.com (Recommended - Free Tier)

1. **Push to GitHub:**
   ```bash
   cd /Users/jamesburke/.openclaw/workspace/smart-tech-innovations
   git add dashboard/requirements.txt dashboard/Procfile dashboard/runtime.txt dashboard/app.py dashboard/DEPLOY.md
   git commit -m "Add dashboard deployment config + basic auth"
   git push origin main
   ```

2. **Deploy on Render:**
   - Go to https://render.com and sign in with GitHub
   - Click "New +" → "Web Service"
   - Connect your `smart-tech-innovations` repo
   - Settings:
     - Name: `iys-dashboard`
     - Region: Oregon (or closest to Sydney)
     - Branch: `main`
     - Root Directory: `dashboard`
     - Runtime: Python 3
     - Build Command: `pip install -r requirements.txt`
     - Start Command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
   - Environment Variables:
     - `ANTHROPIC_API_KEY` = (copy from builder/.env)
     - `DASHBOARD_PASSWORD` = (generate secure password — save this!)
     - `DASHBOARD_AUTH` = `true`
   - Click "Create Web Service"

3. **Get your URL:**
   - Render will give you a URL like `https://iys-dashboard.onrender.com`

4. **Configure GoDaddy DNS:**
   - Go to GoDaddy DNS settings for improveyoursite.com
   - Add CNAME record:
     - Type: CNAME
     - Name: `dashboard`
     - Value: `iys-dashboard.onrender.com`
     - TTL: 600
   - Wait ~5-10 minutes for DNS propagation

5. **Test:**
   - Visit https://dashboard.improveyoursite.com
   - Login: username `james`, password = whatever you set

---

### Option 2: Railway.app (Alternative)

1. Install Railway CLI: `brew install railway`
2. Login: `railway login`
3. Deploy:
   ```bash
   cd /Users/jamesburke/.openclaw/workspace/smart-tech-innovations/dashboard
   railway init
   railway up
   railway variables set ANTHROPIC_API_KEY="sk-ant-..."
   railway variables set DASHBOARD_PASSWORD="<secure-password>"
   railway variables set DASHBOARD_AUTH="true"
   railway domain
   ```
4. Configure GoDaddy CNAME to point to Railway domain

---

## Security

**Auth credentials:**
- Username: `james`
- Password: Set via `DASHBOARD_PASSWORD` env var

To disable auth (localhost only):
- Set `DASHBOARD_AUTH=false`

## Notes

- Free tier on Render: project sleeps after 15 min inactivity (cold start ~30s)
- SQLite database resets on redeploy (transient storage)
- SSE connection from Mac mini agents won't push to remote dashboard yet (local-only for now)
- To enable remote SSE push, agents need to POST events to `https://dashboard.improveyoursite.com/api/events`

---

## Next Steps After Deployment

1. Test dashboard.improveyoursite.com loads and requires auth
2. Verify agent data displays (may be empty initially — agents run on Mac mini)
3. Optional: Update local agents to also push events to remote dashboard via webhook
