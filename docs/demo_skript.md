# FastAccounts demo skript (raamatupidamisbüroole)

Järgmine kulgemine võtab kokku umbes 25–30 minutit. Kõik demoandmed on sünteetilised: büroo töölaual on kaks klienti — Northstar Studio Ltd (Suurbritannia) ja Põhjatäht Teenused OÜ (Eesti). Eesti kliendi jaoks on töötajad sisestatud ning juuli–septembri palgaarvestuse jooksud juba kinnitatud.

## Ettevalmistus (15 min)

```powershell
# kaustas fastaccounts
pip install -r requirements.txt          # uue masina puhul
copy .env.sample .env                    # + demo võtmed ja FASTACCOUNTS_ALLOW_TEST_AUTH=true
.venv\Scripts\python seed.py             # loob demoandmetega andmebaasi (kustutab fastaccounts.sqlite)
.venv\Scripts\python web_app.py          # http://localhost:5012
```

- Avab brauseris `http://localhost:5012/auth/test` — see logib sisse demokasutajasse **Demo Kasutaja** (nõuab `FASTACCOUNTS_ALLOW_TEST_AUTH=true`, ainult demo eesmärgil).
- Kui kasutajaliides on inglise keeles, vajuta paremal üleval nupule „Eesti“ — keel kehtib terve sessiooni jooksul. Tootmiskeskkonnas saab vaikekeele püsivalt määrata keskkonnamuutujaga `FASTACCOUNTS_DEFAULT_LANG=et`.

## Kulgemine

### 1. Büroo töölaud (2 min)
- **Ülevaade** — neli KPI-kaarti: Nõuded, Kohustused, Pangatehingute ülevaatus, Selle kuu palgaarvestus. Viimane kaart näitab Eesti kliendi puhul praeguse kuu kuumaksumust ja jäädakse tühjaks GBP ettevõttele (palgaarvestus on Eesti eurodes raamatupidamise moodul).
- **Klientide raamatupidamine** — kaks ettevõtet ühel töölaual: büroo vaatevinklist haldad mitut kliendi raamatupidamist ühe sisselogimisega, andmed on ettevõtetepõhiselt eraldatud.
- Tõmba rõhku sellele, et iga kanne läbib sama topeltkirjendusega pearaamatu muutmata partiidena — ühtegi kaudset summat ei kirjutata käsitsi.

### 2. Pangandus ja vastendamine (5 min)
- **Pangandus** — konto kaart (Arvelduskonto, EUR), allpool tehingute nimekiri koos olekumärgistega (Vastendamata / Vastendatud).
- Kliki tehingul „Vaata üle“ — avaneb vastendamisvaade: süsteem pakub vastavat müügi- või ostuarvet, kinnitasid ühe nupuga, kanne saab oleku „Vastendatud“ ja pearaamatu kanne luuakse tasakaalustatud partiina.
- Läbi üks konkreetne näide: näiteks üks viimane arve tasumine, mille viite on arve number.

### 3. Raamatupidamine ja aruanded (5 min)
- **Raamatupidamine** — vahelehtedega aruanded: Proovibilanss → Kasumiaruanne → Bilanss → Pearaamat → Nõuete/kohustuste vanusanalüüs → Rahavool.
- Näita Proovibilanssis, et aruanded arvutatakse otse pöördetabelist ja on ajavahemiku järgi filtreeritavad (Alates/Kuni → Rakenda).
- Näita vajadusel ka Kasumiaruannet ja ütle, et kõik aruanded on salvestatavad PDF-iks (nupp „Prindi / salvesta PDF“).

### 4. KMD — käibedeklaratsiooni tööleht (3 min)
- **Maksud** — KMD-vaade. Maksukoodid on Eesti määradega (EE24/EE13/EE9/EE0/EEEX/EEICS/EEOS/EERC).
- Nupp „Koosta tööleht“ arvutab KMD-kastid maksukoodide paigutuse alusel; seejärel „Koosta VD“ ekspordiks. Rõhul: arvestustulemuse üle vaatab inimene raamatupidajana — enne EMTA-sse esitamist jääb vastutus inimesele.

### 5. Palgaarvestus — tuum (10 min)

- **Töötajad**: 6 töötajat koos brutopalga, kogumispensioni määra ja maksuvabastusmärgistega. Üks töötajatest on juhatuseliige (pole töötuskindlustusmakset, pension 0%). „Lisa töötaja“ ja „Muuda“ töötavad kohe.
- **Koosta kuu palgaarvestus** — sisesta periood (visand 2026-10 on juba eelnevalt loodud). Süsteem arvutab iga töötaja kohta: kogumispension, töötuskindlustus 1,6%, tulumaks 22% (määratud maksuvaba miinimumiga 700 € või ilma), sotsiaalmaks 33%, tööandja kulu 33,8% — ja kontrollib alampalka (2026: 886 € kuni märts, 946 € aprillist).
- Laienda rida „Arvestus töötajate kaupa“ — näita ühe töötaja andmeid ja kontrolli summasid: brutopalgast lahutatakse kinnipeetud summad → netopalk; tööandja kulu = brutopalk + sotsiaalmaks + tööandja töötuskindlustus.
- **Kinnita ja kirjenda** — jooks lukustub, pearaamatusse kirjutatakse üks balansseeritud partii (PALG-2026-10): palgakulu, sotsiaalmaksu kulu, tulumaksu võlg ja palgavõla kontodel. Ava **Raamatupidamine → Proovibilanss** ja näita, et palgakantused on juba proovibilanssis.
- **Palgalehed (PDF)** — lae alla ja ava: iga töötaja kohta eraldi leht, samad arvutused nähtavad, tööandja kulu ja kinnipeetud maksude alused välja toodud. Büroo saab sellised palgalehed hiljem töötajatele saata.
- Varasemad jooksud (juuli–september) on kinnitatud sama arvutusega — näita neid töökindluse tõendina.

### 6. Sisselülitused ja keel (2 min)
- Keelelüliti (English/Eesti/Latviešu/Lietuvių) avalikel lehekülgedel ja töölaual.
- Palgaarvestust saab pidada paralleelselt mitme Eesti ettevõtte jaoks; teine demo klient on Suurbritannia raamatupidaja, kellel palgaarvestuse kanal on tühi ja keelatud.

## Tõenäolised küsimused ja vastused

- **Kas süsteem on tootmiskõlblik?** — Raamatupidamise tuumik (topeltkirjendus, muutmata partiid, ettevõtetepõhine eraldus) on tootmiseks valmis; palgaarvestus ja KMD esitamine on demo eesmärgil, enne UAT-i (PDF-i jalus ja aruanded märgistavad seda ausalt).
- **TSD esitamine?** — Palgaarvestus arvutab alused ja koostab palgalehed; TSD deklaratsiooni eksport raamatupidajale on järgmine arendussamm, mitte demo ajal.
- **Kas kliendi andmed on eraldi?** — Iga kanne kuulub ühele ettevõttele; aruanded arvutatakse ainult selle ettevõtte sisestustest, ajavahemiku järgi.
- **Litsentsid ja majutamine?** — Kood on avatud lätekoodiga, tarkvara saab ise hostida ilma tellimusel põhinevate kasutuslitsentsideta.