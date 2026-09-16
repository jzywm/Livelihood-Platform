# 账户服务 ACC 镜像(多阶段构建:构建阶段用 Maven,运行阶段用精简 JRE)
# 构建:docker build -f services/acc/deploy/Dockerfile -t msz/acc:0.1.0-SNAPSHOT .
# 运行:java -cp "/app/classes:/app/lib/*" com.msz.acc.AccApplication(端口 8080)
#
# 说明(与网关镜像的差异,均为 ACC 现状事实):
#   ① ACC 的 pom **未接 spring-boot-maven-plugin**,产物不是可执行 fat jar →
#      以「classes + 运行期依赖目录」方式启动(等价 classpath,行为一致);
#   ② 会话凭据落 **Redis**(与网关同一实例):生产必须设 acc.session.store=redis + acc.redis.host
#      (缺 host 即启动 fail-fast,见 AccConfiguration#sessionStore / 裁定 R-A8);
#   ③ **M1 已知限制**:AccConfiguration 的 DataSource 仍是占位实现,容器内**未接真实数据库**——
#      凡触库的路径(注册/流水/绑定//acc/me)都会明确失败;真实 DataSource 注入落地前,
#      本镜像只用于拓扑与配置口径验证(真机联调走 services/acc/deploy/drill 真机桩)。

FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /build
# 先装公共组件(ACC 依赖 com.msz:common),再构建 ACC(测试不参与镜像构建)
COPY services/_common/pom.xml services/_common/pom.xml
COPY services/_common/src services/_common/src
RUN mvn -q -f services/_common/pom.xml install -Dmaven.test.skip=true
COPY services/acc/pom.xml services/acc/pom.xml
COPY services/acc/src services/acc/src
RUN mvn -q -f services/acc/pom.xml package dependency:copy-dependencies \
      -Dmaven.test.skip=true -DincludeScope=runtime -DoutputDirectory=/build/app/lib

FROM eclipse-temurin:17-jre
LABEL org.opencontainers.image.title="acc" \
      org.opencontainers.image.description="民生甄选 · 账户服务 ACC(实名身份底座 + 纯记账簿 + 会话凭据签发)"
WORKDIR /app
COPY --from=build /build/services/acc/target/classes /app/classes
COPY --from=build /build/app/lib /app/lib
# 配置与密钥全部走环境变量(生产经 KMS 注入),不 baked 进镜像:
#   ACC_SESSION_STORE=redis / ACC_REDIS_HOST / ACC_REDIS_PORT / ACC_REDIS_PASSWORD
#   ACC_JWT_SECRET(必须与网关 GATEWAY_JWT_SECRET 同值,否则网关验签失败)
ENV JAVA_OPTS="-XX:MaxRAMPercentage=75 -XX:+UseG1GC"
EXPOSE 8080
# 健康检查:人机验证接口为白名单公开接口,可反映进程可用性(不触库)
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD ["sh", "-c", "wget -q -O- 'http://127.0.0.1:8080/acc/captcha?type=IMAGE' >/dev/null || exit 1"]
ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -cp '/app/classes:/app/lib/*' com.msz.acc.AccApplication"]
