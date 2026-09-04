# GitHub Publication Checklist

- [ ] No OAuth credentials, API keys, tokens, cookies, or `.env` files.
- [ ] No personal agent `memory.json`, notifications, chat, logs, or provider state.
- [ ] No generated projects or client/customer data.
- [ ] No personal absolute paths, usernames, or private spreadsheet IDs.
- [ ] Run `git diff --cached` and inspect every added line.
- [ ] Run a secret scanner such as Gitleaks before publishing.
- [ ] Start with a private repository, test setup from a clean clone, then make public if appropriate.
- [ ] Add a license selected by the repository owner.
