const { contextBridge } = require('electron')

// 后续按需暴露安全的桌面能力(IPC),保持 contextIsolation 开启
contextBridge.exposeInMainWorld('desktop', {
  platform: process.platform,
})
