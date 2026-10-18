# Circumspectio – Einrichtung

*Circumspectio* (lat.): Umsicht, das Ringsum-Schauen, das Abwägen von allen Seiten.

Ziel ist der morgendliche Versand um 07:00 Uhr in `Europe/Berlin`. Claude recherchiert vorher, SendGrid bekommt die fertige Ausgabe mit `send_at` für 07:00 Uhr. Weder GitHub Actions noch E-Mail-Zustellung garantieren eine genaue Ankunft im Posteingang. Für zuverlässigere Vorbereitung gibt es einen unabhängigen systemd-Zeitplan, siehe [Betrieb und Untersuchung](docs/reliability.md).

## Was im Repository liegt

| Datei | Zweck |
|---|---|
| `.github/workflows/circumspectio.yml` | Zeitplan und Ablauf in GitHub Actions |
| `briefing.py` | Recherche, Darstellung, SendGrid und sicherer Layouttest |
| `daily.py` | Produktionslauf mit dauerhaftem Tagesstatus, Versandkontrolle und Deadline-Check |
| `deploy/` | systemd-Zeitgeber und Statusprüfung außerhalb von GitHub Actions |
| `prompt.md` | Redaktionsanweisung an Claude: Rubriken, Quellen, Haltung. Hier ändern Sie den Inhalt. |
| `template.html.j2` | Gestaltung der Mail (Times New Roman, Zeitungslayout). Hier ändern Sie das Aussehen. |
| `assets/` | Logo (`logo.png`, `zeichen.png`) samt Vorlagen `logo.svg`, `zeichen.svg` und Erzeugungsskript |
| `beispiel.json` | Testdaten, um das Layout ohne API-Kosten anzusehen |
| `requirements.txt` | Python-Pakete |

## Schritt 1: Anthropic API-Schlüssel

1. Unter https://platform.claude.com anmelden (oder Konto anlegen) und Guthaben bzw. Zahlungsmethode hinterlegen.
2. **API Keys → Create Key**, Namen „circumspectio“ vergeben, Schlüssel kopieren (beginnt mit `sk-ant-`). Er wird nur einmal angezeigt.
3. Empfehlung: unter **Limits** ein monatliches Ausgabenlimit setzen.

## Schritt 2: SendGrid

1. Konto bei https://sendgrid.com anlegen. Hinweis: Das Gratisangebot ist inzwischen ein 60-Tage-Test mit 100 Mails pro Tag; danach brauchen Sie einen bezahlten Tarif (Essentials). Aktuelle Preise bitte auf der SendGrid-Seite prüfen.
2. **Absender bestätigen** (Settings → Sender Authentication):
   - **Empfohlen: Domain Authentication.** Wenn Sie eine eigene Domain haben (z. B. `ihrname.de`), legt SendGrid drei CNAME-Einträge fest, die Sie bei Ihrem Domain-Anbieter eintragen. Danach können Sie z. B. `circumspectio@ihrname.de` als Absender nutzen, und die Mail landet zuverlässig im Posteingang.
   - **Notlösung: Single Sender Verification.** Eine einzelne Adresse bestätigen. Achtung: Absender bei Gmail, GMX, web.de, T-Online usw. scheitern an deren DMARC-Regeln, die Mail landet dann im Spam oder wird abgewiesen. Eine Adresse auf eigener Domain funktioniert besser.
3. **API-Schlüssel**: Settings → API Keys → **Create API Key** → „Restricted Access“ → nur **Mail Send: Full Access** aktivieren → Schlüssel kopieren (beginnt mit `SG.`).
4. Falls Ihr Konto in der EU-Region angelegt ist, gilt der API-Host `https://api.eu.sendgrid.com` (siehe Schritt 4, Variablen).

## Schritt 3: GitHub-Repository anlegen

1. Auf https://github.com **New repository**, Name z. B. `circumspectio`, Sichtbarkeit **Private**. (Bei öffentlichen Repositories schaltet GitHub zeitgesteuerte Workflows nach 60 Tagen ohne Commit ab.)
2. Die Dateien hochladen: **Add file → Upload files**, den Inhalt des entpackten ZIP-Ordners in das Fenster ziehen, **Commit changes**.
   - Der Ordner `.github` ist auf dem Mac im Finder versteckt. Mit `Cmd + Shift + .` sichtbar machen, bevor Sie ihn hineinziehen.
   - Alternativ: **Add file → Create new file**, als Dateiname `.github/workflows/circumspectio.yml` eintippen (die Schrägstriche legen die Ordner an) und den Inhalt einfügen.
