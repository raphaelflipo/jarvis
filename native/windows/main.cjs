const { app, BrowserWindow, session, shell } = require('electron');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, 'app');
const origin = 'http://127.0.0.1:18769';
let server, window;
const testFile = process.env.JARVIS_TEST_REPORT;
const offline = process.env.JARVIS_TEST_OFFLINE === '1';
if (process.env.JARVIS_TEST_PROFILE) app.setPath('userData', process.env.JARVIS_TEST_PROFILE);
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if (window) { window.show(); window.focus(); } });
  app.whenReady().then(async () => {
    session.defaultSession.setPermissionRequestHandler((_, __, done) => done(false));
    if (offline) session.defaultSession.webRequest.onBeforeRequest((details, done) => done({cancel: !details.url.startsWith(origin + '/')}));
    server = http.createServer((req, res) => {
      try {
        if (!['GET', 'HEAD'].includes(req.method) || req.headers.host !== '127.0.0.1:18769') {res.writeHead(403).end(); return;}
        const relative = decodeURIComponent(new URL(req.url, origin).pathname).slice(1) || 'index.html';
        const filename = path.resolve(root, relative);
        if (!filename.startsWith(root + path.sep) || !fs.statSync(filename).isFile()) {res.writeHead(404).end(); return;}
        const mime = {'.html':'text/html; charset=utf-8','.js':'text/javascript','.mjs':'text/javascript','.css':'text/css','.json':'application/json','.wasm':'application/wasm','.png':'image/png','.webmanifest':'application/manifest+json'};
        res.writeHead(200, {'Content-Type':mime[path.extname(filename)] || 'application/octet-stream','X-Content-Type-Options':'nosniff','Cache-Control':'no-cache'});
        if (req.method === 'HEAD') res.end();
        else if (relative === 'index.html') res.end(fs.readFileSync(filename,'utf8').replace('<head>', '<head><meta name="jarvis-native" content="bundled">'));
        else fs.createReadStream(filename).pipe(res);
      } catch {res.writeHead(404).end();}
    });
    await new Promise((resolve, reject) => {server.once('error',reject); server.listen(18769,'127.0.0.1',resolve);});
    window = new BrowserWindow({width:1000,height:800,minWidth:360,minHeight:540,backgroundColor:'#edf4e8',autoHideMenuBar:true,
      webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true}});
    window.webContents.setWindowOpenHandler(() => ({action:'deny'}));
    window.webContents.on('will-navigate', (event, url) => { if (!url.startsWith(origin + '/')) {event.preventDefault(); if (url.startsWith('https://')) shell.openExternal(url);} });
    window.webContents.on('render-process-gone', () => { if (!testFile) window.loadURL(origin + '/'); });
    await window.loadURL(origin + '/?offline=' + Number(offline));
    if (testFile) {
      try {const report=await window.webContents.executeJavaScript(fs.readFileSync(path.join(__dirname,'selftest.js'),'utf8')); await new Promise(resolve=>{window.webContents.once('did-finish-load',resolve);window.webContents.reload();}); report.interface=await window.webContents.executeJavaScript(fs.readFileSync(path.join(__dirname,'ui-selftest.js'),'utf8')); fs.writeFileSync(testFile,JSON.stringify(report,null,2)); app.quit();}
      catch(error) {fs.writeFileSync(testFile,JSON.stringify({ok:false,error:String(error)})); app.exit(1);}
    }
  }).catch(error => {if(testFile) fs.writeFileSync(testFile,JSON.stringify({ok:false,error:String(error)})); app.exit(1);});
  app.on('window-all-closed', () => app.quit());
  app.on('will-quit', () => server?.close());
}
