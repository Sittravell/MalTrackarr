#!/usr/bin/env python3
import time
import json
import os
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin

import requests
from flask import Flask, jsonify, request, abort

APP_PORT = int(os.getenv("PORT", "8080"))
CONFIG_PATH = os.getenv("CONFIG_PATH", "config.json")
MAL_TOKEN_URL = "https://myanimelist.net/v1/oauth2/token"
MAL_API_BASE = "https://api.myanimelist.net/v2/"

ANIME_IDS_RAW_URL = "https://raw.githubusercontent.com/Kometa-Team/Anime-IDs/master/anime_ids.json"

app = Flask(__name__)
config: Dict[str, Any] = {}


def load_config() -> Dict[str, Any]:
    global config
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
    else:
        config = {}
    return config


def save_config():
    global config
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def now_ts() -> int:
    return int(time.time())


def token_is_valid() -> bool:
    # expecting config to have access_token and expires_at (unix)
    at = config.get("access_token")
    exp = config.get("expires_at", 0)
    if not at:
        return False
    # consider token expired if within 60s of expiry
    return now_ts() + 60 < int(exp)


def request_token_with_refresh(refresh_token: str, client_id: str, client_secret: str) -> Optional[Dict[str, Any]]:
    data = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }
    resp = requests.post(MAL_TOKEN_URL, data=data, timeout=30)
    if resp.status_code == 200:
        return resp.json()
    else:
        app.logger.warning("refresh token request failed %s %s", resp.status_code, resp.text)
        return None


def request_token_with_code(code: str, code_verifier: str, client_id: str, client_secret: str) -> Optional[Dict[str, Any]]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    resp = requests.post(MAL_TOKEN_URL, data=data, timeout=30)
    if resp.status_code == 200:
        return resp.json()
    else:
        app.logger.warning("authorization_code token request failed %s %s", resp.status_code, resp.text)
        return None


def ensure_token():
    """
    Ensure config contains valid access_token. If expired/missing, try refresh_token first,
    then authorization_code exchange. On success, store access_token, refresh_token, expires_at in config and save.
    """
    load_config()
    if token_is_valid():
        return

    client_id = config.get("client_id")
    client_secret = config.get("client_secret")
    if not client_id or not client_secret:
        raise RuntimeError("client_id and client_secret must be present in config")

    # Try refresh flow first
    refresh_token = config.get("refresh_token")
    if refresh_token:
        app.logger.info("Attempting refresh token flow")
        token_resp = request_token_with_refresh(refresh_token, client_id, client_secret)
        if token_resp:
            apply_token_response(token_resp)
            return

    # If refresh flow absent or failed, try authorization code flow
    authorization_code = config.get("authorization_code")
    code_verifier = config.get("code_verifier")
    if authorization_code and code_verifier:
        app.logger.info("Attempting authorization_code flow")
        token_resp = request_token_with_code(authorization_code, code_verifier, client_id, client_secret)
        if token_resp:
            apply_token_response(token_resp)
            return

    raise RuntimeError("Could not obtain access token. Provide a valid refresh_token or authorization_code+code_verifier in config.")


def apply_token_response(token_resp: Dict[str, Any]):
    """
    token_resp example:
    {"token_type":"Bearer","expires_in":2682000,"access_token":"...","refresh_token":"..."}
    """
    access_token = token_resp.get("access_token")
    refresh_token = token_resp.get("refresh_token")
    expires_in = token_resp.get("expires_in", 0)
    if not access_token:
        raise RuntimeError("token response didn't include access_token")

    config["access_token"] = access_token
    if refresh_token:
        config["refresh_token"] = refresh_token
    # compute expires_at as unix timestamp
    config["expires_at"] = now_ts() + int(expires_in)
    save_config()
    app.logger.info("Stored new access_token, refresh_token, expires_at")


