# PaiLei 排雷

**Give it a stock ticker. It reads years of the company's annual reports and tells you where the red flags are.**

[中文](./README.md)

*PaiLei (排雷) means "minesweeping" — in Chinese retail-investor slang, a stock that blows up on fraud is a "mine" (雷). This tool sweeps for them.*

![demo](docs/demo.gif)
<!-- placeholder: 60-second demo GIF before launch -->

## What it does

Given an A-share ticker, PaiLei:

1. Pulls the last N years of annual reports and audit reports (PDF) from CNINFO, China's official disclosure site — public data, free
2. Extracts key line items from the three financial statements and locates the footnotes
3. Runs a rule set for red flags, then lets an LLM read what rules can't
4. Outputs a red-flag report where **every finding cites the source page number** — verifiable, refutable

## Numbers go to rules, prose goes to the LLM

Some red flags live in the numbers — six deterministic rules catch those. More hide in footnotes and wording, where rule engines can't reach — that part goes to the LLM. So PaiLei has two layers:

**Rule layer** — deterministic checks, no LLM involved. Six built-in rules:

| Rule | What it catches |
|---|---|
| High cash + high debt | Large cash balance alongside large interest-bearing debt |
| Receivables vs. revenue divergence | Receivables growing far faster than revenue |
| Cash flow vs. profit divergence | Operating cash flow persistently lagging net income |
| Goodwill ratio | Goodwill as an outsized share of net assets |
| Audit opinion changes | Year-over-year comparison of opinion types |
| Related-party transaction share | Related-party deals as a share of revenue/procurement |

**LLM layer** — unstructured footnote text that no rule engine can parse:

- Changes in accounting policies and estimates (e.g., a quiet change in revenue recognition)
- Contingent liabilities and guarantees
- Related-party relationship descriptions
- Shifts in audit opinion wording ("unqualified" → "unqualified with emphasis of matter")

Reading one year's footnotes by hand takes hours. This is where the LLM genuinely earns its keep — it's not a wrapper.

## Backtest: could AI have spotted Kangmei three years early?

We only backtest on cases with **final court verdicts** — Kangmei Pharmaceutical's ¥30B cash fabrication and Kangde Xin's fictitious profits, two of China's largest securities fraud cases:

| Company | Ticker | Backtest report |
|---|---|---|
| Kangmei Pharmaceutical | 600518 | <!-- placeholder: examples/kangmei/ --> |
| Kangde Xin | 002450 | <!-- placeholder: examples/kangdexin/ --> |

## Quick start

```bash
pip install pailei

# Any OpenAI-compatible endpoint works: DeepSeek, Qwen, Kimi, GLM, OpenAI...
export PAILEI_API_BASE=https://api.deepseek.com
export PAILEI_API_KEY=sk-...

pailei 600518 --years 5
```

You get a Markdown red-flag report.

## What we don't do

- No stock picks, no buy/sell signals
- No live trading integration
- No price prediction
- No "fraud" verdicts on companies without a court ruling — only verifiable signals, each with a citation

These aren't roadmap items. They're out of scope by design.

## Contribute a red-flag rule

The rule set is pluggable: one rule = one function + a short rationale. If you've seen a signal in equity research or audit practice, PRs are welcome. See [CONTRIBUTING.md](./CONTRIBUTING.md).

## Disclaimer

PaiLei's output is a programmatic cross-check of publicly disclosed data plus "signals worth attention". It is not investment advice and not a conclusive judgment on any company's financial integrity. Verify every signal against the source documents.

## Acknowledgments

Inspired by [Vibe-Trading](https://github.com/HKUDS), TradingAgents, and ai-hedge-fund. They do research and stock selection; we do one small thing: sweep for mines.

## License

GPL-3.0
