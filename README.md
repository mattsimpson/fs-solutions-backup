# Freshservice Solutions KB Backup

Exports your entire Freshservice Solutions Knowledge Base to local Markdown files. The output is structured as a [Retype](https://retype.com/) project, so you can instantly browse the archive as a searchable static documentation site.

## What It Does

- Downloads **all categories, folders, and articles** (including drafts and agent-only content)
- Converts article HTML to clean **Markdown with YAML frontmatter**
- Downloads all **inline images and attachments** for full offline access
- Rewrites image references to **relative paths** so everything works locally
- Generates a **Retype-ready** project with `retype.yml`, navigation hierarchy, and homepage

## Output Structure

```
solutions/
  retype.yml                        # Retype configuration
  index.md                          # Homepage
  Category Name/
    index.md                        # Category landing page
    Folder Name/
      index.md                      # Folder landing page
      Article Title.md              # Article with YAML frontmatter
      images/
        article-slug-img001.png     # Downloaded inline images
        article-slug-att001.pdf     # Downloaded attachments
```

## Prerequisites

- **Python 3.7+**
- A **Freshservice API key** (found in your Freshservice profile settings under API)
- **Retype** (optional, for browsing the exported site)

## Setup

1. Clone this repository:

   ```bash
   git clone https://github.com/mattsimpson/fs-solutions-backup.git
   cd fs-solutions-backup
   ```

2. Install Python dependencies:

   ```bash
   python3 -m pip install -r requirements.txt
   ```

3. Copy the example environment file and fill in your credentials:

   ```bash
   cp .env.example .env
   ```

4. Edit `.env` with your Freshservice details:

   ```
   FRESHSERVICE_DOMAIN=yourcompany.freshservice.com
   FRESHSERVICE_API_KEY=your_api_key_here
   ```

   Your API key is available under **Profile Settings > API** in Freshservice.

## Running the Export

```bash
python3 fs-solutions-backup.py
```

The script will print progress as it runs:

```
Fetching categories …
Found 5 categories.

Category: IT Support (1/5)
  Folder: Getting Started (1/3)
    Article: How to Reset Your Password (1/12)
    Article: VPN Setup Guide (2/12)
    ...

==================================================
Export complete!
  Categories: 5
  Folders:    18
  Articles:   142
  Images:     87
  Output:     /Users/you/freshservice/solutions
==================================================
```

All content is saved to the `solutions/` directory.

## Browsing with Retype

[Retype](https://retype.com/) turns the exported Markdown into a polished, searchable documentation site.

### Install Retype

Using npm (recommended):

```bash
npm install retypeapp --global
```

Or using dotnet:

```bash
dotnet tool install retypeapp --global
```

### Run the Dev Server

```bash
cd solutions
retype start
```

This starts a local server (typically at `http://localhost:5000`) with live reload. The full KB is browsable with search, navigation, and all images working.

### Build a Static Site

```bash
cd solutions
retype build
```

The generated site is output to `solutions/.retype/` and can be deployed to any static hosting (GitHub Pages, Netlify, etc.).

## Configuration

The script reads from a `.env` file in the project root:

| Variable               | Description                          |
|------------------------|--------------------------------------|
| `FRESHSERVICE_DOMAIN`  | Your Freshservice subdomain (e.g. `yourcompany.freshservice.com`) |
| `FRESHSERVICE_API_KEY` | Your Freshservice API key            |

### Retype Customization

After export, you can customize `solutions/retype.yml` to adjust branding, footer, theme, and other Retype settings. See the [Retype project configuration docs](https://retype.com/configuration/project/) for all available options.

## Features

- **Pagination** — handles large KBs with hundreds of articles
- **Rate limiting** — respects Freshservice API limits, sleeps on 429 responses
- **Retries** — failed requests are retried up to 3 times with exponential backoff
- **Image downloading** — inline images and formal attachments are saved locally
- **Duplicate handling** — articles with the same title in a folder get the article ID appended
- **Draft visibility** — draft articles are exported with `visibility: hidden` in Retype (present in source, hidden from navigation)
- **Agent-only folders** — folders with agent-only visibility are marked hidden in Retype

## Article Frontmatter

Each exported article includes YAML frontmatter with both Retype-compatible and Freshservice metadata:

```yaml
---
label: "Article Title"
order: 1
date: "2024-06-20T14:00:00"
tags:
  - vpn
  - setup
id: 123456
status: "published"
author_id: 789
created_at: "2024-01-15T10:30:00Z"
updated_at: "2024-06-20T14:00:00Z"
folder_id: 456
category_id: 123
views: 42
thumbs_up: 5
thumbs_down: 0
---
```

## Re-running the Export

Running the script again will overwrite the `solutions/` directory with fresh content. This makes it easy to schedule regular backups or run it before committing to Git.

## Contributing

Contributions are welcome! To get started:

1. Fork the repository
2. Create a feature branch (`git checkout -b my-feature`)
3. Make your changes
4. Run the script against a test Freshservice instance to verify
5. Commit your changes (`git commit -m "Add my feature"`)
6. Push to your fork (`git push origin my-feature`)
7. Open a Pull Request at [github.com/mattsimpson/fs-solutions-backup](https://github.com/mattsimpson/fs-solutions-backup)

Please keep pull requests focused on a single change and include a clear description of what the change does and why.

## Reporting Bugs

Found a bug or have a feature request? Please open an issue at:

[github.com/mattsimpson/fs-solutions-backup/issues](https://github.com/mattsimpson/fs-solutions-backup/issues)

When reporting a bug, include:

- Python version (`python3 --version`)
- The error message or traceback
- Steps to reproduce the issue
- Expected vs actual behavior

**Important:** Never include your API key or `.env` contents in bug reports.

## License

MIT License. Copyright (c) 2026 Matt Simpson.