def fetch_all_animelist(username: str, status: str = "watching") -> List[Dict[str, Any]]:
    """
    Fetches all animelist entries for given username and status.
    Follows paging using MAL's 'paging' object if present.
    """
    ensure_token()
    token = config.get("access_token")
    headers = {"Authorization": f"Bearer {token}"}
    url = urljoin(MAL_API_BASE, f"users/{username}/animelist")
    params = {"status": status, "limit": 100}  # limit may be up to MAL limit
    items: List[Dict[str, Any]] = []

    while url:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        params = {}  # only include params in first request; subsequent pages have full URL
        if resp.status_code == 401:
            # try refreshing token once
            app.logger.info("Received 401, attempting to refresh token once")
            # force refresh
            config.pop("access_token", None)
            save_config()
            ensure_token()
            token = config.get("access_token")
            headers = {"Authorization": f"Bearer {token}"}
            resp = requests.get(url, headers=headers, timeout=30)

        if resp.status_code != 200:
            app.logger.error("Failed to fetch animelist: %s %s", resp.status_code, resp.text)
            raise RuntimeError(f"Failed to fetch animelist: {resp.status_code} {resp.text}")

        data = resp.json()
        page_items = data.get("data", [])
        items.extend(page_items)
        paging = data.get("paging", {})
        next_url = paging.get("next")
        url = next_url

    return items


def fetch_anime_ids_map() -> Dict[int, Dict[str, Any]]:
    resp = requests.get(ANIME_IDS_RAW_URL, timeout=30)
    resp.raise_for_status()
    payload = resp.json()  # top-level keys are strings (ex: "1": {...})
    # Convert to mapping keyed by mal_id (int)
    mal_map: Dict[int, Dict[str, Any]] = {}
    for key, val in payload.items():
        # Each entry may contain a 'mal_id' field (int). Use it if present, else try the top-level key.
        mal_id = None
        if isinstance(val, dict) and "mal_id" in val:
            try:
                mal_id = int(val["mal_id"])
            except Exception:
                mal_id = None
        if mal_id is None:
            try:
                mal_id = int(key)
            except Exception:
                continue
        mal_map[mal_id] = val
    return mal_map


def build_output_list(animelist_items: List[Dict[str, Any]], anime_ids_map: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    # out = [{"id":157336,"imdb_id":"tt0816692","title":"Interstellar","release_year":"2014","clean_title":"/film/interstellar/","adult":False}]
    # out = [{"title":"Interstellar", "adult":False, "id":157336}]
    for item in animelist_items:
        node = item.get("node") or {}
        mal_id = node.get("id")
        title = node.get("title")
        if not mal_id:
            continue
        entry = {"title": title, "malId": mal_id}
        #Lookup by mal_id
        mapped = anime_ids_map.get(int(mal_id))
        if mapped:
            # tvdb_id may be present as 'tvdb_id'
            if "tvdb_id" in mapped and mapped.get("tvdb_id") not in (None, ""):
                entry["id"] = mapped["tvdb_id"]
            # imdb_id may be present as 'imdb_id' (often like "tt0119698")
            if "imdb_id" in mapped and mapped.get("imdb_id"):
                entry["imdb_id"] = mapped["imdb_id"]
        out.append(entry)
    return out


@app.route("/animelist", methods=["GET"])
def animelist_route():
    """
    GET /animelist?username=spazus&status=watching
    If username not provided, uses config['username'] if present.
    """
    status = request.args.get("status") or "watching"
    username = request.args.get("username") or config.get("username")

    if not username:
        abort(400, "username query param or config 'username' is required")

    status = request.args.get("status", "watching")
    
    try:
        animelist_items = fetch_all_animelist(username, status=status)
        anime_ids_map = fetch_anime_ids_map()
        response_list = build_output_list(animelist_items, anime_ids_map)
        return jsonify(response_list)
    except Exception as e:
        app.logger.exception("Error in /animelist")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    load_config()
    # Try to ensure token early so app logs problems on startup
    try:
        ensure_token()
    except Exception as e:
        app.logger.warning("Token not acquired on startup: %s", e)
    app.run(host="0.0.0.0", port=APP_PORT)
