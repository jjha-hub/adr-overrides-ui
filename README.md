# ADR Overrides UI (standalone)

Minimal Streamlit app for Adam to review / override ADR platinum on
**ClickHouse Cloud**. Not the Lupine monorepo — deploy this tiny repo only.

## Deploy (Streamlit Community Cloud)

1. Create a **new** GitHub repo (e.g. `adr-overrides-ui`) — private is fine.
2. Push only the files in this folder (`streamlit_app.py`, `requirements.txt`).
3. https://share.streamlit.io → Create app:
   - Repo: that new repo (NOT `equityindexetf`)
   - Branch: `main`
   - Main file: `streamlit_app.py`
4. Secrets → paste from `secrets.toml.example` (real password).
5. Share the `*.streamlit.app` URL with Adam.

Streamlit never needs access to `lupinedata/equityindexetf`.

## Local test

```powershell
cd C:\Users\jayan\Downloads\adr-overrides-ui
copy secrets.toml.example .streamlit\secrets.toml
# edit password if needed
pip install -r requirements.txt
streamlit run streamlit_app.py
```
