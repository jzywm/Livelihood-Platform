package com.msz.acc.domain.model;

import java.time.Instant;

/**
 * realname_record 实名业务单实体（er.md §6.2）：回调后回填 account_id，建户前为空。
 * L1 敏感字段（name/id_no）明文进出，经 EncryptedStringTypeHandler 落库加密。
 */
public class RealnameRecord {

    private String bizId;
    private Long accountId;
    private String channel;
    private String openId;
    private String name;
    private String idNo;
    private String status;
    private String level;
    private Instant createdAt;
    private Instant callbackAt;

    public String getBizId() {
        return bizId;
    }

    public void setBizId(String bizId) {
        this.bizId = bizId;
    }

    public Long getAccountId() {
        return accountId;
    }

    public void setAccountId(Long accountId) {
        this.accountId = accountId;
    }

    public String getChannel() {
        return channel;
    }

    public void setChannel(String channel) {
        this.channel = channel;
    }

    public String getOpenId() {
        return openId;
    }

    public void setOpenId(String openId) {
        this.openId = openId;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public String getIdNo() {
        return idNo;
    }

    public void setIdNo(String idNo) {
        this.idNo = idNo;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public String getLevel() {
        return level;
    }

    public void setLevel(String level) {
        this.level = level;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Instant createdAt) {
        this.createdAt = createdAt;
    }

    public Instant getCallbackAt() {
        return callbackAt;
    }

    public void setCallbackAt(Instant callbackAt) {
        this.callbackAt = callbackAt;
    }
}
