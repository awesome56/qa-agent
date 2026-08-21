#!/usr/bin/env bash
set -e
# Creates private GitHub repo for qa-agent (separate from Awesome_App public repo)
REPO_NAME=${1:-qa-agent}
ORG=${ORG:-awesome56}
VISIBILITY=${2:-private}

echo "Creating gh repo $ORG/$REPO_NAME ($VISIBILITY) ..."
if command -v gh >/dev/null; then
  # init as separate repo (qa-agent is nested inside Awesome_App, so we need standalone git)
  TMP=/tmp/$REPO_NAME-$$
  mkdir -p $TMP
  cp -r /Users/apple/Awesome_App/qa-agent/. $TMP/
  cp /Users/apple/Awesome_App/qa-agent/.gitignore $TMP/ 2>/dev/null || true
  cd $TMP
  git init -b main
  git add .
  git commit -m "feat: initial qa-agent closed daemon"
  gh repo create $ORG/$REPO_NAME --$VISIBILITY --source=. --remote=origin --push --description "Private QA stress/load + screen-record daemon (closed build)"
  echo "Created https://github.com/$ORG/$REPO_NAME"
  echo "GHCR will be ghcr.io/$ORG/$REPO_NAME:closed (private by default for private repo)"
else
  echo "gh cli not found. Install: brew install gh && gh auth login"
  echo "Then manually:"
  echo "  1. https://github.com/new -> $REPO_NAME -> Private"
  echo "  2. cd /Users/apple/Awesome_App/qa-agent && git init && git add . && git commit -m 'init' && git remote add origin https://github.com/$ORG/$REPO_NAME.git && git push -u origin main"
fi
