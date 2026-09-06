ISHU AUTH - C# PACKAGE
======================
Author: ISHU

What's inside?
  IshuAuth.cs   -> main SDK (drop this into your project)
  Example.cs    -> full working example
  README.txt    -> this file

INSTALL (do you need any package? NO)
-------------------------------------
1. Run `python server.py` (on your PC or a VPS)
2. Log in to the panel -> copy the MASTER key from the API Keys page
3. Copy the App ID from the Applications page
4. Drop IshuAuth.cs into your C# project's source folder (next to the .sln)
5. Create a user + password or a license key from the Users page
6. Call Verify() in your app:

   var auth = new IshuAuth();
   auth.Server = "http://YOUR-SERVER:3000";   // wherever server.py runs
   auth.ApiKey = "ISHU_XXXX-....";
   auth.AppId  = "APP-XXXXXX";

   var r = await auth.Verify("user123", "pass123", "PC-FINGERPRINT");
   if (r.Success) Console.WriteLine("LOGIN OK @ " + r.Expires);
   else Console.WriteLine("DENIED: " + r.Message);

CONTROL (create/reset/renew/ban — same as the panel)
----------------------------------------------------
   await auth.Create("user2", "pass2", "30d", "user");
   await auth.ResetHwid(licenseId);
   await auth.Renew(licenseId, "7d");
   await auth.Ban(licenseId, true);

What is HWID?  The user's unique device fingerprint
(they can only log in from one PC/phone). Reset it from the panel,
then they can do a fresh login.

Android/APK?  Java needs no package - use HttpURLConnection
(see the notice in Example.cs). Flutter just uses the `http` package.

(c) Copyrighted by ISHU