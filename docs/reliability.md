# Zeitliche Zuverlässigkeit und Betrieb

## Befund am 18. Oktober 2026

Live gelesen: Workflow, Skript und Actions-REST-API einschließlich Jobs und Artefakten. Beide untersuchten Läufe verwendeten Commit `c1126e69254a4215b4faccc3c629c1d1cacf123c`.

| Lauf | Soll laut alter Konfiguration | Tatsächlicher Start | Ergebnis |
|---|---|---|---|
| [39113055446](https://github.com/theodorklink/circumspectio/actions/runs/39113055446) | 04:17 UTC, 06:17 Berlin | 08:51:20 UTC, 10:51:20 Berlin | Briefing-Schritt bis 08:56:07 UTC, Artefakt ab 08:56:08 UTC |
| [39116236351](https://github.com/theodorklink/circumspectio/actions/runs/39116236351) | 05:17 UTC, 07:17 Berlin | 09:40:06 UTC, 11:40:06 Berlin | Grün, kein Ausgabe-Artefakt |

Die Soll-Zuordnung folgt aus der Reihenfolge und dem Verhalten der alten Sommerzeitprüfung. Das Run-Objekt selbst enthält den auslösenden Cron-Ausdruck nicht. Beim ersten Lauf entspricht das einer Abweichung von 4 Stunden 34 Minuten, beim zweiten von 4 Stunden 23 Minuten. `created_at` und `run_started_at` sind jeweils identisch. Die sichtbare Verzögerung liegt also bereits vor der Erzeugung des Run-Objekts, nicht in einer mehrstündigen Wartezeit des bereits angelegten Jobs. Die genaue interne GitHub-Ursache lässt sich aus diesen Daten nicht bestimmen.

Am 18. Oktober gilt UTC+2. Die alte Offset-Auswahl war für diesen Tag richtig. Sie wählte nur den Cron um 04:17 UTC, unabhängig von dessen tatsächlicher Startzeit. Der zweite Lauf wurde vom Skript absichtlich übersprungen. Grün bedeutete deshalb weder erzeugte Ausgabe noch nachgewiesene Zustellung. Die historische Run-Liste zeigt weitere verspätete Starts. Das Problem ist kein isolierter DST-Fehler.

Zusätzliche Schwachstellen der alten Fassung:

* `senden()` verglich die Zielzeit mit dem zu Beginn der Recherche erfassten `now`. Dauert die Recherche bis nach 07:00 Uhr, konnte `send_at` bereits in der Vergangenheit liegen.
* `concurrency` serialisierte Jobs, schützte aber nicht vor erneutem Versand bei einem späteren oder manuell wiederholten Lauf.
* Ein SendGrid-Timeout ließ offen, ob die Mail bereits angenommen wurde. Blindes Wiederholen konnte doppelt senden.
* Ein Dry-Run ohne JSON rief Claude auf und verursachte Kosten. JSON-Layouttests luden außerdem externe Bilder herunter.
* Das Artefakt enthielt keine dauerhafte, maschinenlesbare Annahmequittung.

Für den historischen Versand wurde SendGrid nicht aufgerufen. Die tatsächliche Zustellung und deren Zeitpunkt bleiben ungeprüft. Artefakt und grüner Run ersetzen diesen Nachweis nicht.

## Architekturentscheidung

| Variante | Bewertung |
|---|---|
| Früherer Actions-Cron | Mehr Puffer, aber weiterhin mögliche Verzögerungen und ausgelassene Läufe |
| Externer Scheduler ruft Actions auf | Vermeidet den Actions-Cron, bleibt von Runner-Verfügbarkeit abhängig |
| Unabhängiger Worker mit lokalem Zeitgeber | Empfohlen. Direkte Ausführung um 05:17 Berlin mit 103 Minuten Vorlauf und SendGrid-Terminierung |

Diese Änderung liefert die sichere Übergangslösung und installierbare systemd-Units. Sie stellt keinen Server bereit und aktiviert keinen neuen externen Dienst. Der Worker benötigt weiter funktionierende Netzverbindungen, GitHub für das gemeinsame Journal, Claude und SendGrid. Bei höheren Anforderungen eignen sich ein verwalteter Scheduler mit direkt ausgeführtem Worker und eine transaktionale Datenbank. Die Zustandslogik darf dabei nicht durch einen flüchtigen Cache ersetzt werden.

Aktuell wird pro Berliner Datum genau ein Produktionsversuch automatisch zugelassen. Das bevorzugt die Vermeidung doppelter Mails gegenüber einer blinden Wiederholung. Ohne eine providerseitige Idempotenzgarantie lässt sich bei verlorener HTTP-Antwort kein exakt einmaliger Versand garantieren.

## Gemeinsamer Tagesstatus

`delivery/YYYY-MM-DD.json` auf Branch `circumspectio-state` enthält Zeitstempel, Run-ID, Status, Zielzeit, Verspätung und nach HTTP 202 die `X-Message-Id`. Es enthält keine Newsletter-Inhalte, Adressen oder Schlüssel. In diesem öffentlichen Repository sind auch diese Metadaten öffentlich. Status und Issue-Datum werden außerdem als `custom_args.circumspectio_date` an SendGrid übergeben.

| Status | Bedeutung und Wiederanlauf |
|---|---|
| `generating` | Tagesanspruch angelegt. Bei abgebrochenem Worker erst prüfen, ob er noch läuft |
| `failed_before_send` | Vor dem eigentlichen SendGrid-Aufruf gescheitert. Explizit mit `--retry-failed` erneut versuchen, dabei entstehen erneut Recherchekosten |
| `sending` | Versandabsicht dauerhaft gespeichert. Nach Prozessabbruch ist die Annahme ungeklärt |
| `unknown` | Versandversuch oder Statusspeicherung nach dem Versand gescheitert. Kein automatischer Retry |
| `accepted` | SendGrid hat HTTP 202 geliefert. Kein Beleg für tatsächliche Zustellung |

Die erstmalige Dateierstellung ist atomar. Updates verwenden die von GitHub gelesene Blob-SHA als Vergleichswert. Konflikte oder nicht lesbarer Status stoppen den Worker vor dem nächsten externen Effekt. Die Actions-Gruppe verhindert zusätzlich parallele reguläre Actions-Läufe. Der Status schützt auch konkurrierende externe Worker und manuelle Wiederholungen. Ein Anspruch läuft niemals automatisch ab.

`out/status.json`, Actions-Job-Zusammenfassung und Journal machen auch `outside_window` sowie unterdrückte Wiederholungen sichtbar. Bei einem Ausfall vor der Statusspeicherung kann das lokale Artefakt fehlen. Der unabhängige Deadline-Check erkennt dann die fehlende Annahme. `accepted` wird bei unterdrückten Duplikaten nicht überschrieben.

### Unklaren Versand klären

1. Aktive Worker stoppen und in Actions prüfen, ob noch ein Lauf arbeitet.
2. Tagesstatus und `message_id` sichern. In SendGrid Activity nach Datum, Empfänger und Nachrichten-ID suchen. Bei vorhandener Event-Webhook-Speicherung zusätzlich `circumspectio_date` abgleichen.
3. Bei bestätigter Annahme nicht erneut senden. Das Journal nach gesicherter Prüfung auf `accepted` vervollständigen.
4. Nur wenn eine Annahme ausgeschlossen werden kann, den Status kontrolliert auf `failed_before_send` ändern und `python daily.py --live --retry-failed` starten. Innerhalb von 05:00 bis 12:00 Berlin. Bei unklarer Beweislage bleibt die Sperre bestehen.

Keinen Status blind löschen. Ein leerer Status würde erneut kostenpflichtige Recherche und Versand erlauben. Keine automatischen Restarts des Produktionsdienstes konfigurieren.

## Unabhängiger Zeitgeber

Voraussetzung ist ein dauerhaft eingeschalteter Linux-Host mit systemd, Zeitsynchronisierung, Python 3.12 und Internetzugang. Keine bloße Weiterleitung an einen GitHub-Workflow.

1. Repository in `/opt/circumspectio` auschecken. Dienstkonto `circumspectio` ohne Login anlegen. Code nur für Administratoren schreibbar halten.
2. Virtuelle Umgebung `/opt/circumspectio/.venv` anlegen und `pip install -r requirements.txt` ausführen. Optional `fonts-liberation` installieren.
3. `/opt/circumspectio/out` anlegen und dem Dienstkonto als einziges beschreibbares Projektverzeichnis geben.
4. `deploy/circumspectio.env.example` nach `/etc/circumspectio.env` kopieren, echte Werte eintragen und mit `chmod 600` schützen. Fine-grained GitHub-Token ausschließlich für dieses Repository mit Contents read/write verwenden. Ein externer Worker erhält `GITHUB_TOKEN` nicht automatisch.
5. Vor Produktion Offline-Tests und Layouttest aus der README ausführen. Für diese Tests keine Secrets setzen.
6. Die vier `.service` und `.timer` aus `deploy/` nach `/etc/systemd/system/` kopieren. Die Zeitpläne mit `systemd-analyze calendar '*-*-* 05:17:00 Europe/Berlin'` prüfen. `systemd-analyze verify` mit den installierten Pfaden ausführen.
7. Bestehende Actions-Läufe vollständig beenden lassen. Den alten Versandstatus des Umschalttages in SendGrid prüfen. Die Migration vorzugsweise nach dem letzten Tagesversand durchführen und den neuen Timer erst für den Folgetag aktivieren. Alte Läufe vor diesem PR verwenden noch kein Journal und könnten sonst doppelt senden.
8. Actions-Crons aus `.github/workflows/circumspectio.yml` entfernen, `workflow_dispatch` für Offline-Tests erhalten. Das muss im Standardbranch geschehen.
9. `sudo systemctl daemon-reload` und anschließend `sudo systemctl enable --now circumspectio.timer circumspectio-check.timer` ausführen. Achtung: `Persistent=true` kann beim Aktivieren einen verpassten Termin sofort nachholen. Deshalb Schritt 7 zuerst abschließen. Der Worker blockiert außerhalb des erlaubten Tagesfensters.
10. Mit `systemctl list-timers 'circumspectio*'` die nächsten Termine prüfen. Mit `journalctl -u circumspectio.service` die Ausführung nachvollziehen. Laufende Dienste werden durch einen zweiten Timertermin nicht parallel gestartet.

Die Kalender verwenden ausdrücklich `Europe/Berlin`. Sowohl am 29. März 2026 als auch am 25. Oktober 2026 gibt es 05:17 und 07:00 Uhr eindeutig. `zoneinfo` und der lokale systemd-Kalender berücksichtigen die jeweilige UTC-Abweichung. Die Backup-Auslösung um 06:17 prüft nur den Tagesstatus, wenn der erste Lauf bereits erfolgreich war. Sie wiederholt keine fehlerhafte oder ungeklärte Recherche automatisch.

Bei Änderung von `SEND_HOUR` müssen Vorbereitungszeiten, Actions-Crons und Prüfzeiten gemeinsam geändert werden. Die gelieferten Units sind auf 07:00 Uhr ausgelegt.

## Verspätung und Ausfälle erkennen

* **06:50 Berlin:** `daily.py --check` verlangt eine bereits bestätigte, auf 07:00 terminierte SendGrid-Annahme. Fehlender Status, laufende Recherche, Fehler, unklare Annahme und API-Ausfälle erzeugen einen Exitcode ungleich null.
* **07:05 Berlin:** Derselbe Check erkennt auch eine verspätete oder weiterhin fehlende Annahme. Er ruft weder Claude noch SendGrid auf und ändert das Journal nicht.
* **Versandlauf:** Tatsächliche Start-, Übergabe- und Zielzeit sowie `late_seconds` werden gespeichert. Verspätung erzeugt zusätzlich eine Actions-Warnung. Ein verspäteter Versand kann technisch erfolgreich sein, der Deadline-Check schlägt trotzdem fehl.
* **Host-Ausfall oder ausgefallener Timer:** Ein unabhängiger Dead-Man-Monitor muss das Ausbleiben des erfolgreichen Checks bemerken. Ein Check ausschließlich auf demselben Host oder ausschließlich in Actions kann den Ausfall seines eigenen Zeitgebers nicht zuverlässig melden.

Die mitgelieferten Units erzeugen prüfbare Exitcodes und Journal-Einträge. Aktive Benachrichtigungen sind noch nicht eingerichtet. Den Checkdienst mit dem vorhandenen Monitoring verbinden, einen externen Dead-Man-Termin um 06:50 mit etwa fünf Minuten Toleranz hinterlegen und dessen Alarmweg außerhalb dieses Newsletters testen. Auch Tokenablauf und deaktivierte Actions-Crons überwachen. Ein Actions-Fehleralarm allein entdeckt keinen niemals gestarteten Workflow.

## Annahme und Zustellung unterscheiden

Für eine Zustellkontrolle SendGrid Event Webhook für `processed`, `delivered`, `deferred`, `bounce` und `dropped` einrichten. Signaturen anhand des SendGrid-Public-Keys verifizieren, Events nach `sg_event_id` deduplizieren und pro Ausgabedatum und Empfänger speichern. Empfängeradressen gehören in einen privaten Speicher, nicht in das öffentliche GitHub-Journal.

Um etwa 07:10 sollte ein unabhängiger Monitor für jeden erwarteten Empfänger ein `delivered`-Event verlangen und Verzögerungen, Bounce oder fehlende Events melden. `delivered` belegt die Annahme durch den empfangenden Mailserver, nicht das Erscheinen im Posteingang oder das Lesen der Mail. Ein Webhook-Empfänger ist hier bewusst nicht öffentlich ausgerollt. Ohne eingerichteten Empfänger bleibt der Activity Feed die manuelle Prüfmöglichkeit.

## Validierung

Automatisierte Tests blockieren ausgehende Sockets und verwenden ausschließlich Fixture-Daten und gemockte API-Antworten. Sie prüfen Sommerzeit und Winterzeit einschließlich beider Umstellungstage 2026, echte Fertigstellungszeit, Mitternachtswechsel, Tagesfenster, Duplikate, Claim-Konflikte, Fehler vor dem Versand, unklare Versandantworten, fehlgeschlagene Statusspeicherung und Deadline-Checks. Der Offline-Layouttest rendert die vorhandene Beispielausgabe ohne Bildabrufe. PR-CI erhält keine Secrets und führt keinen Produktionslauf aus.

Kein realer SendGrid-POST, keine Claude-Recherche und kein produktiver Workflow-Dispatch gehören zur Validierung dieses PRs. Der neue Produktionsablauf wurde nicht live ausgelöst. Eine echte Zustellmessung muss nach geplanter Aktivierung im Betrieb erfolgen.

## Primärquellen

* [GitHub zu verzögerten und ausgelassenen Schedule-Events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
* [SendGrid Mail Send, HTTP 202 und send_at](https://www.twilio.com/docs/sendgrid/api-reference/mail-send/mail-send)
* [SendGrid Scheduling Parameters](https://www.twilio.com/docs/sendgrid/for-developers/sending-email/scheduling-parameters)
* [SendGrid Event Webhook und Signaturprüfung](https://www.twilio.com/docs/sendgrid/for-developers/tracking-events/twilio-sendgrid-event-webhook-overview)
* [systemd.timer: OnCalendar, AccuracySec und Persistent](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)
