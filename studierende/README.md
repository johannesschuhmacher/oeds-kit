# Arbeiten am OEDS – Studierendengruppe

Dieser Branch `studierende` ist der gemeinsame Stand der Studierendengruppe.
Hier entstehen eigene Crawler, Post-Run-Skripte und Auswertungen auf Basis des
Open Energy Data Server (OEDS). Fertige Crawler übernimmt die Betreuung später
nach `main`.

- Allgemeine Doku zum OEDS: <https://open-energy-data-server-kit.readthedocs.io>
- Welche Konten und API-Schlüssel ihr braucht: [zugaenge.md](zugaenge.md)
- Vorlage für eure Schlüsseldatei: [keys.env.example](keys.env.example)

## Die Gruppen-VM

Die Gruppe arbeitet zusammen auf einer VM im KIT-Netz:
`iip-vm-oeds-ext.iip.kit.edu`. Dort läuft ein OEDS mit den offenen Daten
(MaStR, ENTSO-E, SMARD, ENTSOG, Netztransparenz, Open-Meteo, Eurostat, DWD,
powerplantmatching, renewables.ninja, regelleistung.net, Trading Hub Europe, GIE,
EIA). Die Quellen ohne Schlüssel werden täglich aktualisiert.

**Anmelden:** mit eurem KIT-Konto per Remote-Desktop (RDP) oder SSH. Die
Freischaltung beantragt die Betreuung bei der IT. Außerhalb des KIT-Netzes
braucht ihr VPN.

**Gruppenordner:** `/srv/oeds-gruppe`. Alles darin können alle aus der Gruppe
lesen und ändern. Dort liegt dieses Repository unter `oeds-kit/`.

**Zugangsdaten der Gruppe:** in `/etc/oeds-gruppe.env` auf der VM. In jedem
neuen Terminal laden:

```bash
source /etc/oeds-gruppe.env
psql                       # SQL-Konsole der Datenbank
```

| Dienst | Adresse |
| --- | --- |
| Datenbank (PostgreSQL) | `localhost:6432`, Datenbank `opendata`, Nutzer `studierende` |
| Grafana | <http://iip-vm-oeds-ext.iip.kit.edu:3006>, Login `studierende` (Ansehen geht ohne Login) |
| PostgREST (nur lesen) | <http://localhost:3001> auf der VM |
| Crawler-Admin | <http://localhost:3010/admin>, nur im Browser auf der VM |

In Python:

```python
import pandas as pd
from sqlalchemy import create_engine

# Nutzer und Passwort kommen aus PGUSER/PGPASSWORD (source /etc/oeds-gruppe.env).
engine = create_engine("postgresql+psycopg2://localhost:6432/opendata")
pd.read_sql("select * from smard.prices limit 10", engine)
```

## Regeln

- **Offene Daten nur lesen.** Die Schemata der Crawler (`smard`, `mastr`, ...)
  sind schreibgeschützt.
- **Eigene Daten in eigene Schemata**, ein Schema pro Projekt oder Crawler,
  z. B. `create schema projekt_wind;`. Alles darin ist auch in Grafana und
  PostgREST lesbar.
- **Große Tabellen gezielt abfragen.** `entsoe_files` hat über 300 Mio. Zeilen;
  immer mit `where` auf Zeit und Gebiet.
- **Keine Passwörter und Schlüssel in Git**, in Notebooks oder im
  Gruppenordner. Eure eigenen Schlüssel liegen in `~/.oeds-keys.env` in eurem
  Home-Verzeichnis (siehe [zugaenge.md](zugaenge.md)).
- **Den Zeitplan des Servers ändert die Betreuung.** Ihr startet eure Crawler
  selbst (siehe unten). Läuft ein Crawler stabil, nehmen wir ihn in den
  Serverbetrieb auf.

## Arbeiten mit Git

```text
main            stabiler Stand, nur die Betreuung merged hierhin
└── studierende gemeinsamer Stand der Gruppe (dieser Branch)
    ├── stud-wind       ein Branch pro Projekt
    └── stud-gasfluss
```

