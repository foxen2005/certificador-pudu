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

El backend **no puede correr en Cloudflare Workers** por sus dependencias nativas (`lxml`, `cryptography`, `reportlab`).

Opciones recomendadas:
- **Railway** — conecta el repo GitHub, apunta a `backend/`, usa `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Render** — igual a Railway
- **Fly.io** — usa el `Dockerfile` si se agrega
- **VPS** — instalar Python 3.11+ y correr con systemd o supervisor

Una vez desplegado, configura la variable `SII_BACKEND_URL` en Lovable → Secrets con la URL pública del backend.
