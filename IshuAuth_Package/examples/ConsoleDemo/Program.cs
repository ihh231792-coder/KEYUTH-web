using System;
using ISHU_Auth;

class Program
{
    // SAME style as KeyAuth — name / ownerid / secret / version, no API key.
    // Get Owner ID + Secret from: panel -> Install page.
    private static readonly api KeyAuthApp = new api(
        name:    "APP-1LHEK3",
        ownerid: "IHH231792GMAILCOM-OFPDR",
        secret:  "SEC_fV0a-6poU-U6sp-xmAN-Wimi-j3ZF-D2HE-d5Hh",
        version: "1.0"
    );

    static void Main(string[] args)
    {
        if (args.Length > 0 && args[0] == "--full")
        {
            FullControl();
            return;
        }

        if (args.Length > 0 && args[0] == "--license")
        {
            string lk = args.Length > 1 ? args[1] : "";
            Console.WriteLine("Server : " + api.Server);
            Console.WriteLine("App    : " + KeyAuthApp.name + " v" + KeyAuthApp.version);
            Console.Write("init() ");
            KeyAuthApp.init();
            Console.WriteLine(KeyAuthApp.response.success ? "OK" : "FAIL: " + KeyAuthApp.response.message);
            Console.Write("license(" + lk + ") ");
            KeyAuthApp.license(lk);
            Console.WriteLine(KeyAuthApp.response.success
                ? "=> LOGIN OK @ " + KeyAuthApp.response.expiry
                : "=> DENIED: " + KeyAuthApp.response.message);
            return;
        }

        string user = args.Length > 0 ? args[0] : "username";
        string pass = args.Length > 1 ? args[1] : "password";

        Console.WriteLine("Server : " + api.Server);
        Console.WriteLine("App    : " + KeyAuthApp.name + " v" + KeyAuthApp.version);

        Console.Write("init() ");
        KeyAuthApp.init();
        Console.WriteLine(KeyAuthApp.response.success ? "OK" : "FAIL: " + KeyAuthApp.response.message);

        Console.Write("login(" + user + ") ");
        KeyAuthApp.login(user, pass);
        Console.WriteLine(KeyAuthApp.response.success
            ? "=> LOGIN OK @ " + KeyAuthApp.response.expiry
            : "=> DENIED: " + KeyAuthApp.response.message);

        return;
    }

    // Full control demo: create -> login -> ban -> unban -> login -> delete
    static void FullControl()
    {
        KeyAuthApp.init();
        Console.WriteLine("Server : " + api.Server);
        Console.WriteLine("App    : " + KeyAuthApp.name + " (ownerid " + KeyAuthApp.ownerid + ")");

        string u = "ctl" + Environment.TickCount.ToString("X");

        Console.Write("create(" + u + ") ");
        var c = KeyAuthApp.Create(u, "pass123", "30d");
        Console.WriteLine(c.ok ? "OK id=" + c.id : "FAIL: " + c.message);
        string id = c.id;

        Console.Write("login(" + u + ") ");
        KeyAuthApp.login(u, "pass123");
        Console.WriteLine(KeyAuthApp.response.success ? "LOGIN OK @ " + KeyAuthApp.response.expiry : "DENIED: " + KeyAuthApp.response.message);

        Console.Write("ban(" + u + ") ");
        KeyAuthApp.Ban(id, true);
        Console.WriteLine(KeyAuthApp.response.message);

        Console.Write("login(" + u + ") again ");
        KeyAuthApp.login(u, "pass123");
        Console.WriteLine(KeyAuthApp.response.success ? "OK (UNEXPECTED)" : "DENIED: " + KeyAuthApp.response.message);

        Console.Write("unban(" + u + ") ");
        KeyAuthApp.Ban(id, false);
        Console.WriteLine(KeyAuthApp.response.message);

        Console.Write("delete(" + u + ") ");
        var d = KeyAuthApp.Delete(id);
        Console.WriteLine(d.ok ? "DELETED" : "FAIL: " + d.message);

        Console.Write("login(" + u + ") after delete ");
        KeyAuthApp.login(u, "pass123");
        Console.WriteLine(KeyAuthApp.response.success ? "OK (UNEXPECTED)" : "DENIED: " + KeyAuthApp.response.message);

        Console.Write("CreateKey(7d) ");
        string lk = KeyAuthApp.CreateKey("7d");
        Console.WriteLine(lk.Length > 0 ? lk : "FAIL");
        if (lk.Length > 0)
        {
            Console.Write("license(" + lk + ") ");
            KeyAuthApp.license(lk);
            Console.WriteLine(KeyAuthApp.response.success ? "LOGIN OK @ " + KeyAuthApp.response.expiry : "DENIED: " + KeyAuthApp.response.message);
        }

        Console.WriteLine("== FULL CONTROL OK ==");
    }
}