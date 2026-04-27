"""OAuth 2.0 PKCE flow for social platforms.

PKCE means we never need a client secret. The user registers a public
client (a free Reddit / Twitter app), points its redirect URI at
``http://localhost:8765/callback``, sets the resulting client ID in an
env var, and the CLI does the rest: opens a browser, captures the
redirect, exchanges the code for an access token, and returns it.

Each platform's wire details are in ``PLATFORMS`` so it stays easy to
read for anyone reviewing what gets sent where.
"""

import base64
import hashlib
import http.server
import logging
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser

import requests

from privacyworm.brokers.base import log_network_request

logger = logging.getLogger("privacyworm")


PLATFORMS = {
    "reddit": {
        "auth_url": "https://www.reddit.com/api/v1/authorize",
        "token_url": "https://www.reddit.com/api/v1/access_token",
        "scopes": ["identity", "edit", "history", "read"],
        "client_id_env": "PRIVACYWORM_REDDIT_CLIENT_ID",
        "user_agent": "privacyworm/1.0 (open-source privacy agent)",
        "extra_auth_params": {"duration": "permanent"},
    },
    "twitter": {
        "auth_url": "https://twitter.com/i/oauth2/authorize",
        "token_url": "https://api.twitter.com/2/oauth2/token",
        "scopes": ["tweet.read", "tweet.write", "users.read", "offline.access"],
        "client_id_env": "PRIVACYWORM_TWITTER_CLIENT_ID",
        "user_agent": "privacyworm/1.0",
        "extra_auth_params": {},
    },
}

CALLBACK_PORT = 8765
CALLBACK_TIMEOUT_S = 300


def _gen_code_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    captured: dict = {}

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        parsed = urllib.parse.urlparse(self.path)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        _CallbackHandler.captured.update(params)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h2>You can close this window now.</h2></body></html>"
        )

    def log_message(self, format, *args):  # noqa: A002 (silence access logs)
        pass


def run_pkce_flow(platform: str, port: int = CALLBACK_PORT) -> dict:
    """Run an OAuth 2.0 PKCE login flow for ``platform``.

    Returns the token JSON from the platform plus a couple of extra fields
    we need to refresh later (``client_id``, ``redirect_uri``).
    """
    if platform not in PLATFORMS:
        raise ValueError(f"Unknown platform: {platform}")

    cfg = PLATFORMS[platform]
    client_id = os.environ.get(cfg["client_id_env"], "").strip()
    if not client_id:
        raise RuntimeError(
            f"Set the env var {cfg['client_id_env']} to your registered "
            f"{platform} OAuth app's client ID. The app must be a public "
            f"client (no secret) with redirect URI "
            f"http://localhost:{port}/callback."
        )

    redirect_uri = f"http://localhost:{port}/callback"
    state = secrets.token_urlsafe(16)
    verifier = _gen_code_verifier()
    challenge = _code_challenge(verifier)

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(cfg["scopes"]),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    params.update(cfg.get("extra_auth_params") or {})
    auth_url = cfg["auth_url"] + "?" + urllib.parse.urlencode(params)

    _CallbackHandler.captured = {}
    server = http.server.HTTPServer(("localhost", port), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    log_network_request("GET", auth_url, f"oauth authorize ({platform})")
    logger.info(f"Opening {platform} login in your browser. If it does not open, "
                f"copy this URL into a browser tab: {auth_url}")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    start = time.time()
    while not _CallbackHandler.captured and time.time() - start < CALLBACK_TIMEOUT_S:
        time.sleep(0.5)
    server.shutdown()

    captured = _CallbackHandler.captured
    if "error" in captured:
        raise RuntimeError(
            f"OAuth error: {captured.get('error')} "
            f"{captured.get('error_description', '')}"
        )
    if not captured:
        raise RuntimeError("OAuth flow timed out without a redirect.")
    if captured.get("state") != state:
        raise RuntimeError("OAuth state mismatch (possible CSRF). Aborting.")
    code = captured.get("code")
    if not code:
        raise RuntimeError("OAuth redirect arrived without a code.")

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    headers = {"Accept": "application/json", "User-Agent": cfg["user_agent"]}
    if platform == "reddit":
        basic = base64.b64encode(f"{client_id}:".encode()).decode()
        headers["Authorization"] = f"Basic {basic}"

    log_network_request("POST", cfg["token_url"], f"oauth token exchange ({platform})")
    resp = requests.post(cfg["token_url"], data=data, headers=headers, timeout=30)
    resp.raise_for_status()
    token = resp.json()
    token["client_id"] = client_id
    token["redirect_uri"] = redirect_uri
    return token
