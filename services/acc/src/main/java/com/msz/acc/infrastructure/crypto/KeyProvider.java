package com.msz.acc.infrastructure.crypto;

import javax.crypto.SecretKey;
import java.util.List;

/**
 * 加密密钥提供者（2.1）：生产走 KMS 适配实现，测试用 {@link FixedKeyProvider} 本地测试凭据。
 *
 * <p>{@link #keyIds()} 用于密钥轮换兼容：解密失败时按返回顺序逐一尝试其余 keyId，
 * 使轮换过渡期内旧密文仍可解（对齐 design.md §2.3「加密脱敏」与 UT-F01）。
 */
public interface KeyProvider {

    /** 返回 keyId 对应的对称密钥，不存在返回 null。 */
    SecretKey key(String keyId);

    /** 返回全部 keyId（有序），用于轮换兜底解密时的尝试顺序。 */
    List<String> keyIds();
}
