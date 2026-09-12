# Account and Funds Specification

## Purpose

Defines the M1 account and funds capability: real-name accounts with a pure-ledger wallet (bookkeeping separated from payment), two-way labor credit reviews, and wage-guaranteed disbursement through licensed third-party channels with arrears warnings and evidence certification (PRD v2.3 I-01/I-02/I-03). The platform never holds funds.

## ADDED Requirements

### Requirement: Real-name account with pure-ledger wallet
The platform SHALL create typed accounts (individual / merchant owner / supplier / platform settlement channel) after WeChat/Alipay real-name relay. The wallet MUST be a pure ledger: no fund balance is held, no real funds are stored, and all real funds remain in licensed institution accounts. Every fund operation MUST generate a platform ledger flow containing the channel transaction number, timestamp, and evidence hash. Bookkeeping and payment MUST be separated (the channel layer is replaceable). Ledger flows MUST support certification (P-02).

#### Scenario: Real-name registration creates account
- **WHEN** a user completes WeChat/Alipay real-name relay
- **THEN** the system creates the typed account and returns the account id with real-name status

#### Scenario: Real-name channel unavailable suspends flow
- **WHEN** the WeChat/Alipay real-name relay is unavailable
- **THEN** the system suspends registration and related flows with an explicit message; no manual document verification fallback is accepted

#### Scenario: Ledger flow carries channel and hash
- **WHEN** a fund operation occurs (e.g., disbursement)
- **THEN** the system records a platform ledger flow with the channel transaction number, timestamp, and evidence hash, without holding any real funds

#### Scenario: Unauthorized flow query blocked
- **WHEN** a user queries another account's ledger flows without authorization
- **THEN** the system denies the request (horizontal privilege check)

### Requirement: Two-way labor credit review
At employment end or salary completion, both employer and worker SHALL be able to review each other with evidence attached. Confirmed weights (2026-09-11): employer side = salary fulfillment 40 + disputes 20 + employment reviews 20 + qualification compliance 20; worker side = attendance fulfillment 40 + disputes 20 + employer reviews 20 + real-name trust 20. Reviews MUST update labor credit scores integrated into the global credit system (A-07/A-06). Untrustworthy employers MUST be restricted from posting jobs and untrustworthy workers from accepting jobs.

#### Scenario: Mutual review updates credit
- **WHEN** both parties submit reviews at employment end or after salary completion
- **THEN** the system updates each side's labor credit score using the confirmed weights and records the reviews with evidence

#### Scenario: Untrustworthy party restricted
- **WHEN** an employer's or worker's credit falls below the untrustworthy threshold
- **THEN** the employer is restricted from posting jobs or the worker from accepting jobs, accordingly

### Requirement: Wage-guaranteed disbursement
The employer SHALL initiate wage disbursement through a licensed institution drawing from the employer's bound account. The platform MUST only verify employment/attendance and keep ledger records — the platform never touches the money. If wages are due but unpaid beyond the deadline, the system MUST raise an arrears warning automatically. After receipt confirmation, the system MUST update the employer's salary-fulfillment rate. Wage flows plus employment records MUST be exportable as one evidence package for arbitration (P-02).

#### Scenario: Disbursement succeeds and confirms receipt
- **WHEN** an employer initiates disbursement with valid employment/attendance and the licensed channel completes the transfer
- **THEN** the worker receives the funds, receipt confirmation updates the employer's salary-fulfillment rate, and the flows are evidenced

#### Scenario: Arrears warning raised automatically
- **WHEN** wages are due but not disbursed beyond the deadline
- **THEN** the system raises an arrears warning and notifies the relevant parties

#### Scenario: Channel failure retries idempotently
- **WHEN** the licensed channel fails or times out
- **THEN** the system retries idempotently or switches to a backup channel; duplicate payments never occur, and daily reconciliation compensates any discrepancy

#### Scenario: Evidence package export for arbitration
- **WHEN** a worker or supervisor requests certification of wage flows and employment records
- **THEN** the system exports a timestamped, hashed evidence package for labor arbitration or regulatory use

### Requirement: No fund pooling and no second clearing
The platform MUST NOT pool funds, MUST NOT perform second clearing, and MUST NOT maintain a fund pool. All funds MUST flow through licensed third-party channels with bookkeeping separated from payment (AC-C1). Audits MUST show no violation.

#### Scenario: Funds never rest on platform accounts
- **WHEN** any wage or payment flows through the platform
- **THEN** real funds are transferred entirely between licensed channel accounts; the platform records only ledger flows, and audit shows no fund resting on platform accounts
