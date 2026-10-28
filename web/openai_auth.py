#!/usr/bin/python3
"""Sign in with ChatGPT support shared by the web UI and ChatGPT BBS."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

AUTH_ROOT = Path("/var/lib/retromodem/chatgpt")
HOST_FILE = AUTH_ROOT / "host.json"
PENDING_FILE = AUTH_ROOT / "pending.json"
CREDENTIALS_FILE = AUTH_ROOT / "credentials.json"
AUTHORIZE_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
DISCOVERY_URL = "https://auth.openai.com/.well-known/openid-configuration"
RESOURCE = "https://api.openai.com/v1"
REDIRECT_URI = "http://127.0.0.1:1455/auth/callback"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"


class AuthError(RuntimeError):
    pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode_b64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _atomic_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _request_json(url: str, *, data: dict[str, str] | None = None,
                  token: str | None = None, timeout: int = 30) -> dict:
    body = None if data is None else urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(url, data=body)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read(4096).decode("utf-8", "replace")
        raise AuthError(f"OpenAI gaf HTTP {error.code}: {detail}") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise AuthError(f"OpenAI is niet bereikbaar: {error}") from error
    return result if isinstance(result, dict) else {}


def _host_id() -> str:
    current = _read_json(HOST_FILE).get("ext_agent_host_id")
    if isinstance(current, str) and current.startswith("urn:uuid:"):
        return current
    value = f"urn:uuid:{uuid.uuid4()}"
    _atomic_json(HOST_FILE, {"ext_agent_host_id": value})
    return value


def start_authorization() -> str:
    credentials = _read_json(CREDENTIALS_FILE)
    verifier = _b64url(secrets.token_bytes(48))
    state = _b64url(secrets.token_bytes(24))
    nonce = _b64url(secrets.token_bytes(24))
    existing_client = credentials.get("client_id")
    client_id = existing_client if isinstance(existing_client, str) else "dynamic_agent_client"
    pending = {
        "state": state, "nonce": nonce, "code_verifier": verifier,
        "redirect_uri": REDIRECT_URI, "client_id": client_id,
        "created_at": int(time.time()),
    }
    _atomic_json(PENDING_FILE, pending)
    parameters = {
        "client_id": client_id,
        "ext_agent_host_id": _host_id(),
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": _b64url(hashlib.sha256(verifier.encode("ascii")).digest()),
    }
    if client_id == "dynamic_agent_client":
        parameters["agent_name_hint"] = "RetroModem ChatGPT BBS"
    elif isinstance(credentials.get("id_token"), str):
        parameters["id_token_hint"] = credentials["id_token"]
        if isinstance(credentials.get("email"), str):
            parameters["login_hint"] = credentials["email"]
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(parameters)


def _validate_id_token(token: str, client_id: str, nonce: str) -> dict:
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        header_part, payload_part, signature_part = token.split(".")
        header = json.loads(_decode_b64url(header_part))
        claims = json.loads(_decode_b64url(payload_part))
        discovery = _request_json(DISCOVERY_URL)
        jwks = _request_json(str(discovery["jwks_uri"]))
        key = next(item for item in jwks.get("keys", []) if item.get("kid") == header.get("kid"))
        public_key = rsa.RSAPublicNumbers(
            int.from_bytes(_decode_b64url(key["e"]), "big"),
            int.from_bytes(_decode_b64url(key["n"]), "big"),
        ).public_key()
        public_key.verify(
            _decode_b64url(signature_part),
            f"{header_part}.{payload_part}".encode("ascii"),
            padding.PKCS1v15(), hashes.SHA256(),
        )
    except Exception as error:
        raise AuthError(f"Het OpenAI-identiteitsbewijs kon niet worden geverifieerd: {error}") from error
    audience = claims.get("aud", [])
    if isinstance(audience, str):
        audience = [audience]
    if claims.get("iss") != discovery.get("issuer") or client_id not in audience:
        raise AuthError("Onjuiste uitgever of client in het identiteitsbewijs")
    if int(claims.get("exp", 0)) <= int(time.time()) or claims.get("nonce") != nonce:
        raise AuthError("Het identiteitsbewijs is verlopen of hoort bij een andere aanmelding")
    return claims


def complete_authorization(callback_url: str) -> dict:
    pending = _read_json(PENDING_FILE)
    if not pending or int(pending.get("created_at", 0)) < int(time.time()) - 900:
        raise AuthError("De aanmelding is verlopen; begin opnieuw")
    pasted = callback_url.strip()
    if "://" not in pasted:
        pasted = REDIRECT_URI + "?" + pasted.lstrip("?")
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(pasted).query)
    value = lambda key: query.get(key, [""])[-1]
    if not secrets.compare_digest(value("state"), str(pending.get("state", ""))):
        raise AuthError("De terugkoppeling hoort niet bij deze aanmelding")
    if value("error"):
        raise AuthError("Aanmelding geweigerd: " + value("error"))
    issued_client = value("client_id") or str(pending.get("client_id", ""))
    if pending.get("client_id") != "dynamic_agent_client" and issued_client != pending.get("client_id"):
        raise AuthError("OpenAI gaf een onverwachte client terug")
    if not issued_client.startswith("oaiapp_") or not value("code"):
        raise AuthError("De geplakte URL bevat geen volledige OpenAI-code")
    tokens = _request_json(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "client_id": issued_client,
        "code": value("code"),
        "code_verifier": str(pending["code_verifier"]),
        "redirect_uri": str(pending["redirect_uri"]),
        "resource": RESOURCE,
    })
    id_token = str(tokens.get("id_token", ""))
    claims = _validate_id_token(id_token, issued_client, str(pending["nonce"]))
    scopes = str(tokens.get("scope", value("scope"))).split()
    if "chatgpt.tokens.use.direct" not in scopes:
        raise AuthError("ChatGPT-abonnementsgebruik is niet toegestaan voor deze verbinding")
    credentials = {
        "email": str(claims.get("email", "")),
        "issuer": str(claims.get("iss", "")),
        "subject": str(claims.get("sub", "")),
        "client_id": issued_client,
        "ext_agent_host_id": _host_id(),
        "id_token": id_token,
        "access_token": str(tokens.get("access_token", "")),
        "refresh_token": str(tokens.get("refresh_token", "")),
        "token_type": str(tokens.get("token_type", "Bearer")),
        "expires_in": int(tokens.get("expires_in", 3600)),
        "scopes": scopes,
        "saved_at": int(time.time()),
    }
    if not credentials["access_token"] or not credentials["refresh_token"]:
        raise AuthError("OpenAI gaf geen volledige hernieuwbare sessie terug")
    _atomic_json(CREDENTIALS_FILE, credentials)
    PENDING_FILE.unlink(missing_ok=True)
    return credentials


def connection_status() -> dict[str, object]:
    credentials = _read_json(CREDENTIALS_FILE)
    return {
        "connected": bool(credentials.get("access_token") and credentials.get("client_id")),
        "email": str(credentials.get("email", "")),
        "scopes": list(credentials.get("scopes", [])) if isinstance(credentials.get("scopes"), list) else [],
    }


def disconnect() -> None:
    credentials = _read_json(CREDENTIALS_FILE)
    refresh_token = credentials.get("refresh_token")
    if isinstance(refresh_token, str) and refresh_token:
        try:
            discovery = _request_json(DISCOVERY_URL)
            data = urllib.parse.urlencode({
                    "token": refresh_token,
                    "token_type_hint": "refresh_token",
                    "client_id": str(credentials.get("client_id", "")),
                }).encode("utf-8")
            request = urllib.request.Request(str(discovery["revocation_endpoint"]), data=data)
            request.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urllib.request.urlopen(request, timeout=20):
                pass
        except (AuthError, KeyError, urllib.error.URLError, TimeoutError):
            pass
    CREDENTIALS_FILE.unlink(missing_ok=True)
    PENDING_FILE.unlink(missing_ok=True)


def access_token() -> str:
    credentials = _read_json(CREDENTIALS_FILE)
    if not credentials:
        raise AuthError("ChatGPT is nog niet verbonden via de webinterface")
    expires_at = int(credentials.get("saved_at", 0)) + int(credentials.get("expires_in", 0))
    if expires_at > int(time.time()) + 120:
        return str(credentials["access_token"])
    tokens = _request_json(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": str(credentials.get("client_id", "")),
        "refresh_token": str(credentials.get("refresh_token", "")),
        "resource": RESOURCE,
    })
    credentials.update({
        "access_token": str(tokens.get("access_token", "")),
        "refresh_token": str(tokens.get("refresh_token", credentials.get("refresh_token", ""))),
        "id_token": str(tokens.get("id_token", credentials.get("id_token", ""))),
        "expires_in": int(tokens.get("expires_in", 3600)),
        "scopes": str(tokens.get("scope", " ".join(credentials.get("scopes", [])))).split(),
        "saved_at": int(time.time()),
    })
    _atomic_json(CREDENTIALS_FILE, credentials)
    return str(credentials["access_token"])


def available_models() -> list[dict[str, str]]:
    document = _request_json("https://api.openai.com/v1/models", token=access_token())
    models = document.get("models", [])
    return [
        {"slug": str(item["slug"]), "display_name": str(item.get("display_name", item["slug"]))}
        for item in models if isinstance(item, dict) and item.get("visibility") == "list" and item.get("slug")
    ]
