# Complaint Redress Specification

## Purpose

Defines the M1 complaint-redress capability: direct complaint submission in at most 3 steps with full progress visibility and public desensitized result disclosure (PRD v2.3 D-02), including the "minor entering in violation" reporting category and the 48-hour merchant handling deadline.

## ADDED Requirements

### Requirement: Direct complaint submission in at most 3 steps
A consumer SHALL be able to submit a complaint in at most 3 steps: select merchant → select category → attach evidence. Categories MUST include "minor entering in violation" for entertainment venues and internet cafes. The complaint MUST generate a work order and return the ticket id and status immediately upon submission.

#### Scenario: Complaint submitted in 3 steps
- **WHEN** a consumer selects a merchant, picks a category, and attaches evidence in three steps
- **THEN** the system creates a complaint work order with a ticket id and returns the initial status

#### Scenario: Minor-entry violation category available
- **WHEN** a consumer selects the complaint category list
- **THEN** the "minor entering in violation" category is available, and submitted reports under it flow to the violation-entry venue alert aggregation

### Requirement: Progress visibility through full lifecycle
The complaint lifecycle statuses (submitted / in handling / resolved / escalated / closed) MUST be visible to the complainant throughout. After triage, the merchant MUST handle the complaint within 48 hours (configurable by category; 48h is the confirmed default). If unresolved within the deadline, the complaint MUST be escalated automatically to the market regulator.

#### Scenario: Merchant handles within deadline
- **WHEN** a merchant receives a complaint and responds within the 48-hour deadline
- **THEN** the system records the response and the progress updates for the complainant

#### Scenario: Unresolved complaint auto-escalates
- **WHEN** the merchant does not resolve the complaint within the deadline
- **THEN** the complaint escalates automatically to the market regulator and the status becomes "escalated"

### Requirement: Public desensitized result disclosure and credit linkage
A closed complaint result SHALL be publicly disclosed in desensitized form. The outcome MUST be counted into the merchant's credit score. Complaint evidence MUST be preserved in the platform evidence chain for certification (P-02).

#### Scenario: Result disclosed desensitized
- **WHEN** a complaint reaches a closed status
- **THEN** the system publishes the desensitized result for public viewing

#### Scenario: Outcome feeds credit score
- **WHEN** a complaint outcome is confirmed
- **THEN** the merchant's credit score is updated accordingly with an audit trail

#### Scenario: Evidence preserved for certification
- **WHEN** complaint evidence is submitted
- **THEN** the evidence is stored with timestamp + hash in the append-only evidence chain and can be packaged for certification
