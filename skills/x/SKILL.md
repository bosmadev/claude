---
name: x
description: "X/Twitter outreach -- research engagement, compose original posts from news, and distribute via replies. Claude dynamically searches, composes, and posts via X API (fast) or Chrome MCP (fallback)."
argument-hint: "research [N] [model] {TOPIC} | post [N] [model] {TEXT with URL} | compose | campaign [N] [model] {TOPIC} | stop | status | news | history | help"
user-invocable: true
---

# /x Skill -- AI-Driven X/Twitter Outreach

## Overview

This skill automates X/Twitter outreach for any project or tool. Claude dynamically:

1. **Research mode** -- explores X search queries to find high-engagement targets
2. **Post mode** -- composes unique replies and posts via X API (1-2 sec/post) with Chrome MCP as fallback
3. **Compose mode** -- creates original tweets from scraped news, then distributes by replying to related conversations
4. **Multi-agent mode** -- spawns N agents with chosen model for parallel research or posting

**Core design:** No hardcoded templates or queries. Claude decides everything dynamically based on context.

**Speed design:** X HTTP API is the primary backend. Post -> log -> next -> post -> log -> next. No browser page loads between posts.

**URL rule:** ALWAYS link to the user's configured `SHARE_URL` (see config below). Never link to source repos directly -- drive impressions to the user's social post.

**Persistence design:** Agents work continuously with aggressive retry logic. Rate limits trigger wait-and-retry, never shutdown.

---

## CRITICAL: Continuous Operation (Never Stop)

**ALL agents must work continuously until explicit shutdown request.** No automatic stopping.

**When hitting obstacles:**
- ❌ **NEVER** stop or go idle permanently
- ❌ **NEVER** exit due to rate limits or empty search results
- ✅ **ALWAYS** wait 60-180 seconds and retry
- ✅ **ALWAYS** try alternative search queries if one fails
- ✅ **ALWAYS** rotate between different targeting strategies

**Rate limit behavior:**
1. Hit rate limit → Wait 60s → Retry same query
2. Still limited → Wait 120s → Try different query
3. Still limited → Wait 180s → Cycle through all targeting strategies
4. Repeat forever until search succeeds or shutdown requested

**Empty results behavior:**
1. No results found → Try broader search terms
2. Still empty → Try different time window (within_time:1d → 3d → 7d)
3. Still empty → Try different engagement threshold (min_faves:10 → 5 → 3 → 1)
4. Cycle through all combinations, then restart

**Rule:** Work continuously = aggressive retry + strategy rotation + zero automatic exits

### NO IDLE STATES (Critical Enforcement)

**ALL agents must be actively working at ALL times. NO exceptions.**

**WORK SILENTLY. DO NOT report progress, status, or ask questions.**

