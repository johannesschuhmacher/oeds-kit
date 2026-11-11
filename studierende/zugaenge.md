# Konten und API-Schlüssel

Die meisten Quellen sind ohne Konto nutzbar und auf der Gruppen-VM schon
geladen. Für einige braucht ihr ein eigenes, kostenloses Konto. Jede Person
legt ihre Konten selbst an; Schlüssel werden nicht geteilt und nicht
committet.

## Was ihr braucht

| Wofür | Konto | Kosten |
| --- | --- | --- |
| VM-Anmeldung | KIT-Konto, Freischaltung über die Betreuung | – |
| Code teilen | GitHub-Konto, Nutzername an die Betreuung | kostenlos |
| eigene Crawler für Quellen mit Schlüssel | die Konten unten, je nach Projekt | kostenlos |

## Quellen ohne Schlüssel

SMARD, MaStR, ENTSOG, Open-Meteo (nicht kommerziell), Eurostat, DWD,
powerplantmatching, renewables.ninja, regelleistung.net, Trading Hub Europe.

## Quellen mit kostenlosem Schlüssel

| Quelle (Crawler) | Variablen | So bekommt ihr den Zugang |
| --- | --- | --- |
| ENTSO-E Web API (`entsoe_api`) | `ENTSOE_API_KEY` | Konto auf <https://transparency.entsoe.eu> anlegen. Dann eine E-Mail an <transparency@entsoe.eu> mit Betreff „Restful API access“ und der E-Mail-Adresse des Kontos schicken. Nach der Freischaltung unter „My Account Settings“ ein Token erzeugen. |
| ENTSO-E File Library (`entsoe_files`) | `ENTSOE_USERNAME`, `ENTSOE_PASSWORD` | Dasselbe Transparency-Konto (E-Mail und Passwort). |
| Netztransparenz (`netztransparenz`) | `NETZTRANSPARENZ_CLIENT_ID`, `NETZTRANSPARENZ_CLIENT_SECRET` | Konto im Extranet <https://extranet.netztransparenz.de> anlegen und dort unter „Meine Clients“ einen API-Client erzeugen. |
| EIA (`eia`) | `EIA_API_KEY` | <https://www.eia.gov/opendata/register.php>; der Schlüssel kommt per E-Mail. |
| GIE AGSI+/ALSI (`gie_agsi_alsi`) | `GIE_API_KEY` | Konto auf <https://agsi.gie.eu> anlegen; der Schlüssel steht im Profil und gilt auch für ALSI. |
| Copernicus CDS (`copernicus_cds`) | `COPERNICUS_CDS_KEY` | Konto auf <https://cds.climate.copernicus.eu>; das Token steht im Profil. Die Lizenz jedes Datensatzes muss auf seiner Seite einmal akzeptiert werden. |

Die genauen Einstellungen jedes Crawlers stehen in `docs/crawlers/<name>.md`.

## Kostenpflichtige Quellen

EPEX SPOT (`epex_spot`), PRISMA (`prisma_capacity`) und energyforecast.de
(`energyforecast`) sind kostenpflichtig oder proprietär. Sie sind auf der
Gruppen-VM nicht geladen. Nur nach Absprache mit der Betreuung.

## Schlüssel ablegen

Kopiert [keys.env.example](keys.env.example) in euer Home-Verzeichnis und
tragt nur die Schlüssel ein, die ihr wirklich habt:

```bash
cp /srv/oeds-gruppe/oeds-kit/studierende/keys.env.example ~/.oeds-keys.env
chmod 600 ~/.oeds-keys.env
nano ~/.oeds-keys.env
```

Vor einem Crawler-Lauf laden:

```bash
source /etc/oeds-gruppe.env
source ~/.oeds-keys.env
uv run oeds-crawl entsoe_api --config projekt.yml
```

## Nutzungsbedingungen

Ob und wie Daten weitergegeben werden dürfen, regeln die Bedingungen der
Quelle. Lest sie, bevor ihr Daten oder Grafiken veröffentlicht, und nennt die
Quelle. Die Lizenz, die ein Crawler einträgt, steht in `public.metadata`.
