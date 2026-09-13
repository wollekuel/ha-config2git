# ha-config2git

Eine Home-Assistant-App (Add-on), die das Home-Assistant-Konfigurationsverzeichnis
überwacht, Änderungen mit Git versioniert und sie per SSH in ein
GitHub-Repository pusht.

## Überblick

ha-config2git läuft als kleiner Container innerhalb von Home Assistant
(verwaltet vom Supervisor). Die App:

- überwacht `/config` (das Home-Assistant-Konfigurationsverzeichnis, das
  schreibgeschützt eingebunden wird),
- erkennt Änderungen an den Dateien, die dich interessieren (anhand
  konfigurierbarer Include-/Exclude-Patterns),
- kopiert geänderte Dateien in ein lokales Git-Repository unter
  `/data/repository`,
- erzeugt einen Git-Commit mit informativer, konfigurierbarer Meldung,
- pusht den Commit per SSH mit einem repository-scoped Deploy Key in ein
  GitHub-Repository.

Das Ergebnis ist ein automatisches, versioniertes Backup deiner
Home-Assistant-Konfiguration auf GitHub.

## Features

- **Überwachung von `/config`** — Änderungen an ausgewählten Dateien werden
  automatisch erkannt.
- **Include-/Exclude-Patterns** — du legst fest, welche Dateien synchronisiert
  werden (z. B. nur `*.yaml`, oder alles außer `secrets.yaml`).
- **Debouncing** — Änderungen werden nach einer konfigurierbaren Ruhephase
  gebündelt, sodass eine Reihe von Edits zu einem einzelnen Commit führt.
- **Git-Commit** — mit informativer, konfigurierbarer Commit-Message (Template)
  und konfigurierbarem Autor.
- **Konfigurierbarer GitHub-Branch** — wird für Commit und Push verwendet.
- **SSH-Authentifizierung** über einen repository-scoped Deploy Key.
- **Strict Host Key Checking** mit gepinnten GitHub-Host-Keys.
- **Kein Force-Push** — die Remote-Historie wird niemals umgeschrieben.
- **Fehlerbehandlung** — Git-/SSH-Fehler werden geloggt; die Überwachung läuft
  weiter.

