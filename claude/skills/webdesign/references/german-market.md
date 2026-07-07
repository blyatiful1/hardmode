# German-market gate

Germany has an active Abmahnung (cease-and-desist-for-profit) culture: a missing
Impressum field or a Google-hosted font is not a style issue, it is a billable
offense a competitor's lawyer finds with a crawler. This document is the hard gate
Stage W3 walks for any site targeting Germany/DACH — each item reported pass/fail.

**Boundary:** legal texts this checklist produces (Impressum, Datenschutzerklärung,
AGB, Widerrufsbelehrung) are structured templates. Say so in the report and name the
fields the site owner must confirm with counsel. Facts below were live-verified
against primary sources (statute text, judgments, authority guidance) in 2026-07;
laws drift — re-verify section numbers before citing them to a user.

## 1. Legal must-haves (every German site)

- [ ] **Impressum** — § 5 DDG (Digitale-Dienste-Gesetz; replaced the TMG on
  2024-05-14 — citing "§ 5 TMG" cites non-existent law; citing no statute at all is
  also fine and future-proof). Reachable from every page under the label "Impressum"
  ("leicht erkennbar und unmittelbar erreichbar" — per BGH I ZR 228/03 two clicks
  are OK, creative labels or footers that need JS/scrolling past a cookie wall are
  not). Required contents scale with legal form:
  - Everyone: full name (natural person, or company name incl. Rechtsform),
    ladungsfähige street address (no P.O. box/Packstation), and **an e-mail address
    — explicitly mandatory; a contact form alone is not enough.** A phone number is
    customary but not strictly required if another fast channel exists.
  - Registered companies: Registergericht + Registernummer (e.g. HRB), all
    Vertretungsberechtigte (GmbH: every Geschäftsführer; AG: Vorstand + Aufsichtsrat).
  - USt-IdNr. (§ 27a UStG) if one exists — but **never the Steuernummer** (not
    required, identity-theft bait), and don't mention share capital voluntarily
    (mentioning it triggers the unpaid-Einlagen disclosure duty).
  - Regulated professions: Berufsbezeichnung + conferring state, zuständige Kammer,
    berufsrechtliche Regelungen, Aufsichtsbehörde where licensing applies.
  - Journalistic/editorial content (blogs, news sections): "Verantwortlich für den
    Inhalt nach § 18 Abs. 2 MStV: [natural person, street address]".
- [ ] **Datenschutzerklärung** — Art. 13/14 DSGVO. **Own page with its own footer
  link, separate from the Impressum** (merging them is a recurring supervisory
  complaint). Must cover every processing the site ACTUALLY does — hosting/server
  logs, contact form, every embed, analytics, consent tooling — naming:
  Verantwortlicher (+ Datenschutzbeauftragter where required), purposes and Art. 6
  legal bases per activity, recipients and third-country transfers, storage
  duration, data-subject rights incl. withdrawal and Beschwerderecht. Generated
  from the real data flows, never pasted boilerplate: describing services the site
  doesn't run is itself a transparency defect — and since ECJ C-21/23
  (Lindenapotheke), a defective Datenschutzerklärung is abmahnfähig by competitors.
- [ ] **Consent (§ 25 TDDDG)** — the law formerly TTDSG, renamed 2024-05. Any
  storing/reading on the visitor's device that is not strictly necessary for the
  requested service (analytics cookies, marketing pixels, non-essential
  localStorage, fingerprinting) needs PRIOR opt-in consent; the only exemptions are
  communication transport and "unbedingt erforderlich" — there is NO analytics or
  legitimate-interest exemption at the § 25 level. Banner rules from case law (OLG
  Köln 6 U 80/23) and DSK guidance: "Ablehnen" as easy and prominent as
  "Akzeptieren" on the first layer, no pre-checked boxes, no dark patterns, closing
  ≠ consent, revocation as easy as granting (persistent settings link). The EU
  "Digital Omnibus" (proposed 2025-11) may eventually move cookie consent into the
  GDPR with new exceptions — proposed is not law; don't build against it. The
  strongest design move remains: **build consent-free (section 2) and ship no
  banner at all** — legal AND better UX AND a trust signal.