3. Prüfen: Im Repository muss der Pfad `.github/workflows/circumspectio.yml` existieren.
4. Falls Sie schon die frühere Fassung hochgeladen hatten: die alte Datei `.github/workflows/morgenlage.yml` löschen, sonst laufen beide Workflows und Sie erhalten jeden Morgen zwei Mails.

## Schritt 4: Schlüssel in GitHub hinterlegen

Repository → **Settings → Secrets and variables → Actions**.

Reiter **Secrets** → **New repository secret**, jeweils Name und Wert:

| Name | Wert |
|---|---|
| `ANTHROPIC_API_KEY` | Ihr Schlüssel `sk-ant-…` |
| `SENDGRID_API_KEY` | Ihr Schlüssel `SG.…` |
| `MAIL_FROM` | die in SendGrid bestätigte Absenderadresse |
| `MAIL_TO` | Ihre Empfängeradresse; mehrere mit Komma trennen |

Reiter **Variables** (alles optional, sonst gelten die Standardwerte):

| Name | Standard | Bedeutung |
|---|---|---|
| `CLAUDE_MODEL` | `claude-sonnet-5-5` | Neuestes Sonnet. Bei einem Nachfolgemodell nur hier ändern. |
| `CLAUDE_EFFORT` | `high` | `medium` ist schneller und günstiger, etwas weniger gründlich |
| `MAX_SEARCHES` | `25` | Höchstzahl Websuchen pro Ausgabe |
| `SEND_HOUR` | `7` | Versandziel (Berlin). Bei Änderung auch beide Zeitpläne und Prüfzeiten anpassen. |
| `SENDGRID_API_HOST` | `https://api.sendgrid.com` | EU-Konten: `https://api.eu.sendgrid.com` |

## Schritt 5: Sicher testen

1. **Actions → Circumspectio → Run workflow** öffnen.
2. „Offline-Layouttest“ aktiviert lassen. Der Standardtest verwendet `beispiel.json`, ruft Claude nicht auf, lädt keine Bilder herunter und versendet nichts.
3. Das HTML aus dem Ausgabe-Artefakt öffnen.
4. Echten Betrieb erst nach Prüfung der Konfiguration aktivieren. Das Abwählen des Layouttests erlaubt API-Kosten und echten Versand. Auch manuelle Produktionsläufe beachten den Tagesstatus und das Zeitfenster. Sie erzwingen keinen Sofortversand.

Automatisierte Tests ohne Netzwerk, API-Kosten und E-Mails:

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

## So funktioniert der Zeitplan

Die Actions-Crons laufen um 03:17 und 04:17 UTC. Im Sommer ist das 05:17 und 06:17 Berlin, im Winter 04:17 und 05:17 Berlin. `daily.py` lässt Vorbereitung von 05:00 bis 12:00 Berlin zu. Der erste zulässige Lauf legt vor der Recherche einen atomaren Tagesstatus auf dem separaten Branch `circumspectio-state` an. Weitere Läufe desselben Tages erzeugen keine zweite Ausgabe. Ein Fenster außerhalb dieser Zeiten wird sichtbar als `outside_window` protokolliert.

SendGrid wird mit der tatsächlichen Fertigstellungszeit verglichen. Vor 07:00 Uhr wird auf 07:00 Uhr terminiert, danach geht die Ausgabe sofort raus und wird als verspätet markiert. Nach Mitternacht wird eine am Vortag begonnene Ausgabe nicht mehr versendet. HTTP 202 bedeutet nur angenommen, nicht zugestellt.

