package com.msz.acc.infrastructure.auth.session;

/**
 * 会话存储不可用（fail-closed 信号）。
 *
 * <p>由 {@code SessionStore} 各实现（含 Lettuce 客户端）在「连接/命令失败、超时」时抛出，经
 * {@code GlobalExceptionHandler} 映射为 **503 + 5003**（依赖不可用）。语义边界与
 * {@code ChannelUnavailableException}（4xxx，第三方业务通道）不同：本异常表示**平台自身会话存储**
 * 不可用，故走 5xxx。抛出即代表**未签发任何 token**、也未产生任何写入副作用。</p>
 */
public class SessionStoreUnavailableException extends RuntimeException {

    public SessionStoreUnavailableException(String message) {
        super(message);
    }

    public SessionStoreUnavailableException(String message, Throwable cause) {
        super(message, cause);
    }
}
