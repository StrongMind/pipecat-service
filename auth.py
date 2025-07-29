import os
import secrets
import jwt
import aiohttp
from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials, HTTPBearer
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from dotenv import load_dotenv

load_dotenv(override=True)

JWT_ENABLED = os.getenv("JWT_ENABLED", "true").lower() == "true"
JWT_ISSUER_URL = os.getenv("JWT_ISSUER_URL", "https://devlogin.strongmind.com")
JWT_JWKS_URL = os.getenv("JWT_JWKS_URL", f"{JWT_ISSUER_URL}/.well-known/openid-configuration/jwks")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "")
JWT_ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]

jwks_cache = {}
jwks_cache_expiry = None

security = HTTPBasic()
bearer_security = HTTPBearer(auto_error=False)


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = os.getenv("BASIC_AUTH_USERNAME", "admin")
    correct_password = os.getenv("BASIC_AUTH_PASSWORD", "password")
    is_correct_username = secrets.compare_digest(credentials.username, correct_username)
    is_correct_password = secrets.compare_digest(credentials.password, correct_password)
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


async def fetch_jwks() -> Dict[str, Any]:
    global jwks_cache, jwks_cache_expiry
    if jwks_cache and jwks_cache_expiry and datetime.now() < jwks_cache_expiry:
        return jwks_cache
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(JWT_JWKS_URL) as response:
                if response.status != 200:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to fetch JWKS from {JWT_JWKS_URL}"
                    )
                jwks_data = await response.json()
                jwks_cache = jwks_data
                jwks_cache_expiry = datetime.now() + timedelta(hours=1)
                return jwks_data
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching JWKS: {str(e)}"
        )


def get_public_key_from_jwks(jwks: Dict[str, Any], kid: str) -> Optional[str]:
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives import serialization
            n = int.from_bytes(jwt.utils.base64url_decode(key["n"]), byteorder="big")
            e = int.from_bytes(jwt.utils.base64url_decode(key["e"]), byteorder="big")
            public_key = rsa.RSAPublicNumbers(e, n).public_key()
            pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            return pem.decode("utf-8")
    return None


async def verify_jwt_token(token: str) -> Dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            raise HTTPException(
                status_code=401,
                detail="JWT token missing key ID (kid)"
            )
        jwks = await fetch_jwks()
        public_key = get_public_key_from_jwks(jwks, kid)
        if not public_key:
            raise HTTPException(
                status_code=401,
                detail=f"Public key not found for key ID: {kid}"
            )
        payload = jwt.decode(
            token,
            public_key,
            algorithms=JWT_ALGORITHMS,
            audience=JWT_AUDIENCE if JWT_AUDIENCE else None,
            issuer=JWT_ISSUER_URL,
            options={"verify_aud": bool(JWT_AUDIENCE)}
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="JWT token has expired"
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid JWT token: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=f"JWT verification failed: {str(e)}"
        )


async def verify_auth(request: Request) -> str:
    if JWT_ENABLED:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = await verify_jwt_token(token)
            return payload.get("sub", payload.get("email", "unknown"))
        credentials = await bearer_security(request)
        if credentials:
            payload = await verify_jwt_token(credentials.credentials)
            return payload.get("sub", payload.get("email", "unknown"))
    credentials = await security(request)
    return verify_credentials(credentials)
