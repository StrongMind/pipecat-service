# JWT Authentication

This server now supports JWT (JSON Web Token) authentication using public keys from configurable identity servers. This allows for secure authentication using tokens issued by your identity provider.

## Configuration

JWT authentication is configured through environment variables:

### Required Environment Variables

- `JWT_ENABLED`: Set to `"true"` to enable JWT authentication (default: `"false"`)
- `JWT_ISSUER_URL`: The base URL of your identity server (default: `"https://login.strongmind.com"`)
- `JWT_JWKS_URL`: The JWKS (JSON Web Key Set) endpoint URL (default: `"{JWT_ISSUER_URL}/.well-known/openid-configuration/jwks"`)

### Optional Environment Variables

- `JWT_AUDIENCE`: The audience claim to verify in JWT tokens (optional)

## Example Configuration

```bash
# Enable JWT authentication
JWT_ENABLED=true

# Configure identity server
JWT_ISSUER_URL=https://login.strongmind.com
JWT_JWKS_URL=https://login.strongmind.com/.well-known/openid-configuration/jwks

# Optional: Set audience for additional verification
JWT_AUDIENCE=your-app-audience
```

## Authentication Flow

1. **JWT Enabled**: When `JWT_ENABLED=true`, the server will:
   - First attempt to authenticate using JWT Bearer tokens
   - Fall back to Basic Authentication if JWT is not provided or fails

2. **JWT Disabled**: When `JWT_ENABLED=false` (default), the server uses Basic Authentication only

## Usage

### With JWT Token

```bash
# Include JWT token in Authorization header
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
     http://localhost:8080/connect
```

### With Basic Authentication (fallback)

```bash
# Use Basic Authentication
curl -u "username:password" \
     http://localhost:8080/connect
```

## Supported Endpoints

All protected endpoints now support both JWT and Basic Authentication:

- `GET /` - Direct browser access
- `GET /{bot_type}` - Direct browser access with specific bot type
- `POST /connect` - RTVI connection endpoint
- `POST /connect/{bot_type}` - RTVI connection endpoint with specific bot type

## JWT Token Requirements

JWT tokens must:

1. Be signed with a supported algorithm (RS256, RS384, RS512, ES256, ES384, ES512)
2. Include a `kid` (Key ID) in the header that matches a key in the JWKS
3. Be issued by the configured issuer (`JWT_ISSUER_URL`)
4. Include an audience claim matching `JWT_AUDIENCE` (if configured)
5. Not be expired

## JWKS Caching

The server caches JWKS data for 1 hour to improve performance and reduce requests to the identity server.

## Security Considerations

- JWT tokens are verified using public keys from your identity server
- The server supports multiple signing algorithms for flexibility
- JWKS data is cached but refreshed automatically
- Failed JWT authentication falls back to Basic Authentication for backward compatibility

## Testing

Run the JWT authentication test suite:

```bash
python3 test_jwt_auth.py
```

This will test the JWKS fetching and public key extraction functionality. 