[SETUP.md](https://github.com/user-attachments/files/31024876/SETUP.md)
# Setup Guide

## 1. File layout to create in the repo

```
visual-versatility-autopost/
├── scripts/
│   ├── autopost.py
│   └── reply_comments.py
├── content/
│   ├── calendar.json
│   └── replied_comments.json
├── .github/
│   └── workflows/
│       ├── post.yml
│       └── reply-comments.yml
├── requirements.txt
└── README.md
```

If setting this up from scratch (no direct repo access), create each folder/file via GitHub's
"Add file" → "Create new file" button, pasting in the path (e.g. type `scripts/autopost.py` as
the filename — GitHub creates the folder automatically) and the contents from the files
provided.

## 2. IMPORTANT: images must be at PUBLIC urls

Meta's Graph API fetches your images from a URL you give it — it cannot read files from a
private GitHub repo. **Done**: images live in a separate **public** repo,
`github.com/osastdl/visual-versatility-post-images`, and `content/calendar.json` links to them
via `raw.githubusercontent.com` URLs. Nothing sensitive lives in that repo, just image files.

To add more images later: push new files to that public repo, then reference their
`raw.githubusercontent.com` URL in a new `calendar.json` entry.

## 3. Get your 4 secret values

### IG_USER_ID (Instagram Business Account ID)
In Graph API Explorer (developers.facebook.com → Tools → Graph API Explorer), with your
access token selected, run a GET request to:
```
me/accounts
```
This lists your Facebook Pages. Find yours, copy its Page ID, then run:
```
{page-id}?fields=instagram_business_account
```
That returns your `IG_USER_ID`.

### FB_PAGE_ID
Same `me/accounts` call above gives you this directly — it's the Page's `id` field.

### FB_PAGE_TOKEN
Still in `me/accounts`, each Page in the response includes an `access_token` field — that's
your Page access token. This is different from your personal user token.

### IG_ACCESS_TOKEN (long-lived)
The token you generated in Graph API Explorer is short-lived (~1 hour). Exchange it for a
60-day long-lived token by visiting this URL in your browser (fill in your values), while
logged in as an app admin:
```
https://graph.facebook.com/v21.0/oauth/access_token?grant_type=fb_exchange_token&client_id={app-id}&client_secret={app-secret}&fb_exchange_token={short-lived-token}
```
The response's `access_token` field is your long-lived token — use that for both
`IG_ACCESS_TOKEN` and `FB_PAGE_TOKEN` if you don't want to separately generate a Page token
(the Page token inherits from your long-lived user token as long as you remain an admin).

⚠️ Never paste your `client_secret` (app secret) anywhere but this one-time URL you run
yourself — don't share it in chat, commits, or screenshots.

## 4. Add the secrets to GitHub

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

Add each of these four:
- `IG_ACCESS_TOKEN`
- `IG_USER_ID`
- `FB_PAGE_ID`
- `FB_PAGE_TOKEN`

## 5. Test it

Go to the **Actions** tab → "Auto-post to Instagram & Facebook" → **Run workflow** (manual
trigger) to test immediately, rather than waiting for the schedule. Check the run's logs to
confirm success or see the exact API error.

There's a second workflow, "Auto-reply to Instagram comments" — it runs every 30 minutes and
replies to comments on your own recent posts only (never on other accounts, that's not what
this does). It reuses the same `IG_ACCESS_TOKEN` and `IG_USER_ID` secrets, so no extra setup
is needed once the 4 secrets above are in place. Test it the same way, from the Actions tab.

## 6. Ongoing maintenance

- Long-lived tokens expire after 60 days — repeat step 3's exchange periodically and update
  the GitHub secret.
- To add more posts, edit `content/calendar.json` directly on GitHub (Edit pencil icon) and
  add a new object to the array in the same format.
- To pause posting, go to Actions → the workflow → "..." menu → Disable workflow.
