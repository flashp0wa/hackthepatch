The project is part of an 8 hours hackathon  https://luma.com/ptc?tk=O0yFAI. The attendees can connect their linked in profiles, an LLM extracts interest and related technologies from the about section and profile. This helps connecting people.

## Features

Complementary matching instead of similar. Extract what each person is building or looking for, not just what they know, and match on gaps: a backend engineer with a half-finished idea gets paired with the designer in the room, not another backend engineer. “Who do you need” is a better question than “who is like you”.
“Ask the room” routing. Attendees post questions during the day (“anyone used Temporal in production?”). The LLM routes each question to the three people whose profiles best fit and notifies them. This turns a static directory into something people use repeatedly during the event, which is also a much stronger demo than a list of matches.
Serendipity mode. Deliberately match people who are far apart in the embedding space but share exactly one unexpected thing (same obscure past employer, same side project domain). The one-surprising-link framing is more memorable than “you both like Python”.
Live room graph. Render the attendees as a graph with clusters and highlight the bridges, the few people connected to multiple clusters. Those are the people worth introducing to everyone. Visually compelling on a projector and nearly free once you have embeddings.

## Constrains
Use BrightData to collect LinkedIn profile information.
FalkorDB Graph database to store the users and their interests and technologies they are skilled in. (Already running on the machine localhost:6379)
Keep the project small and compact so a demo is presentable in 6 hours.
The application accepts any OpenAI compatible endpoint for the LLMs.
Keep the code modular and well-spearated with accurate file naming.
No need for sophisticated agent harness only the core loop.
Work in the project folder only, do not include other services besides Bright Data and FalkorDB

## UI
The UI should reflect all four features.