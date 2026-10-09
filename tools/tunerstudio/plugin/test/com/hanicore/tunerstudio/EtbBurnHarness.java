package com.hanicore.tunerstudio;
import java.io.*;
import java.lang.reflect.*;
import java.util.*;

/** Bench qualification through installed TunerStudio RS232 and plugin streams.
 * No automatic retry of Burn. Requests are paced exactly as the plugin permits.
 */
public final class EtbBurnHarness {
    static InputStream in;
    static OutputStream out;
    static int gap;
    static byte[] request(byte[] payload,int timeout) throws Exception {
        if(gap>0) Thread.sleep(gap);
        out.write(HcProtocol.tsRequest(payload));out.flush();
        ByteArrayOutputStream b=new ByteArrayOutputStream();
        long end=System.currentTimeMillis()+timeout;
        while(System.currentTimeMillis()<end) {
            int av=in.available();
            if(av<=0) {Thread.sleep(1);continue;}
            byte[] p=new byte[Math.min(av,512)];int n=in.read(p);
            if(n>0)b.write(p,0,n);
            byte[] raw=b.toByteArray(), response=HcProtocol.findTsResponse(raw,raw.length);
            if(response!=null) {
                if(response[0]!=0)throw new IOException("ECU response "+(response[0]&255));
                return Arrays.copyOfRange(response,1,response.length);
            }
        }
        throw new IOException("NO REPLY to "+(char)payload[0]+" after "+timeout+"ms; raw="+Arrays.toString(b.toByteArray()));
    }
    static int u(byte[] b,int x) {return (b[x]&255)*256+(b[x+1]&255);}
    static byte[] read(int off,int n,boolean page) throws Exception {
        return request(new byte[]{(byte)(page?'R':'O'),(byte)(off>>8),(byte)off,(byte)(n>>8),(byte)n},1500);
    }
    static void command(int procedure) throws Exception {request(new byte[]{'!','C',(byte)procedure},1500);}
    public static void main(String[] a) throws Exception {
        int burnGap=Integer.parseInt(a[1]);gap=30;int runs=Integer.parseInt(a[2]);
        ClassLoader cl=EtbBurnHarness.class.getClassLoader();
        Method mk=HaniCoreKLinePlugin.class.getDeclaredMethod("createConnectionProxy",ClassLoader.class);mk.setAccessible(true);
        Object conn=mk.invoke(null,cl);Class<?> f=Class.forName("A.f",false,cl);
        f.getMethod("a",String.class,Object.class).invoke(conn,"Com Port",a[0]);
        f.getMethod("a",String.class,Object.class).invoke(conn,"Baud Rate","115200");
        f.getMethod("f").invoke(conn);
        in=(InputStream)f.getMethod("i").invoke(conn);out=(OutputStream)f.getMethod("j").invoke(conn);
        try {
            System.out.println("IDENTITY "+new String(request(new byte[]{'V'},1500),"ISO-8859-1")+" burnGap="+burnGap);
            for(int run=0;run<runs;run++) {
                byte[] old=read(2493,1,true);int original=old[0]&255;
                int val=burnGap<0 ? original : (original+1)&255;
                command(6);long end=System.currentTimeMillis()+55000;int status=0;
                while(System.currentTimeMillis()<end) {
                    byte[] s=read(776,66,false);status=u(s,0);
                    if((status&15)==7 || (status&15)==3)break;
                }
                System.out.println("EXIT run="+run+" status="+status);System.out.flush();
                if((status&15)!=7)throw new IOException("Characterization did not complete");
                if(burnGap>=0)request(new byte[]{'W',9,(byte)189,(byte)val},1500);
                long t=System.currentTimeMillis();
                try {
                    gap=Math.max(0,burnGap);
                    request(new byte[]{'B'},8000);
                    gap=30;
                    System.out.println("BURN OK run="+run+" ms="+(System.currentTimeMillis()-t));
                } catch(Exception e) {
                    System.out.println("BURN FAILED run="+run+" "+e);System.out.flush();
                    // Inspect NVM after the timeout without resending B.
                    gap=30;byte[] nvm=read(430,12,false);
                    System.out.println("POST NVM state="+u(nvm,0)+" error="+u(nvm,2)+" generation="+u(nvm,6)+" commits="+u(nvm,8));
                    throw e;
                }
                if((read(2493,1,true)[0]&255)!=val)throw new IOException("RAM readback mismatch");
                byte[] nvm=read(430,12,false);
                System.out.println("POST NVM state="+u(nvm,0)+" error="+u(nvm,2)+" generation="+u(nvm,6)+" commits="+u(nvm,8));
                // Restore the harmless disabled-idle setting through normal Burn.
                if(burnGap>=0) {
                    request(new byte[]{'W',9,(byte)189,(byte)original},1500);
                    request(new byte[]{'B'},8000);
                }
                System.out.flush();
            }
        } finally {
            try{gap=30;command(0);}catch(Exception ignored){}
            for(Method m:f.getMethods()) if(m.getName().equals("g")&&m.getParameterTypes().length==0) {try{m.invoke(conn);}catch(Exception ignored){}break;}
        }
        System.exit(0);
    }
}
