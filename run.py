import os

from zaehler.app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    try:
        from waitress import serve
        # Hinter dem Nginx Proxy Manager: X-Forwarded-* übernehmen, damit die App weiß, dass sie über HTTPS läuft
        # (sonst bildet sie http-Adressen, z. B. für den Rücksprung von Pocket ID). Ohne trusted_proxy
        # entfernt waitress diese Kopfzeilen.
        serve(app, host="0.0.0.0", port=port, threads=8, trusted_proxy=os.environ.get("TRUSTED_PROXY", "*"),
              trusted_proxy_count=1, trusted_proxy_headers="x-forwarded-for x-forwarded-proto x-forwarded-host",
              clear_untrusted_proxy_headers=True)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