- [ ] **BFSG accessibility** — Barrierefreiheitsstärkungsgesetz, fully in force
  since 2025-06-28, **no grace period for websites** (the "2030 deadline" myth
  covers only pre-existing contracts/products, § 38 BFSG). In scope: digital
  services aimed at concluding a B2C contract — shop checkout, online booking,
  binding order forms pull the whole path to them in scope; purely informational
  sites and pure B2B are out (generic contact forms are a contested gray zone).
  Kleinstunternehmen (< 10 employees AND ≤ €2M turnover) exempt for services only.
  Technical bar: EN 301 549 v3.2.1 = **WCAG 2.1 AA** (the WCAG 2.2 revision was not
  yet harmonized as of mid-2026 — build to 2.2 anyway: target size, focus not
  obscured, accessible authentication). In-scope services publish "Informationen
  zur Barrierefreiheit" per § 14/Anlage 3 BFSG naming the market-surveillance
  authority (MLBF, Magdeburg) — don't copy public-sector BITV templates. Fines:
  up to €100k for offering a non-compliant service, €10k tier for a missing/
  deficient statement; first Abmahn waves ran 2025/2026 over basics: missing alt
  text, low contrast, keyboard-dead forms, missing statement. Accessibility overlay
  widgets do not establish conformity (and are themselves an audit finding);
  automated checkers catch only ~⅓ of failures — the highest-yield AA items for
  marketing sites: contrast pairs checked against hex values, full keyboard path
  with visible focus, labels/errors on every form field, heading order, motion
  behind `prefers-reduced-motion`, 200% text resize / 320 px reflow without loss.
- [ ] **Shops only (commerce view):** § 312j BGB order button labeled
  "zahlungspflichtig bestellen" (or equally unambiguous — "Kaufen"/"Bestellen"
  alone fails); PAngV price display: Gesamtpreis with "inkl. MwSt., zzgl. Versand"
  at the price, Grundpreis (per kg/l/m) beside unit-priced goods, § 11 PAngV
  lowest-prior-price rule for discounts; Widerrufsbelehrung + Muster-
  Widerrufsformular; AGB page; concrete delivery times on the product page; § 36
  VSBG notice on Verbraucherstreitbeilegung. **Do NOT link the EU ODR platform** —
  discontinued 2025-07-20 (Regulation (EU) 2024/3228), references must be removed;
  a dead mandatory link is itself misleading. The § 36 VSBG notice remains.

## 2. Data-flow rules — these change what you BUILD, not what you add

- [ ] **Fonts: self-hosted, always.** LG München I (3 O 17493/20, 2022-01-20):
  loading Google Fonts from Google's servers transmits the visitor's IP without
  consent = GDPR violation, damages awarded — and BGH VI ZR 10/24 (2024) made mere
  loss of control compensable (~€100) with no proven misuse. Download WOFF2
  (fontsource, google-webfonts-helper) and serve from the site's own origin — or
  use the system font stack.
- [ ] **Zero third-party requests at page load.** No CDN frameworks/CSS, no
  external images, no US-endpoint calls before consent. **The W3 check is
  mechanical: a fresh-profile network inspection must show zero non-first-party
  requests before any user interaction.**
- [ ] **Embeds behind a two-click facade.** YouTube, Google Maps, social posts:
  self-hosted static placeholder + explanation + explicit click loads the third
  party. `youtube-nocookie.com` is NOT consent-free on its own (it still contacts
  Google and writes to the device on iframe load) — use it *after* the facade
  click. Maps without a facade: plain address + outbound Google-Maps link
  (transmits nothing until the user leaves), or self-hosted tiles — note the public
  `tile.openstreetmap.org` server is also a third party.
- [ ] **Analytics: none is the default.** Server-log statistics need no banner.
  Next rung: cookieless EU-hosted measurement (Plausible-style — nothing stored/
  read on the device) is arguably outside § 25 TDDDG. Cookieless self-hosted Matomo
  is common practice but the BfDI's published position is that Matomo "generally
  requires consent" — treat it as residual-risk, not safe-by-default. Google
  Analytics always requires consent (cookies + own-purpose processing + US
  transfer): never emit it on a new German build.
- [ ] **US services with an EU alternative:** the EU-US Data Privacy Framework
  (2023 adequacy) is in force as of mid-2026 but under CJEU appeal (C-703/25 P) —
  and it only covers certified vendors and never answers the § 25 device-access
  question. Prefer EU-first vendors (Hetzner, IONOS, netcup …); an Art. 28
  AV-Vertrag with every processor.

## 3. Typography & language — German text breaks default layouts

- `lang="de"` on `<html>` (de-AT Austria; de-CH Switzerland — which uses NO ß) and
  `hyphens: auto` on prose — **hyphenation silently does nothing without the `lang`
  attribute**, the #1 reason German compounds ("Haftpflichtversicherung") overflow
  360 px cards. `&shy;` for headings, `overflow-wrap: break-word` as belt-and-braces.
- Quotation marks: „…“ (opening U+201E low, closing U+201C high) or »…« pointing
  inward. **Trap: the German closing quote IS the English opening quote — a
  mismatched pair is the classic generated-text tell.** Straight "quotes" read as
  machine-translated. `<q>` with `lang="de"` renders correct pairs automatically.
- ß is a letter, not a ligature; capital ẞ (U+1E9E) has been official since 2017
  and the **default in all-caps settings since the 2024 Regelwerk revision**
  (STRAẞE over STRASSE). CSS `text-transform: uppercase` does NOT convert ß —
  hard-code uppercased ß-words and check the font actually has U+1E9E. Avoid
  all-caps for long compounds generally.
