"""Multi-signal viral clip & scene miner (YouTube comments, likes, heatmap, dialogue, FFmpeg action/audio)."""

from __future__ import annotations

import asyncio
import math
import re
import statistics
import subprocess
from pathlib import Path
from typing import Any

from video_mcp.media.ffmpeg_runner import FFmpegRunner

_TS_TOKEN = r"(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)"
_TS_RANGE_RE = re.compile(
    rf"(?<![\d:]){_TS_TOKEN}(?:\s*(?:-|–|—|to|->)\s*{_TS_TOKEN})?(?![\d:])",
    re.IGNORECASE,
)

_VIRAL_COMMENT_WORDS = {
    "goosebumps", "chills", "best part", "best scene", "insane", "crazy", "iconic",
    "legendary", "replay", "favorite", "lmao", "hilarious", "fire", "goat", "clutch",
    "hype", "plot twist", "gta", "trailer", "quote", "dialogue", "line", "scene",
    "epic", "unreal", "hardest", "coldest", "peak", "viral", "replayed", "laughed",
}

_CATCHY_DIALOGUE_WORDS = {
    "trust", "bad luck", "money", "heist", "police", "wasted", "mission", "crazy",
    "insane", "bro", "wtf", "no way", "oh my god", "watch this", "let's go",
    "never", "welcome", "hell", "kill", "dead", "run", "shoot", "car",
    "vice city", "los santos", "lucia", "jason", "franklin", "trevor", "michael",
}

_STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "you", "your", "are", "was",
    "were", "have", "has", "had", "not", "but", "from", "they", "his", "her",
    "she", "him", "its", "our", "out", "can", "will", "just", "like", "what",
    "when", "how", "who", "why", "all", "one", "two", "about", "into", "more",
    "very", "here", "there", "then", "than", "them", "been", "being", "also",
}

_SCENE_PTS_RE = re.compile(r"pts_time:\s*([0-9]+(?:\.[0-9]+)?)")
_EBUR_RE = re.compile(r"t:\s*([0-9]+(?:\.[0-9]+)?)\s+.*?M:\s*(-?[0-9]+(?:\.[0-9]+)?)")


def _hms_to_sec(h: str | None, m: str, s: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s)


def _clamp_window(
    start: float,
    end: float,
    duration_sec: float,
    min_clip_sec: float = 6.0,
    max_clip_sec: float = 25.0,
) -> tuple[float, float]:
    """Clamp `[start, end]` into `[0, duration_sec]` while respecting `[min_clip_sec, max_clip_sec]`."""
    s = max(0.0, float(start))
    e = max(s + 0.5, float(end))

    if e - s > max_clip_sec:
        e = s + max_clip_sec
    if e - s < min_clip_sec:
        e = s + min_clip_sec

    if duration_sec > 0.0:
        if duration_sec <= min_clip_sec:
            return 0.0, round(duration_sec, 2)
        if e > duration_sec:
            shift = e - duration_sec
            s = max(0.0, s - shift)
            e = duration_sec
        if e - s < min_clip_sec:
            s = max(0.0, e - min_clip_sec)

    return round(s, 2), round(e, 2)


def _tokens(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z0-9']+", text.lower())
        if len(w) >= 2 and w not in _STOPWORDS
    }


