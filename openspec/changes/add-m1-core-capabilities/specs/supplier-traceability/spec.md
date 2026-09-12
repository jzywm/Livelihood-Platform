# Supplier and Traceability Specification

## Purpose

Defines the M1 supplier and traceability foundation: supplier onboarding with per-category qualification verification, the supplier credit archive baseline, traceability batch-code generation with event reporting, and scan verification with full-chain transparent display and explicit broken-link annotation (PRD v2.3 T-01, T-05 baseline, T-08, T-09).

## ADDED Requirements

### Requirement: Supplier onboarding with category qualification verification
A supplier SHALL complete real-name verification (no manual fallback) and pass per-category qualification verification before onboarding: agri-input = business license + operation/production permit + registration batch number; food ingredients = business license + operation permit + inspection report (mandatory). The platform MUST only verify information and keep records — it MUST NOT substitute administrative licensing (R-09). Qualification failure MUST return a rejection with reasons.

#### Scenario: Category threshold verified for agri-input
- **WHEN** an agri-input supplier submits licenses, operation/production permit, and registration batch number
- **THEN** the system verifies them against the category threshold and creates the supplier record on success

#### Scenario: Food ingredient inspection report mandatory
- **WHEN** a food ingredient supplier lacks a valid inspection report
- **THEN** the system rejects onboarding with reasons; the inspection report is mandatory for this category

#### Scenario: No administrative licensing substitution
- **WHEN** the platform verifies strongly regulated categories (e.g., agri-input)
- **THEN** the platform only performs information verification and traceability checks; it never issues or substitutes administrative licensing, and pages display this boundary prominently

### Requirement: Supplier credit archive baseline
The supplier credit score SHALL be computed with confirmed weights (2026-09-11): qualification compliance 30 + transaction fulfillment 30 + quality reputation 30 + positive contribution 10. The archive MUST be created upon onboarding. The supplier credit MUST integrate with the global credit system (A-07) — the same subject holds one archive across the platform.

#### Scenario: Score computed with confirmed weights
- **WHEN** a supplier credit score is computed
- **THEN** the score uses the confirmed four-dimension weights and the dimension breakdown is queryable

#### Scenario: Same subject shares one archive
- **WHEN** a supplier also exists as a merchant subject
- **THEN** their credit archives integrate under the global credit system with a single source of truth

### Requirement: Traceability batch code and event reporting
Creating a batch SHALL generate a unique traceability code (one code per item or per batch). Suppliers MUST report events per batch across production/inspection, circulation/temperature, and terminal registration. M1 covers agri-input and food ingredients first.

#### Scenario: Batch created with unique code
- **WHEN** a supplier creates a batch with batch number and category
- **THEN** the system generates the unique traceability code and returns the batch id and code

#### Scenario: Events reported per batch
- **WHEN** the supplier reports an event (production/inspection, circulation/temperature, terminal) for a batch
- **THEN** the system records the event on the batch's chain with timestamp + hash (P-02)

### Requirement: Scan verification with full-chain display
Scanning a traceability code SHALL display the full chain on a timeline: batch number → inspection → temperature control → terminal. Any missing link MUST be explicitly annotated as "missing / broken link". Scan counts MUST be recorded as anti-counterfeit corroboration.

#### Scenario: Full chain displayed on timeline
- **WHEN** a user scans a valid traceability code
- **THEN** the system displays the full chain on a timeline with the events recorded for that batch

#### Scenario: Missing link explicitly annotated
- **WHEN** a chain link is missing
- **THEN** the system explicitly annotates that link as "missing / broken link" instead of silently skipping it

#### Scenario: Invalid code rejected
- **WHEN** a user scans an invalid or unknown traceability code
- **THEN** the system returns a not-found prompt

#### Scenario: Scan count recorded
- **WHEN** a code is scanned
- **THEN** the system increments the scan record for that code as anti-counterfeit corroboration
