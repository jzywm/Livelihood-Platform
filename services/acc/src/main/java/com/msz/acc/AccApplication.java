package com.msz.acc;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * ACC 账户服务 Spring Boot 装配入口（S5）。
 *
 * <p>scanBasePackages 固定为 {@code com.msz.acc}：控制器（controller）、装配（config）、
 * 应用层（application）、基础设施（infrastructure）均在该包下；领域模型/规则为
 * 无注解纯对象，由 {@link com.msz.acc.config.AccConfiguration} 显式装配。</p>
 */
@SpringBootApplication(scanBasePackages = "com.msz.acc")
public class AccApplication {

    public static void main(String[] args) {
        SpringApplication.run(AccApplication.class, args);
    }
}
