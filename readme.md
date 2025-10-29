## Deploy (GitHub Actions)

This repository auto-deploys to **Google Cloud Run** whenever code is pushed to `main`.  
The workflow uses **OIDC authentication** (no JSON keys or secrets).

**Service URL:** https://<your-live-service-url>.a.run.app  
(Replace with the actual URL printed in the GitHub Actions logs.)

### Contracts

| Endpoint | Request | Response |
|-----------|----------|-----------|
| `GET /healthz` | – | `{ "ok": true, "project": "ing-voice-team35", "location": "europe-west1" }` |
| `POST /tts` | `{ "text": "Hello", "lang": "nl-BE" \| "fr-BE" \| "en-GB" }` | `{ "audio": "<base64-mp3>" }` |
| `POST /stt` | `{ "audio": "<base64-wav/mp3>", "lang"?: "nl-BE" \| "fr-BE" \| "en-GB" }` | `{ "text": "<transcribed text>" }` |

### Environment variables

| Name | Example value | Description |
|------|----------------|-------------|
| `GCP_PROJECT` | `ing-voice-team35` | Google Cloud project ID |
| `VERTEX_LOCATION` | `europe-west1` | Region |
| `DATA_ROOT` | `/app/data` | Data root path |
| `CHUNKS_ROOT` | `/app/data/chunks` | Audio chunks path |
| `SYNTHETIC_ROOT` | `/app/data/synthetic_data` | Synthetic data path |

---

## Common pitfalls (to avoid)

- **Wrong app path in Dockerfile or cloudrun.yaml** → must be `app.backend.main:app`.  
- **Region mismatch** → use `europe-west1` everywhere (Cloud Run, Artifact Registry, Vertex, etc.).  
- **Slow cold starts** → `minScale: 1` already set in `cloudrun.yaml`.  
- **Missing OIDC binding** → ensure the GitHub repo can impersonate `github-deployer@ing-voice-team35.iam.gserviceaccount.com`.  
- **Forgot variables** → if not hard-coded, add to GitHub → Settings → Actions → Variables:  
  - `GCP_PROJECT_ID = ing-voice-team35`  
  - `GCP_PROJECT_NUMBER = <your numeric project number>`  

---

## Flow to reproduce from scratch

1. **Create GCP project:** `ing-voice-team35`, link billing.  
2. **Enable APIs:** Run/Build/Artifact Registry/IAM Credentials.  
3. **Create service account:** `github-deployer` + roles (`run.admin`, `cloudbuild.builds.editor`, `artifactregistry.writer`).  
4. **Set up OIDC:** create pool/provider (`github-pool` / `github-provider`), bind your repo to the SA.  
5. **Create Artifact Registry:**  
   ```bash
   gcloud artifacts repositories create ing-voice \
     --repository-format=docker \
     --location=europe-west1
