package com.msz.acc.infrastructure.auth.session;

/**
 * 一条未过期短 token 的 `jti` + 剩余有效期（写网关共享吊销名单的入参）。
 *
 * @param jti              短 token 的 `jti`
 * @param remainingSeconds 剩余有效期（秒，TTL 语义与网关契约一致）
 */
public record AccessJti(String jti, long remainingSeconds) {
}