1. **Einmalig:** GitHub-Konto anlegen und der Betreuung den Nutzernamen
   schicken; ihr bekommt Schreibrechte auf das Repository. Auf der VM einen
   SSH-Schlüssel erzeugen und bei GitHub eintragen
   (<https://github.com/settings/keys>):

   ```bash
   ssh-keygen -t ed25519
   cat ~/.ssh/id_ed25519.pub
   git config --global user.name "Vorname Nachname"
   git config --global user.email "vorname.nachname@student.kit.edu"
   ```

2. **Projekt anlegen:** Der Ordner `/srv/oeds-gruppe/oeds-kit` bleibt auf
   `studierende`. Jedes Projekt bekommt einen eigenen Arbeitsordner
   (Git-Worktree), damit ihr euch nicht gegenseitig den Branch wechselt:

   ```bash
   cd /srv/oeds-gruppe/oeds-kit
   git pull
   git worktree add ../projekte/wind -b stud-wind studierende
   cd ../projekte/wind
   uv sync --all-packages --python 3.13
   ```

3. **Arbeiten, committen, pushen:**

   ```bash
   git add -A && git commit -m "Wind-Crawler: erste Version"
   git push -u origin stud-wind
   ```

4. **Zusammenführen:** Auf GitHub einen Pull Request von `stud-wind` nach
   `studierende` öffnen. Eine zweite Person aus der Gruppe schaut drüber und
   merged. Die Tests müssen grün sein.

## Eigener Crawler

Ein Crawler lädt eine Quelle in ein eigenes Schema. Gute Vorlagen sind kleine
Crawler wie `packages/crawler-pack/src/crawler/dwd_cdc.py` oder
`renewables_ninja.py`. Die Doku jedes Crawlers liegt unter `docs/crawlers/`.

1. Datei `packages/crawler-pack/src/crawler/<name>.py` mit einer Klasse, die
   von `KitCrawler` erbt und `run()` umsetzt.
2. In `packages/crawler-pack/pyproject.toml` unter
   `[project.entry-points."oeds.crawlers"]` eintragen, z. B.
   `wind_projekt = "crawler.wind_projekt:WindProjektCrawler"`, und danach
   `uv sync --all-packages` wiederholen.
3. Eine eigene Konfiguration im Projektordner, z. B. `projekt.yml`:

   ```yaml
   default:
     enable: false
     database_uri: postgresql://studierende@localhost:6432/opendata?options=--search_path=
   wind_projekt:
     enable: true
     schema_name: projekt_wind
   ```

   Die Einstellungen der vorhandenen Crawler stehen in
   `deploy/CRAWLER_CONFIG.yml` und in `docs/configuration.md`.
4. Starten (das Datenbank-Passwort kommt aus `OEDS_DB_PASSWORD`):

   ```bash
   source /etc/oeds-gruppe.env
   source ~/.oeds-keys.env           # nur wenn die Quelle einen Schlüssel braucht
   uv run oeds-crawl wind_projekt --config projekt.yml
   ```

5. Tests in `packages/crawler-pack/tests/test_<name>.py`, ausführen mit:

   ```bash
   uv run --package oeds-crawler-pack pytest packages/crawler-pack/tests
   ```

Ein Crawler schreibt am Ende eine Zeile in `public.metadata` (Quelle, Lizenz,
Zeitraum). Damit erscheint euer Schema im Datenkatalog. Tragt dort die Lizenz
der Quelle ehrlich ein.

## Post-Run-Skripte

Post-Run-Skripte laufen auf dem Server nach einem erfolgreichen Crawler-Lauf,
z. B. um Lücken zu füllen oder abgeleitete Tabellen zu berechnen. In der
Konfiguration stehen sie unter `post_run_scripts` (siehe
`docs/configuration.md`); vorhandene Beispiele liegen in `packages/post/`.

Ein Post-Run-Skript ist ein Python-Skript oder ein Befehl. Testet es direkt:

```bash
source /etc/oeds-gruppe.env
uv run python mein_skript.py
```

Es soll nur in euer eigenes Schema schreiben und bei einem Fehler mit einem
Exit-Code ungleich 0 enden.
