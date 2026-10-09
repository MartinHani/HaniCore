package com.hanicore.tunerstudio;

import java.lang.reflect.Method;
import java.lang.reflect.Modifier;

/**
 * Does the INSTALLED TunerStudio still have every internal the plugin reaches
 * by reflection (HaniCoreKLinePlugin: obfuscated names from TunerStudio
 * 3.3.01)? Loads the classes WITHOUT initialising them. Run with
 * TunerStudioMS.jar and lib/jssc.jar on the class path.
 */
public final class TsCompatCheck {

    private static int bad = 0;

    private static Class<?> cls(String n) {
        try {
            return Class.forName(n, false, TsCompatCheck.class.getClassLoader());
        } catch (Throwable t) {
            System.out.println("  MISSING class " + n);
            bad++;
            return null;
        }
    }

    private static void method(Class<?> c, String name, boolean isStatic, Class<?>... args) {
        if (c == null) return;
        try {
            Method m = c.getMethod(name, args);
            if (Modifier.isStatic(m.getModifiers()) != isStatic) throw new NoSuchMethodException("static?");
            System.out.println("  ok " + c.getName() + "." + name + "/" + args.length);
        } catch (Throwable t) {
            System.out.println("  MISSING " + c.getName() + "." + name + "/" + args.length + " " + t);
            bad++;
        }
    }

    public static void main(String[] a) throws Exception {
        Class<?> provider = cls("A.i");          /* connection provider interface */
        Class<?> registry = cls("aV.w");         /* provider registry             */
        Class<?> desc = cls("A.q");              /* connection descriptor         */
        Class<?> conn = cls("A.f");              /* connection interface          */
        Class<?> rs232 = cls("aD.a");            /* TunerStudio's JSSC RS232      */
        cls("com.efiAnalytics.plugin.ApplicationPlugin");
        cls("jssc.SerialPort");
        method(registry, "c", true);
        method(registry, "a", true, provider);
        method(provider, "a", false);
        if (desc != null) {
            try { desc.getConstructor(); System.out.println("  ok A.q()"); }
            catch (Throwable t) { System.out.println("  MISSING A.q()"); bad++; }
        }
        method(desc, "a", false, String.class);
        method(desc, "b", false, String.class);
        method(desc, "a", false, provider);
        method(desc, "a", false);
        for (String m : new String[] { "f", "g", "h", "i", "j", "n", "r" }) method(conn, m, false);
        method(conn, "a", false, String.class, Object.class);
        method(conn, "a", false, String.class);
        if (rs232 != null) {
            try { rs232.getConstructor(); System.out.println("  ok aD.a()"); }
            catch (Throwable t) { System.out.println("  MISSING aD.a()"); bad++; }
            boolean port = false;       /* 2.1.0 recovery borrows TunerStudio's port */
            for (Class<?> c = rs232; c != null; c = c.getSuperclass()) {
                for (java.lang.reflect.Field f : c.getDeclaredFields()) {
                    if (f.getType().getName().equals("jssc.SerialPort")) port = true;
                }
            }
            System.out.println(port ? "  ok aD.a has a jssc.SerialPort field" : "  MISSING aD.a jssc.SerialPort field");
            if (!port) bad++;
            if (conn != null && !conn.isAssignableFrom(rs232)) {
                System.out.println("  aD.a is not an A.f"); bad++;
            }
        }
        System.out.println(bad == 0 ? "PASS: TunerStudio internals present" : "FAIL: " + bad + " missing");
        System.exit(bad == 0 ? 0 : 1);
    }
}
