# Platform Baseline Specification

## Purpose

Defines the platform-level capabilities of the Minsheng Zhenxuan city livelihood platform: fee-rate transparency, evidence preservation, pilot scope governance, government-system substitution, trust commitment, merchant cold-start, and anti-fraud baseline. These capabilities are cross-cutting commitments (PRD v2.3 P-01~P-06, R-15) that apply to every module on the platform.

## ADDED Requirements

### Requirement: Public fee rate and commission disclosure
The platform SHALL publicly disclose the transparent-transaction service fee rate of 0.5%~1% by category (confirmed), including the calculation method and adjustment rules, and MUST notify merchants before any rate adjustment. The disclosure page MUST be updated when new categories are onboarded. The platform MUST NOT charge bidding-based (paid placement) advertising fees or hidden deductions.

#### Scenario: Query the disclosed fee rate
- **WHEN** a user visits the fee/commission disclosure page on any of the three ends (consumer/merchant/regulator)
- **THEN** the system displays the per-category service fee rate (0.5%~1%), the calculation method, and the adjustment rules

#### Scenario: Fee adjustment requires advance notice
- **WHEN** the platform adjusts a fee rate or its calculation method
- **THEN** merchants are notified before the adjustment takes effect, and the new rate is reflected on the disclosure page

#### Scenario: Category expansion updates the disclosure
- **WHEN** a new category enters the platform through the industry expansion process (P-03)
- **THEN** the disclosure page includes the fee rate and rules for the new category before it goes live

### Requirement: Platform-wide evidence preservation and certification
The platform SHALL record timestamp + hash evidence for wage payroll flows, complaint evidence, traceability event records, and transaction records. Evidence records MUST be append-only (no modification or deletion). The platform MUST support packaging evidence on demand for labor arbitration or regulatory retrieval.

#### Scenario: Rights-related operation is automatically evidenced
- **WHEN** a wage disbursement, complaint, traceability event, or transaction leaves a record
- **THEN** the system stores a timestamp + hash entry for that record in the append-only evidence chain

#### Scenario: Evidence package export
- **WHEN** an authorized party (worker, regulator, platform operator) requests an evidence package for a business record
- **THEN** the system returns an evidence package containing the timestamped, hashed records suitable for arbitration or regulatory use

#### Scenario: Evidence cannot be altered
- **WHEN** any party attempts to modify or delete an existing evidence record
- **THEN** the system rejects the operation and preserves the original record

### Requirement: Pilot scope and industry expansion governance
The platform pilot SHALL be limited to Shijiazhuang with first-phase industries of catering + retail + housekeeping (P-03). A new industry MUST NOT enter formal scope until it completes the research → questionnaire → freeze SOP. Unfrozen industries MUST NOT be onboarded.

#### Scenario: Unfrozen industry rejected from scope
- **WHEN** a merchant from an unfrozen industry (e.g., the second batch of 7 industries) attempts to onboard
- **THEN** the system rejects onboarding with a clear message that the industry is not yet in the formal pilot scope

#### Scenario: Frozen industry enters scope
- **WHEN** an industry completes the freeze process per the SOP
- **THEN** the system allows onboarding for that industry and updates the category/fee configuration accordingly

### Requirement: Government system substitution with dual-track switch
For confirmed non-connectable government systems (Shijian Code, 12345 hotline, bank escrow accounts), the platform SHALL build self-owned substitutes: manual license verification + OCR pre-check, self-built work orders with offline circulation, and third-party licensed payment channels. The platform MUST run the self-built channel first and switch to government interfaces when they become ready (dual track). Connectable registries (childcare filing, elderly care data, education lists) MUST keep their integration paths reserved.

#### Scenario: Self-built channel operates for non-connectable systems
- **WHEN** a merchant submits licenses or a citizen submits a request
- **THEN** the platform handles it through the self-built channel (manual + OCR verification, self-built work order with offline circulation)

#### Scenario: Dual-track switch when government interface is ready
- **WHEN** a government interface becomes available for a previously substituted capability
- **THEN** the platform switches that capability to the government interface while keeping the self-built channel as fallback

### Requirement: Trust endorsement commitment
The platform SHALL deliver a unified external commitment of credit endorsement + government supervision + full-chain traceability + free promotion (credit-weighted) + direct complaint handling with public desensitized results. The platform MUST NOT substitute administrative licensing for strongly regulated categories, and AI MUST NOT execute enforcement actions.

#### Scenario: Unified commitment is delivered externally
- **WHEN** the platform presents its positioning to users, merchants, or regulators
- **THEN** the five-part commitment is stated consistently, and its boundaries (no licensing substitution, no AI enforcement) are disclosed

### Requirement: Merchant cold-start and legacy import
Merchant onboarding MUST support ≤1 minute entry (scan/photograph on PC Web). The platform SHALL provide a manual import channel for legacy merchant data. Cold-start channels are government notices and industry association mobilization; the platform MUST NOT commit to paid traffic acquisition or ground promotion. M1 exit criteria: ≥200 pilot merchants and ≥3 industries.

#### Scenario: Legacy merchant batch import
- **WHEN** the platform operator imports legacy merchant data
- **THEN** the system creates merchant archives through the manual import channel with missing data flagged for补录

#### Scenario: M1 pilot exit criteria
- **WHEN** the M1 pilot closes
- **THEN** the platform demonstrates ≥200 onboarded pilot merchants across ≥3 industries (catering, retail, housekeeping)

### Requirement: Anti-fraud and anti-cheating baseline
The platform SHALL intercept high-frequency operations from the same IP/device and abnormal price operations (R-15), and MUST retain evidence of intercepted attempts.

#### Scenario: High-frequency operation intercepted
- **WHEN** requests from the same IP/device exceed frequency thresholds on protected operations (e.g., repeated submissions, reviews, coupon redemption)
- **THEN** the system intercepts the operation and records evidence of the attempt

#### Scenario: Abnormal price operation intercepted
- **WHEN** a price entry deviates abnormally from the merchant's own historical prices
- **THEN** the system flags and intercepts the operation for review, retaining evidence
