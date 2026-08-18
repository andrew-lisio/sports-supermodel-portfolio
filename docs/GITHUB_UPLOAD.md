# Uploading Sports SuperModel to GitHub

This repository is prepared as the V2.3.3 open-input, prediction-only release.

## Before uploading

From the project root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[ui,dev]"
pytest
sports-supermodel --help
```

Expected test result for this release:

```text
29 passed
```

Review the public-release checklist and inspect the repository for private inputs:

```powershell
git status
```

Do not publish credentials, cookies, balances, account identifiers, or private sportsbook information.

## Recommended command-line method

### 1. Create an empty GitHub repository

Create a new repository on GitHub. Do not initialize it with another README, `.gitignore`, or license because those files already exist in this project.

A suitable name is:

```text
sports-supermodel
```

Keep it private for the first push while you inspect the rendered README and repository contents.

### 2. Initialize and commit locally

```powershell
cd C:\path\to\sports-supermodel-v2.3.3

git init
git add .
git status
git commit -m "Release Sports SuperModel V2.3.3"
git branch -M main
git tag -a v2.3.3 -m "Sports SuperModel V2.3.3 open-input release"
```

### 3. Connect and push

Replace the example URL with your repository URL:

```powershell
git remote add origin https://github.com/YOUR-USERNAME/sports-supermodel.git
git remote -v
git push -u origin main
git push origin v2.3.3
```

## GitHub CLI method

When GitHub CLI is installed and authenticated:

```powershell
cd C:\path\to\sports-supermodel-v2.3.3

git init
git add .
git commit -m "Release Sports SuperModel V2.3.3"
git branch -M main
git tag -a v2.3.3 -m "Sports SuperModel V2.3.3 open-input release"

gh repo create sports-supermodel --private --source=. --remote=origin --push
git push origin v2.3.3
```

## GitHub Desktop method

1. Extract the release archive.
2. Open GitHub Desktop.
3. Select **File > Add local repository**.
4. Choose the extracted project folder.
5. If prompted, create a Git repository there.
6. Commit all files with `Release Sports SuperModel V2.3.3`.
7. Select **Publish repository**.
8. Keep it private for the initial review.
9. Publish.

## Verify after the first push

Confirm that GitHub displays:

- `README.md`
- `DISCLAIMER.md`
- `COPYRIGHT.md` and `NOTICE.md`
- `app.py`
- `src/supermodel/`
- `tests/`
- `docs/USER_INPUTS.md`
- `docs/WEB_APP.md`
- `.github/workflows/tests.yml`

Open the **Actions** tab and confirm that the test workflow passes.

## Repository settings

Suggested topics:

```text
mlb
baseball
machine-learning
sports-analytics
monte-carlo
python
streamlit
```

Recommended settings:

- Enable private vulnerability reporting.
- Protect `main` after the initial push.
- Require the test workflow before merging major changes.
- Use pull requests for model changes.
- Keep V2.4 work on a separate branch.

## Make V2.4 branch

After V2.3.3 is safely pushed:

```powershell
git switch -c v2.4-development
git push -u origin v2.4-development
```

Keep `main` on the stable V2.3.3 input release until V2.4 passes validation and integrity gates.

## Future updates

```powershell
git status
git add .
git commit -m "Describe the change"
git push
```
