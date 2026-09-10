# Concourse — API & agent marketplace prototype

A clickable prototype of an internal capability marketplace for a global company,
built to work out three things: **search**, **the library**, and the **day-to-day
experience** for a non-engineer assembling an automation.

`concourse.html` is the whole prototype — no build step, no dependencies. Open it
in a browser, or publish it as an Artifact. (It is authored as an Artifact body:
the `<!doctype>/<html>/<head>/<body>` skeleton is supplied at publish time. To open
it as a plain local file, wrap it in a minimal HTML document first.)

## What it demonstrates

**Search is intent-first.** The input is phrased *"I want to…"* and matches against a
curated `intents` list on every listing — the phrases real people use — before it
looks at titles. Every result shows *why it matched*, which builds trust and teaches
the domain vocabulary. Facets narrow a ranked list; they don't replace it.

**Access state is a search-result attribute.** For a business builder the blocking
question is "can I use this, with my data, in my region, this week?" — so access
state sits on the row, region is set once in the header, and *fastest to get access*
is a first-class sort.

**One metadata spine, four listing types.** APIs, agents, MCP tool servers and data
products share owner / domain / maturity / regions / data class / access path /
usage. Only the *proof of quality* differs — latency and uptime for APIs, autonomy
and eval pass rate for agents, exposed tools and scopes for tool servers, freshness
and volume for data products.

**The library holds kits, not just bookmarks.** Kits are curated bundles that already
work together, with the composition written down. The library also carries access
requests as visible, chase-able state.

## Data model

Each listing in the `L` array carries:

| field | purpose |
| --- | --- |
| `id`, `name`, `type`, `domain` | identity and taxonomy |
| `summary`, `does[]` | plain-language, outcome-framed description |
| `gives[]`, `gets[]` | what you hand it / what comes back |
| `intents[]`, `tags[]` | the search surface — intents are the high-weight field |
| `owner`, `ownerLoc`, `maturity`, `updated`, `used` | trust signals |
| `access`, `accessNote`, `regions[]`, `dataClass` | entitlement and governance |
| `spec{}` | type-specific proof of quality |
| `related[]` | composition hints |

`KITS` bundles listing ids with a `how` note describing the composition.

## What is staged vs. real

- **Staged** — semantic ranking is a curated intent + synonym map, not embeddings.
  The 23 listings and Halden Group itself are invented but structurally realistic.
- **Real** — the metadata model, facet set, ranking inputs, access states and page
  flows are what you would implement.
- **Deliberately out of scope** — publishing/onboarding flow, chargeback, versioning
  and deprecation comms, and a developer-facing "try it" console.

Saved items and access requests persist in `localStorage` under `concourse.v1`.
