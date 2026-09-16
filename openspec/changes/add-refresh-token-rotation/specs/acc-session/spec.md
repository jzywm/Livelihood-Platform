## Purpose

The lifecycle of platform session credentials: issuing short- and long-lived tokens at login, exchanging a single-use rotating long token for a fresh pair, and detecting replayed long tokens so that a leaked credential invalidates its whole session family. It turns the already-decided dual-token policy into a working, revocable loop.

## ADDED Requirements

### Requirement: Login issues both tokens

The system SHALL provide a passwordless login endpoint that authenticates a mobile number together with a captcha ticket and, on success, issues both a **short-lived access token** and a **long-lived refresh token**. The access token MUST be returned in the response body; the refresh token MUST be delivered only through `Set-Cookie` and MUST NOT appear in the response body or in any log. Login failures (unknown account, closed or frozen account, invalid or already consumed captcha ticket) MUST return `2001 unauthenticated / token invalid` and MUST NOT disclose internal details beyond that. The access token lifetime MUST NOT exceed 15 minutes.

#### Scenario: Successful login returns a token pair
- **WHEN** a client calls the login endpoint with a valid mobile number and a valid captcha ticket
- **THEN** the response body carries the access token (lifetime at most 15 minutes) with the account identity, while the refresh token is set through `Set-Cookie` and never appears in the body

#### Scenario: Invalid login factor rejected
- **WHEN** the captcha ticket is invalid, already consumed, or the mobile number has no account
- **THEN** the system returns 401 with `2001` and issues no token

#### Scenario: Closed or frozen account cannot log in
- **WHEN** the account behind the mobile number is closed (`closed_at` set) or frozen/suspended
- **THEN** login is rejected with 401 and `2001`

### Requirement: Refresh tokens are single-use and rotate

Every exchange SHALL consume the presented refresh token and issue a **new access token and a new refresh token** (rotation). A consumed refresh token MUST become invalid immediately and MUST NOT be usable for another exchange. A successful exchange MUST deliver the new refresh token through `Set-Cookie`, replacing the previous value.

#### Scenario: Exchange rotates the refresh token
- **WHEN** a client exchanges a valid, unused refresh token
- **THEN** it receives a new access token and a new refresh token via `Set-Cookie`, and the previous refresh token can no longer be used

#### Scenario: Expired or unknown refresh token rejected
- **WHEN** the presented refresh token is expired, has an invalid signature, or is unknown to the system
- **THEN** the system returns 401 with `2001` and issues no token

### Requirement: Session family and replay detection

The system SHALL establish a **session family** at login so that every token of one login can be revoked together. When a refresh token that has already been rotated is presented, the system MUST treat it as a replay/leak signal, MUST revoke every access token and refresh token of that session family (including unexpired access tokens), and MUST record a security audit event. Any token of a revoked family MUST be rejected with 401 and `2001`.

#### Scenario: Replaying a rotated refresh token revokes the family
- **WHEN** an attacker replays a refresh token that was already rotated
- **THEN** the system returns 401 with `2001`, revokes every token of that session family, and records a security audit event

#### Scenario: Unrevoked access token of a revoked family stops working
- **WHEN** an unexpired access token belonging to a revoked family is used against a business endpoint
- **THEN** the gateway rejects it through the revocation list (401 with `2001`)

### Requirement: Logout revokes the current session

The system SHALL provide a logout endpoint that revokes the current session family: the access token MUST enter the revocation list readable by the gateway (with a TTL covering its remaining lifetime) and the refresh token MUST be invalidated immediately. Logout MUST be idempotent (repeating it still succeeds) and MUST clear the client cookie through `Set-Cookie`.

#### Scenario: Access token stops working right after logout
- **WHEN** the client uses the pre-logout access token against a protected endpoint immediately after logging out
- **THEN** the gateway returns 401 with `2001`

#### Scenario: Repeated logout is idempotent
- **WHEN** the client calls logout again for the same session
- **THEN** the system still reports success and no error occurs

### Requirement: Refresh token transport and CSRF protection

The refresh token MUST live in a `HttpOnly`, `Secure`, `SameSite` cookie whose `Path` is restricted to the session endpoints, so page scripts MUST NOT be able to read it. The exchange endpoint MUST validate the request origin (`Origin`/`Referer`) to defend against CSRF, and an exchange MUST NOT have side effects other than rotation and issuance. The access token MUST NOT be transported in a cookie, so business endpoints stay out of CSRF scope.

#### Scenario: Cross-site origin is rejected
- **WHEN** the exchange request carries an `Origin`/`Referer` outside the platform's allowed origins
- **THEN** the request is rejected and no token is rotated

#### Scenario: Session cookie cannot be read by scripts
- **WHEN** the `Set-Cookie` attributes of a login or exchange response are inspected
- **THEN** the refresh cookie carries `HttpOnly`, `Secure` and `SameSite`, with `Path` limited to the session endpoints

### Requirement: Session storage and revocation contract

The system SHALL keep session family and refresh token state in **Redis** (the same instance the gateway reads the revocation list from) with these keys and semantics: the refresh record TTL MUST NOT exceed its validity (7 days); revoking an access token MUST use the contract key `revoked:jti:{jti}` with a placeholder value and a TTL covering that token's remaining lifetime (the revocation contract shared with the gateway). When Redis is unavailable, login, exchange and logout MUST fail fast rather than silently degrading into sessions that cannot be revoked.

#### Scenario: Revocation keys follow the gateway contract
- **WHEN** logout or a family-wide revocation happens
- **THEN** the system writes `revoked:jti:{jti}` for every unexpired access token of the family, with a TTL equal to its remaining lifetime

#### Scenario: Session store unavailable fails fast
- **WHEN** the session store (Redis) is unavailable
- **THEN** login, exchange and logout fail fast with a 5xx and no token is issued that could not be revoked

### Requirement: Access token claims match the gateway policy

The access token MUST be HS256-signed and MUST carry at least `sub` (account id), `role`, `mfa`, `jti`, `iat` and `exp`; the difference between `exp` and `iat` MUST NOT exceed 15 minutes, satisfying the gateway token policy (non-blank `sub`, `exp` within the configured maximum plus skew).

#### Scenario: Issued access token satisfies the gateway policy
- **WHEN** the access token obtained from login or exchange is used against any protected business endpoint
- **THEN** the gateway verifies it and forwards the identity, without rejecting it for a policy violation (missing `sub`, lifetime beyond the maximum)
