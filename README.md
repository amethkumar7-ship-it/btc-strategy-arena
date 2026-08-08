# BTC Strategy Arena

Five original long-only Bitcoin algorithms trade live with $100,000 virtual capital
each on 5-minute BTCUSDT candles. TP +0.8% / SL −0.5% / 0.1% fee per side. The
engine runs on GitHub Actions every 5 minutes; the dashboard is a static page on
GitHub Pages. Total hosting cost: ₹0.

## Strategies
| Name | Edge | Data used |
|---|---|---|
| TAKER_TIDE | Aggressive-buy order flow | taker buy volume ratio |
| CROWD_SURGE | Participation breakout | per-candle trade count z-score |
| WICK_ABSORB | Seller absorption | lower vs upper wick sums |
| ENTROPY_DRIFT | Trend-regime detection | Shannon entropy of returns |
| RANGE_COIL | Compression breakout | NR-12 range + volume confirm |

## Setup (10 minutes, one time)

1. **Create a GitHub repo** (public), e.g. `btc-strategy-arena`. Upload this
   entire folder's contents (drag-and-drop works, or `git push`).
2. **Enable Actions**: repo → Actions tab → enable workflows. Open
   "Run trading engine" → **Run workflow** once manually to seed the first data.
3. **Enable Pages**: repo → Settings → Pages → Source: *Deploy from a branch* →
   Branch: `main`, folder: `/docs` → Save. Your site goes live at
   `https://<username>.github.io/btc-strategy-arena/` within ~2 minutes.
4. Done. The cron keeps it trading. Check Actions tab if data ever looks stale.

## Custom domain (recommended before AdSense)
AdSense approval is far easier on your own domain than on github.io.
Buy a domain (₹99–800/yr on Namecheap/Hostinger), then: repo Settings → Pages →
Custom domain → enter it, and add the CNAME record at your registrar pointing to
`<username>.github.io`.

## AdSense
1. Get the site live with a custom domain, let it accumulate 3–4 weeks of trade
   history (AdSense wants "sufficient content" — the live data + strategy
   descriptions qualify, but age helps).
2. Add an About page and Privacy Policy page (required by AdSense).
3. Apply at adsense.google.com, add the verification `<script>` to
   `docs/index.html` `<head>`.
4. Once approved, replace the two `div.adslot` placeholders in `index.html`
   with your ad unit code.

## Notes
- GitHub cron can lag 2–10 min under load; the engine processes every missed
  candle on the next run, so no trades are ever skipped — only reported late.
- State lives in `docs/data/*.json`, committed by the bot. Delete those files
  and re-run to reset the arena to $100K each.
- Stop-loss is checked before take-profit within a candle (conservative).
- To change TP/SL/fees, edit the constants at the top of `engine/run.py`.
