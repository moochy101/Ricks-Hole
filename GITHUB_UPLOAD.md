# Upload RICK-HOLE to GitHub

## Easiest: GitHub website

1. Sign in to GitHub and create a **New repository** named `rick-hole`.
2. Choose **Private** first if you have not checked redistribution rights for the face artwork.
3. Do **not** initialise the repo with a README, licence or `.gitignore`.
4. Create the repository and choose **uploading an existing file**.
5. Unzip `rick-hole-github.zip` and drag the **contents** of `rick-hole-github` into the upload page.
6. Commit the upload.

## Git from Windows

Unzip the package, open PowerShell inside `rick-hole-github`, then:

```powershell
git init
git add .
git commit -m "Initial RICK-HOLE release"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/rick-hole.git
git push -u origin main
```

## Push from the Pi

```bash
cd ~/rick-hole
git init
git add .
git commit -m "Initial RICK-HOLE release"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/rick-hole.git
git push -u origin main
```

Before committing, use `git status` and make sure no live credential file is inside the repo.
