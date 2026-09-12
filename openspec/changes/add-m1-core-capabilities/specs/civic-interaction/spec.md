# Civic Interaction Specification

## Purpose

Defines the M1 civic-interaction capability: the citizen hotline / request work-order baseline (PRD v2.3 G-01). Because the 12345 hotline is confirmed non-connectable, the platform builds a self-owned work-order channel with offline circulation to departments, deadline-based resolution, and public desensitized result disclosure.

## ADDED Requirements

### Requirement: Citizen request submission generates a work order
A citizen SHALL submit a request (select department/category, attach optional evidence) and the system MUST generate a work order and return the ticket id with acceptance status. Submission requires completed real-name verification.

#### Scenario: Request submitted and accepted
- **WHEN** a real-name verified citizen submits a request with department, category, and content
- **THEN** the system creates a work order and returns the ticket id and acceptance status

#### Scenario: Invalid submission rejected with reasons
- **WHEN** required fields are missing
- **THEN** the system rejects with a parameter error message

### Requirement: Intelligent dispatch with offline circulation
Because the 12345 system is non-connectable, the platform SHALL dispatch the work order to the corresponding department via the self-built channel with offline circulation (dual-track per P-04). The dispatch result MUST be recorded on the work order.

#### Scenario: Work order dispatched to department
- **WHEN** a request work order is created
- **THEN** the system assigns it to the corresponding department through the self-built channel, and the offline circulation handoff is recorded

### Requirement: Deadline-based resolution and progress visibility
The department MUST resolve the work order within the configured deadline (7 working days is the confirmed default; configurable). Statuses (accepted / handling / resolved / evaluated) MUST be visible to the citizen throughout. Outstanding high-frequency requests or excellent suggestions MAY be converted to the suggestion forum (G-02, M2) — outside this change.

#### Scenario: Resolution within deadline
- **WHEN** the assigned department resolves the request within the deadline
- **THEN** the work order status becomes resolved and the citizen sees the progress

#### Scenario: Overdue resolution is escalated
- **WHEN** the department fails to resolve within the deadline
- **THEN** the system escalates the work order and the overdue state is recorded for assessment

### Requirement: Public desensitized result disclosure
The resolved result SHALL be publicly disclosed in desensitized form for citizen oversight.

#### Scenario: Resolved result disclosed
- **WHEN** a request work order reaches a resolved status
- **THEN** the system publishes the desensitized result for public viewing
