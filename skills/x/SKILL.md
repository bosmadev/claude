---
name: x
description: "X/Twitter outreach -- research engagement, compose original posts from news, and distribute via replies. Claude dynamically searches, composes, and posts via X API (fast) or Chrome MCP (fallback)."
argument-hint: "research [N] [model] {TOPIC} | post [N] [model] {TEXT with URL} | compose | news | history | status | help"
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
| `status` | Show daily/weekly counts + reach | `/x status` |
| `scrape` | Run scraper now, update feed.json | `/x scrape` |
| `feed` | Show current auto-generated feed (queries + news) | `/x feed` |
| `scheduler install [N]` | Install auto-scraper (every Nh, default 6) | `/x scheduler install 4` |
| `scheduler status` | Show scheduler + feed freshness | `/x scheduler status` |
| `scheduler uninstall` | Remove auto-scraper | `/x scheduler uninstall` |
| `auto [N] [model]` | Headless auto-run: scrape + research + post | `/x auto 5 sonnet` |
| `help` | Show usage help | `/x help` |

### Model Selection Syntax

Both `research` and `post` support `[N] [model]` syntax:

- `[N]` -- number of parallel agents (default: 1, single agent in main context)
- `[model]` -- `opus`, `sonnet`, or `haiku` (default: main context model)

**Examples:**
```
/x post {TEXT}                    # Single agent, main Opus context
/x post 10 opus {TEXT}            # 10 Opus agents in parallel
/x research 5 sonnet {TOPIC}      # 5 Sonnet agents for research
/x post 2 haiku {TEXT}            # 2 Haiku agents (minimal cost)
```

When `N > 1`, Claude spawns Team agents via `Task(model="opus"|"sonnet"|"haiku")` override. Each agent calls `tabs_create_mcp` for a dedicated Chrome tab.

### Agent Allocation (N > 1)

When spawning N agents, allocate them across two browser pools:

**Browser Pool Assignment:**
- **Agents 1-5:** Chrome MCP (`claude-in-chrome`) -- `tabs_create_mcp` per agent
- **Agents 6-10:** Playwriter MCP (`playwriter`) -- `context.newPage()` per agent
- **Agent 1 (always):** "For You" feed scanner (Chrome MCP)

Chrome MCP caps at ~5 concurrent tabs reliably. Beyond 5, use Playwriter for the overflow.

**Role assignment:**
- **1 agent: "For You" feed scanner** -- navigates to `https://x.com`, scrolls the "For You" feed, identifies posts from students/broke devs/people complaining about AI costs. This catches posts that search queries miss because they don't use specific keywords.
- **Remaining N-1 agents: search agents** -- each gets 2-3 unique search queries to run on X

The "For You" agent workflow:
1. `tabs_create_mcp` for dedicated tab
2. `navigate` to `https://x.com` (lands on For You feed)
3. `read_page` to scan visible posts
4. `computer(scroll, down)` 3-4 times, `read_page` after each scroll
5. Look for posts matching: student struggles, AI cost complaints, free tier limits, broke developers, can't afford API
6. Extract targets (author, text, URL, engagement)
7. Report findings to team-lead

**Why "For You":** The algorithmic feed surfaces posts from your network and interest graph -- often students and indie devs who don't use searchable keywords but ARE the target audience. Search misses these; the feed catches them.

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
- Rate limits apply (10/session, 30/day)

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

## Human Tone Guidelines

The following rules ensure replies don't look like a bot. Claude MUST follow these.

### DO:

- Write like a real person texting a friend
- Use simple short sentences
- Use "you" and "your" directly
- Reference something specific from their post
- Keep it under 280 chars
- Use lowercase naturally (not all proper case)
- Use simple dashes (-) not long dashes
- Say "about" not "approximately", "like" not "such as"

### DON'T:

- Use em dashes (the long -- ones become short - in tweets anyway)
- Use formal language ("Furthermore", "Additionally", "I'd like to share")
- Use hashtags in replies (looks like a bot)
- Start with "Hey!" or "Hi!" (looks like spam)
- Use exclamation marks excessively
- Use corporate speak ("leverage", "utilize", "comprehensive")
- Copy the same sentence structure across replies
- Use bullet points or formatted lists in tweets

