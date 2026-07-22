# Uploading the repository to GitHub

## Recommended command-line method

1. Extract the release archive to a permanent folder.
2. Open PowerShell or Git Bash in that folder.
3. Run the tests.
4. Create a new empty GitHub repository. Do not initialize it with another README, `.gitignore`, or license because those files are already included here.
5. Add the GitHub repository as `origin` and push `main`.

```powershell
cd C:\path\to\sports-supermodel-v2.3.1

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
pytest

git init
git add .
git commit -m "Release Sports SuperModel V2.3.1"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git
git remote -v
git push -u origin main
```

## GitHub Desktop method

1. Extract the archive.
2. Open GitHub Desktop.
3. Choose **File > Add local repository**.
4. Select the extracted project folder.
5. If prompted, create a Git repository in the folder.
6. Commit all files with the message `Release Sports SuperModel V2.3.1`.
7. Select **Publish repository**.
8. Choose public or private visibility and publish.

## Before making it public

- Read `DISCLAIMER.md` and obtain legal review if the project will be marketed, monetized, or used beyond personal research.
- Confirm no private credentials, account identifiers, or personal data are present.
- Confirm all data and screenshots may lawfully be redistributed.
- Replace generic project-owner information if desired.
- Add a repository description and topics such as `mlb`, `machine-learning`, `monte-carlo`, and `sports-analytics`.
- Enable branch protection after the first push.

## Updating later

```powershell
git status
git add .
git commit -m "Describe the change"
git push
```

Create V2.4 work on a separate branch:

```powershell
git switch -c v2.4-development
git push -u origin v2.4-development
```
