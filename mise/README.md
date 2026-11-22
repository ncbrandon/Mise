# Mise — a self-hosted cooked.wiki (with every Patron feature unlocked)

Mise turns cluttered recipe pages, cooking videos, photos and documents into clean recipes you keep on
your own server. It's three pieces:

| Piece | What it is |
|---|---|
| `server/` | Python FastAPI API + Postgres. Recipe extraction, AI imports, unit conversion, shopping list, journal, social, export, public share pages and a cooked.wiki-style web reader. |
| `stack/` | Docker Compose stack for Portainer: Postgres 16, the API, nightly database backups, optional Ollama. |
| `ios/` | SwiftUI iPhone/iPad app (iOS 17+) with a **Save to Mise** share extension. |
| Web app | Open your server's address in any browser for the desktop version: library, recipes, cook mode, imports, editing, shopping list, journal, friends and settings. |

## Features vs. cooked.wiki

| cooked.wiki | Mise |
|---|---|
| Save recipes from any website | ✅ schema.org JSON-LD, microdata, WP Recipe Maker / Tasty markup, AI fallback for everything else |
| `cooked.wiki/<url>` reader | ✅ `http://your-server:8000/https://site.com/recipe` (or paste a link on the home page) |
| Save from YouTube, TikTok, Instagram *(Patron)* | ✅ via yt-dlp: follows the creator's linked blog recipe first, then AI on captions + description, then speech-to-text |
| Create from photos, text, voice, documents *(Patron)* | ✅ photos/camera (vision model), pasted text, on-device dictation, PDF (incl. scanned), Word, text, HTML |
| Edit recipes, notes, ratings, favorites | ✅ |
| Adjust portions | ✅ servings stepper or ½×–4× |
| Metric/imperial conversion *(Patron)* | ✅ including cups → grams for ~60 common ingredients and °F ↔ °C in steps |
| Smart shopping list | ✅ merges duplicates across recipes, converts units, sorts by aisle, pick which ingredients to add |
| Automatic categorization *(Patron)* | ✅ keyword rules, or AI when configured |
| Custom collections *(Patron)* | ✅ |
| Nutrition information *(Patron)* | ✅ publisher data when present, otherwise AI estimate per serving |
| Sub-recipe breakdown + diagram *(Patron)* | ✅ |
| Printable PDFs *(Patron)* | ✅ generated on the phone; share or AirPrint |
| Recipe dictation with AI voices *(Patron)* | ✅ reads recipes/steps aloud with the best installed Premium/Enhanced voice |
| Screen stays on while cooking | ✅ step-by-step cook mode with tap-to-start timers |
| Journal + community | ✅ cook log with photos & ratings, follow people on your server, friends feed, profiles |
| Share recipes | ✅ public share links with a clean, printable page |
| Private account *(Patron)* | ✅ |
| Export everything in one click *(Patron)* | ✅ zip of Markdown files + JSON, restorable |

## 1. Deploy the server in Portainer

You need the code somewhere Portainer can build it. Pick one:

**A. Git repository (easiest).** Push this folder to a GitHub/Gitea repo (private is fine).
In Portainer: **Stacks → Add stack → Repository**, enter the repo URL (plus credentials if private) and
set **Compose path** to `stack/docker-compose.yml`. Portainer clones it and builds the API image.

**B. Pre-built image.** Push to GitHub; the included Action (`.github/workflows/server-image.yml`)
runs the tests and publishes `ghcr.io/<you>/mise-server:latest` for amd64 + arm64 (Raspberry Pi works).
Make the package public (or add GHCR credentials under Portainer → Registries), then use
**Stacks → Add stack → Web editor**, paste `stack/docker-compose.yml`, and replace the `build:` block
with `image: ghcr.io/<you>/mise-server:latest` (lowercase).

**C. Build on the host.** `docker build -t mise-server:latest ./server` over SSH, then use the Web editor
and delete the `build:` block (keep `image: mise-server:latest`).

Then set the environment variables in the stack (copy from `stack/stack.env.example`):

| Variable | |
|---|---|
| `POSTGRES_PASSWORD` | required |
| `SECRET_KEY` | required, `openssl rand -hex 32` |
| `PUBLIC_URL` | the address your phone uses, e.g. `http://192.168.1.50:8000` or `https://mise.example.com` |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | optional; any OpenAI-compatible API (OpenAI, OpenRouter, Ollama, LM Studio) |
| `LLM_VISION_MODEL` | optional; a model that accepts images, if `LLM_MODEL` doesn't |
| `TRANSCRIBE_MODEL` | optional; e.g. `whisper-1` for videos without captions |
| `ALLOW_REGISTRATION` | set to `false` after your household has accounts |

