package io.github.raphaelflipo.jarvis;

import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;
import static org.junit.Assert.*;
import android.content.Intent;
import android.app.Activity;
import android.view.ViewGroup;
import android.webkit.WebView;
import java.util.concurrent.atomic.AtomicReference;
import java.nio.charset.StandardCharsets;
import java.io.*;

public class LocalInferenceTest {
    private android.app.Instrumentation getInstrumentation() {return InstrumentationRegistry.getInstrumentation();}
    private WebView findWebView(android.view.View view) {
        if(view instanceof WebView) return (WebView)view;
        if(view instanceof ViewGroup) for(int i=0;i<((ViewGroup)view).getChildCount();i++) {
            WebView result=findWebView(((ViewGroup)view).getChildAt(i));if(result!=null)return result;
        }
        return null;
    }
    @Test public void testLocalModelAndReopen() throws Exception {
        String js;
        try(InputStream in=getInstrumentation().getContext().getAssets().open("selftest.js")) {
            ByteArrayOutputStream out=new ByteArrayOutputStream(); byte[] chunk=new byte[8192]; int n;
            while((n=in.read(chunk))!=-1) out.write(chunk,0,n);
            js=out.toString("UTF-8");
        }
        String phase=InstrumentationRegistry.getArguments().getString("jarvis_phase");
        for(boolean offline:new boolean[]{false,true}) {
            if(phase!=null && offline != phase.equals("offline")) continue;
            Intent intent=new Intent(Intent.ACTION_MAIN).setClassName("io.github.raphaelflipo.jarvis","io.github.raphaelflipo.jarvis.MainActivity").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            Activity activity=getInstrumentation().startActivitySync(intent);
            Thread.sleep(4000);
            WebView web=findWebView(activity.findViewById(android.R.id.content));
            String script="history.replaceState(null,'','/?offline="+(offline?"1":"0")+"');"+js+".then(r=>document.title='JARVIS_TEST:'+JSON.stringify(r)).catch(e=>document.title='JARVIS_TEST:'+JSON.stringify({ok:false,error:String(e)}));";
            getInstrumentation().runOnMainSync(()->web.evaluateJavascript(script,null));
            AtomicReference<String> title=new AtomicReference<>("");
            long deadline=System.currentTimeMillis()+610000;
            while(System.currentTimeMillis()<deadline) {
                getInstrumentation().runOnMainSync(()->title.set(web.getTitle()));
                if(title.get()!=null && title.get().startsWith("JARVIS_TEST:")) break;
                Thread.sleep(1000);
            }
            String report=title.get(); assertNotNull(report); assertTrue(report,report.startsWith("JARVIS_TEST:"));
            try(FileOutputStream out=new FileOutputStream(new File(getInstrumentation().getTargetContext().getFilesDir(),offline?"offline.json":"online.json"))) {out.write(report.substring(12).getBytes(StandardCharsets.UTF_8));}
            android.os.Bundle metrics=new android.os.Bundle();
            metrics.putString(offline?"jarvis_offline":"jarvis_online",report.substring(12));
            getInstrumentation().sendStatus(0,metrics);
            assertTrue(report,report.contains("\"ok\":true"));
            getInstrumentation().runOnMainSync(activity::finish);
            Thread.sleep(2000);
        }
    }
    @Test public void testVisualLayoutAndKeyboard() throws Exception {
        Intent intent=new Intent(Intent.ACTION_MAIN).setClassName("io.github.raphaelflipo.jarvis","io.github.raphaelflipo.jarvis.MainActivity").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        Activity activity=getInstrumentation().startActivitySync(intent);
        Thread.sleep(3000);
        WebView web=findWebView(activity.findViewById(android.R.id.content));
        assertNotNull(web);
        getInstrumentation().runOnMainSync(()->web.evaluateJavascript("document.getElementById('load-model').click()",null));
        AtomicReference<Boolean> ready=new AtomicReference<>(false);
        for(int i=0;i<120 && !ready.get();i++) {
            getInstrumentation().runOnMainSync(()->web.evaluateJavascript("document.getElementById('load-model').textContent === 'Modèle chargé'",v->ready.set("true".equals(v))));
            Thread.sleep(1000);
        }
        assertTrue("Le modèle doit être chargé dans l'interface",ready.get());
        getInstrumentation().runOnMainSync(()-> {web.setNetworkAvailable(false);web.reload();});
        Thread.sleep(2000);
        getInstrumentation().runOnMainSync(()->web.evaluateJavascript("document.getElementById('load-model').click()",null));
        ready.set(false);
        for(int i=0;i<120 && !ready.get();i++) {
            getInstrumentation().runOnMainSync(()->web.evaluateJavascript("document.getElementById('load-model').textContent === 'Modèle chargé'",v->ready.set("true".equals(v))));
            Thread.sleep(1000);
        }
        assertTrue("L'interface doit recharger le modèle hors ligne",ready.get());
        File folder=getInstrumentation().getTargetContext().getExternalFilesDir(null);
        try(FileOutputStream output=new FileOutputStream(new File(folder,"before-keyboard.png"))) {
            getInstrumentation().getUiAutomation().takeScreenshot().compress(android.graphics.Bitmap.CompressFormat.PNG,100,output);
        }
        java.util.concurrent.CountDownLatch positioned=new java.util.concurrent.CountDownLatch(1);
        float[] point=new float[2];
        getInstrumentation().runOnMainSync(()->web.evaluateJavascript("(()=>{const p=document.getElementById('prompt');p.scrollIntoView({block:'center',behavior:'instant'});const r=p.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2,width:innerWidth};})()",value->{
            try {
                org.json.JSONObject coordinates=new org.json.JSONObject(value);
                int[] location=new int[2];web.getLocationOnScreen(location);
                float scale=(float)(web.getWidth()/coordinates.getDouble("width"));
                point[0]=location[0]+(float)coordinates.getDouble("x")*scale;
                point[1]=location[1]+(float)coordinates.getDouble("y")*scale;
            } catch(Exception error) { throw new RuntimeException(error); }
            positioned.countDown();
        }));
        assertTrue(positioned.await(5,java.util.concurrent.TimeUnit.SECONDS));
        long now=android.os.SystemClock.uptimeMillis();
        getInstrumentation().sendPointerSync(android.view.MotionEvent.obtain(now,now,android.view.MotionEvent.ACTION_DOWN,point[0],point[1],0));
        Thread.sleep(80);
        getInstrumentation().sendPointerSync(android.view.MotionEvent.obtain(now,android.os.SystemClock.uptimeMillis(),android.view.MotionEvent.ACTION_UP,point[0],point[1],0));
        Thread.sleep(2500);
        AtomicReference<Integer> keyboardInset=new AtomicReference<>(0);
        getInstrumentation().runOnMainSync(()->keyboardInset.set(activity.getWindow().getDecorView().getRootWindowInsets().getInsets(android.view.WindowInsets.Type.ime()).bottom));
        assertTrue("Le clavier logiciel doit être visible",keyboardInset.get()>0);
        try(FileOutputStream output=new FileOutputStream(new File(folder,"with-keyboard.png"))) {
            getInstrumentation().getUiAutomation().takeScreenshot().compress(android.graphics.Bitmap.CompressFormat.PNG,100,output);
        }
        getInstrumentation().runOnMainSync(()->web.evaluateJavascript("JSON.stringify({viewportHeight:innerHeight,visualHeight:visualViewport.height,promptBottom:document.getElementById('prompt').getBoundingClientRect().bottom,headerTop:document.querySelector('.app-header').getBoundingClientRect().top,documentWidth:document.documentElement.scrollWidth,viewportWidth:innerWidth})",value->{android.os.Bundle report=new android.os.Bundle();report.putString("jarvis_layout",value);getInstrumentation().sendStatus(0,report);}));
        getInstrumentation().runOnMainSync(activity::finish);
    }

}
