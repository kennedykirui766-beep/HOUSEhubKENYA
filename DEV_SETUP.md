Developer setup

1. Copy `.env.example` to `.env` and fill values.

2. DO NOT commit `.env` to the repository. It is listed in `.gitignore`.

3. Install git hooks (Linux/macOS):

```sh
sh scripts/install-git-hooks.sh
```

4. Install git hooks (Windows PowerShell):

```powershell
.\install-git-hooks.ps1
```

5. If you've accidentally committed secrets, rotate them immediately and use a blob cleaner like `git-filter-repo` or the BFG Repo-Cleaner.

6. To push safe changes to `hv3` branch:

```sh
git add .
git commit -m "chore: add .env.example and hook installer"
git push origin hv3
```
