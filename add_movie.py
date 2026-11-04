#!/usr/bin/env python3
"""Add movies to your timeline.

Run:  python add_movie.py
Type a movie name (optionally with a year, e.g. "Dune 2021"), pick the correct
match, confirm the date you watched it. When you're done, press Enter on an
empty name and everything is committed and pushed to GitHub.

Uses only the Python standard library. Needs a free TMDB API key (first run asks).
"""
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "movies.json"
CONFIG_FILE = ROOT / "config.json"  # your private key; listed in .gitignore
API = "https://api.themoviedb.org/3"


# ---------- TMDB ----------
def get_key():
    if CONFIG_FILE.exists():
        key = json.loads(CONFIG_FILE.read_text()).get("tmdb_api_key", "").strip()
        if key:
            return key
    print("First run: paste your TMDB API key (themoviedb.org > Settings > API).")
    print("Either the short 'API Key' or the long 'API Read Access Token' works.")
    key = input("Key: ").strip()
    CONFIG_FILE.write_text(json.dumps({"tmdb_api_key": key}, indent=2))
    return key


KEY = None


def tmdb(path, **params):
    headers = {"accept": "application/json"}
    if KEY.startswith("eyJ"):  # long read-access token
        headers["Authorization"] = f"Bearer {KEY}"
    else:
        params["api_key"] = KEY
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            sys.exit("TMDB rejected your key. Delete config.json and run again.")
        raise


def split_title_year(text):
    m = re.match(r"^(.*?)[\s(]+((?:19|20)\d{2})\)?$", text.strip())
    if m and m.group(1).strip():
        return m.group(1).strip(), m.group(2)
    return text.strip(), None


def search(text):
    title, year = split_title_year(text)
    params = {"query": title, "include_adult": "false"}
    if year:
        params["year"] = year
    return tmdb("/search/movie", **params).get("results", [])[:6]


def build_record(tmdb_id):
    d = tmdb(f"/movie/{tmdb_id}", append_to_response="credits,external_ids")
    crew = d.get("credits", {}).get("crew", [])
    cast = d.get("credits", {}).get("cast", [])
    release = d.get("release_date") or ""
    return {
        "tmdb_id": d["id"],
        "imdb_id": (d.get("external_ids") or {}).get("imdb_id") or d.get("imdb_id"),
        "title": d.get("title"),
        "original_title": d.get("original_title"),
        "year": int(release[:4]) if release[:4].isdigit() else None,
        "release_date": release,
        "runtime": d.get("runtime"),
        "genres": [g["name"] for g in d.get("genres", [])],
        "director": [c["name"] for c in crew if c.get("job") == "Director"],
        "cast": [c["name"] for c in cast[:6]],
        "tagline": d.get("tagline") or "",
        "overview": d.get("overview") or "",
        "language": d.get("original_language"),
        "countries": [c["name"] for c in d.get("production_countries", [])],
        "tmdb_rating": round(d["vote_average"], 1) if d.get("vote_count") else None,
        "poster": d.get("poster_path"),
    }


# ---------- local data ----------
def load():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return []


def save(movies):
    movies.sort(key=lambda m: (m["watched_on"], m["added_at"]), reverse=True)
    DATA_FILE.write_text(
        json.dumps(movies, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# ---------- prompts ----------
def pick(results):
    print()
    for i, r in enumerate(results, 1):
        year = (r.get("release_date") or "????")[:4]
        blurb = (r.get("overview") or "").strip().replace("\n", " ")[:90]
        orig = r.get("original_title")
        extra = f" [{orig}]" if orig and orig != r.get("title") else ""
        print(f"  {i}. {r['title']} ({year}){extra}")
        if blurb:
            print(f"     {blurb}...")
    print("  0. None of these / search again")
    while True:
        c = input("Pick one: ").strip()
        if c.isdigit() and 0 <= int(c) <= len(results):
            return None if c == "0" else results[int(c) - 1]["id"]


def ask_date():
    today = date.today().isoformat()
    while True:
        s = input(f"Watched on (YYYY-MM-DD, Enter = {today}): ").strip() or today
        try:
            datetime.strptime(s, "%Y-%m-%d")
            return s
        except ValueError:
            print("  Use the format 2026-11-04")


def ask_my_rating():
    while True:
        s = input("Your rating out of 10 (Enter to skip): ").strip()
        if not s:
            return None
        try:
            v = float(s)
            if 0 <= v <= 10:
                return v
        except ValueError:
            pass
        print("  Enter a number from 0 to 10")


# ---------- git ----------
def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def publish(added):
    if not (ROOT / ".git").exists():
        print("\nThis folder is not a git repo yet, so nothing was pushed.")
        print("Data is saved in movies.json. See the setup steps, then run again.")
        return
    git("add", "movies.json")
    if git("diff", "--cached", "--quiet").returncode == 0:
        print("Nothing new to push.")
        return
    msg = "Add " + ", ".join(added)
    c = git("commit", "-m", msg)
    if c.returncode != 0:
        print("Commit failed:\n" + c.stderr)
        return
    p = git("push")
    if p.returncode != 0:
        print("Push failed (your data is saved and committed locally):\n" + p.stderr)
    else:
        print("\nPushed to GitHub. The page updates in about a minute.")


# ---------- main ----------
def main():
    global KEY
    KEY = get_key()
    movies = load()
    added = []

    while True:
        text = input("\nMovie name (Enter to finish): ").strip()
        if not text:
            break
        results = search(text)
        if not results:
            print("  No results. Try the exact title, or add the year.")
            continue
        tmdb_id = pick(results)
        if tmdb_id is None:
            continue

        existing = [m for m in movies if m["tmdb_id"] == tmdb_id]
        if existing:
            seen = ", ".join(m["watched_on"] for m in existing)
            if input(f"Already logged (watched {seen}). Add as a rewatch? [y/N]: ").lower() != "y":
                continue

        record = build_record(tmdb_id)
        record["watched_on"] = ask_date()
        record["my_rating"] = ask_my_rating()
        record["added_at"] = datetime.now().isoformat(timespec="seconds")
        movies.append(record)
        save(movies)
        added.append(f"{record['title']} ({record['year']})")
        print(f"  Saved: {record['title']} ({record['year']}), "
              f"dir. {', '.join(record['director']) or 'unknown'}, {record['runtime']} min")

    if added:
        publish(added)
    else:
        print("No movies added.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled. Anything already saved is in movies.json.")