**Actions bleibt eine Übergangslösung.** Der zusätzliche Puffer kann Verzögerungen abfangen, beseitigt sie aber nicht. Für möglichst zuverlässige Vorbereitung den [unabhängigen Zeitgeber einrichten](docs/reliability.md#unabhängiger-zeitgeber) und anschließend die Actions-Crons entfernen. Ein externer Aufruf von `workflow_dispatch` allein beseitigt Wartezeiten auf Actions-Runnern nicht.

Tagesstatus und Wiederanlauf, überwachte Deadlines sowie der Nachweis tatsächlicher Zustellung stehen in [docs/reliability.md](docs/reliability.md).

## Was das Skript für Qualität tut

- **Links:** Es bleiben nur URLs stehen, die Claude in diesem Lauf tatsächlich in Suchergebnissen gefunden hat oder die erreichbar sind. Erfundene Links fliegen raus (im Log sichtbar als „Link verworfen“).
- **Bilder:** Claude nennt passende Wikipedia-Artikel; das Skript lädt deren Hauptbild von Wikimedia Commons (freie Lizenzen) und bettet es direkt in die Mail ein. So erscheinen Bilder auch ohne „Bilder nachladen“.
- **Schaubilder:** Diagramme aus belegten Zahlen (als Bild in der Mail) und Akteurskarten „Wer will was?“ als HTML-Tabelle.
- **HTML-Datei:** Jede Mail enthält zusätzlich die komplette Ausgabe als HTML-Anhang. Das hilft, wenn Gmail lange Mails mit „Nachricht gekürzt“ abschneidet. Abschalten mit der Variable `HTML_ANHANG` = `false`.
- **Tracking aus:** Klick- und Öffnungstracking ist abgeschaltet. Links führen direkt zu FAZ, FT, WSJ usw., wo Sie mit Ihren Abos eingeloggt sind.
- **Archiv:** Jede Ausgabe (JSON und HTML) liegt 30 Tage als Artefakt beim jeweiligen Lauf.

## Anpassen

- **Inhalt, Rubriken, Quellen, Länge:** `prompt.md` bearbeiten. Beispiel: eine Rubrik „Märkte“ oder „Naher Osten“ ergänzen, Quellen hinzufügen, Umfang ändern. Neue Felder müssen auch ins Template.
- **Aussehen:** `template.html.j2`. Farben stehen oben in der Datei.
- **Logo:** liegt als Bild in `assets/`, weil Gmail und Outlook SVG- und CSS-Grafiken nicht zuverlässig anzeigen. Fehlt der Ordner, erscheint der Titel als Schrift. Das Monogramm und der Schriftzug sind in Cinzel gesetzt, einer frei lizenzierten Schrift nach römischen Inschriften (Lizenz in `assets/Cinzel-OFL.txt`).
- **Ausgabennummer:** zählt ab dem Datum in der Variable `AUSGABE_START` (Standard: 2026-10-07 = Nr. 1).
- **Layout testen ohne Kosten** (lokal, Python 3.11+):
  ```
  pip install -r requirements.txt
  python briefing.py --aus-json beispiel.json --dry-run --offline
  ```
  Ergebnis: `out/circumspectio.html`. Mit einer echten Ausgabe aus einem Artefakt (`briefing.json`) geht das genauso.

## Kosten

Pro Ausgabe fallen Token-Kosten für Claude Sonnet 5.5 sowie eine Gebühr pro Websuche an; die aktuellen Preise stehen auf https://claude.com/pricing. Größte Stellschrauben: `CLAUDE_EFFORT` auf `medium` und `MAX_SEARCHES` senken. Den tatsächlichen Verbrauch pro Lauf zeigt das Log („input=…, output=…, suchen=…“) und die Usage-Seite der Claude Console. GitHub Actions ist für private Repositories im Rahmen des Freikontingents (2.000 Minuten/Monat) ausreichend; ein Lauf braucht etwa 5 bis 15 Minuten.

## Fehlersuche

| Problem | Lösung |
|---|---|
| Mail kommt nicht an | Lauf in **Actions** öffnen, Log lesen. SendGrid → Activity Feed prüfen. Spam-Ordner prüfen. |
| Mail im Spam | Domain Authentication in SendGrid einrichten (Schritt 2). |
| `SendGrid-Fehler 403` | Absender nicht bestätigt oder `MAIL_FROM` weicht von der bestätigten Adresse ab. |
| `SendGrid-Fehler 401` | API-Schlüssel falsch oder ohne „Mail Send“-Recht. |
| `authentication_error` von Anthropic | `ANTHROPIC_API_KEY` prüfen, Guthaben prüfen. |
| `not_found_error` beim Modell | Modellnamen in der Variable `CLAUDE_MODEL` prüfen (Liste: https://docs.claude.com/en/docs/about-claude/models/overview). |
| Workflow startet nicht automatisch | Die Datei muss im Standard-Branch (`main`) liegen. Unter Actions prüfen, ob der Workflow aktiviert ist. |
| Gmail zeigt „Nachricht gekürzt“ | Auf „Gesamte Nachricht anzeigen“ tippen oder den HTML-Anhang öffnen. |
| Ein Link fehlt | Er wurde als nicht belegt verworfen. Das ist Absicht. |

## Hinweis zu Bezahlschranken

Das Briefing verlinkt immer auf die Originalartikel. Bei FAZ, FT, WSJ usw. öffnen Sie diese mit Ihren eigenen Abos. Umgehungsdienste für Bezahlschranken nutzt das Skript bewusst nicht.

