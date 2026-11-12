// Jarvis.app — fenêtre native macOS (AppKit + WebKit) avec verre translucide (vibrancy).
// Le paquet autonome contient le moteur et ses dépendances.
// - lance le serveur local de Jarvis s'il ne tourne pas (enfant de l'app → autorisations macOS attribuées à « Jarvis ») ;
// - fermer la fenêtre ne coupe rien ; un clic sur l'icône du Dock la rouvre ;
// - ⌘Q quitte la fenêtre, les tâches continuent ; ⌥⌘Q arrête aussi les tâches ;
// - raccourci global (⌥ Espace par défaut) : fait apparaître Jarvis par-dessus n'importe quelle app, prêt à écrire.
import Carbon.HIToolbox
import Cocoa
import EventKit
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var webView: WKWebView!
    var server: Process?
    var ollama: Process?
    var hotKeyRef: EventHotKeyRef?
    var hotKeySpec = ""
    var hotKeyHandlerInstalled = false
    let home = FileManager.default.homeDirectoryForCurrentUser
    var jarvisDir: URL { URL(fileURLWithPath:ProcessInfo.processInfo.environment["JARVIS_HOME"] ?? home.appendingPathComponent(".jarvis").path) }
    var resources: URL { Bundle.main.resourceURL! }
    var bundled: Bool { FileManager.default.fileExists(atPath:resources.appendingPathComponent("python/bin/python3").path) }


    // ------------------------------------------------------------------ configuration
    func config() -> [String: Any] {
        let url = jarvisDir.appendingPathComponent("config.json")
        guard let data = try? Data(contentsOf: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [:] }
        return obj
    }
    var port: Int { ((config()["server"] as? [String: Any])?["port"] as? Int) ?? 8765 }
    var glass: Bool { (config()["native_glass"] as? Bool) ?? true }
    func token() -> String {
        let url = jarvisDir.appendingPathComponent("server_token")
        return ((try? String(contentsOf: url, encoding: .utf8)) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    func ping() -> Bool {
        guard let url = URL(string: "http://127.0.0.1:\(port)/healthz") else { return false }
        var ok = false
        let sem = DispatchSemaphore(value: 0)
        var req = URLRequest(url: url)
        req.timeoutInterval = 1.0
        URLSession.shared.dataTask(with: req) { data, resp, _ in
            if let data, let json=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any] {
                ok = (resp as? HTTPURLResponse)?.statusCode == 200 && json["version"] as? String == "3.3.0-rc.1"
            }
            sem.signal()
        }.resume()
        _ = sem.wait(timeout: .now() + 1.5)
        return ok
    }

    func startServerIfNeeded() {
        if ping() { return }
        try? FileManager.default.createDirectory(at:jarvisDir.appendingPathComponent("logs"),withIntermediateDirectories:true)
        if bundled { startOllama() }
        let py = bundled ? resources.appendingPathComponent("python/bin/python3") : jarvisDir.appendingPathComponent("venv/bin/python3")
        let script = bundled ? resources.appendingPathComponent("backend/jarvis.py") : jarvisDir.appendingPathComponent("app/jarvis.py")
        let p = Process()
        p.executableURL = py
        p.arguments = [script.path, "serve"]
        p.currentDirectoryURL = script.deletingLastPathComponent()
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = py.deletingLastPathComponent().path + ":" + resources.appendingPathComponent("ollama").path + ":/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        env["JARVIS_HOME"] = jarvisDir.path
        env["JARVIS_RUNTIME_BIN"] = py.deletingLastPathComponent().path
        env["JARVIS_AGENDA_HELPER"] = Bundle.main.executableURL!.deletingLastPathComponent().appendingPathComponent("jarvis-agenda").path
        env["PLAYWRIGHT_BROWSERS_PATH"] = resources.appendingPathComponent("browsers").path
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if bundled { env["SSL_CERT_FILE"] = resources.appendingPathComponent("python/lib/python3.12/site-packages/certifi/cacert.pem").path }
        p.environment = env
        let logURL = jarvisDir.appendingPathComponent("logs/server.log")
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        if let log = try? FileHandle(forWritingTo: logURL) {
            log.seekToEndOfFile()
            p.standardOutput = log
            p.standardError = log
        }
        do { try p.run(); server = p } catch { NSLog("Jarvis: impossible de lancer le serveur: \(error)") }
    }

    func startOllama() {
        let cfg = config()
        let host = cfg["ollama_host"] as? String ?? "http://127.0.0.1:11434"
        guard host == "http://127.0.0.1:11434" else { return }
        let process=Process()
        process.executableURL=resources.appendingPathComponent("ollama/ollama")
        process.arguments=["serve"]
        var environment=ProcessInfo.processInfo.environment
        environment["OLLAMA_HOST"]="127.0.0.1:11434"
        process.environment=environment
        let logURL=jarvisDir.appendingPathComponent("logs/ollama.log")
        FileManager.default.createFile(atPath:logURL.path,contents:nil)
        if let log=try? FileHandle(forWritingTo:logURL) {log.seekToEndOfFile();process.standardOutput=log;process.standardError=log}
        do {try process.run();ollama=process} catch {NSLog("Moteur local indisponible: \(error)")}
    }
    func loadAndOfferModel() {
        load()
        if bundled && config()["model"] == nil { installModel(nil) }
    }
    @objc func installModel(_ sender:Any?) {
        let model=config()["model"] as? String ?? "qwen3:1.7b"
        let alert=NSAlert()
        alert.messageText="Installer le modèle local"
        let size=model == "qwen3:1.7b" ? "environ 1,4 Go" : model == "qwen3:8b" ? "environ 5,2 Go" : "une taille dépendant du modèle"
        alert.informativeText="Jarvis utilise \(model). Le téléchargement initial nécessite Internet et \(size). Les conversations restent sur le Mac. Vous pourrez relancer cette étape dans le menu Jarvis."
        alert.addButton(withTitle:"Télécharger"); alert.addButton(withTitle:"Plus tard")
        guard alert.runModal() == .alertFirstButtonReturn else {return}
        let progress=NSAlert(); progress.messageText="Téléchargement de \(model)…"
        progress.informativeText="Laissez cette fenêtre ouverte. Le téléchargement peut prendre plusieurs minutes."
        let indicator=NSProgressIndicator(frame:NSRect(x:0,y:0,width:300,height:20));indicator.style = .bar;indicator.isIndeterminate=true;indicator.startAnimation(nil);progress.accessoryView=indicator
        progress.addButton(withTitle:"Fermer la fenêtre")
        progress.beginSheetModal(for:window)
        DispatchQueue.global().async {
            let process=Process();process.executableURL=self.resources.appendingPathComponent("ollama/ollama");process.arguments=["pull",model]
            var environment=ProcessInfo.processInfo.environment
            environment["OLLAMA_HOST"] = self.config()["ollama_host"] as? String ?? "http://127.0.0.1:11434"
            process.environment=environment
            let output=Pipe();process.standardOutput=output;process.standardError=output
            output.fileHandleForReading.readabilityHandler={handle in _=handle.availableData}
            var success=false
            do {try process.run();process.waitUntilExit();success=process.terminationStatus==0} catch {}
            output.fileHandleForReading.readabilityHandler=nil
            if success {
                var settings=self.config();settings["model"]=model
                if let data=try? JSONSerialization.data(withJSONObject:settings,options:[.prettyPrinted,.sortedKeys]) {
                    let file=self.jarvisDir.appendingPathComponent("config.json")
                    try? data.write(to:file,options:.atomic)
                    try? FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:file.path)
                }
            }
            DispatchQueue.main.async {
                if progress.window.sheetParent != nil {self.window.endSheet(progress.window)}
                let result=NSAlert();result.messageText=success ? "Modèle installé" : "Téléchargement interrompu"
                result.informativeText=success ? "Quittez puis rouvrez Jarvis pour utiliser le modèle choisi." : "Vérifiez votre connexion et l'espace disponible, puis réessayez depuis le menu Jarvis."
                result.runModal()
            }
        }
    }

    // ------------------------------------------------------------------ cycle de vie
    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        makeWindow()
        DispatchQueue.global().async {
            self.startServerIfNeeded()
            var tries = 0
            while !self.ping() && tries < 100 { Thread.sleep(forTimeInterval: 0.25); tries += 1 }
            DispatchQueue.main.async { tries < 100 ? self.loadAndOfferModel() : self.showError() }
        }
        NSApp.activate(ignoringOtherApps: true)
        registerHotKey()
    }

    // ------------------------------------------------------------------ raccourci global
    // Carbon RegisterEventHotKey : aucune autorisation d'accessibilité nécessaire.
    static let letters: [Character: Int] = [
        "a": kVK_ANSI_A, "b": kVK_ANSI_B, "c": kVK_ANSI_C, "d": kVK_ANSI_D, "e": kVK_ANSI_E, "f": kVK_ANSI_F, "g": kVK_ANSI_G,
        "h": kVK_ANSI_H, "i": kVK_ANSI_I, "j": kVK_ANSI_J, "k": kVK_ANSI_K, "l": kVK_ANSI_L, "m": kVK_ANSI_M, "n": kVK_ANSI_N,
        "o": kVK_ANSI_O, "p": kVK_ANSI_P, "q": kVK_ANSI_Q, "r": kVK_ANSI_R, "s": kVK_ANSI_S, "t": kVK_ANSI_T, "u": kVK_ANSI_U,
        "v": kVK_ANSI_V, "w": kVK_ANSI_W, "x": kVK_ANSI_X, "y": kVK_ANSI_Y, "z": kVK_ANSI_Z]

    func parseHotKey(_ spec: String) -> (UInt32, UInt32)? {
        var mods = 0, key = -1
        for part in spec.lowercased().split(separator: "+").map({ $0.trimmingCharacters(in: .whitespaces) }) {
            switch part {
            case "alt", "option", "opt": mods |= optionKey
            case "cmd", "command": mods |= cmdKey
            case "ctrl", "control": mods |= controlKey
            case "shift": mods |= shiftKey
            case "space": key = kVK_Space
            default:
                if part.count == 1, let c = part.first, let k = AppDelegate.letters[c] { key = k } else { return nil }
            }
        }
        return key >= 0 && mods != 0 ? (UInt32(key), UInt32(mods)) : nil
    }

    func registerHotKey() {
        let spec = (config()["hotkey"] as? String) ?? "alt+space"
        if spec == hotKeySpec { return }
        if let ref = hotKeyRef { UnregisterEventHotKey(ref); hotKeyRef = nil }
        hotKeySpec = spec
        guard spec != "off", let (key, mods) = parseHotKey(spec) else { return }
        if !hotKeyHandlerInstalled {
            var type = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
            InstallEventHandler(GetApplicationEventTarget(), { _, _, userData in
                guard let userData = userData else { return noErr }
                let me = Unmanaged<AppDelegate>.fromOpaque(userData).takeUnretainedValue()
                DispatchQueue.main.async { me.toggleQuick() }
                return noErr
            }, 1, &type, Unmanaged.passUnretained(self).toOpaque(), nil)
            hotKeyHandlerInstalled = true
        }
        let id = EventHotKeyID(signature: OSType(0x4A52_5653), id: 1)       // « JRVS »
        let st = RegisterEventHotKey(key, mods, id, GetApplicationEventTarget(), 0, &hotKeyRef)
        if st != noErr { NSLog("Jarvis: raccourci \(spec) indisponible (\(st)), déjà pris par une autre app ?") }
    }

    @objc func toggleQuick() {
        if NSApp.isActive && window.isVisible && window.isKeyWindow && !window.isMiniaturized {
            NSApp.hide(nil)
            return
        }
        window.collectionBehavior.insert(.moveToActiveSpace)      // apparaît sur le bureau où tu es
        if window.isMiniaturized { window.deminiaturize(nil) }
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
        webView.evaluateJavaScript("window.quickAsk && quickAsk()", completionHandler: nil)
    }

    func applicationDidBecomeActive(_ notification: Notification) { registerHotKey() }

    func userContentController(_ ucc: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
        if type == "hotkey" {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { self.registerHotKey() }   // après l'écriture du réglage
        } else if type == "agenda_access" {
            requestAgendaAccess()
        }
    }

    // Calendrier et Rappels : la demande vient de l'app elle-même (fenêtre macOS au nom de « Jarvis », une seule fois) ;
    // l'outil jarvis-agenda, rangé dans l'app, profite ensuite de l'autorisation.
    let eventStore = EKEventStore()
    func requestAgendaAccess() {
        NSApp.activate(ignoringOtherApps: true)
        let report: (String) -> Void = { msg in
            DispatchQueue.main.async {
                let js = "window.agendaAccessDone && agendaAccessDone(\(String(reflecting: msg)))"
                self.webView.evaluateJavaScript(js, completionHandler: nil)
            }
        }
        let ask: (EKEntityType, @escaping (Bool) -> Void) -> Void = { type, done in
            if #available(macOS 14.0, *) {
                if type == .event { self.eventStore.requestFullAccessToEvents { ok, _ in done(ok) } }
                else { self.eventStore.requestFullAccessToReminders { ok, _ in done(ok) } }
            } else {
                self.eventStore.requestAccess(to: type) { ok, _ in done(ok) }
            }
        }
        ask(.event) { cal in
            ask(.reminder) { rem in
                report(cal && rem ? "Calendrier et Rappels autorisés ✅"
                       : "Accès refusé : Réglages Système › Confidentialité et sécurité › Calendriers / Rappels › active « Jarvis ».")
            }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { window.makeKeyAndOrderFront(nil) }
        return true
    }

    @objc func quitAndStop(_ sender: Any?) {
        server?.terminate()
        ollama?.terminate()
        NSApp.terminate(nil)
    }

    // ------------------------------------------------------------------ fenêtre
    func makeWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1380, height: 900),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                          backing: .buffered, defer: false)
        window.title = "Jarvis"
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.minSize = NSSize(width: 860, height: 600)
        window.isReleasedWhenClosed = false
        window.setFrameAutosaveName("JarvisMainWindow")
        if window.frame.origin == .zero { window.center() }

        let conf = WKWebViewConfiguration()
        conf.websiteDataStore = .default()
        conf.userContentController.add(self, name: "jarvis")      // l'interface prévient l'app (ex. raccourci changé)
        webView = WKWebView(frame: .zero, configuration: conf)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsMagnification = true
        webView.autoresizingMask = [.width, .height]

        if glass {
            window.isOpaque = false
            window.backgroundColor = .clear
            webView.setValue(false, forKey: "drawsBackground")
            if #available(macOS 12.0, *) { webView.underPageBackgroundColor = .clear }
            let fx = NSVisualEffectView()
            fx.material = .underWindowBackground
            fx.blendingMode = .behindWindow
            fx.state = .active
            fx.autoresizingMask = [.width, .height]
            window.contentView = fx
            webView.frame = fx.bounds
            fx.addSubview(webView)
        } else {
            window.backgroundColor = NSColor(calibratedRed: 0.02, green: 0.07, blue: 0.04, alpha: 1)
            window.contentView = webView
        }
        let splash = "<html><body style='margin:0;height:100vh;display:grid;place-items:center;background:transparent;font:15px -apple-system;color:#9fd88a'>" +
                     "<div style='text-align:center'><div style='width:90px;height:90px;border-radius:50%;margin:0 auto 18px;" +
                     "background:radial-gradient(circle at 34% 28%,#efffe0,#7CFC00 32%,#1f6b12 80%);box-shadow:0 0 60px rgba(124,252,0,.5)'></div>" +
                     "Jarvis démarre…</div></body></html>"
        webView.loadHTMLString(splash, baseURL: nil)
        window.makeKeyAndOrderFront(nil)
    }

    func load() {
        var tok = token()
        tok = tok.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? tok
        if let url = URL(string: "http://127.0.0.1:\(port)/?app=1\(glass ? "&glass=1" : "")#t=\(tok)") {
            webView.load(URLRequest(url: url))
        }
    }

    func showError() {
        let html = "<html><body style='font:15px -apple-system;color:#eaf6e6;background:#06110a;padding:40px'>" +
                   "<h2>Jarvis ne démarre pas</h2><p>Ouvre le Terminal et lance : <code>jarvis doctor</code></p>" +
                   "<p>Journal : ~/.jarvis/logs/server.log</p></body></html>"
        webView.loadHTMLString(html, baseURL: nil)
    }

    // ------------------------------------------------------------------ navigation
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = action.request.url, let host = url.host, host != "127.0.0.1", host != "localhost",
           url.scheme == "http" || url.scheme == "https" {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { NSWorkspace.shared.open(url) }
        return nil
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = NSAlert()
        a.messageText = "Jarvis"
        a.informativeText = message
        a.runModal()
        completionHandler()
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = NSAlert()
        a.messageText = "Jarvis"
        a.informativeText = message
        a.addButton(withTitle: "Confirmer")
        a.addButton(withTitle: "Annuler")
        completionHandler(a.runModal() == .alertFirstButtonReturn)
    }

    // Sélecteur de fichiers (bouton 📎) — WKWebView ne l'affiche pas sans ce délégué
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.message = "Choisis les fichiers à envoyer à Jarvis"
        panel.prompt = "Envoyer"
        panel.beginSheetModal(for: window) { r in completionHandler(r == .OK ? panel.urls : nil) }
    }

    // Micro pour la dictée (transcription locale par Whisper) : accordé uniquement à l'interface de Jarvis elle-même
    @available(macOS 12.0, *)
    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin,
                 initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType,
                 decisionHandler: @escaping (WKPermissionDecision) -> Void) {
        let local = origin.host == "127.0.0.1" || origin.host == "localhost"
        decisionHandler(local && type == .microphone ? .grant : .deny)
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { load() }

    // ------------------------------------------------------------------ menus
    @objc func openSettings(_ sender: Any?) { webView.evaluateJavaScript("openSettings()", completionHandler: nil) }
    @objc func newTask(_ sender: Any?) { webView.evaluateJavaScript("showHome()", completionHandler: nil) }
    @objc func reload(_ sender: Any?) { load() }

    func buildMenu() {
        let main = NSMenu()
        func item(_ title: String, _ sel: Selector?, _ key: String, _ mods: NSEvent.ModifierFlags = [.command]) -> NSMenuItem {
            let i = NSMenuItem(title: title, action: sel, keyEquivalent: key)
            i.keyEquivalentModifierMask = mods
            return i
        }
        let appItem = NSMenuItem(); main.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(item("À propos de Jarvis", #selector(NSApplication.orderFrontStandardAboutPanel(_:)), ""))
        appMenu.addItem(.separator())
        let s = item("Réglages…", #selector(openSettings(_:)), ","); s.target = self; appMenu.addItem(s)
        appMenu.addItem(.separator())
        appMenu.addItem(item("Masquer Jarvis", #selector(NSApplication.hide(_:)), "h"))
        appMenu.addItem(.separator())
        appMenu.addItem(item("Quitter (les tâches continuent)", #selector(NSApplication.terminate(_:)), "q"))
        let modelItem=item("Installer le modèle local…",#selector(installModel(_:)),"",[]);modelItem.target=self;appMenu.addItem(modelItem)
        let q = item("Quitter et arrêter les tâches", #selector(quitAndStop(_:)), "q", [.command, .option]); q.target = self; appMenu.addItem(q)
        appItem.submenu = appMenu

        let fileItem = NSMenuItem(); main.addItem(fileItem)
        let fileMenu = NSMenu(title: "Fichier")
        let n = item("Nouvelle tâche", #selector(newTask(_:)), "n"); n.target = self; fileMenu.addItem(n)
        fileMenu.addItem(item("Fermer la fenêtre", #selector(NSWindow.performClose(_:)), "w"))
        fileItem.submenu = fileMenu

        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: "Édition")
        edit.addItem(item("Annuler", Selector(("undo:")), "z"))
        edit.addItem(item("Rétablir", Selector(("redo:")), "z", [.command, .shift]))
        edit.addItem(.separator())
        edit.addItem(item("Couper", #selector(NSText.cut(_:)), "x"))
        edit.addItem(item("Copier", #selector(NSText.copy(_:)), "c"))
        edit.addItem(item("Coller", #selector(NSText.paste(_:)), "v"))
        edit.addItem(item("Tout sélectionner", #selector(NSText.selectAll(_:)), "a"))
        editItem.submenu = edit

        let viewItem = NSMenuItem(); main.addItem(viewItem)
        let view = NSMenu(title: "Présentation")
        let r = item("Recharger", #selector(reload(_:)), "r"); r.target = self; view.addItem(r)
        view.addItem(item("Plein écran", #selector(NSWindow.toggleFullScreen(_:)), "f", [.command, .control]))
        viewItem.submenu = view

        let winItem = NSMenuItem(); main.addItem(winItem)
        let win = NSMenu(title: "Fenêtre")
        win.addItem(item("Réduire", #selector(NSWindow.performMiniaturize(_:)), "m"))
        win.addItem(item("Zoom", #selector(NSWindow.performZoom(_:)), ""))
        winItem.submenu = win
        NSApp.windowsMenu = win
        NSApp.mainMenu = main
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
