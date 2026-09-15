#!/usr/bin/env node
/**
 * 演练用下游桩(ACC 占位):回显请求路径与网关透传的身份头,并支持 /acc/slow 延迟响应。
 * 用法:node services/gateway/deploy/drill/downstream-stub.cjs [port] [slowMillis]
 * 用途:任务 12 验收演练——验证路由重写、身份头透传/伪造头剥离、超时与熔断降级(不依赖真实 ACC/DB)。
 */
const http = require('node:http');

const port = Number(process.argv[2] || 8080);
const slowMillis = Number(process.argv[3] || 2500);

const server = http.createServer((req, res) => {
  const respond = () => {
    const body = [
      `path=${req.url}`,
      `X-User-Id=${req.headers['x-user-id'] ?? 'null'}`,
      `X-User-Role=${req.headers['x-user-role'] ?? 'null'}`,
      `X-User-Mfa=${req.headers['x-user-mfa'] ?? 'null'}`,
      `X-User-Jti=${req.headers['x-user-jti'] ?? 'null'}`,
      `Authorization=${req.headers['authorization'] ? 'present' : 'absent'}`,
    ].join('|');
    res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end(body);
  };
  if (req.url.startsWith('/acc/slow')) {
    setTimeout(respond, slowMillis);
  } else {
    respond();
  }
});

server.listen(port, '127.0.0.1', () => {
  console.log(`downstream-stub listening on http://127.0.0.1:${port}/ (slow=${slowMillis}ms)`);
});
