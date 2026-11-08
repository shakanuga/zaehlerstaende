# Zählerstand

Zählerstände mit Foto erfassen, für die Familie einsehbar auswerten und gegenüber dem Anbieter belegen.

## Installation auf Unraid

Bei jedem Push auf `main` baut GitHub das Image `ghcr.io/shakanuga/zaehlerstaende:latest`.

In Unraid unter Docker, **Add Container** eintragen:

| Feld | Wert |
|---|---|
| Name | `zaehlerstand` |
| Repository | `ghcr.io/shakanuga/zaehlerstaende:latest` |
| Icon URL | `https://raw.githubusercontent.com/shakanuga/zaehlerstaende/main/static/icon-512.png` |
| Network Type | `br0` oder ein eigenes Netz |
| Fixed IP | eine freie Adresse im Heimnetz |
| Pfad `/data` | `/mnt/user/appdata/zaehlerstand` |
| Pfad `/import` (read-only) | `/mnt/user/appdata/zaehlerstand-import` |
| Variable `TZ` | `Europe/Berlin` |

Der Datenordner muss dem Container gehören:

```bash
mkdir -p /mnt/user/appdata/zaehlerstand /mnt/user/appdata/zaehlerstand-import
chown -R 99:100 /mnt/user/appdata/zaehlerstand
```

Die App lauscht auf Port `8080`. Für eine eigene Adresse einen Proxy Host im Reverse Proxy anlegen.
Keine Portfreigabe einrichten, die App ist fürs Heimnetz gedacht.

Der erste Aufruf legt das Admin-Konto an. Bitte direkt nach dem Start erledigen, denn bis dahin kann
das jeder im Netz.

## Anmeldung mit Pocket ID

Optional. Bestehende Konten werden beim ersten Login über den **Benutzernamen** gefunden (Groß- und Kleinschreibung egal) und danach fest verknüpft. Gibt es noch gar kein Konto, wird das erste Pocket-ID-Konto Admin.

1. In Pocket ID einen OIDC-Client `Zählerstände` anlegen, Callback-URL `https://zaehler.example.de/auth/pocketid/zurueck`.
2. Am Container setzen:

| Variable | Wert |
|---|---|
| `OIDC_ISSUER` | Adresse von Pocket ID, z. B. `https://id.example.de` |
| `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | aus Pocket ID |
| `OIDC_LABEL` | optional, Text auf dem Knopf |
| `OIDC_AUTO_REDIRECT` | `1` = Anmeldeseite überspringen |
| `OIDC_DISABLE_PASSWORD` | `1` = nur noch Pocket ID |
| `OIDC_AUTO_CREATE` | `1` = unbekannte Nutzer als Mitglied ohne Eintragsrecht anlegen |
| `OIDC_ALLOWED_GROUPS` | optional, nur diese Pocket-ID-Gruppen dürfen rein |
| `OIDC_ADMIN_GROUPS` | optional, neue Konten aus diesen Gruppen werden Admin |
| `OIDC_REDIRECT_URI` | optional, falls die Rücksprung-Adresse falsch gebildet wird |

## Erste Schritte

1. **Konten:** Unter Mehr, Verwaltung, Konten die Familie anlegen. Familienkonten sehen private
   Zähler nicht. Wer ablesen soll, bekommt den Haken bei „Eintragen“.
2. **Alte Liste übernehmen:** Fotos aus der bisherigen Ablage nach
   `/mnt/user/appdata/zaehlerstand-import` kopieren (Unterordner sind in Ordnung), dann unter
   Verwaltung, Excel übernehmen die `.xlsx` wählen. Die Vorschau zeigt, was übernommen wird und
   welche Fotos fehlen. Erkannt werden im Blatt eingebettete Bilder, Links und Dateinamen.
3. **Handy:** Seite öffnen und zum Startbildschirm hinzufügen.

## Stand aus dem Foto lesen (optional)

Ohne Einstellung tippst du den Stand ein, das Foto steht dabei groß darüber. Mit einer der beiden
Varianten wird der Stand vorausgefüllt. Prüfen und speichern musst du weiterhin selbst.

Als Variablen im Container eintragen. Über die Claude API (eigener API-Schlüssel, Kosten je Foto, das Foto verlässt das Haus):

```
OCR_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
```

Über Ollama (bleibt im Haus, braucht ein Vision-Modell und Rechenleistung):

```
OCR_PROVIDER=ollama
OLLAMA_URL=http://ollama-host:11434
OLLAMA_MODEL=...
```

## Aktualisieren

In Unraid beim Container **Force Update** wählen. Die Daten liegen außerhalb des Containers und bleiben erhalten.

## Daten und Sicherung

Alles liegt in `/mnt/user/appdata/zaehlerstand`: Datenbank `zaehler.sqlite3`, Originalfotos in
`photos/`, Vorschauen in `derived/`. Ein Appdata-Backup erfasst den Ordner mit. Weil die Fotos der
Nachweis sind, lohnt sich zusätzlich eine Kopie außer Haus.

## So rechnet die Statistik

Die Differenz zwischen zwei Ablesungen wird gleichmäßig auf die Tage dazwischen verteilt und dann zu
Monaten und Jahren summiert. Monatswerte sind deshalb rechnerische Werte, die Differenz im Verlauf und
im PDF ist die echte Differenz zwischen zwei Ablesungen. Wird ein Zähler getauscht, beim ersten Stand
des neuen Zählers „Zähler wurde getauscht“ ankreuzen.

## Entwicklung

```bash
pip install -r requirements.txt pytest
python -m pytest tests
ZAEHLER_DATA=./data ZAEHLER_IMPORT=./import PORT=8080 python run.py
```

Schriften: TeX Gyre Heros Condensed (GUST Font License), DejaVu (DejaVu Fonts License).
