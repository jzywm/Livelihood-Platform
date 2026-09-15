# 网关服务镜像(多阶段构建:构建阶段用 Maven,运行阶段用精简 JRE)
# 构建:docker build -f services/gateway/deploy/Dockerfile -t msz/gateway:0.1.0-SNAPSHOT .
# 运行:java -jar gateway.jar(可执行 fat jar,端口 8081)

FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /build
# 先装公共组件(网关依赖 com.msz:common),再打网关包
COPY services/_common/pom.xml services/_common/pom.xml
COPY services/_common/src services/_common/src
RUN mvn -q -f services/_common/pom.xml install -DskipTests
COPY services/gateway/pom.xml services/gateway/pom.xml
COPY services/gateway/src services/gateway/src
RUN mvn -q -f services/gateway/pom.xml package -DskipTests

FROM eclipse-temurin:17-jre
LABEL org.opencontainers.image.title="gateway" \
      org.opencontainers.image.description="民生甄选 · 网关服务 GATEWAY(平台唯一统一入口与唯一鉴权点)"
WORKDIR /app
COPY --from=build /build/services/gateway/target/gateway-*.jar /app/gateway.jar
# 无状态服务:配置与密钥全部走环境变量(KMS / GATEWAY_JWT_SECRET),不 baked 进镜像
ENV JAVA_OPTS="-XX:MaxRAMPercentage=75 -XX:+UseG1GC"
EXPOSE 8081
# 健康检查:依赖不可用时 /gateway/health 返回 503,容器编排据此摘除实例
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD ["sh", "-c", "wget -q -O- http://127.0.0.1:8081/gateway/health >/dev/null || exit 1"]
ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar /app/gateway.jar"]
