# Employment Protection Specification

## Purpose

Defines the M1 employment-protection capability of the platform: child-labor prevention via age verification at employment registration (PRD v2.3 C-01) and attendance clock-in with work-hour accumulation serving as the attendance basis for wage-guaranteed disbursement (C-02, per PDD §5.14.4 / EMP er.md M1 design). Per the PRD deduplication convention, wage protection is specified under account-funds (I-03) and employment history under credibility-regulation (A-06).

## ADDED Requirements

### Requirement: Child-labor prevention at employment registration
Employment registration SHALL run identity + face verification of the candidate and MUST automatically block registration when the verified age is below 16, with a warning and an audit record. The check MUST link to the person archive (A-06) and offer one-click verification for employers (protection rather than burden).

#### Scenario: Registration blocked for age below 16
- **WHEN** an employer registers an employment relationship and the verified age of the candidate is below 16
- **THEN** the system automatically blocks the registration, shows a warning, and keeps an audit record of the blocked attempt

#### Scenario: Registration proceeds for age 16 and above
- **WHEN** the verified age is 16 or above
- **THEN** the employment relationship is recorded and the result links to the person archive

#### Scenario: Verification requires real-name completion
- **WHEN** the candidate has not completed real-name verification
- **THEN** the system rejects the employment registration with a real-name-required message; no document-based manual fallback is accepted

### Requirement: Attendance clock-in with work-hour accumulation
Employees SHALL clock in and out for work, with each punch recorded and work hours accumulated automatically. Accumulated hours MUST serve as the attendance basis for wage-guaranteed disbursement (I-03). Duplicate punches of the same type on the same day MUST be rejected idempotently. Missed punches MUST be recoverable through a makeup application with an audit trail. When attendance data is missing at disbursement time, the system MUST prompt for record completion.

#### Scenario: Clock-in records and accumulates hours
- **WHEN** an employee clocks in or out
- **THEN** the system records the punch time and accumulates the work hours

#### Scenario: Duplicate punch rejected idempotently
- **WHEN** an employee punches the same type again on the same day
- **THEN** the system rejects the duplicate idempotently without double-counting hours

#### Scenario: Missed punch recoverable via makeup application
- **WHEN** an employee missed a punch
- **THEN** the employee can submit a makeup application, which takes effect after employer confirmation with an audit trail

#### Scenario: Attendance hours serve as disbursement basis
- **WHEN** an employer initiates wage disbursement and attendance data is missing or incomplete
- **THEN** the system prompts for record completion, and verified work hours serve as the attendance basis for the disbursement
