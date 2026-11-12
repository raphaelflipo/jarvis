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
    private static ServerSocket server;
    private static final ExecutorService clients = Executors.newFixedThreadPool(3);
    private static final String ORIGIN = "http://127.0.0.1:18769/";
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        try {
            ensureServer(getApplicationContext().getAssets());
        } catch(IOException error) {
            new android.app.AlertDialog.Builder(this).setTitle("Jarvis ne peut pas démarrer").setMessage("Le port local est occupé. Fermez Jarvis puis réessayez.").setPositiveButton("Fermer",(d,w)->finish()).show(); return;
        }
        android.widget.FrameLayout content=new android.widget.FrameLayout(this);
        content.setBackgroundColor(android.graphics.Color.rgb(237,244,232));
        web = new WebView(this);
        content.addView(web,new android.widget.FrameLayout.LayoutParams(-1,-1));
        setContentView(content);
        getWindow().setStatusBarColor(android.graphics.Color.rgb(237,244,232));
        getWindow().setNavigationBarColor(android.graphics.Color.rgb(237,244,232));
        getWindow().getDecorView().setSystemUiVisibility(android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | android.view.View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        if(android.os.Build.VERSION.SDK_INT>=30) {
            getWindow().setDecorFitsSystemWindows(false);
            getWindow().setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING);
            content.setOnApplyWindowInsetsListener((view,insets)-> {
                int types=android.view.WindowInsets.Type.systemBars() | android.view.WindowInsets.Type.displayCutout() | android.view.WindowInsets.Type.ime();
                android.graphics.Insets safe=insets.getInsets(types);
                view.setPadding(safe.left,safe.top,safe.right,safe.bottom);
                android.view.WindowInsetsController controller=view.getWindowInsetsController();
                if(controller!=null) controller.setSystemBarsAppearance(android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS,android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS);
                return new android.view.WindowInsets.Builder(insets).setInsets(types,android.graphics.Insets.NONE).build();
            });
            content.requestApplyInsets();
        }
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
    private static synchronized void ensureServer(android.content.res.AssetManager assets) throws IOException {
        if(server!=null && !server.isClosed()) return;
        ServerSocket listener=new ServerSocket(); listener.setReuseAddress(true);
        try { listener.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"),18769)); }
        catch(IOException error) { listener.close(); throw error; }
        server=listener;
        new Thread(() -> { while(!listener.isClosed()) try { Socket socket=listener.accept(); clients.execute(() -> serve(socket,assets)); } catch(IOException ignored) {} },"jarvis-assets").start();
    }
    private static void serve(Socket socket,android.content.res.AssetManager assets) {
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
            try(InputStream input=assets.open("app"+resource)) {
                ByteArrayOutputStream buffer=new ByteArrayOutputStream(); byte[] chunk=new byte[16384]; int count; while((count=input.read(chunk))!=-1) buffer.write(chunk,0,count); byte[] data=buffer.toByteArray();
                if(resource.equals("/index.html")) data=new String(data,StandardCharsets.UTF_8).replace("<head>","<head><meta name=\"jarvis-native\" content=\"bundled\">").getBytes(StandardCharsets.UTF_8);
                OutputStream out=s.getOutputStream(); out.write(("HTTP/1.1 200 OK\r\nContent-Type: "+mime+"\r\nContent-Length: "+data.length+"\r\nCache-Control: no-cache\r\nX-Content-Type-Options: nosniff\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
                if(parts[0].equals("GET")) out.write(data); out.flush();
            } catch(FileNotFoundException e) {s.getOutputStream().write("HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".getBytes(StandardCharsets.US_ASCII));}
        } catch(IOException ignored) {}
    }
    @Override protected void onDestroy() {
        if(web!=null) {web.destroy(); web=null;}
        super.onDestroy();
    }
    @Override public void onBackPressed() { if(web!=null && web.canGoBack()) web.goBack(); else super.onBackPressed(); }
}
