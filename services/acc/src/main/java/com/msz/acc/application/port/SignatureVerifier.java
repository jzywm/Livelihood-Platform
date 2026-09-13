package com.msz.acc.application.port;

/**
 * 回调签名校验端口（S5 提供真实适配，仅内网 + 验签）。
 */
public interface SignatureVerifier {

    /** 校验回调报文签名：签名有效返回 true。 */
    boolean verify(String payload, String sign);
}
