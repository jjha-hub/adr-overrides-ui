# ADR Overrides UI (standalone)

Minimal Streamlit app for Adam to review / override ADR platinum on
**ClickHouse Cloud**. Not the Lupine monorepo — deploy this tiny repo only.

## Deploy (Streamlit Community Cloud)

**Important:** Do **not** paste the blob URL (`.../blob/master/streamlit_app.py`).
Use the **interactive picker** or paste only:

`https://github.com/jjha-hub/adr-overrides-ui`

Then in **Advanced settings**:
- Branch: `main`
- Main file path: `streamlit_app.py`

If Deploy spins and greys out:
1. https://share.streamlit.io → Settings → **Linked accounts** → reconnect GitHub
2. Grant access to `jjha-hub/adr-overrides-ui` (private repos need explicit grant)
3. Or use a **public** repo (no secrets in git — password goes in Streamlit Secrets only)

Secrets → paste from `secrets.toml.example` (real password).

## Deploy (Docker / Railway / Render — no Streamlit GitHub)

Build and run locally or on any host:

```bash
docker build -t adr-ui .
docker run -p 8501:8501 \
  -e STREAMLIT_SECRETS_CLICKHOUSE__HOST=so3us9c9hq.us-east-1.aws.clickhouse.cloud \
  -e STREAMLIT_SECRETS_CLICKHOUSE__PORT=8443 \
  -e STREAMLIT_SECRETS_CLICKHOUSE__USER=default \
  -e STREAMLIT_SECRETS_CLICKHOUSE__PASSWORD=YOUR_PASSWORD \
  adr-ui
```

On Railway/Render: connect this repo, set those env vars, expose port 8501.

## Local test

```powershell
cd C:\Users\jayan\Downloads\adr-overrides-ui
copy secrets.toml.example .streamlit\secrets.toml
# edit password if needed
pip install -r requirements.txt
streamlit run streamlit_app.py
```
