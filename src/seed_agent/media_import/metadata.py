"""Conservative TMDB matching and Plex rendering; duration never names an edition."""

import json
import re
import time
import unicodedata
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from seed_agent.media_import.probe import probe as probe


class Mapping(BaseModel):
    media_type: str
    tmdb_id: int = Field(gt=0)
    original_title: str = Field(min_length=1)
    year: int = Field(ge=1880, le=2200)
    localized_title: str | None = None
    english_title: str | None = None
    imdb_id: str | None = None
    season: int | None = Field(default=None, ge=0, le=999)
    episodes: list[int] = Field(default_factory=list)
    edition: str | None = None
    collection_id: int | None = None
    reference_duration: float | None = None
    evidence: str = "operator"
    animation: bool | None = None
    classification_evidence: str | None = None


def component(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f{}]', "_", value).strip(" .")
    if not value or value in {".", ".."}:
        raise ValueError("empty unsafe metadata title")
    return value[:180]


def render(mapping: Mapping, profile, suffix: str) -> Path:
    if mapping.media_type not in {"movie", "tv", "anime"}:
        raise ValueError("unsupported media type")
    title = (
        getattr(mapping, f"{profile.title_policy}_title", None)
        or mapping.original_title
        or mapping.localized_title
        or mapping.english_title
    )
    title = component(title)
    base = f"{title} ({mapping.year})"
    if mapping.media_type == "movie":
        if mapping.edition:
            base += " {edition-" + component(mapping.edition) + "}"
        return (
            Path(profile.target_root)
            / getattr(profile, "_route_subdir", "")
            / base
            / (base + suffix)
        )
    if mapping.season is None or not mapping.episodes:
        raise ValueError("season/episode mapping requires review")
    if any(e < 1 or e > 9999 for e in mapping.episodes):
        raise ValueError("invalid episode number")
    episodes = sorted(set(mapping.episodes))
    if episodes != list(range(episodes[0], episodes[-1] + 1)):
        raise ValueError("non-contiguous episode mapping requires review")
    code = f"S{mapping.season:02d}E{episodes[0]:02d}"
    if len(episodes) > 1:
        code += f"-E{episodes[-1]:02d}"
    return (
        Path(profile.target_root)
        / getattr(profile, "_route_subdir", "")
        / f"{base} {{tmdb-{mapping.tmdb_id}}}"
        / f"Season {mapping.season:02d}"
        / f"{base} - {code}{suffix}"
    )


def identity_normalize(value):
    """Comparable provider titles, without transliteration or fuzzy similarity."""
    result = []
    for character in unicodedata.normalize("NFKC", str(value)).casefold():
        parts = unicodedata.normalize("NFD", character)
        latin = unicodedata.name(parts[0], "").startswith("LATIN")
        result.extend(
            c
            for c in parts
            if c.isalnum() or (unicodedata.category(c).startswith("M") and not latin)
        )
    return "".join(result)


def identity_hints(path, source_root):
    """Keep bilingual and parent titles separate; title numbers are not release years."""
    episode = re.search(r"(?i)S(\d{1,2})E(\d{1,3})(?:[-.]?E(\d{1,3}))?", path.stem)
    queries, year = [], None
    current = path
    for depth in range(3):
        if depth and (current == Path(source_root) or current == current.parent):
            break
        value = unicodedata.normalize("NFKC", path.stem if depth == 0 else current.name)
        technical = re.search(
            r"(?i)(?:^|[ ._\[(-])(?:\d{3,4}p|Blu[ ._-]?Ray|BDRip|WEB[ ._-]?(?:DL|Rip)|"
            r"REMUX|HEVC|H[ .]?26[45]|x26[45])(?:$|[ ._\])-])",
            value,
        )
        head = value[: technical.start()] if technical else value
        years = list(re.finditer(r"(?<!\d)(?:19|20)\d{2}(?!\d)", head))
        release_year = years[-1] if years else None
        year = year or (release_year.group() if release_year else None)
        season = re.search(r"(?i)(?<![A-Za-z0-9])S\d{1,2}(?:E\d{1,3})?", head)
        end = min([m.start() for m in [release_year, season] if m] or [len(head)])
        title = head[:end].strip(" ._-()")
        labels = re.findall(r"\[([^\]]+)\]", title)
        unbracketed = re.sub(r"\[[^\]]+\]", " ", title)
        choices = [unbracketed, *labels]
        for choice in list(choices):
            latin = re.search(r"[A-Za-z]", choice)
            if latin and re.search(r"[\u3400-\u9fff]", choice[: latin.start()]):
                choices.extend([choice[: latin.start()], choice[latin.start() :]])
        for choice in choices:
            choice = re.sub(r"[._]", " ", choice)
            choice = re.sub(r"第[零一二三四五六七八九十百\d]+季", " ", choice)
            choice = re.sub(
                r"\d+分(?:钟)?(?:未删减)?|导演剪辑版|未删减版?|加长版", " ", choice
            ).strip(" -()[]：:")
            variants = re.split(r"(?i)\s+aka\s+", choice)
            # A mixed-script string is only a search hint; its separated aliases
            # must also be independently confirmed by the provider.
            for query in variants:
                query = " ".join(query.split())
                if not query or re.fullmatch(r"(?i)(?:(?:episode|season|s)\s*)?\d+", query):
                    continue
                if query.casefold() in {"movie", "movies", "tv", "anime", "animation"}:
                    continue
                if not re.search(r"[^\W\d_]", query):
                    continue
                if identity_normalize(query) not in {identity_normalize(q) for q in queries}:
                    queries.append(query)
        current = current.parent
    return queries[:4], year, episode