Deploy, then open `http://<host>:8000` — you should see the Mise sign-in page (the web version). API docs are at `/docs`.

**Without AI** you still get: website imports, the reader, scaling, conversions, shopping list,
collections, keyword categorization, sub-recipes from recipe sections, journal, social, export, PDFs and
read-aloud. Video and text imports work when the caption/text itself lists the recipe. **With AI**
you also get photo imports, messy-text/voice/video extraction, nutrition estimates and smarter
categorization and breakdowns.

**Getting to it away from home:** put it behind your reverse proxy (Nginx Proxy Manager, Traefik,
Caddy) with HTTPS and set `PUBLIC_URL` to that address, or use Tailscale.

**Instagram** often blocks anonymous downloads. Export a `cookies.txt` from a logged-in browser and
copy it into the `mise_media` volume as `/data/cookies.txt`.

**Home Assistant shopping list:** set `HOME_ASSISTANT_URL`, `HOME_ASSISTANT_TOKEN` (a long-lived access
token from your HA profile → Security) and optionally `HOME_ASSISTANT_TODO_ENTITY` (default
`todo.shopping_list`). Everything added to the Mise shopping list is added to that Home Assistant to-do list,
merged quantities rename the existing item instead of duplicating it, and checking off or removing an item on
either side is reflected on the other. Works with any HA to-do list (Shopping List, Local To-do, Bring!, Todoist…).

**Backups:** the `backup` service writes a daily `pg_dump` to the `mise_backups` volume and keeps 14 days.
Restore with `pg_restore -h db -U mise -d mise --clean <file>`.

## 2. Build the iOS app

Requirements: a Mac with Xcode 16+, and [XcodeGen](https://github.com/yonaskolb/XcodeGen) (`brew install xcodegen`).

```bash
cd ios
# edit project.yml: set BUNDLE_ID_PREFIX (e.g. com.yourname) and DEVELOPMENT_TEAM
xcodegen
open Mise.xcodeproj
```

In Xcode, select the **Mise** scheme and your iPhone, then Run. Automatic signing registers the App Group
(`group.<prefix>.mise`) that lets the share extension use your login. A free Apple ID works for
installing on your own phone (apps expire after 7 days); a paid developer account lets you use TestFlight.

First launch: enter your server address (e.g. `192.168.1.50:8000`), then create an account. The first
account on the server is the admin.

**Saving from other apps:** in Safari, YouTube, TikTok, Instagram, Photos or Files tap **Share →
Save to Mise** (you may need to tap "More" once to enable it).

## How things work

- **Recipe pages:** most recipe sites embed schema.org data, so imports are instant and exact. If a page
  has none, the page text goes to the AI model.
- **Videos:** yt-dlp reads the description and captions. If the description links to a blog with the
  full recipe, Mise imports that page. Otherwise the AI reads description + captions (+ a Whisper
  transcript if enabled).
- **Units:** ingredients are parsed into quantity/unit/name when saved, so scaling and conversion are
  exact rather than text replacement. The original line is always kept and is what you edit.
- **Your data:** everything lives in Postgres in your stack. Export from Settings any time.

## Running the server tests

```bash
cd server
pip install -r requirements.txt
python -m pytest -q tests
```

## Project layout

```
server/app/
  main.py               FastAPI app
  models.py, db.py      SQLAlchemy models (Postgres, JSONB)
  routers/              account, recipes, imports, collections, shopping, social, export, web pages
  services/
    extract.py          schema.org / microdata / plugin recipe extraction
    ingredients.py      parsing, scaling, metric ⇄ imperial, temperatures
    importer.py         URL / video / text / photo / document pipelines
    llm.py              OpenAI-compatible client and prompts
    video.py            yt-dlp captions, description, audio
    shopping.py         merging + aisle sorting
    categorize.py       keyword categories
  templates/            share page, reader, home
stack/                  Portainer compose + env example
ios/
  project.yml           XcodeGen spec (app + share extension)
  Shared/               API client, models, shared login (App Group keychain)
  App/                  SwiftUI app
  ShareExtension/       "Save to Mise"
```
