# The plugin reads live Stratz only, not the `../dota` weekly BigQuery tables

The website's agent also read the weekly pipeline's precomputed tables: tiers, picker data, counters and synergies by custom bracket, and hero pools. The plugin doesn't. Those tables are built for registered players and one bracket model. Reading them would take BigQuery access from a public server and couple it to the pipeline's schedule. What the move to the plugin buys is a frontier model working over the live API with the cookbook, which can answer questions the tables never anticipated.

## Considered Options

- **Read-only tools over the weekly tables**: everyone would get the tier model, at the cost of BigQuery access and coupling. A follow-up if friends miss the tiers.
