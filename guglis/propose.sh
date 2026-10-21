#!/bin/zsh
# Einzelne Guglis Edits als Vorschlag fürs offizielle Repo vorbereiten (guglis/README.md):
# ein neuer Branch vom offiziellen Stand mit nur diesen Commits.
# Aufruf: guglis/propose.sh <branch-name> <commit> [<commit>...]
set -eu

if (( $# < 2 )); then
    print -u2 -- "Aufruf: guglis/propose.sh <branch-name> <commit> [<commit>...]"
    print -u2 -- "Die Commits: git log --oneline origin/main..guglis-edits"
    exit 2
fi
name=$1
shift

cd -- "$(dirname -- "$0")/.."

if [[ -n "$(git status --porcelain)" ]]; then
    print -u2 -- "Ungesicherte Änderungen. Erst committen oder mit git stash -u beiseitelegen."
    exit 1
fi
for commit in "$@"; do
    if git diff-tree --no-commit-id --name-only -r "$commit" | grep -q '^guglis/'; then
        print -u2 -- "$commit ändert guglis/. Das gehört nicht ins offizielle Repo."
        exit 1
    fi
done

start="$(git branch --show-current)"
git fetch origin
git switch -c "$name" origin/main
if ! git cherry-pick "$@"; then
    print -u2 -- ""
    print -u2 -- "Konflikt: Der Edit baut wohl auf einem anderen auf. Lösen und git cherry-pick --continue,"
    print -u2 -- "oder verwerfen: git cherry-pick --abort && git switch $start && git branch -D $name"
    exit 1
fi

print -- ""
print -- "Branch $name vom offiziellen Stand:"
git log --oneline origin/main..HEAD
print -- ""
print -- "Bauen und testen, dann vorschlagen:"
print -- "  git push -u fork $name"
print -- "  gh pr create --repo classicrob/MacioGalaxy --head rzrnr:$name"
print -- "Zurück zu den Guglis Edits: git switch $start"
