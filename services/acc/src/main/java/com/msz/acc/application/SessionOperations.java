package com.msz.acc.application;

/**
 * 会话凭据操作契约（登录 / 换发 / 登出）。
 *
 * <p>由 {@link SessionFlow} 实现；控制器依赖本接口而非实现类——控制器测试因此可以用**手工测试替身**
 * 断言「HTTP 契约」（Cookie 属性、状态码、参数来源），不必依赖字节码 mock 能力
 * （本模块 MockMaker 为 {@code mock-maker-subclass}，无法 mock final 类）。</p>
 */
public interface SessionOperations {

    /** 登录：手机号 + 人机验证票据 → 签发双 token。 */
    SessionFlow.LoginOutcome login(String mobile, String captchaToken);

    /** 换发：消费并轮换 refresh，返回新 token 对。 */
    SessionFlow.RefreshOutcome refresh(String refreshToken);

    /** 登出：吊销当前会话族（幂等）。 */
    SessionFlow.LogoutOutcome logout(String accessJti, String accessFamilyId, long accessRemainingSeconds,
                                     String refreshToken);
}
