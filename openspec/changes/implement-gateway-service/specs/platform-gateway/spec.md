# Platform Gateway Specification

## Purpose

Defines the platform API gateway (GATEWAY): the single unified entry for all client traffic, carrying routing, the unified authentication chain, gateway-level rate limiting, timeout/circuit-breaker degradation, traceId injection, the unified Envelope, and ops endpoints. It is the sole authentication authority; business authorization checks stay inside each service.

## ADDED Requirements

### Requirement: Unified routing and dual-language forwarding
The gateway SHALL be the single entry point for all four client ends, routing `api.example.com/api/v1/{svc}/...` to the corresponding domain service. `/assist/*` and `/aicore/*` MUST be forwarded to the Python services, and all other paths to the Java domain. Server-to-server endpoints (x-external-interfaces) MUST NOT be exposed through the gateway.

#### Scenario: Business request routes to domain service
- **WHEN** a client sends a request to `/api/v1/{svc}/...`
- **THEN** the gateway matches the route and forwards it to the target service instance, and the response returns through the gateway

#### Scenario: AI paths route to Python services
- **WHEN** a client sends a request to `/assist/*` or `/aicore/*`
- **THEN** the gateway authenticates and rate-limits it, then forwards it to the Python service; clients never connect to the Python service directly

#### Scenario: Internal endpoints not reachable from outside
- **WHEN** a request targets a server-to-server endpoint (x-external-interfaces)
- **THEN** the gateway has no route for it and the request cannot reach the internal endpoint from the public entry

### Requirement: Unified authentication chain
The gateway SHALL verify the Bearer JWT (signature and expiry) and check the Redis revocation list before forwarding. Public whitelist paths (e.g. captcha, register, status) MUST pass without a token. Signature failure, expiry, or revocation MUST return 401 with code 2001. The signing key MUST be injected from KMS and MUST never leave the gateway. After verification the gateway MUST forward the authenticated identity to the service, and business-level authorization (2002) MUST be enforced inside the service, not in the gateway.

#### Scenario: Valid token passes and identity is forwarded
- **WHEN** a request carries a valid, non-revoked JWT
- **THEN** the gateway verifies it, forwards the request with the authenticated identity, and the service performs its own 2002 authorization checks

#### Scenario: Invalid or revoked token rejected
- **WHEN** a request carries a missing, malformed, expired, or revoked JWT on a protected path
- **THEN** the gateway returns 401 with code 2001 and the request never reaches the service

#### Scenario: Whitelisted public path passes without a token
- **WHEN** a request targets a whitelisted public path (captcha / register / status)
- **THEN** the gateway forwards it without JWT verification

### Requirement: Gateway-level rate limiting
The gateway SHALL enforce IP / account / API three-level token-bucket rate limiting (Redis + Lua). Over-limit requests MUST return 429 (or 503 for gateway degradation) with a friendly message. AI paths MUST be strongly limited per account (10 requests/minute initial value), and funds-path protection MUST have the highest priority.

#### Scenario: Over-limit request rejected
- **WHEN** an IP, account, or API exceeds its token-bucket limit
- **THEN** the gateway returns 429 with a friendly message and the request does not reach the service

#### Scenario: AI path strongly limited per account
- **WHEN** one account exceeds 10 AI requests in one minute
- **THEN** the gateway rejects further AI requests for that account until the window refills

### Requirement: Timeout, circuit breaking, and degradation
The gateway SHALL apply tiered timeouts (internal 1s / third-party payment 3s / AI 5s initial values) per route, and MUST open a circuit when a downstream keeps failing, failing fast with a unified 503 and friendly message without corrupting business state. After recovery the circuit MUST allow half-open probing.

#### Scenario: Downstream timeout returns 503
- **WHEN** a downstream service exceeds its route timeout
- **THEN** the gateway returns a unified 503 with a friendly message

#### Scenario: Circuit opens and recovers
- **WHEN** a downstream service keeps failing and the circuit opens
- **THEN** requests fail fast with 503; after the service recovers, half-open probing lets traffic through again

### Requirement: traceId injection and unified envelope
The gateway SHALL inject `X-Request-Id` when absent, propagate it downstream, and wrap responses in the unified Envelope with platform error codes (2001/429/503). Gateway-generated errors MUST use the same Envelope and error-code convention as services.

#### Scenario: Request id injected and propagated
- **WHEN** a request arrives without an X-Request-Id
- **THEN** the gateway generates one, injects it into the request and response, and the whole chain logs with the same trace id

#### Scenario: Gateway errors use the unified envelope
- **WHEN** the gateway itself rejects a request (401/429/503)
- **THEN** the error response uses the unified Envelope with the corresponding platform error code and traceId

### Requirement: Gray release routing
The gateway SHALL support gray traffic splitting. In early M1 gray splitting is handled by Nginx (header/cookie/IP/percentage); from late M1 the gateway MUST support route-weight splitting, with K8s canary (5%~10% start, auto rollback on metric degradation) reserved for M2.

#### Scenario: Gray traffic reaches the intended version
- **WHEN** a gray tag (header/cookie/IP/percentage) or route weight is configured
- **THEN** matching traffic is forwarded to the gray target version and the rest stays on the stable version

### Requirement: Ops endpoints
The gateway SHALL expose ops endpoints for health checks and route status queries, described in its own openapi.yaml. The gateway MUST have no business database: Redis holds only the JWT blacklist (short TTL) and rate-limit counters, and route/limit/gray configuration is externalized.

#### Scenario: Health and route status queried
- **WHEN** an operator queries the gateway health or route status endpoint
- **THEN** the gateway returns its liveness status and the current route table without business data

### Requirement: High availability and fast-fail fallback
The gateway MUST run stateless with at least two instances and automatic removal of failed instances. Because the gateway is the sole authentication authority, when no healthy gateway instance remains the entry MUST fail fast with 503 rather than bypassing the gateway to the services.

#### Scenario: Failed instance removed, traffic continues
- **WHEN** one gateway instance fails
- **THEN** the remaining instance keeps serving and the failed instance is removed from the pool

#### Scenario: No healthy gateway fails fast
- **WHEN** no gateway instance is healthy
- **THEN** the entry returns 503 quickly instead of routing clients directly to services without authentication
