const { contextBridge, ipcRenderer, webUtils } = require('electron');
contextBridge.exposeInMainWorld('bme', Object.freeze({
  invoke: (operation, params = {}) => ipcRenderer.invoke('bme:invoke', operation, params),
  importFiles: async files => {
    try {
      if (!Array.isArray(files) || files.length < 1 || files.length > 4) throw new Error();
      const paths = files.map(file => webUtils.getPathForFile(file));
      if (paths.some(value => !value)) throw new Error();
      return ipcRenderer.invoke('bme:attach-files', paths);
    } catch { return {ok:false,error:{message:'请拖入 1–4 个真实本地文件；不接受网页链接或临时图片。'}}; }
  },
  onEvent: callback => {
    const listener = (_event, value) => callback(value);
    ipcRenderer.on('bme:event', listener);
    return () => ipcRenderer.removeListener('bme:event', listener);
  },
}));
