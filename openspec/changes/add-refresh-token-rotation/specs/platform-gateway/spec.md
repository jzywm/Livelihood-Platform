## Purpose

The access-layer behavior contract of the platform's single entry point (gateway service GATEWAY): routing and path rewriting for all traffic, unified authentication with the gateway as the only authentication authority, the access-token policy, gateway-level rate limiting, timeout/circuit-breaking/degradation, traceId and the unified envelope, ops endpoint access control, and the reachability and protection boundaries of the session endpoints at the entry.

## ADDED Requirements

### Requirement: Session endpoints reachability at the entry

The gateway SHALL let the **login** and **exchange** endpoints through the entry **without a valid access token** (they are the only way to obtain credentials when no access token is available), but MUST NOT relax any other path because of them. The **logout** endpoint MUST stay protected (a valid access token is required) and MUST NOT be whitelisted. Session endpoint matching MUST respect **path segment boundaries**, so a look-alike path such as `/api/v1/acc/auth/loginAny` MUST NOT be allowed through.

#### Scenario: Login and exchange reachable without an access token
- **WHEN** a request without an access token targets the login or the exchange endpoint
- **THEN** the gateway forwards it to the downstream service

#### Scenario: Logout stays protected
- **WHEN** a request without a valid access token targets the logout endpoint
- **THEN** the gateway returns 401 with `2001` and the request never reaches the downstream service

#### Scenario: Look-alike paths do not ride the whitelist
- **WHEN** a request without an access token targets a path such as `/api/v1/acc/auth/loginAny` or `/api/v1/acc/auth/login/../me`
- **THEN** the gateway does not treat it as whitelisted and rejects it under the authentication or path-normalization rules

### Requirement: Session cookies pass through the gateway unchanged

The gateway SHALL pass the `Cookie` request header and the `Set-Cookie` response header related to the session endpoints through unchanged, and MUST NOT parse, rewrite or strip the refresh cookie. The gateway MUST NOT base any authentication decision on cookies (authentication uses only the access token in `Authorization: Bearer`). The gateway MUST NOT log raw cookie values.

#### Scenario: Exchange response carries Set-Cookie back
- **WHEN** the downstream service sets `Set-Cookie` on an exchange response
- **THEN** the client receives that `Set-Cookie` with its attributes unchanged by the gateway

#### Scenario: A cookie alone does not authenticate
- **WHEN** a request carries a valid refresh cookie but no `Authorization: Bearer` header
- **THEN** the gateway treats it as unauthenticated (401 with `2001` on protected paths)

### Requirement: Session endpoints remain subject to gateway rate limiting

The login and exchange endpoints SHALL be subject to gateway-level IP rate limiting and MUST NOT be added to any rate-limit exemption list. A rejected request MUST return 429 with `2004` and MUST NOT reach the downstream service.

#### Scenario: Repeated login attempts hit the limit
- **WHEN** a single source IP exceeds its rate-limit window on the login or exchange endpoint
- **THEN** the gateway returns 429 with `2004` and the downstream service never receives the request
