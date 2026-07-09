# Daily arXiv Paper Radar

This repository generates a daily arXiv digest for papers about diffusion language models and model architecture.

## What It Does

- Fetches recent arXiv papers from `cs.CL`, `cs.LG`, `cs.AI`, and `stat.ML`
- Scores papers using configurable topic keywords
- Writes daily reports to `reports/YYYY-MM-DD.md`
- Updates `reports/latest.md`
- Tracks seen arXiv IDs in `data/seen.json`
- Optionally sends the report by email through SMTP

## Run Locally

```bash
python scripts/daily_arxiv.py --sample --no-email
```

To call arXiv for real:

```bash
python scripts/daily_arxiv.py --no-email
```

## GitHub Setup

1. Create a GitHub repository and push these files.
2. Open the repository settings.
3. Go to `Actions > General`.
4. Make sure workflows can read and write repository contents.
5. The workflow runs every day at `23:00 UTC`, which is `07:00` in Beijing time.

## Optional Email Setup

Add these repository secrets if you want one email per run:

```text
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-address@gmail.com
SMTP_PASSWORD=your-gmail-app-password
MAIL_TO=your-address@example.com
```

For Gmail, use an app password rather than your normal account password.

## Tuning

Edit `config.json` to change:

- watched arXiv categories
- topic keywords and weights
- minimum score
- lookback window
- maximum papers in each report
