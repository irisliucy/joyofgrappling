"""The Loop Protocol (see programs.md). Runs synchronously inside a
FastAPI background task -- one call per query_id.
"""
from datetime import datetime, timezone

from . import authority, extraction, node_category, query_expansion, ranking, store, transcript
from .schemas import (
    TRANSITION_TYPE_STAGE, ContestedDetail, GraphEdge, GraphNode, InsightSummary, ReapConfig,
    ReapOutput, SourceRef, TechniqueGraph,
)
from .youtube_search import SourceUnavailable, search


def run(query_id: str, cfg: ReapConfig):
    try:
        _run_loop(query_id, cfg)
    except Exception as e:
        store.update_query_status(query_id, "error", str(e))


def _run_loop(query_id: str, cfg: ReapConfig):
    store.update_query_status(query_id, "running", "iteration 1")

    processed_ids = set()
    searched_queries = set()  # avoid re-spending quota on an exact repeat within this run
    next_query = cfg.query
    iteration = 1
    prior_edge_count = 0
    low_novelty_streak = 0

    while True:
        store.log(query_id, iteration, "expand_query", "start")
        expanded = query_expansion.expand_query(next_query, cfg.target_player)
        new_queries = [q for q in expanded if q not in searched_queries]
        skipped = len(expanded) - len(new_queries)
        store.log(
            query_id, iteration, "expand_query", "done",
            {"query_count": len(expanded), "already_searched_skipped": skipped},
        )

        # 2. SEARCH
        store.update_query_status(query_id, "running", f"iteration {iteration}: searching")
        all_videos = []
        seen_ids = set()
        for q in new_queries:
            searched_queries.add(q)
            try:
                results = search(q, source="youtube", max_results=5)
            except SourceUnavailable as e:
                store.log(query_id, iteration, "search", "source_unavailable", {"error": str(e)})
                continue
            for v in results:
                if v.video_id not in seen_ids:
                    seen_ids.add(v.video_id)
                    all_videos.append(v)
        store.log(
            query_id, iteration, "search", "done",
            {"raw_result_count": len(all_videos), "deduped_count": len(seen_ids)},
        )

        # 3. RANK
        ranked = ranking.rank_videos(all_videos, cfg.query, cfg.top_videos_per_iteration)
        ranked = [(v, s) for v, s in ranked if v.video_id not in processed_ids]
        store.log(query_id, iteration, "rank", "done", {"ranked_video_ids": [v.video_id for v, _ in ranked]})

        if not ranked:
            store.update_query_status(query_id, "done", f"No new videos found in iteration {iteration}.")
            break

        new_nodes_before = _current_node_names(query_id)
        edges_before = len(store.all_edges(query_id))

        for video, _score in ranked:
            processed_ids.add(video.video_id)

            # 4. SCORE SOURCES
            source_score = authority.score_source(video.channel_id, video)
            store.log(query_id, iteration, "score_sources", "done", {"video_id": video.video_id, "tier": source_score.authority_tier})

            # 5. FETCH CAPTIONS
            store.update_query_status(query_id, "running", f"iteration {iteration}: {video.title}")
            caption = transcript.fetch_captions(video.video_id)
            store.save_video(query_id, video, source_score, caption_available=caption is not None)

            if caption is None:
                store.log(query_id, iteration, "fetch_captions", "caption_unavailable", {"video_id": video.video_id})
                continue

            # 6. EXTRACT
            windows = extraction.chunk_segments(caption.segments)
            position_context = ""
            consecutive_empty = 0
            extracted_count = 0
            needs_review_count = 0

            for window in windows:
                if consecutive_empty >= 3:
                    store.log(query_id, iteration, "extract", "sparse_content", {"video_id": video.video_id})
                    break
                try:
                    raw_extractions = extraction.extract_techniques(
                        window, position_context, source_score.authority_tier
                    )
                except Exception as e:
                    store.log(query_id, iteration, "extract", "error", {"video_id": video.video_id, "error": str(e)})
                    continue

                if not raw_extractions:
                    consecutive_empty += 1
                    continue
                consecutive_empty = 0

                for item in raw_extractions:
                    position_context = item.to_position or position_context
                    extracted_count += 1
                    # 7. STORE
                    if item.needs_review:
                        needs_review_count += 1
                        store.queue_for_review(query_id, video.video_id, item)
                        continue
                    store.store_insight(query_id, item, source_score, video)

            store.log(
                query_id, iteration, "extract_store", "done",
                {"video_id": video.video_id, "extraction_count": extracted_count, "needs_review_count": needs_review_count},
            )

        # 8. CHECK TERMINATION
        edges_after = len(store.all_edges(query_id))
        new_edges_this_iteration = edges_after - edges_before
        nodes_after = _current_node_names(query_id)
        new_nodes_this_iteration = len(nodes_after - new_nodes_before)
        novelty_rate = new_edges_this_iteration / edges_after if edges_after else 0.0

        decision_continue, reason = _should_continue(
            iteration, cfg, edges_after, novelty_rate, low_novelty_streak, len(ranked), processed_ids
        )
        if novelty_rate < cfg.novelty_threshold:
            low_novelty_streak += 1
        else:
            low_novelty_streak = 0

        store.log(
            query_id, iteration, "check_termination", "done",
            {"novelty_rate": novelty_rate, "should_continue": decision_continue, "reason": reason},
        )

        if not decision_continue:
            store.update_query_status(query_id, "finalizing", reason)
            break

        # 9. REFINE QUERY
        new_node_names = list(nodes_after - new_nodes_before)
        next_query = new_node_names[0] if new_node_names else cfg.query
        store.log(query_id, iteration, "refine_query", "done", {"next_query": next_query})

        iteration += 1
        prior_edge_count = edges_after

    _finalize(query_id, cfg, iteration, len(processed_ids))


