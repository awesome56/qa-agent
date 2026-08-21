#!/usr/bin/env bash
set -e
# Creates private GitHub repo for qa-agent (separate from Awesome_App public repo)
REPO_NAME=${1:-qa-agent}
ORG=${ORG:-awesome56}
VISIBILITY=${2:-private}

echo "Creating gh repo $ORG/$REPO_NAME ($VISIBILITY) from /Users/apple/qa-agent ..."
if command -v gh >/dev/null; then
  cd /Users/apple/qa-agent
  # already a git repo — just push
  if ! git remote get-url origin >/dev/null 2>&1; then
    gh repo create $ORG/$REPO_NAME --$VISIBILITY --source=. --remote=origin --push --description "Private QA daemon for qa.awesometech.com.ng — closed build, no source in image"
  else
    echo "remote already exists: $(git remote get-url origin)"
    git push -u origin main
  fi
  echo "Created https://github.com/$ORG/$REPO_NAME"
  echo "GHCR will be ghcr.io/$ORG/$REPO_NAME:closed (private)"
else
  echo "gh cli not found. Install: brew install gh && gh auth login"
  echo "Then manually:"
  echo "  1. https://github.com/new -> $REPO_NAME -> Private"
  echo "  2. cd /Users/apple/qa-agent && git remote add origin https://github.com/$ORG/$REPO_NAME.git && git push -u origin main"
fi