After completing a posting batch:
1. **IMMEDIATELY** start next search cycle (don't wait, don't report, don't go idle)
2. Rotate query strategy (change keywords, engagement thresholds, time windows)
3. If rate limited: Wait 60s → retry with NEW query angle (not same query)
4. If empty results: Broaden terms → retry IMMEDIATELY (no delay)

**Continuous loop (no breaks, no reports):**
```
Search → Post → Log → Search → Post → Log → (FOREVER, SILENTLY)
```

**NEVER send status updates, progress reports, or milestone achievements.** These cause idle states. Work in complete silence unless you hit a critical error you cannot resolve (rate limit >10 minutes, Chrome completely broken).

**If you're idle for more than 10 seconds, you're failing the protocol.**

---

## CRITICAL: Profile Post Approval Rule

**NEVER post original tweets to the user's profile without EXPLICIT user approval.** This is the #1 rule.

| Action | Approval Needed? | Why |
|--------|-----------------|-----|
| Reply to someone else's post | NO -- post immediately | Replies are the core workflow, no gate needed |
| Original tweet on user's profile (`x.py tweet`) | YES -- ask user first | Profile posts represent the user's voice directly |
| Quote tweet (embeds another post) | YES -- ask user first | Appears on user's profile, visible to all followers |
| Retweet | YES -- ask user first | Visible on user's profile |

**How to handle profile posts:**
1. Research and compose the draft tweet
2. Present it to the user: "Draft profile tweet: `{text}` -- should I post this?"
3. Wait for explicit "yes" / approval
4. Only THEN call `x.py tweet "{text}"`

**Agents (subagents) MUST NEVER call `x.py tweet`** — only the main orchestrator can, after user approval. Agents should only use `x.py post` (replies to others).

---

## CRITICAL: Tone Enforcement (Friendly, Funny, Humorous with Light Sarcasm)

**Target tone:** Helpful + playful + self-aware. Think "friend giving advice over coffee" not "expert lecturing".

### ❌ BLOCKED: Mean/Condescending Sarcasm
- "Love watching people discover [tool] isn't magic..." (condescending)
- "Good luck with that..." (dismissive)
- "Hope you hit real complexity..." (schadenfreude)
- "Welcome to reality..." (superior)
- "Sure that'll work out..." (doubting)

### ✅ GOOD: Playful/Self-Aware Humor
- "Been there. Spent 3 hours debugging before realizing I forgot to restart the server. Classic."
- "If I had a dollar for every time I forgot to commit .env to .gitignore... I'd have enough for therapy."
- "Love how we all pretend our side projects will be 'quick weekenders'. Three months later..."
- "Pro tip: The bug is always in the code you're 100% certain is correct. Always."
- "Nothing says 'senior developer' like confidently googling the same error for the 47th time."

### ✅ GOOD: Helpful + Funny
- "Have you tried [solution]? Saved my bacon last week when I was drowning in [problem]"
- "Running into [issue]? Our tool handles that - learned the hard way so you don't have to: {SHARE_URL}"
- "Love this approach! Reminds me of when I discovered [technique] - game changer"
- "That moment when [relatable struggle]... we built {SHARE_URL} specifically for this"

### ✅ GOOD: Genuine Interest
- "How did you solve [specific challenge]? Genuinely curious - ran into this last month"
- "This is brilliant. What made you choose [approach] over [alternative]?"
- "Following this thread. Love seeing different approaches to [problem]"

**Rule:** Self-deprecating humor ✅ | Putting others down ❌ | Being helpful always ✅

**Enforcement:** Script blocks condescending patterns. Aim for "funny friend" not "superior expert".

---

## Configuration (Auto-Generated)

Config is auto-generated from environment variables. **No manual config.json creation needed.**

### Option A: .env File (Recommended)

Create `skills/x/.env` with your settings:

```env
# X authentication (from Cookie-Editor extension)
X_CT0=your_ct0_cookie
X_AUTH_TOKEN=your_auth_token

# Profile config (used in all generated content)
X_SHARE_URL=https://x.com/YOUR_HANDLE/status/YOUR_POST_ID
X_HANDLE=@YOUR_HANDLE
X_PROJECT_NAME=Your Project Name
X_PROJECT_DESC=One-line description of what your project does

# Optional: Messari API for crypto news
MESSARI_API_KEY=your_messari_api_key
```

### Option B: System Environment Variables

Set the same variables (`X_SHARE_URL`, `X_HANDLE`, etc.) as system environment variables.

### How It Works

On first run, the scraper reads `.env` (or system env) and auto-generates `skills/x/data/config.json`. This file is gitignored and acts as a cache. Delete it to regenerate from env vars.

**`share_url`** -- The X post URL to include in every reply. Link to YOUR post, not the source repo. Drives impressions to your profile.

---

## Argument Routing

| Input | Action | Example |
|-------|--------|---------|
| `research [N] [model] {TOPIC}` | Explore X queries, rank by engagement | `/x research 5 sonnet free AI tools for students` |
| `post [N] [model] {TEXT with URL}` | Compose unique replies, post via X API | `/x post 10 opus Tell users about our free tool {SHARE_URL}` |
| `compose` | Pick news item, compose original tweet, distribute via replies | `/x compose` |
| `news` | Show scraped news feed (RSS, Messari, changelogs) | `/x news` |
| `history` | Show posting history | `/x history` |
| `status` | Show daily/weekly counts + reach. If campaign active: show agent count + campaign runtime | `/x status` |
| `stop` | Shutdown active campaign: SendMessage(shutdown_request) to all agents → TeamDelete() → final stats | `/x stop` |
| `scrape` | Run scraper now, update feed.json | `/x scrape` |
| `feed` | Show current auto-generated feed (queries + news) | `/x feed` |
| `scheduler install [N]` | Install auto-scraper (every Nh, default 6) | `/x scheduler install 4` |
| `scheduler status` | Show scheduler + feed freshness | `/x scheduler status` |
| `scheduler uninstall` | Remove auto-scraper | `/x scheduler uninstall` |
| `auto [N] [model]` | Headless auto-run: scrape + research + post | `/x auto 5 sonnet` |
| `campaign [N] [model] {TOPIC}` | TeamCreate + N agents, continuous posting loop | `/x campaign 10 sonnet AI cost complaints` |
| `github` | GitHub-to-X pipeline: scan repos/issues, map users to X handles, generate queries | `/x github` |
| `github --search` | Same + search X API for each generated query | `/x github --search` |
| `help` | Show usage help | `/x help` |

### Model Selection Syntax

Commands `research`, `post`, and `campaign` support `[N] [model]` syntax:

- `[N]` -- number of parallel agents (default: 1, single agent in main context)
- `[model]` -- `opus`, `sonnet`, or `haiku` (default: main context model)

**Examples:**
```
/x post {TEXT}                              # Single agent, Sonnet (default)
/x post 10 {TEXT}                           # 10 Sonnet agents in parallel (recommended)
/x post 10 sonnet {TEXT}                    # Same as above, explicit
/x research 5 sonnet {TOPIC}                # 5 Sonnet agents for research
/x post 2 haiku {TEXT}                      # 2 Haiku agents (minimal cost)
/x campaign 10 sonnet AI cost complaints    # 10-agent continuous team (recommended)
/x campaign 5 haiku free tools              # 5 Haiku agents (budget)
/x campaign 10 opus {TOPIC}                 # BLOCKED: "Campaign uses sonnet/haiku only"
```

**Default model is Sonnet for all /x operations.** Never use Opus for /x — it runs continuously and burns weekly quota. Only use `opus` if user explicitly requests it for research/post modes.

**Campaign mode BLOCKS Opus entirely** — continuous loops would drain weekly Opus quota in hours. Use Sonnet (default) or Haiku (budget).

When `N > 1`, Claude spawns Task agents via `Task(model="sonnet")` override. Research agents use Bash subagent_type (X API only), For You scanner uses general-purpose (needs Chrome MCP).

### Agent Allocation (N > 1) -- Research + Poster Architecture

**Default model: Sonnet for ALL /x agents.** Never use Opus for /x — it runs continuously and would drain weekly Opus quota. Sonnet handles search, composition, and posting equally well.

When spawning 10 agents (default for `/x post 10`), use this role-based allocation:

| # | Role | Type | subagent_type | Purpose |
|---|------|------|---------------|---------|
| 1-2 | **Researchers** | X API search | Bash | Run 5 queries each, collect targets, dedup, report |
| 3 | **For You Scanner** | Chrome MCP browse | general-purpose | Scroll algorithmic feed for non-searchable targets |
| 4 | **GitHub Pipeline** | X API + web | Bash | GitHub trending/issues → X search queries |
| 5-8 | **Posters** (4x) | X API posting | Bash | Compose unique replies, post via x.py, log |
| 9 | **Quote Tweeter** | X API posting | Bash | Quote-tweet viral posts (2x distribution) |
| 10 | **Thread Diver** | X API posting | Bash | Find viral threads, reply deep in conversation |

**Why this split:**
- Researchers find MORE targets than posters can consume → no idle posters
- Dedicated For You scanner catches posts that don't use searchable keywords
- Quote tweets reach YOUR followers + the OP's audience (double distribution)
- Thread diver finds active conversations where replies get the most eyeballs

**Continuous Loop Protocol (NO IDLE STATES):**
```
Batch 1 (10 agents) → collect results → IMMEDIATELY launch Batch 2
                    → NO reporting, NO waiting, NO idle time
                    → collect results → IMMEDIATELY launch Batch 3
                    → REPEAT UNTIL USER STOPS
```

**CRITICAL: Zero idle time between batches.** As soon as agents finish posting, they IMMEDIATELY start the next search cycle with fresh query angles. Reporting happens in background, not as a blocking step.

**If any agent is idle for >10 seconds, it's failing the protocol.** The goal is 100% agent utilization at all times.

**For You Scanner Workflow (Chrome MCP Fallback):**
1. `tabs_create_mcp()` → save tabId
2. `navigate(url="https://x.com", tabId=...)` → For You feed
3. `read_page(tabId=...)` → scan visible posts
4. `computer(action="scroll", scroll_direction="down", tabId=...)` → scroll 4-5 times
5. `read_page(tabId=...)` after each scroll
6. Look for: AI cost complaints, rate limit pain, student budget issues, free tier frustration
7. Extract targets (author, text, URL, engagement)
8. Post replies via `x.py post` (X API posting still works)
9. **CLOSE TAB when done:** If no targets found after 5 scrolls → close tab immediately
10. **Switch strategy:** Close tab → return to X API search retry

**Chrome Tab Cleanup Protocol (MANDATORY):**
- ❌ NEVER leave tabs open idle
- ❌ NEVER let tabs sit doing nothing
- ✅ Close tab immediately after: no results, exhausted targets, switching strategies
- ✅ One tab per agent max (create → use → close → repeat)
- ✅ If tab isn't actively finding/posting targets, close it NOW

**Tab Lifecycle:**
```
Create tab → Scan feed → Find targets → Post → Close tab → Return to X API search
                      ↓ (if no results)
                   Close tab → Switch strategy → Retry
```

**Existing Tabs Fallback (When Both X API + Chrome MCP Blocked):**

If X API rate limited AND Chrome MCP navigation fails:
1. `tabs_context_mcp()` → list all existing open tabs
2. Check for pre-loaded X search result tabs (from earlier searches)
3. Extract targets from those tabs:
   - `read_page(tabId=...)` → scan existing results
   - Find posts with engagement
   - Post via `x.py post` (posting API works even when search is limited)
4. Close tab when exhausted
5. Move to next existing tab

**Benefits:**
- No new X API searches needed (bypasses rate limit)
- No new Chrome navigation needed (bypasses loading issues)
- Can extract 50-100 targets from existing tabs
- Maintains continuous operation

**Use this when:** Multiple agents report both X API empty responses AND Chrome MCP stuck loading.

**Quote Tweet Strategy:**
- Search for viral posts (min_faves:50+) about AI costs
- Compose original commentary that adds YOUR perspective
- Include share_url as the solution
- Quote tweets get shown to your followers AND appear in the OP's notifications
- 2x distribution: your follower feed + OP's quote tweet list

**Thread Diver Strategy:**
- Find threads with 10+ replies (active conversations)
- Reply deep in the thread where engaged users are reading (not at the top)
- Use `conversation_id:{thread_id}` to explore full threads
- Reference the specific sub-discussion you're joining

---

### X Impressions: How They Work

| Event | Counts as Impression? | Details |
|-------|----------------------|---------|
| Reply appears in timeline/search | Yes (1x per viewer) | When someone scrolls past it |
| Someone expands thread to read replies | Yes (1x per viewer) | Most valuable -- engaged reader |
| Someone clicks your profile from reply | No new reply impression | Profile gets a separate view |
| Someone clicks the link card (share_url) | No new reply impression | But share_url post gets its OWN impression |
| Same person sees it again (re-scroll) | No | X deduplicates per user per session |

**Key insight:** Each reply generates impressions on the REPLY itself, plus the share_url link card generates SEPARATE impressions on your pinned post when people click through. Every reply = dual impression machine.

**Maximizing impressions:**
1. **Reply to posts with 5+ existing replies** -- people reading that thread will see yours
2. **Early replies on rising posts** -- X sorts by engagement; first good reply gets pushed to top
3. **Quote tweets** -- shown to YOUR followers, not just the OP's audience
4. **Thread diving** -- reply to multiple people in same viral thread (3x impressions per thread)
5. **Engagement hooks** -- end with a question to get responses, which pushes your reply higher in sort
6. **Time-sensitive** -- `within_time:3h` catches posts where OP is still online and likely to respond
7. **Fresh over stale** -- recent posts with growing engagement > old viral posts where replies are buried

---

## Compose Mode: `/x compose`

Compose mode creates original content from scraped news, posts it to your profile, then distributes by replying to related conversations.

### Two-Phase Flow

```
Phase 1: NEWS -> COMPOSE -> POST TO PROFILE
  1. Load feed.json news items (RSS, Messari, changelogs)
  2. Pick the most interesting/relevant item for your audience
  3. Write an original tweet with your own take (not just headline)
  4. Post to your profile via X API client or Chrome MCP
  5. Save the new tweet URL

Phase 2: FIND CONVERSATIONS -> DISTRIBUTE
  1. Search X for conversations related to your tweet topic
  2. Find active discussions where your tweet adds value
  3. Reply with a brief comment + link to your original tweet
  4. Each reply must be unique and reference the specific conversation
  5. Log all distribution replies via x.py
```

### Compose Rules

- Pick news most relevant to your project's audience
- Write 1-3 short sentences, casual tone, under 280 chars
- Add your own opinion or insight (not headline rewrite)
- Include a relevant link if the news item has one
- Post to YOUR profile (not as a reply)

### Distribution Rules

- Each distribution reply references the target conversation's topic
- Include the URL of your original tweet (not the news source)
- Follow same tone guidelines as reply mode
- Check post count via `x.py rate-check` between batches

---

## News Mode: `/x news`

Show the scraped news feed without posting.

**Output:**
```
## News Feed (12 items)

### AI & Coding
1. [google_news_ai] Google announces Gemini 2.5 Flash with improved reasoning
2. [vertex_ai] Vertex AI adds new model garden endpoints

### Crypto
3. [messari] Bitcoin ETF inflows hit $2B in single week
4. [cryptonews] Ethereum L2 costs drop 90% after Dencun upgrade

### Dev Tools
5. [claude_code] Claude Code v2.1.40 adds native agent teams
6. [nextjs] Next.js 15.3 released with Turbopack stable

### Browse Hints (check manually)
- https://ai.google.dev/changelog
- https://jules.google.com/changelog
```

---

## Dynamic Research in Post Mode

**CRITICAL:** `/x post` ALWAYS does research on-the-fly. It generates queries dynamically from the post text, navigates X, finds targets, composes unique replies.

**Workflow:**
1. Parse post text and URL
2. Generate search queries dynamically (no prior `/x research` required)
3. If research was run this session, use those rankings as a head start
4. Always explore fresh queries too -- X is dynamic, engagement changes
5. **Always allocate 1 agent to scan the "For You" feed** (even in single-agent mode, check For You first before searching)
6. Navigate top queries, identify targets, compose replies

**Why dynamic:** Prior research may be hours old. Fresh queries catch new hot posts where replies get seen.
**Why "For You":** Algorithmic feed surfaces relevant posts that don't contain searchable keywords.

---

## X Advanced Search Operator Cheatsheet

Claude uses these operators to build smart queries. This reference is always available.

### Engagement Filters

**Priority strategy:** Always target maximum engagement values (highest min_faves, min_retweets, min_replies) combined with recency (`within_time:2d`) and momentum (growing reply counts). Recent high-engagement posts = active discussions where replies get seen.

| Operator | Effect | Example |
|----------|--------|---------|
| `min_faves:N` | Min likes | `AI expensive min_faves:50` |
| `min_likes:N` | Same as min_faves (API name) | `AI expensive min_likes:50` |
| `min_retweets:N` | Min retweets | `free API min_retweets:20` |
| `min_replies:N` | Min replies (high conversation) | `AI cost min_replies:10` |
| `-min_faves:N` | Max likes (negated) | `-min_faves:500` = under 500 likes |
| `filter:has_engagement` | Any engagement at all | Combine with topic keywords |

### Boolean and Grouping

| Operator | Effect | Example |
|----------|--------|---------|
| `word1 word2` | AND (implicit) | `AI expensive` |
| `word1 OR word2` | OR (uppercase required) | `AI OR API OR LLM` |
| `"exact phrase"` | Exact match | `"can't afford"` |
| `(group1) (group2)` | Grouped booleans | `(AI OR API) (expensive OR "can't afford")` |
| `-word` | Exclude | `-is:reply` for original posts only |

### Content Type Filters

| Operator | Effect |
|----------|--------|
| `filter:links` | Has any URL |
| `filter:media` | Has any media |
| `filter:images` | Has images |
| `filter:videos` | Has video |
| `filter:replies` | Is a reply |
| `-filter:replies` | Original posts only |
| `filter:self_threads` | Self-reply threads |
| `filter:quote` | Contains quote tweets |
| `filter:verified` | From verified accounts |
| `filter:safe` | Excludes NSFW |
| `filter:hashtags` | Has hashtags |
| `filter:mentions` | Has @mentions |

### Quote Tweet and Thread Search

| Operator | Effect | Use Case |
|----------|--------|----------|
| `quoted_tweet_id:ID` | All quotes of specific tweet | Find who quoted our gist post |
| `conversation_id:ID` | All tweets in a thread | Read full conversation |
| `url:x.com/user/status/ID` | Find quotes via URL search | Alternative quote search |

### Time and Date

| Operator | Effect |
|----------|--------|
| `since:YYYY-MM-DD` | After date (inclusive) |
| `until:YYYY-MM-DD` | Before date (exclusive) |
| `within_time:2d` | Last 2 days |
| `within_time:3h` | Last 3 hours |

### User Filters

| Operator | Effect |
|----------|--------|
| `from:username` | Posts by user |
| `to:username` | Replies to user |
| `@username` | Mentions of user |
| `filter:follows` | From your follows only |

### Result Sort

| Parameter | Effect |
|-----------|--------|
| `f=top` | Highest engagement (default) |
| `f=live` | Most recent first |
| `f=user` | People/account results |
| `f=image` | Image results |
| `f=video` | Video results |

---

## Clever Reach Strategies

Claude uses these techniques to maximize reply visibility:

1. **Quote tweet mining** -- `quoted_tweet_id:{our_post_id}` to find who quoted the gist post, then check if THEIR followers would benefit too
2. **Thread diving** -- `conversation_id:{viral_thread_id}` to find active threads about AI costs and reply deep in the conversation where engaged users are reading
3. **Negated max engagement** -- `-min_faves:500 min_faves:10` to find posts with moderate engagement (10-500 likes). These are active discussions where replies still get seen, unlike viral posts where replies get buried.
4. **Fresh posts** -- `within_time:2d` to find very recent posts where the poster is still active and likely to see and engage with the reply
5. **Original posts only** -- `-filter:replies` to find original complaints, not replies to complaints (higher visibility)
6. **Verified accounts** -- `filter:verified min_replies:5` for posts by verified users about AI costs. Their audiences are larger.
7. **Follow network** -- `filter:follows` combined with AI keywords to find posts from people you already follow (warmer audience, less likely to be seen as spam)

---

## Research Mode: `/x research [N] [model] {TOPIC}`

Claude autonomously explores X to find the best engagement patterns for a given topic.

### Orchestration Flow

1. **Parse topic** from `$ARGUMENTS`
2. **Parse N and model** -- if provided, spawn N agents with model override via `Task(model=...)`
3. **Validate Chrome MCP** -- `tabs_context_mcp` to ensure browser connected
4. **Generate search queries** -- Claude brainstorms 8-12 X search queries based on the topic, using the operator cheatsheet above
5. **Execute searches** -- for each query (max 8 per research session):
   - Build URL: `https://x.com/search?q={encoded_query}&{params}`
   - `navigate` to search URL
   - `read_page` IMMEDIATELY -- check for "No results for" text
   - **If "No results":** do NOT report failure. Instead:
     1. Strip engagement filters (remove `min_faves:N`, `min_retweets:N`)
     2. Switch to `f=live` if using `f=top` (or vice versa)
     3. Simplify keywords (fewer terms, no exact phrases)
     4. Navigate to new URL and `read_page` again
     5. If still no results after 2 retries, move to next query
   - **If results found:** extract engagement metrics, record query performance
   - Record: query text, result count, total engagement, top post metrics
6. **Score and rank queries** by total reachable audience
7. **Report results** -- which QUERIES found the most engagement (not individual posts)

### Example Report

```
## Research Report: "free AI tools for students"

| Rank | Query | Results | Total Reach | Avg Faves | Best For |
|------|-------|---------|-------------|-----------|----------|
| 1 | "can't afford" API AI (top) | 12 posts | ~45K views | 89 | direct complaints |
| 2 | AI expensive min_retweets:50 | 8 posts | ~120K views | 234 | viral threads |
| 3 | free AI inference broke student | 15 posts | ~8K views | 12 | targeted |
| 4 | Student ID benefits AI | 6 posts | ~18K views | 156 | student lists |

Best approach: queries #1 and #3 for people who directly need help.
Query #2 has more reach but less targeted.

Ready for: /x post {your message with URL}
```

### No-Results Auto-Retry Protocol

When a search returns "No results for..." on the page, Claude MUST NOT report failure. Instead, immediately retry:

```
Original:  "can't afford" API AI min_faves:10  (f=top)
Retry 1:   "can't afford" API AI              (f=live, no engagement filter)
Retry 2:   can't afford AI expensive           (f=live, no quotes, broader terms)
Give up:   Move to next query after 2 retries
```

**Retry rules:**
1. First retry: remove ALL engagement filters (`min_faves`, `min_retweets`, `min_replies`)
2. Second retry: also remove exact phrase quotes, simplify to 2-3 broad keywords, switch sort order
3. After 2 retries with no results: skip query entirely, move to next one
4. NEVER report "no results" to the user without trying retries first

### Research Intelligence

Claude adapts its search strategy as it goes:

- **No results = auto-retry** -- strip filters, broaden terms, switch sort (see protocol above)
- If first queries return low engagement, pivot to different keywords
- If a query finds viral threads, note the common hashtags for the post phase
- Mix `f=live` (recent, active) and `f=top` (highest engagement) per query
- Use negated engagement ranges to find the sweet spot (10-500 faves)
- Track which search operators work best per topic

---

## Post Mode: `/x post [N] [model] {TEXT}`

Claude dynamically composes and posts replies. Every reply is unique. Claude reads each target post and writes a contextual response.

### Orchestration Flow

1. **Parse post text** from `$ARGUMENTS` -- the message intent + URL to share
2. **Parse N and model** -- if provided, spawn N agents with model override via `Task(model=...)`
3. **Dynamic research on-the-fly** -- ALWAYS generates queries dynamically (no prior `/x research` required). If research was run this session, use those rankings as a head start, otherwise brainstorm fresh queries based on the post text and URL context.
4. **Navigate to top queries** -- start with queries that reach the most users
5. **For each query result page:**
   - `read_page` IMMEDIATELY -- check for "No results for" text
   - **If "No results":** auto-retry (same logic as research mode):
     1. Strip engagement filters from query
     2. Switch `f=top` <-> `f=live`
     3. Simplify keywords
     4. Retry up to 2 times, then skip to next query
   - **If results found:** identify reply-worthy posts (high engagement, relevant topic)
   - Check `x.py check {url}` -- skip already-replied posts
   - For each target post:
     - Read the post content, author, context
     - Claude writes a unique reply following the tone guidelines below
     - Include the URL from the user's post text
6. **Auto-post via X API** -- NO user approval needed. If a target post has traction (any engagement: likes > 0 OR replies > 0 OR views > 50), post immediately:
   - `python skills/x/scripts/x.py post {tweet_id} "{reply text with SHARE_URL}"`
   - X API client posts via HTTP API in 1-2 seconds -- no browser needed
   - **Fallback (if X API client fails):** use Chrome MCP browser posting (see Chrome MCP section)
   - **ALWAYS include the `share_url`** from config
7. **Log each reply** via `python skills/x/scripts/x.py log {target_url} {author} {reply_text} {topic} {query} {reach}`
8. **IMMEDIATELY move to next target** -- no waiting, no screenshots. Post -> log -> next -> post -> log -> next.
9. **Report summary after ALL posts complete** -- N posted, total reach estimate, list of targets

**Traction threshold:** Post if target has ANY of: likes > 0, replies > 0, retweets > 0, views > 50. Skip only zero-engagement posts with < 50 views.

**No approval gate.** The user trusts the dynamic targeting. Just post and report results.

---

## Human Tone Guidelines — ENGAGEMENT FIRST

**CRITICAL:** Every reply MUST drive engagement. Not just funny observations — trigger RESPONSES.

### 4 Reply Strategies (Mix These Every Session)

**1. Question Strategy (30%) — Trigger Discussion:**
```
"wait how are you handling rate limits with that many requests"

"what's your retry logic look like when gemini hits quota"

"are you pooling accounts or using a single key"

"how'd you get around the email verification rate limits"
```

**2. Helpful Strategy (40%) — Solve Their Problem:**
```
"if you're hitting rate limits, pool free gmail accounts for gemini flash. ~300 rpm, zero cost"

"ran into same issue. switched to account rotation and went from 60 to 300 rpm overnight"

"the email-based quota thing is annoying but you can script gmail account creation pretty easily"

"gemini flash has per-email quotas not per-api-key. that's the unlock"
```

**3. Funny + Helpful (20%) — Entertain AND Solve:**
```
"paying for api calls when free gmail accounts exist. check gswarm - pools accounts for 300rpm gemini flash"

"love how we all pretend openai pricing is normal. anyway here's how to dodge it entirely: [solution]"

"spending $50/mo on api calls is peak 2024 energy. gswarm does 300 rpm gemini flash for literally zero cost"
```

**4. Informative Strategy (10%) — Teach Something:**
```
"gemini flash quotas are per gmail account not per api key. pool 100 accounts = 100x the free tier"

"the trick is email-based quotas. create accounts programmatically, rotate through them, zero api cost"

"free tiers reset daily per account. 60 accounts × 50 calls/day = 3000 free calls daily"
```

### CRITICAL: What Triggers RESPONSES vs Scrolling Past

**❌ BLOCKED - Passive Observations (NO engagement hook):**
```
"this is wild"  ← passive, no response trigger
"hits different"  ← observation without hook
"lowkey this slaps"  ← no reason to reply
"the way this works is crazy"  ← dead end
"respect"  ← one-word approval, conversation killer
```

**❌ BLOCKED - Wikipedia/Narrator Tone:**
```
"This is an interesting approach..."  ← textbook
"Furthermore, it's worth noting..."  ← narrator
"This allows developers to..."  ← feature description
```

**✅ GOOD - Engagement Hooks:**
```
"wait how are you scaling this"  ← question = response trigger
"ran into same issue. pool gmail accounts for gemini quotas - went from 60 to 300 rpm"  ← helpful = thanks response
"spending $50/mo on openai when gemini flash is free. check gswarm for account pooling"  ← solution reference
"debugging with console.log in 2026. anyway here's how to actually profile node apps: [tip]"  ← funny + helpful
```

### Engagement Hook Patterns (USE THESE)

**1. Question Hooks:**
- "wait how are you [specific action]"
- "what's your [solution] look like"
- "are you using [approach] or [alternative]"
- "how'd you solve [specific problem]"

**2. Solution Hooks:**
- "ran into same issue. [solution that worked]"
- "if you're hitting [problem], [specific fix]"
- "[their issue] is brutal. switched to [solution] and [result]"
- "the [tool/trick] thing is [insight]. that's the unlock"

**3. Funny + Helpful Hooks:**
- "love how we all [shared misconception]. here's what actually works: [solution]"
- "[their struggle] is peak [year] energy. [solution] does [benefit] for zero cost"
- "paying for [expensive thing] when [free alternative] exists. check [solution]"

**4. GSwarm Reference Patterns (Natural, Not Sales-y):**

**Problem → Personal Solution → Tool Pattern:**
```
"I had this exact issue with [their problem].

What worked: [brief solution explanation]

Built a tool for it: [GSwarm mention]"
```

**Examples:**
- "ran into same issue. pool gmail accounts for gemini quotas - went from 60 to 300 rpm"
- "hit those limits building [related project]. switched to account rotation and the 300 rpm solved it"
- "email-based quotas are the hack. gswarm automates the account pooling part"
- "if you're paying for api calls, account rotation gets you gemini flash for free. check gswarm"

**RED FLAGS (validation will block):**
- ❌ "Check out my tool!"
- ❌ "You should try [product]"
- ❌ Starting with the link
- ❌ No value before URL

### X Algorithm Reality (2026)

**CRITICAL:** Replies = 13.5x More Valuable Than Likes

The X algorithm heavily prioritizes reply engagement. Posts generating conversation receive 3-4x more distribution than posts with equivalent like counts but fewer replies.

**70/30 Rule:** 70% engagement with others' content, 30% original posts. Days with heavy replies to other accounts (even with fewer original posts) drive most profile visits.

**Two-Tweet Pattern (Link Suppression Workaround):**
1. **Main Reply:** Native value, no links (optimized for algorithmic visibility)
2. **Follow-Up Reply:** Add GSwarm link in self-reply to your main reply

Example:
```
Main: "ran into same issue. pool gmail accounts for gemini quotas - went from 60 to 300 rpm overnight"
Follow-up (reply to self): "full setup guide + gswarm tool: [link]"
```

**Why This Works:** Main reply gets algorithmic boost (no link suppression), follow-up directs interested users to resource without hurting main reply's reach.

### Style Guidelines:

- **Length:** 10-30 words (substance over brevity)
- **Caps:** lowercase casual (not strict)
- **Engagement:** EVERY reply needs a hook (question, solution, or helpful tip)
- **References:** Use two-tweet pattern OR mention GSwarm naturally in main reply
- **Tone:** Helpful friend, not salesperson
- **Self-aware humor** (laughing with, not at)
- Use: "me:", "when", "wait", "*action*", "narrator:"

### DON'T:

- Explain the joke after delivering it
- Use proper grammar/caps (too formal)
- Go over 20 words (loses punch)
- Be mean-spirited (playful teasing only)
- Add periods at end (kills comedic timing)
- Use hashtags in the joke itself

### URL Strategy (MANDATORY)

**ALWAYS link to the user's configured `share_url`, NEVER directly to the source repo.**

- **USE:** The `share_url` from config (auto-loaded from .env or config.json)
- **NEVER:** Direct links to GitHub repos, gists, or source code

**Why:** Linking to the user's X post drives impressions to their profile. Direct repo links bypass their social presence entirely. Every reply MUST include the configured share URL.

Claude reads the `share_url` at the start of each `/x` session and includes it in every generated reply.

### Automated Quality Validation (Prevents "AI Slop")

**CRITICAL: All replies validated by `sanitize_reply_text()` before posting.**

**Auto-blocked patterns:**

**Vague/Generic (no substance):**
- Single-word: "Nice!", "Cool!", "Great!"
- Generic: "This is great", "Love this", "Thanks for sharing"
- Low-effort: "Totally agree", "So true", "Exactly"
- Too short: < 20 chars without "?"

**Wikipedia/Narrator Tone (sounds like a bot):**
- Formal transitions: "Furthermore", "Moreover", "Additionally"
- Impersonal: "One can", "It is worth noting"
- Feature descriptions: "This allows developers to..."
- Marketing speak: "comprehensive", "robust", "powerful"
- Wikipedia style: "The solution provides..."
- Forced double questions at end

**What passes validation:**
- Sounds like texting a friend
- References SPECIFIC details from their post
- Natural flow (not a template)
- Questions OPTIONAL (only if genuinely curious)
- 20+ chars with substance

**Example - BLOCKED:**
```
"Nice!"  ❌ (vague, single-word)
"This is great"  ❌ (generic, no substance)
"Thanks for sharing"  ❌ (low-effort acknowledgment)
```

**Example - PASSES:**
```
"been there with rate limits - this pools gmails for 300rpm"  ✅ (specific, helpful)
"wait you're paying /mo? there's a free 300rpm option"  ✅ (references cost, offers solution)
"how did you handle the auth flow? ran into CORS issues myself"  ✅ (specific question)
```

---

## X API Backend (Primary -- Fast API Posting)

The unified `x.py` script handles all X API operations. It uses HTTP API calls (1-2 sec/post) instead of browser automation (17 sec/post).

### Setup (One-Time)

```bash
# Manual cookie input (from Cookie-Editor extension)
python skills/x/scripts/x.py cookies <ct0> <auth_token>

# Verify auth works
python skills/x/scripts/x.py test
```

Cookies saved to `skills/x/data/cookies.json` (gitignored).

### Search (X API)

```bash
python skills/x/scripts/x.py search "\"can't afford\" API AI min_faves:10"
# Returns JSON: { "tweets": [{ "id", "text", "author", "likes", "retweets", "views", "url" }] }
```

### Post Reply (X API)

```bash
python skills/x/scripts/x.py post "TWEET_ID" "reply text with {SHARE_URL}"
# Returns JSON: { "success": true, "tweet_id": "..." }
```

### Post Original Tweet (X API) -- REQUIRES USER APPROVAL

**NEVER call this without explicit user approval.** See "Profile Post Approval Rule" above.

```bash
# ONLY after user explicitly approves the draft:
python skills/x/scripts/x.py tweet "tweet text with optional URL"
# Returns JSON: { "success": true, "tweet_id": "...", "url": "..." }
```

**Subagents MUST NOT call `x.py tweet`.** Only the main orchestrator, after user says yes.

### Post Flow (Speed-Optimized)

```
search -> pick target -> compose reply -> POST -> next target -> compose -> POST -> next...
```

No browser needed. Each post takes 1-2 seconds. Agent moves IMMEDIATELY to next target after posting.

1. `x.py search "{query}"` -> get list of targets
2. `x.py check {url}` -> skip already-replied
3. Claude composes unique reply (with X post URL, NOT gist)
4. `x.py post {tweet_id} "{reply}"` -> posts instantly
5. `x.py log {url} {author} {text} {topic} {query} {reach}` -> track
6. **IMMEDIATELY move to next target** -- no waiting, no screenshots, no page loads

### Speed Rules

- **NO browser navigation between posts** -- X API client posts via HTTP, no page loads
- **NO screenshots for verification** -- trust the API response (success/failure JSON)
- **NO waiting between posts** -- post -> log -> next -> post -> log -> next
- **Compose while posting** -- start writing the next reply while the current one posts
- **Be creative** -- every reply MUST be different in structure, tone, and approach
- **Reference their specific pain point** -- read their post, respond to THEIR situation

---

## Chrome MCP (Fallback + Visual Research)

Chrome MCP is kept as fallback for visual research and when X API client auth expires.

### When to Use Chrome MCP

- **Visual research** -- screenshot search results to understand engagement patterns
- **For You feed scanning** -- scroll the algorithmic feed to find targets search misses
- **Auth expired** -- if X API client cookies expire, use Chrome MCP while re-authenticating
- **Verification** -- spot-check that replies were posted correctly
- **Compose mode** -- posting original tweets to your profile

### Post Operations (Chrome MCP Fallback)

1. **Navigate to target** -- `navigate(url="https://x.com/user/status/123", tabId=...)`
2. **Wait for load** -- `computer(action="wait", duration=2, tabId=...)`
3. **Click reply box** -- `find(query="reply", tabId=...)` then `computer(action="left_click", ref="ref_N", tabId=...)` to focus the contenteditable div
4. **Type reply** -- `computer(action="type", text="reply text...", tabId=...)` (X uses contenteditable div, NOT a form input -- `form_input` will fail)
5. **Click Post** -- `find(query="Reply", tabId=...)` to locate Post/Reply button, then `computer(action="left_click", ref="ref_M", tabId=...)` -- NO user approval needed

### Multi-Agent Chrome Tab Coordination

When `N > 1` and using Chrome MCP:

- Each agent calls `tabs_create_mcp()` to get its own unique `tabId`
- Chrome MCP caps at ~5 concurrent tabs reliably. Beyond 5, use Playwriter for overflow.
- Agents MUST track their own tabId and only interact with their assigned tab

---

## Safety and Rate Limiting

| Rule | Implementation |
|------|----------------|
| **PROFILE POSTS NEED APPROVAL** | `x.py tweet` (original tweets, quote tweets, retweets) REQUIRE explicit user approval. Subagents MUST NEVER call `x.py tweet`. |
| **Replies are autonomous** | `x.py post` (replies to others) need NO approval -- this is the core workflow |
| **Auto-post on traction** | If target has likes > 0 OR replies > 0 OR views > 50, reply immediately |
| **Post tracking** | Daily counter in history.json, check via `x.py rate-check` |
| **Dedup protection** | SHA256 of target_url checked before composing |
| **Unique text per reply** | Claude generates fresh text, no repeated messages |
| **Human tone enforced** | SKILL.md tone guidelines with 3-tone rotation (steal/sarcastic/empathetic) |
| **Logged history** | Every post tracked with timestamp, topic, author, reach |
| **For You feed agent** | 1 dedicated agent always scans For You feed for non-searchable targets |
| **Shell-safe posting** | ALWAYS use `echo '...' \| python x.py post ID --stdin` to prevent `$` expansion |
| **Number integrity** | European format: `.` for thousands, `,` for decimals. Always include `$` before amounts. |

### Number Formatting Rules

**CRITICAL**: All dollar amounts and large numbers must follow these rules:

| Pattern | Correct | Wrong |
|---------|---------|-------|
| Thousands separator | `$1.256/year` | `$1,256/year` |
| Dollar zero | `$0` | (shell expands to `/usr/bin/bash`) |
| Dollar amounts | `$200/mo` | `00/mo` (stripped `$`) |
| Small decimals | `$0.004` | `/usr/bin/bash.004` |
| Large numbers | `5.660` | `5,660` or `,660` |

**Shell safety**: The `$` character is special in bash. When posting via x.py:
- ALWAYS use: `echo 'text with $0 and $100' | python x.py post TWEET_ID --stdin`
- NEVER use: `python x.py post TWEET_ID "text with $0"` (shell expands `$0` to process name)
- Single quotes `'...'` prevent ALL shell expansion — no need to escape `!` `?` `"` `'`
- **NEVER add backslashes** before punctuation (`\!` `\?` `\"` `\'`) — they become literal in the post
- The `--stdin` flag reads text from pipe, bypassing shell argument parsing

---

## Advanced Outreach Strategies

Claude uses these techniques beyond basic search to find high-value targets and maximize impressions.

### GitHub-to-X Pipeline

Find frustrated users via GitHub, then target them on X:

1. **GitHub Trending** -- scan `github.com/trending?since=daily` for AI/ML repos. Users starring/forking free AI tools (Ollama, vLLM, LocalAI, LiteLLM, Jan) are likely cost-conscious
2. **Issue mining** -- search GitHub issues for "rate limit", "quota exceeded", "billing", "free tier" in popular AI repos. Issue authors often have X handles in their GitHub profile
3. **Star-to-X** -- users starring budget AI tools (`ollama/ollama`, `vllm-project/vllm`, `mudler/LocalAI`) are the exact target audience
4. **Release announcements** -- when free AI tools release new versions, find the announcement tweets and reply in the thread

**X search queries for GitHub users:**
```
"just deployed" (ollama OR vllm OR localai) min_faves:5
"rate limited" (openai OR anthropic OR gemini) within_time:3d
"free tier" API (AI OR LLM) -filter:replies min_faves:3
```

### npm/pip Ecosystem Targeting

Find developers hitting cost walls through package ecosystems:

1. **Cost-sensitive packages** -- users of `@ai-sdk/openai`, `litellm`, `openrouter` are actively managing API costs
2. **CLI tool users** -- people tweeting about `gemini-cli`, `claude-code`, `aider` often hit rate limits
3. **Frustration patterns** -- search for: "just spent $50 on OpenAI", "API bill", "rate limit hell", "billing surprise"
4. **Migration signals** -- users moving from paid to free: "switching from OpenAI", "trying ollama", "self-hosting"

**X search queries for package ecosystem:**
```
(npm OR pip) install (ollama OR litellm OR "ai-sdk") within_time:7d
"API bill" (shocked OR surprised OR expensive) min_faves:3
"switching from" (openai OR anthropic) to (free OR local OR self-host)
```

### Newcomer Cross-Promotion

Find new open-source projects and their communities for mutual benefit:

1. **ProductHunt launches** -- AI tools launching on ProductHunt have active X promotion. Reply to launch threads with genuine help
2. **Indie hackers** -- solo devs building AI wrappers, often tweeting progress. Their followers are your audience
3. **First-time OSS** -- new repos with < 100 stars but active maintainers. Engage early, build relationships
4. **Hackathon winners** -- devathon/hackathon projects often need free API access. Search `hackathon AI` + `won` or `built`

**X search queries for newcomers:**
```
"just launched" (AI OR LLM) (free OR open-source) within_time:7d min_faves:5
"building in public" (AI OR API) -filter:replies
"side project" (inference OR LLM OR API) within_time:14d
"hackathon" (AI OR LLM) (built OR won OR demo) within_time:7d
```

### Growth Hacking Tactics

Maximize reply visibility and follower conversion:

1. **Reply multiplier (75x)** -- X algorithm gives replies 75x more reach than new posts. Always reply, never cold-post
2. **Quote tweet chains** -- quote-tweet your OWN reply to add context. Your followers see the quote, the original author sees the reply
3. **Thread hijacking** -- find viral threads about AI costs (10K+ views), reply deep in the conversation where engaged users are actively reading. Use `conversation_id:{thread_id}`
4. **Timing optimization** -- post during 9-11 AM EST (US) and 2-4 PM EST (EU overlap) for maximum engagement window
5. **Hook pattern** -- start reply with the reader's pain point, not your solution. "api costs are brutal" > "check out this free tool"
6. **Cross-platform seeding** -- share X posts to Reddit r/LocalLLaMA, r/selfhosted, HackerNews. Traffic back to X boosts algorithmic ranking
7. **Engagement stacking** -- like + reply + quote in sequence. X's algorithm weighs multi-signal engagement higher

### Target Prioritization Matrix

| Priority | Signal | Why | Query Pattern |
|----------|--------|-----|---------------|
| P1 | Direct cost complaint | Immediate need | `"can't afford" OR "too expensive" (AI OR API)` |
| P2 | Rate limit frustration | Active pain point | `"rate limit" OR "quota" (hit OR exceeded OR stuck)` |
| P3 | Free tier exploration | Shopping for solutions | `"free tier" OR "free alternative" (AI OR LLM)` |
| P4 | OSS migration | Considering switch | `"switching to" OR "trying" (ollama OR local OR self-host)` |
| P5 | Student/broke dev | Budget-constrained | `student (AI OR API OR LLM) (expensive OR cost OR afford)` |

---

## History Mode: `/x history`

Show posting history from `skills/x/data/history.json`.

**Usage:**
```
/x history
/x history --days 7
/x history --topic "free AI tools"
```

**Output:**
```
## Posting History (Last 7 Days)

| Date | Target | Author | Topic | Reach |
|------|--------|--------|-------|-------|
| 2026-02-12 | https://x.com/user/... | @divyansh_ai | free AI tools | 471 views |
| 2026-02-11 | https://x.com/user/... | @psssnikhil1 | free AI tools | 1.2K views |

Total: 5 replies, ~8.3K combined reach
```

---

## Status Mode: `/x status`

Show daily/weekly post counts and reach estimates.

**Output:**
```
## /x Status Report

**Today:** 3 replies, ~2.1K reach
**This Week:** 12 replies, ~18.5K reach
**This Month:** 24 replies, ~45.3K reach

**Top Topics:**
1. free AI tools for students (8 replies, ~12K reach)
2. broke developers rate limits (4 replies, ~6.5K reach)
```

---

## Help Mode: `/x help`

Show usage help.

**Output:**
```
# /x Skill -- X/Twitter Outreach

**Research:** /x research [N] [model] {TOPIC}
  Explore X queries, rank by engagement
  Example: /x research 5 sonnet free AI tools for students

**Post:** /x post [N] [model] {TEXT with URL}
  Compose unique replies, post via X API (fast) or Chrome MCP (fallback)
  Example: /x post 10 opus Tell users about our free tool {SHARE_URL}

**Compose:** /x compose
  Pick news item, compose original tweet on profile, distribute via replies
  News sources: Google News RSS, Messari API, Claude Code changelog, more

**Campaign:** /x campaign [N] [model] {TOPIC}
  Spawn N-agent team for continuous posting (research → post → repeat)
  Uses TeamCreate + persistent agents. Runs until `/x stop`.
  Example: /x campaign 10 sonnet AI cost complaints

**Stop:** /x stop
  Shutdown active campaign: sends shutdown_request to all agents, TeamDelete, final stats
  Only works when a campaign is active (x-campaign team exists)

**News:** /x news
  Show current scraped news feed (RSS, crypto, changelogs)

**History:** /x history [--days N] [--topic T]
  Show posting history

**Status:** /x status
  Show daily/weekly counts + reach. During active campaign: includes agent count + runtime

**Model Selection:**
  [N] -- number of parallel agents (default: 1, campaign default: 10)
  [model] -- opus, sonnet, or haiku (default: sonnet)
  Campaign mode BLOCKS opus (continuous loops burn quota)

**Post Tracking:**
  Check count: /x status
```

---

## GitHub-to-X Pipeline: `/x github`

Unified command that scans GitHub (trending repos, cost issues, releases), maps users to X handles via the GitHub API `twitter_username` field, and generates targeted X search queries.

### Usage

```bash
/x github                    # Scan GitHub, map users, generate queries
/x github --search           # Same + search X API for each query
/x github --search --limit 30  # Increase lookup/search limit (default: 20)
/x github --json             # Machine-readable JSON output for agents
```

### 5-Phase Pipeline

```
Phase 1: SCAN GITHUB
  - Trending repos (scrape_trending_repos)
  - Cost/rate-limit issues (scrape_cost_issues)
  - New releases (scrape_new_releases)
  → Collects repo owners, issue authors, release maintainers

Phase 2: COLLECT USERNAMES
  - Deduplicates across all sources
  - Tracks source context per user (which repo/issue/release)
  - Limits to --limit users (default 20)

Phase 3: LOOK UP X HANDLES
  - GitHub API: GET /users/{username} → twitter_username field
  - 24-hour cache in feed.json → github_users key
  - Uses gh CLI (5000 req/hr) with urllib fallback (60 req/hr)

Phase 4: GENERATE QUERIES
  For users WITH X handle:
    - from:{handle} (AI OR API OR LLM) within_time:7d
  For users WITHOUT X handle (repo context):
    - "{repo_name}" (launched OR released OR built) min_faves:3
  For issue authors:
    - from:{handle} ("rate limit" OR "too expensive" OR "can't afford")
  For release-related:
    - "{repo}" (update OR release OR "new version") within_time:7d

Phase 5: SEARCH X (optional, --search flag)
  - Runs x.py search for each generated query
  - Collects targets with engagement metrics
  - Outputs combined target list sorted by views
```

### Caching

GitHub user lookups are cached in `feed.json` under the `github_users` key with 24-hour TTL. Subsequent runs skip cached users, making repeated calls fast.

### Example Output

```
== GitHub-to-X Pipeline ==

Phase 1: Scanning GitHub...
  Trending repos: 25
  Cost issues: 15
  New releases: 5

Phase 2: Collected 30 unique GitHub users

Phase 3: Looking up X handles (max 20)...
  Found X handles: 8/20

Phase 4: Generated 32 X search queries
  - Direct handle queries: 8
  - Repo context queries: 12
  - Issue context queries: 7
  - Release queries: 5

== Top Targets (by views) ==
  @user1 - 45K views - "switching to local inference..."
  @user2 - 12K views - "rate limits are killing my app..."
```

### Agent Integration

Use `--json` flag for programmatic consumption by posting agents:

```bash
# Agent reads targets, posts replies
targets=$(python x.py github --search --json --limit 15)
# Parse JSON: { "users": [...], "queries": [...], "targets": [...] }
```

### How It Connects to `/x post`

The GitHub pipeline feeds into the standard post workflow:

1. Run `/x github --search` to discover targets from GitHub ecosystem
2. Targets include users who maintain free AI tools, file cost issues, release alternatives
3. Feed these into `/x post` agents or use the targets directly for reply composition
4. All replies still follow human tone guidelines and include `share_url`

---

## Auto-Feed Integration

The scraper (`x.py scrape`) aggregates multiple sources into `data/feed.json`:

### Data Sources

| Source | Type | Items | API |
|--------|------|-------|-----|
| GitHub Trending | Repos | ~25 | `gh` CLI or urllib |
| GitHub Issues | Frustration signals | ~15 | `gh` CLI or urllib |
| GitHub Releases | New versions | ~10 | `gh` CLI or urllib |
| Google News RSS | AI, crypto, coding | ~30 | stdlib XML |
| Google Cloud Feeds | Gemini, Vertex AI | ~10 | stdlib XML |
| Messari API | Crypto news | ~10 | HTTP (needs key) |
| Markdown Changelogs | Dev tools | ~5 | HTTP |

### How Claude Uses the Feed

**In `/x research`:**
1. Check `data/feed.json` -- if exists and fresh (< 12h old), load pre-computed queries
2. Use feed queries as the FIRST batch (already prioritized P1-P5)
3. Generate additional dynamic queries based on the topic
4. Report combined results (label feed vs dynamic queries)

**In `/x post`:**
1. Load feed queries (P1 first) as initial search set
2. Add dynamic queries from the post text
3. Feed queries run faster -- no query brainstorming needed
4. Still generate unique replies per target (feed provides queries, not templates)

**In `/x compose`:**
1. Load news items from feed.json
2. Pick the most interesting/relevant for your audience
3. Compose original tweet with your own take
4. Use feed queries for distribution (Phase 2)

**In `/x auto`:**
1. Run scraper first (update feed.json)
2. Load fresh feed queries + news
3. Execute post or compose mode with feed data
4. All automatic -- no human in the loop

### Feed JSON Schema

```json
{
  "last_updated": "2026-02-12T15:00:00Z",
  "repos": [{"name": "owner/repo", "stars": 1234, "topics": [...]}],
  "issues": [{"title": "...", "repo": "...", "author": "..."}],
  "releases": [{"repo": "ollama/ollama", "tag": "v0.5.0"}],
  "news": [
    {
      "title": "Google announces Gemini 2.5 Flash",
      "url": "https://...",
      "source": "google_news_ai",
      "category": "ai",
      "published": "2026-02-12T10:00:00Z",
      "summary": "Brief description..."
    }
  ],
  "browse_hints": [
    {
      "url": "https://ai.google.dev/changelog",
      "source": "google_ai_changelog",
      "reason": "Check for fresh Gemini API updates"
    }
  ],
  "queries": [
    {
      "query": "\"can't afford\" API AI min_faves:5 within_time:3d",
      "priority": "P1",
      "source": "standard|github_trending|github_issues|github_releases|news",
      "context": "Why this query matters"
    }
  ],
  "stats": {
    "repos_found": 25,
    "issues_found": 15,
    "news_scraped": 30,
    "queries_generated": 42
  }
}
```

### Scraper Commands

```bash
# Manual run
python skills/x/scripts/x.py scrape              # All sources -> feed.json
python skills/x/scripts/x.py feed                # Show current feed + news
python skills/x/scripts/x.py scraper-status      # Scheduler + feed status

# Scheduler (Windows Task Scheduler)
python skills/x/scripts/x.py scraper-install 6   # Run every 6 hours
python skills/x/scripts/x.py scraper-uninstall   # Remove scheduler
```

---

## Headless Auto Mode: `/x auto [N] [model]`

Fully automated pipeline: scrape all sources -> generate queries -> find targets -> compose replies -> post. Runs headless via `claude -p` (non-interactive).

### How It Works

When Claude receives `/x auto`, it:

1. **Runs scraper** -- `python x.py scrape` to refresh feed.json (GitHub + RSS + Messari + changelogs)
2. **Loads feed** -- reads pre-computed queries + news from feed.json
3. **Executes post mode** -- navigates X via Chrome MCP, finds targets, composes unique replies, posts via X API client
4. **Reports results** -- logs everything to history.json

### Auto-Post Script

For true background automation, use the `auto` subcommand:

```bash
# Reply mode (default) -- find targets, post replies
python skills/x/scripts/x.py auto --posts 5 --model sonnet

# Compose mode -- create original tweet from news + distribute
python skills/x/scripts/x.py auto --mode compose --posts 3 --model sonnet

# Dry run -- scrape + research, no posting
python skills/x/scripts/x.py auto --dry-run

# Install scheduler (runs every 12h)
python skills/x/scripts/x.py poster-install 12

# Check status
python skills/x/scripts/x.py poster-status
```

**Model routing for auto mode (MANDATORY):**

| Component | Model | Why |
|-----------|-------|-----|
| Scraper (all sources) | Python script | No LLM needed -- pure HTTP calls |
| Research (query execution) | Sonnet | Good enough for navigating X search |
| Reply composition | Sonnet | Adequate for human-tone short replies |
| Post execution | Haiku | Simple X API calls, no reasoning |

**NEVER use Opus for auto mode** -- it runs on a schedule and would drain weekly Opus quota. Sonnet handles all /x tasks well. Use Haiku for simple posting loops.

### Scheduler + Headless Integration

The scraper scheduler runs as a Windows Task Scheduler job:

```
Every 6h: python x.py scrape                    # Updates feed.json (no LLM)
Every 12h: python x.py auto --posts 5 ...       # Headless Claude posts using fresh feed
```

To install both:

```bash
# Install scraper (every 6h)
python skills/x/scripts/x.py scraper-install 6

# Install headless poster (every 12h)
python skills/x/scripts/x.py poster-install 12
```

### Safety in Auto Mode

- Post count tracked via history.json (no hard limits)
- Dedup still enforced (SHA256 of target URL)
- Human tone guidelines still apply (Sonnet follows SKILL.md instructions)
- All posts logged to history.json for review
- Feed freshness check: skip if feed.json > 24h old (scraper probably failed)

---

## Campaign Mode: `/x campaign [N] [model] {TOPIC}`

Continuous multi-agent posting using Ralph-style TeamCreate + TaskCreate. Spawns a persistent team of N agents that work continuously (research → compose → post → repeat) until explicit user shutdown.

**Default:** N=10, model=sonnet. Opus is BLOCKED (continuous loops burn weekly quota in hours).

### CRITICAL: Profile + Self-Reply Block (HARD ENFORCED)

Campaign agents operate under absolute restrictions — they ONLY reply to OTHER users' posts:

| Action | Allowed? | Enforcement |
|--------|----------|-------------|
| Reply to OTHER users' posts | YES | Core workflow — `x.py post` |
| `x.py tweet` (original profile post) | BLOCKED | Command not included in agent prompts |
| Reply to OUR OWN posts | BLOCKED | `x.py check-author {tweet_id}` before every post |
| Quote tweet our own posts | BLOCKED | Check author matches X_HANDLE → skip |
| Retweet | BLOCKED | No retweet commands in agent prompts |

**Every agent prompt includes:**
```
HARD BLOCK: NEVER call x.py tweet. NEVER reply to posts by {X_HANDLE}.
Before posting: run `x.py check-author {tweet_id}`. If exit code 1, SKIP this target.
```

### Agent Roles (10 Default)

| # | Name | subagent_type | Purpose |
|---|------|---------------|---------|
| 1-2 | `researcher-1`, `researcher-2` | Bash | X API search, collect targets, report to posters |
| 3 | `foryou-scanner` | general-purpose | Chrome MCP feed scroll for non-searchable targets |
| 4 | `github-pipeline` | Bash | GitHub trending → X queries via `x.py github --search` |
| 5-8 | `poster-1..4` | Bash | Compose unique replies, post via x.py, log |
| 9 | `quote-tweeter` | Bash | Quote-tweet viral posts (2x distribution) |
| 10 | `thread-diver` | Bash | Reply deep in active threads via conversation_id |

ALL agents use `Task(model="sonnet")`. Campaign NEVER uses Opus.

### State Machine (2 States)

```
CAMPAIGN_ACTIVE → SHUTDOWN
```

- **CAMPAIGN_ACTIVE:** All agents loop continuously. Team lead monitors for critical errors only.
- **SHUTDOWN:** User requests stop → SendMessage(shutdown_request) to all → TeamDelete()

No RETRY_CHECK, VERIFY_FIX, or REVIEW phases. Posts are short replies validated by `sanitize_reply_text()`.

### Orchestration Flow

**Phase 1: Setup (team lead executes in a SINGLE message)**

```
1. Parse args: N, model, topic
2. IF model == "opus": BLOCK with "Campaign uses sonnet/haiku only". STOP.
3. Run: python skills/x/scripts/x.py scrape    (refresh feed.json)
4. TeamCreate(team_name="x-campaign")
5. TaskCreate milestone tasks:
   - "MILESTONE-1: Post 50 replies" (activeForm: "Posting replies")
   - "MILESTONE-2: Post 150 replies" (activeForm: "Scaling outreach")
   - "MILESTONE-3: Post 300 replies" (activeForm: "Maximum reach")
6. Spawn ALL N agents in ONE message (multiple parallel Task() calls)
```

**Phase 2: Active (continuous, team lead monitors)**

```
- Agents work silently (WORK SILENTLY protocol — NO progress reports)
- Team lead ONLY responds to:
  a) User queries ("how's it going?" → run `x.py status`, report)
  b) Critical agent errors (auth expired, Chrome broken)
- NO agent reassignment needed (agents find work dynamically via search)
- NO idle enforcement (agents self-enforce via continuous loop)
```

**Phase 3: Shutdown (triggered by `/x stop`)**

```
1. SendMessage(type="shutdown_request", recipient="{agent-name}") to EACH agent
2. Wait for all shutdown_response(approve=true)
3. TeamDelete()
4. Run `x.py status` for final campaign report
```

### Agent Prompt Templates

Every agent gets a role-specific prompt. All prompts share a **Common Rules Block** injected at the top:

#### Common Rules Block (ALL agents)

```
You are agent "{name}" in X campaign team "x-campaign".
Topic: {TOPIC}
Share URL: {SHARE_URL}
Your handle: {X_HANDLE}

== HARD SAFETY BLOCKS ==
- NEVER call `x.py tweet` (no profile posts)
- NEVER reply to posts by {X_HANDLE} (no self-replies)
- Before EVERY post: run `python ~/.claude/skills/x/scripts/x.py check-author {tweet_id}`
  - Exit 0 = safe to reply (different author)
  - Exit 1 = BLOCKED (our own post, SKIP immediately)
- NEVER quote-tweet or retweet posts by {X_HANDLE}

== CONTINUOUS LOOP (NO IDLE STATES) ==
Work continuously until you receive a shutdown_request. NO exceptions.
Loop: Search → Post → Log → IMMEDIATELY Search (no breaks, no reports)
WORK SILENTLY. NEVER send status updates, progress reports, or milestone messages.
Only contact team lead for CRITICAL errors: auth expired, Chrome completely broken.

== RATE LIMIT HANDLING ==
1. Hit rate limit → wait 60s → retry with NEW query angle
2. Still limited → wait 120s → try completely different query
3. Still limited → wait 180s → cycle through all targeting strategies
4. NEVER stop. NEVER go idle. Rotate strategies forever.

== EMPTY RESULTS HANDLING ==
1. No results → strip engagement filters (remove min_faves, min_retweets)
2. Still empty → switch f=top <-> f=live, simplify to 2-3 broad keywords
3. Still empty → try different time window (within_time:1d → 3d → 7d)
4. Cycle all combinations, then restart with new topic angle

== POSTING RULES ==
- ALWAYS include {SHARE_URL} in replies
- Use shell-safe posting: echo '...' | python x.py post ID --stdin
- Two-tweet pattern: main value reply (no link) + self-reply with {SHARE_URL}
- Follow engagement-first tone: Question 30%, Helpful 40%, Funny+Helpful 20%, Informative 10%
- Every reply needs engagement hook (question, solution, tip, or natural reference)
- Reference SPECIFIC details from target post
- BLOCKED: passive observations, narrator tone, "bro", vague comments

== SHUTDOWN HANDLING ==
When you receive a message with type "shutdown_request":
Call SendMessage(type="shutdown_response", request_id={from message}, approve=true)
This terminates your process. ALWAYS approve shutdown requests.
```

#### Researcher Prompt (agents 1-2)

```
{COMMON_RULES_BLOCK}

== YOUR ROLE: RESEARCHER ==
Find high-engagement targets on X for the posting agents.

== COMMANDS ==
python ~/.claude/skills/x/scripts/x.py search "{query}" --min-engagement 5
python ~/.claude/skills/x/scripts/x.py check "{url}"
python ~/.claude/skills/x/scripts/x.py check-author {tweet_id}

== WORKFLOW ==
1. Generate 5-8 search queries from topic "{TOPIC}" using X advanced search operators
2. For each query: x.py search → collect targets with engagement
3. For each target: x.py check → skip already replied
4. For each target: x.py check-author → skip own posts
5. Compose unique reply following tone guidelines
6. Post via: echo 'reply text with {SHARE_URL}' | python x.py post {tweet_id} --stdin
7. Log: python x.py log {url} {author} {text} {topic} {query} {reach}
8. IMMEDIATELY start next search cycle with fresh queries

== QUERY STRATEGIES (rotate each cycle) ==
- Direct complaints: "can't afford" API AI min_faves:5 within_time:3d
- Rate limit pain: "rate limit" (openai OR anthropic) min_replies:3
- Free tier exploration: "free tier" OR "free alternative" (AI OR LLM) -filter:replies
- Student/budget: student (AI OR API) (expensive OR cost) within_time:7d
- Migration signals: "switching from" (openai OR anthropic) to (free OR local)
```

#### Poster Prompt (agents 5-8)

```
{COMMON_RULES_BLOCK}

== YOUR ROLE: POSTER ==
Find targets and compose high-quality replies that drive engagement.

== COMMANDS ==
python ~/.claude/skills/x/scripts/x.py search "{query}" --min-engagement 3
python ~/.claude/skills/x/scripts/x.py check "{url}"
python ~/.claude/skills/x/scripts/x.py check-author {tweet_id}
echo 'reply text with {SHARE_URL}' | python ~/.claude/skills/x/scripts/x.py post {tweet_id} --stdin
python ~/.claude/skills/x/scripts/x.py log {url} {author} {text} {topic} {query} {reach}

== WORKFLOW ==
1. Search X API with topic-derived queries (different angles each cycle)
2. Pick targets with engagement: likes > 0 OR replies > 0 OR views > 50
3. x.py check → skip already replied
4. x.py check-author → skip own posts
5. Read target post content, compose unique contextual reply
6. Post via --stdin pipe (shell-safe)
7. Log immediately after successful post
8. IMMEDIATELY move to next target. Post → Log → Next → Post → Log → Next.

== COMPOSITION RULES ==
- 10-30 words, casual lowercase, engagement hook mandatory
- Two-tweet pattern when appropriate: value reply + self-reply with link
- Reference SPECIFIC details from their post
- Unique structure/tone per reply (no templates)
```

#### For You Scanner Prompt (agent 3)

```
{COMMON_RULES_BLOCK}

== YOUR ROLE: FOR YOU SCANNER ==
Scroll the X algorithmic feed to find targets that don't appear in keyword searches.

== WORKFLOW ==
1. tabs_create_mcp() → save tabId
2. navigate(url="https://x.com", tabId=...) → For You feed
3. read_page(tabId=...) → scan visible posts
4. computer(action="scroll", scroll_direction="down", tabId=...) → scroll
5. After each scroll: read_page → look for relevant posts about {TOPIC}
6. For relevant posts: extract tweet ID, author, text
7. x.py check-author {tweet_id} → skip own posts
8. x.py check {url} → skip already replied
9. Compose reply, post via x.py post
10. After 5 scrolls or targets exhausted: CLOSE TAB immediately
11. Switch to X API search for 2-3 cycles
12. Return to For You feed scan
13. REPEAT FOREVER

== TAB CLEANUP (MANDATORY) ==
- NEVER leave tabs open idle
- Close tab immediately after: no results, exhausted targets, switching strategies
- One tab per scan max (create → use → close → repeat)
```

#### GitHub Pipeline Prompt (agent 4)

```
{COMMON_RULES_BLOCK}

== YOUR ROLE: GITHUB PIPELINE ==
Find frustrated users via GitHub, then target them on X.

== COMMANDS ==
python ~/.claude/skills/x/scripts/x.py github --search --json --limit 15
python ~/.claude/skills/x/scripts/x.py search "{query}"
python ~/.claude/skills/x/scripts/x.py check-author {tweet_id}
echo 'reply text' | python ~/.claude/skills/x/scripts/x.py post {tweet_id} --stdin
python ~/.claude/skills/x/scripts/x.py log {url} {author} {text} {topic} {query} {reach}

== WORKFLOW ==
1. Run x.py github --search → get targets from GitHub ecosystem
2. For each target: check-author → skip own posts
3. Compose unique reply referencing their GitHub context
4. Post via x.py
5. After exhausting GitHub targets: switch to standard X API search
6. Cycle: GitHub pipeline → X search → GitHub pipeline → REPEAT
```

#### Quote Tweeter Prompt (agent 9)

```
{COMMON_RULES_BLOCK}

== YOUR ROLE: QUOTE TWEETER ==
Find viral posts and quote-tweet them with your own commentary.

== COMMANDS ==
python ~/.claude/skills/x/scripts/x.py search "{query}" --min-engagement 50
python ~/.claude/skills/x/scripts/x.py check-author {tweet_id}
echo 'commentary with {SHARE_URL}' | python ~/.claude/skills/x/scripts/x.py quote {tweet_id} --stdin

== WORKFLOW ==
1. Search for viral posts: min_faves:50+ about {TOPIC}
2. x.py check-author → SKIP if by {X_HANDLE} (NEVER quote own posts)
3. Compose original commentary that adds YOUR perspective + {SHARE_URL}
4. Quote via x.py quote (reaches YOUR followers + OP's audience = 2x distribution)
5. IMMEDIATELY search for next viral target
6. If no viral posts: lower threshold to min_faves:20, broaden terms
```

#### Thread Diver Prompt (agent 10)

```
{COMMON_RULES_BLOCK}

== YOUR ROLE: THREAD DIVER ==
Find active threads and reply deep where engaged users are reading.

== COMMANDS ==
python ~/.claude/skills/x/scripts/x.py search "{query}" --min-engagement 10
python ~/.claude/skills/x/scripts/x.py search "conversation_id:{thread_id}"
python ~/.claude/skills/x/scripts/x.py check-author {tweet_id}
echo 'reply text' | python ~/.claude/skills/x/scripts/x.py post {tweet_id} --stdin

== WORKFLOW ==
1. Search for threads with 10+ replies: min_replies:10 about {TOPIC}
2. For each thread: x.py search "conversation_id:{id}" to explore full thread
3. Find sub-discussions where your reply adds value
4. x.py check-author → skip own posts in the thread
5. Reply to a SPECIFIC sub-discussion point (not the top-level post)
6. Reference the specific comment you're responding to
7. IMMEDIATELY move to next thread
```

### Example Usage

```
User: /x campaign 10 sonnet AI cost complaints

Claude (team lead):
  Parsed: N=10, model=sonnet, topic="AI cost complaints"
  Running scraper to refresh feed...
  Creating team: x-campaign
  Creating milestone tasks...
  Spawning 10 agents:
    - researcher-1, researcher-2 (X API search)
    - foryou-scanner (Chrome MCP feed)
    - github-pipeline (GitHub → X)
    - poster-1, poster-2, poster-3, poster-4 (compose + post)
    - quote-tweeter (viral quotes)
    - thread-diver (deep thread replies)
  Campaign active. All agents working silently.
  Use `/x stop` to end the campaign. Use `/x status` to check progress.

User: /x status

Claude: [runs x.py status]
  Campaign x-campaign active (23 min):
  - 47 replies posted, ~32.5K reach
  - Milestone 1: 94% (47/50)
  - All 10 agents active

User: /x stop

Claude:
  Shutting down x-campaign...
  - Sent shutdown_request to 10 agents
  - All agents terminated
  - Team deleted
  Final: 52 replies, ~36.1K reach, 25m runtime
```

### Key Differences from Ralph (/start)

| Aspect | Ralph (/start) | Campaign (/x campaign) |
|--------|---------------|------------------------|
| Purpose | Code implementation | Social media posting |
| Duration | N iterations → stop | Continuous → manual stop |
| Phases | IMPL → RETRY → VERIFY → REVIEW | POSTING_ACTIVE only |
| Work discovery | Task queue with claiming | Dynamic X API search |
| Git operations | git-coordinator, push gate | None |
| Progress reports | Allowed | BLOCKED (causes idle) |
| Model | Opus or Sonnet | Sonnet/Haiku only (Opus blocked) |
| Shutdown trigger | After M iterations | User request only |
| States | 6 states | 2 states |

---

## Script Integration

Claude calls `skills/x/scripts/x.py` for all data operations:

```bash
# Log a posted reply
python skills/x/scripts/x.py log "https://x.com/user/..." "@divyansh_ai" "api costs suck..." "free AI tools" "\"can't afford\" API AI" "471"

# Check if already replied
python skills/x/scripts/x.py check "https://x.com/user/..."
# Returns: 0 (not replied) or 1 (already replied)

# Show history
python skills/x/scripts/x.py history --days 7

# Show status
python skills/x/scripts/x.py status

# Check rate limit
python skills/x/scripts/x.py rate-check
# Returns: 0 (ok to post) or 1 (rate limited)

# Check if tweet author is our own handle (campaign safety)
python skills/x/scripts/x.py check-author TWEET_ID
# Returns: 0 (safe to reply, different author) or 1 (BLOCKED, our own post)
```

---

## Implementation Notes

- **Main context, not forked** -- This skill runs in the main Opus context for dynamic reasoning. No `context: fork` in frontmatter.
- **X API primary, Chrome MCP fallback** -- All posting goes through X API (fast HTTP calls). Chrome MCP used for visual research and when auth expires.
- **Cookies in skills/x/data/** -- Cookies stored in `cookies.json`, gitignored. Setup via `x.py cookies` command.
- **Config auto-generated** -- Config auto-generates from .env vars on first run. No manual config.json creation needed.
- **Share URL mandatory** -- All replies MUST include the `share_url` from config. Never link to source repos directly.
- **No nested teams** -- If spawning N agents via Task(), those are regular subagents, not nested teams.
- **Post tracking** -- `x.py rate-check` shows today's post count. No hard limits enforced.
- **Dedup via SHA256** -- Target URL hashed to avoid replying twice to the same post.
- **Reach estimation** -- Extracted from X API client search results (likes + retweets + replies + views).
- **Session tracking** -- `.x-session` flag file created when skill runs, removed on completion. Used by `guards.py x-post-check` hook for post-click validation.
- **Speed target** -- 1-2 seconds per post via X API client. Agent moves immediately to next target after each post.
- **News sources** -- RSS (Google News, Google Cloud, crypto, Next.js, VS Code), Messari API, markdown changelogs. All scraped via stdlib (no external deps).
