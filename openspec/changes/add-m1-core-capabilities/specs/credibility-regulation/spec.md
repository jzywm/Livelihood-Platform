# Credibility and Regulation Specification

## Purpose

Defines the credibility and regulation core of the platform: merchant onboarding with license verification, the public one-store-one-file archive, merchant archive maintenance with anomaly flags, price disclosure (basic edition), minor-access commitment labeling, person archives with employment history, credit scores with red/black lists, and M1 baseline regulatory alerts (PRD v2.3 A-01~A-08 M1 scope).

## ADDED Requirements

### Requirement: Merchant onboarding with license verification
A merchant SHALL complete real-name verification (WeChat/Alipay relay only — no manual document verification fallback, R-02) and upload business license and permits before archive creation. Verification MUST combine self-built manual verification with OCR pre-check (K-01). Onboarding entry MUST complete within 1 minute (scan/photograph on PC Web). License verification failure MUST return a rejection with reasons for re-submission.

#### Scenario: Successful merchant onboarding
- **WHEN** a merchant completes real-name verification and uploads a valid business license and permits within 1 minute
- **THEN** the system creates a merchant archive and returns the onboarding result with audit status

#### Scenario: Verification failure returns reasons
- **WHEN** license verification fails (missing documents, mismatch, or expired)
- **THEN** the system rejects the submission with specific reasons and allows re-submission with a saved draft

#### Scenario: Real-name channel unavailable suspends onboarding
- **WHEN** the WeChat/Alipay real-name relay is unavailable
- **THEN** the system suspends onboarding with an explicit message; manual document verification is never accepted as a fallback

### Requirement: Public one-store-one-file archive
The merchant archive public page SHALL aggregate licenses (with validity period), penalties, sampling inspections, complaint rate, praise rate, credit score, and the price list on a single screen, reachable by scan or search. Display MUST be desensitized (no L1/L2 sensitive data exposed publicly). The archive MUST include the minor-access commitment label when applicable and entry points to traceability.

#### Scenario: One-screen archive query
- **WHEN** a consumer scans a store code or searches for a merchant
- **THEN** the system shows the aggregated archive (licenses, penalties, inspections, complaint rate, praise rate, credit score, price list) on one screen without nesting in multi-level menus

#### Scenario: Sensitive data never exposed publicly
- **WHEN** any user without authorization views the archive
- **THEN** the system outputs only desensitized public-level data (L3) and masks L1/L2 sensitive fields

### Requirement: Merchant archive maintenance and anomaly flags
A merchant SHALL self-maintain the archive (update licenses, respond to complaints). License expiry, annual inspection due, and complaint surge MUST be automatically flagged on the archive and pushed bidirectionally (merchant-side reminder + regulator-side alert). Updating the archive MUST automatically clear the corresponding anomaly flag with an audit trail.

#### Scenario: License update clears the anomaly flag
- **WHEN** a merchant updates an expiring license
- **THEN** the system records the update with history, clears the related anomaly flag, and the regulator-side alert is automatically resolved

#### Scenario: Anomaly flag attached to archive
- **WHEN** a license approaches expiry, an annual inspection is due, or complaints surge for a merchant
- **THEN** the system attaches an anomaly mark to the archive and pushes reminders/alert notifications to both merchant and regulator ends

### Requirement: Price disclosure basic edition
Merchants SHALL self-maintain their price list displayed in the archive's price-disclosure area; every update MUST be versioned and traceable with history. The platform MUST NOT price on behalf of merchants. A complaint or inspection finding that charged price differs from the listed price MUST mark the merchant with a "price dispute" flag linked to the complaint channel (D-02). Prices MUST NOT vary by user profile (no price discrimination, R-07).

#### Scenario: Price list update is versioned
- **WHEN** a merchant maintains the price list (scan/photograph entry within 1 minute)
- **THEN** the system publishes the new version, keeps update history queryable, and displays the current list in the archive

#### Scenario: Price dispute is flagged
- **WHEN** a complaint or inspection finds actual charges differing from the listed prices
- **THEN** the system marks the merchant with a "price dispute" flag and links it to the D-02 complaint workflow

### Requirement: Minor-access commitment labeling
Entertainment venues and internet cafes SHALL have a "no minor entry commitment" label on their archives. The complaint channel (D-02) MUST offer a "minor entering in violation" reporting category. Reported data MUST feed the violation-entry high-frequency venue alert aggregation without automatic determination of liability (human review required).

#### Scenario: Commitment labeled on archive
- **WHEN** an entertainment venue or internet cafe confirms the commitment
- **THEN** the archive displays the desensitized "no minor entry commitment" label to consumers

#### Scenario: Label entry hidden for non-applicable categories
- **WHEN** a merchant does not belong to entertainment venue or internet cafe categories
- **THEN** the commitment entry is not available to that merchant

#### Scenario: Report feeds alert aggregation without auto-judgment
- **WHEN** minor-entry-in-violation reports accumulate for a venue
- **THEN** the reports are aggregated for regulator-side alerting, and the venue is flagged only after human review — never automatically

### Requirement: Person archive with employment history
A practitioner SHALL complete real-name verification and health/skill certificate verification to create a person archive. Employment history MUST accumulate automatically from employment relationships. The history MUST be visible only to the person and authorized employers (graded authorization, R-03). M1 covers catering and housekeeping as pilot industries.

#### Scenario: Person archive created with certificates
- **WHEN** a practitioner completes real-name verification and uploads health/skill certificates
- **THEN** the system verifies the certificates and creates a person archive

#### Scenario: History requires graded authorization
- **WHEN** an unauthorized party attempts to view a practitioner's employment history
- **THEN** the system denies access; only the person and explicitly authorized employers can view it

### Requirement: Credit scores and red/black lists
The platform SHALL compute credit scores for merchants, practitioners, and suppliers and publish desensitized red/black lists. M1 merchant score dimensions are confirmed as basic compliance 60 + operational behavior 40 (2026-09-11). Merchants MUST be able to appeal deduction items (linked to the appeal mechanism). Regulators SHALL use scores for tiered supervision (low scores checked more, high scores less).

#### Scenario: Score with confirmed dimension weights
- **WHEN** a merchant credit score is computed in M1
- **THEN** the score is composed of basic compliance (60%) and operational behavior (40%), with the dimension breakdown queryable

#### Scenario: Deduction appeal
- **WHEN** a merchant appeals a score deduction with evidence
- **THEN** the platform reviews the appeal and either revises or rejects it, recording the outcome

#### Scenario: Score manipulation intercepted
- **WHEN** brushing/cheating behavior is detected against scores or lists
- **THEN** the system intercepts it under the anti-fraud baseline (R-15) and retains evidence

### Requirement: Regulatory alerts M1 baseline
In M1 the platform SHALL provide the baseline alert capability: merchant-side license-expiry reminders (bidirectional push base) and minor-entry violation venue alert aggregation. Alerts MUST push leads only — enforcement is never executed automatically. The full alert dashboard and tiered supervision land in M2.

#### Scenario: License expiry bidirectional reminder
- **WHEN** a merchant's license approaches expiry or an annual inspection is due
- **THEN** the merchant receives a reminder and the regulator end receives the corresponding alert lead

#### Scenario: Alerts never auto-enforce
- **WHEN** an alert lead is generated
- **THEN** the system only pushes the lead; no enforcement, penalty, or public announcement happens without human confirmation
