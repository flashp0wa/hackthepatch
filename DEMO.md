# Demo script

Server: `uv run uvicorn app.main:create_app --factory --port 8000`, open http://localhost:8000 (the LinkedIn
callback is registered on `localhost`, not `127.0.0.1`). FalkorDB must be running on `localhost:6379`.

## Before the demo

- [ ] `.env`: `DEV_LOGIN=false` unless you want the local sign-in fallback on stage. Keep it `true` if LinkedIn
      login is not guaranteed to work on the venue network; the Event tab's Interests button needs a signed-in profile.
- [ ] Restart the server after any `.env` change (it reads the file at start).
- [ ] The live room holds 36 attendees: 34 fictional ones across the five groups, plus David Molnar (LinkedIn
      login, CV-filled) and Lalit Balijepally. The question feed holds the 14 example questions, no duplicates.
- [ ] Tabs, in demo order: Live room graph, Who do you need, Ask the room, Event, My profile.

## 1. The room (Live room graph)

Open on the graph. Point at the clusters (colour) and the bridges (white ring, larger): the few people who connect
several clusters. David Molnar is one of them.

## 2. Add an attendee live (sidebar)

Paste `demo/attendee.txt` into "Add an attendee from profile text", name **Tessa Marlow**, press Extract. The LLM
reads the About text and classifies her as a **founder**, keeps her statement, and fills skills, interests, what she
offers and what she needs: `ml engineer`, `frontend engineer`, `pre-seed investors`.

Say what the text contains: a founder in climate infrastructure, two utility pilots, looking for an ML engineer, a
frontend engineer and pre-seed money, offering grid and utility know-how.

## 3. Who do you need

The app switches to the matches tab for Tessa. Expected, best first:

| Score | Who | Why |
| --- | --- | --- |
| 9.0 | Katrin Hoffmann, investor | investor ↔ founder: fills her funding need; Katrin's thesis (climate, pre-seed) is what Tessa builds |
| 7.5 | Nkechi Obi, investor | investor ↔ founder: funding, pre-seed |
| 6.75 | Ethan Brooks, open to work | founder ↔ open to work: fills frontend engineer, and Tessa's open role is what he seeks |
| 2.75 | Imani Carter, open to work | fills frontend engineer |
| lower | Daniel Reyes, Henrik Dahl, Omar Siddiqui | frontend or machine learning skills, one-sided |

The point to make: nobody here is "like" Tessa. The two investors do not share a skill with her; they are paired
because her gap is their offer. Click **Katrin Hoffmann** in the sidebar to show the reverse: four founders, each
needing funding, in her thesis domains.

Other good clicks: **Henrik Dahl** (hiring) gets the two candidates who seek exactly his roles; **Pavel Novák**
(open to work) gets the hiring manager with a platform role first, then the founder who needs a backend cofounder.

## 4. Ask the room

Ask as Tessa: *"Has anyone shipped a time-series model on satellite imagery to production?"* The question is
embedded, shortlisted by keywords and the LLM picks three people with a reason each. It lands in their inbox; click
one of them in the sidebar to show the Inbox at the bottom of their matches tab.

## 5. Event tab (needs sign-in)

Sign in (LinkedIn, or dev login as yourself), open Event, press **Interests**. The LLM scores the six keynotes against
the signed-in profile and explains each score. The note under the agenda says whether the LLM or the keyword fallback
ranked them.

## 6. My profile (optional)

Set "I am here as" and "What I want from the room", add a few tags under "Looking for" and "Can offer", save,
and show how the matches change. The tags drive matching; the statement and group drive the badge and the
Interests ranking.

## If something breaks

- Interests shows an amber "LLM unavailable" note: the OpenAI key is wrong or the network is down; the keyword
  fallback still ranks.
- "not signed in" on Event: sign in first.
- Reset removes every attendee and question from FalkorDB. There is no undo; the fictional rooms are in
  `tests/fixtures/` and can be re-added by hand through the text form, one at a time.
