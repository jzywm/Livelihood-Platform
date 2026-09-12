# AI Capability Center Specification

## Purpose

Defines the M1 AI capability center: license OCR auto-verification and the AI gateway with governance foundation (PRD v2.3 K-01/K-02). All AI capabilities obey the boundary that AI marks but never decides; enforcement, penalties, and public announcements always require human confirmation (C8).

## ADDED Requirements

### Requirement: License OCR auto-verification
When a license is uploaded, the system SHALL automatically extract fields and compare validity period and category, serving both the merchant-end pre-check and the regulator end. OCR results MUST be traceable. When OCR fails or the image is unreadable, the flow MUST fall back to manual verification.

#### Scenario: OCR extracts and compares
- **WHEN** a merchant or regulator uploads a license (business license / permit / inspection report)
- **THEN** the system extracts the fields, compares validity period and category, and returns the verification result with traceability

#### Scenario: OCR failure falls back to manual verification
- **WHEN** OCR recognition fails or the image is blurry
- **THEN** the system routes the license to manual verification and prompts re-upload where applicable; the pre-check never blocks on OCR alone

### Requirement: AI gateway and governance foundation
The platform SHALL provide a unified AI gateway with model routing (text / vision cloud API / OCR / platform self-built prediction channel), a unified entry with authentication, rate limiting, routing, and auditing, a task queue with result receipts, confidence-tiered outputs, and full-chain auditing. The vision cloud API MUST be covered by a data-compliance agreement (not used for training), and images MUST be desensitized before external calls.

#### Scenario: Unified routing with audit
- **WHEN** any platform component initiates an AI call
- **THEN** the call passes the unified gateway (authenticated, rate-limited, routed) and every call is recorded in the audit chain

#### Scenario: External AI failure degrades gracefully
- **WHEN** the text or vision model API fails
- **THEN** the gateway returns the failure code and the calling flow degrades (FAQ/rule base for assistant, manual review queue for vision) without blocking core business

#### Scenario: Vision cloud covered by compliance agreement
- **WHEN** images are sent to the vision cloud API
- **THEN** the images are desensitized first and the service operates under the signed data-compliance agreement (no training use)

### Requirement: AI marks but never decides
AI outputs MUST remain marks and suggestions only. Any enforcement, penalty, or public announcement action MUST require human confirmation, and review outcomes MUST NOT flow back to third-party model training (C8).

#### Scenario: AI output requires human confirmation
- **WHEN** an AI mark or risk suggestion is produced
- **THEN** no enforcement or public announcement occurs until a human confirms; the confirmation is audited

#### Scenario: Review results never flow back
- **WHEN** human review results are recorded
- **THEN** they are used only for platform tuning and are never returned to third-party model training
