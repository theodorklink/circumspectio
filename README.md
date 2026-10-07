# Circumspectio – Einrichtung

*Circumspectio* (lat.): Umsicht, das Ringsum-Schauen, das Abwägen von allen Seiten.

Jeden Morgen um 7:00 Uhr (Berlin) recherchiert Claude (Sonnet 5.5, Effort „high“) per Websuche die Nachrichtenlage, schreibt das Briefing und SendGrid stellt es zu. Alles läuft als GitHub Action, ohne eigenen Server.

## Was im Repository liegt

| Datei | Zweck |
|---|---|
| `.github/workflows/circumspectio.yml` | Zeitplan und Ablauf in GitHub Actions |
| `briefing.py` | Recherche über die Claude API, Linkprüfung, Bilder, Diagramme, Versand |
| `prompt.md` | Redaktionsanweisung an Claude: Rubriken, Quellen, Haltung. Hier ändern Sie den Inhalt. |
| `template.html.j2` | Gestaltung der Mail (Times New Roman, Zeitungslayout). Hier ändern Sie das Aussehen. |
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
| `SEND_HOUR` | `7` | Zustellstunde (Berlin) |
| `SENDGRID_API_HOST` | `https://api.sendgrid.com` | EU-Konten: `https://api.eu.sendgrid.com` |

## Schritt 5: Testen

1. Reiter **Actions**. Falls GitHub fragt, Workflows aktivieren.
2. Links **Circumspectio** wählen → **Run workflow** → Häkchen bei „Nur erzeugen, nicht senden“ → **Run workflow**.
3. Nach 5 bis 15 Minuten ist der Lauf grün. Unten auf der Lauf-Seite unter **Artifacts** die ZIP-Datei laden und `circumspectio.html` im Browser öffnen.
4. Gefällt das Ergebnis: denselben Ablauf ohne Häkchen starten. Manuelle Läufe werden sofort verschickt.

Ab jetzt läuft es täglich von selbst.

## So funktioniert der Zeitplan

GitHub rechnet in UTC und kennt keine Sommerzeit. Der Workflow startet deshalb zweimal (04:17 und 05:17 UTC). Das Skript erkennt, welcher Lauf heute eine Stunde vor 7 Uhr Berliner Zeit liegt, und beendet den anderen nach wenigen Sekunden. Das fertige Briefing wird bei SendGrid auf genau 7:00 Uhr terminiert. GitHub startet geplante Läufe manchmal mit Verzögerung; der Puffer von rund 40 Minuten fängt das ab. Ist das Briefing erst nach 7 Uhr fertig, geht es sofort raus.

Für eine andere Uhrzeit, z. B. 6 Uhr: `SEND_HOUR` auf `6` setzen und in der Workflow-Datei beide Cron-Stunden um eins verringern (`17 3` und `17 4`).

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
- **Layout testen ohne Kosten** (lokal, Python 3.11+):
  ```
  pip install -r requirements.txt
  python briefing.py --aus-json beispiel.json --dry-run
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
