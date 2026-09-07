// =============================================================
//   ISHU AUTH - SDK (C#)  KEYAUTH-STYLE CLASS
//   Drop this one file into your project. No package needed.
// -------------------------------------------------------------
//   USE (same way you use KeyAuth):
//     public static api KeyAuthApp = new api(
//         name:    "APP-XXXXXX",       // your app id or app name
//         ownerid: "YOUR-OWNER-ID",    // panel: Install -> Owner ID
//         secret:  "SEC-............", // panel: Install -> Secret ID
//         version: "1.0"
//     );
//
//     KeyAuthApp.init();                                    // session
//     KeyAuthApp.login(username, password);                 // login
//     if (KeyAuthApp.response.success)  { /* unlocked */ }
//     else MessageBox.Show("DENIED: " + KeyAuthApp.response.message);
//
//   Server is already set to the ISHU AUTH cloud below.
//   To run on your own server just change:  api.Server = "http://ip:3000";
// =============================================================

using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text.RegularExpressions;
using System.Threading.Tasks;

namespace ISHU_Auth
{
    public class api
    {
        public string name, ownerid, secret, version;

        /// <summary>ISHU AUTH server — default is the live cloud.
        /// Change this if you host server.py yourself.</summary>
        public static string Server = "https://keyuth-web.onrender.com";

        /// <summary>Last call's result (like KeyAuth's response).</summary>
        public data response = new data();

        public api(string name, string ownerid, string secret, string version)
        {
            this.name = name;
            this.ownerid = ownerid;
            this.secret = secret;
            this.version = version;
        }

        // ---------- init : validate app + secret ----------
        public void init()
        {
            response = Call("/api/init", new Dictionary<string, string>
            {
                ["name"] = name, ["ownerid"] = ownerid, ["secret"] = secret, ["version"] = version
            });
        }

        // ---------- login : username + password ----------
        public void login(string username, string password)
        {
            response = Call("/api/verify", new Dictionary<string, string>
            {
                ["name"] = name, ["ownerid"] = ownerid, ["secret"] = secret, ["version"] = version,
                ["user"] = username, ["pass"] = password, ["hwid"] = Fingerprint()
            });
        }

        // ---------- license key login (key-only projects) ----------
        public void license(string key)
        {
            response = Call("/api/verify", new Dictionary<string, string>
            {
                ["name"] = name, ["ownerid"] = ownerid, ["secret"] = secret, ["version"] = version,
                ["user"] = key, ["pass"] = key, ["hwid"] = Fingerprint()
            });
        }

        // ---------- internals ----------
        static readonly HttpClient _http = new HttpClient { Timeout = TimeSpan.FromSeconds(15) };

        static data Call(string path, Dictionary<string, string> fields)
        {
            try
            {
                using var content = new FormUrlEncodedContent(fields);
                var res = _http.PostAsync(Server + path, content).GetAwaiter().GetResult();
                string json = res.Content.ReadAsStringAsync().GetAwaiter().GetResult();
                return new data
                {
                    success = Regex.IsMatch(json, "\"success\"\\s*:\\s*true"),
                    ok = Regex.IsMatch(json, "\"ok\"\\s*:\\s*true"),
                    message = GrabField(json, "message"),
                    username = GrabField(json, "username"),
                    expiry = GrabField(json, "expires"),
                    appid = GrabField(json, "appid")
                };
            }
            catch (Exception ex)
            {
                return new data { success = false, message = "server unreachable: " + ex.Message };
            }
        }

        static string GrabField(string json, string field)
        {
            var m = Regex.Match(json, "\"" + Regex.Escape(field) + "\"\\s*:\\s*\"(.*?)\"");
            return m.Success ? m.Groups[1].Value : "";
        }

        /// <summary>Works like KeyAuth's HWID fingerprint (machine GUID hash).</summary>
        public static string Fingerprint()
        {
            try
            {
                var guid = Microsoft.Win32.Registry.GetValue(
                    @"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography",
                    "MachineGuid", "")?.ToString() ?? "";
                return guid.Length > 0 ? guid.GetHashCode().ToString("X8") : "ISHU-DEFAULT";
            }
            catch { return "ISHU-DEFAULT"; }
        }
    }

    /// <summary>Result of the last api call (success / message / ...).</summary>
    public class data
    {
        public bool success { get; set; }
        public bool ok { get; set; }
        public string message { get; set; } = "";
        public string username { get; set; } = "";
        public string expiry { get; set; } = "";
        public string appid { get; set; } = "";
    }
}