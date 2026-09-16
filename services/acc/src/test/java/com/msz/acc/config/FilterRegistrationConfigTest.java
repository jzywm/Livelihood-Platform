package com.msz.acc.config;

import com.msz.acc.infrastructure.auth.TrustedHeaderAuthFilter;
import com.msz.acc.infrastructure.tx.TransactionBoundaryFilter;
import com.msz.acc.repository.DaoSupport;
import com.msz.acc.repository.RequestSqlSessionHolder;
import jakarta.servlet.DispatcherType;
import org.apache.ibatis.datasource.unpooled.UnpooledDataSource;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.boot.web.servlet.FilterRegistrationBean;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 过滤器装配的派发类型口径（最终评审修复波 FIX-1/F5）。
 *
 * <p>两个请求级过滤器（鉴权 order 1、事务边界 order 2）都持有**请求作用域**语义：
 * 事务边界进入时 {@code RequestSqlSessionHolder.beginRequest()} 建 ThreadLocal 作用域、离开时提交/回滚并
 * 关闭会话。若容器把它们也挂在 {@code FORWARD}/{@code ERROR}/{@code ASYNC} 派发上，同一次请求会在
 * 外层作用域尚未结束时再次进入——所以两者都**显式声明只服务 {@code REQUEST} 派发**
 * （不依赖容器默认值；默认值一旦随容器/注册方式变化即为静默连接泄漏）。</p>
 *
 * <p>与 {@code RequestSqlSessionHolderTest#nestedBeginRequestIsRejectedInsteadOfSilentlyOverwritingScope}
 * 互补：那一侧是「万一真被重入」的兜底拒绝，这一侧是「不让它被重入」的装配口径。</p>
 *
 * <p>断言用 {@code determineDispatcherTypes()}（注册时实际生效的集合，而非私有字段）：不显式声明时
 * Spring Boot 会走启发式——过滤器是 {@code OncePerRequestFilter} 就给**全部**派发类型，否则给
 * {@code REQUEST}。这正是「默认值靠不住」的原因：一次父类替换就会让请求级作用域被重入。</p>
 */
class FilterRegistrationConfigTest {

    private final AccConfiguration configuration = new AccConfiguration();

    @Test
    @DisplayName("FIX-1/F5 鉴权过滤器：生效派发类型只有 REQUEST（order 1、/acc/* 不变）")
    void authFilterServesRequestDispatchOnly() {
        FilterRegistrationBean<TrustedHeaderAuthFilter> registration =
                configuration.trustedHeaderAuthFilterRegistration(configuration.trustedHeaderAuthFilter());

        assertThat(registration.determineDispatcherTypes()).containsExactly(DispatcherType.REQUEST);
        assertThat(registration.getOrder()).isEqualTo(1);
        assertThat(registration.getUrlPatterns()).containsExactly("/acc/*");
    }

    @Test
    @DisplayName("FIX-1/F5 事务边界过滤器：生效派发类型只有 REQUEST（order 2、/acc/* 不变）")
    void transactionBoundaryFilterServesRequestDispatchOnly() {
        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(new DaoSupport().factory(
                new UnpooledDataSource("org.mariadb.jdbc.Driver", "jdbc:mariadb://127.0.0.1:1/acc", "root", "")));
        TransactionBoundaryFilter filter = configuration.transactionBoundaryFilter(holder);

        FilterRegistrationBean<TransactionBoundaryFilter> registration =
                configuration.transactionBoundaryFilterRegistration(filter);

        assertThat(registration.determineDispatcherTypes()).containsExactly(DispatcherType.REQUEST);
        assertThat(registration.getOrder()).isEqualTo(2);
        assertThat(registration.getUrlPatterns()).containsExactly("/acc/*");
    }
}