def ancillary_identity(path, source_root):
    """Extras are visible review cases, never primary films or guessed specials."""
    value = unicodedata.normalize("NFKC", path.stem)
    if re.search(r"(?i)(?:^|[ ._-])extras[ ._-]*\d{1,3}(?!\d)", value):
        return True
    years = list(re.finditer(r"(?<!\d)(?:19|20)\d{2}(?!\d)", value))
    tail = value[years[-1].end() :] if years else ""
    if re.search(r"(?i)(?:^|[ ._-])(?:extras|featurette|trailer|sample)(?:$|[ ._-])", tail):
        return True
    current = path.parent
    for _ in range(2):
        if current == Path(source_root) or current == current.parent:
            break
        if current.name.casefold() in {"extras", "featurettes", "trailers", "samples", "花絮"}:
            return True
        current = current.parent
    return False


class Tmdb:
    def __init__(self, token: str):
        self.token = token
        self._identity_cache = {}

    def identify_mixed(self, path, profile):
        if ancillary_identity(path, profile.source_root):
            return None, [{"reason": "ancillary media requires explicit identity and placement"}]
        queries, year, episode = identity_hints(path, profile.source_root)
        if not queries:
            return None, [{"reason": "work title unresolved"}]
        normalized = {identity_normalize(q) for q in queries}

        with httpx.Client(
            base_url="https://api.themoviedb.org/3",
            timeout=20,
            headers={"Authorization": "Bearer " + self.token},
        ) as client:
            deadline = time.monotonic() + 120
            requests = 0

            def get(endpoint, **kwargs):
                nonlocal requests
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise httpx.ReadTimeout("metadata time budget exceeded")
                key = (endpoint, json.dumps(kwargs.get("params", {}), sort_keys=True))
                cached = self._identity_cache.get(key)
                if cached and time.monotonic() - cached[0] < 300:
                    return cached[1]
                if requests >= 32:
                    raise ValueError("metadata request budget exceeded")
                requests += 1
                payload = bytearray()
                with client.stream(
                    "GET", endpoint, timeout=min(20, remaining), **kwargs
                ) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        payload.extend(chunk)
                        if len(payload) > 2_000_000:
                            raise ValueError("metadata response exceeds limit")
                        if time.monotonic() >= deadline:
                            raise httpx.ReadTimeout("metadata time budget exceeded")
                result = json.loads(payload)
                if len(payload) <= 131072:
                    if len(self._identity_cache) >= 128:
                        self._identity_cache.pop(next(iter(self._identity_cache)))
                    self._identity_cache[key] = (time.monotonic(), result)
                return result

            candidates = []
            seen = set()
            for query, kind in [(q, k) for q in queries for k in ["movie", "tv"]]:
                params = {"query": query, "language": profile.locale}
                if kind == "movie" and year:
                    # A known release year keeps common movie titles from losing
                    # the correct result beyond the bounded first search page.
                    params["primary_release_year"] = year
                for item in get("/search/" + kind, params=params).get("results", [])[:10]:
                    if (kind, item["id"]) in seen:
                        continue
                    seen.add((kind, item["id"]))
                    original = item.get("original_title") or item.get("original_name") or ""
                    local = item.get("title") or item.get("name") or ""
                    date = item.get("release_date") or item.get("first_air_date") or ""
                    candidates.append(
                        {
                            "content_type": kind,
                            "tmdb_id": item["id"],
                            "original_title": original,
                            "localized_title": local,
                            "year": date[:4],
                            "exact": bool(
                                normalized
                                & {identity_normalize(original), identity_normalize(local)}
                            )
                            and (not year or date[:4] == year),
                        }
                    )
            # Explicit SxxEyy plus provider-confirmed episode metadata establishes
            # TV identity; a namesake movie is not a competing episode candidate.
            usable = [c for c in candidates if not episode or c["content_type"] == "tv"]

            def provider_names(candidate, *, translations=False):
                kind, identity = candidate["content_type"], candidate["tmdb_id"]
                names = {
                    identity_normalize(candidate["original_title"]),
                    identity_normalize(candidate["localized_title"]),
                }
                for endpoint in ["alternative_titles", *(["translations"] if translations else [])]:
                    try:
                        payload = get(f"/{kind}/{identity}/{endpoint}")
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 404:
                            raise
                        continue
                    if endpoint == "translations":
                        entries = [t.get("data", {}) for t in payload.get("translations", [])]
                        names.update(
                            identity_normalize(t.get("title") or t.get("name") or "")
                            for t in entries
                        )
                    else:
                        names.update(
                            identity_normalize(t.get("title", ""))
                            for t in payload.get("titles", payload.get("results", []))
                        )
                return names - {""}

            exact = [c for c in usable if c["exact"] and c["year"]]
            if not exact:
                possible = []
                for candidate in usable:
                    title_match = bool(
                        normalized
                        & {
                            identity_normalize(candidate["original_title"]),
                            identity_normalize(candidate["localized_title"]),
                        }
                    )
                    year_match = not year or candidate["year"] == year
                    if not year_match and candidate["content_type"] == "tv" and episode:
                        if not title_match:
                            continue
                        try:
                            season = get(f"/tv/{candidate['tmdb_id']}/season/{int(episode[1])}")
                        except httpx.HTTPStatusError as exc:
                            if exc.response.status_code != 404:
                                raise
                            continue  # A namesake without this season is not a provider outage.
                        year_match = str(season.get("air_date") or "")[:4] == year
                        if year_match:
                            candidate["year_basis"] = "provider_season_air_date"
                    if year_match and candidate["year"]:
                        possible.append((candidate, title_match))
                aliases_needed = [(c, match) for c, match in possible if not match]
                if len(aliases_needed) > 8:
                    return None, [*candidates, {"reason": "provider alias budget exceeded"}]
                for candidate, title_match in possible:
                    if not title_match:
                        title_match = bool(normalized & provider_names(candidate))
                        if not title_match:
                            title_match = bool(
                                normalized & provider_names(candidate, translations=True)
                            )
                        if title_match:
                            candidate["match_basis"] = "provider_alternative_title"
                    if title_match:
                        candidate["exact"] = True
                        exact.append(candidate)
            if 1 < len(exact) <= 8 and len(normalized) > 1:
                # Bilingual hints can disambiguate a generic English namesake
                # only when official titles independently corroborate both names.
                support = [
                    (len(normalized & provider_names(c, translations=True)), c) for c in exact
                ]
                best = max(n for n, _ in support)
                corroborated = [c for n, c in support if n == best]
                if best >= 2 and len(corroborated) == 1:
                    exact = corroborated
                    exact[0]["match_basis"] = "provider_multilingual_title_consensus"
            if 1 < len(exact) <= 4 and episode:
                # A specific provider-confirmed episode can distinguish namesake
                # shows; two shows containing that episode remain ambiguous.
                confirmed = []
                for candidate in exact:
                    if candidate["content_type"] != "tv":
                        continue
                    try:
                        detail = get(
                            f"/tv/{candidate['tmdb_id']}/season/{int(episode[1])}"
                            f"/episode/{int(episode[2])}"
                        )
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 404:
                            raise
                        continue
                    if (detail.get("season_number"), detail.get("episode_number")) == (
                        int(episode[1]),
                        int(episode[2]),
                    ):
                        confirmed.append(candidate)
                if len(confirmed) == 1:
                    exact = confirmed
                    exact[0]["match_basis"] = "provider_episode_identity"
            if len(exact) != 1:
                return None, candidates
            choice = exact[0]
            kind = choice["content_type"]
            if (kind == "tv" and not episode) or (kind == "movie" and episode):
                return None, [*candidates, {"reason": "content type/episode hints require review"}]
            numbers = []
            if episode:
                numbers = list(range(int(episode[2]), int(episode[3] or episode[2]) + 1))
                if not numbers or len(numbers) > 10:
                    return None, [
                        *candidates,
                        {"reason": "episode range unresolved or exceeds verification budget"},
                    ]
            data = get(
                f"/{kind}/{choice['tmdb_id']}",
                params={"append_to_response": "external_ids", "language": profile.locale},
            )
            genres = data.get("genres")
            if (
                not isinstance(genres, list)
                or not genres
                or any(not isinstance(g, dict) or not isinstance(g.get("id"), int) for g in genres)
            ):
                return None, [
                    *candidates,
                    {"reason": "animation classification evidence unavailable"},
                ]
            animation = any(g["id"] == 16 for g in genres)
            duration = (data.get("runtime") or 0) * 60 or None
            if kind == "tv":
                verified = []
                for number in numbers:
                    try:
                        detail = get(
                            f"/tv/{choice['tmdb_id']}/season/{int(episode[1])}/episode/{number}"
                        )
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 404:
                            raise
                        return None, [*candidates, {"reason": "episode metadata unavailable"}]
                    if (
                        detail.get("season_number") != int(episode[1])
                        or detail.get("episode_number") != number
                    ):
                        return None, [
                            *candidates,
                            {"reason": "episode metadata did not confirm numbering"},
                        ]
                    verified.append((detail.get("runtime") or 0) * 60)
                duration = sum(verified) or None
        edition = None
        for pattern, label in [
            (r"director.?s[ ._-]*cut", "Director's Cut"),
            (r"\bextended\b", "Extended"),
            (r"\bunrated\b", "Unrated"),
        ]:
            if re.search(pattern, path.stem.replace(".", " "), re.I):
                edition = label
        return Mapping(
            media_type=kind,
            animation=animation,
            classification_evidence="tmdb_genres",
            tmdb_id=choice["tmdb_id"],
            original_title=choice["original_title"],
            localized_title=choice["localized_title"],
            english_title=data.get("title") or data.get("name"),
            year=int(choice["year"]),
            imdb_id=data.get("imdb_id") or data.get("external_ids", {}).get("imdb_id"),
            collection_id=(data.get("belongs_to_collection") or {}).get("id"),
            reference_duration=duration,
            season=int(episode[1]) if episode else None,
            episodes=numbers,
            edition=edition,
            evidence="tmdb_exact_identity_and_type",
        ), candidates

    def identify(self, path: Path, profile) -> tuple[Mapping | None, list[dict]]:
        if getattr(profile, "_mixed", False):
            return self.identify_mixed(path, profile)
        name = path.stem
        episode = re.search(r"(?i)S(\d{1,2})E(\d{1,3})(?:[-.]?E(\d{1,3}))?", name)
        year = re.search(r"(?:19|20)\d{2}", name)
        split = min([m.start() for m in [episode, year] if m] or [len(name)])
        query = re.sub(r"[._]", " ", name[:split]).strip(" -()")
        kind = "movie" if profile.media_type == "movie" else "tv"
        with httpx.Client(
            base_url="https://api.themoviedb.org/3",
            timeout=20,
            headers={"Authorization": f"Bearer {self.token}"},
        ) as client:
            response = client.get(
                f"/search/{kind}", params={"query": query, "language": profile.locale}
            )
            response.raise_for_status()
            results = response.json().get("results", [])[:10]
            candidates = []

            def normalize(t):
                return re.sub(r"[\W_]", "", t).casefold()

            for item in results:
                original = item.get("original_title") or item.get("original_name") or ""
                local = item.get("title") or item.get("name") or ""
                date = item.get("release_date") or item.get("first_air_date") or ""
                exact = normalize(query) in {normalize(original), normalize(local)}
                year_ok = not year or date[:4] == year.group()
                candidates.append(
                    {
                        "tmdb_id": item["id"],
                        "original_title": original,
                        "localized_title": local,
                        "year": date[:4],
                        "exact": exact and year_ok,
                    }
                )
            exact = [c for c in candidates if c["exact"] and c["year"]]
            if len(exact) != 1 or (kind == "tv" and (not episode or int(episode[1]) == 0)):
                return None, candidates
            choice = exact[0]
            details = client.get(
                f"/{kind}/{choice['tmdb_id']}", params={"append_to_response": "external_ids"}
            )
            details.raise_for_status()
            data = details.json()
        edition = None
        for token, label in [
            (r"director.?s[ ._-]*cut", "Director's Cut"),
            (r"\bextended\b", "Extended"),
            (r"\bunrated\b", "Unrated"),
        ]:
            if re.search(token, name.replace(".", " "), re.I):
                edition = label
        return Mapping(
            media_type=profile.media_type,
            tmdb_id=choice["tmdb_id"],
            original_title=choice["original_title"],
            localized_title=choice["localized_title"],
            english_title=data.get("title") or data.get("name"),
            year=int(choice["year"]),
            imdb_id=data.get("imdb_id") or data.get("external_ids", {}).get("imdb_id"),
            collection_id=(data.get("belongs_to_collection") or {}).get("id"),
            reference_duration=(data.get("runtime") or 0) * 60 or None,
            season=int(episode[1]) if episode else None,
            episodes=list(range(int(episode[2]), int(episode[3] or episode[2]) + 1))
            if episode
            else [],
            edition=edition,
            evidence="tmdb_exact_title_year_release",
        ), candidates
