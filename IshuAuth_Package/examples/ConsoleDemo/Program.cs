using System;
using ISHU_Auth;

class Program
{
    // SAME style as KeyAuth — name / ownerid / secret / version, no API key.
    // Get Owner ID + Secret from: panel -> Install page.
    private static readonly api KeyAuthApp = new api(
        name:    "APP-1LHEK3",
        ownerid: "IHH231792GMAILCOM-OFPDR",
        secret:  "SEC-4C9F-2DB1-B7EA-0F58-9A41-D2E6-7B08-C53A",
        version: "1.0"
    );

    static void Main(string[] args)
    {
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
}