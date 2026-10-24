"""Conservative TMDB matching and Plex rendering; duration never names an edition."""

import json
import re
import subprocess
import time
from pathlib import Path

import httpx
from pydantic import BaseModel, Field


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


def probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,avg_frame_rate:stream_tags=language:"
            "stream_disposition=forced,hearing_impaired",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        timeout=20,
        check=True,
    )
    if len(result.stdout) > 1_000_000:
        raise ValueError("probe output too large")
    data = json.loads(result.stdout)
    duration = float(data.get("format", {}).get("duration", 0))
    if duration <= 0 or not any(s.get("codec_type") == "video" for s in data.get("streams", [])):
        raise ValueError("media probe found no playable video")
    fps = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            a, _, b = stream.get("avg_frame_rate", "0/1").partition("/")
            fps = float(a) / float(b or 1) if float(b or 1) else None
            break
    return {"duration": duration, "fps": fps, "streams": data.get("streams", [])}


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


class Tmdb:
    def __init__(self, token: str):
        self.token = token

    def identify_mixed(self, path, profile):
        episode = re.search(r"(?i)S(\d{1,2})E(\d{1,3})(?:[-.]?E(\d{1,3}))?", path.stem)

        def hints(value):
            year = re.search(r"(?:19|20)\d{2}", value)
            ep = re.search(r"(?i)S\d{1,2}E\d{1,3}", value)
            split = min([m.start() for m in [year, ep] if m] or [len(value)])
            title = re.sub(r"[._]", " ", value[:split]).strip(" -()[]")
            return title, year.group() if year else None

        query, year = hints(path.stem)
        if not query or re.fullmatch(r"(?i)(?:episode\s*)?\d+", query):
            current = path.parent
            for _ in range(2):
                if current == Path(profile.source_root) or current == current.parent:
                    break
                query, parent_year = hints(current.name)
                year = year or parent_year
                if query and not re.fullmatch(r"(?i)(?:season|s)\s*\d+", query):
                    break
                current = current.parent
        if not query or not re.search(r"[^\W\d_]", query):
            return None, [{"reason": "work title unresolved"}]

        def norm(value):
            return re.sub(r"[\W_]", "", str(value)).casefold()

        with httpx.Client(
            base_url="https://api.themoviedb.org/3",
            timeout=20,
            headers={"Authorization": "Bearer " + self.token},
        ) as client:
            deadline = time.monotonic() + 120

            def get(endpoint, **kwargs):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise httpx.ReadTimeout("metadata time budget exceeded")
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
                return json.loads(payload)

            candidates = []
            for kind in ["movie", "tv"]:
                for item in get(
                    "/search/" + kind, params={"query": query, "language": profile.locale}
                ).get("results", [])[:10]:
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
                            "exact": norm(query) in {norm(original), norm(local)}
                            and (not year or date[:4] == year),
                        }
                    )
            exact = [c for c in candidates if c["exact"] and c["year"]]
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
                    detail = get(
                        f"/tv/{choice['tmdb_id']}/season/{int(episode[1])}/episode/{number}"
                    )
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
