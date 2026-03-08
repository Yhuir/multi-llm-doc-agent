# multi-llm-doc-agent

V1 skeleton now uses `React + FastAPI + Worker`.

## Run backend API

```bash
python -m pip install -r requirements.txt
uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000
```

## Run React UI

```bash
cd ui
npm install
npm run dev
```

Default UI URL: `http://localhost:5173`

If backend is not on `http://localhost:8000`, set env before starting UI:

```bash
VITE_API_BASE=http://localhost:8000 npm run dev
```
