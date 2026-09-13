package com.msz.acc.domain.model;

import java.time.Instant;

/**
 * wallet_binding 收款账户绑定实体（er.md §6.4）：解绑置 UNBOUND 不删行，重新绑定复用原行。
 * L1 敏感字段（payee_account/payee_name）明文进出，经 EncryptedStringTypeHandler 落库加密。
 */
public class WalletBinding {

    private String bindingId;
    private long accountId;
    private String channel;
    private String payeeAccount;
    private String payeeName;
    private String status;
    private Instant createdAt;
    private Instant unboundAt;

    public String getBindingId() {
        return bindingId;
    }

    public void setBindingId(String bindingId) {
        this.bindingId = bindingId;
    }

    public long getAccountId() {
        return accountId;
    }

    public void setAccountId(long accountId) {
        this.accountId = accountId;
    }

    public String getChannel() {
        return channel;
    }

    public void setChannel(String channel) {
        this.channel = channel;
    }

    public String getPayeeAccount() {
        return payeeAccount;
    }

    public void setPayeeAccount(String payeeAccount) {
        this.payeeAccount = payeeAccount;
    }

    public String getPayeeName() {
        return payeeName;
    }

    public void setPayeeName(String payeeName) {
        this.payeeName = payeeName;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Instant createdAt) {
        this.createdAt = createdAt;
    }

    public Instant getUnboundAt() {
        return unboundAt;
    }

    public void setUnboundAt(Instant unboundAt) {
        this.unboundAt = unboundAt;
    }
}
