package com.msz.gateway;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * 网关服务 GATEWAY · 平台唯一统一入口(M1 初期交付即接管)。
 *
 * <p>技术栈:Spring Boot 3.5 + Spring Cloud Gateway(WebFlux)+ Redis Reactive
 * + Resilience4j;无业务数据库、无状态,双实例水平扩展。</p>
 */
@SpringBootApplication
public class GatewayApplication {

    public static void main(String[] args) {
        SpringApplication.run(GatewayApplication.class, args);
    }
}