Nicht implementiert: automatische Repository-/Deploy-Key-Erstellung,
PAT/OAuth/GitHub-App-Authentifizierung, HACS-Integration oder die
Home-Assistant-API. Siehe
[Bekannte Einschränkungen / Roadmap](#bekannte-einschränkungen--roadmap).

## Voraussetzungen

- **Home Assistant** mit Supervisor-Unterstützung (Möglichkeit, Add-ons/Apps zu
  installieren). Unterstützte Architekturen: `aarch64` und `amd64`.
- **Ein GitHub-Repository**, in das gepusht werden soll. Für den ersten Test
  ein **leeres** Repository verwenden (siehe Hinweis unten).
- **Ein SSH-Deploy-Key mit Schreibzugriff** auf dieses Repository.
- Zugriff auf deine Home-Assistant-Konfiguration (`/config`).

> **Hinweis zu leeren/neuen Repositories:** ha-config2git verwendet niemals
> `--force` und schreibt niemals Historie um. Wenn das GitHub-Repository bereits
> eine eigene Historie besitzt (z. B. weil es mit einer README oder
> `.gitignore` initialisiert wurde), kann der erste Push mit einem
> *non-fast-forward*-Fehler scheitern, weil lokale und entfernte Historie nicht
> zusammenhängen. Verwende für einen ersten Test ein vollständig leeres
> Repository (ohne README, ohne `.gitignore`).

## Installation

1. **GitHub-Repository anlegen** (Settings → Repositories → New). Wähle einen
   Namen wie `my-homeassistant-config`. Lasse es **leer** — keine README und
   keine `.gitignore` hinzufügen.
2. **Deploy-Key erzeugen** auf deinem Rechner (siehe
   [GitHub Deploy Key einrichten](#github-deploy-key-einrichten)).
3. **Public Key bei GitHub hinterlegen** unter
   *Settings → Deploy keys* des Repositories, mit aktiviertem
   *Allow write access*.
4. **Repository in Home Assistant hinzufügen** als App-Repository:
   *Einstellungen → Add-ons → Add-on-Store → ⋮ → Repositories*. Trage die URL
   des ha-config2git-Repositories ein und bestätige.
5. **App installieren** — nach dem Aktualisieren erscheint `ha-config2git` im
   Store.
6. **Konfiguration öffnen** der installierten App.
7. **Werte eintragen** (siehe [Konfiguration](#konfiguration)) — mindestens
   `github_repository` und `ssh_private_key`.
8. **Private Key sicher hinterlegen** in der App-Konfiguration. Siehe
   [GitHub Deploy Key einrichten](#github-deploy-key-einrichten) — niemals
   committen.
9. **App starten.**
10. **Logs kontrollieren** (Registerkarte *Log* der App) — auf erfolgreichen
    Start und die geloggte Konfigurationsübersicht achten.
11. **Teständerung in `/config` durchführen** (z. B. eine YAML-Datei bearbeiten
    oder eine temporäre Datei anlegen).
12. **Commit und Push bei GitHub kontrollieren** — ein neuer Commit auf dem
    konfigurierten Branch erscheint.

## GitHub Deploy Key einrichten

Ein **Deploy Key** ist ein SSH-Key, der Zugriff auf **ein einzelnes**
Repository gewährt. Anders als ein persönlicher SSH-Key (der meist Zugriff auf
alle deine Repositories hat) kann ein Deploy Key auf genau ein Repository
beschränkt und unabhängig widerrufen werden. Deshalb ist er für einen
automatisierten Prozess wie ha-config2git die richtige Wahl.

### 1. Schlüsselpaar erzeugen (auf deinem Rechner)

```sh
ssh-keygen -t ed25519 -C "ha-config2git" -f ~/.ssh/ha-config2git
```

Dabei entstehen zwei Dateien:

- `~/.ssh/ha-config2git` — der **private** Schlüssel (geheim halten).
- `~/.ssh/ha-config2git.pub` — der **öffentliche** Schlüssel (darf an GitHub).

### 2. Öffentlichen Schlüssel bei GitHub hinterlegen

1. Öffne dein Repository auf GitHub.
2. Gehe zu **Settings → Deploy keys → Add deploy key**.
3. Füge den **Inhalt der `.pub`-Datei** in das Feld *Key* ein.
4. Gib einen Titel an (z. B. `ha-config2git`).
5. **Aktiviere "Allow write access"** — das ist erforderlich, damit die App
   pushen kann.
6. Klicke **Add key**.

### 3. Privaten Schlüssel in die App-Konfiguration legen

- Der **private** Schlüssel gehört **ausschließlich** in die
  Home-Assistant-App-Konfiguration (`ssh_private_key`).
- Der **öffentliche** Schlüssel kommt zu GitHub.
- Committe den privaten Schlüssel niemals in ein Repository.

### So sieht die SSH-Verbindung aus

Die App verbindet sich zu deinem Repository als:

```text
git@github.com:OWNER/REPOSITORY.git
```

`OWNER/REPOSITORY` ist dabei exakt der Wert von `github_repository` aus deiner
Konfiguration (z. B. `myuser/my-homeassistant-config` →
`git@github.com:myuser/my-homeassistant-config.git`).

## Konfiguration

Folgende Optionen sind verfügbar. Die Defaults entsprechen `config.yaml`.

| Option | Typ | Default | Beschreibung |
| --- | --- | --- | --- |
| `github_repository` | String | — (erforderlich) | GitHub-Repository im Format `OWNER/REPOSITORY`. Ein abschließendes `/` oder `.git` wird ignoriert. Beispiel: `myuser/my-homeassistant-config`. |
| `github_branch` | String | `main` | Branch, der für Commit und Push verwendet wird. |
| `git_author_name` | String | `ha-config2git` | Name, der in jedem Commit vermerkt wird. |
| `git_author_email` | String | `ha-config2git@home-assistant` | E-Mail, die in jedem Commit vermerkt wird. |
| `commit_message_template` | String | `Sync Home Assistant configuration: {changed_files}` | Template für die Commit-Message (siehe [Commit-Message-Template](#commit-message-template)). |
| `commit_debounce_seconds` | Ganzzahl | `30` | Ruhephase (Sekunden) nach der letzten Änderung, bevor ein Commit erzeugt wird. |
| `push_interval_seconds` | Ganzzahl | `300` | **Reserviert, aktuell ungenutzt.** Im Schema vorhanden und validiert, aber die App pusht derzeit nur direkt nach einem Commit. |
| `log_level` | String | `info` | Log-Level: `debug`, `info`, `warning` oder `error`. |
| `ssh_private_key` | String (Passwort) | `""` | Der private SSH-Schlüssel (OpenSSH-Format). Bei leerem Wert verweigert die App den Start. |
| `include_patterns` | Liste von Strings | siehe unten | Glob-Patterns für Dateien, die synchronisiert werden. Mindestens ein Eintrag erforderlich. |
| `exclude_patterns` | Liste von Strings | siehe unten | Glob-Patterns für Dateien, die ignoriert werden. Darf leer sein. |

### Commit-Message-Template

Mit `commit_message_template` legst du den Text jedes Commits fest. Der Text darf
feste Zeichenfolgen und Platzhalter der Form `{name}` enthalten. Folgende
Platzhalter werden unterstützt:

| Platzhalter | Bedeutung |
| --- | --- |
| `{changed_count}` | Anzahl aller geänderten Dateien (neu + geändert + gelöscht). |
| `{changed_files}` | Kommagetrennte Liste der geänderten relativen Pfade. Maximal 5 Pfade werden direkt ausgegeben; bei mehr als 5 Dateien folgt `… (+M more)` mit der Anzahl der restlichen Dateien. |
| `{added_count}` | Anzahl neu hinzugefügter Dateien. |
| `{modified_count}` | Anzahl geänderter, bereits vorhandener Dateien. |
| `{deleted_count}` | Anzahl gelöschter Dateien. |

Die generierte Commit-Message ist auf **maximal 200 Zeichen** begrenzt; bei
Bedarf wird die Dateiliste gekürzt, ohne die `… (+M more)`-Darstellung zu
beschädigen. Datei**inhalte** oder Diff-Inhalte werden niemals in die
Commit-Message aufgenommen — nur relative Pfade und Zähler.

Beispiele mit dem Default-Template:

```text
Sync Home Assistant configuration: configuration.yaml
Sync Home Assistant configuration: automations.yaml, scripts.yaml
Sync Home Assistant configuration: a.yaml, b.yaml, c.yaml, d.yaml, e.yaml, … (+7 more)
```

Eigene Templates, zum Beispiel:

```yaml
commit_message_template: "Update {changed_count} files"
commit_message_template: "Changed {changed_files}"
```

Ungültige Templates (unbekannte Platzhalter, fehlerhafte Klammern) werden beim
Start der App abgelehnt.

### Default-Include-/Exclude-Patterns

Include:

```yaml
include_patterns:
  - "*.yaml"
  - "*.yml"
  - "*.json"
  - "custom_components/**"
  - "blueprints/**"
  - "esphome/**"
```

Exclude:

```yaml
exclude_patterns:
  - "secrets.yaml"
  - "*.db"
  - "*.db-*"
  - ".storage/**"
```

### Hinweise zu einzelnen Optionen

- **`github_repository`** ist erforderlich und muss `OWNER/REPOSITORY`
  entsprechen. Führende/abschließende Leerzeichen werden entfernt; ein
  abschließendes `/` und ein `.git`-Suffix werden vor dem Aufbau der
  Remote-URL entfernt.
- **`ssh_private_key`** wird in der Home-Assistant-Oberfläche als Passwort
  behandelt (maskiert). Die App normalisiert OpenSSH-Schlüssel
  (`-----BEGIN OPENSSH PRIVATE KEY-----` … `-----END OPENSSH PRIVATE KEY-----`),
  auch wenn deren Zeilenumbrüche von der Oberfläche zu Leerzeichen gefaltet
  wurden. Nur das OpenSSH-Format wird normalisiert; andere PEM-Formate werden
  unverändert durchgereicht.
- **`commit_debounce_seconds`** steuert, wie schnell Änderungen nach dem
  letzten Edit committet werden. Ein größerer Wert bündelt mehr Änderungen in
  einem Commit.
- **`push_interval_seconds`** ist aus Kompatibilitätsgründen im Schema
  vorhanden, wird aber **funktional noch nicht verwendet**: Es gibt keinen
  periodischen Push. Ein Push erfolgt nur direkt nach einem erfolgreichen
  Commit.

## Include- und Exclude-Patterns

Die Patterns sind Glob-Muster:

- `*` matcht beliebige Zeichen innerhalb eines einzelnen Pfadsegments.
- `**` matcht null oder mehr ganze Pfadsegmente.
- Ein Pattern, das ein Verzeichnis matcht, matcht auch alles darunter.

**Priorität:** `exclude_patterns` gewinnen immer gegenüber `include_patterns`.
Eine Datei wird nur synchronisiert, wenn sie ein Include-Pattern matcht und
kein Exclude-Pattern matcht.

Beispiele (mit den Defaults):

| Pattern | Bedeutung |
| --- | --- |
| `*.yaml` | Jede `.yaml`-Datei (innerhalb eines einzelnen Segments). |
| `custom_components/**` | Alles unterhalb von `custom_components/`. |
| `blueprints/**` | Alles unterhalb von `blueprints/`. |
| `esphome/**` | Alles unterhalb von `esphome/`. |
| `secrets.yaml` | Schließt `secrets.yaml` aus, damit Secrets nie gepusht werden. |
| `*.db` | Schließt Datenbankdateien aus. |
| `*.db-*` | Schließt Datenbank-Backups/Rollover-Dateien aus. |
| `.storage/**` | Schließt das interne `.storage`-Verzeichnis aus. |

## Was passiert bei einer Änderung?

1. **Dateiänderung** — eine Datei unter `/config` wird erzeugt, geändert oder
   gelöscht.
2. **Watcher** — ein Hintergrund-Thread überwacht `/config` (per `os.scandir`)
   und bemerkt die Änderung.
3. **Debounce** — nach der letzten relevanten Änderung wartet der Watcher
   `commit_debounce_seconds` Sekunden.
4. **Synchronisierung** — die geänderten Dateien werden in das lokale
   Git-Repository unter `/data/repository` gespiegelt (nur Dateien, die auf die
   Include-/Exclude-Patterns passen).
5. **Filter** — die Include-/Exclude-Patterns werden angewendet; ausgeschlossene
   Dateien werden ignoriert und veraltete Dateien aus dem lokalen Repository
   entfernt.
6. **Git staging/commit** — Änderungen werden gestaged und mit der Meldung
   `Sync Home Assistant configuration` committet.
7. **Push** — der Commit wird auf `git@github.com:OWNER/REPOSITORY.git` auf den
   konfigurierten Branch gepusht.

Tritt ein Git- oder SSH-Fehler auf, wird er geloggt und die Überwachung läuft
weiter; die nächste Änderung löst einen neuen Versuch aus.

## Sicherheit

- Der private Schlüssel wird **nie geloggt**. `ssh_private_key` wird außerdem
  aus der beim Start geloggten Konfigurationsübersicht (`summary()`)
  weggelassen.
- Die Schlüsseldatei wird mit `0600` angelegt, das `.ssh`-Verzeichnis mit
  `0700`.
- SSH nutzt `StrictHostKeyChecking=yes` und eine eigene, gepinnte
  `known_hosts`-Datei mit den offiziellen GitHub-Host-Keys (DSA ist bewusst
  weggelassen).
- SSH nutzt `IdentitiesOnly=yes` (nur der konfigurierte Schlüssel wird
  angeboten) und `BatchMode=yes` (keine interaktiven Rückfragen).
- Alle externen Befehle werden ohne Shell ausgeführt (`shell=True` wird nie
  verwendet).
- Die App pusht niemals mit Force und schreibt niemals Historie um.
- Im Repository liegen keine Zugangsdaten; private Schlüssel werden von
  `.gitignore` ignoriert.

Ein **Deploy Key** ist einem persönlichen SSH-Key vorzuziehen: Er lässt sich
auf ein einzelnes Repository beschränken, hat keinen Zugriff auf deine übrigen
Repositories und kann unabhängig vom Konto widerrufen werden.

## Troubleshooting

### "is not a valid app repository"

Diese Meldung erscheint, wenn Home Assistant das App-Repository-Manifest nicht
lesen kann.

- Stelle sicher, dass das Repository eine gültige `repository.yaml` mit `name`,
  `url` und `maintainer` enthält.
- Stelle sicher, dass die App in einem Unterordner (`ha_config2git/`) mit
  gültiger `config.yaml`, `Dockerfile` und `run.sh` liegt.
- Ist das Repository privat, muss dein Home-Assistant-Benutzer Lesezugriff
  darauf haben.

### "Permission denied (publickey)"

Der SSH-Handshake ist fehlgeschlagen. Prüfe der Reihe nach:

1. Der **Deploy Key** wurde unter *Settings → Deploy keys* hinterlegt (nicht
   als persönlicher SSH-Key).
2. **"Allow write access"** ist für den Deploy Key aktiviert.
3. Der **private** Schlüssel in `ssh_private_key` passt zum **öffentlichen**
   Schlüssel bei GitHub (die beiden müssen zusammengehören).
4. `github_repository` ist exakt als `OWNER/REPOSITORY` geschrieben (die Remote
   ist `git@github.com:OWNER/REPOSITORY.git`).
5. Der Schlüssel liegt im OpenSSH-Format vor (`-----BEGIN OPENSSH PRIVATE
   KEY-----`).

### "Load key ... error in libcrypto: unsupported"

Diese Meldung bedeutet in der Regel, dass OpenSSH im Container den privaten
Schlüssel nicht parsen konnte. Häufigste Ursache: Der **mehrzeilige Schlüssel
wurde zu einer einzigen Zeile gefaltet** — etwa wenn die Home-Assistant-GUI
einen mehrzeiligen Wert speichert und die Zeilenumbrüche durch Leerzeichen
ersetzt.

Die App **normalisiert OpenSSH-Schlüssel**, indem sie den Header
`-----BEGIN OPENSSH PRIVATE KEY-----` und den Footer
`-----END OPENSSH PRIVATE KEY-----` erkennt und den Body wieder in gültige
Zeilen umbricht. Um das Problem ganz zu vermeiden, hinterlege den Schlüssel als
YAML-Multiline-Block:

```yaml
ssh_private_key: |
  -----BEGIN OPENSSH PRIVATE KEY-----
  ...
  -----END OPENSSH PRIVATE KEY-----
```

Nur das OpenSSH-Format wird normalisiert; beliebige PEM-Formate werden nicht
garantiert unterstützt. Verwende die Standard-Ausgabe von `ssh-keygen`
(`ed25519`, OpenSSH-Format).

### Non-fast-forward / Push rejected

Die lokale Commit-Historie und die Remote-Historie hängen nicht zusammen oder
sind auseinandergelaufen. ha-config2git pusht **niemals mit Force**, daher wird
dieser Push abgelehnt.

- Verwende für einen ersten Test ein **vollständig leeres** Repository.
- Falls das Remote bereits Commits enthält, importiere sie zuerst in das lokale
  Repository oder beginne mit einem leeren Repository neu.

### Keine Änderung wird synchronisiert

- Prüfe die **Include-/Exclude-Patterns**: Die Datei muss ein Include-Pattern
  matchen und darf kein Exclude-Pattern matchen.
- Prüfe die **Logs** auf der Registerkarte *Log* der App.
- Stelle sicher, dass die Datei tatsächlich unter `/config` liegt.
- Denke an das **Debounce**: Committet wird erst nach `commit_debounce_seconds`
  Ruhephase.

## Beispielkonfiguration

```yaml
github_repository: myuser/my-homeassistant-config
github_branch: main
git_author_name: ha-config2git
git_author_email: ha-config2git@home-assistant
commit_message_template: "Sync Home Assistant configuration: {changed_files}"
commit_debounce_seconds: 30
push_interval_seconds: 300
log_level: info
ssh_private_key: |
  -----BEGIN OPENSSH PRIVATE KEY-----
  <dein-private-key-body-hier>
  -----END OPENSSH PRIVATE KEY-----
include_patterns:
  - "*.yaml"
  - "*.yml"
  - "*.json"
  - "custom_components/**"
  - "blueprints/**"
  - "esphome/**"
exclude_patterns:
  - "secrets.yaml"
  - "*.db"
  - "*.db-*"
  - ".storage/**"
```

Ersetze `myuser/my-homeassistant-config` und den Platzhalter für den privaten
Schlüssel durch deine eigenen Werte. Füge niemals einen echten privaten
Schlüssel in Dokumentation oder Commits ein.

## Erster Test

1. App starten.
2. Registerkarte **Log** öffnen und prüfen, dass der Start erfolgreich war
   (die Konfigurationsübersicht wird ohne den privaten Schlüssel geloggt).
3. Eine ungefährliche Änderung unter `/config` durchführen (z. B. eine
   Test-YAML-Datei anlegen oder bearbeiten).
4. Die Debounce-Zeit plus einen Moment abwarten.
5. Nach einer Logzeile wie
   `Synchronized: … committed=True, pushed=True` suchen.
6. Das GitHub-Repository öffnen und prüfen, dass ein neuer Commit
   (`Sync Home Assistant configuration: <dateien>`) auf dem Branch erscheint.

Ein erfolgreicher Test zeigt `committed=True, pushed=True` in den Logs und
einen neuen Commit auf GitHub. Siehst du stattdessen `committed=True,
pushed=False` oder einen Fehler, wirf einen Blick in
[Troubleshooting](#troubleshooting).

## Repository-Struktur

```text
repository.yaml            # Manifest des Home-Assistant-App-Repositories
ha_config2git/
  config.yaml              # App-Metadaten und Konfigurationsschema
  Dockerfile               # Container-Build-Definition
  run.sh                   # Container-Entrypoint
  rootfs/app/
    config.py              # Validierung/Normalisierung der Optionen
    pathfilter.py          # Include-/Exclude-Matching
    sync.py                # Spiegelt /config in das lokale Repository
    watcher.py             # Polling-Watcher mit Debounce
    git_backend.py         # Git-Operationen (init/open/commit/push)
    orchestrator.py        # Verbindet Sync + Commit + Push
    ssh.py                 # Deploy-Key-Setup + gepinnte known_hosts
    main.py                # Einstiegspunkt / Verdrahtung
tests/                     # Unit- und Integrationstests
LICENSE
README.md
CHANGELOG.md
```

## Entwicklung / Tests

Die Testsuite nutzt Pythons `unittest`. Lokal vom Repository-Root ausführen:

```sh
python3 -m unittest discover -s tests
```

Die Tests decken unter anderem ab: Validierung und Normalisierung der
Konfiguration, den Include-/Exclude-Filter, Watcher und Debouncing, das
Sync-Verhalten, Git-Operationen (inkl. Push in lokale Bare-Repositories), das
SSH-Setup und die Verdrahtung der App. Mehrere Tests verwenden temporäre lokale
Git-Repositories, daher muss `git` installiert sein.

## Versionierung

Das Projekt verwendet [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
in der Form `MAJOR.MINOR.PATCH`.

- In der `0.x`-Phase (Entwicklungsphase):
  - **PATCH** — Bugfixes, Sicherheitskorrekturen und interne Verbesserungen
    ohne neue Nutzerfunktion.
  - **MINOR** — neue, rückwärtskompatible Nutzerfunktionen und relevante neue
    Konfigurationsmöglichkeiten.
- **1.0.0** markiert den ersten stabilen Release; danach kennzeichnen
  `MAJOR`-Versionen inkompatible Änderungen.

Jede veröffentlichte Version erhält einen Git-Tag im Format `vX.Y.Z`
(z. B. `v0.2.0`) und wird im `CHANGELOG.md` dokumentiert. Jeder Release ist
damit eindeutig einem Git-Commit und einem Git-Tag zugeordnet. Die App-Version
wird zentral in `ha_config2git/config.yaml` gepflegt; die detaillierten
Änderungen je Version stehen im [CHANGELOG](CHANGELOG.md).

## Bekannte Einschränkungen / Roadmap

Aktuell implementiert:

- Überwachung von `/config`, Include-/Exclude-Filterung, Debouncing.
- Lokaler Git-Commit und Push zu GitHub per SSH über einen Deploy Key.

Noch nicht implementiert:

- Automatische GitHub-Repository-Erstellung.
- Automatische Deploy-Key-Erstellung.
- PAT-, OAuth- oder GitHub-App-Authentifizierung.
- HACS-spezifische Integration.
- Home-Assistant-API-Integration.
- Periodischer Push (`push_interval_seconds` ist reserviert, aber ungenutzt).
- Inotify-basierte Überwachung (der Watcher verwendet derzeit Polling).
