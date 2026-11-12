import UIKit
import WebKit
import Network

@main
final class AppDelegate: UIResponder, UIApplicationDelegate {
    var window: UIWindow?
    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        window = UIWindow(frame: UIScreen.main.bounds)
        window?.rootViewController = JarvisViewController()
        window?.makeKeyAndVisible()
        return true
    }
}

final class JarvisViewController: UIViewController, WKNavigationDelegate, WKUIDelegate {
    private var web: WKWebView!
    private var server: LocalAssets?
    private let origin = "http://127.0.0.1:18769/"
    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = UIColor(red:0.93,green:0.96,blue:0.91,alpha:1)
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        web = WKWebView(frame:.zero, configuration:configuration)
        web.navigationDelegate = self; web.uiDelegate = self
        web.translatesAutoresizingMaskIntoConstraints = false
        web.isOpaque = false; web.backgroundColor = view.backgroundColor
        view.addSubview(web)
        NSLayoutConstraint.activate([web.topAnchor.constraint(equalTo:view.safeAreaLayoutGuide.topAnchor), web.bottomAnchor.constraint(equalTo:view.safeAreaLayoutGuide.bottomAnchor), web.leadingAnchor.constraint(equalTo:view.leadingAnchor),web.trailingAnchor.constraint(equalTo:view.trailingAnchor)])
        do {
            server = try LocalAssets(root:Bundle.main.resourceURL!.appendingPathComponent("app"))
            server?.start { [weak self] result in
                DispatchQueue.main.async {
                    guard let self else {return}
                    switch result {
                    case .success:
                        let offline = ProcessInfo.processInfo.arguments.contains("--test-offline")
                        self.web.load(URLRequest(url:URL(string:self.origin + "?offline=" + (offline ? "1":"0"))!))
                    case .failure: self.failure("Le service local ne peut pas démarrer. Fermez Jarvis puis réessayez.")
                    }
                }
            }
        } catch {failure("Le port local est occupé. Fermez Jarvis puis réessayez.")}
    }
    private func failure(_ message:String) {
        let alert=UIAlertController(title:"Jarvis",message:message,preferredStyle:.alert)
        alert.addAction(UIAlertAction(title:"Réessayer",style:.default) { [weak self] _ in self?.web.reload() })
        present(alert,animated:true)
    }
    func webView(_ webView:WKWebView, decidePolicyFor action:WKNavigationAction, decisionHandler:@escaping(WKNavigationActionPolicy)->Void) {
        guard let url=action.request.url else {decisionHandler(.cancel);return}
        if url.absoluteString.hasPrefix(origin) {decisionHandler(.allow);return}
        if action.navigationType == .linkActivated && url.scheme == "https" {UIApplication.shared.open(url)}
        decisionHandler(.cancel)
    }
    func webView(_ webView:WKWebView, didFailProvisionalNavigation navigation:WKNavigation!, withError error:Error) {failure("Chargement impossible. Réessayez.")}
    func webView(_ webView:WKWebView, didFinish navigation:WKNavigation!) {
        guard ProcessInfo.processInfo.arguments.contains("--self-test"), let file=Bundle.main.url(forResource:"selftest",withExtension:"js"), let js=try? String(contentsOf:file,encoding:.utf8) else {return}
        webView.callAsyncJavaScript("return await " + js, arguments:[:],in:nil,in:.page) { result in
            let report: [String:Any]
            switch result {
            case .success(let value): report=value as? [String:Any] ?? ["ok":false,"error":"Rapport invalide"]
            case .failure(let error): report=["ok":false,"error":error.localizedDescription]
            }
            let url=FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("verification.json")
            if let data=try? JSONSerialization.data(withJSONObject:report,options:[.prettyPrinted,.sortedKeys]) {try? data.write(to:url)}
        }
    }
}

final class LocalAssets {
    private let listener:NWListener
    private let root:URL
    private let queue=DispatchQueue(label:"jarvis.assets",qos:.userInitiated,attributes:.concurrent)
    init(root:URL) throws {
        self.root=root.standardizedFileURL
        let parameters=NWParameters.tcp
        parameters.requiredLocalEndpoint = .hostPort(host:"127.0.0.1",port:18769)
        listener=try NWListener(using:parameters)
    }
    func start(_ ready:@escaping(Result<Void,Error>)->Void) {
        listener.stateUpdateHandler={state in
            if case .ready=state {ready(.success(()))}
            if case .failed(let error)=state {ready(.failure(error))}
        }
        listener.newConnectionHandler={ [weak self] connection in
            guard let self else {connection.cancel();return}
            connection.start(queue:self.queue)
            self.receive(connection,Data())
        }
        listener.start(queue:queue)
    }
    private func receive(_ connection:NWConnection,_ prefix:Data) {
        connection.receive(minimumIncompleteLength:1,maximumLength:16384) { [weak self] data,_,complete,error in
            guard let self else {connection.cancel();return}
            let request=prefix + (data ?? Data())
            if request.count>16384 || error != nil {connection.cancel();return}
            if request.range(of:Data("\r\n\r\n".utf8)) != nil {self.respond(connection,request)}
            else if complete {connection.cancel()}
            else {self.receive(connection,request)}
        }
    }
    private func respond(_ connection:NWConnection,_ request:Data) {
        guard let text=String(data:request,encoding:.utf8) else {connection.cancel();return}
        let lines=text.components(separatedBy:"\r\n")
        let parts=(lines.first ?? "").split(separator:" ")
        guard parts.count==3, ["GET","HEAD"].contains(parts[0]), lines.contains(where:{$0.lowercased() == "host: 127.0.0.1:18769"}), let url=URLComponents(string:String(parts[1])) else {connection.cancel();return}
        let resource=url.path == "/" ? "index.html" : String(url.path.dropFirst())
        let file=root.appendingPathComponent(resource).standardizedFileURL
        guard file.path.hasPrefix(root.path + "/"), !resource.contains("\\"), let content=try? Data(contentsOf:file) else {
            send(connection,status:"404 Not Found",mime:"text/plain",data:Data(),head:false);return
        }
        let mime=["html":"text/html; charset=utf-8","js":"text/javascript","mjs":"text/javascript","css":"text/css","wasm":"application/wasm","png":"image/png","webmanifest":"application/manifest+json","json":"application/json"][file.pathExtension] ?? "application/octet-stream"
        var data=content
        if resource == "index.html",let html=String(data:content,encoding:.utf8) {data=Data(html.replacingOccurrences(of:"<head>",with:"<head><meta name=\"jarvis-native\" content=\"bundled\">").utf8)}
        send(connection,status:"200 OK",mime:mime,data:data,head:parts[0] == "HEAD")
    }
    private func send(_ connection:NWConnection,status:String,mime:String,data:Data,head:Bool) {
        var response=Data("HTTP/1.1 \(status)\r\nContent-Type: \(mime)\r\nContent-Length: \(data.count)\r\nCache-Control: no-cache\r\nX-Content-Type-Options: nosniff\r\nConnection: close\r\n\r\n".utf8)
        if !head {response.append(data)}
        connection.send(content:response,completion:.contentProcessed({_ in connection.cancel()}))
    }
    deinit {listener.cancel()}
}