- Formats (DIN 5008): 1.234,56 (dot/thin-space thousands, comma decimals);
  currency AFTER the amount with a non-breaking space (19,90 €, never €19.99);
  dates DD.MM.YYYY on consumer sites (07.07.2026 or "7. Juli 2026", never
  MM/DD); times 24h ("14:30 Uhr"). In JS: `Intl.NumberFormat('de-DE')` /
  `toLocaleDateString('de-DE')`, never hand-format.
- German copy runs roughly 20–35% longer than English ("Datenschutzeinstellungen",
  "Zahlungsmöglichkeiten" are the sizing reality). Buttons, nav items, and headline
  slots sized on English drafts will truncate — design with the German strings.
- **Sie vs. du is a brand decision, made once, applied everywhere.** Default Sie:
  B2B, banking/finance, legal/tax, healthcare, public sector, trades. du is
  plausible for lifestyle/fashion/fitness/gaming/startup audiences. Mixing
  registers on one site damages trust more than either choice; when unsure, Sie.
- Slugs/URLs: transliterate umlauts (ä→ae, ö→oe, ü→ue, ß→ss).

## 4. Market conventions & trust

- Footer canon on every page, exact German labels, server-rendered (never behind a
  cookie banner or JS failure): Impressum · Datenschutzerklärung (· AGB ·
  Widerrufsbelehrung · Versand & Zahlung for shops · Erklärung zur Barrierefreiheit
  for in-scope B2C). Germans check for the Impressum as a legitimacy probe.
- Trust is institutional, not testimonial: certificates and memberships (Trusted
  Shops, TÜV, IHK/Innung, "Meisterbetrieb", ISO row, "seit 1974" heritage), real
  street address and phone, named Ansprechpartner with photos. **A trust seal must
  be clickable and resolve to a live certificate naming the shop — a static seal
  image reads as fake and is worse than none** (fake seals are a headline
  Verbraucherzentrale fraud signal, as is Vorkasse-only payment). Superlative copy
  ("das beste …") costs trust with German audiences; precision earns it.
- Shop payment mix (EHI 2025 revenue shares): PayPal ~28%, **Kauf auf Rechnung
  ~26% — uniquely load-bearing in Germany**, SEPA-Lastschrift ~17%, cards ~12%.
  Show the logo row before checkout; card-only checkouts measurably lose German
  customers. giropay/paydirekt was discontinued (2024) — never render its logo;
  "Sofortüberweisung" is Klarna branding now.
- Register and density: Mittelstand/B2B expects restrained palettes, higher
  information density, real photography, longer explanatory content, CTAs after
  substance (6–12 month buying cycles — US-style 2-field-form hero hype
  underperforms in DACH). Consumer/startup brands can run bolder; precision still
  beats vibe. A banner-free, fast, self-hosted site is itself a trust signal.

## 5. Walking the gate (Stage W3)

Report sections 1–4 as a checklist: pass / fail / not-applicable (with the reason).
Two checks are mechanical — run them, don't assert them: (a) zero non-first-party
requests on a fresh load, (b) the reduced-motion + keyboard pass from
design-views.md. A German-market build with any open FAIL in section 1 or 2 is not
"done" — same rule as a red test suite. Close with the legal-template disclaimer
from the boundary note.

## Primary sources (verified 2026-07)

- § 5 DDG (Impressum): https://www.gesetze-im-internet.de/ddg/__5.html · fines § 33 DDG
- Art. 13 DSGVO: https://gdpr-info.eu/art-13-gdpr/ · ECJ C-21/23 (Lindenapotheke)
- § 25 TDDDG: https://www.gesetze-im-internet.de/ttdsg/__25.html (URL still says ttdsg) · OLG Köln 6 U 80/23
- BFSG: https://www.gesetze-im-internet.de/bfsg/ (§ 14 statement, § 37 fines, § 38 transition) · EN 301 549 v3.2.1: https://digital-strategy.ec.europa.eu/en/policies/latest-changes-accessibility-standard · WCAG 2.1: https://www.w3.org/TR/WCAG21/
- Google-Fonts ruling LG München I 3 O 17493/20 · BGH VI ZR 10/24 (Art. 82 damages)
- ODR shutdown (Reg. (EU) 2024/3228, 2025-07-20): https://consumer-redress.ec.europa.eu/site-relocation_en
- BfDI on Matomo: https://www.bfdi.bund.de/DE/Fachthemen/Inhalte/Telemedien/Matomo.html
- DPF status: https://commission.europa.eu/law/law-topic/data-protection/international-dimension-data-protection/eu-us-data-transfers_en (appeal C-703/25 P pending)
- EHI Online-Payment 2025: https://www.ehi.org/presse/paypal-festigt-spitzenposition/ · Verbraucherzentrale on seals/fake shops