def _make_hook_text(text: str, fallback: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return fallback[:64]
    if len(cleaned) <= 64:
        return cleaned
    return cleaned[:61].rstrip() + "..."


def parse_comment_timestamps(
    text: str, max_duration: float | None = None
) -> list[tuple[float, float | None]]:
    """Extract `(start_sec, end_sec | None)` timestamp markers and ranges from comment text."""
    results: list[tuple[float, float | None]] = []
    for match in _TS_RANGE_RE.finditer(text or ""):
        h1, m1, s1, h2, m2, s2 = match.groups()
        t1 = float(_hms_to_sec(h1, m1, s1))
        if max_duration is not None and max_duration > 0 and t1 >= max_duration:
            continue
        t2: float | None = None
        if m2 is not None and s2 is not None:
            cand2 = float(_hms_to_sec(h2, m2, s2))
            if cand2 > t1 and (max_duration is None or max_duration <= 0 or cand2 <= max_duration + 2.0):
                t2 = cand2
        results.append((t1, t2))
    return results


def score_comment_virality(text: str, likes: int) -> float:
    """Compute a virality score from comment likes + viral/gaming reaction keywords."""
    lowered = (text or "").lower()
    base = 1.0 + math.log1p(max(0, int(likes))) * 2.5
    kw_hits = sum(1 for kw in _VIRAL_COMMENT_WORDS if kw in lowered)
    quote_bonus = 1.25 if ('"' in lowered or "'" in lowered or "“" in lowered) else 0.0
    exclaim_bonus = min(1.5, lowered.count("!") * 0.4)
    return round(base + kw_hits * 1.4 + quote_bonus + exclaim_bonus, 3)


def mine_comment_moments(
    comments: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    duration_sec: float,
    min_clip_sec: float = 6.0,
    max_clip_sec: float = 25.0,
) -> list[dict[str, Any]]:
    """Mine viral candidate clips from timestamped comments and quoted-dialogue comments."""
    if not comments:
        return []

    timestamp_clusters: list[dict[str, Any]] = []
    quote_candidates: list[dict[str, Any]] = []

    # Pre-build single + 2-segment transcript windows for quote matching
    seg_windows: list[tuple[float, float, str, set[str]]] = []
    for idx, seg in enumerate(segments or []):
        t1 = str(seg.get("text") or "").strip()
        if t1:
            seg_windows.append(
                (float(seg.get("start") or 0.0), float(seg.get("end") or 0.0), t1, _tokens(t1))
            )
        if idx + 1 < len(segments or []):
            nxt = segments[idx + 1]
            t2 = f"{t1} {str(nxt.get('text') or '').strip()}".strip()
            if t2:
                seg_windows.append(
                    (
                        float(seg.get("start") or 0.0),
                        float(nxt.get("end") or 0.0),
                        t2,
                        _tokens(t2),
                    )
                )

    for comment in comments:
        text = str(comment.get("text") or "").strip()
        if not text:
            continue
        likes = int(comment.get("likes") or comment.get("like_count") or 0)
        weight = score_comment_virality(text, likes)
        ts_pairs = parse_comment_timestamps(
            text, max_duration=duration_sec if duration_sec > 0 else None
        )

        if ts_pairs:
            for t_start, t_end in ts_pairs:
                win_start, win_end = _clamp_window(
                    t_start - 3.0,
                    t_end if t_end is not None else (t_start + 12.0),
                    duration_sec,
                    min_clip_sec=min_clip_sec,
                    max_clip_sec=max_clip_sec,
                )
                matched_cluster = next(
                    (c for c in timestamp_clusters if abs(c["anchor"] - t_start) <= 10.0),
                    None,
                )
                entry = {"text": text[:220], "likes": likes}
                if matched_cluster is not None:
                    matched_cluster["score"] += weight
                    matched_cluster["comment_likes"] += likes
                    matched_cluster["comments"].append(entry)
                    matched_cluster["start_sec"] = min(matched_cluster["start_sec"], win_start)
                    matched_cluster["end_sec"] = max(matched_cluster["end_sec"], win_end)
                else:
                    timestamp_clusters.append(
                        {
                            "anchor": t_start,
                            "start_sec": win_start,
                            "end_sec": win_end,
                            "score": weight,
                            "comment_likes": likes,
                            "comments": [entry],
                            "source": "comment_timestamp",
                        }
                    )
            continue

        # No timestamp: match quoted dialogue in comment against transcript
        quoted = re.findall(r'"([^"]{6,})"|“([^”]{6,})”', text)
        quote_str = " ".join(q[0] or q[1] for q in quoted).strip()
        probe_text = quote_str or text
        c_toks = _tokens(probe_text)
        if seg_windows and len(c_toks) >= 3:
            best_win: tuple[float, float, str, float] | None = None
            probe_low = quote_str.lower() if quote_str else ""
            for s_st, s_en, s_txt, s_toks in seg_windows:
                if not s_toks:
                    continue
                shared = len(c_toks & s_toks)
                if probe_low and len(probe_low) >= 8 and probe_low in s_txt.lower():
                    ratio = 1.0
                elif shared >= 3:
                    ratio = shared / max(1, min(len(c_toks), len(s_toks)))
                else:
                    ratio = 0.0
                if ratio >= 0.45 and (best_win is None or ratio > best_win[3]):
                    best_win = (s_st, s_en, s_txt, ratio)

            if best_win is not None:
                win_start, win_end = _clamp_window(
                    best_win[0] - 2.0,
                    best_win[1] + 2.0,
                    duration_sec,
                    min_clip_sec=min_clip_sec,
                    max_clip_sec=max_clip_sec,
                )
                quote_candidates.append(
                    {
                        "start_sec": win_start,
                        "end_sec": win_end,
                        "score": round(weight * 1.15, 3),
                        "comment_likes": likes,
                        "comments": [{"text": text[:220], "likes": likes}],
                        "dialogue_text": best_win[2],
                        "source": "comment_quote",
                    }
                )

    combined: list[dict[str, Any]] = []
    for item in [*timestamp_clusters, *quote_candidates]:
        st, en = _clamp_window(
            item["start_sec"], item["end_sec"], duration_sec, min_clip_sec, max_clip_sec
        )
        top_comments = sorted(item["comments"], key=lambda c: c["likes"], reverse=True)[:3]
        combined.append(
            {
                "start_sec": st,
                "end_sec": en,
                "raw_score": round(float(item["score"]), 3),
                "comment_likes": int(item["comment_likes"]),
                "matching_comments": top_comments,
                "dialogue_text": item.get("dialogue_text", ""),
                "signal": item["source"],
            }
        )
    combined.sort(key=lambda x: x["raw_score"], reverse=True)
    return combined


def mine_heatmap_peaks(
    heatmap: list[dict[str, Any]],
    duration_sec: float,
    min_clip_sec: float = 6.0,
    max_clip_sec: float = 25.0,
) -> list[dict[str, Any]]:
    """Find local replay peaks (>= 0.65 intensity) in YouTube's Most Replayed heatmap."""
    if not heatmap:
        return []
    ordered = sorted(
        (h for h in heatmap if isinstance(h, dict) and "start_time" in h and "value" in h),
        key=lambda h: float(h["start_time"]),
    )
    peaks: list[dict[str, Any]] = []
    for idx, bucket in enumerate(ordered):
        val = float(bucket["value"])
        if val < 0.65:
            continue
        prev_val = float(ordered[idx - 1]["value"]) if idx > 0 else -1.0
        next_val = float(ordered[idx + 1]["value"]) if idx + 1 < len(ordered) else -1.0
        if val >= prev_val and val >= next_val:
            st_raw = float(bucket["start_time"])
            en_raw = float(bucket.get("end_time") or st_raw + 6.0)
            mid = (st_raw + en_raw) / 2.0
            win_s, win_e = _clamp_window(
                mid - 5.0, mid + 7.0, duration_sec, min_clip_sec, max_clip_sec
            )
            if not any(abs(p["mid"] - mid) <= 8.0 for p in peaks):
                peaks.append(
                    {
                        "mid": mid,
                        "start_sec": win_s,
                        "end_sec": win_e,
                        "raw_score": round(val * 25.0, 3),
                        "heatmap_value": round(val, 3),
                        "signal": "most_replayed",
                    }
                )
    peaks.sort(key=lambda p: p["raw_score"], reverse=True)
    return peaks


def mine_catchy_dialogue(
    segments: list[dict[str, Any]],
    query: str | None,
    duration_sec: float,
    min_clip_sec: float = 6.0,
    max_clip_sec: float = 25.0,
) -> list[dict[str, Any]]:
    """Score Whisper dialogue segments & short 2-segment windows for catchy/viral speech."""
    if not segments:
        return []
    query_terms = [q.strip().lower() for q in (query or "").split(",") if q.strip()]
    candidates: list[dict[str, Any]] = []

    windows: list[tuple[float, float, str]] = []
    for idx, seg in enumerate(segments):
        txt = str(seg.get("text") or "").strip()
        if not txt:
            continue
        st = float(seg.get("start") or 0.0)
        en = float(seg.get("end") or st + 2.0)
        windows.append((st, en, txt))
        if idx + 1 < len(segments):
            nxt = segments[idx + 1]
            n_txt = str(nxt.get("text") or "").strip()
            n_en = float(nxt.get("end") or en)
            if n_txt and (n_en - st) <= max_clip_sec:
                windows.append((st, n_en, f"{txt} {n_txt}"))

    for st, en, text in windows:
        low = text.lower()
        words = len(text.split())
        if words < 3:
            continue

        query_hits = sum(low.count(term) for term in query_terms)
        if query_terms and query_hits == 0:
            continue

        punch_score = 4.0 if 4 <= words <= 22 else 2.0
        exclaim_score = min(4.0, text.count("!") * 1.8 + text.count("?") * 1.3)
        hook_hits = sum(1 for kw in _CATCHY_DIALOGUE_WORDS if kw in low)
        raw_score = punch_score + exclaim_score + hook_hits * 2.5 + query_hits * 8.0

        win_s, win_e = _clamp_window(
            st - 1.5, en + 2.0, duration_sec, min_clip_sec=min_clip_sec, max_clip_sec=max_clip_sec
        )
        candidates.append(
            {
                "start_sec": win_s,
                "end_sec": win_e,
                "raw_score": round(raw_score, 3),
                "dialogue_text": text,
                "signal": "catchy_dialogue",
            }
        )

    candidates.sort(key=lambda c: c["raw_score"], reverse=True)
    # Deduplicate heavily overlapping windows
    deduped: list[dict[str, Any]] = []
    for cand in candidates:
        if any(
            abs(cand["start_sec"] - prev["start_sec"]) <= 5.0
            for prev in deduped
        ):
            continue
        deduped.append(cand)
    return deduped


def _run_ffmpeg_stderr(args: list[str], timeout_sec: int) -> str:
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    return proc.stderr or ""


def _cluster_timestamps(
    points: list[tuple[float, float]],
    duration_sec: float,
    min_clip_sec: float,
    max_clip_sec: float,
    bucket_sec: float = 8.0,
) -> list[dict[str, Any]]:
    if not points:
        return []
    ordered = sorted(points, key=lambda p: p[0])
    clusters: list[list[tuple[float, float]]] = [[ordered[0]]]
    for pt in ordered[1:]:
        if pt[0] - clusters[-1][-1][0] <= bucket_sec:
            clusters[-1].append(pt)
        else:
            clusters.append([pt])

    results: list[dict[str, Any]] = []
    for grp in clusters:
        t_first = grp[0][0]
        t_last = grp[-1][0]
        total_weight = sum(w for _, w in grp)
        win_s, win_e = _clamp_window(
            t_first - 2.0, t_last + 6.0, duration_sec, min_clip_sec, max_clip_sec
        )
        results.append(
            {
                "start_sec": win_s,
                "end_sec": win_e,
                "raw_score": round(total_weight, 3),
                "event_count": len(grp),
                "signal": "viral_scene",
            }
        )
    return results


async def detect_viral_scenes(
    runner: FFmpegRunner,
    video_path: Path,
    duration_sec: float,
    has_audio: bool = True,
    min_clip_sec: float = 6.0,
    max_clip_sec: float = 25.0,
) -> list[dict[str, Any]]:
    """Detect high-action visual cuts (`scene`) and loud audio/hype spikes (`ebur128`)."""
    if not video_path.is_file():
        return []
    timeout = min(runner.timeout_sec, 120)
    points: list[tuple[float, float]] = []

    try:
        scene_stderr = await asyncio.to_thread(
            _run_ffmpeg_stderr,
            [
                runner.ffmpeg_bin,
                "-hide_banner",
                "-nostats",
                "-i",
                str(video_path),
                "-vf",
                "fps=2,scale=320:-1,select='gt(scene,0.32)',showinfo",
                "-an",
                "-f",
                "null",
                "-",
            ],
            timeout,
        )
        for match in _SCENE_PTS_RE.finditer(scene_stderr):
            points.append((float(match.group(1)), 5.0))
    except Exception:
        pass

    if has_audio:
        try:
            audio_stderr = await asyncio.to_thread(
                _run_ffmpeg_stderr,
                [
                    runner.ffmpeg_bin,
                    "-hide_banner",
                    "-nostats",
                    "-i",
                    str(video_path),
                    "-vn",
                    "-af",
                    "ebur128=peak=true",
                    "-f",
                    "null",
                    "-",
                ],
                timeout,
            )
            samples = [
                (float(m.group(1)), float(m.group(2)))
                for m in _EBUR_RE.finditer(audio_stderr)
                if math.isfinite(float(m.group(2))) and float(m.group(2)) > -70.0
            ]
            if samples:
                med_lufs = statistics.median(val for _, val in samples)
                threshold = med_lufs + 5.0
                for ts, lufs in samples:
                    if lufs >= threshold:
                        points.append((ts, 4.0 + min(6.0, lufs - threshold)))
        except Exception:
            pass

    scenes = _cluster_timestamps(
        points,
        duration_sec=duration_sec,
        min_clip_sec=min_clip_sec,
        max_clip_sec=max_clip_sec,
    )
    scenes.sort(key=lambda s: s["raw_score"], reverse=True)
    return scenes


def _intervals_close_or_overlap(a: dict[str, Any], b: dict[str, Any], gap_sec: float = 6.0) -> bool:
    return not (a["end_sec"] + gap_sec < b["start_sec"] or b["end_sec"] + gap_sec < a["start_sec"])


def _compute_engagement_grade(view_count: int, like_count: int, comments_analyzed: int) -> str:
    like_ratio = (like_count / view_count) if view_count > 0 else 0.0
    if like_count >= 50_000 or like_ratio >= 0.05 or (comments_analyzed >= 20 and like_count >= 5_000):
        return "S"
    if like_count >= 5_000 or like_ratio >= 0.03 or comments_analyzed >= 10:
        return "A"
    if like_count >= 250 or comments_analyzed >= 1:
        return "B"
    return "C"


def fuse_viral_moments(
    comment_moments: list[dict[str, Any]],
    heatmap_peaks: list[dict[str, Any]],
    dialogue_moments: list[dict[str, Any]],
    scene_moments: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    youtube_meta: dict[str, Any] | None,
    title: str,
    duration_sec: float,
    max_clips: int = 8,
    min_clip_sec: float = 6.0,
    max_clip_sec: float = 25.0,
) -> dict[str, Any]:
    """Fuse multi-signal candidates into ranked, non-overlapping viral moments + engagement stats."""
    all_cands: list[tuple[str, dict[str, Any]]] = []
    for c in comment_moments:
        all_cands.append(("comments", c))
    for h in heatmap_peaks:
        all_cands.append(("heatmap", h))
    for d in dialogue_moments:
        all_cands.append(("dialogue", d))
    for s in scene_moments:
        all_cands.append(("scene", s))

    clusters: list[dict[str, Any]] = []
    for kind, cand in all_cands:
        target = next(
            (cl for cl in clusters if _intervals_close_or_overlap(cl, cand)),
            None,
        )
        if target is None:
            st, en = _clamp_window(
                cand["start_sec"], cand["end_sec"], duration_sec, min_clip_sec, max_clip_sec
            )
            target = {
                "start_sec": st,
                "end_sec": en,
                "signals": [],
                "signal_scores": {},
                "comment_likes": 0,
                "matching_comments": [],
                "dialogue_text": "",
                "heatmap_value": 0.0,
            }
            clusters.append(target)
        else:
            st, en = _clamp_window(
                min(target["start_sec"], cand["start_sec"]),
                max(target["end_sec"], cand["end_sec"]),
                duration_sec,
                min_clip_sec,
                max_clip_sec,
            )
            target["start_sec"] = st
            target["end_sec"] = en

        sig = str(cand.get("signal") or kind)
        if sig not in target["signals"]:
            target["signals"].append(sig)
        target["signal_scores"][kind] = max(
            target["signal_scores"].get(kind, 0.0), float(cand.get("raw_score") or 0.0)
        )
        if cand.get("comment_likes"):
            target["comment_likes"] = max(target["comment_likes"], int(cand["comment_likes"]))
        for mc in cand.get("matching_comments") or []:
            if mc not in target["matching_comments"]:
                target["matching_comments"].append(mc)
        if cand.get("dialogue_text") and not target["dialogue_text"]:
            target["dialogue_text"] = str(cand["dialogue_text"])
        if cand.get("heatmap_value"):
            target["heatmap_value"] = max(target["heatmap_value"], float(cand["heatmap_value"]))

    # Attach nearest transcript dialogue to moments discovered solely from comments/heatmap/scene
    for cl in clusters:
        if not cl["dialogue_text"] and segments:
            overlapping = [
                str(s.get("text") or "").strip()
                for s in segments
                if float(s.get("end") or 0.0) >= cl["start_sec"]
                and float(s.get("start") or 0.0) <= cl["end_sec"]
            ]
            cl["dialogue_text"] = " ".join(t for t in overlapping if t).strip()

    # Normalize scores across clusters -> 0..100
    weighted_totals: list[float] = []
    for cl in clusters:
        ss = cl["signal_scores"]
        total = (
            ss.get("comments", 0.0) * 1.8
            + ss.get("heatmap", 0.0) * 1.1
            + ss.get("dialogue", 0.0) * 1.2
            + ss.get("scene", 0.0) * 0.9
            + (len(ss) - 1) * 8.0
        )
        cl["_raw_total"] = total
        weighted_totals.append(total)

    max_total = max(weighted_totals) if weighted_totals else 1.0
    if max_total <= 0:
        max_total = 1.0

    signal_labels = {
        "comment_timestamp": "Comment Timestamp",
        "comment_quote": "Quoted in Comments",
        "most_replayed": "Most Replayed",
        "catchy_dialogue": "Catchy Dialogue",
        "viral_scene": "High-Action Scene",
    }

    moments: list[dict[str, Any]] = []
    for cl in sorted(clusters, key=lambda c: c["_raw_total"], reverse=True)[:max_clips]:
        distinct = len(cl["signal_scores"])
        norm_score = min(99, max(25, round(30.0 + (cl["_raw_total"] / max_total) * 69.0)))
        if distinct >= 2:
            category = "multi_signal"
        elif "comments" in cl["signal_scores"]:
            category = "comment_viral"
        elif "heatmap" in cl["signal_scores"]:
            category = "most_replayed"
        elif "dialogue" in cl["signal_scores"]:
            category = "catchy_dialogue"
        else:
            category = "viral_scene"

        badges = [signal_labels.get(s, s) for s in cl["signals"]]
        top_comments = sorted(
            cl["matching_comments"], key=lambda c: int(c.get("likes") or 0), reverse=True
        )[:3]
        dialogue = cl["dialogue_text"]
        hook = _make_hook_text(
            dialogue or (top_comments[0]["text"] if top_comments else ""),
            fallback=f"{title} Highlight",
        )

        reasons: list[str] = []
        if top_comments:
            reasons.append(f"{cl['comment_likes']:,} comment likes")
        if cl["heatmap_value"] > 0:
            reasons.append(f"replay intensity {int(cl['heatmap_value'] * 100)}%")
        if dialogue:
            reasons.append("catchy dialogue")
        if "scene" in cl["signal_scores"]:
            reasons.append("high-action cut / audio spike")

        dur = round(max(0.1, cl["end_sec"] - cl["start_sec"]), 2)
        moments.append(
            {
                "start_sec": cl["start_sec"],
                "end_sec": cl["end_sec"],
                "duration_sec": dur,
                "viral_score": norm_score,
                "category": category,
                "signals": badges,
                "dialogue_text": dialogue,
                "hook_text": hook,
                "title_suggestion": f"{hook[:48]} | Viral Clip",
                "comment_likes": cl["comment_likes"],
                "matching_comments": top_comments,
                "reason": " + ".join(reasons) if reasons else "Peak viral window",
            }
        )

    yt = youtube_meta or {}
    view_count = int(yt.get("view_count") or 0)
    like_count = int(yt.get("like_count") or 0)
    comment_count = int(yt.get("comment_count") or 0)
    like_ratio = float(yt.get("like_ratio") or (round(like_count / view_count, 5) if view_count > 0 else 0.0))
    yt_comments = list(yt.get("comments") or [])

    engagement = {
        "title": str(yt.get("title") or title),
        "uploader": yt.get("uploader"),
        "view_count": view_count,
        "like_count": like_count,
        "comment_count": comment_count,
        "like_ratio": like_ratio,
        "comments_analyzed": len(yt_comments),
        "heatmap_peaks": len(heatmap_peaks),
        "engagement_grade": _compute_engagement_grade(view_count, like_count, len(yt_comments)),
    }

    return {
        "video_engagement": engagement,
        "top_comments": yt_comments[:10],
        "moment_count": len(moments),
        "moments": moments,
    }