def _current_node_names(query_id: str) -> set[str]:
    names = set()
    for edge in store.all_edges(query_id):
        names.add(edge.from_position)
        names.add(edge.to_position)
    return names


def _should_continue(iteration, cfg: ReapConfig, edge_count, novelty_rate, low_novelty_streak, ranked_count, processed_ids):
    if iteration >= cfg.max_iterations:
        return False, f"reached max_iterations ({cfg.max_iterations})"
    if novelty_rate < cfg.novelty_threshold and low_novelty_streak >= 1:
        return False, "novelty_rate below threshold for two consecutive iterations"
    if edge_count >= cfg.max_edges:
        return False, f"reached max_edges ({cfg.max_edges})"
    if ranked_count == 0:
        return False, "no new videos left to process"
    return True, "continuing"


def _finalize(query_id: str, cfg: ReapConfig, iteration_count: int, videos_processed: int):
    edges = store.all_edges(query_id)

    node_names = {}
    for edge in edges:
        for name in (edge.from_position, edge.to_position):
            key = store.normalize_name(name)
            if key not in node_names:
                node_names[key] = {"label": name, "mention_count": 0, "source_count": 0}
            node_names[key]["mention_count"] += 1

    for edge in edges:
        for name in (edge.from_position, edge.to_position):
            key = store.normalize_name(name)
            node_names[key]["source_count"] = max(node_names[key]["source_count"], edge.source_count)

    graph_nodes = [
        GraphNode(
            id=key,
            label=data["label"],
            category=node_category.classify_category(data["label"]),
            mention_count=data["mention_count"],
            source_count=data["source_count"],
        )
        for key, data in node_names.items()
    ]

    graph_edges = [
        GraphEdge(
            id=edge.id,
            **{"from": store.normalize_name(edge.from_position)},
            to=store.normalize_name(edge.to_position),
            transition_type=edge.transition_type,
            stage=TRANSITION_TYPE_STAGE[edge.transition_type],
            weight=edge.source_count,
            confidence_label=edge.confidence_label,
            has_competition_footage=edge.has_competition_footage,
        )
        for edge in edges
    ]

    insights = [
        InsightSummary(
            text=_insight_text(edge),
            confidence_label=edge.confidence_label,
            source_count=edge.source_count,
            supporting_video_ids=[s.video_id for s in edge.sources],
            sources=edge.sources,
            graph_edge_id=edge.id,
            from_node_id=store.normalize_name(edge.from_position),
            to_node_id=store.normalize_name(edge.to_position),
        )
        for edge in sorted(edges, key=lambda e: e.source_count, reverse=True)
    ]

    contested = [
        ContestedDetail(
            technique=f"{e.from_position} -> {e.to_position}",
            point_of_disagreement=e.contested_detail or "unspecified",
            side_a=e.sources[0].raw_quote if e.sources else "",
            side_b=e.sources[-1].raw_quote if len(e.sources) > 1 else "",
            side_a_sources=[e.sources[0].video_id] if e.sources else [],
            side_b_sources=[e.sources[-1].video_id] if len(e.sources) > 1 else [],
        )
        for e in edges
        if e.contested
    ]

    sources_used = {s.video_id: s for edge in edges for s in edge.sources}.values()

    output = ReapOutput(
        query=cfg.query,
        generated_at=datetime.now(timezone.utc).isoformat(),
        iteration_count=iteration_count,
        videos_processed=videos_processed,
        graph=TechniqueGraph(nodes=graph_nodes, edges=graph_edges),
        insights=insights,
        contested=contested,
        sources_used=list(sources_used),
    )

    store.save_output(query_id, output.model_dump_json(by_alias=True))
    store.update_query_status(query_id, "done", f"Processed {videos_processed} videos over {iteration_count} iterations.")


def _insight_text(edge) -> str:
    condition = f" when {edge.conditions[0]}" if edge.conditions else ""
    return f"{edge.from_position} -> {edge.to_position} ({edge.transition_type}){condition}."
