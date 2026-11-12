package io.github.raphaelflipo.jarvis;

import android.app.Activity;
import android.os.Bundle;
import android.webkit.*;
import android.content.Intent;
import android.net.Uri;
import android.widget.Toast;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;

public final class MainActivity extends Activity {
    private WebView web;
    private ServerSocket server;
    private final ExecutorService clients = Executors.newFixedThreadPool(3);
    private static final String ORIGIN = "http://127.0.0.1:18769/";
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        try {
            server = new ServerSocket(); server.setReuseAddress(true);
            server.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"),18769));
            new Thread(() -> { while(!server.isClosed()) try { Socket socket=server.accept(); clients.execute(() -> serve(socket)); } catch(IOException ignored) {} }, "jarvis-assets").start();
        } catch(IOException error) {
            new android.app.AlertDialog.Builder(this).setTitle("Jarvis ne peut pas démarrer").setMessage("Le port local est occupé. Fermez Jarvis puis réessayez.").setPositiveButton("Fermer",(d,w)->finish()).show(); return;
        }
        web = new WebView(this); setContentView(web);
        WebSettings settings=web.getSettings(); settings.setJavaScriptEnabled(true); settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false); settings.setAllowContentAccess(false); settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                String url=request.getUrl().toString();
                if(url.startsWith(ORIGIN)) return false;
                if(request.hasGesture() && url.startsWith("https://")) startActivity(new Intent(Intent.ACTION_VIEW,request.getUrl()));
                return true;
            }
            @Override public void onReceivedError(WebView view,WebResourceRequest request,WebResourceError error) {
                if(request.isForMainFrame()) Toast.makeText(MainActivity.this,"Chargement impossible. Fermez puis rouvrez Jarvis.",Toast.LENGTH_LONG).show();
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onPermissionRequest(PermissionRequest request) { request.deny(); }
        });
        web.loadUrl(ORIGIN);
    }
    private void serve(Socket socket) {
        try(Socket s=socket) {
            s.setSoTimeout(5000);
            BufferedReader reader=new BufferedReader(new InputStreamReader(s.getInputStream(),StandardCharsets.US_ASCII));
            String first=reader.readLine(); if(first==null || first.length()>4096) return;
            String[] parts=first.split(" "); if(parts.length!=3 || !(parts[0].equals("GET")||parts[0].equals("HEAD"))) return;
            int length=first.length(); String line,host="";
            while((line=reader.readLine())!=null && !line.isEmpty()) { length+=line.length(); if(length>16384) return; if(line.toLowerCase().startsWith("host:")) host=line.substring(5).trim(); }
            if(!host.equals("127.0.0.1:18769")) return;
            String resource=Uri.decode(parts[1].split("\\?",2)[0]);
            if(resource.contains("..") || resource.contains("\\") || !resource.startsWith("/")) return;
            if(resource.equals("/")) resource="/index.html";
            String mime=resource.endsWith(".wasm")?"application/wasm":resource.endsWith(".js")||resource.endsWith(".mjs")?"text/javascript":resource.endsWith(".css")?"text/css":resource.endsWith(".html")?"text/html; charset=utf-8":resource.endsWith(".png")?"image/png":"application/json";
            try(InputStream input=getAssets().open("app"+resource)) {
                ByteArrayOutputStream buffer=new ByteArrayOutputStream(); byte[] chunk=new byte[16384]; int count; while((count=input.read(chunk))!=-1) buffer.write(chunk,0,count); byte[] data=buffer.toByteArray();
                if(resource.equals("/index.html")) data=new String(data,StandardCharsets.UTF_8).replace("<head>","<head><meta name=\"jarvis-native\" content=\"bundled\">").getBytes(StandardCharsets.UTF_8);
                OutputStream out=s.getOutputStream(); out.write(("HTTP/1.1 200 OK\r\nContent-Type: "+mime+"\r\nContent-Length: "+data.length+"\r\nCache-Control: no-cache\r\nX-Content-Type-Options: nosniff\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
                if(parts[0].equals("GET")) out.write(data); out.flush();
            } catch(FileNotFoundException e) {s.getOutputStream().write("HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".getBytes(StandardCharsets.US_ASCII));}
        } catch(IOException ignored) {}
    }
    @Override protected void onDestroy() {
        if(web!=null) {web.destroy(); web=null;}
        try {if(server!=null) server.close();} catch(IOException ignored) {}
        clients.shutdownNow(); super.onDestroy();
    }
    @Override public void onBackPressed() { if(web!=null && web.canGoBack()) web.goBack(); else super.onBackPressed(); }
}
