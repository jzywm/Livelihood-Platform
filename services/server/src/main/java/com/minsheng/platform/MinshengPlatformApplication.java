package com.minsheng.platform;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * 民生甄选后端单聚合服务入口。
 * <p>
 * 当前为单体聚合形态,按业务域分包(domain.*);后续按需拆分为独立微服务,
 * 拆分边界见 services/README.md。
 */
@SpringBootApplication
public class MinshengPlatformApplication {

    public static void main(String[] args) {
        SpringApplication.run(MinshengPlatformApplication.class, args);
    }
}
