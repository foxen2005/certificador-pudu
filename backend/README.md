# Backend — SII Certificador DTE

FastAPI que firma, genera y valida DTEs para certificación SII Chile.

## Instalación

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# Mac/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## Levantar localmente

```bash
uvicorn main:app --reload --port 8000
```

El frontend React espera el backend en `http://localhost:8000` por defecto.

## Variables de entorno

| Variable         | Descripción                              | Default             |
|-----------------|------------------------------------------|---------------------|
| `PORT`          | Puerto del servidor                      | `8000`              |

## Endpoints

| Método | Ruta         | Descripción                                                  |
|--------|-------------|--------------------------------------------------------------|
| POST   | /certificar | Flujo completo: Set de Pruebas + CAFs + PFX → ZIP con XMLs firmados y PDFs |
| POST   | /procesar   | Re-procesar XML EnvioDTE existente → ZIP con PDFs           |
| POST   | /validar    | Validar un PDF ya generado                                   |

## Despliegue en producción

El backend **no puede correr en Cloudflare Workers** por sus dependencias nativas (`lxml`, `cryptography`, `reportlab`) — por eso el frontend (`../src`, TanStack Start) se despliega aparte en Cloudflare Workers y este backend va a **GCP Cloud Run**.

Deploy real: `../cloudbuild.yaml` construye `Dockerfile` (Python 3.12-slim) y hace `gcloud run deploy` al servicio `certificador-sii` en `us-central1` — se dispara con push a `main`, no manualmente.

El frontend le apunta a través del proxy `src/routes/api/sii.$.ts`, que autentica contra Cloud Run con un ID token OIDC (service account en el secret `GCP_SA_KEY_JSON`) o con `SII_BACKEND_TOKEN` como fallback estático — no se usa `SII_BACKEND_URL` vía Lovable Secrets, eso quedó obsoleto.
