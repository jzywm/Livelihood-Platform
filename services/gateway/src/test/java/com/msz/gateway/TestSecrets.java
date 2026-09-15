package com.msz.gateway;

/**
 * 测试固定凭据（fixture）：与 {@code @SpringBootTest properties} 里的
 * {@code gateway.auth.jwt-secret} 保持一致。
 *
 * <p>独立成顶层类的原因：注解属性要求**编译期常量**，而同类内后置声明的常量
 * 在注解中出现会造成编译失败（实测 javac 报 cannot find symbol）；集中一处也避免
 * 各测试类各写一份密钥字面量。</p>
 */
public final class TestSecrets {

    /** 集成测试用的 HS256 密钥（与 properties 中的 gateway.auth.jwt-secret 同值）。 */
    public static final String FIXTURE_SECRET = "test-secret";

    private TestSecrets() {
    }
}
