# Projekt_ListedInc

## Om projektet
Projekt_ListedInc är ett verktyg för att snabbt samla in, lagra och analysera data om listade företag. Systemet är byggt för att underlätta insamling av företagsdata från olika källor, spara denna information i en relationsdatabas och möjliggöra diagnostik samt snapshots för vidare analys. Projektet är tänkt att vara lätt att komma igång med och anpassa för egna behov.

## Features
- Web crawl och dataingest från olika källor.
- Extrahering av text från PDF-filer.
- Metadatahantering såsom rubriker, taggar och publiceringsdatum.
- Kontaktutvinning inklusive e-postadresser, telefonnummer samt personer med namn och roll.
- Idempotent ingest med versionshantering för att undvika dubbletter och bevara historik.
- Snapshot- och diagnosfunktioner för att analysera databasens tillstånd och jämföra data över tid.

## Kom igång

Följ stegen nedan för att snabbt komma igång med Projekt_ListedInc. Makefile är det centrala arbetsflödet, och det rekommenderas att använda `make env` för att skapa och konfigurera den Python-virtuella miljön:

1. **Klona repot**
   ```bash
   git clone https://github.com/ditt-användarnamn/Projekt_ListedInc.git
   cd Projekt_ListedInc
   ```
2. **Skapa och aktivera Python-virtuell miljö via Makefile**
   ```bash
   make env
   source venv/bin/activate
   ```
3. **Installera beroenden**
   ```bash
   pip install -r requirements.txt
   ```
4. **Initiera databasschema**
   ```bash
   make schema
   ```
5. **Kör dataingest eller scanning**
   ```bash
   make ingest
   # eller
   make scan
   ```
   Se Make-kommandon nedan för fler alternativ.

## Make-kommandon

Projektet använder en Makefile för att förenkla vanliga arbetsflöden:

- `make env` – Skapar och konfigurerar den Python-virtuella miljön.
- `make dev` – Startar utvecklingsmiljön med automatisk omstart vid kodändringar.
- `make schema` – Initierar eller uppdaterar databasschemat i PostgreSQL.
- `make ingest` – Kör dataingest-scriptet för att samla in företagsdata.
  
  Exempel (om sidan har problem med SSL‑certifikat):
  ```bash
  make ingest URL="https://www.exempel.com" INSECURE=1
  ```
- `make scan` – Kör scanning eller analys av insamlad data.
- `make test` – Kör alla tester.
- `make lint` – Kör kodkontroll för att hitta stil- och syntaxfel.
- `make fmt` – Formaterar koden enligt projektets kodstandard.
- `make lint-fix` – Åtgärdar automatiskt vissa kodstilproblem.
- `make db-start` – Startar PostgreSQL-databasen via Homebrew-tjänst.
- `make db-stop` – Stoppar PostgreSQL-databasen.
- `make db-restart` – Startar om PostgreSQL-databasen.
- `make db-status` – Visar status för PostgreSQL-databasen.
- `make db-logs` – Visar loggar från PostgreSQL-databasen.
- `make db-help` – Visar hjälp och information om databasrelaterade Make-kommandon.

### Kontakt & rapporter

- `make sync-contacts` – Synkroniserar kontaktinformation från databasen.
- `make contacts-csv` – Exporterar kontakter till CSV-fil för vidare användning eller rapportering.

## Databas

Projektet använder PostgreSQL som relationsdatabas. Standarddatabasen heter `listedinc` och anslutning sker via miljövariabeln `DATABASE_URL`.

- Databasschemat definieras i `db/schema.sql`.
- Centrala tabeller är `document` och `contact_info` där företagsdata och kontaktuppgifter lagras.
- Det finns vyer som `contact_info_extracted` för att underlätta analys av extraherad kontaktinformation.
- Funktioner för att synkronisera kontakter finns implementerade för att hålla data uppdaterad.
- Databasen hanteras via Homebrew-tjänster på macOS.
- Följande Make-kommandon används för att kontrollera databasen:
  - `make db-start` för att starta databasen.
  - `make db-stop` för att stoppa databasen.
  - `make db-restart` för att starta om databasen.
  - `make db-status` för att kontrollera status.
  - `make db-logs` för att visa databasen loggar.
- Initiera databasschemat första gången med:
  ```bash
  make schema
  ``` 

## Snapshot & diagnoser

Du kan när som helst ta en snapshot av databasen för att frysa aktuell status:

```bash
make snapshot
```

Snapshots kan användas för att jämföra crawl mellan olika bolag eller över tid, vilket underlättar analys av förändringar.

För att felsöka och analysera databasens hälsa:

```bash
make diagnose
```

Snapshots sparas i katalogen `snapshots/` och kan användas för återställning eller jämförelse.

## Bidra

Bidrag är välkomna! Skicka gärna en pull request eller öppna ett issue om du hittar buggar eller har förbättringsförslag. Se till att följa kodningsstandarder och skriv tester för ny funktionalitet.

## Licens

Projekt_ListedInc är öppen källkod och licensieras under MIT-licensen. Se `LICENSE`-filen för mer information.