### URL Strategy (MANDATORY)

**ALWAYS link to the user's configured `share_url`, NEVER directly to the source repo.**

- **USE:** The `share_url` from config (auto-loaded from .env or config.json)
- **NEVER:** Direct links to GitHub repos, gists, or source code

**Why:** Linking to the user's X post drives impressions to their profile. Direct repo links bypass their social presence entirely. Every reply MUST include the configured share URL.

Claude reads the `share_url` at the start of each `/x` session and includes it in every generated reply.

### Examples of Good Tone:

```
"api costs suck for students. check this out - it pools
free accounts for way higher rate limits. no card needed.
{SHARE_URL}"

"if rate limits are killing you - this tool gets you
way more requests for free.
{SHARE_URL}"

"you can get way more out of free tier APIs
with this. zero cost.
{SHARE_URL}"
```

Replace `{SHARE_URL}` with the actual URL from your config at runtime.

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

### Post Original Tweet (X API)

```bash
python skills/x/scripts/x.py tweet "tweet text with optional URL"
# Returns JSON: { "success": true, "tweet_id": "...", "url": "..." }
```

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
| **Auto-post on traction** | If target has likes > 0 OR replies > 0 OR views > 50, post immediately -- NO user approval |
| **No approval gate** | Saves context window and time -- Claude posts and reports results after |
| **Rate limit: 10/session** | `x.py rate-check` before each batch |
| **Rate limit: 30/day** | Daily counter in history.json |
| **Dedup protection** | SHA256 of target_url checked before composing |
| **Unique text per reply** | Claude generates fresh text, no repeated messages |
| **Human tone enforced** | SKILL.md tone guidelines, no formal/bot language |
| **Logged history** | Every post tracked with timestamp, topic, author, reach |
| **For You feed agent** | 1 dedicated agent always scans For You feed for student/broke dev posts |

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

**Rate Limits:**
- Session: 3/10 replies remaining
- Daily: 3/30 replies remaining

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

**News:** /x news
  Show current scraped news feed (RSS, crypto, changelogs)

**History:** /x history [--days N] [--topic T]
  Show posting history

**Status:** /x status
  Show daily/weekly counts + reach

**Model Selection:**
  [N] -- number of parallel agents (default: 1)
  [model] -- opus, sonnet, or haiku (default: main context)

**Rate Limits:**
  - 10 replies per session
  - 30 replies per day
```

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

- Rate limits still enforced (10/session, 30/day via x.py)
- Dedup still enforced (SHA256 of target URL)
- Human tone guidelines still apply (Sonnet follows SKILL.md instructions)
- All posts logged to history.json for review
- Feed freshness check: skip if feed.json > 24h old (scraper probably failed)

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
```

---

## Implementation Notes

- **Main context, not forked** -- This skill runs in the main Opus context for dynamic reasoning. No `context: fork` in frontmatter.
- **X API primary, Chrome MCP fallback** -- All posting goes through X API (fast HTTP calls). Chrome MCP used for visual research and when auth expires.
- **Cookies in skills/x/data/** -- Cookies stored in `cookies.json`, gitignored. Setup via `x.py cookies` command.
- **Config auto-generated** -- Config auto-generates from .env vars on first run. No manual config.json creation needed.
- **Share URL mandatory** -- All replies MUST include the `share_url` from config. Never link to source repos directly.
- **No nested teams** -- If spawning N agents via Task(), those are regular subagents, not nested teams.
- **Rate limiting enforced** -- `x.py rate-check` returns exit code 1 if rate limited. Claude stops posting and reports the limit.
- **Dedup via SHA256** -- Target URL hashed to avoid replying twice to the same post.
- **Reach estimation** -- Extracted from X API client search results (likes + retweets + replies + views).
- **Session tracking** -- `.x-session` flag file created when skill runs, removed on completion. Used by `guards.py x-post-check` hook for post-click validation.
- **Speed target** -- 1-2 seconds per post via X API client. Agent moves immediately to next target after each post.
- **News sources** -- RSS (Google News, Google Cloud, crypto, Next.js, VS Code), Messari API, markdown changelogs. All scraped via stdlib (no external deps).
