# hackthepatch

Event matcher for an 8-hour hackathon. Attendees sign in with LinkedIn and describe themselves (by hand, from
pasted profile text, or from consented Member Data Portability data); an OpenAI-compatible LLM extracts their group,
what each person builds, offers and needs, and FalkorDB holds the room as a graph. Three features on top:

1. **Who do you need** — complementary matching on gaps (`looking_for` vs `can_offer` + skills), not similarity.
2. **Ask the room** — a question is embedded, shortlisted against profiles, and the LLM picks the three best people.
   It lands in their inbox.
3. **Live room graph** — clusters and bridges, rendered with vis-network. Edges are rarity-weighted.

Plus **Sign in with LinkedIn** (OpenID Connect): the login creates the attendee from name/email/picture, the
profile fills from the member's own import, and the attendee describes an **active project**; the LLM
extracts pain points, needs and domains, and the room is searched for people who can unblock them.

LinkedIn's self-serve OIDC product returns name, email and picture but not the profile URL. The URL
(`vanityName`) needs the `r_basicprofile` scope, which LinkedIn grants per app; with it the URL is stored at login.
LinkedIn's logged-out public profile hides experience, so the app does not scrape: members import their own copy.

Members in the EU/EEA and Switzerland can instead consent to LinkedIn's Member Data Portability API: add that
product to the app and `r_dma_portability_self_serve` to `LINKEDIN_SCOPES`, and the login pulls PROFILE,
POSITIONS, EDUCATION, SKILLS and PROJECTS straight from LinkedIn into the same LLM extraction.
Members elsewhere cannot consent and fill in their profile by hand instead.

## Run

```bash
cp .env.example .env            # fill OPENAI_API_KEY
uv sync --all-groups
uv run uvicorn app.main:create_app --factory --reload
open http://localhost:8000
```

For LinkedIn login create an app at https://www.linkedin.com/developers/, add the product
"Sign In with LinkedIn using OpenID Connect", register `http://localhost:8000/auth/callback` as redirect URL,
and put the client id/secret in `.env`. `DEV_LOGIN=true` gives a local sign-in for testing without it.

FalkorDB is expected on `localhost:6379` (graph name `hackthepatch`). `STORE=memory` runs without it.
Without an embeddings endpoint the app falls back to a local hashed embedding; without any LLM the
"paste a profile" path fails but "Load demo room" and all four features still work.

## Test

```bash
uv run pytest -q
```

Tests use an in-memory store and a fake OpenAI client; nothing reaches the network.

## Layout

```
app/
  config.py      settings from .env
  models.py      Profile / Question, tag normalisation, ids
  llm.py         extraction prompt, embeddings (+ hash fallback), question ranking
  graph.py       FalkorDB store (Cypher) and InMemoryStore with the same interface
  matching.py    complementary_matches, route_question, project_connections
  roomgraph.py   networkx clusters, bridge ranking
  auth.py        LinkedIn OIDC (authorization code -> token -> userinfo, optional vanityName)
  main.py        FastAPI routes, session, portability jobs, static UI
static/          index.html, style.css, app.js
data/            event_sessions.json (the agenda)
tests/fixtures/  two fictional rooms (14 and 20 attendees) the matching and graph tests are built on
tests/
```

## Graph model (FalkorDB)

```
(:Person)-[:HAS_ROLE]->(:Role)            investor | founder | hiring | open_to_work | connecting
(:Person)-[:SKILLED_IN|OFFERS|NEEDS]->(:Skill)
(:Person)-[:INTERESTED_IN]->(:Interest)
(:Person)-[:WORKED_AT]->(:Company)
(:Person)-[:STUDIED_AT]->(:School)
(:Person)-[:HAS_PAIN_POINT]->(:PainPoint)
(:Question)-[:ROUTED_TO {reason}]->(:Person)
```

The active project is stored on the Person node as `project_json`; its pain points also become `PainPoint` nodes.
`role` and `statement` (the About sentence saying what they want from the room) are Person properties.

Matching pairs across groups on gaps: an investor's thesis (`NEEDS`) against the domains a founder builds in,
a hiring manager's roles against a candidate's skills, a founder's missing roles against the people seeking them,
and plain skills for everyone else. Each group is a tenant of the same `NEEDS`/`OFFERS` edges; see `matching.py`.

Example, the "who do you need" question as Cypher:

```cypher
MATCH (a:Person {id: $id})-[:NEEDS]->(s:Skill)<-[:OFFERS]-(b:Person)
RETURN b.name, collect(s.name) AS fills ORDER BY size(fills) DESC
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET | /auth/login, /auth/callback | Sign in with LinkedIn (OIDC); `POST /auth/logout` |
| POST | /auth/dev-login | `{name}` local sign-in, only with `DEV_LOGIN=true` |
| GET | /api/me | signed-in attendee, login config, latest import job |
| PUT | /api/me/project | `{description}` → LLM pain points/needs + connections in the room |
| GET | /api/me/connections | possible connections for the active project |
| POST | /api/attendees/text | `{name, text}` → LLM extraction |
| GET | /api/attendees, /api/attendees/{id} | list / detail |
| DELETE | /api/attendees/{id}, /api/attendees | remove one / reset |
| GET | /api/matches/{id} | complementary matches |
| POST | /api/questions | `{text, asker_id?}` → routed to three people |
| GET | /api/questions, /api/inbox/{id} | feed / notifications |
| GET | /api/room-graph | nodes, edges, clusters, bridges |
