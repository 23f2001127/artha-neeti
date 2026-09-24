# docker

Container images for the API and the web app. Build from the repository root;
`docker-compose.yml` there wires them together.

| File | Image |
| --- | --- |
| `backend.Dockerfile` | Python 3.11 slim, multi-stage. Runs Uvicorn as a non-root user with a health check on `/`. Includes the agents, API, MCP servers and fonts. |
| `frontend.Dockerfile` | Builds the Vite app with Node, then serves it from unprivileged nginx on port 8080. |
| `nginx.conf.template` | Serves the app with an SPA fallback and long-lived caching for hashed assets. Proxies `/api/` to `${API_UPSTREAM}` (default `http://backend:8000`). |

## Running the stack

```bash
cp .env.example .env         # fill in the four required values
docker compose up --build
```

| Service | URL |
| --- | --- |
| Web app | <http://localhost:8080> |
| API | <http://localhost:8000> (docs at `/docs`) |

The browser calls the API through nginx on the same origin, so no CORS setup is
needed. Uploaded annual reports are kept in the `uploads` volume.

### Local database

To run without a hosted database, start the optional pgvector container and
point the API at it:

```bash
# in .env
DATABASE_URL=postgresql://arthaneeti:arthaneeti@db:5432/arthaneeti

docker compose --profile local-db up --build
```

The API creates its tables on startup. A new database has no annual reports
until they are indexed (see `mcp_servers/filings_rag_mcp`).

## Building images individually

```bash
docker build -f docker/backend.Dockerfile -t arthaneeti-api .
docker build -f docker/frontend.Dockerfile -t arthaneeti-web .

# a web image that calls an API on another origin instead of the /api proxy
docker build -f docker/frontend.Dockerfile \
  --build-arg VITE_API_BASE_DIRECT=https://api.example.com -t arthaneeti-web .
```

The backend image reads `PORT` (default 8000). Render sets it automatically:
`render.yaml` deploys `backend.Dockerfile`. Uvicorn runs with proxy headers
enabled, so per-IP limits see the real client address behind Render or nginx.
