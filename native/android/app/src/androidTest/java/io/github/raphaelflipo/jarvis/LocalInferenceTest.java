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
            WebView web=(WebView)((ViewGroup)activity.findViewById(android.R.id.content)).getChildAt(0);
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
}
