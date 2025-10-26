# MalTrackarr

**MalTrackarr** is a lightweight Python + Flask microservice that fetches your **MyAnimeList** "Watching" anime list and merges it with the [Kometa-Team Anime IDs](https://github.com/Kometa-Team/Anime-IDs) dataset.

It produces a clean JSON response containing MAL, TVDB, and IMDb identifiers — ideal for syncing your anime collection across different metadata sources like Plex, Jellyfin, or Trakt.

---

## Features

- **Automatic OAuth2 Token Management**
  - Automatically refreshes or regenerates access tokens for MyAnimeList API.
- **MAL “Watching” List Fetching**

  - Retrieves your current anime list directly from MyAnimeList’s API.

- 🔗 **Dataset Integration**

  - Maps each MAL anime to its corresponding TVDB and IMDb IDs using the [Kometa-Team Anime-IDs](https://github.com/Kometa-Team/Anime-IDs) dataset.

- **Unified Output Format**

  - Provides both `imdb_id` and `imdbId` naming styles for compatibility with different tools.

- **Docker Ready**
  - Deploy anywhere with a single container.

---

## Project flow

1. App starts and reads config.json (path adjustable via CONFIG_PATH env var).

2. Validate access_token:

   - If present and not expired → continue.

   - If missing/expired:
     - Try refresh_token flow (POST /v1/oauth2/token with grant_type=refresh_token).
     - If missing or refresh fails, try authorization_code flow (POST /v1/oauth2/token with grant_type=authorization_code).

3. Store tokens (access_token, refresh_token, expires_at) back to config.json.

4. Query MAL API: GET /v2/users/{username}/animelist?status={status} — follow pagination via paging.next.

5. Download anime_ids.json from Kometa-Team GitHub raw URL and map entries by mal_id.

6. For each MAL entry, look up mal_id in the map and attach tvdbId and imdb_id/imdbId if present.

7. Return an array of simplified objects through the /animelist HTTP endpoint.

## Configuration (config.json)

Create config.json in repository root (or mount via Docker):

```json
{
  "client_id": "YOUR_MAL_CLIENT_ID",
  "client_secret": "YOUR_MAL_CLIENT_SECRET",
  "authorization_code": "YOUR_AUTHORIZATION_CODE",
  "code_verifier": "YOUR_CODE_VERIFIER"
}
```

## Setup & run (local)

1. Clone repo:

```bash
git clone https://github.com/<your-user>/MalTrackarr.git
cd MalTrackarr
```

2. Create config.json as above.

3. Create virtualenv and install:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

4. Run:

```bash
python app.py
```

5. Access:

```bash
http://localhost:8080/animelist?username=YOUR_USERNAME&status=LIST_TYPE
```

## Docker

Create docker-compose.yml:

```yaml
version: "3.8"
services:
  maltrackarr:
    image: sittravell/maltrackarr:latest
    container_name: maltrackarr
    ports:
      - "3434:3434"
    volumes:
      - ./config.json:/app/config.json
```

Run:

```bash
docker compose up -d
```

## Example Output

```json
[
  {
    "title": "Cowboy Bebop",
    "malId": 1,
    "tvdbId": 76885,
    "imdb_id": "tt0213338",
    "imdbId": "tt0213338"
  },
  {
    "title": "Attack on Titan",
    "malId": 16498,
    "tvdbId": 267440,
    "imdb_id": "tt2560140",
    "imdbId": "tt2560140"
  }
]
```
