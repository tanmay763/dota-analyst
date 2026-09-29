# Dota Analyst

Ask Claude anything about Dota 2 statistics, and turn the answer into an in-game hero
grid. Claude queries live data from [Stratz](https://stratz.com): hero win and pick rates
by rank, position and patch, matchups, items, lanes, a player's matches, pro leagues.

## Use it

1. Add the plugin, then connect **Dota Analyst** from the plugin's Connectors tab.
2. When asked, paste your Stratz API token. It's free: sign in with Steam at
   [stratz.com/api](https://stratz.com/api) and copy the token.
3. Ask a question: "Which position 1 heroes are winning most in Divine+ this week?",
   "What does Morphling build on this patch?", "Show my hero pool by position".
4. When you're happy with the analysis, ask for a hero grid, for example "make that a
   tier list grid". Claude shows a preview and a download link for
   `hero_grid_config.json`, and explains where the Dota client reads it from. It can
   merge the new grid with your current one so you keep your own layouts.

## Data

Your Stratz queries run on your own Stratz token, on the plugin's server. The token is
sealed inside your sign-in and never stored. Stratz responses are cached on the server
for up to 7 days, separately for each user, and only summaries and query results reach
the conversation. Hero grid download links carry the grid itself and nothing else. The
hero grid preview loads hero portraits straight from Valve's Steam CDN
(`cdn.steamstatic.com`) in your browser.
Source: https://github.com/tanmay763/dota-analyst
