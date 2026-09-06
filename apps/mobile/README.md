# apps/mobile · 移动端(uni-app Vue3)

uni-app(Vue 3 + Vite)移动端。

## 开发

```bash
pnpm dev:mobile              # H5
pnpm dev:mobile:mp-weixin    # 微信小程序(产物在 dist/dev/mp-weixin,用微信开发者工具打开)
```

## ⚠️ 依赖版本说明(重要)

`@dcloudio/*` 系列包必须**锁定到同一个 build 版本**,当前为 `3.0.0-4020920240930001`。
混用不同 build 的 `@dcloudio` 包会导致运行时报版本不一致错误。

如需升级到最新稳定 build,推荐用官方模板生成并复制其版本号:

```bash
npx degit dcloudio/uni-preset-vue#vite /tmp/uni-template
# 复制 /tmp/uni-template/package.json 中的 @dcloudio/* 版本号,整体替换本 package.json 里的版本
```

> 本仓库沙箱环境无法直连 npm registry 核实实时版本,故采用官方模板已知稳定 build;升级时请以官方模板为准。
