# ACC Transactional Data Access Specification

## Purpose

Defines how the ACC service accesses its database: one transaction per request, atomic multi-table writes, cross-connection visibility of committed data, per-request connection isolation under concurrency, and release of idempotency claims when a request fails. It covers the persistence behavior that the account, real-name, wallet, binding, reconcile and idempotency flows rely on.

## ADDED Requirements

### Requirement: Request-scoped transaction boundary

Each ACC request that performs data access SHALL run inside exactly one database transaction for the whole request. The transaction MUST be committed when the request completes successfully and MUST be rolled back when the request fails with an unhandled exception, so that a failed request leaves no partial changes visible to other connections. The database connection MUST be released when the request ends, on the success path and on the failure path alike. Requests that perform no data access MUST NOT acquire a database connection, so endpoints served without persistence keep working even when the configured datasource cannot hand out connections.

#### Scenario: Successful write request is committed and externally visible
- **WHEN** a request performs one or more writes and returns a successful response
- **THEN** the changes are committed, and a separate connection opened afterwards observes the new state immediately

#### Scenario: Failed request leaves no partial writes
- **WHEN** a request performs a write and then fails with an unhandled exception before returning
- **THEN** every write of that request is rolled back, and no partial row is visible to other connections

#### Scenario: Connections are released after repeated failures
- **WHEN** a client repeats a failing request many times in a row
- **THEN** each failure releases its connection, so subsequent requests are still served successfully instead of failing on connection exhaustion

#### Scenario: Non-persistent requests do not need a database connection
- **WHEN** a request is handled without touching the database (for example an endpoint whose collaborators do not query it)
- **THEN** it completes successfully even if the configured datasource cannot provide connections

### Requirement: Cross-table atomicity within a request

All writes performed while handling one request SHALL form a single atomic unit, regardless of how many tables or mappers they touch. If any part fails, none of the writes of that request may take effect.

#### Scenario: Account creation and business-record update roll back together
- **WHEN** a real-name callback creates an account and then fails while updating the corresponding real-name business record
- **THEN** neither the new account row nor the business-record change is persisted, so no account exists without its matching record

#### Scenario: Duplicate-key conflict does not leave a half-written aggregate
- **WHEN** a write inside a request violates a unique constraint after an earlier write of the same request already succeeded
- **THEN** the earlier write is rolled back together with the failing one, so no partially written aggregate remains visible to other connections

### Requirement: Idempotency claims follow transaction outcome

A request that claims an idempotency key SHALL keep that claim only if the request succeeds. When a request that claimed a key fails, the claim MUST be released, so a client retrying with the same key executes the operation again instead of receiving a pending or empty prior result. A successful first execution MUST remain replayable: repeating the same key after success returns the stored result of the first execution without re-executing it.

#### Scenario: Failed first attempt releases the key
- **WHEN** a request claims an idempotency key, fails downstream, and the client retries with the same key
- **THEN** the retry performs the operation (it is not treated as a duplicate) and its outcome is returned to the client

#### Scenario: Successful first execution stays replayable
- **WHEN** a request claims an idempotency key, succeeds, and the same key is submitted again
- **THEN** the second submission returns the stored result of the first execution and does not execute the operation a second time

### Requirement: Read behavior across transaction boundaries

Reads SHALL observe data that other connections committed before the request started; a request MUST NOT serve a snapshot frozen at an earlier request. A read request that ends with a documented business error MUST still return that documented error to the client rather than failing because of transaction handling.

#### Scenario: Committed external change is visible to the next request
- **WHEN** another connection commits a change to a row and a new ACC request then reads that row
- **THEN** the response reflects the committed change (no stale value from a previous request)

#### Scenario: Read request failing with a business error keeps its contract
- **WHEN** a read request targets a record that does not exist
- **THEN** the client receives the documented "object not found" business error with its usual HTTP status and envelope, exactly as before this change

### Requirement: Per-request connection isolation under concurrency

Concurrent requests SHALL NOT share a database session or connection. A database session MUST be usable by a single request thread only, so simultaneous requests cannot interleave statements on one connection or observe each other's uncommitted work.

#### Scenario: Concurrent read and write requests all succeed
- **WHEN** many requests are issued in parallel against the same service instance, mixing reads and writes
- **THEN** every request completes with its own correct result, with no serialization, interleaving or cross-talk errors

#### Scenario: Uncommitted work of one request is invisible to another
- **WHEN** a request is still in flight with uncommitted changes and another request reads the same rows
- **THEN** the second request sees the previously committed state only

### Requirement: Preservation of existing external contracts

The change SHALL NOT alter externally observable contracts: request paths, response envelope shape, documented error codes (including authentication, validation, duplicate and not-found errors), and the documented idempotent outcome for repeated keys MUST stay as they are. Existing behavior verified by the service's test suite MUST remain green.

#### Scenario: Existing suite stays green
- **WHEN** the service test suite is executed after the change
- **THEN** all previously passing cases still pass, including the controller contract, error-matrix, authentication-matrix and DAO cases

#### Scenario: Documented error codes are unchanged
- **WHEN** a request triggers a documented failure (unauthorized, validation, duplicate key, not found, rate limited)
- **THEN** the response carries the same HTTP status and error code as before the change
